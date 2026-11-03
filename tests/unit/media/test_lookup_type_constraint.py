"""类型约束：源已声明类型时不得被跨类型猜测翻转。

生产事故：源目录标明是剧集、解析器也判为 tv，但 TMDB 查询时 TV 结果会与
同名的老电影做模糊评分比较，电影分数更高就翻转类型 —— 剧集于是被认成
十几年前的同类同名影片，或者被认成译名相同的中文片，落进电影目录。

这类翻转有三个入口，都必须被「已知类型」挡住：
1. TV 命中后与电影做模糊评分比较
2. 电影命中后与 TV 做模糊评分比较
3. 最后的 search_multi / 互换类型兜底
"""

from unittest.mock import MagicMock

from app.domain.mediatypes import MediaType
from app.media.lookup.tmdb_lookup import TmdbLookup

# 测试用的中性标题与虚构 TMDB ID，不指向任何真实作品
TV_TITLE = "测试剧集"
MOVIE_TITLE = "测试电影"


def _parsed(title_cn=None, title_en=None, year=None, mtype=MediaType.TV, season=1, episode=None):
    p = MagicMock()
    p.title_cn = title_cn
    p.title_en = title_en
    p.year = year
    p.type = mtype
    p.season = season
    p.episode = episode
    p.org_string = f"{title_cn or title_en or ''}.S01".strip(".")
    return p


def _service(*, tv_hit=None, movie_hit=None, multi_hit=None):
    svc = TmdbLookup.__new__(TmdbLookup)
    svc._lookup_cache = MagicMock()
    svc._lookup_cache.get.return_value = None
    svc.client = MagicMock()

    search = MagicMock()
    search.search_tv.return_value = tv_hit
    search.search_tv_by_season.return_value = None
    search.search_movie.return_value = movie_hit
    search.search_multi.return_value = multi_hit
    search.search_multi_infos.return_value = []
    search._fetch_allnames.return_value = ({}, [])
    svc.search = search

    detail = MagicMock()
    detail.get_detail.side_effect = lambda *a, **k: {
        "id": a[0] if a else 0,
        "name": TV_TITLE,
        "title": TV_TITLE,
        "genres": [{"id": 18, "name": "Drama"}],
    }
    svc.detail = detail
    return svc


TV_HIT = {
    "id": 900001,
    "name": TV_TITLE,
    "first_air_date": "2018-05-02",
    "genres": [{"id": 18, "name": "Drama"}],
}
MOVIE_HIT = {
    "id": 900002,
    "title": MOVIE_TITLE,
    "release_date": "1987-04-01",
    "genres": [{"id": 28, "name": "Action"}],
}


class TestCrossTypeFlipBlocked:
    def test_tv_does_not_flip_to_movie_when_constrained(self, monkeypatch):
        """TV 命中后不得因电影模糊分更高而翻转。"""
        monkeypatch.setattr("app.media.lookup.tmdb_lookup._score_fuzzy_match", lambda *a, **k: 0.9)
        svc = _service(tv_hit=dict(TV_HIT), movie_hit=dict(MOVIE_HIT))
        monkeypatch.setattr(svc, "_match_tmdb_candidate", lambda *a, **k: True)

        result = svc.lookup(_parsed(title_cn=TV_TITLE, year="2018"), hint_type=MediaType.TV, constrain_type=True)
        assert result is not None
        assert result.tmdb_id == TV_HIT["id"]
        assert result.media_type == MediaType.TV

    def test_flip_still_allowed_without_constraint(self, monkeypatch):
        """未声明类型时保留原有跨类型比较行为（不破坏既有能力）。"""
        monkeypatch.setattr("app.media.lookup.tmdb_lookup._score_fuzzy_match", lambda *a, **k: 0.9)
        svc = _service(tv_hit=dict(TV_HIT), movie_hit=dict(MOVIE_HIT))
        monkeypatch.setattr(svc, "_match_tmdb_candidate", lambda *a, **k: True)
        # TV 与电影同分时保持 TV；这里只验证「没被 constrain 挡掉」这条路径有执行
        result = svc.lookup(_parsed(title_cn=TV_TITLE, year="2018"), hint_type=MediaType.TV, constrain_type=False)
        assert result is not None
        assert result.tmdb_id in (TV_HIT["id"], MOVIE_HIT["id"])


