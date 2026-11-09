"""类型约束的适用边界：只锁「确实有剧集特征」的内容。

上一版把「源目录声明了类型」直接当作约束条件，结果误伤了正常内容：
电影目录里的作品在 TMDB 被归为 tv 时，约束会拒绝唯一的搜索结果，
整条内容变成「未识别」。日志里的典型形态是：

    多类型搜索只找到 tv，与已知类型 movie 不符，放弃
    以年份 2023 在TMDB中未找到movie信息!

正确的判据是**文件名是否解析出季集**，而不是源目录名：
- 剧集（有 SxxExx / 季）   → 约束，避免被模糊评分翻成同名老电影
- 电影（单文件、无季集）    → 不约束，允许 TMDB 用它的类型判断
"""

from types import SimpleNamespace

import pytest

from app.domain.media_types import ProviderMediaType


def _parsed(season=None, episode=None):
    return SimpleNamespace(season=season, episode=episode)

def _decide(media_type, parsed_list):
    """复刻 identify_files 的类型约束判定。"""
    hint = ProviderMediaType.from_value(str(getattr(media_type, "value", media_type) or ""))
    looks_episodic = any(
        item is not None and (item.season is not None or item.episode is not None) for item in parsed_list
    )
    constrain = hint in (ProviderMediaType.SERIES, ProviderMediaType.ANIME) and looks_episodic
    return hint, looks_episodic, constrain

class TestEpisodicContentConstrained:
    """剧集内容必须约束，否则会被同名老电影抢走."""

    @pytest.mark.parametrize(
        "parsed",
        [
            [_parsed(season=1, episode=9)],
            [_parsed(season=5)],
            [_parsed(episode=12)],
        ],
    )
    def test_tv_source_with_episode_marks(self, parsed):
        _hint, looks, constrain = _decide("tv", parsed)
        assert looks is True
        assert constrain is True

    def test_anime_source_with_episode_marks(self):
        _hint, _looks, constrain = _decide("anime", [_parsed(season=1, episode=3)])
        assert constrain is True

    def test_mixed_batch_any_episodic_constrains(self):
        # 一个目录里只要有一条带季集，说明是剧集批次
        _hint, _looks, constrain = _decide("tv", [None, _parsed(season=1, episode=2)])
        assert constrain is True

class TestFilmContentNotConstrained:
    """电影内容不得约束：TMDB 把电影归为 tv 时仍要能接受."""

    def test_movie_source_without_episode(self):
        _hint, looks, constrain = _decide("movie", [_parsed()])
        assert looks is False
        assert constrain is False

    def test_movie_source_unparsed(self):
        _hint, _looks, constrain = _decide("movie", [None])
        assert constrain is False

    def test_movie_source_never_constrains(self):
        # 即使解析器偶然给出季号，源声明是电影就不该锁死类型
        # （电影目录里混入剧集封装的情况应交给 TMDB 判断）
        _hint, _looks, constrain = _decide("movie", [_parsed(season=1, episode=1)])
        assert constrain is False

class TestNoHint:
    def test_unknown_hint_never_constrains(self):
        for mt in (None, "", ProviderMediaType.UNKNOWN):
            _hint, _looks, constrain = _decide(mt, [_parsed(season=1, episode=1)])
            assert constrain is False

    def test_hint_still_passed_when_not_constraining(self):
        """不约束时仍要传 hint，否则电影会先被当成剧集搜."""
        hint, _looks, constrain = _decide("movie", [_parsed()])
        assert hint == ProviderMediaType.MOVIE
        assert constrain is False

class TestRealWorldShapes:
    """用真实文件名形态验证判定（不含具体作品名）."""

    @pytest.mark.parametrize(
        ("describe", "media_type", "season", "episode", "expect_constrain"),
        [
            ("剧集：S01 目录级", "tv", 1, None, True),
            ("剧集：S01E01 文件级", "tv", 1, 1, True),
            ("剧集：仅季号", "tv", 2, None, True),
            ("电影：无季集", "movie", None, None, False),
            ("电影：单文件", "movie", None, None, False),
        ],
    )
    def test_shapes(self, describe, media_type, season, episode, expect_constrain):
        _hint, _looks, constrain = _decide(media_type, [_parsed(season=season, episode=episode)])
        assert constrain is expect_constrain, describe
