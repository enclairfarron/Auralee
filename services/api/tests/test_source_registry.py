from dataclasses import replace

import pytest

from app.sources.registry import (
    P1_SOURCE_KEYS,
    SOURCE_REGISTRY,
    ContentScope,
    IdentityStrategy,
    StorageLane,
    get_source_spec,
    validate_source_key,
)


def test_registry_contains_the_existing_sources_and_sec_shadow() -> None:
    assert set(SOURCE_REGISTRY) == {"hn", "reuters", "wsj", "sec_edgar"}
    assert all(key == spec.key for key, spec in SOURCE_REGISTRY.items())


def test_p1_source_boundary_is_frozen_to_hn_and_marketwatch() -> None:
    assert P1_SOURCE_KEYS == frozenset({"hn", "reuters"})
    assert all(SOURCE_REGISTRY[key].storage_lane is StorageLane.BASELINE for key in P1_SOURCE_KEYS)
    assert SOURCE_REGISTRY["reuters"].display_name == "MarketWatch"


def test_sec_edgar_is_an_inert_shadow_source() -> None:
    spec = SOURCE_REGISTRY["sec_edgar"]

    assert spec.storage_lane is StorageLane.SHADOW
    assert spec.identity_strategy is IdentityStrategy.SOURCE_ID
    assert ContentScope.EXCERPT in spec.content_scopes
    assert not spec.activate_price_tickers
    assert not spec.judge_enabled
    assert not spec.scheduler_enabled
    assert spec.key not in P1_SOURCE_KEYS


@pytest.mark.parametrize(
    "key",
    [
        "",
        "a",
        "HN",
        "_sec",
        "sec-edgar",
        "sec/edgar",
        "../sec",
        "sec.edgar",
        "证券",
        "a" * 33,
    ],
)
def test_source_key_validation_rejects_unsafe_or_noncanonical_values(key: str) -> None:
    with pytest.raises(ValueError, match="source key must match"):
        validate_source_key(key)


@pytest.mark.parametrize("key", ["hn", "reuters", "wsj", "sec_edgar", "a1"])
def test_source_key_validation_accepts_safe_values(key: str) -> None:
    assert validate_source_key(key) == key


def test_source_spec_validates_its_key_on_construction() -> None:
    with pytest.raises(ValueError, match="source key must match"):
        replace(SOURCE_REGISTRY["hn"], key="../hn")


def test_get_source_spec_rejects_unknown_and_unsafe_keys() -> None:
    assert get_source_spec("hn") is SOURCE_REGISTRY["hn"]

    with pytest.raises(KeyError, match="unknown source"):
        get_source_spec("unknown")
    with pytest.raises(ValueError, match="source key must match"):
        get_source_spec("../hn")
