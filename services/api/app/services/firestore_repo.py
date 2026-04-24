import logging
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from google.cloud import firestore
from google.cloud.firestore_v1.base_document import DocumentSnapshot

from app.models.article import Article, EvalScore
from app.models.price import DailyOHLC, Price
from app.models.run import Run

logger = logging.getLogger(__name__)


class FirestoreRepo:
    def __init__(self, _client: Any | None = None) -> None:
        self._client = _client or firestore.Client()

    # articles
    def article_exists(self, article_id: str) -> bool:
        doc = cast(DocumentSnapshot, self._client.collection("articles").document(article_id).get())
        return bool(doc.exists)

    def save_article(self, article: Article) -> None:
        data = article.model_dump(mode="json")
        self._client.collection("articles").document(article.id).set(data)

    def get_article(self, article_id: str) -> Article | None:
        doc = cast(DocumentSnapshot, self._client.collection("articles").document(article_id).get())
        if not doc.exists:
            return None
        return Article.model_validate(doc.to_dict())

    # prices
    def upsert_ticker_stub(self, ticker: str) -> None:
        doc = cast(DocumentSnapshot, self._client.collection("prices").document(ticker).get())
        if doc.exists:
            self._client.collection("prices").document(ticker).update({"is_active": True})
        else:
            now = datetime.now(UTC)
            self._client.collection("prices").document(ticker).set(
                Price(
                    ticker=ticker,
                    first_seen_at=now,
                    last_refreshed_at=None,
                    is_active=True,
                ).model_dump(mode="json")
            )

    def list_active_tickers(self) -> list[str]:
        docs = self._client.collection("prices").where("is_active", "==", True).stream()
        return [d.id for d in docs]

    def save_daily_ohlc(self, ticker: str, ohlc: DailyOHLC) -> None:
        date_key = ohlc.date.replace("-", "")
        (
            self._client.collection("prices")
            .document(ticker)
            .collection("daily")
            .document(date_key)
            .set(ohlc.model_dump(mode="json"))
        )

    def update_ticker_refreshed(self, ticker: str, when: datetime) -> None:
        self._client.collection("prices").document(ticker).update(
            {"last_refreshed_at": when.isoformat()}
        )

    # runs
    def save_run(self, run: Run) -> str:
        if not run.id:
            run.id = str(uuid.uuid4())
        self._client.collection("runs").document(run.id).set(run.model_dump(mode="json"))
        return run.id

    # metrics
    def save_metrics(self, date_yyyymmdd: str, payload: dict[str, Any]) -> None:
        self._client.collection("metrics").document(date_yyyymmdd).set(payload)

    def get_metrics(self, date_yyyymmdd: str) -> dict[str, Any] | None:
        doc = cast(
            DocumentSnapshot, self._client.collection("metrics").document(date_yyyymmdd).get()
        )
        return doc.to_dict() if doc.exists else None

    # helpers used by /admin and /cron
    def list_recent_articles(self, source: str | None, limit: int) -> list[Article]:
        coll = self._client.collection("articles")
        query = coll.where("source", "==", source) if source else coll
        query = query.order_by("processed_at", direction=firestore.Query.DESCENDING).limit(limit)
        return [Article.model_validate(d.to_dict()) for d in query.stream()]

    def list_articles_in_range(self, start: datetime, end: datetime) -> list[Article]:
        docs = (
            self._client.collection("articles")
            .where("processed_at", ">=", start.isoformat())
            .where("processed_at", "<", end.isoformat())
            .stream()
        )
        return [Article.model_validate(d.to_dict()) for d in docs]

    def list_articles_needing_judge(
        self, processed_after: datetime, limit: int = 200
    ) -> list[Article]:
        docs = (
            self._client.collection("articles")
            .where("processed_at", ">=", processed_after.isoformat())
            .where("eval_score", "==", None)
            .limit(limit)
            .stream()
        )
        return [Article.model_validate(d.to_dict()) for d in docs]

    def update_article_eval_score(self, article_id: str, score: EvalScore) -> None:
        self._client.collection("articles").document(article_id).update(
            {"eval_score": score.model_dump(mode="json")}
        )
