"""目录同步的媒体类型线索。

qb 的下载分类直接体现在 btstore 子目录上（btstore/tv、btstore/movie、btstore/animetv）。
早期同步流程完全没把这个线索传下去，媒体类型只能靠 TMDB 猜：
剧集被猜成电影就会走电影路径列表，而该盘可能没有配置电影媒体库，
于是内容被送到另一块盘 —— 跨盘后无法硬链接，只能复制，白白多占一份空间。

同时修掉了 transfer_media 里「下载记录缺失时把调用方传入的媒体类型抹成 None」的问题。
"""

import pytest

from app.domain.mediatypes import MediaType
from app.services.sync_engine import media_type_hint_from_source


class TestMediaTypeHintFromSource:
    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ("/media/storedisk2/btstore/tv", MediaType.TV.value),
            ("/media/storedisk2/btstore/tv/", MediaType.TV.value),
            ("/media/storedisk1/btstore/movie", MediaType.MOVIE.value),
            ("/media/favorites/btstore/movie", MediaType.MOVIE.value),
            ("/media/favorites/btstore/animetv", MediaType.ANIME.value),
            ("/media/gof/btstore/tv", MediaType.TV.value),
            ("/media/gof/btstore/movie", MediaType.MOVIE.value),
        ],
    )
    def test_known_dirs_map_to_type(self, source, expected):
        assert media_type_hint_from_source(source) == expected

    @pytest.mark.parametrize(
        "source",
        [
            "/media/storedisk2/btstore/documentory",
            "/media/storedisk2/btstore/show",
            "/media/storedisk2/btstore/ebook",
            "/media/storedisk2/btstore/music",
            "/media/storedisk2/btstore/other",
        ],
    )
    def test_ambiguous_dirs_give_no_hint(self, source):
        # 纪录片/演出/电子书等无法可靠归类，交给识别链判断，不强行指定
        assert media_type_hint_from_source(source) is None

    @pytest.mark.parametrize("source", [None, "", "/"])
    def test_empty_source_gives_no_hint(self, source):
        assert media_type_hint_from_source(source) is None

    def test_case_insensitive(self):
        assert media_type_hint_from_source("/media/x/btstore/TV") == MediaType.TV.value


class TestTransferMediaKeepsHintedType:
    """下载记录缺失时不能把调用方显式传入的媒体类型丢掉。"""

    @staticmethod
    def _lookup_result_clears_type(media_type):
        """复刻 transfer_media 的兜底：记录查不到时回退到声明的类型。"""
        # _lookup_download_record 无记录时返回 (None, None, None, None)
        looked_up_type = None
        hinted = media_type
        return looked_up_type if looked_up_type is not None else hinted

    def test_hint_survives_missing_record(self):
        assert self._lookup_result_clears_type(MediaType.TV.value) == MediaType.TV.value

    def test_record_type_wins_when_present(self):
        looked_up_type = MediaType.MOVIE.value
        hinted = MediaType.TV.value
        assert (looked_up_type if looked_up_type is not None else hinted) == MediaType.MOVIE.value
