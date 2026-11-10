"""按识别记录的源文件定位下载器任务.

识别记录存的是源文件目录 + 文件名，而下载历史的 SAVE_PATH 是种子的保存目录。
两者通常相差若干层（多文件种子还会多出「剧名/Season 1」），所以要从源目录
逐级向上回溯，找到与之相等的 SAVE_PATH，才能拿到种子 hash。

只做精确相等匹配：SAVE_PATH 与某个上级目录完全相同才算命中，避免按名称模糊
匹配到别的作品，把用户的种子误删。
"""

import os

# 回溯层数上限：种子保存目录不会嵌在源文件目录的深处，层数过多只会放大误匹配面
MAX_UP_LEVELS = 5


def candidate_dirs(source_path: str, max_up: int = MAX_UP_LEVELS) -> list[str]:
    """源目录及其全部上级目录（由近到远），用于与 SAVE_PATH 精确比对."""
    raw = str(source_path or "").strip()
    if not raw:
        return []
    current = os.path.normpath(raw)
    result = [current]
    for _ in range(max_up):
        parent = os.path.dirname(current)
        if not parent or parent == current:
            break
        result.append(parent)
        current = parent
    return result


def locate_download_tasks(
    source_refs: list[dict],
    list_history_by_path,
    max_up: int = MAX_UP_LEVELS,
) -> dict[str, set[str]]:
    """返回 {下载器: {种子 hash}}，用于「同时移除种子」。

    :param source_refs: 每项含 source_path（识别记录的源目录）
    :param list_history_by_path: 接收目录、返回下载历史列表的函数
    """
    tasks: dict[str, set[str]] = {}
    seen_dirs: set[str] = set()
    for ref in source_refs or []:
        for directory in candidate_dirs(str(ref.get("source_path") or ""), max_up):
            if directory in seen_dirs:
                continue
            seen_dirs.add(directory)
            try:
                records = list_history_by_path(directory) or []
            except Exception:  # noqa: BLE001 - 定位失败按未命中处理
                continue
            for record in records:
                downloader = str(getattr(record, "DOWNLOADER", "") or "")
                download_id = str(getattr(record, "DOWNLOAD_ID", "") or "")
                if not downloader or not download_id or download_id == "0":
                    continue
                tasks.setdefault(downloader, set()).add(download_id)
    return tasks
