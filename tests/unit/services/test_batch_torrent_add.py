"""批量上传种子时必须按各自文件名识别。

真实问题：前端多选上传后仍传「第一个文件名」作为 title，后端
``identify_title = title or file_name`` 优先用它 → 整批种子都被识别成
同一部作品，后续推送/入库互相覆盖。
"""

from unittest.mock import MagicMock

from app.media.models import MediaInfo
from app.services.download_service import DownloadService


def _service(recognized: dict[str, str] | None = None):
    svc = DownloadService.__new__(DownloadService)
    media = MagicMock()
    recognized = recognized or {}

    def get_media_info(title="", subtitle=""):
        info = MediaInfo()
        info.title = recognized.get(title, title)
        return info

    media.get_media_info.side_effect = get_media_info
    svc._media = media
    svc._downloader = MagicMock()
    svc._downloader.download.return_value = (None, True, "")
    svc._sites = MagicMock()
    svc._sites.get_sites.return_value = {}
    svc._site_engine = MagicMock()
    svc._check_multi_version = MagicMock(return_value=None)
    def _resolve(file_item):
        return (file_item, f"/tmp/{file_item}") if file_item else ("", "")

    svc._resolve_uploaded_torrent = _resolve
    return svc, media


class TestBatchTorrentTitles:
    def test_each_file_recognized_by_own_name(self, tmp_path, monkeypatch):
        """多文件：每个种子用自己的文件名识别，不共用第一个标题。"""
        import app.services.download_service as mod

        svc, media = _service()
        monkeypatch.setattr(mod.os.path, "exists", lambda _p: True)

        svc.download_from_torrent_files_or_urls(
            files=["Movie.A.2020.torrent", "Movie.B.2021.torrent"],
            urls=[],
            dl_dir="",
            dl_setting="",
            user_name="u",
            title="Movie.A.2020.torrent",  # 前端传的第一个文件名
        )

        called = [c.kwargs.get("title") for c in media.get_media_info.call_args_list]
        # 种子内容不可解析时回退到原始文件名，并去掉 .torrent 后缀
        assert called == ["Movie.A.2020", "Movie.B.2021"]
        assert not any("upload_" in t for t in called)

    def test_single_file_keeps_caller_title(self, tmp_path, monkeypatch):
        """单文件：保留调用方给的标题（可能来自页面上下文，更准确）。"""
        import app.services.download_service as mod

        svc, media = _service()
        monkeypatch.setattr(mod.os.path, "exists", lambda _p: True)

        svc.download_from_torrent_files_or_urls(
            files=["Movie.A.2020.torrent"],
            urls=[],
            dl_dir="",
            dl_setting="",
            user_name="u",
            title="页面上的精确标题",
        )

        called = [c.kwargs.get("title") for c in media.get_media_info.call_args_list]
        assert called == ["页面上的精确标题"]

    def test_batch_urls_each_recognized_separately(self, monkeypatch):
        """多链接同样不能共用第一个标题。"""
        import app.services.download_service as mod

        svc, media = _service()
        monkeypatch.setattr(mod.os.path, "exists", lambda _p: True)

        svc.download_from_torrent_files_or_urls(
            files=[],
            urls=["magnet:?xt=urn:btih:aaa", "magnet:?xt=urn:btih:bbb"],
            dl_dir="",
            dl_setting="",
            user_name="u",
            title="第一个链接的标题",
        )

        called = [c.kwargs.get("title") for c in media.get_media_info.call_args_list]
        assert called == ["magnet:?xt=urn:btih:aaa", "magnet:?xt=urn:btih:bbb"]

    def test_all_batch_files_pushed_to_downloader(self, monkeypatch):
        """每个种子都要真正推送到下载器。"""
        import app.services.download_service as mod

        svc, _media = _service()
        monkeypatch.setattr(mod.os.path, "exists", lambda _p: True)

        svc.download_from_torrent_files_or_urls(
            files=["a.torrent", "b.torrent", "c.torrent"],
            urls=[],
            dl_dir="",
            dl_setting="",
            user_name="u",
        )

        assert getattr(svc._downloader, "download").call_count == 3
