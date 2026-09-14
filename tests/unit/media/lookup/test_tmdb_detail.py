"""TmdbDetail.get_season_detail 季不存在（404）negative cache 回归测试."""

from unittest.mock import MagicMock

from app.infrastructure.cache_system.adapters import MemoryCacheAdapter
from app.infrastructure.cache_system.caches import TMDBCache
from app.infrastructure.http.exceptions import HttpClientError
from app.media.lookup.tmdb_detail import TmdbDetail


def _make_detail(season_effect=None, season_return=None):
    cache = TMDBCache(MemoryCacheAdapter())
    tv = MagicMock()
    if season_effect is not None:
        tv.season_details.side_effect = season_effect
    if season_return is not None:
        tv.season_details.return_value = season_return
    client = MagicMock()
    client.redis_cache = cache
    client.tv = tv
    return TmdbDetail(client), tv


def test_season_404_is_negative_cached():
    """季不存在（404）应进入 negative cache，第二次不再请求 TMDB.

    回归：合并季动漫（如《海贼王女》TMDB 仅 1 季，但资源被标成 S06）转移抓集标题时
    会查 season/6 得到 404。修复前 404 走 except 分支不缓存，每次转移都重复打 TMDB
    并刷 WARNING。
    """
    detail, tv = _make_detail(HttpClientError("Client error '404 Not Found'", status_code=404))

    assert detail.get_season_detail(106480, 6) == {}
    assert tv.season_details.call_count == 1

    # 第二次命中 negative cache，不再打 TMDB
    assert detail.get_season_detail(106480, 6) == {}
    assert tv.season_details.call_count == 1


def test_season_404_other_status_not_cached():
    """非 404（如 401/429）不应 negative cache，后续仍应重试."""
    detail, tv = _make_detail(HttpClientError("Unauthorized", status_code=401))

    assert detail.get_season_detail(106480, 6) == {}
    assert detail.get_season_detail(106480, 6) == {}
    assert tv.season_details.call_count == 2


def test_season_success_cached():
    """正常季详情应缓存并复用，不重复请求."""
    episodes = [{"episode_number": 1, "name": "第一集"}]
    detail, tv = _make_detail(season_return={"episodes": episodes, "season_number": 6})

    result = detail.get_season_detail(106480, 6)
    assert result.get("episodes") == episodes
    # 第二次命中正缓存
    detail.get_season_detail(106480, 6)
    assert tv.season_details.call_count == 1
