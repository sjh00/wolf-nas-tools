"""标准 RSS、Atom 与 JSON Feed 解析。"""

import json
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse

from defusedxml import ElementTree


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _children(node, *names: str):
    expected = {name.lower() for name in names}
    return [child for child in list(node) if _local_name(str(child.tag)) in expected]


def _first_text(node, *names: str) -> str:
    for child in _children(node, *names):
        text = str(child.text or "").strip()
        if text:
            return text
    return ""


def _first_attr(node, names: tuple[str, ...], attr: str) -> str:
    for child in _children(node, *names):
        value = str(child.attrib.get(attr) or "").strip()
        if value:
            return value
    return ""


def _as_size(value: Any) -> int:
    try:
        return max(0, int(float(str(value or "0").strip())))
    except (TypeError, ValueError):
        return 0


def _as_timestamp(value: str) -> float | str:
    value = str(value or "").strip()
    if not value:
        return ""
    try:
        return parsedate_to_datetime(value).timestamp()
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return ""


def _looks_like_download(url: str) -> bool:
    lowered = url.lower()
    if lowered.startswith("magnet:"):
        return True
    parsed = urlparse(url)
    return parsed.path.lower().endswith(".torrent") or any(
        key in parsed.query.lower() for key in ("passkey=", "authkey=", "torrent_pass=")
    )


def _xml_item(node) -> dict[str, Any]:
    links = _children(node, "link")
    link = _first_text(node, "link")
    enclosure = _first_attr(node, ("enclosure",), "url")
    for atom_link in links:
        href = str(atom_link.attrib.get("href") or "").strip()
        rel = str(atom_link.attrib.get("rel") or "alternate").lower()
        if href and rel == "enclosure" and not enclosure:
            enclosure = href
        elif href and rel == "alternate" and not link:
            link = href
    enclosure = enclosure or _first_text(node, "magneturi", "magneturl")
    if not enclosure and _looks_like_download(link):
        enclosure, link = link, ""
    length = _first_attr(node, ("enclosure",), "length")
    size = _as_size(length or _first_text(node, "size", "contentlength"))
    published = _first_text(node, "pubdate", "published", "updated", "date")
    return {
        "title": _first_text(node, "title"),
        "enclosure": enclosure,
        "link": link,
        "size": size,
        "description": _first_text(node, "description", "summary", "content"),
        "pubdate": _as_timestamp(published),
        "category": _first_text(node, "category"),
        "guid": _first_text(node, "guid", "id"),
    }


def parse_xml_feed(text: str) -> list[dict[str, Any]]:
    """解析 RSS 2.0 item 与 Atom entry，忽略命名空间前缀。"""
    root = ElementTree.fromstring(text.encode("utf-8"))
    nodes = [node for node in root.iter() if _local_name(str(node.tag)) in ("item", "entry")]
    return [item for item in (_xml_item(node) for node in nodes) if item["title"]]


def parse_json_feed(text: str) -> list[dict[str, Any]]:
    """解析 JSON Feed 1.x 及兼容 items 数组。"""
    payload = json.loads(text)
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise ValueError("JSON Feed 缺少 items 数组")
    result = []
    for item in items:
        if not isinstance(item, dict) or not item.get("title"):
            continue
        attachments = item.get("attachments") or []
        attachment = attachments[0] if attachments and isinstance(attachments[0], dict) else {}
        link = str(item.get("external_url") or item.get("url") or "")
        enclosure = str(attachment.get("url") or "")
        if not enclosure and _looks_like_download(link):
            enclosure, link = link, ""
        result.append(
            {
                "title": str(item["title"]).strip(),
                "enclosure": enclosure,
                "link": link,
                "size": _as_size(attachment.get("size_in_bytes")),
                "description": str(item.get("content_text") or item.get("content_html") or ""),
                "pubdate": _as_timestamp(str(item.get("date_published") or "")),
                "category": ",".join(str(tag) for tag in (item.get("tags") or [])),
                "guid": str(item.get("id") or ""),
            }
        )
    return result


def parse_feed(text: str, content_type: str = "") -> tuple[str, list[dict[str, Any]]]:
    """按内容自动识别 Feed 格式，返回格式和统一报文。"""
    stripped = text.lstrip("\ufeff\x00\t\r\n ")
    if not stripped:
        raise ValueError("RSS 响应为空")
    if "json" in content_type.lower() or stripped.startswith("{"):
        return "JSON Feed", parse_json_feed(stripped)
    if stripped.startswith("<"):
        return "RSS / Atom", parse_xml_feed(stripped)
    raise ValueError("响应不是受支持的 RSS、Atom 或 JSON Feed")
