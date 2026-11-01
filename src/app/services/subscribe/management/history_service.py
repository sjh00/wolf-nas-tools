"""Subscribe history service — 订阅历史记录管理."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.db.repositories.subscribe_repo_adapter import SubscribeHistoryRepositoryAdapter
from app.domain.mediatypes import MediaType
from app.schemas.auth import UserContext
from app.services.rss_processor import RssHelper

if TYPE_CHECKING:
    from app.services.subscribe_service import SubscribeService


class SubscribeHistoryService:
    """订阅历史服务 — 历史查询、删除、重做、清空."""

    def __init__(
        self,
        history_repo: SubscribeHistoryRepositoryAdapter,
        subscribe: SubscribeService,
        rss_helper: RssHelper,
    ):
        self._history_repo = history_repo
        self._subscribe = subscribe
        self._rss_helper = rss_helper

    def get_history(
        self,
        mtype: str,
        user: UserContext | None = None,
        content_profile: str | None = None,
    ) -> list[dict]:
        """获取订阅历史记录（按媒体类型、内容画像和归属过滤）."""
        return [
            rec.to_dict() for rec in self._history_repo.get_all(rtype=mtype, user=user, content_profile=content_profile)
        ]

    def delete(self, rssid: int | None, user: UserContext | None = None) -> None:
        """删除订阅历史记录（普通用户仅可删除自己的历史）."""
        if rssid is None:
            return
        if user is not None and not user.is_superadmin:
            if not self._history_repo.get_all(rid=rssid, user=user):
                return
        self._history_repo.delete(rssid)

    def redo(
        self,
        rssid: int | None,
        rtype: str,
        user: UserContext | None = None,
        content_profile: str | None = None,
    ) -> tuple[int, str]:
        """从历史记录重新订阅（保留内容画像、来源与锚点）."""
        if rssid is None:
            return -1, "缺少订阅ID"
        history = self._history_repo.get_all(rtype=rtype, rid=rssid, user=user)
        if not history:
            return -1, "订阅历史记录不存在"
        row = history[0]
        profile = str(content_profile or row.content_profile or "default")
        mtype = MediaType.MOVIE if rtype == MediaType.MOVIE.value else MediaType.TV
        if profile == "anime":
            mtype = MediaType.ANIME
        if row.season:
            season = int(str(row.season).replace("S", ""))
        else:
            season = None
        anchor_provider = str(row.anchor_provider or "").strip()
        anchor_external = str(row.anchor_external_id or "").strip()
        metadata_ref = str(row.metadata_ref or "").strip() or None
        if anchor_provider and anchor_external:
            mediaid = f"{anchor_provider}:{anchor_external}"
        elif metadata_ref:
            mediaid = metadata_ref
        else:
            mediaid = row.tmdb_id
        code, msg, _ = self._subscribe.add_rss_subscribe(
            mtype=mtype,
            name=row.name,
            year=row.year,
            channel="auto",
            season=season,
            mediaid=mediaid,
            metadata_ref=metadata_ref,
            provider=row.provider,
            content_profile=profile,
            metadata_policy=row.metadata_policy,
            naming_profile=row.naming_profile,
            total_ep=row.total,
            current_ep=row.start,
            user_id=user.user_id if user else None,
        )
        return code, msg

    def truncate(self, user: UserContext | None = None) -> None:
        """清空订阅历史记录（普通用户仅清空自己的历史）."""
        if user is not None and not user.is_superadmin:
            for rec in self._history_repo.get_all(user=user):
                self._history_repo.delete(rec.id)
            return
        self._rss_helper.truncate_rss_history()
        self._subscribe.truncate_rss_episodes()
