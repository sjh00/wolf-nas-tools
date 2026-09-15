"""媒体服务器图片 URL 必须自带 api_key。

与 API 请求不同：API 请求走 _http_get()，可以携带 Authorization: MediaBrowser 头；
而图片 URL 会被图片代理、浏览器 <img>、以及 TG/微信等外部消息客户端直接读取，
这些上下文都无法附加自定义头，只能用查询参数鉴权。

历史回归：某次「Jellyfin 改用 Authorization 头」的改动，把 API 请求和图片 URL 的
api_key 一并去掉了，导致图片全部取不到（404/401）。可对照 emby.py 的 Backdrop/Thumb
始终保留 api_key —— 设计意图就是「图片 URL 必须带 api_key」。
"""

import ast
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import unquote

import pytest

from app.mediaserver.client.emby import Emby
from app.mediaserver.client.jellyfin import Jellyfin

_CLIENT_DIR = Path(sys.modules[Jellyfin.__module__].__file__ or "").parent
_CFG = {"host": "http://127.0.0.1:8096", "api_key": "secret-key", "user_id": "u1"}

_ITEM = {
    "Id": "c548724f9c789b73052464ab353a2d40",
    "Name": "某影片",
    "Type": "Movie",
    "ImageTags": {"Primary": "tag-abc"},
    "UserData": {"PlayedPercentage": 10},
}


def _jellyfin() -> Jellyfin:
    with (
        patch.object(Jellyfin, "get_user", return_value="u1"),
        patch.object(Jellyfin, "get_server_id", return_value="s1"),
    ):
        return Jellyfin(config=dict(_CFG))


def _emby() -> Emby:
    with (
        patch.object(Emby, "_Emby__get_emby_folders", return_value=[]),
        patch.object(Emby, "get_user", return_value="u1"),
        patch.object(Emby, "get_server_id", return_value="s1"),
    ):
        return Emby(config=dict(_CFG))


def _decode(url: str) -> str:
    """图片地址形如 /img/library/<整段 URL 编码后的上游地址>，断言前先解码"""
    return unquote(url or "")


def _jellyfin_images(method_name: str, payload, **kwargs):
    """驱动 get_latest / get_resume，返回解码后的图片地址列表"""
    client = _jellyfin()
    mock_resp = MagicMock()
    mock_resp.json.return_value = payload
    with patch.object(client, "_http_get", return_value=mock_resp):
        result = getattr(client, method_name)(**kwargs) or []
    return [_decode(r.get("image")) for r in result]


class TestImageUrlCarriesApiKey:
    def test_get_latest_images_have_api_key(self):
        images = _jellyfin_images("get_latest", [_ITEM], num=1)

        assert images, "应产出图片 URL"
        assert "Images/Primary" in images[0]
        assert "api_key=secret-key" in images[0]

    def test_get_resume_images_have_api_key(self):
        """get_resume 返回 {"Items": [...]}"""
        images = _jellyfin_images("get_resume", {"Items": [_ITEM]}, num=1)

        assert images
        assert "api_key=secret-key" in images[0]

    def test_get_libraries_images_have_api_key(self):
        client = _jellyfin()
        libs = [{"Id": "lib1", "Name": "电影", "CollectionType": "movies", "ImageTags": {"Primary": "t1"}}]
        with patch.object(client, "_Jellyfin__get_jellyfin_librarys", return_value=libs):
            libraries = client.get_libraries() or []

        assert libraries
        assert "api_key=secret-key" in _decode(libraries[0].get("image"))

    def test_library_images_go_through_internal_proxy(self):
        """内网地址要包成 /img/library/... 交给后端代理"""
        client = _jellyfin()
        libs = [{"Id": "lib1", "Name": "电影", "CollectionType": "movies", "ImageTags": {"Primary": "t1"}}]
        with patch.object(client, "_Jellyfin__get_jellyfin_librarys", return_value=libs):
            libraries = client.get_libraries() or []

        assert (libraries[0].get("image") or "").startswith("/img/library/")

    @pytest.mark.parametrize(
        ("factory", "method", "image_path", "kwargs"),
        [
            (_jellyfin, "get_local_image_by_id", "Images/Primary", {"remote": True}),
            (_jellyfin, "get_local_image_by_id", "Images/Primary", {"remote": False}),
            (_emby, "get_local_image_by_id", "Images/Primary", {"remote": True}),
            (_emby, "get_local_image_by_id", "Images/Primary", {"remote": False}),
        ],
    )
    def test_local_image_by_id_has_api_key(self, factory, method, image_path, kwargs):
        """remote=True 时内网地址会被包成 /img/library/... 并整体编码，需先解码"""
        url = _decode(getattr(factory(), method)(item_id="i1", **kwargs))

        assert url and image_path in url
        assert "api_key=secret-key" in url


class TestEveryImageUrlInSourceHasApiKey:
    """源码级契约：两个客户端里出现的每个图片 URL 都必须带 api_key。

    新增图片地址而忘记带 api_key 时，这条会直接失败——避免再次出现
    「API 改了鉴权方式，顺手把图片 URL 也改了」这类回归。
    """

    _IMAGE_URL = re.compile(r"Images/(?:Primary|Backdrop|Thumb)")

    @classmethod
    def _image_url_literals(cls, module_file: str) -> list[str]:
        """取出模块内全部图片 URL 字面量。

        用 ast 而不是正则：解析器会把跨行隐式拼接的字符串折叠成一个节点，
        这样 `"…/Images/Primary" "?tag=…&api_key=…"` 会被视为一整条 URL。

        注意 Python 3.12+ 会把 f-string 拆成 JoinedStr + 若干 Constant 片段，
        片段本身是半截字符串（如 "/Images/Backdrop?tag="），必须合并后再判断，
        否则会把完整 URL 误判成缺 api_key。
        """
        tree = ast.parse((_CLIENT_DIR / module_file).read_text(encoding="utf-8"))

        fragment_ids: set[int] = set()
        urls: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.JoinedStr):
                continue
            pieces: list[str] = []
            for value in node.values:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    pieces.append(value.value)
                    fragment_ids.add(id(value))
            text = "".join(pieces)
            if cls._IMAGE_URL.search(text):
                urls.append(text)

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in fragment_ids
                and cls._IMAGE_URL.search(node.value)
            ):
                urls.append(node.value)
        return urls

    @pytest.mark.parametrize("module_file", ["jellyfin.py", "emby.py"])
    def test_image_urls_carry_api_key(self, module_file):
        urls = self._image_url_literals(module_file)

        assert urls, f"{module_file} 应至少产出一个图片 URL，检查匹配条件是否失效"
        missing = [u for u in urls if "api_key" not in u]
        assert not missing, (
            "以下图片 URL 缺少 api_key（图片代理、浏览器 <img>、外部消息客户端都无法附加 "
            "Authorization 头）:\n" + "\n".join(missing)
        )
