# Auralee Phase 1 Design — Data Pipeline Viability PoC

> **Historical design record.** The current source boundary, scheduler policy, evaluation gates,
> and next milestones are maintained in [`docs/roadmap.md`](../../roadmap.md). Where this April
> design conflicts with that roadmap or the checked-in scripts, the current roadmap/scripts win.

**Status:** Draft v1 · **Date:** 2026-04-24 · **Owner:** enclairfarron

---

## 1. Context & Goal

Auralee (loosely "personal AI agent that refines financial information into gold and insight") is a planned macOS-only native financial Agent app that aggregates WSJ, Reuters, Bloomberg, and Hacker News, processes them with Gemini, correlates news with US stock movements, and builds a per-user reading memory via RAG.

**Phase 1 is NOT an MVP.** It is a one-week **data source viability proof-of-concept** whose sole purpose is to answer a single question:

> *Is the data pipeline good enough that it's worth building the desktop app at all?*

If the PoC passes its thresholds, we proceed to Week 2 (desktop client + user memory). If it fails, we re-evaluate the product definition before writing any UI code.

### 1.1 Scope at a Glance

**In scope for Phase 1 (Week 1):**
- Single FastAPI service on Cloud Run
- Ingestion pipeline for 3 sources: Hacker News, Reuters (RSS), WSJ (cookie-based scrape)
- Gemini 2.5 Flash extraction (summary, tickers, sentiment, core thesis, entities)
- Firestore storage with forward-compatible schema for future vector search and multi-user
- Daily US equity OHLC via `yfinance`
- Fully automated evaluation (M2 regex sanity + M3 LLM-as-Judge)
- GitHub Actions → Cloud Build → Cloud Run deployment
- Cost monitoring and two email alerts

**Explicitly out of scope for Phase 1:**
- Desktop app (Tauri + Next.js) — deferred to Week 2+
- Firebase Auth, multi-tenancy — schema reserves seats but no writes
- Vector embedding / RAG / knowledge graph — deferred to Week 2+
- Bloomberg ingestion — deferred (hostile to scraping)
- Intraday stock prices
- Production-grade observability, SLOs, dashboards
- Terraform / IaC — bash + gcloud scripts only
- Manual human evaluation or labeling — fully automated

---

## 2. Key Decisions Log

| # | Decision | Rationale |
|---|---|---|
| D1 | Eventual target = multi-user (B: personal + <10 invited friends), but **Week 1 runs single-user** with deferred auth | Simplest valid PoC; schema kept forward-compatible |
| D2 | Week 1 sources = HN + Reuters RSS + WSJ (option P2) | WSJ is the riskiest source — validate it early. Bloomberg deferred. |
| D3 | User supplies WSJ cookie directly to GCP Secret Manager, never via application or codebase | Security invariant — sensitive credentials never transit through CI, PR review, or AI assistants |
| D4 | Model correction: Gemini 3.1 Pro does not exist. Use `gemini-2.5-flash` for ingest, reserve `gemini-2.5-pro` for LLM-as-Judge and future agent dialogue | Factual correction; Flash is sufficient for structured extraction |
| D5 | Evaluation tool split: E2 (admin JSON endpoints) + E4 (Jupyter Notebook) | Lightweight query surface + flexible deep analysis |
| D6 | Zero human involvement in evaluation: M2 (regex precision check) + M3 (LLM-as-Judge with Pro) + M2↔M3 disagreement cross-check | User explicit requirement — decisions made from aggregated metrics only |
| D7 | Architecture = Monolith Cloud Run Service (option A) | Fastest iteration loop; split to Service+Job in Week 2 if needed |
| D8 | Include stock prices in Week 1 via `yfinance`, daily OHLC batch refresh | Price-reaction signal is the core Auralee value hypothesis — must validate in PoC |
| D9 | GCP project ID = `auralee-api-server`, region = `us-east1` | us-east1 chosen over asia-east1 for reliable WSJ egress; project ID is immutable |
| D10 | Python package manager = `uv`. CI = GitHub Actions (WIF auth) → Cloud Build (`cloudbuild.yaml`) → `gcloud run deploy` | uv is fastest; Cloud Build keeps build in-region and makes future multi-service fan-out easier |
| D11 | No Terraform in Week 1 | Nine idempotent bash scripts in `infra/scripts/` are sufficient and more readable for PoC scale |

Any decision above is revisitable, but each has a recorded reason — changing one should re-examine cascading assumptions.

---

## 3. Week 1 Decision Thresholds

At end of day 7, the following seven metrics must be computed from the evaluation notebook. Each has a pass threshold. The combined result determines whether to greenlight Week 2.

| # | Metric | Threshold | Source |
|---|---|---|---|
| 1 | Volume (articles/day, all sources) | > 100 | `articles` collection |
| 2 | M2 ticker precision pass rate | > 90% | `articles.sanity_check` |
| 3 | M3 average LLM-as-Judge score | > 7.0 / 10 | `articles.eval_score` |
| 4 | M2↔M3 disagreement rate | < 5% | Computed in notebook |
| 5 | Price-signal spread (mean next-day return: bullish − bearish) | > 1% | `articles` ⨝ `prices/*/daily` |
| 6 | Average Gemini cost per article | < $0.01 | `articles.gemini_meta.cost_usd` |
| 7 | WSJ scrape success rate | > 80% | `runs` collection |

**Interpretation:**
- 7/7 green → proceed to Week 2 (desktop client + user memory)
- 5–6/7 green → investigate red metrics, iterate one more week
- Metric 5 red (core hypothesis) → product definition must be revisited before continuing

---

## 4. Service Topology

```
                    ┌──────────────────────────────────────┐
                    │    Cloud Scheduler (6 cron jobs)     │
                    │  • scrape-hn-hourly        (:05)     │
                    │  • scrape-reuters-hourly   (:15)     │
                    │  • scrape-wsj-hourly       (:25)     │
                    │  • refresh-prices-daily    (21:00 UTC)│
                    │  • aggregate-metrics-daily (23:55)   │
                    │  • eval-judge-daily        (04:30)   │
                    └──────────────┬───────────────────────┘
                                   │ HTTP + OIDC token
                                   ▼
                    ┌──────────────────────────────────────┐
                    │   Cloud Run Service: auralee-api     │
                    │   FastAPI (single container)         │
                    │                                      │
                    │   Routers:                           │
                    │     /cron/scrape?source=…            │
                    │     /cron/refresh-prices             │
                    │     /cron/aggregate-metrics          │
                    │     /cron/eval-judge                 │
                    │     /ingest                          │
                    │     /admin/articles, /admin/stats    │
                    │     /admin/runs, /admin/healthz      │
                    │     /admin/reingest/{id}             │
                    └────┬──────────┬─────────┬────────────┘
                         │          │         │
                         ▼          ▼         ▼
                    Firestore   Secret Mgr   Vertex AI
                    + GCS raw   (2 secrets)  (Flash + Pro)
```

