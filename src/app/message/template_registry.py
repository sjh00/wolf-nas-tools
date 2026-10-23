"""插件消息模板注册表.

插件通过 manifest 声明 ``profile -> msg_type -> {title, text}`` 模板包，
核心只做注册、选择与回退；插件卸载后立即失效。
"""

from threading import RLock

import log
from app.message.templates import DEFAULT_MESSAGE_TEMPLATES

_ALLOWED_MSG_TYPES = frozenset(DEFAULT_MESSAGE_TEMPLATES)
_MAX_TEMPLATE_LENGTH = 20000


class MessageTemplateRegistry:
    """线程安全的消息模板包注册表."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._entries: dict[tuple[str, str], tuple[str, dict]] = {}
        self._labels: dict[str, tuple[str, str]] = {}

    def register_pack(
        self,
        plugin_id: str,
        templates: dict | None,
        labels: dict | None = None,
    ) -> None:
        """注册插件模板包；同 profile/msg_type 冲突时保留先注册者."""
        if not isinstance(templates, dict):
            return
        with self._lock:
            for profile, pack in templates.items():
                profile_key = str(profile or "").strip()
                if not profile_key or not isinstance(pack, dict):
                    continue
                for msg_type, template in pack.items():
                    msg_key = str(msg_type or "").strip()
                    if msg_key not in _ALLOWED_MSG_TYPES or not isinstance(template, dict):
                        log.warn(f"[MessageTemplate]忽略非法模板 {plugin_id}: {profile_key}/{msg_key}")
                        continue
                    title = template.get("title", "")
                    text = template.get("text", "")
                    if not isinstance(title, str) or not isinstance(text, str):
                        log.warn(f"[MessageTemplate]模板 title/text 必须为字符串 {plugin_id}: {profile_key}/{msg_key}")
                        continue
                    if len(title) + len(text) > _MAX_TEMPLATE_LENGTH:
                        log.warn(f"[MessageTemplate]模板超长，忽略 {plugin_id}: {profile_key}/{msg_key}")
                        continue
                    key = (profile_key, msg_key)
                    if key in self._entries and self._entries[key][0] != plugin_id:
                        log.warn(f"[MessageTemplate]模板冲突，保留 {self._entries[key][0]}: {profile_key}/{msg_key}")
                        continue
                    self._entries[key] = (
                        plugin_id,
                        {"title": title, "text": text},
                    )
            if isinstance(labels, dict):
                for profile, label in labels.items():
                    profile_key = str(profile or "").strip()
                    label_text = str(label or "").strip()
                    if profile_key and label_text:
                        self._labels.setdefault(profile_key, (plugin_id, label_text))

    def unregister_plugin(self, plugin_id: str) -> None:
        """移除插件注册的全部模板和标签."""
        with self._lock:
            for key, (owner, _template) in list(self._entries.items()):
                if owner == plugin_id:
                    self._entries.pop(key, None)
            for profile, (owner, _label) in list(self._labels.items()):
                if owner == plugin_id:
                    self._labels.pop(profile, None)

    def resolve(self, content_profile: str | None, msg_type: str) -> dict | None:
        """按内容画像读取插件模板；没有则返回 None."""
        profile = str(content_profile or "").strip()
        if not profile:
            return None
        with self._lock:
            entry = self._entries.get((profile, msg_type))
            if entry is None:
                return None
            return dict(entry[1])

    def label(self, content_profile: str | None) -> str:
        """内容画像展示名，例如 adult -> AV."""
        profile = str(content_profile or "").strip()
        if not profile:
            return ""
        with self._lock:
            entry = self._labels.get(profile)
            return entry[1] if entry else ""

    def list_profiles(self) -> list[dict]:
        """返回可用于消息设置页编辑的画像模板包."""
        with self._lock:
            profiles: dict[str, dict] = {}
            for (profile, msg_type), (_owner, template) in self._entries.items():
                item = profiles.setdefault(
                    profile,
                    {"key": profile, "label": self._labels.get(profile, (None, profile))[1], "templates": {}},
                )
                item["templates"][msg_type] = dict(template)
            return list(profiles.values())


message_template_registry = MessageTemplateRegistry()
