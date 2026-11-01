"""Provider 无关的元数据引擎（ADR-025）.

P0 只包含 DTO、错误、注册表、策略与合成器；不接线上链路。
"""

from .composer import MetadataComposer
from .errors import (
    ProviderAuthError,
    ProviderError,
    ProviderNotFound,
    ProviderParseError,
    ProviderRateLimited,
    ProviderSchemaError,
    ProviderTimeout,
    ProviderUnavailable,
)
from .images import ImageResolver
from .models import (
    Credit,
    Detection,
    DiscoveryFeed,
    DiscoveryItem,
    DiscoveryPage,
    EpisodeRecord,
    FacetValue,
    FieldValue,
    ImageAsset,
    MatchResult,
    MediaMetadata,
    ProviderCapability,
    ProviderDescriptor,
    ProviderHealth,
    ProviderRecord,
    ProviderRef,
    SearchHit,
    SearchQuery,
    SeasonRecord,
    SourceTier,
)
from .orchestrator import ComposeResult, MetadataOrchestrator
from .policy import (
    ANCHOR_POLICY,
    DEFAULT_POLICY_KEY,
    FieldRule,
    MetadataPolicy,
    get_preset,
    resolve_policy,
)
from .registry import MetadataRegistry, registry

__all__ = [
    "ANCHOR_POLICY",
    "DEFAULT_POLICY_KEY",
    "ComposeResult",
    "Credit",
    "Detection",
    "DiscoveryFeed",
    "DiscoveryItem",
    "DiscoveryPage",
    "EpisodeRecord",
    "FacetValue",
    "FieldRule",
    "FieldValue",
    "ImageAsset",
    "ImageResolver",
    "MatchResult",
    "MediaMetadata",
    "MetadataComposer",
    "MetadataOrchestrator",
    "MetadataPolicy",
    "MetadataRegistry",
    "ProviderAuthError",
    "ProviderCapability",
    "ProviderDescriptor",
    "ProviderError",
    "ProviderHealth",
    "ProviderNotFound",
    "ProviderParseError",
    "ProviderRateLimited",
    "ProviderRecord",
    "ProviderRef",
    "ProviderSchemaError",
    "ProviderTimeout",
    "ProviderUnavailable",
    "SearchHit",
    "SearchQuery",
    "SeasonRecord",
    "SourceTier",
    "get_preset",
    "registry",
    "resolve_policy",
]