### 4.1 Cloud Run Configuration

| Parameter | Value | Reason |
|---|---|---|
| Region | `us-east1` | Reliable US egress for WSJ |
| Authentication | `--no-allow-unauthenticated` | Private service; callers require IAM or admin token |
| Service Account | `auralee-runtime@…` | Least-privilege runtime identity |
| Memory | 1 GiB | `trafilatura` + pandas peak usage |
| CPU | 1 vCPU | IO-bound workload |
| Min instances | 0 | Scale-to-zero for cost |
| Max instances | 3 | Prevent runaway cost |
| Concurrency | 10 | IO-bound, async FastAPI handles it |
| Timeout | 600 s | Hourly scrape may take several minutes |
| Execution env | gen2 | Faster startup; full syscall support for `trafilatura` |

### 4.2 Monorepo Layout

```
Auralee/
├── apps/                       # Desktop client, deferred (Week 2+)
│   └── desktop/                # Placeholder for Tauri + Next.js
│
├── services/
│   └── api/                    # Phase 1 main workspace
│       ├── app/
│       │   ├── main.py         # FastAPI entry
│       │   ├── config.py       # Settings (pydantic-settings)
│       │   ├── deps.py         # GCP clients, auth guards
│       │   ├── routers/
│       │   │   ├── ingest.py
│       │   │   ├── cron.py
│       │   │   ├── admin.py
│       │   │   └── health.py
│       │   ├── services/
│       │   │   ├── gemini.py
│       │   │   ├── firestore.py
│       │   │   ├── prices.py
│       │   │   ├── secrets.py
│       │   │   ├── judge.py    # LLM-as-Judge (M3)
│       │   │   ├── sanity.py   # Regex precision check (M2)
│       │   │   └── scrapers/
│       │   │       ├── base.py
│       │   │       ├── hn.py
│       │   │       ├── reuters.py
│       │   │       └── wsj.py
│       │   └── models/         # Pydantic models
│       │       ├── article.py
│       │       ├── price.py
│       │       └── run.py
│       ├── tests/
│       ├── Dockerfile
│       ├── cloudbuild.yaml
│       ├── pyproject.toml
│       └── README.md
│
├── infra/
│   └── scripts/                # Nine idempotent setup scripts
│       ├── 00-bootstrap.sh
│       ├── 01-create-service-accounts.sh
│       ├── 02-create-secrets.sh
│       ├── 03-create-buckets.sh
│       ├── 04-create-firestore.sh
│       ├── 05-create-artifact-registry.sh
│       ├── 06-grant-iam.sh
│       ├── 07-setup-wif.sh
│       ├── 08-create-scheduler-jobs.sh
│       └── deploy-local.sh
│
├── notebooks/
│   └── analyze.ipynb           # E4 evaluation notebook
│
├── docs/
│   └── superpowers/
│       └── specs/              # This document lives here
│
├── .github/
│   └── workflows/
│       └── deploy.yml          # GHA → Cloud Build → Cloud Run
│
├── .gitignore
├── LICENSE
└── README.md
```

---

## 5. Firestore Schema

Firestore is in Native mode, single database, same region as Cloud Run (`us-east1`). All collections follow the conventions below.

### 5.1 Collections Overview

```
Week 1 (writes happen):
  articles/{articleId}
  prices/{ticker}
  prices/{ticker}/daily/{YYYYMMDD}
  runs/{runId}
  metrics/{YYYYMMDD}

Week 2+ (reserved, no writes yet):
  users/{uid}
  users/{uid}/reads/{articleId}
  users/{uid}/memory/{memoryId}    # Vector index built here
  entities/{entityId}
```

### 5.2 `articles/{articleId}`

**Document ID convention:** `{source}_{YYYYMMDD}_{md5(url)[:8]}`
Example: `wsj_20260424_a3f1b9d2`

```jsonc
{
  // Identity & metadata
  "id": "wsj_20260424_a3f1b9d2",
  "source": "wsj",                       // enum: hn | reuters | wsj
  "source_id": "WP-12345",
  "url": "https://www.wsj.com/...",
  "title": "Apple Reports Q2 Earnings...",
  "author": "John Smith",                // nullable
  "published_at": "2026-04-24T13:30:00Z",
  "fetched_at":   "2026-04-24T13:35:12Z",
  "processed_at": "2026-04-24T13:35:18Z",
  "language": "en",

  // Raw archive in GCS (not in Firestore)
  "raw_html_gcs_uri": "gs://auralee-api-server-raw/wsj/2026-04-24/wsj_20260424_a3f1b9d2.html",
  "clean_text_chars": 8421,

  // Gemini Flash extraction (Week 1 core output)
  "summary": "Apple beat consensus...",
  "tickers": ["AAPL"],
  "sentiment": {
    "score": 0.62,                       // -1 to +1
    "label": "bullish"                   // bullish | bearish | neutral
  },
  "core_thesis": "iPhone sales in China rebounded after...",
  "categories": ["earnings", "tech"],
  "entities": [
    { "type": "company", "name": "Apple Inc.", "ticker": "AAPL" },
    { "type": "person",  "name": "Tim Cook" }
  ],

  // Gemini call metadata (cost + latency monitoring)
  "gemini_meta": {
    "model": "gemini-2.5-flash",
    "tokens_in": 7821,
    "tokens_out": 412,
    "cost_usd": 0.00045,
    "latency_ms": 2340,
    "prompt_version": "v1"
  },

  // M2: Automated regex sanity check (inline with /ingest)
  "sanity_check": {
    "ticker_precision_pass": true,       // all extracted tickers found in body
    "checked_at": "2026-04-24T13:35:19Z",
    "flags": []                          // e.g. ["hallucinated_ticker:XYZ"]
  },

  // M3: Async LLM-as-Judge (filled by /cron/eval-judge)
  "eval_score": {
    "score": 8.5,                        // 0-10
    "judge_model": "gemini-2.5-pro",
    "judged_at": "2026-04-25T04:30:12Z",
    "issues": ["missing_ticker:TSLA"],
    "reasoning": "Ticker AAPL correct; sentiment aligns with earnings beat; missed TSLA reference in paragraph 3."
  },

  // Week 2 reservations (null in Week 1)
  "embedding": null,                     // vector<float, 768>
  "embedding_model": null,
  "embedded_at": null
}
```

