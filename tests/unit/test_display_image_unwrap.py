"""订阅保存时不能把模糊代理 URL 写回数据库."""

from app.media.display_image_policy import unwrap_display_image_url


def test_unwrap_blur_url():
    raw = "https://c0.jdbstatic.com/covers/0e/0emdq3.jpg"
    blur = f"/img/blur?url={raw.replace(':', '%3A').replace('/', '%2F')}&radius=24"
    assert unwrap_display_image_url(blur) == raw


def test_unwrap_plain_url_is_unchanged():
    assert unwrap_display_image_url("https://example.com/a.jpg") == "https://example.com/a.jpg"
