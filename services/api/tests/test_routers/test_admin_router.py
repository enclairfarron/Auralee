from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.models.article import Article, Extraction, GeminiMeta, Sentiment, Source
from app.services.article_id import compute_article_id
from app.services.gemini import ExtractionResult


@pytest.fixture(autouse=True)
def _set_admin_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "secret-test-token")
    from app.config import get_settings

    get_settings.cache_clear()


def test_admin_endpoint_rejects_missing_token(test_client: TestClient) -> None:
    response = test_client.get("/admin/articles")
    assert response.status_code == 401


def test_admin_endpoint_rejects_wrong_token(test_client: TestClient) -> None:
    response = test_client.get("/admin/articles", headers={"X-Admin-Token": "wrong"})
    assert response.status_code == 401


def test_admin_stats_404_when_no_metrics(
    test_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Bypass real Firestore by overriding get_repo
    from app.deps import get_repo
    from app.main import create_app

    mock_repo = MagicMock()
    mock_repo.get_metrics.return_value = None
    app = create_app()
    app.dependency_overrides[get_repo] = lambda: mock_repo
    client = TestClient(app)

    response = client.get(
        "/admin/stats?date=2026-04-24",
        headers={"X-Admin-Token": "secret-test-token"},
    )
    assert response.status_code == 404


def _health_client(
    *, vertex_error: Exception | None = None
) -> tuple[TestClient, MagicMock, MagicMock]:
    from app.deps import get_extractor, get_repo, get_secrets
    from app.main import create_app

    mock_repo = MagicMock()
    mock_secrets = MagicMock()
    mock_secrets.get.return_value = "valid-cookie"
    mock_extractor = MagicMock()
    mock_extractor.model = "gemini-2.5-flash"
    if vertex_error:
        mock_extractor.check_health.side_effect = vertex_error

    app = create_app()
    app.dependency_overrides[get_repo] = lambda: mock_repo
    app.dependency_overrides[get_secrets] = lambda: mock_secrets
    app.dependency_overrides[get_extractor] = lambda: mock_extractor
    return TestClient(app), mock_secrets, mock_extractor


def test_healthz_detail_verifies_vertex_and_does_not_read_legacy_key() -> None:
    client, mock_secrets, mock_extractor = _health_client()

    response = client.get(
        "/admin/healthz-detail",
        headers={"X-Admin-Token": "secret-test-token"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "firestore": True,
        "secrets_wsj_cookie": True,
        "vertex_ai": True,
        "vertex_model": "gemini-2.5-flash",
    }
    mock_secrets.get.assert_called_once_with("WSJ_COOKIE")
    mock_extractor.check_health.assert_called_once_with()


def test_healthz_detail_reports_vertex_permission_failure() -> None:
    client, _, _ = _health_client(vertex_error=RuntimeError("403 Permission denied"))

    response = client.get(
        "/admin/healthz-detail",
        headers={"X-Admin-Token": "secret-test-token"},
    )

    assert response.status_code == 200
    assert response.json()["vertex_ai"] is False
    assert response.json()["vertex_ai_error"] == "403 Permission denied"


def _archived_article(
    *,
    source: Source,
    url: str,
    raw_content_gcs_uri: str | None = None,
    raw_html_gcs_uri: str | None = None,
) -> Article:
    published_at = datetime(2026, 4, 23, 23, 30, tzinfo=UTC)
    article_id = compute_article_id(source, published_at, url)
    return Article(
        id=article_id,
        source=source,
        source_id="source-1",
        url=url,
        title="Archived story",
        published_at=published_at,
        fetched_at=datetime(2026, 4, 24, 1, 30, tzinfo=UTC),
        processed_at=datetime(2026, 4, 24, 1, 31, tzinfo=UTC),
        language="en",
        raw_content_gcs_uri=raw_content_gcs_uri,
        raw_html_gcs_uri=raw_html_gcs_uri,
        clean_text_chars=500,
        summary="summary",
        sentiment=Sentiment(score=0.2, label="bullish"),
        core_thesis="thesis",
        gemini_meta=GeminiMeta(
            model="gemini-2.5-flash",
            tokens_in=100,
            tokens_out=20,
            cost_usd=0.001,
            latency_ms=100,
            prompt_version="v1",
        ),
    )


def _mock_extraction_result() -> ExtractionResult:
    return ExtractionResult(
        extraction=Extraction(
            title="Re-extracted story",
            summary="summary",
            sentiment=Sentiment(score=0.2, label="bullish"),
            core_thesis="thesis",
            language="en",
        ),
        tokens_in=100,
        tokens_out=20,
        cost_usd=0.001,
        latency_ms=100,
        prompt_version="v1",
        model="gemini-2.5-flash",
    )


def _reingest_client(
    monkeypatch: pytest.MonkeyPatch,
    article: Article,
    archived_content: str,
) -> tuple[TestClient, MagicMock, MagicMock, MagicMock]:
    from app.deps import get_archiver, get_extractor, get_repo
    from app.main import create_app

    repo = MagicMock()
    repo.get_article.return_value = article
    repo.article_exists.return_value = False
    extractor = MagicMock()
    extractor.extract.return_value = _mock_extraction_result()
    archiver = MagicMock()

    gcs_client = MagicMock()
    gcs_client.bucket.return_value.blob.return_value.download_as_text.return_value = (
        archived_content
    )
    monkeypatch.setattr("app.routers.admin.gcs_storage.Client", lambda: gcs_client)

    app = create_app()
    app.dependency_overrides[get_repo] = lambda: repo
    app.dependency_overrides[get_extractor] = lambda: extractor
    app.dependency_overrides[get_archiver] = lambda: archiver
    return TestClient(app), repo, extractor, archiver


def test_reingest_replays_archived_raw_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uri = "gs://raw/reuters/2026-04-24/reuters_20260423_abc.json"
    article = _archived_article(
        source="reuters",
        url="https://www.marketwatch.com/story/apple",
        raw_content_gcs_uri=uri,
    )
    archived_content = (
        '{"body":"Apple reported strong earnings. '
        "Apple raised guidance. Apple shares gained. "
        "Investors welcomed the results. Apple expects further growth. "
        "The company also expanded margins. Analysts lifted targets. "
        "Management increased its forecast for the year, citing demand. "
        'The board approved additional investment in product development.",'
        '"kind":"text","metadata":{"feed":"marketwatch"},"title":"Apple earnings"}'
    )
    client, repo, extractor, archiver = _reingest_client(monkeypatch, article, archived_content)
    archiver.upload_text_safe.return_value = uri

    response = client.post(
        f"/admin/reingest/{article.id}",
        headers={"X-Admin-Token": "secret-test-token"},
    )

    assert response.status_code == 200
    assert response.json()["article_id"] == article.id
    archiver.upload_text_safe.assert_not_called()
    assert "Apple earnings" in extractor.extract.call_args.kwargs["clean_text"]
    assert "Apple raised guidance" in extractor.extract.call_args.kwargs["clean_text"]
    assert extractor.extract.call_args.kwargs["published_at"] == article.published_at.isoformat()
    saved = repo.save_article.call_args.args[0]
    assert saved.raw_content_gcs_uri == uri
    assert saved.raw_html_gcs_uri is None


def test_reingest_reuses_legacy_html_archive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uri = "gs://raw/wsj/2026-04-24/wsj_20260423_abc.html"
    article = _archived_article(
        source="wsj",
        url="https://www.wsj.com/articles/apple",
        raw_html_gcs_uri=uri,
    )
    html = (
        "<html><body><article>"
        + ("Apple reported strong earnings and raised its annual guidance. " * 30)
        + "</article></body></html>"
    )
    client, repo, _, archiver = _reingest_client(monkeypatch, article, html)
    archiver.upload_safe.return_value = uri

    response = client.post(
        f"/admin/reingest/{article.id}",
        headers={"X-Admin-Token": "secret-test-token"},
    )

    assert response.status_code == 200
    assert response.json()["article_id"] == article.id
    archiver.upload_safe.assert_not_called()
    archiver.upload_text_safe.assert_not_called()
    saved = repo.save_article.call_args.args[0]
    assert saved.raw_content_gcs_uri == uri
    assert saved.raw_html_gcs_uri == uri


def test_reingest_preserves_original_publication_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.deps import get_archiver, get_extractor, get_repo
    from app.main import create_app
    from app.models.article import Article, GeminiMeta, Sentiment
    from app.models.ingest import IngestResponse
    from app.routers import admin as admin_router

    published_at = datetime(2026, 4, 23, 23, 30, tzinfo=UTC)
    fetched_at = datetime(2026, 4, 24, 13, 30, tzinfo=UTC)
    article = Article(
        id="wsj_20260423_a3f1b9d2",
        source="wsj",
        source_id="WP-123",
        url="https://example.com/a",
        title="Apple Q2",
        published_at=published_at,
        fetched_at=fetched_at,
        processed_at=fetched_at,
        language="en",
        raw_html_gcs_uri="gs://bucket/raw.html",
        clean_text_chars=1000,
        summary="Apple beat earnings.",
        tickers=["AAPL"],
        sentiment=Sentiment(score=0.5, label="bullish"),
        core_thesis="Apple beat earnings.",
        gemini_meta=GeminiMeta(
            model="gemini-2.5-flash",
            tokens_in=100,
            tokens_out=50,
            cost_usd=0.0001,
            latency_ms=200,
            prompt_version="v1",
        ),
    )

    repo = MagicMock()
    repo.get_article.return_value = article
    storage_client = MagicMock()
    storage_client.bucket.return_value.blob.return_value.download_as_text.return_value = (
        "<html><body>" + "Apple earnings. " * 100 + "</body></html>"
    )
    monkeypatch.setattr(admin_router.gcs_storage, "Client", lambda: storage_client)

    captured_calls = []

    class CapturingIngestService:
        def __init__(self, **_: object) -> None:
            pass

        def process(self, payload: object, **options: object) -> IngestResponse:
            captured_calls.append((payload, options))
            return IngestResponse(article_id=article.id, status="duplicate")

    monkeypatch.setattr(admin_router, "IngestService", CapturingIngestService)

    app = create_app()
    app.dependency_overrides[get_repo] = lambda: repo
    app.dependency_overrides[get_extractor] = lambda: MagicMock()
    app.dependency_overrides[get_archiver] = lambda: MagicMock()
    client = TestClient(app)

    response = client.post(
        f"/admin/reingest/{article.id}",
        headers={"X-Admin-Token": "secret-test-token"},
    )

    assert response.status_code == 200
    assert len(captured_calls) == 1
    payload, options = captured_calls[0]
    assert payload.published_at == published_at
    assert payload.fetched_at == fetched_at
    assert options == {
        "allow_existing": True,
        "existing_article_id": article.id,
        "existing_archive_uri": article.raw_html_gcs_uri,
    }
    repo._client.collection.return_value.document.return_value.delete.assert_not_called()
