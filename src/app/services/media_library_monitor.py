"""MediaLibraryMonitorService - 监听媒体库目录，手动放入的媒体文件自动识别/刮削.

用户手动把（压制好的）媒体文件放进媒体库目录后，本服务监听 movie/tv/anime 目录，
检测到媒体文件出现/变动时自动触发刮削（生成 nfo/海报），使 nas-tools/media server
能"看得见、管理得动"手动放入的媒体。

刮削严格遵循设置（MediaConfig.nfo_poster）：开启才刮削；关闭则仅依赖文件索引服务
（file_index_service 每 5 分钟全量扫描）让文件在文件管理界面对用户可见，不做额外处理。

复用 MediaFileService.scrap_media_path（底层为 Scraper.folder_scraper：解析文件名→查 TMDB→生成 nfo/海报）。
"""

import os
import threading

import log
from app.core.constants import RMT_MEDIAEXT
from app.core.settings import settings
from app.infrastructure.distributed_lock.lock_manager import get_lock_manager
from app.utils import ExceptionUtils
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

_observer_lock = threading.Lock()


class _MediaLibraryEventHandler(FileSystemEventHandler):
    """媒体库目录文件事件处理器：媒体文件变化时触发刮削。"""

    def __init__(self, monitor_service, root: str):
        self._svc = monitor_service
        self._root = root

    def _handle(self, path: str) -> None:
        self._svc.on_media_file_event(path)

    def on_created(self, event) -> None:
        if not event.is_directory:
            self._handle(event.src_path)

    def on_moved(self, event) -> None:
        if not event.is_directory:
            self._handle(event.dest_path)

    def on_modified(self, event) -> None:
        if not event.is_directory:
            self._handle(event.src_path)


class MediaLibraryMonitorService:
    """监听媒体库目录并自动识别/刮削手动放入的媒体文件。"""

    def __init__(self, media_file_service, thread_executor=None):
        self._media_file = media_file_service
        self._thread_executor = thread_executor
        self._observers: list[Observer | PollingObserver] = []
        self._seen: set[str] = set()  # 最近处理过的路径，去重（监控事件可能重复触发）

    # ---------- 生命周期 ----------

    def start(self) -> None:
        """启动媒体库目录监控（每个媒体库根目录一个 observer）。

        为避免频繁唤醒磁盘：
        - 使用事件驱动的 Observer（inotify/FSEvents/ReadDirectoryChangesW），
          只在媒体库目录发生实际文件变化时才唤醒磁盘，不再每 30 秒轮询。
        - 仅当刮削开关（MediaConfig.nfo_poster）开启时才监听；关闭刮削则跳过
          监听（文件管理靠 file_index_service 索引即可）。
        """
        self.stop()
        if not self._scrape_enabled():
            log.info("[MediaLibraryMonitor]刮削已关闭，不启动媒体库监控（避免无谓的目录监听）")
            return
        roots = self._get_library_roots()
        if not roots:
            log.info("[MediaLibraryMonitor]未配置媒体库路径，跳过监控")
            return
        for root in roots:
            if not os.path.isdir(root):
                log.warn(f"[MediaLibraryMonitor]媒体库目录不存在：{root}")
                continue
            try:
                # 事件驱动，不轮询磁盘（仅在目录内容变化时收到事件）
                obs = Observer()
                obs.schedule(_MediaLibraryEventHandler(self, root), path=root, recursive=True)
                obs.daemon = True
                obs.start()
            except Exception as e:  # noqa: BLE001
                log.error(f"[MediaLibraryMonitor]{root} 监控启动失败：{e}")
                continue
            with _observer_lock:
                self._observers.append(obs)
            log.info(f"[MediaLibraryMonitor]{root} 监控已启动（事件驱动）")
        if self._observers:
            log.info(f"[MediaLibraryMonitor]媒体库监控已启动，共 {len(self._observers)} 个目录")

    def stop(self) -> None:
        with _observer_lock:
            for obs in self._observers:
                try:
                    obs.stop()
                    obs.join(timeout=5)
                except Exception as e:  # noqa: BLE001
                    log.error(f"[MediaLibraryMonitor]停止监控异常：{e}")
            self._observers = []

    # ---------- 事件处理 ----------

    def on_media_file_event(self, path: str) -> None:
        """媒体文件变化事件：判断刮削开关并触发刮削（目录级）。"""
        try:
            if not path:
                return
            ext = os.path.splitext(path)[-1].lower()
            if ext not in RMT_MEDIAEXT:
                return
            # 去重：同一路径短时间内只处理一次
            if path in self._seen:
                return
            self._seen.add(path)
            if len(self._seen) > 5000:
                self._seen.clear()
            # 刮削开关（MediaConfig.nfo_poster）
            if not self._scrape_enabled():
                log.debug(f"[MediaLibraryMonitor]刮削已关闭，跳过 {path}")
                return
            parent = os.path.dirname(path)
            if not parent or not os.path.isdir(parent):
                return
            log.info(f"[MediaLibraryMonitor]检测到媒体文件：{path}，触发目录刮削：{parent}")
            self._media_file.scrap_media_path(path=parent, backend_id="local")
        except Exception as e:  # noqa: BLE001
            log.error(f"[MediaLibraryMonitor]媒体文件事件处理失败：{e}")
            ExceptionUtils.exception_traceback(e)

    # ---------- 辅助 ----------

    def _get_library_roots(self) -> list[str]:
        """获取媒体库根目录（movie/tv/anime）。"""
        roots: list[str] = []
        media = settings.get("media") or {}
        for key in ("movie_path", "tv_path", "anime_path"):
            paths = media.get(key) or []
            if isinstance(paths, str):
                paths = [paths]
            for p in paths:
                if p:
                    roots.append(os.path.normpath(p).replace("\\", "/"))
        return roots

    def _scrape_enabled(self) -> bool:
        """刮削是否开启（MediaConfig.nfo_poster）。"""
        try:
            media = settings.get("media") or {}
            return bool(media.get("nfo_poster", True))
        except Exception:  # noqa: BLE001
            return True
