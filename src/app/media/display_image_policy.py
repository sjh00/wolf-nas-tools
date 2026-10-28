"""通用展示图片转换器：插件可按内容画像统一裁剪/模糊所有展示图片.

探索、下载、历史、订阅与通知共用同一套规则，避免消息渠道单独维护模糊开关。
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable

_TRANSFORMERS: list[Callable[[str, str], str]] = []


def register_display_image_transformer(
    transformer: Callable[[str, str], str],
) -> None:
    if transformer not in _TRANSFORMERS:
        _TRANSFORMERS.append(transformer)


def unregister_display_image_transformer(transformer: Callable[[str, str], str]) -> None:
    with contextlib.suppress(ValueError):
        _TRANSFORMERS.remove(transformer)


def clear_display_image_transformers() -> None:
    _TRANSFORMERS.clear()


def transform_display_image(content_profile: str, image_url: str) -> str:
    """按注册顺序转换展示图片；插件失败不影响其他规则."""
    value = str(image_url or "")
    profile = str(content_profile or "")
    for transformer in list(_TRANSFORMERS):
        try:
            transformed = transformer(profile, value)
            if transformed:
                value = transformed
        except Exception:  # noqa: BLE001 - 单插件失败不影响图片展示
            continue
    return value
