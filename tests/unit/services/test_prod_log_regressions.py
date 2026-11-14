"""生产日志里反复出现的三个真实缺陷的回归测试。

这些不是推测出来的问题，是从 NAS 上运行的日志里统计出来的高频错误：

1. `validation error for MediaInfo`（单批 200 次任务失败）
   TMDB 对缺失的 external_ids 显式返回 null，`dict.get(key, default)` 的默认值
   只在键不存在时生效，于是 None 被写进 `imdb_id: str`，pydantic 校验失败。

2. `'str' object has no attribute 'exists'`（58 次）
   转移历史里的 DST_BACKEND 是 id 字符串，被当成后端对象调用 `.exists()`。
   后果不止是报错：远端后端的文件永远被判为不存在 → 反复重复转移。

3. `[Filter]过滤规则出现严重错误 expected string or bytes-like object, got 'NoneType'`
   rev_string 为空时把 None 直接交给 re.search，整条过滤规则失效。
"""

from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from app.domain.media_types import ProviderMediaType
from app.indexer.core.filter_engine import IndexerFilterEngine
from app.media.models import MediaInfo


def _patch_categories():
    """set_provider_data 会读分类规则表；单元测试里用空规则隔离。"""
    adapter = MagicMock()
    adapter.get_all.return_value = []
    return patch("app.media.models.CategoryConfigRepositoryAdapter", return_value=adapter)


class TestExternalIdsNoneIsNormalized:
    """缺陷 1：external_ids 里的 null 不能写进 str 字段。"""

    def test_imdb_id_null_becomes_empty_string(self):
        info = MediaInfo(type=ProviderMediaType.SERIES, title="Some Show")
        payload = {
            "id": 12345,
            "media_type": ProviderMediaType.SERIES,
            "name": "Some Show",
            "genre_ids": [16],
            # TMDB 对没有 IMDb 号的作品返回的就是显式 null
            "external_ids": {"imdb_id": None, "tvdb_id": None},
        }

        with _patch_categories():
            info.set_provider_data(payload)

        assert info.imdb_id == ""
        assert info.tvdb_id == 0

    def test_imdb_id_missing_key_still_works(self):
        info = MediaInfo(type=ProviderMediaType.SERIES, title="Some Show")
        payload = {
            "id": 12346,
            "media_type": ProviderMediaType.SERIES,
            "name": "Some Show",
            "genre_ids": [16],
            "external_ids": {},
        }

        with _patch_categories():
            info.set_provider_data(payload)

        assert info.imdb_id == ""
        assert info.tvdb_id == 0

    def test_real_ids_are_kept(self):
        info = MediaInfo(type=ProviderMediaType.SERIES, title="Some Show")
        payload = {
            "id": 12347,
            "media_type": ProviderMediaType.SERIES,
            "name": "Some Show",
            "genre_ids": [16],
            "external_ids": {"imdb_id": "tt1234567", "tvdb_id": 999},
        }

        with _patch_categories():
            info.set_provider_data(payload)

        assert info.imdb_id == "tt1234567"
        assert info.tvdb_id == 999


class TestBackendIdStringAccepted:
    """缺陷 2：存在性检查必须同时接受后端对象与后端 id 字符串。"""

    def test_backend_id_string_is_resolved_not_crashing(self, tmp_path):
        from app.services.transfer.filetransfer_service import FileTransferService

        svc = FileTransferService.__new__(FileTransferService)

        class _Resolver:
            def resolve_backend_by_id(self, backend_id):
                return None  # 后端不存在 → 按本地处理

        svc._path_resolver = cast(Any, _Resolver())
        existing = tmp_path / "a.mkv"
        existing.write_text("x", encoding="utf-8")

        # 传 id 字符串不能抛异常
        assert svc._target_exists(str(existing), "local") is True
        assert svc._target_exists(str(existing), "7") is True
        assert svc._target_exists(str(tmp_path / "missing.mkv"), "7") is False

    def test_backend_object_is_used(self, tmp_path):
        from app.services.transfer.filetransfer_service import FileTransferService

        svc = FileTransferService.__new__(FileTransferService)
        svc._path_resolver = cast(Any, object())
        existing = tmp_path / "b.mkv"
        existing.write_text("x", encoding="utf-8")

        class _Backend:
            def __init__(self, present):
                self._present = present

            def exists(self, path):
                return self._present

        assert svc._target_exists(str(existing), _Backend(True)) is True
        assert svc._target_exists(str(existing), _Backend(False)) is False


class TestFilterNullRevString:
    """缺陷 3：rev_string 为空时过滤规则不能崩。"""

    @staticmethod
    def _info(rev_string):
        info = MediaInfo(type=ProviderMediaType.SERIES, title="某剧")
        info.rev_string = rev_string
        info.org_string = "some.release.name"
        return info

    @pytest.mark.parametrize("rev", [None, ""])
    def test_null_rev_string_does_not_raise(self, rev):
        info = self._info(rev)
        filters = [
            {
                "include": ["1080p"],
                "exclude": [],
                "size": "",
                "free": "",
                "pri": 1,
                "original_language": "",
            }
        ]

        # 不能抛 TypeError；规则不匹配即可
        matched, _order, _name = IndexerFilterEngine.check_rules(
            info, {"name": "r"}, filters
        )
        assert matched is False

    def test_normal_rev_string_still_matches(self):
        info = self._info("Some.Show.1080p.WEB-DL.mkv")
        filters = [{"include": ["1080p"], "exclude": [], "pri": 1}]

        matched, _order, _name = IndexerFilterEngine.check_rules(
            info, {"name": "r"}, filters
        )
        assert matched is True
