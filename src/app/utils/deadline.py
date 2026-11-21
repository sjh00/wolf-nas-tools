"""带期限的同步调用：超时就放弃等待，不让请求无限拖住。

用途：API 请求路径上需要调用「可能很慢的同步逻辑」（如识别 + 多版本检测，
含 TMDB 网络请求与文件系统扫描）。这类逻辑一旦遇到网络抖动或大目录扫描，
会把 HTTP 请求拖到客户端超时——用户看到「超时失败」，实际后端仍在跑，
于是误以为失败而重复操作。

约定：超时返回 ``default``，被放弃的那次调用在后台继续执行（其结果通常
会写入元数据缓存，后续后台流水线直接受益），因此不浪费已完成的工作。
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import TypeVar

import log

_T = TypeVar("_T")

# 专用线程池：与 API 线程池、下载线程池隔离，避免相互挤占。
# 少数几个槽位即可——超时后我们会立刻返回，不排队等待。
_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="wolfnas-deadline")


def run_with_deadline(
    func: Callable[[], _T],
    timeout_seconds: float,
    default: _T | None = None,
    label: str = "",
) -> _T | None:
    """在专用线程池里执行 ``func``，超过 ``timeout_seconds`` 返回 ``default``。

    :param timeout_seconds: 期限秒数；<=0 表示不限，直接同步执行
    :param label: 日志标识，便于定位是哪个调用超时
    """
    if timeout_seconds <= 0:
        return func()
    try:
        future = _EXECUTOR.submit(func)
    except RuntimeError as e:  # 池已关闭（进程退出中）
        log.debug(f"[Deadline]{label} 线程池不可用，改同步执行: {e}")
        return func()
    try:
        return future.result(timeout=timeout_seconds)
    except FutureTimeout:
        log.warn(f"[Deadline]{label} 超过 {timeout_seconds:.1f}s 未完成，先放行（后台继续执行）")
        return default
    except Exception as e:  # noqa: BLE001 - 业务异常照常上抛，由调用方处理
        raise e
