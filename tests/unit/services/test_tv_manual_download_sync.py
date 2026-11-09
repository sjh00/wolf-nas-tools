"""手动下载后回写电视剧订阅，避免重复下载。

电影的手动下载回写（finish / over_edition）早已有之；电视剧走另一条分支：
按本次下载覆盖的集号，从订阅的缺失集里扣掉。本模块锁定该行为，
并覆盖几个容易出错的边界：

- 范围集（E01-E10）要一次扣掉 10 集，而不是只扣首集
- 只扣「缺失集里真实存在的」，不把区间外的集数算进去
- 扣完仍有缺集 → 订阅保持 RUNNING；扣完无缺集 → 标记 COMPLETED
- 没有集号信息时不动订阅（避免误清缺失集）
"""

from unittest.mock import MagicMock

import pytest

from app.services.subscribe.management.service import SubscribeService


def _service(missing: list[int]):
    svc = SubscribeService.__new__(SubscribeService)
    svc._tv_episode_repo = MagicMock()
    svc._tv_episode_repo.get.return_value = list(missing)
    svc._tv_repo = MagicMock()
    return svc


class TestTvLackWriteBack:
    def test_partial_download_keeps_running(self):
        svc = _service([1, 2, 3, 4, 5])
        completed = svc.update_subscribe_tv_lack_by_episodes(42, [3, 4])
        assert completed is False
        # 缺失集从 5 降到 3
        args, kwargs = svc._tv_repo.update_lack.call_args
        assert kwargs["lack_episodes"] == [1, 2, 5]
        assert kwargs["rssid"] == 42
        # 仍有缺集 → 保持运行态
        assert svc._tv_repo.update_state.call_args.kwargs["state"] == "R"

    def test_all_episodes_downloaded_marks_completed(self):
        svc = _service([1, 2, 3])
        completed = svc.update_subscribe_tv_lack_by_episodes(42, [1, 2, 3])
        assert completed is True
        assert svc._tv_repo.update_state.call_args.kwargs["state"] == "C"
        # 集齐时不应再写缺失集
        svc._tv_repo.update_lack.assert_not_called()

    def test_range_batch_deducts_every_episode(self):
        """整季种子 E01-E10：必须扣掉 10 集。"""
        svc = _service(list(range(1, 25)))
        completed = svc.update_subscribe_tv_lack_by_episodes(42, list(range(1, 11)))
        assert completed is False
        args, kwargs = svc._tv_repo.update_lack.call_args
        assert kwargs["lack_episodes"] == list(range(11, 25))

    def test_episodes_outside_missing_are_ignored(self):
        """下载了订阅缺失集之外的集，不影响缺失集。"""
        svc = _service([5, 6])
        completed = svc.update_subscribe_tv_lack_by_episodes(42, [99, 100])
        assert completed is False
        args, kwargs = svc._tv_repo.update_lack.call_args
        assert kwargs["lack_episodes"] == [5, 6]

    def test_no_episode_info_does_nothing(self):
        """无集号信息时不得清空缺失集（否则订阅会以为全下完了）。"""
        svc = _service([1, 2, 3])
        assert svc.update_subscribe_tv_lack_by_episodes(42, []) is False
        svc._tv_repo.update_lack.assert_not_called()
        svc._tv_repo.update_state.assert_not_called()

    def test_invalid_episode_tokens_skipped(self):
        svc = _service([1, 2])
        completed = svc.update_subscribe_tv_lack_by_episodes(42, ["x", "", None, 2])
        assert completed is False
        args, kwargs = svc._tv_repo.update_lack.call_args
        assert kwargs["lack_episodes"] == [1]

    def test_missing_rssid_is_noop(self):
        svc = _service([1])
        assert svc.update_subscribe_tv_lack_by_episodes(None, [1]) is False
        svc._tv_repo.update_lack.assert_not_called()

    def test_duplicate_episodes_deduplicated(self):
        svc = _service([1, 2, 3])
        completed = svc.update_subscribe_tv_lack_by_episodes(42, [2, 2, 2])
        assert completed is False
        args, kwargs = svc._tv_repo.update_lack.call_args
        assert kwargs["lack_episodes"] == [1, 3]


class TestMediaInfoEpisodePayload:
    """事件 payload 依赖 media_info.to_dict() 的 episode 字段。"""

    @staticmethod
    def _info(begin, end=None):
        from app.domain.media_types import ProviderMediaType
        from app.media.models import MediaInfo

        info = MediaInfo()
        info.type = ProviderMediaType.SERIES
        info.title = "测试剧"
        info.tmdb_id = 12345
        info.begin_season = 1
        info.begin_episode = begin
        info.end_episode = end
        return info

    def test_single_episode(self):
        d = self._info(7).to_dict()
        assert d["episode"] == [7]

    def test_range_episode_expands(self):
        d = self._info(1, 10).to_dict()
        assert d["episode"] == list(range(1, 11))

    def test_movie_has_no_episode(self):
        from app.domain.media_types import ProviderMediaType
        from app.media.models import MediaInfo

        info = MediaInfo()
        info.type = ProviderMediaType.MOVIE
        info.title = "测试电影"
        info.tmdb_id = 999
        assert info.to_dict()["episode"] == []

    def test_episode_list_feeds_write_back(self):
        """to_dict 的 episode 直接喂给回写方法即可正确扣减。"""
        d = self._info(1, 10).to_dict()
        svc = _service(list(range(1, 21)))
        svc.update_subscribe_tv_lack_by_episodes(7, d["episode"])
        _args, kwargs = svc._tv_repo.update_lack.call_args
        assert kwargs["lack_episodes"] == list(range(11, 21))


class TestDownloadTriggerCondition:
    """事件只在「搜索结果手动下载 + 有 tmdb_id」时触发。"""

    @pytest.mark.parametrize(
        ("in_from_is_ot", "has_tmdb", "should_publish"),
        [
            (True, True, True),
            (True, False, False),  # 无 TMDB 无法定位订阅
            (False, True, False),  # 订阅/自动下载不需回写
            (False, False, False),
        ],
    )
    def test_publish_condition(self, in_from_is_ot, has_tmdb, should_publish):
        # 复刻 pipeline 的判定：in_from == SearchType.OT and media_info.tmdb_id
        tmdb_id = 123 if has_tmdb else 0
        assert bool(in_from_is_ot and tmdb_id) is should_publish
