from datetime import UTC, datetime
from unittest.mock import MagicMock, call

from app.models.article import (
    Article,
    GeminiMeta,
    Sentiment,
)
from app.models.run import Run
from app.services.firestore_repo import FirestoreRepo


class _FakeDoc:
    def __init__(self, data: dict | None = None) -> None:
        self._data = data
        self.exists = data is not None

    def to_dict(self) -> dict | None:
        return self._data


class _FakeDocRef:
    def __init__(self, store: dict, path: str) -> None:
        self._store = store
        self._path = path

    def get(self) -> _FakeDoc:
        return _FakeDoc(self._store.get(self._path))

    def set(self, data: dict) -> None:
        self._store[self._path] = data

    def update(self, data: dict) -> None:
        self._store[self._path] = {**self._store.get(self._path, {}), **data}


class _FakeCollection:
    def __init__(self, store: dict, prefix: str) -> None:
        self._store = store
        self._prefix = prefix

    def document(self, doc_id: str) -> _FakeDocRef:
        return _FakeDocRef(self._store, f"{self._prefix}/{doc_id}")

    def add(self, data: dict) -> tuple[None, _FakeDocRef]:
        import uuid

        doc_id = str(uuid.uuid4())
        ref = _FakeDocRef(self._store, f"{self._prefix}/{doc_id}")
        ref.set(data)
        return (None, ref)


class _FakeClient:
    def __init__(self) -> None:
        self.store: dict[str, dict] = {}

    def collection(self, name: str) -> _FakeCollection:
        return _FakeCollection(self.store, name)


def _sample_article(article_id: str = "wsj_20260424_a3f1b9d2") -> Article:
    now = datetime.now(UTC)
    return Article(
        id=article_id,
        source="wsj",
        source_id="x",
        url="https://x",
        title="t",
        published_at=now,
        fetched_at=now,
        processed_at=now,
        language="en",
        summary="s",
        tickers=["AAPL"],
        sentiment=Sentiment(score=0.5, label="bullish"),
        core_thesis="c",
        gemini_meta=GeminiMeta(
            model="gemini-2.5-flash",
            tokens_in=10,
            tokens_out=5,
            cost_usd=0.0001,
            latency_ms=100,
            prompt_version="v1",
        ),
    )


def test_save_and_get_article() -> None:
    repo = FirestoreRepo(_client=_FakeClient())
    a = _sample_article()
    repo.save_article(a)
    fetched = repo.get_article(a.id)
    assert fetched is not None
    assert fetched.id == a.id


def test_article_exists() -> None:
    repo = FirestoreRepo(_client=_FakeClient())
    a = _sample_article()
    assert not repo.article_exists(a.id)
    repo.save_article(a)
    assert repo.article_exists(a.id)


def test_save_run_assigns_id_when_blank() -> None:
    repo = FirestoreRepo(_client=_FakeClient())
    r = Run(id="", kind="scrape", source="hn", started_at=datetime.now(UTC))
    saved_id = repo.save_run(r)
    assert saved_id != ""


def test_upsert_ticker_stub_creates_when_missing() -> None:
    client = _FakeClient()
    repo = FirestoreRepo(_client=client)
    repo.upsert_ticker_stub("AAPL")
    assert "prices/AAPL" in client.store
    assert client.store["prices/AAPL"]["ticker"] == "AAPL"
    assert client.store["prices/AAPL"]["is_active"] is True


def test_list_runs_in_range_uses_kind_and_half_open_utc_window() -> None:
    start = datetime(2026, 4, 24, tzinfo=UTC)
    end = datetime(2026, 4, 25, tzinfo=UTC)
    stored = Run(
        id="run-1",
        kind="scrape",
        source="hn",
        started_at=start,
    ).model_dump(mode="json")
    doc = MagicMock()
    doc.to_dict.return_value = stored
    query = MagicMock()
    query.where.return_value = query
    query.order_by.return_value = query
    query.stream.return_value = [doc]
    client = MagicMock()
    client.collection.return_value = query

    runs = FirestoreRepo(_client=client).list_runs_in_range(start, end, kind="scrape")

    assert [run.id for run in runs] == ["run-1"]
    assert query.where.call_args_list == [
        call("kind", "==", "scrape"),
        call("started_at", ">=", start.isoformat()),
        call("started_at", "<", end.isoformat()),
    ]
    query.order_by.assert_called_once_with("started_at", direction="DESCENDING")
