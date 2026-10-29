"""通用消息图片策略：插件可按内容画像改写最终通知图片."""

from __future__ import annotations

import contextlib
from collections.abc import Callable

from app.media.display_image_policy import transform_display_image

_TRANSFORMERS: list[Callable[[str, str], str]] = []


def register_message_image_transformer(
    transformer: Callable[[str, str], str],
) -> None:
    if transformer not in _TRANSFORMERS:
        _TRANSFORMERS.append(transformer)


def unregister_message_image_transformer(transformer: Callable[[str, str], str]) -> None:
    with contextlib.suppress(ValueError):
        _TRANSFORMERS.remove(transformer)


def clear_message_image_transformers() -> None:
    _TRANSFORMERS.clear()


def transform_message_image(content_profile: str, image_url: str) -> str:
    value = str(image_url or "")
    profile = str(content_profile or "")
    transformers = list(_TRANSFORMERS)
    if not transformers:
        # 兼容旧插件：只注册了展示转换器时，消息仍沿用旧行为。
        return transform_display_image(profile, value)
    for transformer in transformers:
        try:
            transformed = transformer(profile, value)
            if transformed:
                value = transformed
        except Exception:  # noqa: BLE001 - 单个插件失败不影响消息
            continue
    return value
