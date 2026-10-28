"""增量刮削判定：已有 NFO/海报的文件应跳过."""

from unittest.mock import MagicMock

from app.media.scraper import Scraper


def _build_scraper() -> Scraper:
    system_config = MagicMock()
    system_config.get.return_value = {
        "scraper_nfo": {"movie": {"basic": True}},
        "scraper_pic": {"movie": {"poster": True}},
    }
    return Scraper(media_service=MagicMock(), system_config=system_config)


def test_has_scraped_metadata_requires_nfo_and_poster(tmp_path):
    media_file = tmp_path / "Test.Movie.2020.mkv"
    media_file.write_bytes(b"x")
    scraper = _build_scraper()

    assert scraper._has_scraped_metadata(str(media_file)) is False

    (tmp_path / "Test.Movie.2020.nfo").write_text("<movie><plot>剧情</plot></movie>", encoding="utf-8")
    assert scraper._has_scraped_metadata(str(media_file)) is False

    (tmp_path / "poster.jpg").write_bytes(b"x")
    assert scraper._has_scraped_metadata(str(media_file)) is True


def test_has_scraped_metadata_skips_when_nothing_configured(tmp_path):
    media_file = tmp_path / "Test.Movie.2020.mkv"
    media_file.write_bytes(b"x")
    system_config = MagicMock()
    system_config.get.return_value = {"scraper_nfo": {}, "scraper_pic": {}}
    scraper = Scraper(media_service=MagicMock(), system_config=system_config)

    assert scraper._has_scraped_metadata(str(media_file)) is True


def test_incomplete_nfo_is_still_missing_even_with_poster(tmp_path):
    media_file = tmp_path / "Test.Movie.2020.mkv"
    media_file.write_bytes(b"x")
    (tmp_path / "Test.Movie.2020.nfo").write_text(
        "<movie><plot></plot><rating>0</rating><fileinfo /></movie>", encoding="utf-8"
    )
    (tmp_path / "poster.jpg").write_bytes(b"x")
    scraper = _build_scraper()

    assert scraper._has_scraped_metadata(str(media_file)) is False
