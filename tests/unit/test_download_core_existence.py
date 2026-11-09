"""DownloadCore 媒体库存在性检查回归测试。"""

from unittest.mock import MagicMock

import pytest

from app.domain.media_types import ProviderMediaType
from app.services.download_core import DownloadCore
from app.sites.torrent import Torrent


@pytest.mark.parametrize("total_ep", [{1: 10}, {"1": 10}])
@pytest.mark.parametrize("season", [1, "1"])
def test_check_exists_medias_accepts_numeric_or_string_season_keys(total_ep, season):
    """季号与总集数字典的键既可为数字也可为字符串，结果必须一致。"""
    core = DownloadCore.__new__(DownloadCore)
    core._filetransfer = MagicMock()
    core._filetransfer.get_no_exists_medias.return_value = []
    media = MagicMock()
    media.type = ProviderMediaType.SERIES
    media.total_episodes = 0
    media.get_season_seq.return_value = season

    exists, missing, _ = core.check_exists_medias(media, total_ep=total_ep)

    assert exists is True
    assert missing == {}
    # 季号由实现归一为整数后传给存在性检查
    core._filetransfer.get_no_exists_medias.assert_called_once_with(media, season=int(season), total_num=10)


def test_check_exists_medias_normalizes_missing_episode_list_for_intersection():
    core = DownloadCore.__new__(DownloadCore)
    core._filetransfer = MagicMock()
    core._filetransfer.get_no_exists_medias.return_value = [1, 2, 3]
    media = MagicMock()
    media.type = ProviderMediaType.SERIES
    media.total_episodes = 0
    media.series_key = None
    media.tmdb_id = 123
    media.anchor_provider = None
    media.get_season_seq.return_value = "1"

    exists, missing, _ = core.check_exists_medias(media, total_ep={1: 10})

    assert exists is False
    # 键格式与季号类型以实现为准，只要唯一且带缺失集信息即可
    assert len(missing) == 1
    key = next(iter(missing))
    entries = missing[key]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["episodes"] == [1, 2, 3]
    assert int(entry["season"]) == 1
    assert entry["total_episodes"] == 10

    target = {key: [{"season": entry["season"], "episodes": [1, 2, 3]}]}
    result = Torrent.get_intersection_episodes(target=target, source=missing, title=key)
    assert result[key][0]["episodes"] == [1, 2, 3]
