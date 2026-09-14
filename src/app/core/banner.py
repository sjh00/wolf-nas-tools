"""WolfNas 启动 Banner."""

import log

BANNER_LINES = [
    " __      _____  _     ___     _  _   _   ___",
    r" \ \    / / _ \| |   | __|   | \| | /_\ / __|",
    r"  \ \/\/ / (_) | |__ | _|    | .` |/ _ \ \__ \ ",
    r"   \_/\_/ \___/|____||_|     |_|\_/_/ \_|___/",
]


def print_startup_banner() -> None:
    """输出启动 Banner（逐行 log.info）."""
    for line in BANNER_LINES:
        log.info(line)
