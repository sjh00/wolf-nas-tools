"""规范剧集解析：并发时同一来源条目必须落到同一个 series_key。

真实故障：同一部剧的一批文件在 1 秒内并发处理，各自走到 resolve()。
每条都「查别名 → 查不到 → 新建剧集 → 写别名」，只有一条能写进别名表，
但每条都返回自己新建的 series_key，于是同一个 TMDB ID 在
TRANSFER_HISTORY / MEDIA_SERIES 里分裂成多个 series_key（实测 4 个）。
"""

from unittest.mock import MagicMock

from app.services.series_service import SeriesResolution, SeriesService


class _Series:
    def __init__(self, key, title, year):
        self.SERIES_KEY = key
        self.TITLE = title
        self.YEAR = year


class _Alias:
    def __init__(self, series_key, season=1):
        self.SERIES_KEY = series_key
        self.SEASON_NUMBER = season


def _service(*, alias_after_create):
    """构造仓储替身：create_alias 返回给定别名，模拟「别人先写成功了」。"""
    repo = MagicMock()
    repo.get_alias.return_value = None  # 首次查询都没有别名（并发窗口）
    repo.find_series_by_title.return_value = []
    repo.create_series.return_value = _Series("series:mine", "新建剧集", "2026")
    repo.create_alias.return_value = alias_after_create
    return SeriesService(repo=repo), repo


class TestConcurrentResolve:
    def test_uses_existing_alias_key_not_own(self):
        """别名已存在时，必须返回别名指向的剧集，不能返回自己新建的。"""
        service, repo = _service(alias_after_create=_Alias("series:winner"))
        repo.get_series.return_value = _Series("series:winner", "胜出剧集", "2026")

        result = service.resolve(
            provider="tmdb",
            external_id="100669",
            title="长征",
            year="2001",
            season_number=1,
        )

        assert isinstance(result, SeriesResolution)
        assert result.series_key == "series:winner", "并发时必须收敛到同一剧集"
        assert result.title == "胜出剧集"

    def test_uses_own_key_when_alias_created_by_self(self):
        service, repo = _service(alias_after_create=_Alias("series:mine"))
        repo.get_series.return_value = _Series("series:mine", "新建剧集", "2026")

        result = service.resolve(
            provider="tmdb", external_id="999", title="某剧", year="2026", season_number=1
        )

        assert result.series_key == "series:mine"

    def test_falls_back_when_alias_missing(self):
        """别名创建失败时仍返回新建剧集，不能因并发保护而丢结果。"""
        service, _repo = _service(alias_after_create=None)

        result = service.resolve(
            provider="tmdb", external_id="888", title="某剧", year="2026", season_number=1
        )

        assert result.series_key == "series:mine"

    def test_alias_reused_without_creating_series(self):
        """别名已存在时不应再新建剧集。"""
        repo = MagicMock()
        repo.get_alias.return_value = _Alias("series:exist")
        repo.get_series.return_value = _Series("series:exist", "已有剧集", "2026")
        service = SeriesService(repo=repo)

        result = service.resolve(
            provider="tmdb", external_id="777", title="已有剧集", year="2026", season_number=1
        )

        assert result.series_key == "series:exist"
        repo.create_series.assert_not_called()
