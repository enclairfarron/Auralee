import logging
from datetime import UTC, datetime

from app.models.article import Article, GeminiMeta
from app.models.ingest import IngestMeta, IngestPayload, IngestResponse, RawHtml
from app.services.article_id import compute_article_id
from app.services.firestore_repo import FirestoreRepo
from app.services.gcs import RawHtmlArchiver
from app.services.gemini import GeminiExtractor
from app.services.html_extract import extract_clean_text
from app.services.sanity import check_ticker_precision

logger = logging.getLogger(__name__)

_MIN_CLEAN_TEXT_CHARS = 500


class IngestService:
    def __init__(
        self,
        repo: FirestoreRepo,
        extractor: GeminiExtractor,
        archiver: RawHtmlArchiver,
    ) -> None:
        self._repo = repo
        self._extractor = extractor
        self._archiver = archiver

    def process(self, payload: IngestPayload) -> IngestResponse:
        article_id = compute_article_id(payload.source, payload.fetched_at, payload.url)

        if self._repo.article_exists(article_id):
            logger.info("ingest skipped: duplicate", extra={"article_id": article_id})
            return IngestResponse(article_id=article_id, status="duplicate")

        # Normalize to clean text
        if isinstance(payload.raw, RawHtml):
            clean_text = extract_clean_text(payload.raw.html) or ""
        else:
            clean_text = payload.raw.body or ""

        if len(clean_text) < _MIN_CLEAN_TEXT_CHARS:
            logger.info(
                "ingest skipped: short text",
                extra={"article_id": article_id, "chars": len(clean_text)},
            )
            return IngestResponse(article_id=article_id, status="skipped_short")

        # Archive raw HTML (best effort, only when we have HTML)
        gcs_uri: str | None = None
        if isinstance(payload.raw, RawHtml):
            gcs_uri = self._archiver.upload_safe(
                article_id=article_id,
                source=payload.source,
                published_at=payload.fetched_at,
                html=payload.raw.html,
            )

        # Gemini extraction
        result = self._extractor.extract(
            source=payload.source,
            url=payload.url,
            published_at=payload.fetched_at.isoformat(),
            clean_text=clean_text,
        )

        # M2 sanity check
        sanity = check_ticker_precision(
            tickers=result.extraction.tickers,
            clean_text=clean_text,
        )

        now = datetime.now(UTC)
        article = Article(
            id=article_id,
            source=payload.source,
            source_id=payload.source_id,
            url=payload.url,
            title=result.extraction.title,
            published_at=payload.fetched_at,
            fetched_at=payload.fetched_at,
            processed_at=now,
            language=result.extraction.language,
            raw_html_gcs_uri=gcs_uri,
            clean_text_chars=len(clean_text),
            summary=result.extraction.summary,
            tickers=result.extraction.tickers,
            sentiment=result.extraction.sentiment,
            core_thesis=result.extraction.core_thesis,
            categories=result.extraction.categories,
            entities=result.extraction.entities,
            gemini_meta=GeminiMeta(
                model=result.model,
                tokens_in=result.tokens_in,
                tokens_out=result.tokens_out,
                cost_usd=result.cost_usd,
                latency_ms=result.latency_ms,
                prompt_version=result.prompt_version,
            ),
            sanity_check=sanity,
        )
        self._repo.save_article(article)

        for ticker in result.extraction.tickers:
            self._repo.upsert_ticker_stub(ticker)

        return IngestResponse(
            article_id=article_id,
            status="ingested",
            extracted=result.extraction,
            meta=IngestMeta(
                tokens_in=result.tokens_in,
                tokens_out=result.tokens_out,
                cost_usd=result.cost_usd,
                latency_ms=result.latency_ms,
                prompt_version=result.prompt_version,
                raw_html_gcs_uri=gcs_uri,
            ),
        )
