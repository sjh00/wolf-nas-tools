"""图片模糊代理的来源还原测试（本地代理/嵌套 blur）."""

import urllib.parse

from api.routers import image as image_router


def test_external_url_passthrough():
    assert image_router._resolve_blur_source("https://a.example/x.jpg") == ("https://a.example/x.jpg", "")


def test_library_proxy_is_unwrapped():
    inner = "https://a.example/x.jpg"
    wrapped = "/img/library/" + urllib.parse.quote(inner, safe="")

    assert image_router._resolve_blur_source(wrapped) == (inner, "")


def test_local_poster_proxy_is_resolved(monkeypatch, tmp_path):
    poster = tmp_path / "poster.jpg"
    poster.write_bytes(b"x")
    monkeypatch.setattr(image_router, "_safe_local_poster", lambda path: str(poster))
    wrapped = "/img/poster?path=" + urllib.parse.quote("/Media/movie/poster.jpg", safe="")

    assert image_router._resolve_blur_source(wrapped) == ("", str(poster))


def test_nested_blur_url_is_unwrapped():
    inner = "/img/library/" + urllib.parse.quote("https://a.example/x.jpg", safe="")
    wrapped = "/img/blur?url=" + urllib.parse.quote(inner, safe="") + "&radius=24"

    assert image_router._resolve_blur_source(wrapped) == ("https://a.example/x.jpg", "")


def test_tmdb_proxy_is_resolved():
    assert image_router._resolve_blur_source("/img/tmdb/w500/abc.jpg") == (
        "https://image.tmdb.org/t/p/original/abc.jpg",
        "",
    )


def test_blur_recursion_is_bounded():
    url = "https://a.example/x.jpg"
    for _ in range(10):
        url = "/img/blur?url=" + urllib.parse.quote(url, safe="")
    assert image_router._resolve_blur_source(url) == ("", "")
