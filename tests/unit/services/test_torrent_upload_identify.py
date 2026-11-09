"""上传种子的识别源必须是真实作品名，不能是上传临时文件名。

真实问题：上传接口把文件存成 `upload_<随机>.torrent`，而添加下载时
`identify_title` 直接取了这个临时名 → 识别失败 → 下载记录显示
`upload_2026……`，入库命名也跟着退化。

识别源优先级：调用方标题（仅单条）→ 种子内部 info.name → 原始文件名。
"""

from unittest.mock import MagicMock

import bencodepy
import pytest

from app.media.models import MediaInfo
from app.services.download_service import DownloadService


def _make_torrent(path, name: str, *, multifile: bool = False):
    info: dict = {
        "name": name,
        "piece length": 262144,
        "pieces": b"\x00" * 20,
    }
    if multifile:
        info["files"] = [{"length": 100, "path": ["ep1.mkv"]}]
    else:
        info["length"] = 1024
    path.write_bytes(bencodepy.encode({"announce": "http://t/announce", "info": info}))
    return path


class TestTorrentInnerName:
    def test_single_file_torrent(self, tmp_path):
        f = _make_torrent(tmp_path / "u.torrent", "Some.Movie.2020.1080p.BluRay-GROUP")
        assert DownloadService._torrent_inner_name(str(f)) == "Some.Movie.2020.1080p.BluRay-GROUP"

    def test_multi_file_torrent(self, tmp_path):
        f = _make_torrent(tmp_path / "u.torrent", "Some.Show.S01.1080p.WEB-DL", multifile=True)
        assert DownloadService._torrent_inner_name(str(f)) == "Some.Show.S01.1080p.WEB-DL"

    def test_invalid_and_missing_return_empty(self, tmp_path):
        bad = tmp_path / "bad.torrent"
        bad.write_bytes(b"not a torrent")
        assert DownloadService._torrent_inner_name(str(bad)) == ""
        assert DownloadService._torrent_inner_name(str(tmp_path / "nope.torrent")) == ""


class TestTitleFallback:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("upload_20261107_abc.torrent", "upload_20261107_abc"),
            ("My.Movie.2020.torrent", "My.Movie.2020"),
            ("Show.S01E01.TORRENT", "Show.S01E01"),
            ("plain", "plain"),
        ],
    )
    def test_strips_torrent_suffix(self, raw, expected):
        assert DownloadService._torrent_title_fallback(raw) == expected


class TestResolveUploadedTorrent:
    def test_dict_prefers_original_name(self, tmp_path):
        temp_name = "upload_20261107_abc.torrent"
        (tmp_path / temp_name).write_bytes(b"x")
        fake_temp = tmp_path / temp_name

        class _TempManager:
            def get_temp_path(self, name):
                return str(fake_temp)

        import app.services.download_service as mod

        original = mod.temp_manager
        mod.temp_manager = _TempManager()
        try:
            name, path = DownloadService._resolve_uploaded_torrent(
                {"filename": temp_name, "original_name": "Real.Movie.2020.torrent"}
            )
        finally:
            mod.temp_manager = original

        assert name == "Real.Movie.2020.torrent", "识别源应取原始文件名"
        assert path == str(fake_temp)

    def test_string_still_supported(self, tmp_path):
        temp_name = "upload_x.torrent"
        (tmp_path / temp_name).write_bytes(b"x")

        class _TempManager:
            def get_temp_path(self, name):
                return str(tmp_path / name)

        import app.services.download_service as mod

        original = mod.temp_manager
        mod.temp_manager = _TempManager()
        try:
            name, path = DownloadService._resolve_uploaded_torrent(temp_name)
        finally:
            mod.temp_manager = original

        assert name == temp_name
        assert path.endswith(temp_name)


class _Recorder:
    """记录 get_media_info 的入参，并返回可用的 MediaInfo。"""

    def __init__(self):
        self.titles: list[str] = []

    def get_media_info(self, title="", subtitle="", **_kw):
        self.titles.append(title)
        info = MediaInfo()
        info.title = title
        return info


