"""测试电视剧识别改进"""

from app.domain.mediatypes import MediaType
from app.media.parser._release_groups import ReleaseGroupsMatcher
from app.media.parser.video import parse_video_title


class TestVideoParserFix:
    def test_bracket_episode(self):
        result = parse_video_title("[05] Title 1080p.mkv")
        assert result.begin_episode == 5
        assert result.type == MediaType.TV

    def test_bracket_episode_no_match_no_digits(self):
        result = parse_video_title("[abc] Title 1080p.mkv")
        assert result.begin_episode is None


class TestChineseSeasonDetection:
    def test_chinese_single_season(self):
        result = parse_video_title("Show 第2季")
        assert result.begin_season == 2
        assert result.type == MediaType.TV

    def test_chinese_season_range(self):
        result = parse_video_title("Show 第1-3季")
        assert result.begin_season == 1
        assert result.end_season == 3
        assert result.type == MediaType.TV

    def test_multitoken_chinese_season(self):
        result = parse_video_title("Show [1080p] 第1季")
        assert result.begin_season == 1


class TestChineseEpisodeDetection:
    def test_chinese_episode(self):
        result = parse_video_title("Show 第05集")
        assert result.begin_episode == 5
        assert result.type == MediaType.TV

    def test_chinese_episode_range(self):
        result = parse_video_title("Show 第01-05集")
        assert result.begin_episode is not None
        assert result.type == MediaType.TV

    def test_chinese_episode_with_tags(self):
        result = parse_video_title("Show [1080p] 第08集.mkv")
        assert result.begin_episode == 8


class TestWebSourceDetection:
    def test_amzn_source(self):
        result = parse_video_title("Show.S01E01.AMZN.WEB-DL.1080p")
        # AMZN 为 WEB 源标签，应被识别
        assert result.type == MediaType.TV

    def test_nf_source(self):
        result = parse_video_title("Show.S01E01.NF.WEB-DL.1080p")
        assert result.type == MediaType.TV


class TestSeasonEpisodeStandard:
    def test_standard_s01e01(self):
        result = parse_video_title("Show.S01E01.1080p")
        assert result.begin_season == 1
        assert result.begin_episode == 1
        assert result.type == MediaType.TV

    def test_bare_multi_episode_range(self):
        result = parse_video_title("Show.E01-E05.1080p")
        assert result.begin_episode == 1
        assert result.end_episode == 5

    def test_multi_season_pack(self):
        result = parse_video_title("Show.S01-S03.1080p.BluRay")
        assert result.begin_season == 1
        assert result.end_season == 3

    def test_audio_token_not_episode(self):
        result = parse_video_title("Dr.STONE.S04.2025.1080p.BluRay.x265.10bit.FLAC.2.0.2Audio-ADE")
        assert result.begin_season == 4
        assert result.begin_episode is None
        assert result.type == MediaType.TV


class TestReleaseGroups:
    def test_ntb_group(self):
        m = ReleaseGroupsMatcher()
        result = m.match("[NTb] Show.S01E01.1080p")
        assert "NTb" in result

    def test_qxr_group(self):
        m = ReleaseGroupsMatcher()
        result = m.match("[QxR] Show.S01E01.1080p")
        assert "QxR" in result

    def test_rar_bg_group(self):
        m = ReleaseGroupsMatcher()
        result = m.match("[RARBG] Show.S01E01.1080p")
        assert "RARBG" in result

    def test_vcb_in_anime(self):
        m = ReleaseGroupsMatcher()
        result = m.match("[VCB-Studio] Anime [BDRip]")
        assert "VCB-Studio" in result


class TestCRCNotEpisode:
    def test_crc_e859_not_episode(self):
        """CRC 标签中的数字不应被误判为集号"""
        result = parse_video_title(
            "[Yameii] Witch Hat Atelier - S01E13 [English Dub]"
            " [CR WEB-DL 1080p H264 AAC] [EE32E859] (Tongari Boushi no Atelier)"
        )
        assert result.begin_episode == 13
        assert result.end_episode is None


class TestSeasonEndingProtection:
    """修正媒体元数据识别将作品名中的 Season 误去除（对应 sjh00 26e7bde4，已由 v4 覆盖）"""

    def test_the_long_season_movie(self):
        """标题以 Season 结尾的年份不应剥离 Season（The Long Season 2017 → 电影）"""
        result = parse_video_title("The Long Season 2017 2160p WEB-DL H265 AAC-XXX")
        assert result.en_name == "The Long Season"
        assert result.year == "2017"
        assert result.type == MediaType.MOVIE

    def test_cherry_season_tv(self):
        """标题以 Season 结尾，随后 S01 应正确识别为电视剧"""
        result = parse_video_title("Cherry Season S01 2014 2160p WEB-DL H265 AAC-XXX")
        assert result.en_name == "Cherry Season"
        assert result.year == "2014"
        assert result.begin_season == 1
        assert result.type == MediaType.TV


class TestChineseTitleEnMerge:
    """中文标题前的英文片段应并入 cn_name 而非独立为 en_name（3de1b8dc）"""

    def test_en_prefix_merged_into_cn(self):
        """'Movie Name 电影名 S01' → cn_name='Movie Name 电影名', en_name=''"""
        result = parse_video_title("Movie Name 电影名 S01 1080p WEB-DL")
        assert result.cn_name == "Movie Name 电影名"
        assert result.en_name == ""
        assert result.begin_season == 1
        assert result.type == MediaType.TV

    def test_chinese_only_unaffected(self):
        """纯中文标题（无英文前缀）保持原有 cn_name 不变"""
        result = parse_video_title("特效电影名称 第一季 2023 S01 1080p")
        assert result.cn_name == "特效电影名称"
        assert result.en_name is None
        assert result.begin_season == 1
