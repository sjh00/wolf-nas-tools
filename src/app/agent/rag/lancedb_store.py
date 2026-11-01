"""LanceDB 向量库 — 可选加速实现（原生混合检索 + RRF 重排）

注意：lancedb 预编译原生库要求 AVX2 CPU，不支持的机器 import 即 SIGILL。
本模块只允许被 vector_store.create_vector_store 在通过 CPU 探测后惰性加载，
严禁被其他模块直接 import。
"""

import json
from pathlib import Path

import lancedb
import pyarrow as pa
from lancedb.index import FTS
from lancedb.rerankers import RRFReranker

import log
from app.agent.rag.models import Chunk, ScoredChunk
from app.agent.rag.vector_store import VectorStore


class LanceDBStore(VectorStore):
    """LanceDB 可选加速（原生混合检索 + RRF 重排，需 AVX2 CPU）"""

    def __init__(self, path: str, dimension: int = 0):
        Path(path).mkdir(parents=True, exist_ok=True)
        self._db = lancedb.connect(path)
        self._dimension = dimension

    def _table_names(self) -> list[str]:
        # lancedb 0.40 起 table_names() 已弃用，官方替代为 list_tables()。
        return list(self._db.list_tables().tables)

    def _table(self, namespace: str, dimension: int):
        name = f"kb_{namespace}"
        if name in self._table_names():
            return self._db.open_table(name)
        schema = pa.schema(
            [
                ("id", pa.string()),
                ("text", pa.string()),
                ("source", pa.string()),
                ("metadata", pa.string()),
                ("vector", pa.list_(pa.float32(), dimension)),
            ]
        )
        return self._db.create_table(name, schema=schema)

    def upsert(self, namespace: str, chunks: list[Chunk], vectors: list[list[float] | None]) -> int:
        if not chunks:
            return 0
        if len(chunks) != len(vectors):
            raise ValueError(f"chunks({len(chunks)}) 与 vectors({len(vectors)}) 数量不一致")
        first_vector = next((v for v in vectors if v is not None), None)
        dimension = len(first_vector) if first_vector is not None else self._dimension or 1
        table = self._table(namespace, dimension)
        rows = [
            {
                "id": c.id,
                "text": c.text,
                "source": c.source,
                "metadata": json.dumps(c.metadata, ensure_ascii=False),
                "vector": v,
            }
            for c, v in zip(chunks, vectors, strict=True)
        ]
        table.merge_insert("id").when_matched_update_all().when_not_matched_insert_all().execute(rows)
        try:
            table.create_index("text", config=FTS(), replace=True)
        except Exception as e:
            log.warn(f"[LanceDBStore]FTS 索引创建失败: {e}")
        return len(chunks)

    def delete_by_source(self, namespace: str, source: str) -> int:
        name = f"kb_{namespace}"
        if name not in self._table_names():
            return 0
        table = self._db.open_table(name)
        before = table.count_rows()
        safe_source = str(source).replace("'", "''")
        table.delete(f"source = '{safe_source}'")
        return before - table.count_rows()

    def hybrid_search(
        self, query: str, vector: list[float] | None, namespace: str | None, top_k: int
    ) -> list[ScoredChunk]:
        table_names = self._table_names()
        namespaces = [namespace] if namespace else [n[3:] for n in table_names if n.startswith("kb_")]
        results: list[ScoredChunk] = []
        for ns in namespaces:
            name = f"kb_{ns}"
            if name not in table_names:
                continue
            table = self._db.open_table(name)
            try:
                if vector is None:
                    rows = table.search(query, query_type="fts").limit(top_k).to_list()
                    if not rows:
                        rows = [
                            row for row in table.to_arrow().to_pylist() if str(query) in str(row.get("text") or "")
                        ][:top_k]
                else:
                    rows = (
                        table.search(query_type="hybrid")
                        .vector(vector)
                        .text(query)
                        .rerank(RRFReranker())
                        .limit(top_k)
                        .to_list()
                    )
            except Exception as e:
                if vector is None:
                    log.warn(f"[LanceDBStore]全文检索失败: {e}")
                    continue
                log.warn(f"[LanceDBStore]混合检索失败，退回纯向量: {e}")
                rows = table.search(vector).limit(top_k).to_list()
            for r in rows:
                chunk = Chunk(
                    id=r["id"],
                    text=r["text"],
                    namespace=ns,
                    source=r["source"],
                    metadata=json.loads(r.get("metadata") or "{}"),
                )
                score = r.get("_relevance_score", r.get("_score", 0.0))
                results.append(ScoredChunk(chunk=chunk, score=float(score)))
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_k]

    def list_by_source_prefix(self, namespace: str, prefix: str, limit: int = 50) -> list[dict]:
        name = f"kb_{namespace}"
        if name not in self._table_names():
            return []
        table = self._db.open_table(name)
        try:
            # 过滤下推到 LanceDB 扫描，避免全表物化；limit 在存储层生效
            safe_prefix = str(prefix).replace("'", "''")
            scan = table.to_lance().scan(filter=f"source LIKE '{safe_prefix}%'", limit=limit)
            rows = scan.to_arrow()
        except Exception as e:
            log.warn(f"[LanceDBStore]过滤扫描失败，回退全量列举: {e}")
            try:
                rows = table.to_arrow()
            except Exception as e2:
                log.warn(f"[LanceDBStore]列举失败: {e2}")
                return []
        result = []
        for record in rows.to_pylist():
            src = str(record.get("source", ""))
            if src.startswith(prefix):
                result.append({"id": str(record.get("id", "")), "source": src, "text": str(record.get("text", ""))})
        return result[:limit]

    def count(self, namespace: str | None = None) -> int:
        table_names = self._table_names()
        names = [f"kb_{namespace}"] if namespace else [n for n in table_names if n.startswith("kb_")]
        return sum(self._db.open_table(n).count_rows() for n in names if n in table_names)