def _service(recorder: _Recorder):
    svc = DownloadService.__new__(DownloadService)
    gateway = MagicMock()
    gateway.resolve_by_title.side_effect = lambda title, **kw: recorder.get_media_info(title=title)
    svc._metadata_gateway = gateway
    svc._downloader = _StubDownloader()  # type: ignore[assignment]
    svc._check_multi_version = lambda media=None: None
    return svc


class _StubDownloader:
    def __init__(self):
        self.media_titles: list[str] = []

    def download(self, media_info=None, **_kw):
        self.media_titles.append(getattr(media_info, "title", ""))
        return None, True, ""


class TestBatchIdentifyTitles:
    def test_batch_uses_inner_torrent_name(self, tmp_path):
        """核心回归：批量上传按种子内部发布名识别，不出现 upload_ 前缀。"""
        files = []
        for idx, inner in enumerate(
            ["Movie.One.2020.1080p-GROUP", "Movie.Two.2021.2160p-GROUP"]
        ):
            temp = tmp_path / f"upload_20261107_{idx}.torrent"
            _make_torrent(temp, inner)
            files.append({"filename": temp.name, "original_name": temp.name})

        recorder = _Recorder()
        svc = _service(recorder)

        def _resolve_dict(file_item):
            return (file_item["original_name"], str(tmp_path / file_item["filename"]))

        svc._resolve_uploaded_torrent = _resolve_dict

        svc.download_from_torrent_files_or_urls(
            files=files,
            urls=[],
            dl_dir="",
            dl_setting="",
            user_name="u",
            title="upload_20261107_0.torrent",  # 前端旧行为
        )

        assert recorder.titles == [
            "Movie.One.2020.1080p-GROUP",
            "Movie.Two.2021.2160p-GROUP",
        ]
        assert not any("upload_" in t for t in recorder.titles)

    def test_single_keeps_caller_title(self, tmp_path):
        """单条仍尊重调用方标题（页面上下文可能更准确）。"""
        temp = tmp_path / "upload_1.torrent"
        _make_torrent(temp, "Inner.Name.2020")
        recorder = _Recorder()
        svc = _service(recorder)
        svc._resolve_uploaded_torrent = lambda file_item=None, _i=None: ("upload_1.torrent", str(temp))

        svc.download_from_torrent_files_or_urls(
            files=["upload_1.torrent"],
            urls=[],
            dl_dir="",
            dl_setting="",
            user_name="u",
            title="页面上的精确标题",
        )

        assert recorder.titles == ["页面上的精确标题"]

    def test_falls_back_to_original_name_when_torrent_invalid(self, tmp_path):
        """种子无法解析时用原始文件名，仍不暴露临时名。"""
        temp = tmp_path / "upload_2.torrent"
        temp.write_bytes(b"broken")
        recorder = _Recorder()
        svc = _service(recorder)
        svc._resolve_uploaded_torrent = lambda file_item=None, _i=None: ("Real.Movie.2020.torrent", str(temp))

        svc.download_from_torrent_files_or_urls(
            files=["upload_2.torrent"],
            urls=[],
            dl_dir="",
            dl_setting="",
            user_name="u",
        )

        assert recorder.titles == ["Real.Movie.2020"], "应去掉 .torrent 后缀"

    def test_download_history_title_is_real_name(self, tmp_path):
        """推送给下载器的媒体标题也必须是真实作品名。"""
        temp = tmp_path / "upload_3.torrent"
        _make_torrent(temp, "Real.Show.S02.1080p")
        recorder = _Recorder()
        svc = _service(recorder)
        svc._resolve_uploaded_torrent = lambda file_item=None, _i=None: ("upload_3.torrent", str(temp))

        svc.download_from_torrent_files_or_urls(
            files=["upload_3.torrent"],
            urls=[],
            dl_dir="",
            dl_setting="",
            user_name="u",
        )

        assert getattr(svc._downloader, "media_titles") == ["Real.Show.S02.1080p"]
