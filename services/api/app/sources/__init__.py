"""Declarative source metadata for ingestion adapters."""

from app.sources.registry import (
    P1_SOURCE_KEYS,
    SOURCE_REGISTRY,
    ArchiveMode,
    ContentScope,
    IdentityStrategy,
    SourceKind,
    SourceSpec,
    StorageLane,
    get_source_spec,
    validate_source_key,
)

__all__ = [
    "P1_SOURCE_KEYS",
    "SOURCE_REGISTRY",
    "ArchiveMode",
    "ContentScope",
    "IdentityStrategy",
    "SourceKind",
    "SourceSpec",
    "StorageLane",
    "get_source_spec",
    "validate_source_key",
]
