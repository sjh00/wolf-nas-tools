"""日志级别过滤（含 Web 日志缓冲区）测试."""

import logging
import uuid

import log
import log._levels as levels
from log._intercept import InterceptHandler


def _set_level(monkeypatch, no: int) -> None:
    monkeypatch.setattr(levels, "min_level_no", lambda: no)
    levels.reset_cache()


def _buffered(text: str) -> bool:
    return any(text in str(entry) for entry in log.LOG_BUFFER)


def test_debug_filtered_when_info(monkeypatch):
    _set_level(monkeypatch, 20)
    debug_probe = f"probe-debug-{uuid.uuid4().hex}"
    info_probe = f"probe-info-{uuid.uuid4().hex}"

    log.debug(debug_probe)
    log.info(info_probe)

    assert not _buffered(debug_probe)
    assert _buffered(info_probe)


def test_debug_allowed_when_debug(monkeypatch):
    _set_level(monkeypatch, 10)
    probe = f"probe-debug-{uuid.uuid4().hex}"

    log.debug(probe)

    assert _buffered(probe)


def test_intercept_handler_filtered(monkeypatch):
    _set_level(monkeypatch, 20)
    handler = InterceptHandler()
    debug_probe = f"probe-stdlib-debug-{uuid.uuid4().hex}"
    info_probe = f"probe-stdlib-info-{uuid.uuid4().hex}"

    handler.emit(logging.LogRecord("t", logging.DEBUG, __file__, 1, debug_probe, None, None))
    handler.emit(logging.LogRecord("t", logging.INFO, __file__, 1, info_probe, None, None))

    assert not _buffered(debug_probe)
    assert _buffered(info_probe)


def test_console_always_buffered(monkeypatch):
    _set_level(monkeypatch, 40)
    probe = f"probe-console-{uuid.uuid4().hex}"

    log.console(probe)

    assert _buffered(probe)
