"""豆瓣 HTML 分集抓取（PoW + Cookie）.

豆瓣 API 无分集数据，分集页需要先通过 sec.douban.com 的 PoW 挑战。
仅用于单条详情/刮削的后台补全，不在同步热路径中高频调用。
"""

from __future__ import annotations

import hashlib
import random
import re
import time
from typing import Any

import httpx
from lxml import etree

import log
from app.core.settings import settings
from app.infrastructure.cache_system import lru_cache_with_ttl
from app.utils.config_tools import get_proxies

_POW_TARGET = "0000"
_EPISODE_LINK_RE = re.compile(r"/episode/(\d+)/")


class DoubanChallengeError(RuntimeError):
    pass


def solve_pow(cha: str, difficulty: int = 4, max_iterations: int = 2_000_000) -> int:
    target = "0" * difficulty
    for nonce in range(1, max_iterations):
        if hashlib.sha512((cha + str(nonce)).encode()).hexdigest().startswith(target):
            return nonce
    raise DoubanChallengeError("PoW 求解超过上限")


def parse_episode_html(html: str, episode_number: int) -> dict[str, Any]:
    tree = etree.HTML(html or "")
    title = _first(tree, "//title/text()") or ""
    cn_name = _labeled(tree, "本集中文名") or _first(tree, "//h2//text()")
    original_name = _labeled(tree, "本集原名")
    air_date = _labeled(tree, "播放时间")
    overview = re.sub(r"更多[»>]*$", "", _labeled(tree, "剧情简介")).strip()
    if overview in {"", ".", "暂无"}:
        overview = ""
    still = _first(tree, "//div[contains(@class,'ep-pic')]//img/@src") or _first(
        tree, "//img[contains(@class,'ep')]/@src"
    )
    return {
        "episode_number": episode_number,
        "title": cn_name or original_name or title.replace(" - 豆瓣", "").strip() or f"第 {episode_number} 集",
        "original_title": original_name or None,
        "air_date": air_date or None,
        "overview": overview or None,
        "still": still or None,
    }


def _labeled(tree, label: str) -> str:
    for expr in (
        f"//*[contains(text(),'{label}')]/following-sibling::*[1]//text()",
        f"//*[contains(text(),'{label}')]/parent::*/following-sibling::*[1]//text()",
        f"//*[contains(text(),'{label}')]/parent::*//text()",
    ):
        value = "".join(str(item).strip() for item in tree.xpath(expr) if str(item).strip())
        value = value.replace(label, "").strip("：: ")
        if value:
            return value
    return ""


def _first(tree, expr: str) -> str:
    values = tree.xpath(expr)
    return str(values[0]).strip() if values else ""


class DoubanEpisodeScraper:
    """豆瓣分集页抓取器，带 PoW 与进程内 TTL 缓存."""

    def __init__(
        self,
        *,
        cookie: str | None = None,
        max_episodes: int = 60,
        min_delay: float = 1.5,
        max_delay: float = 3.5,
    ) -> None:
        self._cookie = cookie or ""
        self._max_episodes = max_episodes
        self._min_delay = min_delay
        self._max_delay = max_delay

    @lru_cache_with_ttl(maxsize=64, ttl=86400)
    def fetch(self, subject_id: str, season: int = 1) -> tuple[dict[str, Any], ...]:
        subject_id = str(subject_id).strip()
        if not subject_id:
            return ()
        proxies = get_proxies() or None
        ua = (settings.get("app") or {}).get("user_agent") or "Mozilla/5.0"
        headers = {
            "User-Agent": ua,
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": f"https://movie.douban.com/subject/{subject_id}/",
        }
        if self._cookie:
            headers["Cookie"] = self._cookie
        with httpx.Client(
            headers=headers,
            cookies={"bid": _random_bid()},
            proxy=proxies.get("http") if isinstance(proxies, dict) else None,
            follow_redirects=False,
            timeout=15,
        ) as session:
            try:
                session.get("https://www.douban.com/")
            except Exception as exc:  # noqa: BLE001 - cookie 获取失败仍尝试分集页
                log.debug(f"[DoubanEpisodes] 获取基础 cookie 失败: {exc}")
            first_url = f"https://movie.douban.com/subject/{subject_id}/episode/1/"
            first_html = self._get_with_challenge(session, first_url)
            numbers = self._episode_numbers(first_html)
            if not numbers:
                # 不是剧集/页面异常时不能盲抓 1..60，否则会触发风控并拖住队列
                return ()
            numbers = numbers[: self._max_episodes]
            results = [self._parse(numbers[0], first_html, season)]
            for number in numbers[1:]:
                time.sleep(random.uniform(self._min_delay, self._max_delay))
                html = self._get_with_challenge(
                    session, f"https://movie.douban.com/subject/{subject_id}/episode/{number}/"
                )
                results.append(self._parse(number, html, season))
        return tuple(item for item in results if item)

    def _parse(self, number: int, html: str, season: int) -> dict[str, Any]:
        item = parse_episode_html(html, number)
        item["season_number"] = season
        return item

    def _get_with_challenge(self, session: httpx.Client, url: str) -> str:
        response = session.get(url)
        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("location", "")
            if "sec.douban.com" in location:
                self._solve_challenge(session, location)
                response = session.get(url)
        if response.status_code != 200:
            raise DoubanChallengeError(f"豆瓣分集页返回 {response.status_code}")
        return response.text

    def _solve_challenge(self, session: httpx.Client, location: str) -> None:
        challenge = session.get(location)
        html = challenge.text
        tok = _input_value(html, "tok")
        cha = _input_value(html, "cha")
        red = _input_value(html, "red")
        if not (tok and cha and red):
            raise DoubanChallengeError("未找到 PoW 挑战参数")
        nonce = solve_pow(cha)
        result = session.post(
            "https://sec.douban.com/c",
            data={"tok": tok, "cha": cha, "sol": str(nonce), "red": red},
        )
        if result.status_code not in (200, 301, 302, 303):
            raise DoubanChallengeError(f"PoW 提交失败: {result.status_code}")
        log.debug(f"[DoubanEpisodes] PoW solved nonce={nonce}")

    def _episode_numbers(self, html: str) -> list[int]:
        numbers = sorted({int(value) for value in _EPISODE_LINK_RE.findall(html or "")})
        return numbers or list(range(1, self._max_episodes + 1))


def _input_value(html: str, element_id: str) -> str:
    match = re.search(rf'id="{element_id}"[^>]*value="([^"]+)"', html or "")
    return match.group(1) if match else ""


def _random_bid() -> str:
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "".join(random.choice(alphabet) for _ in range(11))
