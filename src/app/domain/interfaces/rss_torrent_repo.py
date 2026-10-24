"""
RSS 种子领域 Repository 接口
"""

from typing import Protocol

from app.domain.entities.rss_torrent import SubscribeTorrentEntity


class IRssTorrentRepository(Protocol):
    """RSS 种子仓储接口"""

    def get_by_enclosure(self, enclosure: str) -> SubscribeTorrentEntity | None: ...
    def get_by_name(self, torrent_name: str) -> SubscribeTorrentEntity | None: ...
    def insert(
        self,
        torrent_name: str,
        enclosure: str,
        type_: str,
        title: str,
        year: str,
        season: str,
        episode: str,
        *,
        identity_id: str | None = None,
        anchor_provider: str | None = None,
        anchor_external_id: str | None = None,
        content_profile: str | None = None,
    ) -> bool: ...
    def simple_insert(self, title: str, enclosure: str) -> bool: ...
    def simple_delete(self, title: str, enclosure: str | None = None) -> bool: ...
    def truncate(self) -> bool: ...
    def is_exists_by_enclosure(self, enclosure: str) -> bool: ...
    def is_exists_by_name(self, torrent_name: str, enclosure: str | None = None) -> bool: ...
