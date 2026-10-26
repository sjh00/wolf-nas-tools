"""媒体服务器插件的共享生命周期逻辑."""

import log
from app.db.repositories.config_repo_adapter import MediaServerRepositoryAdapter


def disable_mediaserver_record(server_type: str) -> None:
    """禁用指定类型的媒体服务器记录（插件禁用时随动停用，配置保留，重新启用时恢复）"""
    try:
        repo = MediaServerRepositoryAdapter()
        for s in repo.get_media_servers() or []:
            if getattr(s, "NAME", None) == server_type and getattr(s, "ENABLED", False):
                repo.update_media_server(sid=s.ID, name=s.NAME, enabled=0, config=s.CONFIG, is_default=s.IS_DEFAULT)
    except Exception as e:  # noqa: BLE001
        log.error(f"[Plugin]禁用媒体服务器记录失败 {server_type}: {e}")


def resolve_plugin_server_id(media_server, config: dict, target_path=None, content_profile=None):
    """解析插件目标实例：显式配置优先，其次目录和画像，最后默认实例。"""
    raw = (config or {}).get("server_id")
    try:
        server_id = int(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        server_id = None
    return media_server.resolve_server_id(server_id, content_profile, target_path)


def resolve_plugin_server_ids(media_server, config: dict, target_path=None, content_profile=None) -> list[int | None]:
    """解析插件需要同时处理的多个实例，兼容旧 server_id 单选配置。"""
    raw_ids = (config or {}).get("server_ids") or []
    if isinstance(raw_ids, str):
        raw_ids = raw_ids.split(",")
    server_ids = []
    for raw in raw_ids:
        try:
            if raw not in (None, ""):
                server_ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    if server_ids:
        return server_ids
    return [resolve_plugin_server_id(media_server, config, target_path, content_profile)]
