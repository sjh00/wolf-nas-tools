"""LanceDB 可选实现测试。"""

import pytest

from app.agent.rag.factory import _cpu_supports_avx2
from app.agent.rag.lancedb_store import LanceDBStore
from app.agent.rag.models import Chunk

lancedb = pytest.importorskip("lancedb")


@pytest.mark.skipif(not _cpu_supports_avx2(), reason="当前 CPU 不支持 AVX2")
def test_lancedb_text_only_and_quoted_source(tmp_path):
    store = LanceDBStore(str(tmp_path / "lance"))
    chunk = Chunk(id="a", text="如何配置下载器", namespace="faq", source="s'1")
    assert store.upsert("faq", [chunk], [None]) == 1
    assert store.hybrid_search("下载器", None, "faq", 5)
    assert store.delete_by_source("faq", "s'1") == 1
    assert store.count("faq") == 0
