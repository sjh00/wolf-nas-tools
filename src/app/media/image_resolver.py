"""MediaImageResolver — 媒体图片 URL 解析工具

从 MediaInfo 模型中剥离的图片业务逻辑，避免领域模型依赖外部服务。
"""

from app.core.constants import DEFAULT_TMDB_IMAGE


class MediaImageResolver:
    """提供媒体图片 URL 的解析规则，纯工具类，无外部依赖。"""

    @staticmethod
    def get_backdrop_image(media, default=True, original=False):
        """获取背景图 URL。"""
        if media.fanart_backdrop:
            return media.fanart_backdrop
        if media.backdrop_path:
            if original:
                return media.backdrop_path.replace("/w500", "/original")
            return media.backdrop_path
        return DEFAULT_TMDB_IMAGE if default else ""

    @staticmethod
    def get_message_image(media):
        """获取消息通知用图片 URL（优先 backdrop，fallback 到 poster / 默认图）。"""
        if media.fanart_backdrop:
            return media.fanart_backdrop
        if media.backdrop_path:
            return media.backdrop_path
        if media.poster_path:
            return media.poster_path
        # 下载/搜索结果不一定写入 poster_path，兼容站点返回的 image/poster 字段。
        for attr in ("fanart_poster", "image", "poster", "cover_url"):
            value = getattr(media, attr, None)
            if value:
                return str(value)
        provider_data = getattr(media, "provider_data", None)
        if isinstance(provider_data, dict):
            for key in ("poster", "image", "cover_url", "cover"):
                value = provider_data.get(key)
                if value:
                    return str(value)
        # 自定义画像（插件）通常只把图片放在快照里，不能回退成 TMDB 占位图。
        snapshot = getattr(media, "snapshot", None)
        images = getattr(snapshot, "images", None)
        if isinstance(images, dict):
            for kind in ("fanart", "backdrop", "poster"):
                assets = images.get(kind) or []
                if assets:
                    url = getattr(assets[0], "url", None)
                    if url:
                        return str(url)
        return DEFAULT_TMDB_IMAGE

    @staticmethod
    def get_poster_image(media, original=False):
        """获取海报图 URL。"""
        if media.poster_path:
            if original:
                return media.poster_path.replace("/w500", "/original")
            return media.poster_path
        return media.fanart_poster or ""
