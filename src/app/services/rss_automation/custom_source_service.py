"""自定义 RSS 源管理与订阅站点适配服务。"""

import json
import time
from urllib.parse import urlparse

from app.core.exceptions import ServiceError
from app.db.repositories.custom_rss_repo_adapter import CustomRssSourceRepositoryAdapter
from app.domain.entities.custom_rss import CustomRssSourceEntity, custom_rss_id
from app.infrastructure.http.client import HttpClient
from app.infrastructure.http.config import HttpClientConfig
from app.schemas.auth import UserContext
from app.services.rss_automation.custom_source_parser import parse_feed
from app.utils.config_tools import get_proxies, get_ua

_MASK = "******"
_MAX_RESPONSE_BYTES = 5 * 1024 * 1024


class CustomRssSourceService:
    def __init__(self, repo: CustomRssSourceRepositoryAdapter | None = None):
        self._repo = repo or CustomRssSourceRepositoryAdapter()

    @staticmethod
    def _validate(data: dict) -> None:
        name = str(data.get("name") or "").strip()
        url = str(data.get("url") or "").strip()
        if not name or len(name) > 100:
            raise ServiceError("RSS 名称不能为空且不能超过 100 个字符")
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ServiceError("RSS 地址必须是有效的 HTTP/HTTPS 地址")
        headers = data.get("headers")
        if headers and headers != _MASK:
            try:
                if not isinstance(json.loads(headers), dict):
                    raise ValueError
            except (TypeError, ValueError, json.JSONDecodeError) as err:
                raise ServiceError("自定义请求头必须是 JSON 对象") from err

    @staticmethod
    def _secret(value: str | None) -> str | None:
        return _MASK if value else None

    def _to_dict(self, entity: CustomRssSourceEntity) -> dict:
        return {
            "id": entity.id,
            "ref": entity.ref,
            "name": entity.name,
            "url": entity.url,
            "domain": urlparse(entity.url).netloc,
            "enabled": entity.enabled,
            "proxy": entity.proxy,
            "cookie": self._secret(entity.cookie),
            "headers": self._secret(entity.headers),
            "last_fetch_at": entity.last_fetch_at.isoformat() if entity.last_fetch_at else None,
            "last_success_at": entity.last_success_at.isoformat() if entity.last_success_at else None,
            "last_error": entity.last_error,
            "item_count": entity.item_count,
            "health": "disabled" if not entity.enabled else ("error" if entity.last_error else "ok"),
            "created_at": entity.created_at.isoformat() if entity.created_at else None,
            "updated_at": entity.updated_at.isoformat() if entity.updated_at else None,
        }

    def list(self, user: UserContext) -> list[dict]:
        return [self._to_dict(entity) for entity in self._repo.list(user)]

    def get(self, source_id: int, user: UserContext) -> CustomRssSourceEntity:
        entity = self._repo.get(source_id, user)
        if entity is None:
            raise ServiceError("RSS 源不存在或无权访问")
        return entity

    def create(self, data: dict, user: UserContext) -> dict:
        self._validate(data)
        entity = CustomRssSourceEntity(
            user_id=user.user_id,
            name=str(data["name"]).strip(),
            url=str(data["url"]).strip(),
            enabled=bool(data.get("enabled", True)),
            proxy=bool(data.get("proxy", False)),
            cookie=str(data.get("cookie") or "").strip() or None,
            headers=str(data.get("headers") or "").strip() or None,
        )
        return self._to_dict(self._repo.create(entity))

    def update(self, source_id: int, data: dict, user: UserContext) -> dict:
        entity = self.get(source_id, user)
        merged = {
            "name": data.get("name", entity.name),
            "url": data.get("url", entity.url),
            "headers": data.get("headers", entity.headers),
        }
        self._validate(merged)
        entity.name = str(merged["name"]).strip()
        entity.url = str(merged["url"]).strip()
        entity.enabled = bool(data.get("enabled", entity.enabled))
        entity.proxy = bool(data.get("proxy", entity.proxy))
        for field in ("cookie", "headers"):
            if field not in data:
                continue
            value = str(data.get(field) or "").strip()
            if value != _MASK:
                setattr(entity, field, value or None)
        if not self._repo.update(entity, user):
            raise ServiceError("RSS 源更新失败")
        return self._to_dict(self.get(source_id, user))

    def delete(self, source_id: int, user: UserContext) -> bool:
        return self._repo.delete(source_id, user)

    def _fetch(self, entity: CustomRssSourceEntity) -> tuple[str, list[dict]]:
        headers = {
            "User-Agent": get_ua(),
            "Accept": "application/rss+xml, application/atom+xml, application/json, text/xml, */*",
        }
        if entity.headers:
            try:
                headers.update(json.loads(entity.headers))
            except (TypeError, ValueError, json.JSONDecodeError) as err:
                raise ServiceError("自定义请求头格式错误") from err
        if entity.cookie:
            headers["Cookie"] = entity.cookie
        proxies = get_proxies() if entity.proxy else None
        proxy_url = proxies.get("http") if isinstance(proxies, dict) else None
        client = HttpClient(config=HttpClientConfig(proxy_url=proxy_url, timeout=30, connect_timeout=10))
        try:
            response = client.get(entity.url, headers=headers)
            if len(response.content) > _MAX_RESPONSE_BYTES:
                raise ServiceError("RSS 响应超过 5 MB 限制")
            return parse_feed(response.text, response.headers.get("content-type", ""))
        except ServiceError:
            raise
        except Exception as err:
            raise ServiceError(f"RSS 抓取失败：{err}") from err
        finally:
            client.close()

    def test(self, data: dict, user: UserContext) -> dict:
        source_id = data.get("id")
        entity = self.get(int(source_id), user) if source_id else CustomRssSourceEntity(user_id=user.user_id)
        for field in ("name", "url", "enabled", "proxy", "cookie", "headers"):
            if field in data and data[field] != _MASK:
                setattr(entity, field, data[field])
        self._validate({"name": entity.name or "RSS 测试", "url": entity.url, "headers": entity.headers})
        started = time.monotonic()
        try:
            feed_type, items = self._fetch(entity)
            if source_id:
                self._repo.mark_fetch(entity.id, len(items))
        except Exception as err:
            if source_id:
                self._repo.mark_fetch(entity.id, 0, str(err))
            raise
        download_count = sum(bool(item.get("enclosure")) for item in items)
        return {
            "feed_type": feed_type,
            "item_count": len(items),
            "download_count": download_count,
            "missing_download_count": len(items) - download_count,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "items": items[:50],
        }

    def visible_sites(self, user: UserContext) -> list[dict]:
        return [
            {
                "id": entity.ref,
                "name": entity.name,
                "value": entity.ref,
                "source": "custom_rss",
                "builtin": False,
                "permissions": ["rss"],
                "health": "error" if entity.last_error else "ok",
            }
            for entity in self._repo.list(user, enabled_only=True)
        ]

    def can_use_ref(self, user: UserContext, ref: str) -> bool:
        source_id = custom_rss_id(ref)
        entity = self._repo.get(source_id, user) if source_id is not None else None
        return entity is not None and entity.enabled

    def poll_sites(self) -> list[dict]:
        return [
            {
                "id": -entity.id,
                "name": entity.ref,
                "display_name": entity.name,
                "rssurl": entity.url,
                "proxy": entity.proxy,
                "cookie": entity.cookie,
                "headers": entity.headers,
                "ua": get_ua(),
                "parse": False,
                "rule": None,
                "pri": 0,
                "custom_rss": True,
                "owner_user_id": entity.user_id,
                "source_id": entity.id,
            }
            for entity in self._repo.list(enabled_only=True)
        ]

    def poll_articles(self, source_id: int) -> list[dict]:
        entity = self._repo.get(source_id)
        if entity is None or not entity.enabled:
            return []
        try:
            _, items = self._fetch(entity)
            self._repo.mark_fetch(source_id, len(items))
            return items
        except Exception as err:
            self._repo.mark_fetch(source_id, 0, str(err))
            return []
