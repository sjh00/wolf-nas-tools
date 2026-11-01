"""ULID 生成工具（26 字符，Crockford Base32）."""

from __future__ import annotations

import secrets
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_ulid() -> str:
    """生成 26 位 ULID：48-bit 毫秒时间戳 + 80-bit 随机数."""
    value = (int(time.time() * 1000) << 80) | secrets.randbits(80)
    chars: list[str] = []
    for _ in range(26):
        chars.append(_ALPHABET[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))