### 5.3 `prices/{ticker}` + `prices/{ticker}/daily/{YYYYMMDD}`

```jsonc
// prices/AAPL
{
  "ticker": "AAPL",
  "name": "Apple Inc.",
  "exchange": "NASDAQ",
  "currency": "USD",
  "first_seen_at": "2026-04-24T13:35:18Z",
  "last_refreshed_at": "2026-04-24T21:05:00Z",
  "is_active": true                      // mentioned in any article in last 30 days
}

// prices/AAPL/daily/20260424
{
  "date": "2026-04-24",
  "open": 178.32, "high": 181.50, "low": 177.90, "close": 180.45,
  "volume": 52340000,
  "adj_close": 180.45,
  "fetched_at": "2026-04-24T21:05:00Z",
  "source": "yfinance"
}
```

### 5.4 `runs/{runId}`

Every cron invocation writes one document. Debugging lifeline — answers "did the 3pm scrape actually fire?"

```jsonc
{
  "id": "auto-uuid",
  "kind": "scrape",                      // scrape | refresh-prices | aggregate-metrics | eval-judge
  "source": "wsj",                       // only for scrape
  "started_at": "2026-04-24T13:00:00Z",
  "finished_at": "2026-04-24T13:02:14Z",
  "status": "success",                   // success | partial | failure | noop
  "articles_attempted": 12,
  "articles_ingested": 11,
  "articles_skipped_dup": 1,
  "errors": [
    { "url": "...", "stage": "fetch", "message": "403 paywall" }
  ],
  "cost_usd": 0.0142
}
```

### 5.5 `metrics/{YYYYMMDD}`

Pre-aggregated daily stats so `/admin/stats` can serve without re-scanning articles.

```jsonc
{
  "date": "2026-04-24",
  "articles_total": 156,
  "by_source": { "hn": 78, "reuters": 45, "wsj": 33 },
  "by_sentiment": { "bullish": 52, "bearish": 38, "neutral": 66 },
  "ticker_extraction_rate": 0.87,
  "unique_tickers_seen": 124,
  "top_tickers": [
    { "ticker": "AAPL", "count": 12 },
    { "ticker": "TSLA", "count": 9 }
  ],
  "gemini_cost_usd_total": 0.184,
  "gemini_avg_latency_ms": 2410,
  "ingest_errors_total": 4,

  // M2 + M3 aggregations
  "m2_precision_pass_rate": 0.93,
  "m3_avg_score": 7.8,
  "m2_m3_disagreement_count": 3,
  "m2_m3_disagreement_rate": 0.019
}
```

### 5.6 Composite Indexes (Week 1)

| Collection | Fields | Used by |
|---|---|---|
| `articles` | `source ASC, published_at DESC` | Listing latest per source |
| `articles` | `tickers ARRAY_CONTAINS, published_at DESC` | All news mentioning `$TICKER` |
| `articles` | `processed_at DESC` | `/admin/articles` default sort |
| `runs` | `kind ASC, started_at DESC` | Cron debugging |

**Vector index (Week 2 only):** `users/{uid}/memory.embedding`, 768 dims, cosine distance.

### 5.7 GCS Raw Archive

- **Bucket:** `auralee-api-server-raw` (same region, Standard storage)
- **Path:** `gs://auralee-api-server-raw/{source}/{YYYY-MM-DD}/{articleId}.html`
- **Lifecycle:** transition to Nearline at 90 days (Week 2 tuning)
- **Purpose:** reprocess articles after prompt changes; debug extraction drift

---

## 6. `/ingest` Contract & Gemini Prompt

### 6.1 Endpoint

```http
POST /ingest
Content-Type: application/json
X-Admin-Token: <token-from-secret-manager>
```

**Request body** (discriminated union on `raw.kind`):

```jsonc
{
  "source": "wsj",
  "source_id": "WP-12345",
  "url": "https://www.wsj.com/articles/...",
  "fetched_at": "2026-04-24T13:35:12Z",
  "raw": {
    "kind": "html",
    "html": "<html>...</html>",
    "encoding": "utf-8"
  }
  // Or:
  // "raw": { "kind": "text", "title": "...", "body": "...", "metadata": {...} }
}
```

**Response (200):**

```jsonc
{
  "article_id": "wsj_20260424_a3f1b9d2",
  "status": "ingested",                  // ingested | duplicate | skipped_short
  "extracted": { /* Pydantic Extraction model */ },
  "meta": {
    "tokens_in": 5821, "tokens_out": 412,
    "cost_usd": 0.00045, "latency_ms": 2340,
    "prompt_version": "v1",
    "raw_html_gcs_uri": "gs://..."
  }
}
```

**Status codes:**
- `200` success or idempotent duplicate (check `status` field)
- `422` validation error
- `502` Vertex AI Gemini request failed after one retry
- `504` Gemini call exceeded 30s

### 6.2 Internal Pipeline

```
[1]  Pydantic validation
[2]  Compute article_id = f"{source}_{YYYYMMDD}_{md5(url)[:8]}"
[3]  Firestore existence check → return status=duplicate if present
[4]  HTML normalization → trafilatura clean_text (HTML mode only)
[5]  Length gate: <500 chars → status=skipped_short
[6]  Fire-and-forget upload raw to GCS
[7]  Call Gemini 2.5 Flash with response_schema + cached system instruction
[8]  Pydantic-validate Gemini output
[9]  M2 sanity_check inline (regex + company→ticker dictionary)
[10] Write articles/{article_id}
[11] Upsert prices/{ticker} stubs for new tickers
[12] Return response
```

### 6.3 Gemini Prompt Design

**Pydantic response schema:**

