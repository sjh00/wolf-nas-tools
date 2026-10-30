"""
LibraryRefresh Plugin v2
入库完成后刷新媒体库服务器海报墙
"""

from datetime import datetime, timedelta
from typing import Any

from app.plugin_framework.context import PluginContext


class LibraryRefreshPlugin:
    """刷新媒体库插件"""

    def __init__(self, ctx: PluginContext, mediaserver: Any):
        self.ctx = ctx
        self._mediaserver = mediaserver

    def _get_config(self):
        return self.ctx.get_config() or {}

    def on_enable(self):
        config = self._get_config()
        enable = config.get("enable", False)
        delay = config.get("delay", 0)
        if not enable:
            return
        if delay > 0:
            self.ctx.info(f"媒体库延迟刷新服务启动，延迟 {delay} 秒刷新媒体库")
        else:
            self.ctx.info("媒体库实时刷新服务启动")

    def on_disable(self):
        self.ctx.info("媒体库刷新服务已停止")

    def on_hook(self, event, data):
        if event == "plugin.config_changed":
            if data.get("plugin_id") == self.ctx.plugin_id:
                self.ctx.info("配置已变更，重载服务")
                self.on_disable()
                self.on_enable()
        elif event in ("media.transfer_finished", "media.library_synced"):
            self._handle_refresh(data)

    def _handle_refresh(self, event_data: dict):
        config = self._get_config()
        if not config.get("enable", False):
            return

        delay = config.get("delay", 0)
        if delay > 0:
            run_date = datetime.now() + timedelta(seconds=int(delay))
            self.ctx.info(f"新增延迟刷新任务，将在 {run_date.strftime('%Y-%m-%d %H:%M:%S')} 刷新媒体库")
            self.ctx.schedule_date(
                "refresh_once",
                self._refresh_library,
                run_date=run_date,
            )
        else:
            self._refresh_library(event_data)

    def _refresh_library(self, event_data: dict | None = None):
        if not event_data:
            event_data = {}

        media_info = event_data.get("media_info") if event_data else None
        profile = media_info.get("content_profile") if media_info else None
        target_path = event_data.get("target_path") or event_data.get("dest")
        route = self._mediaserver.resolve_route(profile, target_path)
        server_id = int(route.server_id) if route else self._mediaserver.resolve_server_id()
        library_id = route.library_id if route else None
        if self._mediaserver:
            mediaserver_type_obj = self._mediaserver.get_type(server_id)
            # get_type 返回字符串或枚举（不同客户端实现不一），统一转为字符串
            mediaserver_type = (
                mediaserver_type_obj.value
                if hasattr(mediaserver_type_obj, "value")
                else str(mediaserver_type_obj or "")
            )
        else:
            mediaserver_type = ""
        if media_info:
            title = media_info.get("title")
            year = media_info.get("year")
            media_name = f"{title} ({year})" if year else title
            self.ctx.info(f"媒体服务器 {mediaserver_type} 刷新媒体 {media_name} ...")
            self._mediaserver.refresh_library_by_items(
                [
                    {
                        "title": title,
                        "year": year,
                        "type": media_info.get("type"),
                        "category": media_info.get("category"),
                        "content_profile": media_info.get("content_profile"),
                        "target_path": event_data.get("dest"),
                        "file_path": event_data.get("target_path"),
                    }
                ]
            )
            # 新目录可能尚未被 Emby 扫描到，再触发路由命中的媒体库扫描
            self._mediaserver.refresh_root_library(server_id=server_id, library_id=library_id)
        else:
            self.ctx.info(f"媒体服务器 {mediaserver_type} 刷新整库 ...")
            self._mediaserver.refresh_root_library(server_id=server_id, library_id=library_id)
