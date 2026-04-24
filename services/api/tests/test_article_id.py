from datetime import UTC, datetime

from app.services.article_id import compute_article_id


def test_id_format_has_source_date_hash() -> None:
    aid = compute_article_id(
        source="wsj",
        published_at=datetime(2026, 4, 24, 13, 30, tzinfo=UTC),
        url="https://www.wsj.com/articles/foo-bar",
    )
    assert aid.startswith("wsj_20260424_")
    assert len(aid.split("_")[-1]) == 8


def test_same_url_yields_same_id() -> None:
    args = ("hn", datetime(2026, 4, 24, tzinfo=UTC), "https://example.com/x")
    assert compute_article_id(*args) == compute_article_id(*args)


def test_different_urls_yield_different_ids() -> None:
    args1 = ("hn", datetime(2026, 4, 24, tzinfo=UTC), "https://example.com/x")
    args2 = ("hn", datetime(2026, 4, 24, tzinfo=UTC), "https://example.com/y")
    assert compute_article_id(*args1) != compute_article_id(*args2)


def test_url_normalized_strips_trailing_slash_and_fragment() -> None:
    args1 = ("hn", datetime(2026, 4, 24, tzinfo=UTC), "https://example.com/x")
    args2 = ("hn", datetime(2026, 4, 24, tzinfo=UTC), "https://example.com/x/#section")
    assert compute_article_id(*args1) == compute_article_id(*args2)


def test_published_at_naive_treated_as_utc() -> None:
    aid_aware = compute_article_id("hn", datetime(2026, 4, 24, tzinfo=UTC), "https://x")
    aid_naive = compute_article_id("hn", datetime(2026, 4, 24), "https://x")
    assert aid_aware == aid_naive


def test_url_normalization_strips_utm_tracking() -> None:
    args1 = (
        "hn",
        datetime(2026, 4, 24, tzinfo=UTC),
        "https://example.com/x?utm_source=twitter&utm_medium=social",
    )
    args2 = ("hn", datetime(2026, 4, 24, tzinfo=UTC), "https://example.com/x?utm_source=email")
    args3 = ("hn", datetime(2026, 4, 24, tzinfo=UTC), "https://example.com/x")
    assert compute_article_id(*args1) == compute_article_id(*args2) == compute_article_id(*args3)


def test_url_normalization_strips_wsj_mod_param() -> None:
    args1 = (
        "wsj",
        datetime(2026, 4, 24, tzinfo=UTC),
        "https://www.wsj.com/articles/foo?mod=hp_lead_pos1",
    )
    args2 = ("wsj", datetime(2026, 4, 24, tzinfo=UTC), "https://www.wsj.com/articles/foo")
    assert compute_article_id(*args1) == compute_article_id(*args2)


def test_url_normalization_preserves_meaningful_query_params() -> None:
    # Some publishers route via ?id=... — must NOT be stripped
    args1 = ("hn", datetime(2026, 4, 24, tzinfo=UTC), "https://example.com/article?id=12345")
    args2 = ("hn", datetime(2026, 4, 24, tzinfo=UTC), "https://example.com/article?id=99999")
    assert compute_article_id(*args1) != compute_article_id(*args2)


def test_url_normalization_lowercases_host() -> None:
    args1 = ("hn", datetime(2026, 4, 24, tzinfo=UTC), "https://Example.COM/x")
    args2 = ("hn", datetime(2026, 4, 24, tzinfo=UTC), "https://example.com/x")
    assert compute_article_id(*args1) == compute_article_id(*args2)
