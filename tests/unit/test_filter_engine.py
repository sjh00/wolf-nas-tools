"""IndexerFilterEngine 单元测试."""

from unittest.mock import MagicMock

import pytest

from app.domain.mediatypes import MediaType
from app.indexer.core.filter_engine import IndexerFilterEngine


def _meta(title: str, subtitle: str | None = None):
    m = MagicMock()
    m.rev_string = title
    m.subtitle = subtitle
    m.org_string = title
    m.get_edtion_string.return_value = ""
    m.resource_pix = ""
    m.resource_team = ""
    return m


class TestBookFilter:
    @pytest.mark.parametrize(
        "title",
        [
            "あかね噺 raw 第13巻 あかね噺1-6 7-13巻相当2024年08月26日更新",
            "[漫画] あかね噺 第13巻",
            "あかね噺 Manga Vol.13",
            "あかね噺 コミック 第13巻",
        ],
    )
    def test_reject_manga_for_anime(self, title):
        meta = _meta(title)
        match, _, msg = IndexerFilterEngine.check_torrent_filter(meta, {"type": MediaType.ANIME})
        assert not match
        assert "漫画/书籍类资源" in msg

    def test_keep_anime_bdmv_volume(self):
        meta = _meta("あかね噺 第1巻 BD")
        match, _, _ = IndexerFilterEngine.check_torrent_filter(meta, {"type": MediaType.ANIME})
        assert match

    def test_keep_anime_episode(self):
        meta = _meta("Akane Banashi S01E12 1080p NF WEB-DL AAC2.0 H 264-VARYG")
        match, _, _ = IndexerFilterEngine.check_torrent_filter(meta, {"type": MediaType.ANIME})
        assert match

    def test_reject_raw_volume(self):
        meta = _meta("あかね噺 RAW 第13巻")
        match, _, _ = IndexerFilterEngine.check_torrent_filter(meta, {"type": MediaType.ANIME})
        assert not match


class TestRulePatternSplit:
    def test_newline_and_not_comma(self):
        from app.indexer.core.filter_engine import split_rule_patterns

        raw = "[中国國][字配]|国语|國語|中文\n1080[pi]\nblu-?ray"
        parts = split_rule_patterns(raw)
        assert parts is not None
        assert len(parts) == 3
        assert "1080[pi]" in parts

    def test_webdl_without_chinese_rejected(self):
        meta = _meta("The End of Oak Street 2026 1080p AMZN WEB-DL H264 DDP5.1-SCOPE")
        meta.size = 8 * 1024**3
        meta.type = MediaType.MOVIE
        filters = [
            {
                "include": [
                    "[中国國繁简](/|\\s|\\\\|\\|)?[繁简英粤]|[英简繁](/|\\s|\\\\|\\|)?[中繁简]|繁體|简体|[中国國][字配]|国语|國語|中文",
                    "1080[pi]",
                ],
                "exclude": None,
                "size": "1,30",
                "free": None,
                "pri": 2,
                "original_language": "",
            }
        ]
        match, _, _ = IndexerFilterEngine.check_rules(meta, {"name": "日常观影-免费"}, filters)
        assert match is False

    def test_chinese_subtitle_accepted(self):
        meta = _meta("逃出绝命街 2026 1080p BluRay 中字 H264")
        meta.size = 8 * 1024**3
        meta.type = MediaType.MOVIE
        filters = [
            {
                "include": ["[中国國][字配]|国语|國語|中文", "1080[pi]"],
                "exclude": None,
                "size": "1,30",
                "free": None,
                "pri": 2,
                "original_language": "",
            }
        ]
        match, _, _ = IndexerFilterEngine.check_rules(meta, {"name": "日常观影-免费"}, filters)
        assert match is True
