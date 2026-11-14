"""从上游融合的噪声剥离规则（iT 标记 / 多音轨复数 / HDRVivid）。

这三处都是「发布信息残留在片名里」的问题：残留会让 TMDB 搜索带上一串技术词，
匹配不到正确作品，最终表现为未识别或错配。
"""

import pytest

from app.media import meta_info


class TestItalianTag:
    @pytest.mark.parametrize(
        ("name", "expect"),
        [
            ("Interstellar.2014.iT.1080p.BluRay.mkv", "Interstellar"),
            ("Dune.Part.Two.2024.iT.2160p.WEB-DL.mkv", "Dune Part Two"),
        ],
    )
    def test_it_marker_is_stripped(self, name, expect):
        assert meta_info(title=name).get_name() == expect

    def test_english_word_it_is_kept(self):
        """《It》是片名本身，不能被当成意大利语标记剥掉。"""
        assert meta_info(title="It.2017.1080p.BluRay.mkv").get_name() == "It"


class TestMultiAudioTag:
    @pytest.mark.parametrize(
        ("name", "expect"),
        [
            (
                "Breaking.Bad.S01E01.2008.2160p.WEB-DL.AAC.2Audios-CSWEB.mkv",
                "Breaking Bad",
            ),
            ("The.Last.of.Us.S01E03.1080p.FLAC.5Audios.mkv", "The Last Of"),
            ("Film.Title.2020.1080p.3Audio.mkv", "Film Title"),
        ],
    )
    def test_audio_count_is_stripped(self, name, expect):
        assert meta_info(title=name).get_name() == expect


class TestHdrVivid:
    def test_hdrvivid_is_metadata_not_title(self):
        info = meta_info(
            title="Yu.Zhou.Hu.Wei.2026.2160p.WEB-DL.HDRVivid.H.265.FLAC-CSWEB.mkv"
        )

        assert info.get_name() == "Yu Zhou Hu Wei"
        assert info.year == "2026"
