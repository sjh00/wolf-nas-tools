"""特别篇（extra/花絮）识别：Sp 独立成词也算特别篇。

约定：特别篇一律进 `extras/` 子目录，不进 Season N。
发布组常用 `Sp` 单独成词表示特别篇（`...S08end.Sp.2012...`），
只认 `SP01` 这种带序号的写法会漏掉整类文件。
"""

import pytest

from app.utils import PathUtils


class TestSpMarkerIsExtras:
    @pytest.mark.parametrize(
        "path",
        [
            "Show.Sp.2012.1080p.mkv",
            "Show.Sp.1080p.mkv",
            "/tv/某剧S08/某剧S08/剧名.House.S08end.Sp.2012.1080p.mkv",
        ],
    )
    def test_sp_word_is_extras(self, path):
        assert PathUtils.is_extras(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            "Show.SP01.1080p.mkv",
            "Show.SP12.mkv",
            "The.World.at.War.SP09.1973.BluRay.mkv",
        ],
    )
    def test_numbered_sp_still_extras(self, path):
        assert PathUtils.is_extras(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            "Spider-Man.2002.1080p.mkv",
            "Spider-Man.No.Way.Home.2021.2160p.mkv",
            "Spring.Breakdown.2012.1080p.mkv",
            "Sports.Night.2023.1080p.mkv",
            "The.SpongeBob.Movie.2004.mkv",
        ],
    )
    def test_words_containing_sp_are_not_extras(self, path):
        """以 Sp 开头的普通单词不能被误判成特别篇。"""
        assert PathUtils.is_extras(path) is False

    @pytest.mark.parametrize(
        "path",
        [
            "Show.S01E05.1080p.WEB-DL.mkv",
            "Show.S01E05.Special.1080p.mkv",
        ],
    )
    def test_normal_episode_is_not_extras(self, path):
        assert PathUtils.is_extras(path) is False

    @pytest.mark.parametrize(
        "path",
        [
            "/tv/Show/Season 0/Show - S00E01.mkv",
            "/tv/Show/Extras/behind.mkv",
            "/tv/Show/Specials/x.mkv",
        ],
    )
    def test_extras_directory_segments(self, path):
        assert PathUtils.is_extras(path) is True
