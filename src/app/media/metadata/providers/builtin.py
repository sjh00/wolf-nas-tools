"""内置 provider 注册入口."""

from __future__ import annotations

from ..registry import MetadataRegistry, registry
from .bangumi import BangumiProvider
from .douban import DoubanProvider
from .tmdb import TmdbProvider


def register_builtin_providers(
    target: MetadataRegistry | None = None,
    *,
    tmdb: TmdbProvider | None = None,
    douban: DoubanProvider | None = None,
    bangumi: BangumiProvider | None = None,
) -> MetadataRegistry:
    """幂等注册内置 provider；已存在的 key 不重复构造."""
    target = target or registry
    if target.get_provider("tmdb") is None:
        target.register_provider(tmdb or TmdbProvider())
    if target.get_provider("douban") is None:
        target.register_provider(douban or DoubanProvider())
    if target.get_provider("bangumi") is None:
        target.register_provider(bangumi or BangumiProvider())
    return target
