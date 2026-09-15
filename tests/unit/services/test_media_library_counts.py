"""媒体库统计的字段类型约定。

回归：
1. get_media_count 原先格式化成带千分位的展示字符串（"{:,}".format → "1,234"），
   前端首页用 Number("1,234") 得到 NaN，导致「电影」计数恒为 0
   （而媒体库页面自己剥了千分位所以显示正常）。
2. 空间字段原先用 "{:,} GB"（带千分位），与 SiteUserInfo 的 "{:.2f} GB"
   （不带千分位）格式不一致；前端 parseSize 的匹配正则要求以数字开头，
   带逗号会静默返回 0。
"""

from unittest.mock import MagicMock, patch

from app.services.media_library_service import MediaLibraryService


def _service(medias_count, user_count=3):
    media_server = MagicMock()
    media_server.get_medias_count.return_value = medias_count
    media_server.get_user_count.return_value = user_count
    return MediaLibraryService(
        media_server=media_server,
        filetransfer=MagicMock(),
        system_config=MagicMock(),
        thread_executor=MagicMock(),
        media_config_service=MagicMock(),
    )


class TestGetMediaCount:
    def test_returns_raw_numbers_not_formatted_strings(self):
        """大于 1000 时不得返回带千分位的字符串"""
        svc = _service({"MovieCount": 1234, "SeriesCount": 88, "EpisodeCount": 5678, "SongCount": 0})
        counts = svc.get_media_count()

        assert counts is not None
        for key in ("Movie", "Series", "Episodes", "Music", "User"):
            assert isinstance(counts[key], int), f"{key} 应为原始数字，实际 {counts[key]!r}"
        assert counts["Movie"] == 1234
        assert counts["Episodes"] == 5678

    def test_missing_keys_become_zero(self):
        """上游未返回的字段按 0 处理，不得抛异常"""
        svc = _service({"MovieCount": 10})
        counts = svc.get_media_count()

        assert counts is not None
        assert counts["Movie"] == 10
        assert counts["Series"] == 0
        assert counts["Episodes"] == 0
        assert counts["Music"] == 0

    def test_none_values_become_zero(self):
        """字段为 None 时按 0 处理（原先 "{:,}".format(None) 会抛 TypeError）"""
        svc = _service({"MovieCount": None, "SeriesCount": None, "EpisodeCount": None, "SongCount": None})
        counts = svc.get_media_count()

        assert counts is not None
        assert counts["Movie"] == 0
        assert counts["Series"] == 0

    def test_no_upstream_data_returns_none(self):
        """上游无数据 → None（调用方据此判定媒体服务器不可用）"""
        assert _service(None).get_media_count() is None

    def test_frontend_number_parse_of_result(self):
        """模拟前端 Number()：原始数字可直接解析，不会再变成 NaN"""
        svc = _service({"MovieCount": 1234, "SeriesCount": 88, "EpisodeCount": 0, "SongCount": 0})
        counts = svc.get_media_count()
        assert counts is not None
        # 前端逻辑：Number(value) || 0；对 int 而言即原值
        assert (counts["Movie"] or 0) == 1234


class TestSpaceFormatIsParseable:
    """空间字符串必须能被前端 parseSize 解析（不得带千分位）。

    前端 parseSize 的正则是 ^(\\d+(\\.\\d+)?)\\s*(TB|GB|MB|KB|B)，
    要求以数字开头；"1,234.56 GB" 会匹配失败并静默返回 0。
    """

    def _space_service(self, total_gb: float, free_gb: float):
        svc = _service({"MovieCount": 1})
        media_config = MagicMock()
        media_config.get_config.return_value = {"movie_path": ["/media/movies"], "tv_path": [], "anime_path": []}
        svc._media_config_service = media_config
        return svc, (total_gb, free_gb)

    def _run(self, total_gb: float, free_gb: float):
        svc, space = self._space_service(total_gb, free_gb)
        with patch("app.services.media_library_service.SystemUtils.calculate_space_usage", return_value=space):
            return svc.get_space_info()

    def test_no_thousands_separator(self):
        """超过 1000 GB 时不得出现千分位逗号"""
        info = self._run(4096.0, 1024.0)
        for value in (info.total_space, info.used_space, info.free_space):
            assert "," not in value, f"空间字符串不应带千分位：{value!r}"

    def test_matches_frontend_parse_size_regex(self):
        """生成的空间字符串必须能被前端 parseSize 的正则匹配到"""
        import re

        info = self._run(4096.0, 1024.0)
        pattern = re.compile(r"^(\d+(?:\.\d+)?)\s*(TB|GB|MB|KB|B)", re.IGNORECASE)
        for value in (info.total_space, info.used_space, info.free_space):
            assert pattern.match(value), f"前端 parseSize 无法解析：{value!r}"

    def test_used_percent_is_number(self):
        info = self._run(100.0, 25.0)
        assert isinstance(info.used_percent, (int, float))
        assert info.used_percent == 75.0
