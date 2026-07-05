import logging
import os
import sys
import re
import threading
import time
import inspect
from collections import deque
from html import escape
from typing import Optional, Dict
from loguru import logger as _loguru_logger

from config import Config

logging.getLogger('werkzeug').setLevel(logging.ERROR)
logging.getLogger('watchdog').setLevel(logging.INFO)
lock = threading.Lock()

LOG_QUEUE = deque(maxlen=200)
LOG_INDEX = 0

_loguru_logger_lock = threading.Lock()
_loguru_configured = False


def _configure_loguru():
    global _loguru_configured
    if _loguru_configured:
        return
    
    with _loguru_configured_lock:
        if _loguru_configured:
            return
        
        try:
            app_config = Config().get_config('app')
            logtype = app_config.get('logtype') or "console"
            loglevel = app_config.get('loglevel') or "info"
            
            handlers = []
            _loguru_logger.level(loglevel.upper())
            
            if logtype == "server":
                logserver = app_config.get('logserver', '').split(':')
                if logserver:
                    logip = logserver[0]
                    logport = int(logserver[1]) if len(logserver) > 1 else 514
                    handlers.append({
                        "sink": f"tcp://{logip}:{logport}",
                        "format": "{time:YYYY-MM-DD HH:mm:ss.SSS} |{level:8}| {file} : {module}.{function}:{line:4} | - {message}",
                        "colorize": False
                    })
            elif logtype == "file":
                logpath = os.environ.get('NASTOOL_LOG') or app_config.get('logpath') or ""
                if logpath:
                    if not os.path.exists(logpath):
                        os.makedirs(logpath)
                    handlers.append({
                        "sink": os.path.join(logpath, "nastools.log"),
                        "rotation": "5 MB",
                        "format": "{time:YYYY-MM-DD HH:mm:ss.SSS} |{level:8}| {file} : {module}.{function}:{line:4} | - {message}",
                        "colorize": False,
                        "retention": "5 days"
                    })
            
            handlers.append({
                "sink": sys.stderr,
                "format": "{time:YYYY-MM-DD HH:mm:ss.SSS} |<lvl>{level:8}</>| {file} : {module}.{function}:{line:4} | - <lvl>{message}</>",
                "colorize": True
            })
            
            _loguru_logger.configure(handlers=handlers)
            _loguru_logger.add(
                sys.stderr,
                format="{time:YYYY-MM-DD HH:mm:ss.SSS} |<lvl>{level:8}</>| {file} : {module}.{function}:{line:4} | - <lvl>{message}</>",
                colorize=True
            )
            
            logging.basicConfig(handlers=[InterceptHandler()], level=0)
            _loguru_configured = True
        except Exception:
            pass


_loguru_configured_lock = threading.Lock()


class InterceptHandler(logging.Handler):
    def emit(self, record):
        try:
            level = _loguru_logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = logging.currentframe(), 1
        while frame.f_code.co_filename == logging.__file__ or frame.f_code.co_filename == __file__:
            frame = frame.f_back
            depth += 1
        _loguru_logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


class Logger:
    logger = None
    __instance: Dict[str, 'Logger'] = {}

    def __init__(self, module: str):
        _configure_loguru()
        self.logger = _loguru_logger

    @staticmethod
    def get_instance(module: Optional[str] = None) -> 'Logger':
        if not module:
            module = "run"
        if Logger.__instance.get(module):
            return Logger.__instance.get(module)
        with lock:
            Logger.__instance[module] = Logger(module)
        return Logger.__instance.get(module)


def __append_log_queue(level, text):
    global LOG_INDEX, LOG_QUEUE
    with lock:
        text = escape(text)
        if text.startswith("【"):
            source = re.findall(r"(?<=【).*?(?=】)", text)[0]
            text = text.replace(f"【{source}】", "")
        else:
            source = "System"
        LOG_QUEUE.append({
            "time": time.strftime('%H:%M:%S', time.localtime(time.time())),
            "level": level,
            "source": source,
            "text": text})
        LOG_INDEX += 1


def debug(text: str, module: Optional[str] = None):
    frame, depth = inspect.currentframe(), 0
    while frame and (depth == 0 or frame.f_code.co_filename == __file__):
        frame = frame.f_back
        depth += 1
    return Logger.get_instance(module).logger.opt(depth=depth).debug(text)


def info(text: str, module: Optional[str] = None):
    frame, depth = inspect.currentframe(), 0
    while frame and (depth == 0 or frame.f_code.co_filename == __file__):
        frame = frame.f_back
        depth += 1
    __append_log_queue("INFO", text)
    return Logger.get_instance(module).logger.opt(depth=depth).info(text)


def error(text: str, module: Optional[str] = None):
    frame, depth = inspect.currentframe(), 0
    while frame and (depth == 0 or frame.f_code.co_filename == __file__):
        frame = frame.f_back
        depth += 1
    __append_log_queue("ERROR", text)
    return Logger.get_instance(module).logger.opt(depth=depth).error(text)


def warn(text: str, module: Optional[str] = None):
    frame, depth = inspect.currentframe(), 0
    while frame and (depth == 0 or frame.f_code.co_filename == __file__):
        frame = frame.f_back
        depth += 1
    __append_log_queue("WARN", text)
    return Logger.get_instance(module).logger.opt(depth=depth).warning(text)


def console(text):
    __append_log_queue("INFO", text)
    print(text)
