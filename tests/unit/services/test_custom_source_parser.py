"""自定义 RSS 标准报文解析测试。"""

import pytest

from app.services.rss_automation.custom_source_parser import parse_feed


class TestCustomSourceParser:
    def test_parse_rss_with_namespaces(self):
        feed_type, items = parse_feed(
            """<?xml version="1.0"?><rss xmlns:torrent="urn:torrent"><channel><item>
            <title>Example.Show.S01E02.1080p</title>
            <guid>episode-2</guid><link>https://example.com/detail/2</link>
            <enclosure url="https://example.com/download/2.torrent" length="1024" />
            <pubDate>Mon, 26 Oct 2026 01:00:00 GMT</pubDate>
            <torrent:size>2048</torrent:size><description><![CDATA[简介]]></description>
            </item></channel></rss>"""
        )
        assert feed_type == "RSS / Atom"
        assert items == [
            {
                "title": "Example.Show.S01E02.1080p",
                "enclosure": "https://example.com/download/2.torrent",
                "link": "https://example.com/detail/2",
                "size": 1024,
                "description": "简介",
                "pubdate": items[0]["pubdate"],
                "category": "",
                "guid": "episode-2",
            }
        ]
        assert items[0]["pubdate"]

    def test_parse_atom_enclosure_and_alternate(self):
        _, items = parse_feed(
            """<feed xmlns="http://www.w3.org/2005/Atom"><entry>
            <title>Movie 2026</title><id>movie-1</id>
            <link rel="alternate" href="https://example.com/movie/1" />
            <link rel="enclosure" href="magnet:?xt=urn:btih:abc" />
            <updated>2026-10-26T01:00:00Z</updated><summary>电影</summary>
            </entry></feed>"""
        )
        assert items[0]["title"] == "Movie 2026"
        assert items[0]["enclosure"].startswith("magnet:")
        assert items[0]["link"] == "https://example.com/movie/1"
        assert items[0]["guid"] == "movie-1"

    def test_parse_json_feed(self):
        feed_type, items = parse_feed(
            """{"version":"https://jsonfeed.org/version/1.1","items":[{
            "id":"1","title":"Episode 1","external_url":"https://example.com/1",
            "date_published":"2026-10-26T01:00:00Z","tags":["tv"],
            "attachments":[{"url":"https://example.com/1.torrent","size_in_bytes":4096}]
            }]}""",
            "application/feed+json",
        )
        assert feed_type == "JSON Feed"
        assert items[0]["enclosure"] == "https://example.com/1.torrent"
        assert items[0]["size"] == 4096
        assert items[0]["category"] == "tv"

    def test_torrent_link_becomes_enclosure(self):
        _, items = parse_feed(
            "<rss><channel><item><title>A</title><link>https://example.com/a.torrent</link></item></channel></rss>"
        )
        assert items[0]["enclosure"] == "https://example.com/a.torrent"
        assert items[0]["link"] == ""

    def test_reject_non_feed(self):
        with pytest.raises(ValueError, match="不是受支持"):
            parse_feed("not a feed")

        with pytest.raises(ValueError, match="items"):
            parse_feed("{}")
