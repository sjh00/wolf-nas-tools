"""通用消息图片策略：插件可按内容画像改写最终通知图片."""

from __future__ import annotations

import contextlib
from collections.abc import Callable

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
    for transformer in list(_TRANSFORMERS):
        try:
            transformed = transformer(profile, value)
            if transformed:
                value = transformed
        except Exception:  # noqa: BLE001 - 单个插件失败不影响消息
            continue
    return value
