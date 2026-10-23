"""订阅管理工具 Schema"""

from app.agent.tools.base import BaseTool, ToolLevel


class SubscribeAddTool(BaseTool):
    name = "subscribe_add"
    description = (
        "添加订阅。普通电影/电视剧使用 tmdb；插件内容画像通过 provider + external_id "
        "指定元数据来源，并传对应的 content_profile。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "影视标题或番号"},
            "media_type": {
                "type": "string",
                "enum": ["movie", "tv"],
                "description": "载体类型；AV 也使用 movie；默认 movie",
                "default": "movie",
            },
            "year": {"type": "integer", "description": "可选，年份"},
            "season": {"type": "integer", "description": "可选，电视剧季号"},
            "provider": {
                "type": "string",
                "description": (
                    "元数据来源 key；以当前注册的 metadata provider 为准，普通影视通常为 tmdb/douban/bangumi"
                ),
            },
            "external_id": {
                "type": "string",
                "description": "provider 详情 ID，例如 TMDB ID 或插件 provider 的外部 ID",
            },
            "content_id": {"type": "string", "description": "可选，番号/内容 ID；用于资源搜索关键词"},
            "metadata_ref": {
                "type": "string",
                "description": "可选，直接传 provider:external_id；与 provider/external_id 二选一",
            },
            "content_profile": {
                "type": "string",
                "description": "内容画像 key；未填时按 provider descriptor 自动推断",
                "default": "default",
            },
            "metadata_policy": {
                "type": "string",
                "description": "可选；非默认内容画像默认 provider_only:<profile>",
            },
        },
        "required": ["title"],
    }
    level = ToolLevel.WRITE
    permission = "subscription:manage"


class SubscribeListTool(BaseTool):
    name = "subscribe_list"
    description = "查询当前订阅列表（含缺失集信息）。当用户问'我订阅了什么/某剧追到哪儿了'时调用。"
    parameters = {
        "type": "object",
        "properties": {
            "media_type": {"type": "string", "enum": ["movie", "tv"], "description": "可选，限定类型"},
            "content_profile": {"type": "string", "description": "可选，限定内容画像 key"},
        },
    }
    level = ToolLevel.READ
    permission = "subscription:view"


class SubscribeDetailTool(BaseTool):
    name = "subscribe_detail"
    description = (
        "查询单个订阅的详细信息（进度、缺集、站点、过滤条件等）。当用户问'某部剧订阅到哪了/缺哪几集/某订阅详情'时调用。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "剧名（模糊匹配）"},
            "tmdb_id": {"type": "integer", "description": "可选，TMDB ID"},
            "media_type": {"type": "string", "enum": ["movie", "tv"], "description": "可选，限定类型"},
            "content_profile": {"type": "string", "description": "可选，限定内容画像 key"},
        },
        "required": ["title"],
    }
    level = ToolLevel.READ
    permission = "subscription:view"


class SubscribeDeleteTool(BaseTool):
    name = "subscribe_delete"
    description = "删除订阅。当用户要求取消某部作品的订阅时调用。"
    parameters = {
        "type": "object",
        "properties": {
            "sub_id": {"type": "integer", "description": "订阅 ID（可先 subscribe_list 查询）"},
            "media_type": {
                "type": "string",
                "enum": ["movie", "tv"],
                "description": "媒体类型，默认 movie",
                "default": "movie",
            },
        },
        "required": ["sub_id"],
    }
    level = ToolLevel.DANGEROUS
    permission = "subscription:manage"
