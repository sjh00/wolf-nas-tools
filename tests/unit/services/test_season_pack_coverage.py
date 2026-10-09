"""整季包覆盖判定回归测试：标题不足为依据，需实际集号覆盖。

回归：
- 磁力无法解析文件清单时不得清空缺失（否则单集包被当整季完成）。
- 单季包在总集数未知/实际集数不足时不得当作整季下载。
"""

from unittest.mock import MagicMock

from app.domain.mediatypes import MediaType
from app.services import download_strategies
from app.services.download_strategies import EpisodeStrategy, SeasonPackStrategy


def _tv_item(enclosure="http://x/download"):
    item = MagicMock()
    item.type = MediaType.TV
    item.tmdb_id = 1
    item.enclosure = enclosure
    item.page_url = "http://p/show"
    item.org_string = "Show S01"
    item.get_season_list.return_value = [1]
    item.get_episode_list.return_value = []
    return item


def test_season_pack_requires_actual_coverage_when_total_unknown(monkeypatch):
    monkeypatch.setattr(download_strategies, "is_download_failed", lambda i: False)
    item = _tv_item()
    need_tvs = {1: [{"season": 1, "episodes": None, "total_episodes": 0}]}
    need_seasons = SeasonPackStrategy.build_need_seasons(need_tvs)
    download_callback = MagicMock(return_value=("qb", "id1", ""))

    SeasonPackStrategy.find_season_packs(
        download_list=[item],
        need_seasons=need_seasons,
        need_tvs=need_tvs,
        get_download_url_callback=MagicMock(return_value="http://dl"),
        download_callback=download_callback,
        get_torrent_episodes_callback=MagicMock(return_value=([1], None)),  # 实为单集
    )

    download_callback.assert_not_called()
    assert 1 in need_tvs  # 缺失保留，不误当整季


def test_season_pack_accepted_when_covers_total(monkeypatch):
    monkeypatch.setattr(download_strategies, "is_download_failed", lambda i: False)
    item = _tv_item()
    need_tvs = {1: [{"season": 1, "episodes": None, "total_episodes": 12}]}
    need_seasons = SeasonPackStrategy.build_need_seasons(need_tvs)
    download_callback = MagicMock(return_value=("qb", "id1", ""))

    SeasonPackStrategy.find_season_packs(
        download_list=[item],
        need_seasons=need_seasons,
        need_tvs=need_tvs,
        get_download_url_callback=MagicMock(return_value="http://dl"),
        download_callback=download_callback,
        get_torrent_episodes_callback=MagicMock(return_value=(list(range(1, 13)), "/tmp/a.torrent")),
    )

    download_callback.assert_called_once()
    assert 1 not in need_tvs  # 已满足整季，移除缺失


def test_magnet_unknown_filelist_keeps_missing(monkeypatch):
    monkeypatch.setattr(download_strategies, "is_download_failed", lambda i: False)
    item = _tv_item("magnet:?xt=urn:btih:abc")
    need_tvs = {1: [{"season": 1, "episodes": [1, 2], "total_episodes": 12}]}
    download_callback = MagicMock(return_value=("qb", "id1", ""))

    EpisodeStrategy.download_from_season_pack(
        download_list=[item],
        need_tvs=need_tvs,
        get_download_url_callback=MagicMock(return_value="http://dl"),
        download_callback=download_callback,
        get_torrent_episodes_callback=MagicMock(return_value=([], None)),
        set_files_status_callback=MagicMock(),
        start_torrents_callback=MagicMock(),
        return_items=[],
        get_torrent_episodes_by_tid_callback=MagicMock(return_value=[]),  # 清单取不到
        remove_torrents_callback=MagicMock(),
    )

    assert 1 in need_tvs  # 缺失未被清空
