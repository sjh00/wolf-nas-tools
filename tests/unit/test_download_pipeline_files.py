"""测试文件列表层类型推断"""

import pytest

from app.downloader.pipeline import DownloadPipeline


class TestInferTypeFromFiles:
    TV_PATTERNS = [
        (["Show - 01.mkv", "Show - 02.mkv", "Show - 03.mkv"], "tv"),
        (["Show_01.mkv", "Show_02.mkv", "Show_03.mkv", "Show_04.mkv"], "tv"),
        (["S01E01.mkv", "S01E02.mkv", "S01E03.mkv"], "tv"),
        (["[Group] Title EP01 [1080P].mkv", "[Group] Title EP02 [1080P].mkv", "[Group] Title EP03 [1080P].mkv"], "tv"),
        (["path/to/Show.E01.mkv", "path/to/Show.E02.mkv", "path/to/Show.E03.mkv"], "tv"),
    ]

    MOVIE_PATTERNS = [
        (["Movie Title.mkv"], "movie"),
        (["/path/to/BDRip.mkv"], "movie"),
    ]

    NO_SIGNAL_PATTERNS = [
        ([], None),
        (["file1.mkv", "file2.mkv"], None),
        (["disc1.mkv", "disc2.mkv"], None),
        (["Show - 01.mkv", "Show - 02.mkv"], None),
        (["Show - 03.mkv", "Show - 01.mkv", "Show - 02.mkv"], None),  # non-sequential
        (["Extra.mkv", "Menu.mkv", "Trailer.mkv", "Feature.mkv"], None),  # no numbers
    ]

    @pytest.mark.parametrize("files,expected", TV_PATTERNS)
    def test_tv_patterns(self, files, expected):
        assert DownloadPipeline._infer_type_from_files(files) == expected

    @pytest.mark.parametrize("files,expected", MOVIE_PATTERNS)
    def test_movie_patterns(self, files, expected):
        assert DownloadPipeline._infer_type_from_files(files) == expected

    @pytest.mark.parametrize("files,expected", NO_SIGNAL_PATTERNS)
    def test_no_signal_patterns(self, files, expected):
        assert DownloadPipeline._infer_type_from_files(files) == expected


class TestFileTypeMismatch:
    def test_no_mismatch_when_no_files(self, capsys):
        from unittest.mock import MagicMock

        media_info = MagicMock()
        DownloadPipeline._check_file_type_mismatch(media_info, [])
        captured = capsys.readouterr()
        assert "类型推断不一致" not in captured.err

    def test_no_mismatch_when_ambiguous(self, capsys):
        from unittest.mock import MagicMock

        media_info = MagicMock()
        DownloadPipeline._check_file_type_mismatch(media_info, ["a.mkv", "b.mkv"])
        captured = capsys.readouterr()
        assert "类型推断不一致" not in captured.err


class TestStagePostMagnetDetection:
    """回归 #192：磁力判定应基于实际下载内容，而非 media_info.enclosure（原始 http）。"""

    @staticmethod
    def _pipeline():
        from unittest.mock import MagicMock

        pipe = DownloadPipeline.__new__(DownloadPipeline)
        factory = MagicMock()
        factory.get_download_visit_dir.return_value = "/visit"
        pipe._client_factory = factory
        pipe._download_history_repo = MagicMock()
        pipe._sitesubtitle = MagicMock()
        pipe._message = MagicMock()
        return pipe, factory

    def _call(self, pipe, media, content):
        pipe._stage_post(
            media_info=media,
            downloader_id="d1",
            download_id="id1",
            page_url=None,
            content=content,
            dl_files_folder="",
            dl_files=[],
            download_dir="/dl",
            downloader_name="qb",
            download_setting_name="s",
            site_info={},
            torrent_attr={},
            in_from="sub",
            user_name="u",
        )

    def test_magnet_content_sets_visit_dir_and_keeps_task(self):
        from unittest.mock import MagicMock

        pipe, factory = self._pipeline()
        media = MagicMock()
        # enclosure 仍是 http（Prowlarr/Jackett 下载接口），实际内容才是 magnet
        media.enclosure = "https://prowlarr.example/download?link=xxx"

        self._call(pipe, media, "magnet:?xt=urn:btih:ABC123")

        factory.get_client.return_value.delete_torrents.assert_not_called()
        pipe._download_history_repo.insert_download_history.assert_called_once()
        assert pipe._download_history_repo.insert_download_history.call_args.kwargs["save_dir"] == "/visit"

    def test_enclosure_magnet_still_supported(self):
        from unittest.mock import MagicMock

        pipe, factory = self._pipeline()
        media = MagicMock()
        media.enclosure = "magnet:?xt=urn:btih:XYZ"

        self._call(pipe, media, b"d8:announce...")  # content 非 magnet，但 enclosure 是

        factory.get_client.return_value.delete_torrents.assert_not_called()
        pipe._download_history_repo.insert_download_history.assert_called_once()
