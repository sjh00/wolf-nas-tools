"""Subscribe utils - 订阅模块共享工具函数."""

from typing import Any

from app.utils.json_utils import JsonUtils


def parse_rss_desc(desc):
    """解析订阅的JSON字段"""
    if not desc:
        return {}
    return JsonUtils.loads(desc) or {}


# 旧版本「只订阅不搜索」的哨兵值。历史订阅把它写在 search_sites 里表达
# 「只走 RSS 轮询、不做站点搜索」。v4 已经用空列表表达同一语义，但数据库里
# 仍留有带该标记的记录；不识别它会被当成一个不存在的站点名，导致
# 「站点列表为空，跳过搜索」的误导日志，前端也会显示这个假站点。
DONT_USE_SENTINEL = "#dontuse"


def normalize_sites(value: list | str | None) -> list[str] | None:
    """订阅站点入参归一化：None 保持 None，空列表保持空列表。

    保留 None 与 [] 的差别是「取消全选」能生效的前提：
    - None  = 调用方没传，按未设置处理（回退默认设置 / 沿用已有值）
    - []    = 用户取消了全选，明确一个站点都不用，搜索按零站点执行

    历史遗留的 `#dontuse` 哨兵一并折算为空列表：它表达的正是「一个站点都不搜」。
    """
    if value is None:
        return None
    if isinstance(value, str):
        items = value.split(",")
    else:
        items = list(value)
    cleaned = [str(item).strip() for item in items if str(item).strip()]
    if any(item == DONT_USE_SENTINEL for item in cleaned):
        return [item for item in cleaned if item != DONT_USE_SENTINEL]
    return cleaned


def gen_rss_note(media: Any) -> str:
    """生成订阅的JSON备注信息"""
    if not media:
        return "{}"
    note = {
        "poster": media.get_poster_image(),
        "release_date": media.release_date,
        "vote": media.vote_average,
        # 订阅媒体类型（movie/tv/anime）：动漫需与电视剧区分，避免入库到电视剧库
        "media_type": str(getattr(media, "type", "") or ""),
        # 通用题材：非 TMDB 来源也能据此判断动漫分类
        "genres": list(getattr(media, "genres", []) or []),
        "source_provider": (
            (getattr(media, "provider_data", None) or {}).get("source_provider")
            if isinstance(getattr(media, "provider_data", None), dict)
            else ""
        ),
    }
    return JsonUtils.dumps(note, separators=(", ", ": "))


def tv_filter_signature(row) -> tuple:
    """订阅过滤要求签名（实体/模型字段名兼容）.

    用于判断兄弟订阅能否共享同一下载/进度：质量/规则/免费等要求一致才联动。
    """

    def g(name):
        val = getattr(row, name, None)
        if val is None:
            val = getattr(row, name.upper(), None)
        return val

    return (
        g("filter_restype") or "",
        g("filter_pix") or "",
        g("filter_team") or "",
        str(g("filter_rule") or ""),
        g("filter_include") or "",
        g("filter_exclude") or "",
        str(g("filter_free") if g("filter_free") is not None else ""),
    )
