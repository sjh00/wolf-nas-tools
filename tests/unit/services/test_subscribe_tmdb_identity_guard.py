"""TMDB 号按类型分区：同一数字在电影与剧集下是两部不同作品。

真实故障：订阅电视剧时带着「剧集 TMDB 号 + 电影类型」提交，
服务端按电影命名空间解析该数字，得到一部毫不相关的 1939 年老片，
于是订阅被建成那部电影（标题变了、海报还是原来的），且没有任何提示。

修复：解析 TMDB 号后用标题核对，若与要订阅的作品不符，尝试另一类型；
另一类型能对上就纠正，否则保留调用方信息并告警。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.domain.media_types import ProviderMediaType
from app.services.subscribe.management.add_service import SubscribeAddService


def _info(title: str, media_type: ProviderMediaType, year: str = "2026"):
    return SimpleNamespace(
        title=title,
        cn_name=title,
        original_title=title,
        type=media_type,
        year=year,
        tmdb_id="",
        poster_path="",
        provider_data=None,
    )

@pytest.fixture()
def svc(monkeypatch):
    s = SubscribeAddService.__new__(SubscribeAddService)
    s._metadata_service = MagicMock()  # type: ignore[attr-defined]
    return s

class TestTitleMatch:
    @pytest.mark.parametrize(
        ("a", "b", "expected"),
        [
            ("谷雨", "谷雨", True),
            ("谷雨", "谷雨 (2026)", True),
            ("The Silent Storm", "The.Silent.Storm", True),
            ("谷雨", "Cavalcade d'amour", False),
            ("", "x", False),
            ("x", "", False),
        ],
    )
    def test_titles_look_same(self, a, b, expected):
        assert SubscribeAddService._titles_look_same(a, b) is expected

class TestIdentityGuard:
    def test_matching_detail_is_kept(self, svc):
        media = _info("谷雨", ProviderMediaType.SERIES)
        svc._provider_media_info = MagicMock(side_effect=AssertionError("不应再查另一类型"))

        result = svc._resolve_tmdb_identity(
            media,
            name="谷雨",
            year="2026",
            requested=ProviderMediaType.SERIES,
            content_profile=None,
            allow_private=False,
            permissions=None,
            external_id="279155",
        )
        assert result is media
        svc._provider_media_info.assert_not_called()

    def test_mismatch_switches_to_other_type(self, svc):
        """剧集号 + 电影类型解析出无关电影时，按剧集重新解析并纠正。"""
        wrong = _info("Cavalcade d'amour", ProviderMediaType.MOVIE, "1939")
        right = _info("谷雨", ProviderMediaType.SERIES)
        svc._provider_media_info = MagicMock(return_value=right)

        result = svc._resolve_tmdb_identity(
            wrong,
            name="谷雨",
            year="2026",
            requested=ProviderMediaType.MOVIE,
            content_profile=None,
            allow_private=False,
            permissions=None,
            external_id="279155",
        )
        assert result is right
        assert result.type is ProviderMediaType.SERIES
        assert result.tmdb_id == "279155"
        # 换类型查询时传的是另一类型
        assert svc._provider_media_info.call_args.kwargs["media_type"] is ProviderMediaType.SERIES

    def test_mismatch_without_alternate_match_clears_tmdb_id(self, svc):
        """两种类型都对不上：清空 TMDB 号，避免订阅挂着指向别部作品的号。"""
        wrong = _info("Cavalcade d'amour", ProviderMediaType.MOVIE, "1939")
        wrong.tmdb_id = "12345"
        svc._provider_media_info = MagicMock(return_value=_info("别的东西", ProviderMediaType.SERIES))

        result = svc._resolve_tmdb_identity(
            wrong,
            name="谷雨",
            year="2026",
            requested=ProviderMediaType.MOVIE,
            content_profile=None,
            allow_private=False,
            permissions=None,
            external_id="12345",
        )
        assert result is wrong
        assert result.tmdb_id == "", "对不上的 TMDB 号必须清空"
        assert result.title == "Cavalcade d'amour"

    def test_alternate_lookup_failure_keeps_original(self, svc):
        """换类型校验失败时保留原结果（不能因为查不到就把号清空）。"""
        wrong = _info("Cavalcade d'amour", ProviderMediaType.MOVIE, "1939")
        wrong.tmdb_id = "279155"
        svc._provider_media_info = MagicMock(side_effect=RuntimeError("网络错误"))

        result = svc._resolve_tmdb_identity(
            wrong,
            name="谷雨",
            year="2026",
            requested=ProviderMediaType.MOVIE,
            content_profile=None,
            allow_private=False,
            permissions=None,
            external_id="279155",
        )
        assert result is wrong
        assert result.tmdb_id == "279155"

    def test_no_name_skips_check(self, svc):
        media = _info("Cavalcade d'amour", ProviderMediaType.MOVIE)
        svc._provider_media_info = MagicMock()
        result = svc._resolve_tmdb_identity(
            media,
            name=None,
            year=None,
            requested=ProviderMediaType.MOVIE,
            content_profile=None,
            allow_private=False,
            permissions=None,
            external_id="279155",
        )
        assert result is media
        svc._provider_media_info.assert_not_called()

    def test_anime_request_not_switched(self, svc):
        """动漫不在两种类型间切换（其 ID 与剧集同源）。"""
        media = _info("某动漫", ProviderMediaType.ANIME)
        svc._provider_media_info = MagicMock()
        result = svc._resolve_tmdb_identity(
            media,
            name="完全不同的名字",
            year=None,
            requested=ProviderMediaType.ANIME,
            content_profile=None,
            allow_private=False,
            permissions=None,
            external_id="1",
        )
        assert result is media
        svc._provider_media_info.assert_not_called()

class TestRejectedIdDropsAnchor:
    """号被判定为无关时必须同时丢弃锚点，否则后续查详情仍解析回错误作品。

    这里只校验判定契约：清空 tmdb_id 是调用方据此丢弃 anchor 的依据。
    """

    def test_cleared_id_is_detectable_by_caller(self, svc):
        wrong = _info("Cavalcade d'amour", ProviderMediaType.MOVIE, "1939")
        wrong.tmdb_id = "12345"
        svc._provider_media_info = MagicMock(return_value=_info("别的东西", ProviderMediaType.SERIES))

        result = svc._resolve_tmdb_identity(
            wrong,
            name="谷雨",
            year="2026",
            requested=ProviderMediaType.MOVIE,
            content_profile=None,
            allow_private=False,
            permissions=None,
            external_id="12345",
        )
        # 调用方据此判断是否丢弃 anchor/metadata_ref
        assert not getattr(result, "tmdb_id", "")

    def test_accepted_id_keeps_value(self, svc):
        media = _info("谷雨", ProviderMediaType.SERIES)
        media.tmdb_id = "279155"
        result = svc._resolve_tmdb_identity(
            media,
            name="谷雨",
            year="2026",
            requested=ProviderMediaType.SERIES,
            content_profile=None,
            allow_private=False,
            permissions=None,
            external_id="279155",
        )
        assert result.tmdb_id == "279155"
