"""TMDB 推荐/相似接口的 404 处理。

TMDB 对不存在的资源返回 404（该 tmdbid 已被删除/合并），属预期内的空结果，
不应按异常告警刷屏；其他错误（网络/5xx/鉴权）仍需告警。
"""

from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.http.exceptions import HttpClientError
from app.media.lookup.tmdb_discover import TmdbDiscover


def _discover(exc):
    client = MagicMock()
    client.movie.recommendations.side_effect = exc
    client.movie.similar.side_effect = exc
    client.tv.recommendations.side_effect = exc
    client.tv.similar.side_effect = exc
    return TmdbDiscover(client)


class TestNotFoundDowngraded:
    @pytest.mark.parametrize(
        "method,args",
        [
            ("get_movie_recommendations", (107396,)),
            ("get_movie_similar", (107396,)),
            ("get_tv_recommendations", (106480,)),
            ("get_tv_similar", (106480,)),
        ],
    )
    def test_404_is_debug_not_warn(self, method, args):
        discover = _discover(HttpClientError("404 Not Found", status_code=404))
        with patch("app.media.lookup.tmdb_discover.log") as mock_log:
            result = getattr(discover, method)(*args)

        assert result == []
        mock_log.warn.assert_not_called()
        assert mock_log.debug.call_count == 1


class TestOtherErrorsStillWarn:
    @pytest.mark.parametrize("status_code", [401, 429, 500, 503])
    def test_non_404_still_warns(self, status_code):
        discover = _discover(HttpClientError("boom", status_code=status_code))
        with patch("app.media.lookup.tmdb_discover.log") as mock_log:
            result = discover.get_movie_recommendations(107396)

        assert result == []
        mock_log.warn.assert_called_once()

    def test_no_status_code_treated_as_error(self):
        """无状态码的异常（网络层）不能被当成 404 静默"""
        discover = _discover(HttpClientError("connection reset", status_code=None))
        with patch("app.media.lookup.tmdb_discover.log") as mock_log:
            result = discover.get_movie_recommendations(107396)

        assert result == []
        mock_log.warn.assert_called_once()
