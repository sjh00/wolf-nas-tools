"""媒体类型 API 别名归一化测试."""

from app.domain.mediatypes import MediaType, normalize_media_type_input
from app.services.system.info import WebSearchService


def test_av_alias_maps_to_movie_adult_profile():
    media_type, profile = normalize_media_type_input("av", "default")

    assert media_type == "movie"
    assert profile == "adult"


def test_av_alias_keeps_explicit_profile():
    media_type, profile = normalize_media_type_input("AV", "adult")

    assert media_type == "movie"
    assert profile == "adult"


def test_regular_media_type_is_unchanged():
    media_type, profile = normalize_media_type_input("tv", "default")

    assert media_type == "tv"
    assert profile == "default"


def test_web_search_normalizes_av_alias_and_profile():
    captured = {}

    def search_fn(**kwargs):
        captured.update(kwargs)
        return 1, ""

    WebSearchService(search_fn).search("FC2-PPV-1", media_type="av")

    assert captured["media_type"] == MediaType.MOVIE
    assert captured["filters"]["content_profile"] == "adult"
