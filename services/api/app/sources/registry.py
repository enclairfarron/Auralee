"""Versioned, code-owned registry of content sources.

This module is deliberately declarative. The scorecard imports only the frozen
P1 allowlist; models, routers, scrapers, and schedulers do not resolve adapters
from it yet. Later integration work can adopt policy here incrementally instead
of adding another closed ``Literal``.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final


class StorageLane(StrEnum):
    BASELINE = "baseline"
    SHADOW = "shadow"


class SourceKind(StrEnum):
    COMMUNITY = "community"
    PUBLISHER_RSS = "publisher_rss"
    SUBSCRIPTION_PUBLISHER = "subscription_publisher"
    REGULATORY_FILING = "regulatory_filing"


class ContentScope(StrEnum):
    FULL = "full"
    SUMMARY = "summary"
    EXCERPT = "excerpt"
    METADATA = "metadata"


class ArchiveMode(StrEnum):
    BEST_EFFORT = "best_effort"
    REQUIRED = "required"
    HASH_ONLY = "hash_only"
    FORBIDDEN = "forbidden"


class IdentityStrategy(StrEnum):
    LEGACY_URL_DATE = "legacy_url_date"
    SOURCE_ID = "source_id"


_SOURCE_KEY_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_]{1,31}$", re.ASCII)


def validate_source_key(key: str) -> str:
    """Return a safe source key or raise ``ValueError``.

    Source keys will eventually be used in Firestore documents and GCS object
    prefixes.  Keeping the accepted alphabet intentionally small prevents path
    separators, traversal components, Unicode lookalikes, and case aliases.
    """

    if _SOURCE_KEY_RE.fullmatch(key) is None:
        raise ValueError(
            "source key must match ^[a-z][a-z0-9_]{1,31}$ "
            "(lowercase ASCII letters, digits, and underscores only)"
        )
    return key


@dataclass(frozen=True, slots=True)
class SourceSpec:
    key: str
    display_name: str
    source_kind: SourceKind
    storage_lane: StorageLane
    content_scopes: frozenset[ContentScope]
    archive_mode: ArchiveMode
    identity_strategy: IdentityStrategy
    candidate_limit: int
    fetch_delay_seconds: float
    activate_price_tickers: bool
    judge_enabled: bool
    scheduler_enabled: bool

    def __post_init__(self) -> None:
        validate_source_key(self.key)
        if not self.display_name.strip():
            raise ValueError("display_name must not be blank")
        if not self.content_scopes:
            raise ValueError("content_scopes must not be empty")
        if self.candidate_limit < 1:
            raise ValueError("candidate_limit must be positive")
        if self.fetch_delay_seconds < 0:
            raise ValueError("fetch_delay_seconds must not be negative")


def _build_registry(specs: tuple[SourceSpec, ...]) -> Mapping[str, SourceSpec]:
    registry: dict[str, SourceSpec] = {}
    for spec in specs:
        if spec.key in registry:
            raise ValueError(f"duplicate source key: {spec.key}")
        registry[spec.key] = spec
    return MappingProxyType(registry)


SOURCE_REGISTRY: Final[Mapping[str, SourceSpec]] = _build_registry(
    (
        SourceSpec(
            key="hn",
            display_name="Hacker News",
            source_kind=SourceKind.COMMUNITY,
            storage_lane=StorageLane.BASELINE,
            content_scopes=frozenset({ContentScope.FULL, ContentScope.METADATA}),
            archive_mode=ArchiveMode.BEST_EFFORT,
            identity_strategy=IdentityStrategy.LEGACY_URL_DATE,
            candidate_limit=30,
            fetch_delay_seconds=0.0,
            activate_price_tickers=True,
            judge_enabled=True,
            scheduler_enabled=True,
        ),
        SourceSpec(
            key="reuters",
            display_name="MarketWatch",
            source_kind=SourceKind.PUBLISHER_RSS,
            storage_lane=StorageLane.BASELINE,
            content_scopes=frozenset({ContentScope.SUMMARY}),
            archive_mode=ArchiveMode.BEST_EFFORT,
            identity_strategy=IdentityStrategy.LEGACY_URL_DATE,
            candidate_limit=50,
            fetch_delay_seconds=1.0,
            activate_price_tickers=True,
            judge_enabled=True,
            scheduler_enabled=True,
        ),
        SourceSpec(
            key="wsj",
            display_name="The Wall Street Journal",
            source_kind=SourceKind.SUBSCRIPTION_PUBLISHER,
            storage_lane=StorageLane.BASELINE,
            content_scopes=frozenset({ContentScope.FULL}),
            archive_mode=ArchiveMode.BEST_EFFORT,
            identity_strategy=IdentityStrategy.LEGACY_URL_DATE,
            candidate_limit=50,
            fetch_delay_seconds=2.0,
            activate_price_tickers=True,
            judge_enabled=False,
            scheduler_enabled=False,
        ),
        SourceSpec(
            key="sec_edgar",
            display_name="SEC EDGAR",
            source_kind=SourceKind.REGULATORY_FILING,
            storage_lane=StorageLane.SHADOW,
            content_scopes=frozenset({ContentScope.EXCERPT, ContentScope.FULL}),
            archive_mode=ArchiveMode.REQUIRED,
            identity_strategy=IdentityStrategy.SOURCE_ID,
            candidate_limit=10,
            fetch_delay_seconds=0.5,
            activate_price_tickers=False,
            judge_enabled=False,
            scheduler_enabled=False,
        ),
    )
)

# This allowlist is the frozen Phase-1 experiment boundary.  It intentionally
# does not mean "every baseline source": legacy WSJ data shares the baseline
# collection but is not part of the P1 scorecard.
P1_SOURCE_KEYS: Final[frozenset[str]] = frozenset({"hn", "reuters"})


def get_source_spec(key: str) -> SourceSpec:
    """Resolve a registered source after rejecting unsafe key syntax."""

    validate_source_key(key)
    try:
        return SOURCE_REGISTRY[key]
    except KeyError as exc:
        raise KeyError(f"unknown source: {key}") from exc
