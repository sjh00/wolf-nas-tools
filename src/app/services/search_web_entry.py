"""Web 搜索统一入口 — 构建 SearchContext 走 SearchOrchestrator

替代已删除的 search_web_service.search_medias_for_web（294 行重复流水线）。
Web 特有逻辑（默认订阅站点、tmdbid 直达）在此收敛，orchestrator 保持通用。
"""

from typing import Any

import log
from app.domain.enums import SearchType, SystemConfigKey
from app.domain.mediatypes import MediaType
from app.media import meta_info
from app.services.search_context import SearchContext
from app.services.search_orchestrator import SearchOrchestrator
from app.services.web.utils import get_mediainfo_from_id


def make_web_search_fn(orchestrator: SearchOrchestrator, system_config: Any):
    """生成 WebSearchService 所需的 search_fn（签名与旧流水线一致）"""

    def search_fn(
        content: str,
        ident_flag: bool = True,
        filters: dict | None = None,
        tmdbid: str | None = None,
        media_type: MediaType | None = None,
        session_id: str | None = None,
        user_id: int | None = None,
    ) -> tuple[int, str]:
        match_media = None
        if tmdbid:
            match_media = get_mediainfo_from_id(mtype=media_type, mediaid=tmdbid)
            if not match_media:
                return -1, f"{content} 未识别到媒体信息！"

        filter_args = dict(filters or {})
        profile = str(filter_args.get("content_profile") or "").strip()
        if match_media is None and profile and profile != "default":
            # 无 TMDB ID 的来源仍需一个本地匹配目标
            match_media = meta_info(title=content, mtype=media_type or MediaType.MOVIE)
            match_media.content_profile = profile
            match_media.keyword = content
            match_media.type = media_type or MediaType.MOVIE
            match_media.anchor_provider = str(filter_args.get("metadata_source") or profile)
            match_media.anchor_external_id = str(filter_args.get("anchor_external_id") or content)
        if filter_args.get("site") == []:
            # 前端未选择站点时传空数组：归一为 None（全部可见站点）
            filter_args["site"] = None
        if "site" not in filter_args and system_config:
            _apply_default_sites(filter_args, media_type, system_config, profile)

        ctx = SearchContext(
            keyword=content,
            session_id=session_id or "web",
            search_type=SearchType.WEB,
            match_media=match_media,
            media_type=media_type,
            ident_flag=ident_flag,
            filter_args=filter_args,
            auto_download=False,
            persist=True,
            user_id=str(user_id) if user_id else None,
        )
        _, _, total, _ = orchestrator.orchestrate(ctx)
        if total:
            return 0, ""
        return 1, f"{content} 未搜索到任何资源"

    return search_fn


def _apply_default_sites(
    filter_args: dict,
    media_type: MediaType | None,
    system_config: Any,
    content_profile: str | None = None,
) -> None:
    """未显式指定站点时，应用对应载体/内容画像的默认搜索站点."""
    try:
        if media_type in (MediaType.TV, MediaType.ANIME):
            key = SystemConfigKey.DefaultSubscribeSettingTV
        else:
            profile = str(content_profile or "").strip()
            key = SystemConfigKey.DefaultSubscribeSettingMOV
            if profile and profile != "default":
                key = f"{key.value}::{profile}"
        default_setting = system_config.get(key)
        if not isinstance(default_setting, dict):
            default_setting = {}
        # None = 不限制，由索引器按用户可见站点过滤；避免空列表被当成"零站点"
        filter_args["site"] = default_setting.get("search_sites") or None
    except Exception as e:
        log.warn(f"[WebSearch]读取默认订阅设置站点失败: {e}")
