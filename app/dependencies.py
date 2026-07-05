"""
依赖注入模块 - 集中管理核心服务单例
解决循环导入问题，统一管理服务初始化顺序
"""
from typing import Optional, Dict, Any
import threading

from app.media import Media
from app.downloader import Downloader
from app.indexer import Indexer
from app.sites import Sites
from app.message import Message
from app.mediaserver import MediaServer
from app.filter import Filter
from app.helper import (
    DbHelper,
    ProgressHelper,
    ThreadHelper,
    SiteHelper,
    IndexerHelper,
    RedisHelper,
    RssHelper
)

lock = threading.Lock()


class Dependencies:
    """依赖注入容器"""
    _instances: Dict[str, Any] = {}
    _initialized = False

    @classmethod
    def get_media(cls) -> Media:
        """获取媒体服务"""
        if 'media' not in cls._instances:
            with lock:
                if 'media' not in cls._instances:
                    cls._instances['media'] = Media()
        return cls._instances['media']

    @classmethod
    def get_downloader(cls) -> Downloader:
        """获取下载器服务"""
        if 'downloader' not in cls._instances:
            with lock:
                if 'downloader' not in cls._instances:
                    cls._instances['downloader'] = Downloader()
        return cls._instances['downloader']

    @classmethod
    def get_indexer(cls) -> Indexer:
        """获取索引器服务"""
        if 'indexer' not in cls._instances:
            with lock:
                if 'indexer' not in cls._instances:
                    cls._instances['indexer'] = Indexer()
        return cls._instances['indexer']

    @classmethod
    def get_sites(cls) -> Sites:
        """获取站点服务"""
        if 'sites' not in cls._instances:
            with lock:
                if 'sites' not in cls._instances:
                    cls._instances['sites'] = Sites()
        return cls._instances['sites']

    @classmethod
    def get_message(cls) -> Message:
        """获取消息服务"""
        if 'message' not in cls._instances:
            with lock:
                if 'message' not in cls._instances:
                    cls._instances['message'] = Message()
        return cls._instances['message']

    @classmethod
    def get_mediaserver(cls) -> MediaServer:
        """获取媒体服务器服务"""
        if 'mediaserver' not in cls._instances:
            with lock:
                if 'mediaserver' not in cls._instances:
                    cls._instances['mediaserver'] = MediaServer()
        return cls._instances['mediaserver']

    @classmethod
    def get_filter(cls) -> Filter:
        """获取过滤器服务"""
        if 'filter' not in cls._instances:
            with lock:
                if 'filter' not in cls._instances:
                    cls._instances['filter'] = Filter()
        return cls._instances['filter']

    @classmethod
    def get_dbhelper(cls) -> DbHelper:
        """获取数据库助手"""
        if 'dbhelper' not in cls._instances:
            with lock:
                if 'dbhelper' not in cls._instances:
                    cls._instances['dbhelper'] = DbHelper()
        return cls._instances['dbhelper']

    @classmethod
    def get_progress(cls) -> ProgressHelper:
        """获取进度助手"""
        if 'progress' not in cls._instances:
            with lock:
                if 'progress' not in cls._instances:
                    cls._instances['progress'] = ProgressHelper()
        return cls._instances['progress']

    @classmethod
    def get_thread(cls) -> ThreadHelper:
        """获取线程助手"""
        if 'thread' not in cls._instances:
            with lock:
                if 'thread' not in cls._instances:
                    cls._instances['thread'] = ThreadHelper()
        return cls._instances['thread']

    @classmethod
    def get_site_helper(cls) -> SiteHelper:
        """获取站点助手"""
        if 'site_helper' not in cls._instances:
            with lock:
                if 'site_helper' not in cls._instances:
                    cls._instances['site_helper'] = SiteHelper()
        return cls._instances['site_helper']

    @classmethod
    def get_indexer_helper(cls) -> IndexerHelper:
        """获取索引器助手"""
        if 'indexer_helper' not in cls._instances:
            with lock:
                if 'indexer_helper' not in cls._instances:
                    cls._instances['indexer_helper'] = IndexerHelper()
        return cls._instances['indexer_helper']

    @classmethod
    def get_redis(cls) -> RedisHelper:
        """获取Redis助手"""
        if 'redis' not in cls._instances:
            with lock:
                if 'redis' not in cls._instances:
                    cls._instances['redis'] = RedisHelper()
        return cls._instances['redis']

    @classmethod
    def get_rss_helper(cls) -> RssHelper:
        """获取RSS助手"""
        if 'rss_helper' not in cls._instances:
            with lock:
                if 'rss_helper' not in cls._instances:
                    cls._instances['rss_helper'] = RssHelper()
        return cls._instances['rss_helper']

    @classmethod
    def init_all(cls):
        """初始化所有核心服务"""
        if cls._initialized:
            return
        with lock:
            if cls._initialized:
                return
            cls.get_dbhelper()
            cls.get_media()
            cls.get_downloader()
            cls.get_indexer()
            cls.get_sites()
            cls.get_message()
            cls.get_mediaserver()
            cls.get_filter()
            cls.get_progress()
            cls.get_thread()
            cls._initialized = True
