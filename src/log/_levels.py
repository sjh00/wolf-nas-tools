"""日志级别判定：用于 Web 日志缓冲区等非 loguru sink 的级别过滤.

loguru 的 sink 自带 level 过滤，但 `LOG_BUFFER`（Web 日志查看器数据源）是
直接 append 的，必须先按配置级别过滤，否则把 level 设为 info 后仍会看到 DEBUG。
"""

from __future__ import annotations

from app.core.settings import settings

LEVEL_NO: dict[str, int] = {
    "TRACE": 5,
    "DEBUG": 10,
    "INFO": 20,
    "SUCCESS": 25,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
}
_DEFAULT_LEVEL = "INFO"

_level_no_cache: int | None = None


def reset_cache() -> None:
    """清除缓存的级别（配置变更/测试用；运行时改级别仍需重启）."""
    global _level_no_cache
    _level_no_cache = None


def min_level_no() -> int:
    try:
        cfg = settings.get("log") or {}
        name = str(cfg.get("level") or _DEFAULT_LEVEL).upper()
    except Exception:  # noqa: BLE001
        name = _DEFAULT_LEVEL
    return LEVEL_NO.get(name, LEVEL_NO[_DEFAULT_LEVEL])


def is_enabled(level: str) -> bool:
    """该级别在当前配置下是否会输出（含缓冲区）."""
    global _level_no_cache
    if _level_no_cache is None:
        _level_no_cache = min_level_no()
    return LEVEL_NO.get(str(level).upper(), LEVEL_NO[_DEFAULT_LEVEL]) >= _level_no_cache
