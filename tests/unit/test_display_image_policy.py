"""展示图片转换器回归：所有展示入口共用同一套插件规则."""

from app.domain.mediatypes import MediaType
from app.media.display_image_policy import (
    clear_display_image_transformers,
    register_display_image_transformer,
    transform_display_image,
    unregister_display_image_transformer,
)
from app.media.models import MediaInfo


def test_display_transformer_applies_by_profile():
    clear_display_image_transformers()
    register_display_image_transformer(lambda profile, url: "/img/blur?url=x" if profile == "adult" and url else url)
    try:
        assert transform_display_image("adult", "http://a.jpg") == "/img/blur?url=x"
        assert transform_display_image("default", "http://a.jpg") == "http://a.jpg"
    finally:
        clear_display_image_transformers()


def test_display_transformer_unregister_stops_rewrite():
    clear_display_image_transformers()

    def transformer(profile, url):
        return "/blur" if url else url

    register_display_image_transformer(transformer)
    unregister_display_image_transformer(transformer)
    assert transform_display_image("adult", "http://a.jpg") == "http://a.jpg"


def test_display_transformer_ignores_plugin_errors():
    clear_display_image_transformers()

    def broken(profile, url):
        raise RuntimeError("boom")

    register_display_image_transformer(broken)
    try:
        assert transform_display_image("adult", "http://a.jpg") == "http://a.jpg"
    finally:
        clear_display_image_transformers()


def test_media_info_message_image_uses_display_transformer():
    clear_display_image_transformers()
    register_display_image_transformer(lambda profile, url: "/img/blur?url=x" if profile == "adult" and url else url)
    try:
        media = MediaInfo(title="T", type=MediaType.MOVIE)
        media.content_profile = "adult"
        media.poster_path = "http://a.jpg"
        assert media.get_message_image() == "/img/blur?url=x"
    finally:
        clear_display_image_transformers()
