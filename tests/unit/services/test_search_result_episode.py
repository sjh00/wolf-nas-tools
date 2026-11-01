"""搜索结果季集补全：ES_STRING 只有季时从标题推断集数."""

from app.domain.episode_utils import infer_episode_key


class TestInferEpisodeKey:
    def test_dash_episode(self):
        title = "[黒ネズミたち] 乱世千金 / Kyouran Reijou Nia Liston - 03 (ABEMA 1920x1080 x264 AAC)"
        assert infer_episode_key("S01", title) == "S01 E03"

    def test_explicit_episode(self):
        assert infer_episode_key("S01", "[ANi] 番剧 - 12 [1080P]") == "S01 E12"
        assert infer_episode_key("S02", "Show S02E07 1080p") == "S02 E07"

    def test_chinese_episode(self):
        assert infer_episode_key("S01", "某番 第8集 1080P") == "S01 E08"

    def test_keep_existing_episode_and_movie(self):
        assert infer_episode_key("S01 E05", "show - 09") == "S01 E05"
        assert infer_episode_key("movie", "movie - 03") == "movie"

    def test_no_episode(self):
        assert infer_episode_key("S01", "某番 1080P 合集") == "S01"
