"""新增订阅的起始进度：先看媒体库已有几集，再去搜索。

真实故障：媒体库里整季都在（手工放入或旧版本入库），但历史表里没有记录，
新订阅的进度仍是 0 / 从第 1 集开始，于是把已有剧集重新下载一遍。
"""


from app.domain.media_types import ProviderMediaType
from app.media.models import MediaInfo
from app.services.subscribe.management.add_service import SubscribeAddService
from app.services.web.utils import WebUtils


def _service(filetransfer):
    return SubscribeAddService(
        movie_repo=None,
        tv_repo=None,
        media_service=None,
        message=None,
        event_bus=None,
        system_config=None,
        web_utils=WebUtils(),
        filetransfer=filetransfer,
    )


def _tv():
    return MediaInfo(
        type=ProviderMediaType.SERIES,
        title="示例剧集",
        year="2026",
        begin_season=1,
        org_string="示例剧集.S01E01.mkv",
        rev_string="示例剧集.S01E01.mkv",
    )


class _Transfer:
    def __init__(self, episodes):
        self._episodes = set(episodes)
        self.calls = []

    def find_season_episodes(self, media_info, season=None):
        self.calls.append(season)
        return set(self._episodes)


class _LegacyTransfer:
    """没有 find_season_episodes 的旧实现：回退 get_no_exists_medias."""

    def __init__(self, missing):
        self._missing = missing

    def get_no_exists_medias(self, media_info, season=None, total_num=None):
        return list(self._missing)


class TestContiguousLibraryEpisodes:
    def test_counts_contiguous_episodes_from_start(self):
        svc = _service(_Transfer({1, 2, 3, 5}))

        count = svc._contiguous_library_episodes(_tv(), season=1, total=10)

        assert count == 3, "第 4 集缺失，连续计数必须停在 3"

    def test_start_offset_is_respected(self):
        svc = _service(_Transfer({1, 2, 3, 4, 5}))

        count = svc._contiguous_library_episodes(_tv(), season=1, total=10, start=4)

        assert count == 2

    def test_nothing_in_library(self):
        svc = _service(_Transfer(set()))

        assert svc._contiguous_library_episodes(_tv(), season=1, total=10) == 0

    def test_no_transfer_service_returns_zero(self):
        svc = _service(None)

        assert svc._contiguous_library_episodes(_tv(), season=1, total=10) == 0

    def test_unknown_total_returns_zero(self):
        svc = _service(_Transfer({1, 2}))

        assert svc._contiguous_library_episodes(_tv(), season=1, total=0) == 0

    def test_scan_failure_does_not_advance_progress(self):
        class _Broken:
            def find_season_episodes(self, media_info, season=None):
                raise RuntimeError("扫库炸了")

        svc = _service(_Broken())

        assert svc._contiguous_library_episodes(_tv(), season=1, total=10) == 0

    def test_legacy_fallback_uses_missing_episodes(self):
        # 缺 4..10 → 已有 1..3
        svc = _service(_LegacyTransfer([4, 5, 6, 7, 8, 9, 10]))

        assert svc._contiguous_library_episodes(_tv(), season=1, total=10) == 3

    def test_legacy_fallback_all_present_counts_whole_season(self):
        # 旧接口返回空缺失清单 = 整季都在
        svc = _service(_LegacyTransfer([]))

        assert svc._contiguous_library_episodes(_tv(), season=1, total=10) == 10

    def test_legacy_fallback_none_means_undeterminable(self):
        # 旧接口返回 None = 无法判定（路径未配置），不能当成"整季都在"
        class _Unknown:
            def get_no_exists_medias(self, media_info, season=None, total_num=None):
                return None

        svc = _service(_Unknown())

        assert svc._contiguous_library_episodes(_tv(), season=1, total=10) == 0

    def test_season_number_is_passed_to_scanner(self):
        transfer = _Transfer({1})
        svc = _service(transfer)

        svc._contiguous_library_episodes(_tv(), season=2, total=5)

        assert transfer.calls == [2]