```python
class Sentiment(BaseModel):
    score: float = Field(ge=-1.0, le=1.0)
    label: Literal["bullish", "bearish", "neutral"]

class Entity(BaseModel):
    type: Literal["company", "person", "location", "product"]
    name: str
    ticker: Optional[str] = None

class Extraction(BaseModel):
    title: str
    summary: str
    tickers: list[str] = Field(default_factory=list)
    sentiment: Sentiment
    core_thesis: str
    categories: list[str] = Field(default_factory=list)
    entities: list[Entity] = Field(default_factory=list)
    language: str
```

**System instruction (v1, cached):**

```
You are a financial news analyst. Extract structured data from news articles.

RULES:

1. tickers — Only US-listed equities (NYSE, NASDAQ). Uppercase, no exchange prefix.
   - "Apple" → "AAPL". "Tesla" → "TSLA".
   - Do NOT invent tickers for private companies or vague references.
   - If unsure, OMIT. Empty list is correct.

2. sentiment — Direction for the PRIMARY SUBJECT of the article.
   - score: -1.0 (most bearish) to +1.0 (most bullish); 0.0 for neutral/factual
   - label: bullish | bearish | neutral
   - Pure factual reporting (e.g. Fed action announcement) → neutral / 0.0

3. summary — 2-3 sentences, factual, in the SAME language as the article.

4. core_thesis — Article's central argument, 1 sentence.

5. entities — Named companies, people, locations, products. Skip generic terms.

6. NEVER fabricate. If unknown, return safe defaults (empty list / "neutral").

EXAMPLES:
[Three few-shot examples in full prompt]
```

**Gemini SDK call:**

```python
response = client.models.generate_content(
    model="gemini-2.5-flash",
    config=types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION_V1,
        response_mime_type="application/json",
        response_schema=Extraction,
        temperature=0.1,
        cached_content=cached_system_handle,
        max_output_tokens=2048,
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    ),
    contents=[user_message],
)
extraction = Extraction.model_validate_json(response.text)
```

### 6.4 Cost Per Article

Gemini 2.5 Flash pricing (late-2025):
- Input: $0.075/M tokens (cached: $0.01875/M)
- Output: $0.30/M tokens

Per article estimate:
- Cached system (~800 tok): $0.000015
- Uncached article body (~5000 tok): $0.000375
- Output (~400 tok): $0.000120
- **Total: ~$0.0005/article** (well below $0.01 threshold)

### 6.5 Edge Cases

| Condition | Handling |
|---|---|
| `clean_text` < 500 chars (paywall/empty) | Skip Gemini call, `status=skipped_short` |
| Gemini returns invalid JSON | `response_schema` prevents; if it still happens, retry once |
| Gemini 5xx | Exponential backoff, one retry, then 502 |
| Duplicate `article_id` | Return existing doc, `status=duplicate` |
| HTML extraction returns garbage | Fall back to raw text; GCS archive enables re-extraction |
| Non-English article | Gemini handles multilingual; summary in source language |

### 6.6 Idempotency

`POST /ingest` with the same payload → same `article_id` → second call returns existing doc without calling Gemini. Safe for Scheduler retries.

---

## 7. Scrape Workers & Price Fetcher

### 7.1 Common Scaffolding

```python
class Candidate(BaseModel):
    source_id: str
    url: str
    title: str | None
    published_at: datetime | None

class BaseScraper(ABC):
    source_name: str
    async def list_candidates(self, limit: int = 50) -> list[Candidate]: ...
    async def fetch_one(self, c: Candidate) -> IngestPayload: ...
```

**Cron handler pattern** (applies to all three scrape endpoints):

```python
async def cron_scrape(source: Literal["hn","reuters","wsj"]):
    scraper = SCRAPERS[source]()
    run = Run(kind="scrape", source=source, started_at=utcnow())
    for c in await scraper.list_candidates():
        article_id = compute_article_id(source, c.published_at, c.url)
        if articles_exists(article_id):
            run.skipped_dup += 1
            continue
        try:
            payload = await scraper.fetch_one(c)
            result = await ingest_service.process(payload)  # direct call, no HTTP
            run.ingested += 1
            run.cost_usd += result.meta.cost_usd
        except Exception as e:
            run.errors.append({"url": c.url, "stage": classify(e), "message": str(e)[:200]})
    run.finished_at = utcnow()
    runs_collection.add(run)
    return run.summary()
```

**Design note:** scrapers invoke `ingest_service.process()` directly (in-process function call), not HTTP self-call. The HTTP `/ingest` router is a thin Pydantic wrapper around the same service function. Week 2 split to Cloud Run Job replaces the function call with an HTTP client.

### 7.2 Hacker News Scraper

- **Source:** Firebase HN API (free, no auth)
- **Strategy:** top 30 stories, fetch linked external URL via `trafilatura`, fall back to title-only on fetch failure
- **Cadence:** hourly at `:05`

```python
TOP_STORIES_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{id}.json"
```

Let Gemini determine whether each story is financially relevant (empty tickers + neutral sentiment implicitly flags non-financial content). This is part of the PoC — measuring HN's financial signal density.

### 7.3 Reuters Scraper

- **Source:** free RSS feeds
  - `https://feeds.reuters.com/reuters/businessNews`
  - `https://feeds.reuters.com/reuters/marketsNews`
- **Strategy:** parse RSS via `feedparser`, fetch full article via `trafilatura`
- **Cadence:** hourly at `:15`

Reuters has partially paywalled content since 2022. If failure rate > 20% in runs, evaluate paid API in Week 2.

### 7.4 WSJ Scraper (Highest Risk)

