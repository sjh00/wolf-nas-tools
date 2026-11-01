"""内置 provider 的映射与 adapter."""

from .bangumi import BangumiProvider, bangumi_item_to_record
from .builtin import register_builtin_providers
from .douban import DoubanProvider, douban_detail_to_record, parse_runtime, pick_release_date
from .tmdb import TmdbProvider, tmdb_detail_to_record

__all__ = [
    "BangumiProvider",
    "DoubanProvider",
    "TmdbProvider",
    "bangumi_item_to_record",
    "douban_detail_to_record",
    "parse_runtime",
    "pick_release_date",
    "register_builtin_providers",
    "tmdb_detail_to_record",
]