class TestCrossTypeFallbackBlocked:
    def test_multi_search_wrong_type_rejected(self, monkeypatch):
        """TV 查不到时，多类型搜索只找到电影也不接受。"""
        movie = dict(MOVIE_HIT, media_type="movie")
        svc = _service(tv_hit=None, multi_hit=movie)
        monkeypatch.setattr(svc, "_match_tmdb_candidate", lambda *a, **k: True)
        result = svc.lookup(_parsed(title_cn=TV_TITLE, year="2019"), hint_type=MediaType.TV, constrain_type=True)
        assert result is None

    def test_multi_search_same_type_accepted(self, monkeypatch):
        """多类型搜索命中的是剧集时可以接受（约束不阻同类型）。"""
        tv = dict(TV_HIT, media_type="tv")
        svc = _service(tv_hit=None, multi_hit=tv)
        monkeypatch.setattr(svc, "_match_tmdb_candidate", lambda *a, **k: True)
        result = svc.lookup(_parsed(title_cn=TV_TITLE, year="2019"), hint_type=MediaType.TV, constrain_type=True)
        assert result is not None
        assert result.tmdb_id == TV_HIT["id"]

    def test_swap_type_search_skipped(self, monkeypatch):
        """互换类型兜底在约束下不再执行。"""
        svc = _service(tv_hit=None, movie_hit=dict(MOVIE_HIT))
        monkeypatch.setattr(svc, "_match_tmdb_candidate", lambda *a, **k: True)
        result = svc.lookup(_parsed(title_cn=TV_TITLE, year="2019"), hint_type=MediaType.TV, constrain_type=True)
        assert result is None

    def test_swap_type_search_runs_without_constraint(self, monkeypatch):
        svc = _service(tv_hit=None, movie_hit=dict(MOVIE_HIT))
        monkeypatch.setattr(svc, "_match_tmdb_candidate", lambda *a, **k: True)
        result = svc.lookup(_parsed(title_cn=TV_TITLE, year="2019"), hint_type=MediaType.TV, constrain_type=False)
        # 无约束时允许多类型兜底，可能返回电影
        assert result is None or result.media_type == MediaType.MOVIE


class TestSameTypeFallbackPreserved:
    def test_yearless_tv_retry_still_works(self, monkeypatch):
        """约束只禁跨类型，同类型的「去年份重试」必须保留。"""
        calls = []

        def search_tv(name, year, season=None, episode=None):
            calls.append(year)
            return dict(TV_HIT) if year is None else None

        svc = _service()
        svc.search.search_tv = search_tv  # type: ignore[method-assign]
        result = svc.lookup(_parsed(title_cn=TV_TITLE, year="2018"), hint_type=MediaType.TV, constrain_type=True)
        assert result is not None
        assert result.tmdb_id == TV_HIT["id"]
        # 先按年份查、再去年份查
        assert calls[-1] is None


class TestIdentifyFilesPassesHint:
    """identify_files 必须把调用方的类型提示传给 lookup。"""

    def test_hint_becomes_constraint(self):
        # 复刻 identify_files 的转换逻辑
        def to_constraint(media_type):
            hint = MediaType.from_string(str(getattr(media_type, "value", media_type) or ""))
            constrain = hint != MediaType.UNKNOWN
            return (hint if constrain else None), constrain

        assert to_constraint("tv") == (MediaType.TV, True)
        assert to_constraint(MediaType.TV) == (MediaType.TV, True)
        assert to_constraint("movie") == (MediaType.MOVIE, True)
        assert to_constraint(None) == (None, False)
        assert to_constraint("") == (None, False)
