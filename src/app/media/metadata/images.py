"""图片候选解析：按 provider 优先级与分辨率选择，支持失败 fallback."""

from __future__ import annotations

from app.media.metadata.models import ImageAsset, MediaMetadata


class ImageResolver:
    """从快照中产出有序图片候选 URL."""

    def candidates(
        self,
        snapshot: MediaMetadata,
        kind: str,
        *,
        locale: str | None = None,
        min_width: int | None = None,
    ) -> list[str]:
        assets = snapshot.images.get(kind) or []
        if not assets:
            return []
        rank = self._provider_rank(snapshot)
        selected = [asset for asset in assets if asset.url and (min_width is None or (asset.width or 0) >= min_width)]
        selected.sort(
            key=lambda asset: (
                rank.get(asset.provider or "", len(rank)),
                -_resolution(asset),
                0 if locale and _locale_matches(asset.locale, locale) else 1,
            )
        )
        result: list[str] = []
        seen: set[str] = set()
        for asset in selected:
            if asset.url in seen:
                continue
            seen.add(asset.url)
            result.append(asset.url)
        return result

    def best(
        self,
        snapshot: MediaMetadata,
        kind: str,
        *,
        locale: str | None = None,
        min_width: int | None = None,
    ) -> str | None:
        candidates = self.candidates(snapshot, kind, locale=locale, min_width=min_width)
        return candidates[0] if candidates else None

    def actor_candidates(self, snapshot: MediaMetadata) -> list[tuple[str, str]]:
        """返回 (演员名, 图片 URL)，按演员顺序."""
        result: list[tuple[str, str]] = []
        seen: set[str] = set()
        for credit in sorted(snapshot.credits, key=lambda item: item.order):
            if credit.role != "actor" or not credit.image_url or credit.name in seen:
                continue
            seen.add(credit.name)
            result.append((credit.name, credit.image_url))
        return result

    def _provider_rank(self, snapshot: MediaMetadata) -> dict[str, int]:
        ordered: list[str] = []
        if snapshot.primary_provider:
            ordered.append(snapshot.primary_provider)
        for ref in snapshot.refs:
            if ref.provider not in ordered:
                ordered.append(ref.provider)
        return {provider: index for index, provider in enumerate(ordered)}


def _resolution(asset: ImageAsset) -> int:
    return (asset.width or 0) * (asset.height or 0)


def _locale_matches(asset_locale: str | None, wanted: str) -> bool:
    if not asset_locale:
        return False
    return asset_locale.lower().replace("_", "-")[:2] == wanted.lower().replace("_", "-")[:2]
