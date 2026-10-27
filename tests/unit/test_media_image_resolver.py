from types import SimpleNamespace

from app.core.constants import DEFAULT_TMDB_IMAGE
from app.media.image_resolver import MediaImageResolver


def _media(profile: str, tmdb_id: str = "", poster_path: str = ""):
    return SimpleNamespace(
        content_profile=profile,
        tmdb_id=tmdb_id,
        poster_path=poster_path,
        fanart_backdrop="",
        backdrop_path="",
        fanart_poster="",
        image="",
        poster="",
        cover_url="",
        provider_data={},
    )


def test_non_default_profile_without_tmdb_has_no_default_image():
    assert MediaImageResolver.get_message_image(_media("custom")) == ""


def test_non_default_profile_with_tmdb_keeps_default_image():
    assert MediaImageResolver.get_message_image(_media("anime", tmdb_id="12345")) == DEFAULT_TMDB_IMAGE


def test_default_profile_keeps_default_image():
    assert MediaImageResolver.get_message_image(_media("default")) == DEFAULT_TMDB_IMAGE


def test_explicit_poster_wins():
    assert MediaImageResolver.get_message_image(_media("custom", poster_path="/poster.jpg")) == "/poster.jpg"
