"""MessageGovernor - 消息治理层（去重/聚合），抑制批量通知风暴。

所有外部渠道消息统一经 `MessageDispatcher.sendmsg` 出站，治理层在该单点生效：
- immediate: 直接发送
- dedup: TTL 内相同内容只发一次
- digest: 窗口内前 N 条直接发送，超出部分聚合为一条摘要

状态放在 `GovernorStore`（Redis 优先，内存降级），使多 worker/多实例判定一致；
摘要 flush 由调度器定时任务驱动（见 scheduler_jobs）。归属用户消息以 `user_id`
隔离，避免跨用户混合（ADR-021）。
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

import log
from app.message.core.governor_store import GovernorStore, MemoryGovernorStore
from app.message.switches import MESSAGE_SWITCHES
from app.utils.json_utils import JsonUtils

_PREFIX = "msg_governor"
_BUFFER_TTL = 3600


@dataclass(frozen=True)
class GovernorPolicy:
    """单类消息的治理策略."""

    mode: str = "digest"  # immediate | dedup | digest
    threshold: int = 3  # digest: 窗口内直接发送的条数上限
    window: int = 60  # digest: 计数窗口（秒）
    dedup_ttl: int = 600  # dedup: 去重有效期（秒）


# 默认策略：高频通知聚合，插件/统计类保持即时
DEFAULT_POLICIES: dict[str, GovernorPolicy] = {
    "transfer_fail": GovernorPolicy(mode="digest"),
    "download_fail": GovernorPolicy(mode="digest"),
    "transfer_finished": GovernorPolicy(mode="digest"),
    "download_start": GovernorPolicy(mode="digest", threshold=5),
    "rss_added": GovernorPolicy(mode="digest"),
    "rss_finished": GovernorPolicy(mode="digest", threshold=5),
    "site_signin": GovernorPolicy(mode="digest"),
    "site_message": GovernorPolicy(mode="digest"),
    "site_parse_health": GovernorPolicy(mode="digest"),
    "brushtask_added": GovernorPolicy(mode="digest"),
    "brushtask_remove": GovernorPolicy(mode="digest"),
    "brushtask_pause": GovernorPolicy(mode="digest"),
    "auto_remove_torrents": GovernorPolicy(mode="digest"),
    "mediaserver_message": GovernorPolicy(mode="digest"),
    "custom_message": GovernorPolicy(mode="immediate"),
    "ptrefresh_date_message": GovernorPolicy(mode="immediate"),
}

DEFAULT_POLICY = GovernorPolicy(mode="immediate")

Sender = Callable[..., bool]
ClientResolver = Callable[[str], Any]


def build_policies(
    modes: dict[str, str] | None = None,
    thresholds: dict[str, int] | None = None,
) -> dict[str, GovernorPolicy]:
    """在默认策略之上应用配置覆盖（modes / thresholds）."""
    policies = dict(DEFAULT_POLICIES)
    for msg_type, mode in (modes or {}).items():
        policies[msg_type] = replace(policies.get(msg_type, GovernorPolicy()), mode=str(mode))
    for msg_type, threshold in (thresholds or {}).items():
        try:
            value = int(threshold)
        except (TypeError, ValueError):
            continue
        policies[msg_type] = replace(policies.get(msg_type, GovernorPolicy()), threshold=value)
    return policies


class MessageGovernor:
    """按 msg_type 策略对出站消息去重与聚合."""

    def __init__(
        self,
        sender: Sender,
        *,
        store: GovernorStore | None = None,
        client_resolver: ClientResolver | None = None,
        policies: dict[str, GovernorPolicy] | None = None,
        default_policy: GovernorPolicy | None = None,
        enabled: bool = True,
        flush_seconds: int = 30,
        max_samples: int = 3,
        template_engine: Any | None = None,
        digest_msg_type: str = "message_digest",
    ):
        self._sender = sender
        self._store = store or MemoryGovernorStore()
        self._client_resolver = client_resolver
        self._policies = dict(policies if policies is not None else DEFAULT_POLICIES)
        self._default_policy = default_policy or DEFAULT_POLICY
        self._enabled = enabled
        self._flush_seconds = max(1, int(flush_seconds))
        self._max_samples = max(1, int(max_samples))
        self._template_engine = template_engine
        self._digest_msg_type = digest_msg_type

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def flush_seconds(self) -> int:
        return self._flush_seconds

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)

    def set_policies(self, policies: dict[str, GovernorPolicy]) -> None:
        self._policies = dict(policies)

    def _policy(self, msg_type: str | None) -> GovernorPolicy:
        if not msg_type:
            return self._default_policy
        return self._policies.get(msg_type, self._default_policy)

    @staticmethod
    def _client_id(client: Any) -> str:
        if isinstance(client, dict):
            return str(client.get("id", ""))
        return ""

    @staticmethod
    def _scope(msg_type: str | None, client: Any, user_id: str) -> str:
        return f"{msg_type or ''}:{MessageGovernor._client_id(client)}:{user_id or ''}"

    def _label(self, msg_type: str | None) -> str:
        info = MESSAGE_SWITCHES.get(msg_type or "")
        return (info or {}).get("name") or msg_type or "通知"

    def intercept(
        self,
        *,
        client: Any,
        title: str | None,
        text: str | None,
        image: str | None,
        url: str | None,
        user_id: str,
        msg_type: str | None,
    ) -> bool:
        """治理判定：返回 True 表示已拦截/缓冲（调用方不再发送），False 表示放行."""
        if not self._enabled:
            return False
        policy = self._policy(msg_type)
        if policy.mode == "immediate":
            return False
        try:
            if policy.mode == "dedup":
                digest = hashlib.sha1(f"{title or ''}|{text or ''}".encode()).hexdigest()[:16]
                key = f"{_PREFIX}:dedup:{self._scope(msg_type, client, user_id)}:{digest}"
                return self._store.mark_dedup(key, policy.dedup_ttl)
            return self._intercept_digest(policy, client, user_id, msg_type, title, text)
        except Exception as e:  # noqa: BLE001
            log.warn(f"[MessageGovernor]治理判定失败，改为直接发送: {e!s}")
            return False

    def _intercept_digest(self, policy: GovernorPolicy, client, user_id, msg_type, title, text) -> bool:
        scope = self._scope(msg_type, client, user_id)
        count = self._store.incr_window(f"{_PREFIX}:win:{scope}", policy.window)
        if count <= policy.threshold:
            return False
        item = JsonUtils.dumps(
            {
                "msg_type": msg_type or "",
                "client_id": self._client_id(client),
                "user_id": str(user_id or ""),
                "title": title or "",
                "text": text or "",
            }
        )
        self._store.append(f"{_PREFIX}:buf:{scope}", item, _BUFFER_TTL)
        return True

    def _resolve_client(self, client_id: str) -> Any:
        if not client_id or self._client_resolver is None:
            return None
        try:
            return self._client_resolver(client_id)
        except Exception as e:  # noqa: BLE001
            log.debug(f"[MessageGovernor]解析客户端失败 {client_id}: {e!s}")
            return None

    def flush_once(self) -> int:
        """立即 flush 聚合缓冲，返回合并后发送的摘要条数（供调度器/测试调用）."""
        sent = 0
        try:
            keys = self._store.keys(f"{_PREFIX}:buf:*")
        except Exception as e:  # noqa: BLE001
            log.warn(f"[MessageGovernor]读取聚合缓冲失败: {e!s}")
            return 0
        for key in keys:
            try:
                raw = self._store.drain(key)
            except Exception as e:  # noqa: BLE001
                log.warn(f"[MessageGovernor]取出聚合缓冲失败 {key}: {e!s}")
                continue
            items = self._parse_items(raw)
            if not items:
                continue
            if self._send_summary(items):
                sent += 1
        return sent

    @staticmethod
    def _parse_items(raw: list[str]) -> list[dict]:
        items: list[dict] = []
        for entry in raw:
            try:
                parsed = JsonUtils.loads(entry)
            except Exception:  # noqa: BLE001
                continue
            if isinstance(parsed, dict):
                items.append(parsed)
        return items

    def _send_summary(self, items: list[dict]) -> bool:
        first = items[0]
        msg_type = first.get("msg_type") or ""
        client = self._resolve_client(str(first.get("client_id") or ""))
        label = self._label(msg_type)
        samples = [(it.get("title") or "").strip() for it in items[: self._max_samples]]
        samples = [s for s in samples if s]
        more = len(items) - len(samples)
        title, text = self._render_summary(client, label, len(items), samples, more)
        try:
            self._sender(
                client=client,
                title=title,
                text=text,
                image=None,
                url=None,
                user_id=str(first.get("user_id") or ""),
            )
            return True
        except Exception as e:  # noqa: BLE001
            log.warn(f"[MessageGovernor]摘要发送失败: {e!s}")
            return False

    def _render_summary(self, client, label: str, count: int, samples: list[str], more: int) -> tuple[str, str]:
        """优先用消息模板渲染摘要，无引擎/模板缺失时回退内置文案."""
        if self._template_engine is not None:
            variables = {"label": label, "count": count, "samples": samples, "more": more}
            try:
                title, text = self._template_engine.apply_client_template(
                    client or {}, self._digest_msg_type, variables
                )
                if title:
                    return title, text or ""
            except Exception as e:  # noqa: BLE001
                log.warn(f"[MessageGovernor]摘要模板渲染失败，回退内置文案: {e!s}")
        title = f"[{count} 条{label}已合并]"
        text = "；".join(samples)
        if more > 0:
            text = f"{text}；…另有 {more} 条" if text else f"…另有 {more} 条"
        return title, text