- **Source:** RSS feeds (no auth) + full article fetch using user-provided cookie from Secret Manager
  - `https://feeds.a.dj.com/rss/RSSWSJD.xml` (What's News)
  - `https://feeds.a.dj.com/rss/RSSMarketsMain.xml` (Markets) ★ primary validation target
  - `https://feeds.a.dj.com/rss/RSSWSJBuyside.xml`
- **Strategy:** RSS → full HTML fetch with cookie + desktop user-agent + Referer header
- **Cadence:** hourly at `:25`

**Cookie handling:**
- Loaded from Secret Manager at cold start, cached in process
- Paywall detection: if `"Sign In to Continue Reading"` in HTML OR HTML length < 5000 chars → raise `WSJCookieExpiredError`
- Expired cookie → logged to `runs.errors` with stage=`cookie_expired`; Week 2 will add email alert
- Cookie refresh: user manually re-uploads to Secret Manager via `gcloud secrets versions add`

**Risk mitigations:**

| Risk | Mitigation |
|---|---|
| Cookie expiry (1-2 weeks) | Paywall keyword detection → clear error; manual refresh flow |
| IP blocking on Cloud Run egress | us-east1 chosen; if sustained 403s, investigate egress IP range |
| Rate-limit pattern detection | 2-3s sleep between fetches |
| HTML structure drift | `trafilatura` is generic; GCS raw archive enables re-extraction |

### 7.5 Price Fetcher (`yfinance`)

- **Source:** Yahoo Finance via `yfinance` library (unofficial, free)
- **Cadence:** daily after US market close (UTC 21:00)
- **Strategy:** batch fetch via `yf.download()` for all `is_active` tickers

```python
async def cron_refresh_prices():
    run = Run(kind="refresh-prices", started_at=utcnow())
    active = list(prices_collection.where("is_active", "==", True).stream())
    if not active:
        run.status = "noop"; run.finished_at = utcnow()
        runs_collection.add(run); return run.summary()

    tickers = [d.id for d in active]
    data = yf.download(tickers, period="1mo", group_by="ticker",
                       auto_adjust=False, threads=True, progress=False)

    for ticker in tickers:
        try:
            df = data[ticker] if len(tickers) > 1 else data
            df = df.dropna(subset=["Close"])
            batch = firestore.batch()
            for date_idx, row in df.iterrows():
                doc = (prices_collection.document(ticker)
                       .collection("daily").document(date_idx.strftime("%Y%m%d")))
                batch.set(doc, {
                    "date": date_idx.date().isoformat(),
                    "open": float(row["Open"]), "high": float(row["High"]),
                    "low": float(row["Low"]),   "close": float(row["Close"]),
                    "volume": int(row["Volume"]),
                    "adj_close": float(row["Adj Close"]),
                    "fetched_at": utcnow(),
                    "source": "yfinance",
                })
            batch.commit()
            prices_collection.document(ticker).update({"last_refreshed_at": utcnow()})
            run.refreshed += 1
        except Exception as e:
            run.errors.append({"ticker": ticker, "message": str(e)[:200]})

    run.finished_at = utcnow()
    runs_collection.add(run)
    return run.summary()
```

**`is_active` maintenance:** `/cron/aggregate-metrics` daily sets tickers mentioned in any article within last 30 days to `is_active=true`, others to `false`. Prevents unbounded yfinance growth.

**Fallback:** if Yahoo proves unreliable, migrate to Polygon.io at $29/month in Week 2.

### 7.6 Cloud Scheduler Jobs

| Job name | Cron (UTC) | Endpoint | Purpose |
|---|---|---|---|
| `scrape-hn-hourly` | `5 * * * *` | `POST /cron/scrape?source=hn` | Offset by 5 min |
| `scrape-reuters-hourly` | `15 * * * *` | `POST /cron/scrape?source=reuters` | Offset 10 min from HN |
| `scrape-wsj-hourly` | `25 * * * *` | `POST /cron/scrape?source=wsj` | Offset 10 min from Reuters |
| `refresh-prices-daily` | `0 21 * * *` | `POST /cron/refresh-prices` | After US market close |
| `aggregate-metrics-daily` | `55 23 * * *` | `POST /cron/aggregate-metrics` | End of UTC day |
| `eval-judge-daily` | `30 4 * * *` | `POST /cron/eval-judge` | Before US market open |

Offset timing avoids simultaneous cold starts and keeps logs cleanly attributable.

### 7.7 `/cron/eval-judge` (M3 implementation)

Pulls the last 24h of articles, calls Gemini 2.5 Pro with a judge prompt to grade each, writes `articles.{id}.eval_score`.

Judge prompt (abbreviated):

```
You are evaluating a structured extraction from a financial news article.

Given the article text and the extraction output, rate 0-10 on these dimensions:
- tickers: precision (no hallucinations) and recall (no missed US-listed equities)
- sentiment: correctness for the primary subject
- summary: factual accuracy and completeness

Return JSON:
{
  "score": 0-10,
  "issues": ["missing_ticker:XYZ", "wrong_sentiment", ...],
  "reasoning": "brief explanation"
}
```

Cost estimate: Gemini 2.5 Pro at ~$1.25/M input, $5/M output → ~$0.01/article judged × 100/day × 30 = **~$3/month**.

---

## 8. Dockerfile, Cloud Run, IAM, CI/CD

### 8.1 Dockerfile

```dockerfile
# syntax=docker/dockerfile:1.7

FROM python:3.12-slim-bookworm AS builder
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PYTHON_DOWNLOADS=never
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY app/ ./app/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

FROM python:3.12-slim-bookworm AS runtime
RUN groupadd --system app && useradd --system --gid app --no-create-home app
WORKDIR /app
COPY --from=builder --chown=app:app /app /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080
USER app
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
```

### 8.2 `pyproject.toml`

```toml
[project]
name = "auralee-api"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "pydantic>=2.9",
    "pydantic-settings>=2.6",
    "google-genai>=0.3",
    "google-cloud-firestore>=2.19",
    "google-cloud-secret-manager>=2.21",
    "google-cloud-storage>=2.18",
    "google-cloud-logging>=3.11",
    "httpx>=0.28",
    "trafilatura>=1.12",
    "feedparser>=6.0",
    "yfinance>=0.2.50",
]

[dependency-groups]
dev = ["pytest>=8.3", "pytest-asyncio>=0.24", "ruff>=0.8", "mypy>=1.13"]
```

### 8.3 `cloudbuild.yaml`

```yaml
steps:
  - name: gcr.io/cloud-builders/docker
    id: build
    args:
      - build
      - --tag=${_REGION}-docker.pkg.dev/${PROJECT_ID}/${_REPO}/${_SERVICE}:${_SHA}
      - --tag=${_REGION}-docker.pkg.dev/${PROJECT_ID}/${_REPO}/${_SERVICE}:latest
      - --cache-from=${_REGION}-docker.pkg.dev/${PROJECT_ID}/${_REPO}/${_SERVICE}:latest
      - .

  - name: gcr.io/cloud-builders/docker
    id: push
    args:
      - push
      - --all-tags
      - ${_REGION}-docker.pkg.dev/${PROJECT_ID}/${_REPO}/${_SERVICE}

images:
  - ${_REGION}-docker.pkg.dev/${PROJECT_ID}/${_REPO}/${_SERVICE}:${_SHA}
  - ${_REGION}-docker.pkg.dev/${PROJECT_ID}/${_REPO}/${_SERVICE}:latest

substitutions:
  _REGION: us-east1
  _REPO: api
  _SERVICE: auralee-api
  _SHA: latest

options:
  machineType: E2_HIGHCPU_8
  logging: CLOUD_LOGGING_ONLY

serviceAccount: projects/${PROJECT_ID}/serviceAccounts/auralee-cloudbuild@${PROJECT_ID}.iam.gserviceaccount.com
```

### 8.4 Cloud Run Deploy Command

```bash
gcloud run deploy auralee-api \
  --image us-east1-docker.pkg.dev/auralee-api-server/api/auralee-api:${SHA} \
  --region us-east1 \
  --no-allow-unauthenticated \
  --service-account auralee-runtime@auralee-api-server.iam.gserviceaccount.com \
  --memory 1Gi --cpu 1 \
  --min-instances 0 --max-instances 3 \
  --concurrency 10 \
  --timeout 600 \
  --execution-environment gen2 \
  --set-env-vars "GCP_PROJECT=auralee-api-server,GCP_REGION=us-east1,LOG_LEVEL=INFO,PROMPT_VERSION=v1" \
  --set-secrets "WSJ_COOKIE=WSJ_COOKIE:latest,ADMIN_TOKEN=ADMIN_TOKEN:latest"
```

### 8.5 Service Accounts (four, least-privilege)

| SA | Purpose | Roles |
|---|---|---|
| `auralee-runtime` | Cloud Run runtime identity | `datastore.user` · `secretmanager.secretAccessor` · `aiplatform.user` · `storage.objectAdmin` (raw bucket) · `logging.logWriter` |
| `auralee-scheduler` | Cloud Scheduler → Cloud Run invoker | `run.invoker` on `auralee-api` only |
| `auralee-deployer` | GitHub Actions deployment | `cloudbuild.builds.editor` · `run.developer` · `iam.serviceAccountUser` on `auralee-runtime` and `auralee-cloudbuild` |
| `auralee-cloudbuild` | Cloud Build worker identity | `artifactregistry.writer` · `logging.logWriter` · `storage.objectUser` (staging) |

**Anti-patterns explicitly avoided:**
- Default compute SA (excessive default permissions)
- `roles/owner` or `roles/editor` on any project SA
- Downloaded SA JSON keys (WIF used instead)

### 8.6 Secret Manager

Two secrets. Cloud Run mounts them as env vars via `--set-secrets`. Gemini uses
Vertex AI with runtime service-account ADC, so it does not require an API-key secret.

| Secret | Content | Source | Refresh |
|---|---|---|---|
| `WSJ_COOKIE` | Full WSJ session cookie string | User's browser export | Every 1-2 weeks when paywall re-triggers |
| `ADMIN_TOKEN` | 64-char random | `openssl rand -hex 32` | Never (until compromise) |

**Security invariants:**
- Secrets never enter Git, logs, or AI assistant context
- Cookie flow is direct: user's browser → `gcloud secrets versions add` → Cloud Run
- `--set-secrets` uses latest alias; Cloud Run reloads on cold start or explicit service update

### 8.7 GitHub Actions Workflow

```yaml
name: Deploy auralee-api
on:
  push:
    branches: [main]
    paths: ['services/api/**', '.github/workflows/deploy.yml']
  workflow_dispatch:

env:
  PROJECT_ID: auralee-api-server
  REGION: us-east1
  REPO: api
  SERVICE: auralee-api

jobs:
  deploy:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      id-token: write
    steps:
      - uses: actions/checkout@v4
      - uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: projects/${{ secrets.GCP_PROJECT_NUMBER }}/locations/global/workloadIdentityPools/github-pool/providers/github-provider
          service_account: auralee-deployer@${{ env.PROJECT_ID }}.iam.gserviceaccount.com
      - uses: google-github-actions/setup-gcloud@v2

      - name: Submit Cloud Build
        working-directory: services/api
        run: |
          gcloud builds submit \
            --config=cloudbuild.yaml \
            --region=${REGION} \
            --substitutions=_SHA=${GITHUB_SHA},_REGION=${REGION},_REPO=${REPO},_SERVICE=${SERVICE} \
            .

      - name: Deploy to Cloud Run
        run: |
          gcloud run deploy "$SERVICE" \
            --image "${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/${SERVICE}:${GITHUB_SHA}" \
            --region "$REGION" --no-allow-unauthenticated \
            --service-account "auralee-runtime@${PROJECT_ID}.iam.gserviceaccount.com" \
            --memory 1Gi --cpu 1 \
            --min-instances 0 --max-instances 3 \
            --concurrency 10 --timeout 600 --execution-environment gen2 \
            --set-env-vars "GCP_PROJECT=${PROJECT_ID},GCP_REGION=${REGION},LOG_LEVEL=INFO,PROMPT_VERSION=v1" \
            --set-secrets "WSJ_COOKIE=WSJ_COOKIE:latest,ADMIN_TOKEN=ADMIN_TOKEN:latest"
```

### 8.8 One-Time Setup Order

```
[Manual]  1. Create GCP project `auralee-api-server` in Console, enable billing
[Script]  2. ./00-bootstrap.sh           — Enable 10 APIs
[Script]  3. ./01-create-service-accounts.sh  — 4 SAs
[Script]  4. ./02-create-secrets.sh      — 2 empty secrets
[Script]  5. ./03-create-buckets.sh      — GCS raw bucket
[Script]  6. ./04-create-firestore.sh    — Native mode in us-east1
[Script]  7. ./05-create-artifact-registry.sh
[Script]  8. ./06-grant-iam.sh           — All bindings
[Script]  9. ./07-setup-wif.sh           — Outputs GCP_PROJECT_NUMBER
[Manual] 10. GitHub repo → Settings → Secrets: add GCP_PROJECT_NUMBER
[Manual] 11. Populate Secret Manager values (WSJ_COOKIE, ADMIN_TOKEN)
[Git]    12. git push origin main → GitHub Actions auto-deploys
[Script] 13. ./08-create-scheduler-jobs.sh  — 6 cron jobs (after first deploy)
```

### 8.9 APIs to Enable

```
run.googleapis.com                     artifactregistry.googleapis.com
firestore.googleapis.com               secretmanager.googleapis.com
cloudscheduler.googleapis.com          storage.googleapis.com
logging.googleapis.com                 aiplatform.googleapis.com
cloudbuild.googleapis.com              iamcredentials.googleapis.com
```

---

## 9. Cost, Monitoring, Evaluation

### 9.1 Monthly Cost Estimate

Assuming ~3000 ingested articles/month, ~30 active tickers, 6 cron jobs:

| Service | Cost | Notes |
|---|---|---|
| Cloud Run | $5 – $15 | vCPU-seconds from cron runtime |
| Firestore | $0 | Within 20K writes/day free tier |
| Cloud Scheduler | $0.30 | 6 jobs, first 3 free |
| Secret Manager | $0 | 2 secrets in free tier |
| GCS (raw archive) | < $0.01 | ~150MB/month |
| Artifact Registry | $0.10 | ~1GB including cache layers |
| Gemini Flash (ingest) | $1.50 | ~3000 articles × $0.0005 |
| Gemini Pro (judge) | $3.00 | ~3000 articles × $0.01 |
| Cloud Build | $0 | Under 120 min/day free tier |
| Cloud Logging | $0 | ~15MB/month |
| Network egress | $0 | In-region + free ingress |
| **Total** | **$10 – $20** | 5-10% of $200 budget |

### 9.2 Monitoring Stack (PoC-weight)

Five observation surfaces — no Prometheus, no custom dashboards.

1. **Cloud Run console** — request count, p50/p99 latency, error rate, instance count
2. **Cloud Scheduler console** — last status per cron job
3. **`GET /admin/stats`** — daily aggregated metrics (from `metrics/{date}`)
4. **`GET /admin/runs`** — per-run debug detail
5. **`notebooks/analyze.ipynb`** — end-of-week decision analysis

### 9.3 Alerts (two only)

1. **GCP Budget Alert** — $50/month, notify at 50% / 90% / 100% via email
2. **Log-based Error Alert** — match `resource.type="cloud_run_revision" AND severity="ERROR"`, trigger on ≥3 events in 5 min, notify via email

### 9.4 Evaluation Methodology (M2 + M3, Zero Human Involvement)

**M2 — Regex Precision Check (inline with `/ingest`):**

For every extracted ticker, check whether the ticker symbol OR the company name appears in the cleaned article body. Maintained company→ticker dictionary sourced from SEC EDGAR (~5000 entries for major US equities).

- Covers 100% of articles, zero cost, runs synchronously with ingestion
- Writes to `articles.{id}.sanity_check`
- Catches hallucinations (high-precision check)
- Limitation: cannot detect missed tickers (recall)

**M3 — LLM-as-Judge (daily cron):**

`/cron/eval-judge` runs at 04:30 UTC, pulls articles processed in the last 24 hours, calls Gemini 2.5 Pro with a rubric prompt to grade each.

- Covers 100% of new articles daily
- Cost: ~$3/month
- Writes to `articles.{id}.eval_score` with `score`, `issues`, `reasoning`
- Catches both precision and recall issues, plus sentiment and summary quality
- Limitation: shared-bias risk with Flash (both are Gemini family)

**M2 ↔ M3 Cross-Check (meta-indicator of system trustworthiness):**

Aggregated daily in `metrics/{date}`:

- `M2 fail & M3 score > 7` → judge missed a hallucination
- `M2 pass & M3 score < 4` → judge flagged something regex didn't see
- Daily disagreement rate > 10% → evaluation system itself is unreliable; investigate

### 9.5 Week 1 Evaluation Notebook Structure

```
Cell 1: Setup — Firestore client, load last 7 days of articles
Cell 2: Volume — articles/day by source (line chart)
Cell 3: Automated Quality — M2 pass rate, M3 score distribution, disagreement count
Cell 4: Sentiment Distribution — histogram by source
Cell 5: Price Reaction (CORE HYPOTHESIS) — bullish − bearish next-day return spread
Cell 6: Error Analysis — WSJ success rate trend, error breakdown by stage
Cell 7: Cost Tracking — total / per-article / per-source
Cell 8: Week 1 Scorecard — 7 threshold metrics in a single dict, color-coded pass/fail
```

All cells read Firestore directly via `google-cloud-firestore` with ADC (`gcloud auth application-default login`). No deployment needed. Notebook source is committed; outputs are gitignored.

---

## 10. `/admin/*` Endpoints

All require `X-Admin-Token` header.

```
GET  /admin/stats                         # Today's aggregated metrics
GET  /admin/stats?date=YYYY-MM-DD         # Specific day
GET  /admin/stats/summary?days=7          # N-day rollup

GET  /admin/articles?source=X&limit=N     # List recent articles
GET  /admin/articles/{article_id}         # Single article detail (with GCS URI)

GET  /admin/runs?kind=scrape&source=X     # Run history
GET  /admin/runs/{run_id}                 # Single run detail

GET  /admin/healthz                       # Liveness
GET  /admin/healthz-detail                # Firestore + Vertex model reachability + WSJ cookie validity

POST /admin/reingest/{article_id}         # Re-extract using current prompt version (A/B)
```

Simple offset+limit pagination (no cursor). PoC scale doesn't warrant it.

---

## 11. Known Limitations & Open Questions

### 11.1 Accepted Risks for Phase 1

| Risk | Accepted Because |
|---|---|
| LLM-as-Judge and Flash share family bias | Zero-human evaluation policy; M2 provides independent signal |
| WSJ cookie may fail silently if detection heuristic is bypassed | PoC; Week 2 adds active cookie-health probe |
| `yfinance` is unofficial | Free and sufficient for PoC; Polygon.io is $29/mo fallback |
| Company→ticker dictionary missing recent IPOs | SEC EDGAR refresh monthly; gaps flagged in M2 logs |
| No rate-limiting on `/admin/*` | Private service + admin token + small scale |
| HN scraper fetches any top story, not pre-filtered for finance | This is deliberate — PoC measures HN's financial signal density |

### 11.2 Open Questions for Week 2

- Cookie refresh automation: browser extension? GCP-hosted headless login?
- Polygon.io evaluation if yfinance proves flaky
- Firebase Auth integration and desktop app auth flow
- Vector embedding model choice (Gemini text-embedding-004 at 768 vs. alternatives)
- Pub/Sub split: when does scraper traffic justify moving off monolith?

---

## 12. Week 1 Readiness Checklist

Before beginning implementation, verify:

- [ ] GCP project `auralee-api-server` exists, billing enabled
- [ ] `gcloud` CLI installed and authenticated locally
- [ ] User has current WSJ US account and can export cookies from browser
- [ ] Vertex AI API enabled and runtime SA granted `roles/aiplatform.user`
- [ ] GitHub repo `enclairfarron/Auralee` cloned locally
- [ ] `uv` installed (≥0.5)
- [ ] Docker Desktop installed (for local build testing)
- [ ] Python 3.12 available

Once all items are checked, proceed to the implementation plan (written in a separate document by the `writing-plans` skill).

---

## 13. Changelog

- **2026-04-24** — v1 draft authored during brainstorm session; decisions D1–D11 finalized
- **2026-04-25** — Phase 1 deployed; significant deviations recorded in §14

---

## 14. Phase 1 Deployment Findings (2026-04-25)

Deployed and observed. Summary of deviations from the original spec:

### Worked as designed
- Single Cloud Run Service architecture (option A)
- Firestore schema, doc IDs, GCS raw archive
- Hacker News scraper end-to-end (≥27 articles ingested with full extraction)
- M2 sanity check inline with `/ingest`
- `/admin/*` endpoints (modulo `runs` composite index — see below)
- 6 Cloud Scheduler jobs auto-running
- Workload Identity Federation + GitHub Actions auto-deploy
- Cost tracking (~$0.0003/article via Vertex AI)

### Deviated — required fixes
1. **Gemini billing model** (D4 superseded). AI Studio API keys require
   prepayment credits in some accounts (returns 429 RESOURCE_EXHAUSTED).
   Switched all Gemini calls to Vertex AI (`genai.Client(vertexai=True, ...)`)
   so billing flows through the GCP project. Runtime SA needs
   `roles/aiplatform.user`. No separate Gemini API-key secret is used.
2. **Reuters RSS** is dead (`feeds.reuters.com` offline as of 2025).
   Replaced with MarketWatch RSS (Dow Jones owned). Source enum still
   labels these "reuters" — TODO Week 2 rename to "marketwatch".
3. **MarketWatch full-article fetch** returns 401 from Cloud Run
   (Dow Jones anti-bot blocks datacenter IPs). Scraper now uses RSS
   `<description>` field as body instead of HTTP-fetching the article URL.
   `_MIN_CLEAN_TEXT_CHARS` lowered 500 → 200 to accommodate.
4. **`response_schema` Pydantic class** triggers a google-genai SDK quirk
   that emits `additional_properties` in the protobuf. AI Studio rejected
   it; Vertex AI accepts it. After the Vertex switch, response_schema
   was re-enabled.
5. **Cloud Build `--mount=type=cache`** requires BuildKit. Added
   `DOCKER_BUILDKIT=1` env var on the cloudbuild step.
6. **Deployer SA missing perms** for Cloud Build via GHA: needed
   `serviceusage.serviceUsageConsumer`, `logging.viewer`, and
   `storage.objectAdmin` on the auto-created `${PROJECT_ID}_cloudbuild`
   bucket. `cloudbuild.builds.builder` (deprecated combined role) was
   also added defensively.
7. **ADMIN_TOKEN trailing newline** from `openssl rand -hex 32 | gcloud
   secrets versions add ...` caused header-comparison failures. Re-uploaded
   with `tr -d '\n'` filter.

### Unfixed limitations (deferred to Week 2)
1. **WSJ paywalled content scraping is impossible from server-side IPs.**
   Akamai blocks all known datacenter ranges (Cloud Run, AWS Lambda, etc.)
   regardless of cookie validity or TLS fingerprint. Diagnosis path
   exhausted: tested httpx (TLS fingerprint), curl_cffi
   (`impersonate=safari184` matches Safari JA3 perfectly), full browser
   header set including Sec-Fetch-* — all return 401 from Cloud Run.
   Same code from a residential IP (user's home network through VPN)
   returns 200 + 714KB body. **Architecture fix for Week 2: move WSJ
   scraping to the Tauri desktop client** (runs from user's residential
   IP, naturally bypasses datacenter blocklist). The Phase 1 WSJ cron
   continues to run hourly and fail — the failure rate is captured in
   the `wsj_success_rate` Day-7 metric (will show 0%, accurately
   reflecting reality).
2. **Firestore composite index on `runs(kind, started_at desc)`** not
   yet created. `/admin/runs?kind=scrape` returns 500 with a Firebase
   console URL to one-click create the index. Manual click pending; the
   error message is informative and the index is single-use.
3. **MarketWatch source label says "reuters"** — Source enum + scheduler
   job names still reference Reuters. Cosmetic but misleading.
4. **`tickers.json` only 30 entries** — limits M2 precision check accuracy
   for non-mega-cap names. SEC EDGAR has full list, deferred.
5. **Cloud Run reserves/intercepts the exact `/healthz` path** on the
   deployed service even though FastAPI registers it. The canonical
   external liveness route is now `/health`; `/healthz` remains a local
   compatibility alias.

### Day-7 expected outcome (with current source mix)

| Metric                    | Threshold | Realistic actual |
|---------------------------|-----------|------------------|
| volume/day                | >100      | likely PASS (HN 30/h × 24 + MW ~20-40/day) |
| m2_precision_rate         | >90%      | depends on Gemini quality |
| m3_avg_score              | >7.0      | depends |
| m2_m3_disagreement_rate   | <5%       | depends |
| price_signal_spread       | >1%       | depends — most HN/MW articles are non-financial |
| avg_cost_per_article      | <$0.01    | likely PASS (~$0.0003) |
| wsj_success_rate          | >80%      | **0% (deferred to Week 2)** |

Day-7 evaluation must interpret `wsj_success_rate=0` as "expected,
documented limitation" not "broken pipeline."
