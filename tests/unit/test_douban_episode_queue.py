"""豆瓣分集后台队列测试."""

from app.infrastructure.external.doubanapi.episode_queue import EpisodeEnrichmentQueue


class _FakeScraper:
    def __init__(self):
        self.calls = []

    def fetch(self, subject_id, season=1):
        self.calls.append((subject_id, season))
        return ({"episode_number": 1, "title": "第一集", "season_number": season},)


def test_queue_deduplicates_and_caches_result():
    scraper = _FakeScraper()
    queue = EpisodeEnrichmentQueue(scraper=scraper, max_workers=1)

    first = queue.get("1", 1)
    second = queue.get("1", 1)

    assert len(first) == 1
    assert first == second
    assert scraper.calls == [("1", 1)]

    queue.clear()
    queue.get("1", 1)
    assert len(scraper.calls) == 2


def test_queue_submit_without_wait():
    scraper = _FakeScraper()
    queue = EpisodeEnrichmentQueue(scraper=scraper, max_workers=1)

    result = queue.get("2", 1, wait=False)

    assert result == ()
    queue.get("2", 1)
    assert scraper.calls == [("2", 1)]
