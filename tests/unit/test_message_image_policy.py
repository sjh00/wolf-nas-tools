from app.media.message_image_policy import (
    clear_message_image_transformers,
    register_message_image_transformer,
    transform_message_image,
    unregister_message_image_transformer,
)


def test_message_image_transformer_is_profile_scoped():
    clear_message_image_transformers()
    register_message_image_transformer(lambda profile, url: "/img/blur?url=x" if profile == "custom" and url else url)
    try:
        assert transform_message_image("custom", "http://a.jpg") == "/img/blur?url=x"
        assert transform_message_image("default", "http://a.jpg") == "http://a.jpg"
    finally:
        clear_message_image_transformers()


def test_message_image_transformer_can_be_unregistered():
    clear_message_image_transformers()
    transformer = lambda profile, url: "/img/blur?url=x" if profile == "custom" else url  # noqa: E731
    register_message_image_transformer(transformer)
    unregister_message_image_transformer(transformer)
    try:
        assert transform_message_image("custom", "http://a.jpg") == "http://a.jpg"
    finally:
        clear_message_image_transformers()
