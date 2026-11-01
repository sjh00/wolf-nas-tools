"""长程记忆用户命名空间测试。"""

from unittest.mock import MagicMock

from app.agent.agents.memory.long_term import SemanticMemory
from app.agent.rag.models import Chunk, ScoredChunk


def test_semantic_memory_uses_user_namespace():
    store = MagicMock()
    store.hybrid_search.return_value = []
    store.list_by_source_prefix.return_value = []
    embedding = MagicMock()
    embedding.embed_query.return_value = [0.1, 0.2]
    memory = SemanticMemory(store=store, embedding=embedding)

    memory.add_memory("u1", "偏好 4K")
    store.upsert.assert_called_once()
    assert store.upsert.call_args.args[0] == "user_memory:u1"

    hit = ScoredChunk(
        chunk=Chunk(id="m", text="偏好 4K", namespace="user_memory:u1", source="s", metadata={"user_id": "u1"}),
        score=1.0,
    )
    store.hybrid_search.return_value = [hit]
    assert memory.search("u1", "4K") == ["偏好 4K"]
    assert store.hybrid_search.call_args.args[2] == "user_memory:u1"

    memory.forget("u1", "偏好 4K")
    store.delete_by_source.assert_called_once_with("user_memory:u1", "s")
