"""MediaConsistencyService - 媒体库一致性校验/跨盘整理感知.

用户手动在文件资源管理器里整理（移动/跨盘调换）媒体库文件后，
TRANSFER_HISTORY 记录的 DEST 路径可能与实际磁盘不一致，导致文件管理"遗漏/出错"。

本服务对比转移记录与磁盘真实状态：
- 记录 DEST 存在 -> 正常
- 记录 DEST 不存在，但文件索引（file_index_service 全盘扫描）中存在"同名文件"唯一候选
  -> 判为手动移动后的新位置，自动更新记录 DEST
- 找不到匹配候选 -> 标注为"丢失"

匹配依据：DEST_FILENAME（文件名）+ 唯一性（同一文件名在索引中唯一，避免跨作品同名误判）。
跨盘移动后文件名通常不变，可可靠追踪；你做种源+媒体库一起移动时同样适用（不依赖旧路径仍存在）。
"""

import os

import log


class MediaConsistencyService:
    """媒体库一致性校验服务。"""

    def __init__(self, history_manager, file_index_service):
        self._history = history_manager
        self._file_index = file_index_service

    def check_library_consistency(self, page_size: int = 500, max_pages: int = 100) -> dict:
        """扫描全部转移记录，修正/标注 DEST 不一致的记录。

        :return: {checked, fixed, missing, moved_records}
        """
        checked = 0
        fixed = 0
        missing = 0
        missing_records: list[dict] = []
        for page in range(1, max_pages + 1):
            total, records = self._history.get_transfer_history(search=None, page=page, rownum=page_size)
            if not records:
                break
            for rec in records:
                dest_path = getattr(rec, "DEST_PATH", "") or ""
                dest_filename = getattr(rec, "DEST_FILENAME", "") or ""
                logid = getattr(rec, "ID", None)
                checked += 1
                if not dest_path or not dest_filename:
                    continue
                full = os.path.join(dest_path, dest_filename)
                if os.path.exists(full):
                    continue
                # DEST 不存在：尝试用文件名在索引中定位新位置
                candidate = self._find_unique_candidate(dest_filename, dest_path)
                if candidate and logid:
                    try:
                        self._history.update_transfer_dest(
                            logid=logid,
                            new_dest_path=candidate["path"],
                            new_dest_filename=dest_filename,
                        )
                        fixed += 1
                        log.info(f"[Consistency]转移记录 {logid} 目标已移动到 {candidate['path']}")
                    except Exception as e:  # noqa: BLE001
                        log.error(f"[Consistency]更新记录 {logid} 失败：{e}")
                else:
                    missing += 1
                    missing_records.append(
                        {
                            "id": logid,
                            "dest_path": dest_path,
                            "dest_filename": dest_filename,
                            "expected": full,
                        }
                    )
            if len(records) < page_size:
                break
        return {
            "checked": checked,
            "fixed": fixed,
            "missing": missing,
            "missing_records": missing_records,
        }

    def _find_unique_candidate(self, filename: str, old_path: str) -> dict | None:
        """在文件索引中找"同名文件"唯一候选（路径不同于旧路径）。"""
        if not filename or not self._file_index:
            return None
        try:
            matches = self._file_index.find_by_name(filename, limit=50)
        except Exception as e:  # noqa: BLE001
            log.debug(f"[Consistency]检索同名文件失败 {filename}: {e}")
            return None
        # 过滤掉旧路径本身（若旧路径仍有同名项则不修正）
        candidates = [m for m in matches if m.get("path") != os.path.normpath(old_path)]
        if len(candidates) == 1:
            c = candidates[0]
            return {"path": os.path.dirname(c["path"]).replace("\\", "/"), "filename": c["name"]}
        return None
