from app.db.repositories.media_library_route_repo_adapter import MediaLibraryRouteRepositoryAdapter
from app.domain.entities.media_library_route import MediaLibraryRouteEntity
from app.domain.enums import SystemConfigKey
from app.infrastructure.cache_system import TokenCache
from app.mediaserver import MediaServer
from app.schemas.media import LibrarySpaceDTO
from app.services.filetransfer_service import FileTransferService as FileTransfer
from app.utils import SystemUtils


class MediaLibraryService:
    """
    媒体库业务服务
    """

    def __init__(
        self,
        media_server: MediaServer,
        filetransfer: FileTransfer,
        system_config,
        thread_executor,
        media_config_service,
        route_repo=None,
    ):
        self._media_server = media_server
        self._filetransfer = filetransfer
        self._system_config = system_config
        self._thread_executor = thread_executor
        self._media_config_service = media_config_service
        self._route_repo = route_repo or MediaLibraryRouteRepositoryAdapter()

    def get_sync_state(self, server_id: int | None = None) -> str:
        """获取指定实例同步状态文本"""
        status = self._media_server.get_mediasync_status(server_id)
        if not status:
            return "未同步"
        return "电影：{}，电视剧：{}，同步时间：{}".format(
            status.get("movie_count"),
            status.get("tv_count"),
            status.get("time"),
        )

    def get_servers(self) -> list[dict]:
        return self._media_server.get_server_options()

    def start_sync(self, librarys: list, server_id: int | None = None):
        """开始指定实例的媒体库同步。"""
        TokenCache.delete("index")
        if server_id is None:
            self._system_config.set(key=SystemConfigKey.SyncLibrary, value=librarys)
            self._thread_executor.submit(self._media_server.sync_mediaserver)
            return
        if not librarys:
            raise ValueError("请选择需要同步的媒体库")
        self._thread_executor.submit(self._media_server.sync_mediaserver, server_id, librarys)

    def refresh_library(self, server_id: int | None = None, items: list | None = None):
        """刷新指定实例，可按项目刷新或刷新整库。"""
        if items:
            return self._media_server.refresh_library_by_items(items, server_id=server_id)
        return self._media_server.refresh_root_library(server_id=server_id)

    def get_media_count(self, server_id: int | None = None) -> dict | None:
        """获取指定实例媒体库统计"""
        media_counts = self._media_server.get_medias_count(server_id)
        user_count = self._media_server.get_user_count(server_id)
        if media_counts:
            return {
                "Movie": "{:,}".format(media_counts.get("MovieCount")),
                "Series": "{:,}".format(media_counts.get("SeriesCount")),
                "Episodes": "{:,}".format(media_counts.get("EpisodeCount")) if media_counts.get("EpisodeCount") else "",
                "Music": "{:,}".format(media_counts.get("SongCount")),
                "User": user_count,
            }
        return None

    def get_play_history(self, server_id: int | None = None) -> list:
        """获取指定实例播放记录"""
        return self._media_server.get_activity_log(30, server_id=server_id)

    def get_libraries(self, server_id: int | None = None):
        """获取指定实例媒体库列表"""
        return self._media_server.get_libraries(server_id)

    def get_resume(self, num=12, server_id: int | None = None):
        """获取指定实例继续观看"""
        return self._media_server.get_resume(num=num, server_id=server_id)

    def get_latest(self, num=20, server_id: int | None = None):
        """获取指定实例最新入库"""
        return self._media_server.get_latest(num=num, server_id=server_id)

    def get_routes(self) -> list[dict]:
        servers = {item["id"]: item["name"] for item in self.get_servers()}
        return [
            {
                "id": route.id,
                "content_profile": route.content_profile,
                "target_path": route.target_path,
                "server_id": route.server_id,
                "server_name": servers.get(route.server_id, f"实例 {route.server_id}"),
                "library_id": route.library_id,
                "enabled": route.enabled,
                "note": route.note,
            }
            for route in self._route_repo.list()
        ]

    def save_route(self, data: dict, route_id: int | None = None) -> dict:
        profile = str(data.get("content_profile") or "").strip()
        target_path = str(data.get("target_path") or "").strip()
        server_id = int(data.get("server_id") or 0)
        if not profile and not target_path:
            raise ValueError("请填写目标目录或内容画像")
        if not server_id:
            raise ValueError("目标媒体服务器不能为空")
        if server_id not in {item["id"] for item in self.get_servers()}:
            raise ValueError("目标媒体服务器不存在或未启用")
        entity = MediaLibraryRouteEntity(
            id=route_id or 0,
            content_profile=profile,
            target_path=target_path,
            server_id=server_id,
            library_id=str(data.get("library_id") or "").strip() or None,
            enabled=bool(data.get("enabled", True)),
            note=str(data.get("note") or ""),
        )
        saved = self._route_repo.upsert(entity)
        self._media_server.refresh()
        return {
            "id": saved.id,
            "content_profile": saved.content_profile,
            "target_path": saved.target_path,
            "server_id": saved.server_id,
        }

    def delete_route(self, route_id: int) -> bool:
        deleted = self._route_repo.delete(route_id)
        self._media_server.refresh()
        return deleted

    def get_space_info(self) -> LibrarySpaceDTO:
        """获取媒体库存储空间"""
        media_cfg = self._media_config_service.get_config()
        movie_paths = media_cfg.get("movie_path") or []
        tv_paths = media_cfg.get("tv_path") or []
        anime_paths = media_cfg.get("anime_path") or []

        all_paths = movie_paths + tv_paths + anime_paths
        if not all_paths:
            return LibrarySpaceDTO()

        space_result = SystemUtils.calculate_space_usage(all_paths)
        if not isinstance(space_result, tuple):
            return LibrarySpaceDTO()
        total_space, free_space = space_result
        if not total_space:
            return LibrarySpaceDTO()

        used_space = total_space - free_space
        used_percent = round((used_space / total_space) * 100, 1)

        def fmt_space(val):
            if val > 1024:
                return f"{round(val / 1024, 2):,} TB"
            return f"{round(val, 2):,} GB"

        return LibrarySpaceDTO(
            used_percent=used_percent,
            free_space=fmt_space(free_space),
            used_space=fmt_space(used_space),
            total_space=fmt_space(total_space),
        )
