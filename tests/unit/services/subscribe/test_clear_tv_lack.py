"""整季完成时清空缺集."""

from unittest.mock import MagicMock

from app.domain.entities.rss import SubscribeState
from app.services.subscribe.management.service import SubscribeService


class TestClearTvLack:
    def test_clears_lack_for_rssid(self):
        svc = SubscribeService.__new__(SubscribeService)
        svc._tv_repo = MagicMock()

        svc.clear_subscribe_tv_lack(42)

        svc._tv_repo.update_lack.assert_called_once_with(title=None, year=None, season=None, rssid=42, lack_episodes=[])

    def test_marks_pending_transfer(self):
        """清空缺集必须同时转「待转移」，否则订阅会停在进度满却仍在订阅并重复下载."""
        svc = SubscribeService.__new__(SubscribeService)
        svc._tv_repo = MagicMock()

        svc.clear_subscribe_tv_lack(42)

        svc._tv_repo.update_state.assert_called_once_with(
            title=None, year=None, season=None, rssid=42, state=SubscribeState.COMPLETED.value
        )

    def test_clears_sibling_lack(self):
        svc = SubscribeService.__new__(SubscribeService)
        svc._tv_repo = MagicMock()
        svc._find_tv_siblings = MagicMock(return_value=[MagicMock(id=43)])

        svc.clear_subscribe_tv_lack(42, media_info=MagicMock())

        rssids = [call.kwargs["rssid"] for call in svc._tv_repo.update_lack.call_args_list]
        assert rssids == [42, 43]
        assert all(call.kwargs["lack_episodes"] == [] for call in svc._tv_repo.update_lack.call_args_list)
        states = [call.kwargs for call in svc._tv_repo.update_state.call_args_list]
        assert [s["rssid"] for s in states] == [42, 43]
        assert all(s["state"] == SubscribeState.COMPLETED.value for s in states)
