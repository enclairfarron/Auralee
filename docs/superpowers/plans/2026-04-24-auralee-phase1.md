# Auralee Phase 1 Implementation Plan

> **Historical implementation record.** Do not use the embedded scheduler commands or scorecard
> as the current runbook. See [`docs/roadmap.md`](../../roadmap.md) and `infra/scripts/` for the
> active plan; they supersede conflicting steps below.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a single FastAPI service on Cloud Run that ingests news from Hacker News, Reuters, and WSJ, processes via Gemini 2.5 Flash, refreshes daily US equity prices via yfinance, and writes everything to Firestore — instrumented with M2 regex sanity checks and M3 LLM-as-Judge so the user can decide on day 7 whether to build the desktop app.

**Architecture:** Single Cloud Run Service (FastAPI, Python 3.12, uv) triggered by Cloud Scheduler for hourly scrapes, daily price refresh, daily metric aggregation, and daily judge eval. All state in Firestore + GCS (raw HTML). Secrets in Secret Manager. CI via GitHub Actions → Cloud Build → `gcloud run deploy`. Workload Identity Federation auth (no service-account JSON keys).

**Tech Stack:** Python 3.12 · uv · FastAPI · pydantic v2 · google-genai · google-cloud-{firestore,secret-manager,storage,logging} · httpx · trafilatura · feedparser · yfinance · Docker · gcloud · GitHub Actions · Cloud Build · Cloud Run · Firestore (Native) · Cloud Scheduler

---

## File Structure

Plan-time decomposition. Every file has one responsibility; modules small enough to hold in context.

### `services/api/` — Python service workspace

```
services/api/
├── pyproject.toml             # uv project, deps + dev-deps
├── uv.lock                    # locked deps
├── .python-version            # "3.12"
├── Dockerfile                 # multi-stage uv build
├── cloudbuild.yaml            # Cloud Build config
├── README.md                  # how to run/deploy locally
├── .dockerignore
├── app/
│   ├── __init__.py
│   ├── main.py                # FastAPI app, router wiring, startup hooks
│   ├── config.py              # Settings via pydantic-settings
│   ├── deps.py                # FastAPI deps: GCP clients, auth guards
│   ├── http_client.py         # Shared httpx.AsyncClient + UA constants
│   ├── logging_setup.py       # Cloud Logging structured handler
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── health.py          # /healthz
│   │   ├── ingest.py          # POST /ingest
│   │   ├── cron.py            # /cron/scrape, /cron/refresh-prices, /cron/aggregate-metrics, /cron/eval-judge
│   │   └── admin.py           # /admin/articles, /admin/runs, /admin/stats, /admin/healthz-detail, /admin/reingest
│   ├── services/
│   │   ├── __init__.py
│   │   ├── article_id.py      # Pure: compute article_id
│   │   ├── sanity.py          # Pure: M2 regex precision check + ticker dictionary loader
│   │   ├── ingest_service.py  # Core ingest: orchestrates extraction + sanity + write
│   │   ├── gemini.py          # Gemini Flash extraction wrapper
│   │   ├── judge.py           # Gemini Pro judge wrapper
│   │   ├── firestore_repo.py  # Firestore I/O (articles, prices, runs, metrics)
│   │   ├── secrets.py         # Secret Manager wrapper (cached)
│   │   ├── gcs.py             # GCS raw HTML archival (fire-and-forget)
│   │   ├── prices.py          # yfinance wrapper + refresh job
│   │   ├── metrics.py         # Daily aggregation logic
│   │   └── scrapers/
│   │       ├── __init__.py
│   │       ├── base.py        # BaseScraper abstract + Candidate model
│   │       ├── hn.py          # Hacker News
│   │       ├── reuters.py     # Reuters RSS
│   │       └── wsj.py         # WSJ (RSS + cookie fetch)
│   ├── models/
│   │   ├── __init__.py
│   │   ├── article.py         # Article, Extraction, Sentiment, Entity, EvalScore, SanityCheck, GeminiMeta
│   │   ├── price.py           # Price, DailyOHLC
│   │   ├── run.py             # Run, RunError
│   │   ├── ingest.py          # IngestPayload, IngestResponse, RawHtml, RawText
│   │   └── candidate.py       # Candidate
│   └── prompts/
│       ├── __init__.py
│       ├── extraction_v1.py   # SYSTEM_INSTRUCTION_V1, PROMPT_VERSION
│       └── judge_v1.py        # JUDGE_SYSTEM_INSTRUCTION_V1
└── tests/
    ├── __init__.py
    ├── conftest.py            # Fixtures: settings, mock GCP clients
    ├── data/                  # sample HTML / RSS fixtures
    │   ├── wsj_sample.html
    │   ├── reuters_sample.html
    │   ├── reuters_feed.xml
    │   └── wsj_feed.xml
    ├── test_article_id.py
    ├── test_sanity.py
    ├── test_models.py
    ├── test_gemini.py
    ├── test_judge.py
    ├── test_ingest_service.py
    ├── test_metrics.py
    ├── test_scrapers/
    │   ├── __init__.py
    │   ├── test_hn.py
    │   ├── test_reuters.py
    │   └── test_wsj.py
    └── test_routers/
        ├── __init__.py
        ├── test_health.py
        ├── test_ingest_router.py
        ├── test_cron_router.py
        └── test_admin_router.py
```

### `infra/scripts/` — GCP setup (bash, idempotent)

```
infra/scripts/
├── _common.sh                 # PROJECT_ID, REGION, SAs as exported vars; helper fns
├── 00-bootstrap.sh            # Enable 10 APIs
├── 01-create-service-accounts.sh   # 4 SAs
├── 02-create-secrets.sh       # 2 empty secrets
├── 03-create-buckets.sh       # GCS auralee-api-server-raw
├── 04-create-firestore.sh     # Native mode @ us-east1
├── 05-create-artifact-registry.sh  # Docker repo "api"
├── 06-grant-iam.sh            # All bindings
├── 07-setup-wif.sh            # WIF pool + provider
├── 08-create-scheduler-jobs.sh     # 6 cron jobs
└── deploy-local.sh            # Manual deploy (no-CI fallback)
```

### Other repo files

```
.github/workflows/deploy.yml   # GHA → Cloud Build → Cloud Run
.gitignore                     # Python, node, IDE, GCP, notebooks output
notebooks/analyze.ipynb        # E4 evaluation notebook
README.md                      # already exists, will be replaced
```

---

## Conventions

- **Tests:** `pytest` + `pytest-asyncio` + `pytest-httpx` for HTTP mocking. Run from `services/api/` with `uv run pytest`.
- **Lint/format:** `uv run ruff format .` and `uv run ruff check . --fix`. Run before each commit.
- **Type checking:** `uv run mypy app` runs strict on the `app/` tree. Fix errors before commit.
- **Commits:** Conventional commits (`feat:`, `fix:`, `chore:`, `docs:`, `test:`, `ci:`). One concept per commit.
- **TDD discipline:**
  - Pure logic (article_id, sanity check, metrics aggregation, prompt builders): write failing test → see it fail → minimal impl → pass → commit.
  - IO-heavy wrappers (GCP clients, scrapers): smoke test with mocks; rely on deployed-service smoke test for real-world confidence.
  - Routers: FastAPI `TestClient` with monkeypatched service layer.
- **Run from project root:** All bash + git commands assume cwd = `/Users/farron/code/Auralee/`. Python commands assume cwd = `services/api/`.

---

## Phase 0 — Repo Skeleton & Hello-World Deploy

Goal: get an empty FastAPI service deployed to Cloud Run end-to-end before writing any feature code, so deployment isn't blocking later phases.

### Task 0.1: Initialize `.gitignore` and monorepo skeleton dirs

**Files:**
- Create: `.gitignore`
- Create: `services/api/.gitkeep`
- Create: `apps/desktop/.gitkeep`
- Create: `infra/scripts/.gitkeep`
- Create: `notebooks/.gitkeep`

- [ ] **Step 1: Write `.gitignore`**

```gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
.venv/
venv/
env/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/
dist/
build/
*.egg-info/

# uv
.uv-cache/

# Notebooks
*.ipynb_checkpoints/
notebooks/*.html

# IDE
.vscode/
.idea/
*.swp
.DS_Store

# Secrets / local env
.env
.env.local
*.pem
*.key
service-account-*.json

# Tauri / Node (Week 2+)
node_modules/
target/
dist-ssr/

# Build artifacts
*.log
```

- [ ] **Step 2: Create placeholder dirs**

```bash
mkdir -p services/api apps/desktop infra/scripts notebooks
touch services/api/.gitkeep apps/desktop/.gitkeep infra/scripts/.gitkeep notebooks/.gitkeep
```

- [ ] **Step 3: Commit**

```bash
git add .gitignore services/ apps/ infra/ notebooks/
git commit -m "chore: initialize monorepo skeleton"
```

### Task 0.2: Bootstrap `services/api/` Python project with uv

**Files:**
- Create: `services/api/.python-version`
- Create: `services/api/pyproject.toml`
- Create: `services/api/README.md`

- [ ] **Step 1: Verify uv is installed**

```bash
uv --version
```

Expected: `uv 0.5.x` or later. If missing: `brew install uv`.

- [ ] **Step 2: Create `services/api/.python-version`**

```
3.12
```

- [ ] **Step 3: Create `services/api/pyproject.toml`**

```toml
[project]
name = "auralee-api"
version = "0.1.0"
description = "Auralee Phase 1 — data pipeline viability PoC"
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
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "pytest-httpx>=0.34",
    "ruff>=0.8",
    "mypy>=1.13",
    "types-requests>=2.32",
]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "B", "ASYNC", "RUF"]
ignore = ["E501"]  # line length handled by formatter

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["."]

[tool.mypy]
python_version = "3.12"
strict = true
ignore_missing_imports = true
```

- [ ] **Step 4: Create `services/api/README.md`**

```markdown
# auralee-api

Phase 1 backend service. See [/docs/superpowers/specs/2026-04-24-auralee-phase1-design.md](../../docs/superpowers/specs/2026-04-24-auralee-phase1-design.md).

## Local development

```bash
cd services/api
uv sync
uv run uvicorn app.main:app --reload --port 8080
```

Health check: `curl http://localhost:8080/healthz`

## Tests

```bash
uv run pytest
uv run ruff check .
uv run mypy app
```
```

- [ ] **Step 5: Sync dependencies (creates `uv.lock`)**

```bash
cd services/api && uv sync
```

Expected: creates `.venv/`, `uv.lock`, prints "Installed N packages".

- [ ] **Step 6: Commit**

```bash
git add services/api/.python-version services/api/pyproject.toml services/api/uv.lock services/api/README.md
git commit -m "feat(api): bootstrap uv project with deps"
```

### Task 0.3: FastAPI app skeleton with `/healthz`

**Files:**
- Create: `services/api/app/__init__.py`
- Create: `services/api/app/main.py`
- Create: `services/api/app/routers/__init__.py`
- Create: `services/api/app/routers/health.py`
- Create: `services/api/tests/__init__.py`
- Create: `services/api/tests/conftest.py`
- Create: `services/api/tests/test_routers/__init__.py`
- Create: `services/api/tests/test_routers/test_health.py`

- [ ] **Step 1: Write failing health test**

`services/api/tests/test_routers/test_health.py`:

```python
from fastapi.testclient import TestClient


def test_healthz_returns_ok(test_client: TestClient) -> None:
    response = test_client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Create `services/api/tests/conftest.py`**

```python
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def test_client() -> Iterator[TestClient]:
    app = create_app()
    with TestClient(app) as client:
        yield client
```

- [ ] **Step 3: Create empty `__init__.py` files**

```bash
cd services/api
touch app/__init__.py app/routers/__init__.py tests/__init__.py tests/test_routers/__init__.py
```

- [ ] **Step 4: Run test, expect ImportError**

```bash
cd services/api && uv run pytest tests/test_routers/test_health.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.main'`.

- [ ] **Step 5: Implement `services/api/app/routers/health.py`**

```python
from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 6: Implement `services/api/app/main.py`**

```python
from fastapi import FastAPI

from app.routers import health


def create_app() -> FastAPI:
    app = FastAPI(title="auralee-api", version="0.1.0")
    app.include_router(health.router)
    return app


app = create_app()
```

- [ ] **Step 7: Run test, expect PASS**

```bash
cd services/api && uv run pytest tests/test_routers/test_health.py -v
```

Expected: `1 passed`.

- [ ] **Step 8: Boot locally to sanity check**

```bash
cd services/api && uv run uvicorn app.main:app --port 8080 &
sleep 2
curl -s http://localhost:8080/healthz
kill %1
```

Expected: `{"status":"ok"}`.

- [ ] **Step 9: Lint, format, type-check**

```bash
cd services/api && uv run ruff format . && uv run ruff check . --fix && uv run mypy app
```

Expected: no errors.

- [ ] **Step 10: Commit**

```bash
git add services/api/app services/api/tests
git commit -m "feat(api): FastAPI scaffold with /healthz"
```

### Task 0.4: Dockerfile + local container test

**Files:**
- Create: `services/api/Dockerfile`
- Create: `services/api/.dockerignore`

- [ ] **Step 1: Write `services/api/.dockerignore`**

```
.venv
__pycache__
*.pyc
.pytest_cache
.mypy_cache
.ruff_cache
tests/
.git
.gitignore
README.md
```

- [ ] **Step 2: Write `services/api/Dockerfile`**

```dockerfile
# syntax=docker/dockerfile:1.7

FROM python:3.12-slim-bookworm AS builder
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never
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

- [ ] **Step 3: Build image**

```bash
cd services/api && docker build -t auralee-api:dev .
```

Expected: build completes, final image ~150-250MB.

- [ ] **Step 4: Run container and curl healthz**

```bash
docker run --rm -d -p 8080:8080 --name auralee-test auralee-api:dev
sleep 3
curl -s http://localhost:8080/healthz
docker stop auralee-test
```

Expected: `{"status":"ok"}`.

- [ ] **Step 5: Commit**

```bash
git add services/api/Dockerfile services/api/.dockerignore
git commit -m "feat(api): Dockerfile (uv multi-stage)"
```

### Task 0.5: cloudbuild.yaml

**Files:**
- Create: `services/api/cloudbuild.yaml`

- [ ] **Step 1: Write `services/api/cloudbuild.yaml`**

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

- [ ] **Step 2: Commit**

```bash
git add services/api/cloudbuild.yaml
git commit -m "ci(api): add cloudbuild.yaml"
```

### Task 0.6: Bash `_common.sh` and bootstrap script (00)

**Files:**
- Create: `infra/scripts/_common.sh`
- Create: `infra/scripts/00-bootstrap.sh`

- [ ] **Step 1: Write `infra/scripts/_common.sh`**

```bash
#!/usr/bin/env bash
# Sourced by all setup scripts. Defines exported vars + helpers.
set -euo pipefail

export PROJECT_ID="auralee-api-server"
export REGION="us-east1"
export AR_REPO="api"
export SERVICE_NAME="auralee-api"
export RAW_BUCKET="${PROJECT_ID}-raw"

export RUNTIME_SA="auralee-runtime@${PROJECT_ID}.iam.gserviceaccount.com"
export SCHEDULER_SA="auralee-scheduler@${PROJECT_ID}.iam.gserviceaccount.com"
export DEPLOYER_SA="auralee-deployer@${PROJECT_ID}.iam.gserviceaccount.com"
export CLOUDBUILD_SA="auralee-cloudbuild@${PROJECT_ID}.iam.gserviceaccount.com"

export GH_REPO="enclairfarron/Auralee"

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1" >&2; exit 1; }
}

ensure_project() {
  local current
  current=$(gcloud config get-value project 2>/dev/null || true)
  if [[ "${current}" != "${PROJECT_ID}" ]]; then
    echo "Setting active project to ${PROJECT_ID}"
    gcloud config set project "${PROJECT_ID}"
  fi
}

log() { echo "[$(date +%H:%M:%S)] $*"; }
```

- [ ] **Step 2: Write `infra/scripts/00-bootstrap.sh`**

```bash
#!/usr/bin/env bash
# Enables required GCP APIs. Idempotent.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_common.sh
source "${SCRIPT_DIR}/_common.sh"

require_cmd gcloud
ensure_project

APIS=(
  run.googleapis.com
  artifactregistry.googleapis.com
  firestore.googleapis.com
  secretmanager.googleapis.com
  cloudscheduler.googleapis.com
  storage.googleapis.com
  logging.googleapis.com
  aiplatform.googleapis.com
  cloudbuild.googleapis.com
  iamcredentials.googleapis.com
)

log "Enabling ${#APIS[@]} APIs (this may take a minute)..."
gcloud services enable "${APIS[@]}"
log "Done."
```

- [ ] **Step 3: Make executable**

```bash
chmod +x infra/scripts/00-bootstrap.sh
```

- [ ] **Step 4: Commit**

```bash
git add infra/scripts/_common.sh infra/scripts/00-bootstrap.sh
git commit -m "infra: bootstrap script and shared common.sh"
```

### Task 0.7: Bash script 01 — create 4 service accounts

**Files:**
- Create: `infra/scripts/01-create-service-accounts.sh`

- [ ] **Step 1: Write `infra/scripts/01-create-service-accounts.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"

require_cmd gcloud
ensure_project

create_sa() {
  local name="$1"
  local desc="$2"
  if gcloud iam service-accounts describe "${name}@${PROJECT_ID}.iam.gserviceaccount.com" >/dev/null 2>&1; then
    log "SA ${name} exists, skip."
  else
    log "Creating SA ${name}"
    gcloud iam service-accounts create "${name}" --display-name="${desc}"
  fi
}

create_sa auralee-runtime    "Cloud Run runtime for auralee-api"
create_sa auralee-scheduler  "Cloud Scheduler invoker"
create_sa auralee-deployer   "GitHub Actions deployer"
create_sa auralee-cloudbuild "Cloud Build worker"

log "Done. 4 service accounts ready."
```

- [ ] **Step 2: Make executable, commit**

```bash
chmod +x infra/scripts/01-create-service-accounts.sh
git add infra/scripts/01-create-service-accounts.sh
git commit -m "infra: script 01 to create 4 service accounts"
```

### Task 0.8: Bash scripts 02-05 — secrets, bucket, firestore, AR

**Files:**
- Create: `infra/scripts/02-create-secrets.sh`
- Create: `infra/scripts/03-create-buckets.sh`
- Create: `infra/scripts/04-create-firestore.sh`
- Create: `infra/scripts/05-create-artifact-registry.sh`

- [ ] **Step 1: Write `infra/scripts/02-create-secrets.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"

require_cmd gcloud
ensure_project

create_secret() {
  local name="$1"
  if gcloud secrets describe "${name}" >/dev/null 2>&1; then
    log "Secret ${name} exists, skip."
  else
    log "Creating empty secret ${name}"
    gcloud secrets create "${name}" --replication-policy=automatic
  fi
}

create_secret WSJ_COOKIE
create_secret ADMIN_TOKEN

log "Done. Populate values manually:"
log "  pbpaste | gcloud secrets versions add WSJ_COOKIE --data-file=-"
log "  openssl rand -hex 32 | gcloud secrets versions add ADMIN_TOKEN --data-file=-"
```

- [ ] **Step 2: Write `infra/scripts/03-create-buckets.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"

require_cmd gcloud
require_cmd gsutil
ensure_project

if gsutil ls "gs://${RAW_BUCKET}" >/dev/null 2>&1; then
  log "Bucket gs://${RAW_BUCKET} exists, skip."
else
  log "Creating bucket gs://${RAW_BUCKET}"
  gsutil mb -p "${PROJECT_ID}" -c STANDARD -l "${REGION}" -b on "gs://${RAW_BUCKET}"
fi

# Lifecycle: transition to Nearline at 90 days
cat <<EOF >/tmp/lifecycle.json
{
  "lifecycle": {
    "rule": [
      { "action": { "type": "SetStorageClass", "storageClass": "NEARLINE" },
        "condition": { "age": 90, "matchesStorageClass": ["STANDARD"] } }
    ]
  }
}
EOF
gsutil lifecycle set /tmp/lifecycle.json "gs://${RAW_BUCKET}"
rm /tmp/lifecycle.json
log "Done."
```

- [ ] **Step 3: Write `infra/scripts/04-create-firestore.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"

require_cmd gcloud
ensure_project

if gcloud firestore databases describe --database="(default)" >/dev/null 2>&1; then
  log "Default Firestore database exists, skip."
else
  log "Creating Firestore (Native mode) in ${REGION}"
  gcloud firestore databases create --location="${REGION}" --type=firestore-native
fi
log "Done."
```

- [ ] **Step 4: Write `infra/scripts/05-create-artifact-registry.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"

require_cmd gcloud
ensure_project

if gcloud artifacts repositories describe "${AR_REPO}" --location="${REGION}" >/dev/null 2>&1; then
  log "AR repo ${AR_REPO} exists, skip."
else
  log "Creating Artifact Registry repo ${AR_REPO} in ${REGION}"
  gcloud artifacts repositories create "${AR_REPO}" \
    --repository-format=docker \
    --location="${REGION}" \
    --description="auralee-api Docker images"
fi
log "Done."
```

- [ ] **Step 5: Make all executable, commit**

```bash
chmod +x infra/scripts/0[2345]-*.sh
git add infra/scripts/02-create-secrets.sh \
        infra/scripts/03-create-buckets.sh \
        infra/scripts/04-create-firestore.sh \
        infra/scripts/05-create-artifact-registry.sh
git commit -m "infra: scripts 02-05 (secrets, bucket, firestore, AR)"
```

### Task 0.9: Bash script 06 — IAM bindings

**Files:**
- Create: `infra/scripts/06-grant-iam.sh`

- [ ] **Step 1: Write `infra/scripts/06-grant-iam.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"

require_cmd gcloud
ensure_project

bind_project_role() {
  local member="$1"
  local role="$2"
  log "Bind ${role} to ${member}"
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${member}" --role="${role}" --condition=None >/dev/null
}

# Runtime SA
for role in roles/datastore.user \
            roles/secretmanager.secretAccessor \
            roles/aiplatform.user \
            roles/logging.logWriter \
            roles/cloudtrace.agent ; do
  bind_project_role "${RUNTIME_SA}" "${role}"
done
log "Granting storage.objectAdmin on ${RAW_BUCKET} to runtime SA"
gsutil iam ch "serviceAccount:${RUNTIME_SA}:roles/storage.objectAdmin" "gs://${RAW_BUCKET}"

# Cloud Build worker SA
for role in roles/artifactregistry.writer \
            roles/logging.logWriter \
            roles/storage.objectUser ; do
  bind_project_role "${CLOUDBUILD_SA}" "${role}"
done

# Deployer SA
for role in roles/cloudbuild.builds.editor \
            roles/run.developer ; do
  bind_project_role "${DEPLOYER_SA}" "${role}"
done

# Deployer can act-as runtime + cloudbuild SAs
log "Allow deployer to impersonate runtime and cloudbuild SAs"
gcloud iam service-accounts add-iam-policy-binding "${RUNTIME_SA}" \
  --member="serviceAccount:${DEPLOYER_SA}" --role=roles/iam.serviceAccountUser >/dev/null
gcloud iam service-accounts add-iam-policy-binding "${CLOUDBUILD_SA}" \
  --member="serviceAccount:${DEPLOYER_SA}" --role=roles/iam.serviceAccountUser >/dev/null

# Scheduler SA can invoke Cloud Run service (binding added after first deploy in script 08)
log "Done. (Scheduler-to-RunInvoker binding deferred to script 08, after first deploy.)"
```

- [ ] **Step 2: Make executable, commit**

```bash
chmod +x infra/scripts/06-grant-iam.sh
git add infra/scripts/06-grant-iam.sh
git commit -m "infra: script 06 IAM bindings (runtime, cloudbuild, deployer)"
```

### Task 0.10: Bash script 07 — Workload Identity Federation

**Files:**
- Create: `infra/scripts/07-setup-wif.sh`

- [ ] **Step 1: Write `infra/scripts/07-setup-wif.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"

require_cmd gcloud
ensure_project

PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')
POOL_ID="github-pool"
PROVIDER_ID="github-provider"

if gcloud iam workload-identity-pools describe "${POOL_ID}" --location=global >/dev/null 2>&1; then
  log "Pool ${POOL_ID} exists, skip create."
else
  log "Creating WIF pool ${POOL_ID}"
  gcloud iam workload-identity-pools create "${POOL_ID}" \
    --location=global --display-name="GitHub Actions Pool"
fi

if gcloud iam workload-identity-pools providers describe "${PROVIDER_ID}" \
     --workload-identity-pool="${POOL_ID}" --location=global >/dev/null 2>&1; then
  log "Provider ${PROVIDER_ID} exists, skip create."
else
  log "Creating OIDC provider ${PROVIDER_ID} for repo ${GH_REPO}"
  gcloud iam workload-identity-pools providers create-oidc "${PROVIDER_ID}" \
    --workload-identity-pool="${POOL_ID}" --location=global \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
    --attribute-condition="attribute.repository == '${GH_REPO}'"
fi

log "Allowing repo ${GH_REPO} to impersonate ${DEPLOYER_SA}"
gcloud iam service-accounts add-iam-policy-binding "${DEPLOYER_SA}" \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/attribute.repository/${GH_REPO}" >/dev/null

cat <<EOF

============================================================
WIF setup complete.

ADD THIS TO GitHub repo Settings → Secrets and variables → Actions:

  Name:  GCP_PROJECT_NUMBER
  Value: ${PROJECT_NUMBER}

============================================================
EOF
```

- [ ] **Step 2: Make executable, commit**

```bash
chmod +x infra/scripts/07-setup-wif.sh
git add infra/scripts/07-setup-wif.sh
git commit -m "infra: script 07 Workload Identity Federation for GitHub Actions"
```

### Task 0.11: GitHub Actions workflow

**Files:**
- Create: `.github/workflows/deploy.yml`

- [ ] **Step 1: Create directory**

```bash
mkdir -p .github/workflows
```

- [ ] **Step 2: Write `.github/workflows/deploy.yml`**

```yaml
name: Deploy auralee-api
on:
  push:
    branches: [main]
    paths:
      - 'services/api/**'
      - '.github/workflows/deploy.yml'
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

      - id: auth
        uses: google-github-actions/auth@v2
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
            --region "$REGION" \
            --no-allow-unauthenticated \
            --service-account "auralee-runtime@${PROJECT_ID}.iam.gserviceaccount.com" \
            --memory 1Gi --cpu 1 \
            --min-instances 0 --max-instances 3 \
            --concurrency 10 --timeout 600 --execution-environment gen2 \
            --set-env-vars "GCP_PROJECT=${PROJECT_ID},GCP_REGION=${REGION},LOG_LEVEL=INFO,PROMPT_VERSION=v1" \
            --set-secrets "WSJ_COOKIE=WSJ_COOKIE:latest,ADMIN_TOKEN=ADMIN_TOKEN:latest"
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/deploy.yml
git commit -m "ci: GitHub Actions deploy workflow with WIF + Cloud Build"
```

### Task 0.12: First end-to-end deploy

This is a manual sequence run by the human operator. The plan documents the exact commands and expected outcomes.

**Prerequisites:** GCP project `auralee-api-server` exists in console with billing enabled. `gcloud auth login` already done locally. macOS with `gcloud`, `gsutil`, `docker`, `uv` installed.

- [ ] **Step 1: Set active project locally**

```bash
gcloud config set project auralee-api-server
```

- [ ] **Step 2: Run setup scripts in order (00 → 07)**

```bash
cd /Users/farron/code/Auralee
./infra/scripts/00-bootstrap.sh
./infra/scripts/01-create-service-accounts.sh
./infra/scripts/02-create-secrets.sh
./infra/scripts/03-create-buckets.sh
./infra/scripts/04-create-firestore.sh
./infra/scripts/05-create-artifact-registry.sh
./infra/scripts/06-grant-iam.sh
./infra/scripts/07-setup-wif.sh
```

Expected: each script completes with "Done." Script 07 prints `GCP_PROJECT_NUMBER`.

- [ ] **Step 3: Add `GCP_PROJECT_NUMBER` to GitHub repo secrets**

Open https://github.com/enclairfarron/Auralee/settings/secrets/actions, click "New repository secret", name `GCP_PROJECT_NUMBER`, value from script 07 output.

- [ ] **Step 4: Populate Secret Manager values**

```bash
# WSJ cookie: open Safari → wsj.com → DevTools Network → copy Cookie header → paste
pbpaste | gcloud secrets versions add WSJ_COOKIE --data-file=-

# Admin token
openssl rand -hex 32 | gcloud secrets versions add ADMIN_TOKEN --data-file=-
gcloud secrets versions access latest --secret=ADMIN_TOKEN  # save this for curl tests
```

- [ ] **Step 5: Push to trigger deploy**

```bash
git push origin main
```

Expected: GitHub Actions runs, ~3-5 min later Cloud Run service `auralee-api` exists in us-east1.

- [ ] **Step 6: Verify deploy by hitting `/healthz`**

```bash
SERVICE_URL=$(gcloud run services describe auralee-api --region=us-east1 --format='value(status.url)')
TOKEN=$(gcloud auth print-identity-token)
curl -s -H "Authorization: Bearer ${TOKEN}" "${SERVICE_URL}/healthz"
```

Expected: `{"status":"ok"}`.

- [ ] **Step 7: Tag the commit as "phase 0 done"**

```bash
git tag -a phase-0-deploy -m "First successful Cloud Run deploy"
git push origin phase-0-deploy
```

**Phase 0 done.** Service is live, CI/CD wired, GCP infra in place. All future work is push-to-deploy.

---

## Phase 1 — Pure Models, Utilities, Config

Goal: lay down all the Pydantic models, pure-function utilities, settings, and auth before touching IO. TDD discipline strict in this phase.

### Task 1.1: Pydantic models — `article.py`

**Files:**
- Create: `services/api/app/models/__init__.py`
- Create: `services/api/app/models/article.py`
- Create: `services/api/tests/test_models.py`

- [ ] **Step 1: Create `services/api/app/models/__init__.py` (empty)**

```bash
touch services/api/app/models/__init__.py
```

- [ ] **Step 2: Write failing model test**

`services/api/tests/test_models.py`:

```python
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.models.article import (
    Article,
    Entity,
    EvalScore,
    Extraction,
    GeminiMeta,
    SanityCheck,
    Sentiment,
)


def test_sentiment_score_must_be_in_range() -> None:
    Sentiment(score=0.5, label="bullish")
    with pytest.raises(ValidationError):
        Sentiment(score=1.5, label="bullish")
    with pytest.raises(ValidationError):
        Sentiment(score=-2.0, label="bearish")


def test_extraction_minimal() -> None:
    e = Extraction(
        title="t",
        summary="s",
        sentiment=Sentiment(score=0.0, label="neutral"),
        core_thesis="c",
        language="en",
    )
    assert e.tickers == []
    assert e.entities == []
    assert e.categories == []


def test_entity_with_optional_ticker() -> None:
    Entity(type="company", name="Apple Inc.", ticker="AAPL")
    Entity(type="person", name="Tim Cook")  # no ticker


def test_article_full_doc() -> None:
    a = Article(
        id="wsj_20260424_a3f1b9d2",
        source="wsj",
        source_id="WP-123",
        url="https://example.com/a",
        title="t",
        published_at=datetime(2026, 4, 24, tzinfo=UTC),
        fetched_at=datetime(2026, 4, 24, tzinfo=UTC),
        processed_at=datetime(2026, 4, 24, tzinfo=UTC),
        language="en",
        raw_html_gcs_uri="gs://bucket/x.html",
        clean_text_chars=100,
        summary="s",
        tickers=["AAPL"],
        sentiment=Sentiment(score=0.5, label="bullish"),
        core_thesis="c",
        gemini_meta=GeminiMeta(
            model="gemini-2.5-flash",
            tokens_in=100, tokens_out=50,
            cost_usd=0.0001, latency_ms=200,
            prompt_version="v1",
        ),
    )
    assert a.embedding is None  # Week 2 reserved
    assert a.sanity_check is None  # set later in pipeline
    assert a.eval_score is None


def test_sanity_check_default_pass_empty_flags() -> None:
    s = SanityCheck(ticker_precision_pass=True, checked_at=datetime.now(UTC))
    assert s.flags == []


def test_eval_score_with_issues() -> None:
    e = EvalScore(
        score=8.5,
        judge_model="gemini-2.5-pro",
        judged_at=datetime.now(UTC),
        issues=["missing_ticker:TSLA"],
        reasoning="...",
    )
    assert 0 <= e.score <= 10
```

- [ ] **Step 3: Run, expect ImportError**

```bash
cd services/api && uv run pytest tests/test_models.py -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 4: Implement `services/api/app/models/article.py`**

```python
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Source = Literal["hn", "reuters", "wsj"]
SentimentLabel = Literal["bullish", "bearish", "neutral"]
EntityType = Literal["company", "person", "location", "product"]


class Sentiment(BaseModel):
    score: float = Field(ge=-1.0, le=1.0)
    label: SentimentLabel


class Entity(BaseModel):
    type: EntityType
    name: str
    ticker: str | None = None


class GeminiMeta(BaseModel):
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int
    prompt_version: str


class SanityCheck(BaseModel):
    ticker_precision_pass: bool
    checked_at: datetime
    flags: list[str] = Field(default_factory=list)


class EvalScore(BaseModel):
    score: float = Field(ge=0.0, le=10.0)
    judge_model: str
    judged_at: datetime
    issues: list[str] = Field(default_factory=list)
    reasoning: str


class Extraction(BaseModel):
    """Schema fed to Gemini as response_schema."""

    model_config = ConfigDict(extra="forbid")

    title: str
    summary: str = Field(description="2-3 sentences in the SAME language as the article")
    tickers: list[str] = Field(
        default_factory=list,
        description="US-listed tickers, uppercase, e.g. ['AAPL']",
    )
    sentiment: Sentiment
    core_thesis: str = Field(description="Article's central argument, 1 sentence")
    categories: list[str] = Field(default_factory=list)
    entities: list[Entity] = Field(default_factory=list)
    language: str = Field(description="ISO 639-1 code")


class Article(BaseModel):
    """Firestore document for `articles/{id}`."""

    id: str
    source: Source
    source_id: str
    url: str
    title: str
    author: str | None = None
    published_at: datetime
    fetched_at: datetime
    processed_at: datetime
    language: str

    raw_html_gcs_uri: str | None = None
    clean_text_chars: int = 0

    summary: str
    tickers: list[str] = Field(default_factory=list)
    sentiment: Sentiment
    core_thesis: str
    categories: list[str] = Field(default_factory=list)
    entities: list[Entity] = Field(default_factory=list)

    gemini_meta: GeminiMeta

    sanity_check: SanityCheck | None = None
    eval_score: EvalScore | None = None

    # Week 2 reservations
    embedding: list[float] | None = None
    embedding_model: str | None = None
    embedded_at: datetime | None = None
```

- [ ] **Step 5: Run test, expect PASS**

```bash
cd services/api && uv run pytest tests/test_models.py -v
```

Expected: 6 tests pass.

- [ ] **Step 6: Lint, type, commit**

```bash
cd services/api && uv run ruff format . && uv run ruff check . --fix && uv run mypy app
cd /Users/farron/code/Auralee
git add services/api/app/models/ services/api/tests/test_models.py
git commit -m "feat(api): article models (Article, Extraction, Sentiment, etc.)"
```

### Task 1.2: Pydantic models — `price.py`, `run.py`, `ingest.py`, `candidate.py`

**Files:**
- Create: `services/api/app/models/price.py`
- Create: `services/api/app/models/run.py`
- Create: `services/api/app/models/ingest.py`
- Create: `services/api/app/models/candidate.py`

- [ ] **Step 1: Append tests for new models to `tests/test_models.py`**

```python
# Append at end of file:

from app.models.candidate import Candidate
from app.models.ingest import IngestPayload, IngestResponse, IngestStatus, RawHtml, RawText
from app.models.price import DailyOHLC, Price
from app.models.run import Run, RunError, RunKind, RunStatus


def test_price_and_daily_ohlc() -> None:
    Price(
        ticker="AAPL", name="Apple Inc.", exchange="NASDAQ", currency="USD",
        first_seen_at=datetime.now(UTC), last_refreshed_at=datetime.now(UTC),
        is_active=True,
    )
    DailyOHLC(
        date="2026-04-24", open=1.0, high=2.0, low=0.5, close=1.5,
        volume=100, adj_close=1.5,
        fetched_at=datetime.now(UTC), source="yfinance",
    )


def test_run_with_errors() -> None:
    r = Run(
        id="abc", kind="scrape", source="wsj",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        status="partial",
        articles_attempted=10, articles_ingested=8, articles_skipped_dup=1,
        errors=[RunError(url="u", stage="fetch", message="403")],
        cost_usd=0.01,
    )
    assert r.kind == "scrape"
    assert len(r.errors) == 1


def test_ingest_payload_html_variant() -> None:
    p = IngestPayload(
        source="wsj", source_id="x", url="https://x", fetched_at=datetime.now(UTC),
        raw=RawHtml(kind="html", html="<html></html>", encoding="utf-8"),
    )
    assert p.raw.kind == "html"


def test_ingest_payload_text_variant() -> None:
    p = IngestPayload(
        source="hn", source_id="x", url="https://x", fetched_at=datetime.now(UTC),
        raw=RawText(kind="text", title="t", body="b", metadata={}),
    )
    assert p.raw.kind == "text"


def test_candidate_minimal() -> None:
    c = Candidate(source_id="x", url="https://x")
    assert c.title is None
    assert c.published_at is None
```

- [ ] **Step 2: Run, expect ImportError**

```bash
cd services/api && uv run pytest tests/test_models.py -v
```

Expected: FAIL on new imports.

- [ ] **Step 3: Implement `services/api/app/models/price.py`**

```python
from datetime import datetime

from pydantic import BaseModel


class Price(BaseModel):
    ticker: str
    name: str | None = None
    exchange: str | None = None
    currency: str = "USD"
    first_seen_at: datetime
    last_refreshed_at: datetime | None = None
    is_active: bool = True


class DailyOHLC(BaseModel):
    date: str  # YYYY-MM-DD
    open: float
    high: float
    low: float
    close: float
    volume: int
    adj_close: float
    fetched_at: datetime
    source: str = "yfinance"
```

- [ ] **Step 4: Implement `services/api/app/models/run.py`**

```python
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

RunKind = Literal["scrape", "refresh-prices", "aggregate-metrics", "eval-judge"]
RunStatus = Literal["success", "partial", "failure", "noop"]


class RunError(BaseModel):
    url: str | None = None
    ticker: str | None = None
    stage: str
    message: str


class Run(BaseModel):
    id: str
    kind: RunKind
    source: str | None = None  # for scrape only
    started_at: datetime
    finished_at: datetime | None = None
    status: RunStatus = "success"
    articles_attempted: int = 0
    articles_ingested: int = 0
    articles_skipped_dup: int = 0
    refreshed: int = 0
    errors: list[RunError] = Field(default_factory=list)
    cost_usd: float = 0.0
```

- [ ] **Step 5: Implement `services/api/app/models/ingest.py`**

```python
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from app.models.article import Extraction, Source

IngestStatus = Literal["ingested", "duplicate", "skipped_short"]


class RawHtml(BaseModel):
    kind: Literal["html"] = "html"
    html: str
    encoding: str = "utf-8"


class RawText(BaseModel):
    kind: Literal["text"] = "text"
    title: str
    body: str
    metadata: dict[str, Any] = Field(default_factory=dict)


Raw = Annotated[RawHtml | RawText, Field(discriminator="kind")]


class IngestPayload(BaseModel):
    source: Source
    source_id: str
    url: str
    fetched_at: datetime
    raw: Raw


class IngestMeta(BaseModel):
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int
    prompt_version: str
    raw_html_gcs_uri: str | None = None


class IngestResponse(BaseModel):
    article_id: str
    status: IngestStatus
    extracted: Extraction | None = None  # null when status=duplicate or skipped_short
    meta: IngestMeta | None = None
```

- [ ] **Step 6: Implement `services/api/app/models/candidate.py`**

```python
from datetime import datetime

from pydantic import BaseModel


class Candidate(BaseModel):
    source_id: str
    url: str
    title: str | None = None
    published_at: datetime | None = None
```

- [ ] **Step 7: Run test, expect PASS**

```bash
cd services/api && uv run pytest tests/test_models.py -v
```

Expected: all tests pass (11 total).

- [ ] **Step 8: Lint, type, commit**

```bash
cd services/api && uv run ruff format . && uv run ruff check . --fix && uv run mypy app
cd /Users/farron/code/Auralee
git add services/api/app/models/ services/api/tests/test_models.py
git commit -m "feat(api): price, run, ingest, candidate models"
```

### Task 1.3: `article_id` pure function

**Files:**
- Create: `services/api/app/services/__init__.py`
- Create: `services/api/app/services/article_id.py`
- Create: `services/api/tests/test_article_id.py`

- [ ] **Step 1: Create `services/api/app/services/__init__.py` (empty)**

```bash
touch services/api/app/services/__init__.py
```

- [ ] **Step 2: Write failing test**

`services/api/tests/test_article_id.py`:

```python
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
```

- [ ] **Step 3: Run, expect ImportError**

```bash
cd services/api && uv run pytest tests/test_article_id.py -v
```

Expected: FAIL.

- [ ] **Step 4: Implement `services/api/app/services/article_id.py`**

```python
import hashlib
from datetime import UTC, datetime
from urllib.parse import urlparse, urlunparse

from app.models.article import Source


def _normalize_url(url: str) -> str:
    p = urlparse(url)
    path = p.path.rstrip("/") or "/"
    return urlunparse((p.scheme, p.netloc, path, "", p.query, ""))


def compute_article_id(source: Source, published_at: datetime, url: str) -> str:
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=UTC)
    date_str = published_at.astimezone(UTC).strftime("%Y%m%d")
    h = hashlib.md5(_normalize_url(url).encode("utf-8")).hexdigest()[:8]
    return f"{source}_{date_str}_{h}"
```

- [ ] **Step 5: Run test, expect PASS**

```bash
cd services/api && uv run pytest tests/test_article_id.py -v
```

Expected: 5 tests pass.

- [ ] **Step 6: Lint, type, commit**

```bash
cd services/api && uv run ruff format . && uv run ruff check . --fix && uv run mypy app
cd /Users/farron/code/Auralee
git add services/api/app/services/article_id.py services/api/tests/test_article_id.py services/api/app/services/__init__.py
git commit -m "feat(api): compute_article_id pure function"
```

### Task 1.4: M2 sanity check (regex precision)

**Files:**
- Create: `services/api/app/services/sanity.py`
- Create: `services/api/tests/test_sanity.py`
- Create: `services/api/app/data/__init__.py`
- Create: `services/api/app/data/tickers.json`

- [ ] **Step 1: Create minimal ticker dictionary**

`services/api/app/data/tickers.json`:

```json
{
  "AAPL": ["Apple", "Apple Inc.", "Apple Inc"],
  "MSFT": ["Microsoft", "Microsoft Corp.", "Microsoft Corp", "Microsoft Corporation"],
  "GOOGL": ["Alphabet", "Alphabet Inc.", "Google", "Google LLC"],
  "GOOG": ["Alphabet", "Alphabet Inc.", "Google", "Google LLC"],
  "AMZN": ["Amazon", "Amazon.com", "Amazon.com Inc.", "Amazon.com, Inc."],
  "META": ["Meta", "Meta Platforms", "Meta Platforms Inc.", "Facebook"],
  "TSLA": ["Tesla", "Tesla Inc.", "Tesla Inc"],
  "NVDA": ["Nvidia", "NVIDIA", "Nvidia Corp.", "NVIDIA Corporation"],
  "JPM": ["JPMorgan", "JP Morgan", "JPMorgan Chase", "JPMorgan Chase & Co."],
  "BAC": ["Bank of America", "BofA"],
  "GS": ["Goldman Sachs", "Goldman Sachs Group"],
  "WMT": ["Walmart", "Wal-Mart", "Walmart Inc."],
  "BRK.B": ["Berkshire Hathaway", "Berkshire"],
  "V": ["Visa", "Visa Inc."],
  "MA": ["Mastercard", "Mastercard Inc."],
  "DIS": ["Disney", "Walt Disney", "The Walt Disney Company"],
  "NFLX": ["Netflix", "Netflix Inc."],
  "ORCL": ["Oracle", "Oracle Corp.", "Oracle Corporation"],
  "INTC": ["Intel", "Intel Corp.", "Intel Corporation"],
  "AMD": ["AMD", "Advanced Micro Devices"],
  "CRM": ["Salesforce", "Salesforce.com"],
  "ADBE": ["Adobe", "Adobe Inc."],
  "PYPL": ["PayPal", "PayPal Holdings"],
  "UBER": ["Uber", "Uber Technologies"],
  "ABNB": ["Airbnb", "Airbnb Inc."],
  "SNOW": ["Snowflake", "Snowflake Inc."],
  "PLTR": ["Palantir", "Palantir Technologies"],
  "COIN": ["Coinbase", "Coinbase Global"],
  "HOOD": ["Robinhood", "Robinhood Markets"],
  "SHOP": ["Shopify", "Shopify Inc."]
}
```

(This is a starter; production version pulled from SEC EDGAR. ~30 entries cover most-traded names; sufficient for PoC.)

- [ ] **Step 2: Write failing tests**

`services/api/tests/test_sanity.py`:

```python
from app.services.sanity import check_ticker_precision


def test_passes_when_ticker_symbol_in_text() -> None:
    result = check_ticker_precision(
        tickers=["AAPL"],
        clean_text="Today AAPL reported earnings.",
    )
    assert result.ticker_precision_pass is True
    assert result.flags == []


def test_passes_when_company_name_in_text() -> None:
    result = check_ticker_precision(
        tickers=["AAPL"],
        clean_text="Today Apple Inc. reported earnings.",
    )
    assert result.ticker_precision_pass is True


def test_fails_with_hallucinated_ticker_flag() -> None:
    result = check_ticker_precision(
        tickers=["AAPL", "ZZZZ"],
        clean_text="Today AAPL reported earnings.",
    )
    assert result.ticker_precision_pass is False
    assert any("ZZZZ" in f for f in result.flags)


def test_empty_tickers_passes() -> None:
    result = check_ticker_precision(tickers=[], clean_text="some text")
    assert result.ticker_precision_pass is True


def test_case_insensitive_company_match() -> None:
    result = check_ticker_precision(tickers=["MSFT"], clean_text="microsoft beat...")
    assert result.ticker_precision_pass is True


def test_unknown_ticker_only_symbol_check() -> None:
    # Ticker not in dictionary → only check the symbol literal
    result = check_ticker_precision(tickers=["XYZQ"], clean_text="XYZQ surged today")
    assert result.ticker_precision_pass is True
```

- [ ] **Step 3: Run, expect FAIL**

```bash
cd services/api && uv run pytest tests/test_sanity.py -v
```

- [ ] **Step 4: Create `services/api/app/data/__init__.py` (empty)**

```bash
touch services/api/app/data/__init__.py
```

- [ ] **Step 5: Implement `services/api/app/services/sanity.py`**

```python
import json
from datetime import UTC, datetime
from functools import lru_cache
from importlib.resources import files

from app.models.article import SanityCheck


@lru_cache(maxsize=1)
def _ticker_dictionary() -> dict[str, list[str]]:
    raw = files("app.data").joinpath("tickers.json").read_text()
    return json.loads(raw)


def _ticker_found_in_text(ticker: str, clean_text: str) -> bool:
    text_lower = clean_text.lower()
    if ticker.upper() in clean_text:
        return True
    aliases = _ticker_dictionary().get(ticker.upper(), [])
    return any(alias.lower() in text_lower for alias in aliases)


def check_ticker_precision(tickers: list[str], clean_text: str) -> SanityCheck:
    flags: list[str] = []
    for t in tickers:
        if not _ticker_found_in_text(t, clean_text):
            flags.append(f"hallucinated_ticker:{t}")
    return SanityCheck(
        ticker_precision_pass=len(flags) == 0,
        checked_at=datetime.now(UTC),
        flags=flags,
    )
```

- [ ] **Step 6: Run test, expect PASS**

```bash
cd services/api && uv run pytest tests/test_sanity.py -v
```

Expected: 6 tests pass.

- [ ] **Step 7: Lint, type, commit**

```bash
cd services/api && uv run ruff format . && uv run ruff check . --fix && uv run mypy app
cd /Users/farron/code/Auralee
git add services/api/app/services/sanity.py services/api/app/data/ services/api/tests/test_sanity.py
git commit -m "feat(api): M2 ticker precision sanity check"
```

### Task 1.5: Settings (`config.py`)

**Files:**
- Create: `services/api/app/config.py`

- [ ] **Step 1: Implement `services/api/app/config.py`**

```python
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # GCP
    gcp_project: str = Field(default="auralee-api-server", alias="GCP_PROJECT")
    gcp_region: str = Field(default="us-east1", alias="GCP_REGION")
    raw_bucket: str = Field(default="auralee-api-server-raw", alias="RAW_BUCKET")

    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # Secrets (mounted as env by Cloud Run via --set-secrets)
    wsj_cookie: str = Field(default="", alias="WSJ_COOKIE")
    admin_token: str = Field(default="", alias="ADMIN_TOKEN")

    # Prompt versioning
    prompt_version: str = Field(default="v1", alias="PROMPT_VERSION")

    # Models
    extraction_model: str = "gemini-2.5-flash"
    judge_model: str = "gemini-2.5-pro"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 2: Smoke test by importing**

```bash
cd services/api && uv run python -c "from app.config import get_settings; print(get_settings().gcp_project)"
```

Expected: `auralee-api-server`.

- [ ] **Step 3: Lint, type, commit**

```bash
cd services/api && uv run ruff format . && uv run ruff check . --fix && uv run mypy app
cd /Users/farron/code/Auralee
git add services/api/app/config.py
git commit -m "feat(api): Settings via pydantic-settings"
```

### Task 1.6: Auth dependency (`X-Admin-Token`)

**Files:**
- Create: `services/api/app/deps.py`
- Create: `services/api/tests/test_routers/test_admin_router.py` (placeholder test for auth)

- [ ] **Step 1: Write failing auth test**

`services/api/tests/test_routers/test_admin_router.py`:

```python
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _set_admin_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "secret-test-token")
    from app.config import get_settings
    get_settings.cache_clear()


def test_protected_endpoint_rejects_missing_token(test_client: TestClient) -> None:
    # /admin/articles is added in Phase 6 — for now create a test echo route.
    response = test_client.get("/_test/admin-echo")
    assert response.status_code == 401


def test_protected_endpoint_rejects_wrong_token(test_client: TestClient) -> None:
    response = test_client.get("/_test/admin-echo", headers={"X-Admin-Token": "wrong"})
    assert response.status_code == 401


def test_protected_endpoint_accepts_correct_token(test_client: TestClient) -> None:
    response = test_client.get("/_test/admin-echo", headers={"X-Admin-Token": "secret-test-token"})
    assert response.status_code == 200
    assert response.json() == {"ok": True}
```

- [ ] **Step 2: Run, expect FAIL**

```bash
cd services/api && uv run pytest tests/test_routers/test_admin_router.py -v
```

- [ ] **Step 3: Implement `services/api/app/deps.py`**

```python
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from app.config import Settings, get_settings


def require_admin_token(
    x_admin_token: Annotated[str | None, Header()] = None,
    settings: Annotated[Settings, Depends(get_settings)] = ...,  # type: ignore[assignment]
) -> None:
    if not settings.admin_token:
        raise HTTPException(status_code=503, detail="ADMIN_TOKEN not configured")
    if not x_admin_token or x_admin_token != settings.admin_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")
```

- [ ] **Step 4: Add a test-only echo route to `services/api/app/main.py`**

Modify `create_app` to add a test-only protected route. The simplest thing is to add a tiny test-routes-only router that always exists (size penalty is negligible).

Edit `services/api/app/main.py`:

```python
from fastapi import Depends, FastAPI

from app.deps import require_admin_token
from app.routers import health


def create_app() -> FastAPI:
    app = FastAPI(title="auralee-api", version="0.1.0")
    app.include_router(health.router)

    @app.get("/_test/admin-echo", dependencies=[Depends(require_admin_token)])
    async def _admin_echo() -> dict[str, bool]:
        return {"ok": True}

    return app


app = create_app()
```

(`/_test/*` namespace makes the throwaway nature explicit; will be removed once a real admin endpoint exercises the dep.)

- [ ] **Step 5: Run tests, expect PASS**

```bash
cd services/api && uv run pytest tests/test_routers/test_admin_router.py -v
```

Expected: 3 pass.

- [ ] **Step 6: Lint, type, commit**

```bash
cd services/api && uv run ruff format . && uv run ruff check . --fix && uv run mypy app
cd /Users/farron/code/Auralee
git add services/api/app/deps.py services/api/app/main.py services/api/tests/test_routers/test_admin_router.py
git commit -m "feat(api): X-Admin-Token auth dependency + test echo route"
```

### Task 1.7: Logging setup (Cloud Logging structured)

**Files:**
- Create: `services/api/app/logging_setup.py`

- [ ] **Step 1: Implement `services/api/app/logging_setup.py`**

```python
import logging
import sys

from app.config import get_settings


def configure_logging() -> None:
    """Cloud Logging picks up stdout JSON; for local dev use plain text."""
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # Quiet libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
```

- [ ] **Step 2: Wire into `app/main.py`**

Edit `services/api/app/main.py` (top of file, after imports):

```python
from app.logging_setup import configure_logging

# At top of create_app():
def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="auralee-api", version="0.1.0")
    # ... rest unchanged
```

- [ ] **Step 3: Smoke test by booting locally and watching logs**

```bash
cd services/api && uv run uvicorn app.main:app --port 8080 &
sleep 2
curl -s http://localhost:8080/healthz
kill %1
```

Expected: log lines printed in `YYYY-MM-DD HH:MM:SS LEVEL name message` format, including the GET /healthz access log.

- [ ] **Step 4: Lint, type, commit**

```bash
cd services/api && uv run ruff format . && uv run ruff check . --fix && uv run mypy app
cd /Users/farron/code/Auralee
git add services/api/app/logging_setup.py services/api/app/main.py
git commit -m "feat(api): structured logging setup"
```

**Phase 1 done.** Models, pure utilities, config, auth, logging are in place. All tests pass. Ready to wrap GCP services next.

---

## Phase 2 — GCP Wrappers

Goal: thin, testable wrappers over Secret Manager, GCS, and Firestore. Each wrapper hides the raw client and exposes only the methods the rest of the app needs.

### Task 2.1: Secret Manager wrapper

**Files:**
- Create: `services/api/app/services/secrets.py`
- Create: `services/api/tests/test_secrets.py`

- [ ] **Step 1: Write failing test (smoke, with mock)**

`services/api/tests/test_secrets.py`:

```python
from unittest.mock import MagicMock

import pytest

from app.services.secrets import SecretClient


def test_get_uses_latest_alias_and_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_response = MagicMock()
    mock_response.payload.data = b"super-secret-value"
    mock_client = MagicMock()
    mock_client.access_secret_version.return_value = mock_response

    sc = SecretClient(project_id="proj", _client=mock_client)
    assert sc.get("WSJ_COOKIE") == "super-secret-value"
    assert sc.get("WSJ_COOKIE") == "super-secret-value"  # cached, no re-call

    mock_client.access_secret_version.assert_called_once()
    args, _ = mock_client.access_secret_version.call_args
    assert args[0]["name"] == "projects/proj/secrets/WSJ_COOKIE/versions/latest"


def test_invalidate_forces_refresh() -> None:
    mock_response = MagicMock()
    mock_response.payload.data = b"v1"
    mock_client = MagicMock()
    mock_client.access_secret_version.return_value = mock_response

    sc = SecretClient(project_id="proj", _client=mock_client)
    sc.get("X")
    sc.invalidate("X")
    sc.get("X")
    assert mock_client.access_secret_version.call_count == 2
```

- [ ] **Step 2: Run, expect FAIL**

```bash
cd services/api && uv run pytest tests/test_secrets.py -v
```

- [ ] **Step 3: Implement `services/api/app/services/secrets.py`**

```python
from typing import Any

from google.cloud import secretmanager


class SecretClient:
    def __init__(self, project_id: str, _client: Any | None = None) -> None:
        self._project_id = project_id
        self._client = _client or secretmanager.SecretManagerServiceClient()
        self._cache: dict[str, str] = {}

    def get(self, name: str) -> str:
        if name not in self._cache:
            full_name = f"projects/{self._project_id}/secrets/{name}/versions/latest"
            response = self._client.access_secret_version({"name": full_name})
            self._cache[name] = response.payload.data.decode("utf-8")
        return self._cache[name]

    def invalidate(self, name: str) -> None:
        self._cache.pop(name, None)
```

- [ ] **Step 4: Run test, expect PASS**

```bash
cd services/api && uv run pytest tests/test_secrets.py -v
```

- [ ] **Step 5: Lint, type, commit**

```bash
cd services/api && uv run ruff format . && uv run ruff check . --fix && uv run mypy app
cd /Users/farron/code/Auralee
git add services/api/app/services/secrets.py services/api/tests/test_secrets.py
git commit -m "feat(api): Secret Manager wrapper with in-process cache"
```

### Task 2.2: GCS wrapper (raw HTML archival)

**Files:**
- Create: `services/api/app/services/gcs.py`
- Create: `services/api/tests/test_gcs.py`

- [ ] **Step 1: Write failing test (smoke, with mock)**

`services/api/tests/test_gcs.py`:

```python
from datetime import UTC, datetime
from unittest.mock import MagicMock

from app.services.gcs import RawHtmlArchiver


def test_archive_writes_to_correct_path() -> None:
    mock_blob = MagicMock()
    mock_bucket = MagicMock()
    mock_bucket.blob.return_value = mock_blob
    mock_client = MagicMock()
    mock_client.bucket.return_value = mock_bucket

    archiver = RawHtmlArchiver(bucket_name="auralee-api-server-raw", _client=mock_client)
    uri = archiver.upload(
        article_id="wsj_20260424_a3f1b9d2",
        source="wsj",
        published_at=datetime(2026, 4, 24, 13, 30, tzinfo=UTC),
        html="<html></html>",
    )

    mock_client.bucket.assert_called_once_with("auralee-api-server-raw")
    mock_bucket.blob.assert_called_once_with(
        "wsj/2026-04-24/wsj_20260424_a3f1b9d2.html"
    )
    mock_blob.upload_from_string.assert_called_once()
    args, kwargs = mock_blob.upload_from_string.call_args
    assert args[0] == "<html></html>"
    assert kwargs.get("content_type") == "text/html; charset=utf-8"
    assert uri == "gs://auralee-api-server-raw/wsj/2026-04-24/wsj_20260424_a3f1b9d2.html"
```

- [ ] **Step 2: Run, expect FAIL**

```bash
cd services/api && uv run pytest tests/test_gcs.py -v
```

- [ ] **Step 3: Implement `services/api/app/services/gcs.py`**

```python
import logging
from datetime import UTC, datetime
from typing import Any

from google.cloud import storage

from app.models.article import Source

logger = logging.getLogger(__name__)


class RawHtmlArchiver:
    def __init__(self, bucket_name: str, _client: Any | None = None) -> None:
        self._bucket_name = bucket_name
        self._client = _client or storage.Client()

    def upload(
        self,
        article_id: str,
        source: Source,
        published_at: datetime,
        html: str,
    ) -> str:
        date_str = published_at.astimezone(UTC).strftime("%Y-%m-%d")
        path = f"{source}/{date_str}/{article_id}.html"
        blob = self._client.bucket(self._bucket_name).blob(path)
        blob.upload_from_string(html, content_type="text/html; charset=utf-8")
        uri = f"gs://{self._bucket_name}/{path}"
        logger.info("archived raw HTML", extra={"uri": uri, "article_id": article_id})
        return uri

    def upload_safe(
        self,
        article_id: str,
        source: Source,
        published_at: datetime,
        html: str,
    ) -> str | None:
        """Fire-and-forget variant: log and swallow exceptions."""
        try:
            return self.upload(article_id, source, published_at, html)
        except Exception:  # noqa: BLE001
            logger.exception("failed to archive raw HTML", extra={"article_id": article_id})
            return None
```

- [ ] **Step 4: Run test, expect PASS**

```bash
cd services/api && uv run pytest tests/test_gcs.py -v
```

- [ ] **Step 5: Lint, type, commit**

```bash
cd services/api && uv run ruff format . && uv run ruff check . --fix && uv run mypy app
cd /Users/farron/code/Auralee
git add services/api/app/services/gcs.py services/api/tests/test_gcs.py
git commit -m "feat(api): GCS raw HTML archiver"
```

### Task 2.3: Firestore repository

**Files:**
- Create: `services/api/app/services/firestore_repo.py`
- Create: `services/api/tests/test_firestore_repo.py`

This wrapper exposes only the high-level operations the app needs. We use it as a seam — tests inject a fake; production uses the real `firestore.Client`.

- [ ] **Step 1: Write failing tests (with in-memory fake)**

`services/api/tests/test_firestore_repo.py`:

```python
from datetime import UTC, datetime

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
        id=article_id, source="wsj", source_id="x", url="https://x",
        title="t", published_at=now, fetched_at=now, processed_at=now,
        language="en", summary="s", tickers=["AAPL"],
        sentiment=Sentiment(score=0.5, label="bullish"),
        core_thesis="c",
        gemini_meta=GeminiMeta(
            model="gemini-2.5-flash", tokens_in=10, tokens_out=5,
            cost_usd=0.0001, latency_ms=100, prompt_version="v1",
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
```

- [ ] **Step 2: Run, expect FAIL**

```bash
cd services/api && uv run pytest tests/test_firestore_repo.py -v
```

- [ ] **Step 3: Implement `services/api/app/services/firestore_repo.py`**

```python
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from google.cloud import firestore

from app.models.article import Article
from app.models.price import DailyOHLC, Price
from app.models.run import Run

logger = logging.getLogger(__name__)


class FirestoreRepo:
    def __init__(self, _client: Any | None = None) -> None:
        self._client = _client or firestore.Client()

    # ── articles ────────────────────────────────────────
    def article_exists(self, article_id: str) -> bool:
        doc = self._client.collection("articles").document(article_id).get()
        return bool(doc.exists)

    def save_article(self, article: Article) -> None:
        data = article.model_dump(mode="json")
        self._client.collection("articles").document(article.id).set(data)

    def get_article(self, article_id: str) -> Article | None:
        doc = self._client.collection("articles").document(article_id).get()
        if not doc.exists:
            return None
        return Article.model_validate(doc.to_dict())

    # ── prices ──────────────────────────────────────────
    def upsert_ticker_stub(self, ticker: str) -> None:
        doc = self._client.collection("prices").document(ticker).get()
        if doc.exists:
            self._client.collection("prices").document(ticker).update(
                {"is_active": True}
            )
        else:
            now = datetime.now(UTC)
            self._client.collection("prices").document(ticker).set(
                Price(
                    ticker=ticker, first_seen_at=now, last_refreshed_at=None,
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

    # ── runs ────────────────────────────────────────────
    def save_run(self, run: Run) -> str:
        if not run.id:
            run.id = str(uuid.uuid4())
        self._client.collection("runs").document(run.id).set(run.model_dump(mode="json"))
        return run.id

    # ── metrics ─────────────────────────────────────────
    def save_metrics(self, date_yyyymmdd: str, payload: dict[str, Any]) -> None:
        self._client.collection("metrics").document(date_yyyymmdd).set(payload)

    def get_metrics(self, date_yyyymmdd: str) -> dict[str, Any] | None:
        doc = self._client.collection("metrics").document(date_yyyymmdd).get()
        return doc.to_dict() if doc.exists else None

    # ── helpers used by /admin and /cron ────────────────
    def list_recent_articles(self, source: str | None, limit: int) -> list[Article]:
        coll = self._client.collection("articles")
        query = coll.where("source", "==", source) if source else coll
        query = query.order_by("processed_at", direction=firestore.Query.DESCENDING).limit(limit)
        return [Article.model_validate(d.to_dict()) for d in query.stream()]

    def list_articles_in_range(
        self, start: datetime, end: datetime
    ) -> list[Article]:
        docs = (
            self._client.collection("articles")
            .where("processed_at", ">=", start.isoformat())
            .where("processed_at", "<", end.isoformat())
            .stream()
        )
        return [Article.model_validate(d.to_dict()) for d in docs]
```

Note: `model_dump(mode="json")` produces ISO strings for datetime, which Firestore accepts and round-trips through Pydantic. (Firestore native `Timestamp` round-tripping works too but adds a sentinel-conversion layer; keeping it as ISO strings is simpler for the PoC and is identical for query semantics with the indexes we declared.)

- [ ] **Step 4: Run test, expect PASS**

```bash
cd services/api && uv run pytest tests/test_firestore_repo.py -v
```

- [ ] **Step 5: Lint, type, commit**

```bash
cd services/api && uv run ruff format . && uv run ruff check . --fix && uv run mypy app
cd /Users/farron/code/Auralee
git add services/api/app/services/firestore_repo.py services/api/tests/test_firestore_repo.py
git commit -m "feat(api): Firestore repository wrapper"
```

### Task 2.4: HTTP client + UA constants

**Files:**
- Create: `services/api/app/http_client.py`

- [ ] **Step 1: Implement `services/api/app/http_client.py`**

```python
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

import httpx

UA_DESKTOP = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)
UA_SAFARI_MAC = UA_DESKTOP


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, connect=5.0),
        follow_redirects=True,
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        transport=httpx.AsyncHTTPTransport(retries=2),
    )


@asynccontextmanager
async def http_client() -> AsyncIterator[httpx.AsyncClient]:
    client = make_client()
    try:
        yield client
    finally:
        await client.aclose()
```

- [ ] **Step 2: Smoke test (fetch a public URL)**

```bash
cd services/api && uv run python -c "
import asyncio
from app.http_client import http_client

async def main():
    async with http_client() as c:
        r = await c.get('https://hacker-news.firebaseio.com/v0/topstories.json')
        print(r.status_code, len(r.json()))
asyncio.run(main())
"
```

Expected: `200 N` where N ≈ 500.

- [ ] **Step 3: Lint, type, commit**

```bash
cd services/api && uv run ruff format . && uv run ruff check . --fix && uv run mypy app
cd /Users/farron/code/Auralee
git add services/api/app/http_client.py
git commit -m "feat(api): shared httpx client + UA constants"
```

**Phase 2 done.** Secrets, GCS, Firestore, and HTTP client wrappers ready.

---

## Phase 3 — Ingest Pipeline (Gemini + /ingest)

Goal: end-to-end synchronous ingest. Submit `IngestPayload` → get `IngestResponse` with extraction stored in Firestore.

### Task 3.1: Extraction prompt v1

**Files:**
- Create: `services/api/app/prompts/__init__.py`
- Create: `services/api/app/prompts/extraction_v1.py`

- [ ] **Step 1: Create `services/api/app/prompts/__init__.py` (empty)**

```bash
touch services/api/app/prompts/__init__.py
```

- [ ] **Step 2: Implement `services/api/app/prompts/extraction_v1.py`**

```python
"""Extraction prompt — version 1.

When changing this prompt in a way that may shift Gemini's outputs, BUMP
PROMPT_VERSION (e.g. v1 -> v2) and keep the old constant if you need to
re-process old content with the old prompt.
"""

PROMPT_VERSION = "v1"

SYSTEM_INSTRUCTION = """\
You are a financial news analyst. Extract structured data from news articles.

RULES:

1. tickers — Only US-listed equities (NYSE, NASDAQ). Uppercase, no exchange prefix.
   - "Apple" -> "AAPL". "Tesla" -> "TSLA".
   - Do NOT invent tickers for private companies, foreign-only listings, or vague references.
   - If unsure, OMIT. Empty list is correct.

2. sentiment — Direction for the PRIMARY SUBJECT of the article.
   - score: -1.0 (most bearish) to +1.0 (most bullish), use 0.0 for neutral/factual
   - label: bullish | bearish | neutral
   - Pure factual reporting (e.g. "Fed announced...") with no clear direction -> neutral / 0.0

3. summary — 2-3 sentences, factual, in the SAME language as the article.

4. core_thesis — The article's central argument or news angle, 1 sentence.

5. entities — Named companies, people, locations, products. Skip generic terms ("the market", "investors").

6. NEVER fabricate. If unknown -> safe default (empty list / "neutral" / etc.).

EXAMPLES:

Article: "Apple Inc. reported Q2 earnings of $1.52 per share, beating consensus..."
-> tickers: ["AAPL"], sentiment: {score: 0.7, label: "bullish"}, core_thesis: "Apple Q2 EPS beat estimates."

Article: "The Federal Reserve held rates steady at 5.25-5.50%."
-> tickers: [], sentiment: {score: 0.0, label: "neutral"}, core_thesis: "Fed maintained current interest rates."

Article: "OpenAI is rumored to be raising at $300B valuation."
-> tickers: [], sentiment: {score: 0.0, label: "neutral"}
   # OpenAI is private, no ticker
"""


def build_user_message(*, source: str, url: str, published_at: str, clean_text: str) -> str:
    return (
        f"Source: {source} | URL: {url} | Published: {published_at}\n\n"
        f"Article:\n---\n{clean_text}\n---\n\n"
        f"Respond with the structured Extraction JSON."
    )
```

- [ ] **Step 3: Commit**

```bash
git add services/api/app/prompts/
git commit -m "feat(api): extraction prompt v1 (system + builder)"
```

### Task 3.2: Gemini Flash extraction wrapper

**Files:**
- Create: `services/api/app/services/gemini.py`
- Create: `services/api/tests/test_gemini.py`

- [ ] **Step 1: Write failing test (mocked Gemini client)**

`services/api/tests/test_gemini.py`:

```python
from unittest.mock import MagicMock

import pytest

from app.models.article import Sentiment
from app.services.gemini import ExtractionResult, GeminiExtractor


@pytest.fixture
def fake_response_json() -> str:
    return (
        '{"title":"t","summary":"s","tickers":["AAPL"],'
        '"sentiment":{"score":0.5,"label":"bullish"},'
        '"core_thesis":"c","categories":[],"entities":[],"language":"en"}'
    )


def test_extract_parses_response_into_pydantic(fake_response_json: str) -> None:
    fake_response = MagicMock()
    fake_response.text = fake_response_json
    fake_response.usage_metadata.prompt_token_count = 100
    fake_response.usage_metadata.candidates_token_count = 50

    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = fake_response

    extractor = GeminiExtractor(model="gemini-2.5-flash", _client=fake_client)
    result: ExtractionResult = extractor.extract(
        source="wsj",
        url="https://x",
        published_at="2026-04-24T13:30:00Z",
        clean_text="Apple beat earnings.",
    )

    assert result.extraction.tickers == ["AAPL"]
    assert result.extraction.sentiment == Sentiment(score=0.5, label="bullish")
    assert result.tokens_in == 100
    assert result.tokens_out == 50
    assert result.cost_usd > 0
    assert result.latency_ms >= 0
    assert result.prompt_version == "v1"
```

- [ ] **Step 2: Run, expect FAIL**

```bash
cd services/api && uv run pytest tests/test_gemini.py -v
```

- [ ] **Step 3: Implement `services/api/app/services/gemini.py`**

```python
import logging
import time
from dataclasses import dataclass
from typing import Any

from google import genai
from google.genai import types

from app.models.article import Extraction
from app.prompts.extraction_v1 import (
    PROMPT_VERSION,
    SYSTEM_INSTRUCTION,
    build_user_message,
)

logger = logging.getLogger(__name__)

# Gemini 2.5 Flash pricing (USD per 1M tokens), late-2025
_PRICE_FLASH_INPUT_PER_M = 0.075
_PRICE_FLASH_OUTPUT_PER_M = 0.30


def _flash_cost(tokens_in: int, tokens_out: int) -> float:
    return (
        tokens_in / 1_000_000 * _PRICE_FLASH_INPUT_PER_M
        + tokens_out / 1_000_000 * _PRICE_FLASH_OUTPUT_PER_M
    )


@dataclass
class ExtractionResult:
    extraction: Extraction
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int
    prompt_version: str
    model: str


class GeminiExtractor:
    def __init__(
        self,
        model: str = "gemini-2.5-flash",
        project: str | None = None,
        location: str = "us-east1",
        _client: Any | None = None,
    ) -> None:
        self._model = model
        self._client = _client or genai.Client(
            vertexai=True,
            project=project,
            location=location,
        )

    @property
    def model(self) -> str:
        return self._model

    def check_health(self) -> None:
        response = self._client.models.count_tokens(
            model=self._model,
            contents="Auralee Vertex AI health check",
        )
        total_tokens = getattr(response, "total_tokens", None)
        if not isinstance(total_tokens, int) or total_tokens < 1:
            raise RuntimeError("Vertex AI countTokens returned no token count")

    def extract(
        self,
        *,
        source: str,
        url: str,
        published_at: str,
        clean_text: str,
    ) -> ExtractionResult:
        user_msg = build_user_message(
            source=source, url=url, published_at=published_at, clean_text=clean_text,
        )
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=Extraction,
            temperature=0.1,
            max_output_tokens=2048,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )

        t0 = time.perf_counter()
        response = self._client.models.generate_content(
            model=self._model,
            config=config,
            contents=[user_msg],
        )
        latency_ms = int((time.perf_counter() - t0) * 1000)

        extraction = Extraction.model_validate_json(response.text)

        tokens_in = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
        tokens_out = getattr(response.usage_metadata, "candidates_token_count", 0) or 0
        cost = _flash_cost(tokens_in, tokens_out)

        return ExtractionResult(
            extraction=extraction,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
            latency_ms=latency_ms,
            prompt_version=PROMPT_VERSION,
            model=self._model,
        )
```

- [ ] **Step 4: Run test, expect PASS**

```bash
cd services/api && uv run pytest tests/test_gemini.py -v
```

- [ ] **Step 5: Lint, type, commit**

```bash
cd services/api && uv run ruff format . && uv run ruff check . --fix && uv run mypy app
cd /Users/farron/code/Auralee
git add services/api/app/services/gemini.py services/api/tests/test_gemini.py
git commit -m "feat(api): Gemini Flash extractor wrapper"
```

> **Note on Context Caching:** the spec calls for caching the system instruction. The `google-genai` SDK exposes this via `client.caches.create(...)` returning a handle to pass as `cached_content` in `GenerateContentConfig`. We deliberately defer this micro-optimization to a Week-1 follow-up: it requires a startup-time cache creation flow with TTL refresh, and the un-cached cost ($0.0005/article × 3000 = $1.50/month) is already negligible. If/when added, only `GeminiExtractor.__init__` and a `refresh_cache` method need to change.

### Task 3.3: HTML normalization helper (trafilatura)

**Files:**
- Create: `services/api/app/services/html_extract.py`
- Create: `services/api/tests/test_html_extract.py`
- Create: `services/api/tests/data/__init__.py`
- Create: `services/api/tests/data/wsj_sample.html`

- [ ] **Step 1: Create `tests/data/__init__.py` and a small HTML fixture**

```bash
touch services/api/tests/data/__init__.py
```

`services/api/tests/data/wsj_sample.html`:

```html
<!DOCTYPE html>
<html><head><title>Sample WSJ Article</title></head>
<body>
<nav>Sections | Markets | Tech | Sign In</nav>
<header><h1>Apple Reports Strong Q2 Earnings</h1></header>
<article>
<p>Apple Inc. reported quarterly earnings that exceeded analysts' expectations,
driven by strong iPhone sales in China and continued growth in services revenue.</p>
<p>The company posted earnings per share of $1.52, beating the consensus
estimate of $1.43. Revenue rose 8% year over year to $94.8 billion.</p>
<p>"We are pleased with our performance this quarter," said CEO Tim Cook.</p>
</article>
<footer>Copyright Dow Jones</footer>
</body></html>
```

- [ ] **Step 2: Write failing tests**

`services/api/tests/test_html_extract.py`:

```python
from importlib.resources import files

from app.services.html_extract import extract_clean_text


def _load_sample() -> str:
    return files("tests.data").joinpath("wsj_sample.html").read_text()


def test_extracts_main_body_skipping_nav_footer() -> None:
    html = _load_sample()
    text = extract_clean_text(html)
    assert text is not None
    assert "Apple Inc." in text
    assert "iPhone sales" in text
    assert "Sign In" not in text
    assert "Copyright Dow Jones" not in text


def test_returns_none_for_empty_html() -> None:
    assert extract_clean_text("") is None


def test_returns_none_for_garbage_html() -> None:
    # No body content => trafilatura returns None
    assert extract_clean_text("<html></html>") is None
```

- [ ] **Step 3: Run, expect FAIL**

```bash
cd services/api && uv run pytest tests/test_html_extract.py -v
```

- [ ] **Step 4: Implement `services/api/app/services/html_extract.py`**

```python
import trafilatura


def extract_clean_text(html: str) -> str | None:
    if not html or not html.strip():
        return None
    return trafilatura.extract(
        html,
        include_comments=False,
        include_tables=False,
        favor_recall=False,
        no_fallback=False,
    )
```

- [ ] **Step 5: Run test, expect PASS**

```bash
cd services/api && uv run pytest tests/test_html_extract.py -v
```

- [ ] **Step 6: Lint, type, commit**

```bash
cd services/api && uv run ruff format . && uv run ruff check . --fix && uv run mypy app
cd /Users/farron/code/Auralee
git add services/api/app/services/html_extract.py services/api/tests/test_html_extract.py services/api/tests/data/
git commit -m "feat(api): HTML clean-text extraction via trafilatura"
```

### Task 3.4: `ingest_service.process()` orchestrator

**Files:**
- Create: `services/api/app/services/ingest_service.py`
- Create: `services/api/tests/test_ingest_service.py`

This is the heart of the pipeline. It composes article_id → existence check → HTML clean → Gemini → sanity → Firestore write → GCS archive (fire-and-forget).

- [ ] **Step 1: Write failing tests (with all dependencies mocked)**

`services/api/tests/test_ingest_service.py`:

```python
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from app.models.article import Extraction, Sentiment
from app.models.ingest import IngestPayload, RawHtml, RawText
from app.services.gemini import ExtractionResult
from app.services.ingest_service import IngestService


@pytest.fixture
def sample_extraction() -> Extraction:
    return Extraction(
        title="Apple Q2",
        summary="Apple beat earnings.",
        tickers=["AAPL"],
        sentiment=Sentiment(score=0.7, label="bullish"),
        core_thesis="Apple Q2 EPS beat.",
        categories=["earnings"],
        entities=[],
        language="en",
    )


@pytest.fixture
def sample_extraction_result(sample_extraction: Extraction) -> ExtractionResult:
    return ExtractionResult(
        extraction=sample_extraction,
        tokens_in=1000, tokens_out=200,
        cost_usd=0.0001, latency_ms=200,
        prompt_version="v1", model="gemini-2.5-flash",
    )


@pytest.fixture
def html_payload() -> IngestPayload:
    return IngestPayload(
        source="wsj", source_id="x",
        url="https://www.wsj.com/articles/apple-q2",
        fetched_at=datetime(2026, 4, 24, 13, 30, tzinfo=UTC),
        raw=RawHtml(kind="html", html=(
            "<html><body><article>"
            + "Apple Inc. reported strong earnings. " * 60
            + "</article></body></html>"
        )),
    )


def test_duplicate_returns_status_duplicate_without_calling_gemini(
    html_payload: IngestPayload,
) -> None:
    repo = MagicMock(); repo.article_exists.return_value = True
    extractor = MagicMock()
    archiver = MagicMock()
    svc = IngestService(repo=repo, extractor=extractor, archiver=archiver)

    response = svc.process(html_payload)

    assert response.status == "duplicate"
    extractor.extract.assert_not_called()
    repo.save_article.assert_not_called()


def test_short_text_returns_skipped_short(html_payload: IngestPayload) -> None:
    repo = MagicMock(); repo.article_exists.return_value = False
    extractor = MagicMock()
    archiver = MagicMock()
    svc = IngestService(repo=repo, extractor=extractor, archiver=archiver)

    short = html_payload.model_copy(
        update={"raw": RawHtml(kind="html", html="<html><body>short</body></html>")}
    )
    response = svc.process(short)

    assert response.status == "skipped_short"
    extractor.extract.assert_not_called()


def test_text_payload_skips_html_extraction(
    sample_extraction_result: ExtractionResult,
) -> None:
    repo = MagicMock(); repo.article_exists.return_value = False
    extractor = MagicMock(); extractor.extract.return_value = sample_extraction_result
    archiver = MagicMock()

    payload = IngestPayload(
        source="hn", source_id="42",
        url="https://news.ycombinator.com/item?id=42",
        fetched_at=datetime(2026, 4, 24, tzinfo=UTC),
        raw=RawText(kind="text", title="t", body="x" * 1000, metadata={}),
    )
    svc = IngestService(repo=repo, extractor=extractor, archiver=archiver)
    response = svc.process(payload)

    assert response.status == "ingested"
    archiver.upload_safe.assert_not_called()
    extractor.extract.assert_called_once()


def test_html_happy_path_writes_article_and_returns_extracted(
    html_payload: IngestPayload, sample_extraction_result: ExtractionResult,
) -> None:
    repo = MagicMock(); repo.article_exists.return_value = False
    extractor = MagicMock(); extractor.extract.return_value = sample_extraction_result
    archiver = MagicMock(); archiver.upload_safe.return_value = "gs://bucket/x.html"

    svc = IngestService(repo=repo, extractor=extractor, archiver=archiver)
    response = svc.process(html_payload)

    assert response.status == "ingested"
    assert response.article_id.startswith("wsj_")
    assert response.extracted is not None
    assert response.extracted.tickers == ["AAPL"]
    assert response.meta is not None
    assert response.meta.cost_usd == 0.0001
    assert response.meta.raw_html_gcs_uri == "gs://bucket/x.html"

    repo.save_article.assert_called_once()
    saved = repo.save_article.call_args[0][0]
    assert saved.tickers == ["AAPL"]
    assert saved.sanity_check is not None
    assert saved.sanity_check.ticker_precision_pass is True

    repo.upsert_ticker_stub.assert_called_with("AAPL")
```

- [ ] **Step 2: Run, expect FAIL**

```bash
cd services/api && uv run pytest tests/test_ingest_service.py -v
```

- [ ] **Step 3: Implement `services/api/app/services/ingest_service.py`**

```python
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
```

- [ ] **Step 4: Run test, expect PASS**

```bash
cd services/api && uv run pytest tests/test_ingest_service.py -v
```

- [ ] **Step 5: Lint, type, commit**

```bash
cd services/api && uv run ruff format . && uv run ruff check . --fix && uv run mypy app
cd /Users/farron/code/Auralee
git add services/api/app/services/ingest_service.py services/api/tests/test_ingest_service.py
git commit -m "feat(api): IngestService orchestrator (id->dedupe->extract->sanity->save)"
```

### Task 3.5: `/ingest` router

**Files:**
- Create: `services/api/app/routers/ingest.py`
- Create: `services/api/tests/test_routers/test_ingest_router.py`
- Modify: `services/api/app/main.py`
- Modify: `services/api/app/deps.py` (add factory deps)

- [ ] **Step 1: Add factory deps to `services/api/app/deps.py`**

Edit `services/api/app/deps.py`:

```python
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from app.config import Settings, get_settings
from app.services.firestore_repo import FirestoreRepo
from app.services.gcs import RawHtmlArchiver
from app.services.gemini import GeminiExtractor
from app.services.ingest_service import IngestService
from app.services.secrets import SecretClient


def require_admin_token(
    x_admin_token: Annotated[str | None, Header()] = None,
    settings: Annotated[Settings, Depends(get_settings)] = ...,  # type: ignore[assignment]
) -> None:
    if not settings.admin_token:
        raise HTTPException(status_code=503, detail="ADMIN_TOKEN not configured")
    if not x_admin_token or x_admin_token != settings.admin_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")


@lru_cache(maxsize=1)
def get_repo() -> FirestoreRepo:
    return FirestoreRepo()


@lru_cache(maxsize=1)
def get_archiver() -> RawHtmlArchiver:
    return RawHtmlArchiver(bucket_name=get_settings().raw_bucket)


@lru_cache(maxsize=1)
def get_secrets() -> SecretClient:
    return SecretClient(project_id=get_settings().gcp_project)


@lru_cache(maxsize=1)
def get_extractor() -> GeminiExtractor:
    s = get_settings()
    return GeminiExtractor(
        model=s.extraction_model,
        project=s.gcp_project,
        location=s.gcp_region,
    )


def get_ingest_service(
    repo: Annotated[FirestoreRepo, Depends(get_repo)],
    extractor: Annotated[GeminiExtractor, Depends(get_extractor)],
    archiver: Annotated[RawHtmlArchiver, Depends(get_archiver)],
) -> IngestService:
    return IngestService(repo=repo, extractor=extractor, archiver=archiver)
```

- [ ] **Step 2: Implement `services/api/app/routers/ingest.py`**

```python
from typing import Annotated

from fastapi import APIRouter, Depends

from app.deps import get_ingest_service, require_admin_token
from app.models.ingest import IngestPayload, IngestResponse
from app.services.ingest_service import IngestService

router = APIRouter(tags=["ingest"], dependencies=[Depends(require_admin_token)])


@router.post("/ingest", response_model=IngestResponse)
async def ingest(
    payload: IngestPayload,
    service: Annotated[IngestService, Depends(get_ingest_service)],
) -> IngestResponse:
    return service.process(payload)
```

- [ ] **Step 3: Wire router into `services/api/app/main.py`**

Edit `services/api/app/main.py`:

```python
from fastapi import Depends, FastAPI

from app.deps import require_admin_token
from app.logging_setup import configure_logging
from app.routers import health, ingest


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="auralee-api", version="0.1.0")
    app.include_router(health.router)
    app.include_router(ingest.router)

    @app.get("/_test/admin-echo", dependencies=[Depends(require_admin_token)])
    async def _admin_echo() -> dict[str, bool]:
        return {"ok": True}

    return app


app = create_app()
```

- [ ] **Step 4: Write router test (with mocked service via dependency_overrides)**

`services/api/tests/test_routers/test_ingest_router.py`:

```python
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.deps import get_ingest_service
from app.main import create_app
from app.models.article import Extraction, Sentiment
from app.models.ingest import IngestMeta, IngestResponse


@pytest.fixture
def client_with_mock_service() -> tuple[TestClient, MagicMock]:
    mock_service = MagicMock()
    app = create_app()
    app.dependency_overrides[get_ingest_service] = lambda: mock_service
    return TestClient(app), mock_service


def test_ingest_requires_admin_token(client_with_mock_service: tuple[TestClient, MagicMock]) -> None:
    client, _ = client_with_mock_service
    response = client.post("/ingest", json={})
    assert response.status_code in (401, 422)  # 422 if validation runs first; 401 either way


def test_ingest_accepts_html_payload_and_returns_response(
    client_with_mock_service: tuple[TestClient, MagicMock], monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "test-token")
    from app.config import get_settings
    get_settings.cache_clear()

    client, mock_service = client_with_mock_service
    mock_service.process.return_value = IngestResponse(
        article_id="wsj_20260424_a3f1b9d2",
        status="ingested",
        extracted=Extraction(
            title="t", summary="s", tickers=["AAPL"],
            sentiment=Sentiment(score=0.5, label="bullish"),
            core_thesis="c", language="en",
        ),
        meta=IngestMeta(
            tokens_in=10, tokens_out=5, cost_usd=0.0001,
            latency_ms=100, prompt_version="v1",
        ),
    )

    body = {
        "source": "wsj",
        "source_id": "WP-1",
        "url": "https://www.wsj.com/articles/x",
        "fetched_at": datetime(2026, 4, 24, tzinfo=UTC).isoformat(),
        "raw": {"kind": "html", "html": "<html></html>", "encoding": "utf-8"},
    }
    response = client.post("/ingest", json=body, headers={"X-Admin-Token": "test-token"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ingested"
    assert data["extracted"]["tickers"] == ["AAPL"]
```

- [ ] **Step 5: Run tests, expect PASS**

```bash
cd services/api && uv run pytest tests/test_routers/test_ingest_router.py -v
```

- [ ] **Step 6: Lint, type, commit**

```bash
cd services/api && uv run ruff format . && uv run ruff check . --fix && uv run mypy app
cd /Users/farron/code/Auralee
git add services/api/app/routers/ingest.py services/api/app/deps.py services/api/app/main.py services/api/tests/test_routers/test_ingest_router.py
git commit -m "feat(api): /ingest endpoint with admin auth + DI factories"
```

**Phase 3 done.** Synchronous ingest pipeline works end-to-end (with mocks). After deploy, you can `curl POST /ingest` against Cloud Run with a real HTML payload to confirm Gemini integration. Phase 4 wires the scrapers that will feed `/ingest`.

---

## Phase 4 — Scrapers

Goal: three scrapers (HN, Reuters, WSJ) implementing a common interface, plus the `/cron/scrape?source=…` route that drives them.

### Task 4.1: BaseScraper interface + Candidate

**Files:**
- Create: `services/api/app/services/scrapers/__init__.py`
- Create: `services/api/app/services/scrapers/base.py`

- [ ] **Step 1: Create empty `__init__.py`**

```bash
touch services/api/app/services/scrapers/__init__.py
```

- [ ] **Step 2: Implement `services/api/app/services/scrapers/base.py`**

```python
from abc import ABC, abstractmethod

import httpx

from app.models.candidate import Candidate
from app.models.ingest import IngestPayload


class BaseScraper(ABC):
    source_name: str

    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    @abstractmethod
    async def list_candidates(self, limit: int = 50) -> list[Candidate]: ...

    @abstractmethod
    async def fetch_one(self, candidate: Candidate) -> IngestPayload: ...
```

- [ ] **Step 3: Commit**

```bash
git add services/api/app/services/scrapers/
git commit -m "feat(api): BaseScraper interface"
```

### Task 4.2: Hacker News scraper

**Files:**
- Create: `services/api/app/services/scrapers/hn.py`
- Create: `services/api/tests/test_scrapers/__init__.py`
- Create: `services/api/tests/test_scrapers/test_hn.py`

- [ ] **Step 1: Create test dir init**

```bash
touch services/api/tests/test_scrapers/__init__.py
```

- [ ] **Step 2: Write failing tests with `pytest-httpx`**

`services/api/tests/test_scrapers/test_hn.py`:

```python
import json

import httpx
import pytest
from pytest_httpx import HTTPXMock

from app.services.scrapers.hn import HNScraper


@pytest.mark.asyncio
async def test_list_candidates_returns_top_stories(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://hacker-news.firebaseio.com/v0/topstories.json",
        json=[1, 2, 3],
    )
    httpx_mock.add_response(
        url="https://hacker-news.firebaseio.com/v0/item/1.json",
        json={"id": 1, "type": "story", "title": "T1", "url": "https://x/1", "time": 1714000000},
    )
    httpx_mock.add_response(
        url="https://hacker-news.firebaseio.com/v0/item/2.json",
        json={"id": 2, "type": "story", "title": "T2", "url": "https://x/2", "time": 1714000100},
    )
    httpx_mock.add_response(
        url="https://hacker-news.firebaseio.com/v0/item/3.json",
        json={"id": 3, "type": "comment", "time": 1714000200},  # filtered out
    )

    async with httpx.AsyncClient() as client:
        scraper = HNScraper(http=client)
        candidates = await scraper.list_candidates(limit=3)

    assert len(candidates) == 2  # comment filtered
    assert candidates[0].source_id == "1"
    assert candidates[0].title == "T1"
    assert str(candidates[0].url) == "https://x/1"


@pytest.mark.asyncio
async def test_fetch_one_returns_html_payload_when_url_reachable(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://example.com/article",
        text="<html><body><p>Some article body.</p></body></html>",
    )

    async with httpx.AsyncClient() as client:
        scraper = HNScraper(http=client)
        from app.models.candidate import Candidate
        from datetime import UTC, datetime
        c = Candidate(
            source_id="42", url="https://example.com/article",
            title="t", published_at=datetime(2026, 4, 24, tzinfo=UTC),
        )
        payload = await scraper.fetch_one(c)

    assert payload.source == "hn"
    assert payload.url == "https://example.com/article"
    assert payload.raw.kind == "html"


@pytest.mark.asyncio
async def test_fetch_one_falls_back_to_text_on_fetch_failure(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_exception(httpx.ConnectError("boom"), url="https://broken.example/")

    async with httpx.AsyncClient() as client:
        scraper = HNScraper(http=client)
        from app.models.candidate import Candidate
        from datetime import UTC, datetime
        c = Candidate(
            source_id="99", url="https://broken.example/",
            title="A title", published_at=datetime(2026, 4, 24, tzinfo=UTC),
        )
        payload = await scraper.fetch_one(c)

    assert payload.raw.kind == "text"
    assert payload.raw.title == "A title"
```

- [ ] **Step 3: Run, expect FAIL**

```bash
cd services/api && uv run pytest tests/test_scrapers/test_hn.py -v
```

- [ ] **Step 4: Implement `services/api/app/services/scrapers/hn.py`**

```python
import asyncio
import logging
from datetime import UTC, datetime

import httpx

from app.models.candidate import Candidate
from app.models.ingest import IngestPayload, RawHtml, RawText
from app.services.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

_TOP_STORIES_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
_ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{id}.json"


class HNScraper(BaseScraper):
    source_name = "hn"

    async def list_candidates(self, limit: int = 30) -> list[Candidate]:
        ids_response = await self._http.get(_TOP_STORIES_URL)
        ids_response.raise_for_status()
        ids: list[int] = ids_response.json()[:limit]

        items = await asyncio.gather(
            *[self._fetch_item(i) for i in ids], return_exceptions=False
        )

        candidates: list[Candidate] = []
        for item in items:
            if not item or item.get("type") != "story":
                continue
            url = item.get("url") or f"https://news.ycombinator.com/item?id={item['id']}"
            candidates.append(
                Candidate(
                    source_id=str(item["id"]),
                    url=url,
                    title=item.get("title"),
                    published_at=datetime.fromtimestamp(item["time"], tz=UTC),
                )
            )
        return candidates

    async def _fetch_item(self, item_id: int) -> dict | None:
        try:
            r = await self._http.get(_ITEM_URL.format(id=item_id), timeout=10.0)
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError):
            logger.warning("HN item fetch failed", extra={"item_id": item_id})
            return None

    async def fetch_one(self, candidate: Candidate) -> IngestPayload:
        published_at = candidate.published_at or datetime.now(UTC)
        try:
            r = await self._http.get(candidate.url, timeout=10.0)
            r.raise_for_status()
            return IngestPayload(
                source="hn",
                source_id=candidate.source_id,
                url=candidate.url,
                fetched_at=datetime.now(UTC),
                raw=RawHtml(kind="html", html=r.text),
            )
        except httpx.HTTPError:
            logger.info(
                "HN external URL fetch failed; falling back to title-only",
                extra={"url": candidate.url},
            )
            return IngestPayload(
                source="hn",
                source_id=candidate.source_id,
                url=candidate.url,
                fetched_at=datetime.now(UTC),
                raw=RawText(
                    kind="text",
                    title=candidate.title or "",
                    body=candidate.title or "",
                    metadata={"published_at": published_at.isoformat()},
                ),
            )
```

- [ ] **Step 5: Run test, expect PASS**

```bash
cd services/api && uv run pytest tests/test_scrapers/test_hn.py -v
```

- [ ] **Step 6: Lint, type, commit**

```bash
cd services/api && uv run ruff format . && uv run ruff check . --fix && uv run mypy app
cd /Users/farron/code/Auralee
git add services/api/app/services/scrapers/hn.py services/api/tests/test_scrapers/
git commit -m "feat(api): Hacker News scraper"
```

### Task 4.3: Reuters scraper (RSS)

**Files:**
- Create: `services/api/app/services/scrapers/reuters.py`
- Create: `services/api/tests/data/reuters_feed.xml`
- Create: `services/api/tests/test_scrapers/test_reuters.py`

- [ ] **Step 1: Create RSS fixture**

`services/api/tests/data/reuters_feed.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<title>Reuters Markets</title>
<link>https://www.reuters.com</link>
<description>test feed</description>
<item>
  <title>Stocks rise on Fed comments</title>
  <link>https://www.reuters.com/markets/stocks-rise-1</link>
  <guid>https://www.reuters.com/markets/stocks-rise-1</guid>
  <pubDate>Fri, 24 Apr 2026 13:30:00 GMT</pubDate>
  <description>Brief...</description>
</item>
<item>
  <title>Apple beats earnings</title>
  <link>https://www.reuters.com/markets/apple-q2</link>
  <guid>https://www.reuters.com/markets/apple-q2</guid>
  <pubDate>Fri, 24 Apr 2026 14:00:00 GMT</pubDate>
  <description>Brief...</description>
</item>
</channel></rss>
```

- [ ] **Step 2: Write failing tests**

`services/api/tests/test_scrapers/test_reuters.py`:

```python
from importlib.resources import files

import httpx
import pytest
from pytest_httpx import HTTPXMock

from app.services.scrapers.reuters import FEEDS, ReutersScraper


@pytest.mark.asyncio
async def test_list_candidates_parses_rss_and_dedupes(httpx_mock: HTTPXMock) -> None:
    feed = files("tests.data").joinpath("reuters_feed.xml").read_text()
    for url in FEEDS:
        httpx_mock.add_response(url=url, text=feed)

    async with httpx.AsyncClient() as client:
        scraper = ReutersScraper(http=client)
        candidates = await scraper.list_candidates(limit=10)

    # 2 items per feed × N feeds, but dedupe by URL → 2 unique
    assert len(candidates) == 2
    titles = {c.title for c in candidates}
    assert "Apple beats earnings" in titles


@pytest.mark.asyncio
async def test_fetch_one_returns_html_payload(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://www.reuters.com/markets/apple-q2",
        text="<html><body><p>Long article.</p></body></html>",
    )
    async with httpx.AsyncClient() as client:
        scraper = ReutersScraper(http=client)
        from datetime import UTC, datetime
        from app.models.candidate import Candidate
        c = Candidate(
            source_id="1", url="https://www.reuters.com/markets/apple-q2",
            title="Apple", published_at=datetime(2026, 4, 24, tzinfo=UTC),
        )
        payload = await scraper.fetch_one(c)

    assert payload.source == "reuters"
    assert payload.raw.kind == "html"
```

- [ ] **Step 3: Run, expect FAIL**

```bash
cd services/api && uv run pytest tests/test_scrapers/test_reuters.py -v
```

- [ ] **Step 4: Implement `services/api/app/services/scrapers/reuters.py`**

```python
import logging
from datetime import UTC, datetime

import feedparser

from app.http_client import UA_DESKTOP
from app.models.candidate import Candidate
from app.models.ingest import IngestPayload, RawHtml
from app.services.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

FEEDS = [
    "https://feeds.reuters.com/reuters/businessNews",
    "https://feeds.reuters.com/reuters/marketsNews",
]


class ReutersScraper(BaseScraper):
    source_name = "reuters"

    async def list_candidates(self, limit: int = 50) -> list[Candidate]:
        seen: dict[str, Candidate] = {}
        for feed_url in FEEDS:
            try:
                resp = await self._http.get(feed_url, timeout=15.0)
                resp.raise_for_status()
            except Exception:  # noqa: BLE001
                logger.warning("Reuters feed fetch failed", extra={"feed": feed_url})
                continue
            parsed = feedparser.parse(resp.text)
            for entry in parsed.entries[:limit]:
                url = entry.link
                if url in seen:
                    continue
                published = self._parse_pubdate(entry)
                seen[url] = Candidate(
                    source_id=entry.get("id") or url,
                    url=url,
                    title=entry.get("title"),
                    published_at=published,
                )
        return list(seen.values())

    @staticmethod
    def _parse_pubdate(entry: dict) -> datetime | None:
        struct = entry.get("published_parsed") or entry.get("updated_parsed")
        if not struct:
            return None
        return datetime(*struct[:6], tzinfo=UTC)

    async def fetch_one(self, candidate: Candidate) -> IngestPayload:
        resp = await self._http.get(
            candidate.url,
            timeout=15.0,
            headers={"User-Agent": UA_DESKTOP},
        )
        resp.raise_for_status()
        return IngestPayload(
            source="reuters",
            source_id=candidate.source_id,
            url=candidate.url,
            fetched_at=datetime.now(UTC),
            raw=RawHtml(kind="html", html=resp.text),
        )
```

- [ ] **Step 5: Run test, expect PASS**

```bash
cd services/api && uv run pytest tests/test_scrapers/test_reuters.py -v
```

- [ ] **Step 6: Lint, type, commit**

```bash
cd services/api && uv run ruff format . && uv run ruff check . --fix && uv run mypy app
cd /Users/farron/code/Auralee
git add services/api/app/services/scrapers/reuters.py services/api/tests/test_scrapers/test_reuters.py services/api/tests/data/reuters_feed.xml
git commit -m "feat(api): Reuters RSS scraper"
```

### Task 4.4: WSJ scraper (RSS + cookie fetch)

**Files:**
- Create: `services/api/app/services/scrapers/wsj.py`
- Create: `services/api/tests/data/wsj_feed.xml`
- Create: `services/api/tests/test_scrapers/test_wsj.py`

- [ ] **Step 1: Create RSS fixture**

`services/api/tests/data/wsj_feed.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<title>WSJ Markets</title>
<link>https://www.wsj.com</link>
<description>test feed</description>
<item>
  <title>Apple beats Q2</title>
  <link>https://www.wsj.com/articles/apple-q2-12345</link>
  <guid>WP-AAPL-1</guid>
  <pubDate>Fri, 24 Apr 2026 13:30:00 GMT</pubDate>
</item>
<item>
  <title>Markets Snapshot Video</title>
  <link>https://www.wsj.com/video/snapshot-99</link>
  <guid>WP-VID-1</guid>
  <pubDate>Fri, 24 Apr 2026 14:00:00 GMT</pubDate>
</item>
</channel></rss>
```

- [ ] **Step 2: Write failing tests**

`services/api/tests/test_scrapers/test_wsj.py`:

```python
from importlib.resources import files

import httpx
import pytest
from pytest_httpx import HTTPXMock

from app.services.scrapers.wsj import (
    RSS_FEEDS,
    WSJCookieExpiredError,
    WSJScraper,
)


@pytest.mark.asyncio
async def test_list_candidates_filters_to_articles_only(httpx_mock: HTTPXMock) -> None:
    feed = files("tests.data").joinpath("wsj_feed.xml").read_text()
    for url in RSS_FEEDS:
        httpx_mock.add_response(url=url, text=feed)

    async with httpx.AsyncClient() as client:
        scraper = WSJScraper(http=client, cookie="cookie=value")
        candidates = await scraper.list_candidates(limit=10)

    assert len(candidates) == 1  # video link filtered
    assert "wsj.com/articles/" in candidates[0].url


@pytest.mark.asyncio
async def test_fetch_one_includes_cookie_and_returns_html(httpx_mock: HTTPXMock) -> None:
    body = "Long article body. " * 800  # > 5000 chars
    httpx_mock.add_response(
        url="https://www.wsj.com/articles/apple-q2-12345",
        text=f"<html><body><article>{body}</article></body></html>",
    )
    async with httpx.AsyncClient() as client:
        scraper = WSJScraper(http=client, cookie="auth=secret")
        from datetime import UTC, datetime
        from app.models.candidate import Candidate
        c = Candidate(
            source_id="WP-1", url="https://www.wsj.com/articles/apple-q2-12345",
            title="Apple", published_at=datetime(2026, 4, 24, tzinfo=UTC),
        )
        payload = await scraper.fetch_one(c)

    assert payload.source == "wsj"
    assert payload.raw.kind == "html"
    sent_request = httpx_mock.get_request(url="https://www.wsj.com/articles/apple-q2-12345")
    assert sent_request is not None
    assert sent_request.headers.get("Cookie") == "auth=secret"


@pytest.mark.asyncio
async def test_paywall_signature_raises_cookie_expired(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://www.wsj.com/articles/blocked",
        text="<html><body>Sign In to Continue Reading</body></html>",
    )
    async with httpx.AsyncClient() as client:
        scraper = WSJScraper(http=client, cookie="x")
        from datetime import UTC, datetime
        from app.models.candidate import Candidate
        c = Candidate(
            source_id="x", url="https://www.wsj.com/articles/blocked",
            title="t", published_at=datetime(2026, 4, 24, tzinfo=UTC),
        )
        with pytest.raises(WSJCookieExpiredError):
            await scraper.fetch_one(c)


@pytest.mark.asyncio
async def test_short_response_also_raises_cookie_expired(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://www.wsj.com/articles/short",
        text="<html><body>tiny</body></html>",
    )
    async with httpx.AsyncClient() as client:
        scraper = WSJScraper(http=client, cookie="x")
        from datetime import UTC, datetime
        from app.models.candidate import Candidate
        c = Candidate(
            source_id="x", url="https://www.wsj.com/articles/short",
            title="t", published_at=datetime(2026, 4, 24, tzinfo=UTC),
        )
        with pytest.raises(WSJCookieExpiredError):
            await scraper.fetch_one(c)
```

- [ ] **Step 3: Run, expect FAIL**

```bash
cd services/api && uv run pytest tests/test_scrapers/test_wsj.py -v
```

- [ ] **Step 4: Implement `services/api/app/services/scrapers/wsj.py`**

```python
import logging
from datetime import UTC, datetime

import feedparser

from app.http_client import UA_SAFARI_MAC
from app.models.candidate import Candidate
from app.models.ingest import IngestPayload, RawHtml
from app.services.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

RSS_FEEDS = [
    "https://feeds.a.dj.com/rss/RSSWSJD.xml",
    "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
    "https://feeds.a.dj.com/rss/RSSWSJBuyside.xml",
]

_PAYWALL_MARKERS = (
    "Sign In to Continue Reading",
    "Subscribe to continue reading",
)
_MIN_HTML_LEN = 5000


class WSJCookieExpiredError(RuntimeError):
    pass


class WSJScraper(BaseScraper):
    source_name = "wsj"

    def __init__(self, http, cookie: str) -> None:
        super().__init__(http)
        self._cookie = cookie

    async def list_candidates(self, limit: int = 50) -> list[Candidate]:
        seen: dict[str, Candidate] = {}
        for feed_url in RSS_FEEDS:
            try:
                resp = await self._http.get(feed_url, timeout=15.0)
                resp.raise_for_status()
            except Exception:  # noqa: BLE001
                logger.warning("WSJ feed fetch failed", extra={"feed": feed_url})
                continue
            parsed = feedparser.parse(resp.text)
            for entry in parsed.entries[:limit]:
                url = entry.link
                if "wsj.com/articles/" not in url:
                    continue
                if url in seen:
                    continue
                published = self._parse_pubdate(entry)
                seen[url] = Candidate(
                    source_id=entry.get("id") or url,
                    url=url,
                    title=entry.get("title"),
                    published_at=published,
                )
        return list(seen.values())

    @staticmethod
    def _parse_pubdate(entry: dict) -> datetime | None:
        struct = entry.get("published_parsed") or entry.get("updated_parsed")
        if not struct:
            return None
        return datetime(*struct[:6], tzinfo=UTC)

    async def fetch_one(self, candidate: Candidate) -> IngestPayload:
        resp = await self._http.get(
            candidate.url,
            timeout=20.0,
            headers={
                "Cookie": self._cookie,
                "User-Agent": UA_SAFARI_MAC,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://www.wsj.com/",
            },
        )
        resp.raise_for_status()
        html = resp.text
        if any(m in html for m in _PAYWALL_MARKERS) or len(html) < _MIN_HTML_LEN:
            raise WSJCookieExpiredError(f"paywall or short response for {candidate.url}")
        return IngestPayload(
            source="wsj",
            source_id=candidate.source_id,
            url=candidate.url,
            fetched_at=datetime.now(UTC),
            raw=RawHtml(kind="html", html=html),
        )
```

- [ ] **Step 5: Run test, expect PASS**

```bash
cd services/api && uv run pytest tests/test_scrapers/test_wsj.py -v
```

- [ ] **Step 6: Lint, type, commit**

```bash
cd services/api && uv run ruff format . && uv run ruff check . --fix && uv run mypy app
cd /Users/farron/code/Auralee
git add services/api/app/services/scrapers/wsj.py services/api/tests/test_scrapers/test_wsj.py services/api/tests/data/wsj_feed.xml
git commit -m "feat(api): WSJ scraper with cookie + paywall detection"
```

### Task 4.5: `/cron/scrape` route + scrape orchestrator

**Files:**
- Modify: `services/api/app/services/ingest_service.py` (no change needed; we already exposed `process`)
- Create: `services/api/app/services/scrape_runner.py`
- Create: `services/api/tests/test_scrape_runner.py`
- Create: `services/api/app/routers/cron.py`
- Modify: `services/api/app/deps.py` (add scraper factory + scrape runner dep)
- Modify: `services/api/app/main.py` (wire cron router)

- [ ] **Step 1: Write failing scrape_runner test**

`services/api/tests/test_scrape_runner.py`:

```python
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.candidate import Candidate
from app.models.ingest import IngestMeta, IngestPayload, IngestResponse, RawText
from app.services.scrape_runner import run_scrape


def _candidate(i: int) -> Candidate:
    return Candidate(
        source_id=str(i), url=f"https://x/{i}",
        title=f"T{i}", published_at=datetime(2026, 4, 24, tzinfo=UTC),
    )


def _ingested_resp(article_id: str, cost: float = 0.0001) -> IngestResponse:
    return IngestResponse(
        article_id=article_id, status="ingested",
        meta=IngestMeta(
            tokens_in=10, tokens_out=5, cost_usd=cost,
            latency_ms=100, prompt_version="v1",
        ),
    )


@pytest.mark.asyncio
async def test_run_scrape_aggregates_counts_and_cost() -> None:
    scraper = MagicMock()
    scraper.source_name = "hn"
    scraper.list_candidates = AsyncMock(return_value=[_candidate(1), _candidate(2)])
    scraper.fetch_one = AsyncMock(side_effect=lambda c: IngestPayload(
        source="hn", source_id=c.source_id, url=c.url,
        fetched_at=datetime.now(UTC),
        raw=RawText(kind="text", title=c.title or "", body=c.title or ""),
    ))

    ingest = MagicMock()
    ingest.process = MagicMock(side_effect=[
        _ingested_resp("hn_1", 0.0001),
        _ingested_resp("hn_2", 0.0002),
    ])

    repo = MagicMock()
    repo.save_run = MagicMock(return_value="run-id")

    summary = await run_scrape(scraper=scraper, ingest=ingest, repo=repo)

    assert summary["ingested"] == 2
    assert summary["attempted"] == 2
    assert summary["cost_usd"] == pytest.approx(0.0003)
    saved_run = repo.save_run.call_args[0][0]
    assert saved_run.kind == "scrape"
    assert saved_run.source == "hn"


@pytest.mark.asyncio
async def test_run_scrape_records_errors_and_continues() -> None:
    scraper = MagicMock()
    scraper.source_name = "wsj"
    scraper.list_candidates = AsyncMock(return_value=[_candidate(1), _candidate(2)])

    async def fetch(c: Candidate) -> IngestPayload:
        if c.source_id == "1":
            raise RuntimeError("boom")
        return IngestPayload(
            source="wsj", source_id=c.source_id, url=c.url,
            fetched_at=datetime.now(UTC),
            raw=RawText(kind="text", title=c.title or "", body=c.title or ""),
        )

    scraper.fetch_one = AsyncMock(side_effect=fetch)
    ingest = MagicMock()
    ingest.process = MagicMock(return_value=_ingested_resp("wsj_2"))
    repo = MagicMock()

    summary = await run_scrape(scraper=scraper, ingest=ingest, repo=repo)

    assert summary["ingested"] == 1
    assert summary["errors"] == 1
    saved_run = repo.save_run.call_args[0][0]
    assert saved_run.status == "partial"


@pytest.mark.asyncio
async def test_run_scrape_skips_when_already_ingested() -> None:
    scraper = MagicMock()
    scraper.source_name = "hn"
    scraper.list_candidates = AsyncMock(return_value=[_candidate(1)])
    scraper.fetch_one = AsyncMock()
    ingest = MagicMock()
    ingest.process = MagicMock(
        return_value=IngestResponse(article_id="hn_1", status="duplicate")
    )
    repo = MagicMock()

    summary = await run_scrape(scraper=scraper, ingest=ingest, repo=repo)
    assert summary["skipped_dup"] == 1
    assert summary["ingested"] == 0
```

- [ ] **Step 2: Run, expect FAIL**

```bash
cd services/api && uv run pytest tests/test_scrape_runner.py -v
```

- [ ] **Step 3: Implement `services/api/app/services/scrape_runner.py`**

```python
import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from app.models.run import Run, RunError
from app.services.firestore_repo import FirestoreRepo
from app.services.ingest_service import IngestService
from app.services.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)


async def run_scrape(
    scraper: BaseScraper,
    ingest: IngestService,
    repo: FirestoreRepo,
    candidate_limit: int = 50,
    fetch_delay_seconds: float = 0.0,
) -> dict[str, Any]:
    run = Run(id="", kind="scrape", source=scraper.source_name, started_at=datetime.now(UTC))

    try:
        candidates = await scraper.list_candidates(limit=candidate_limit)
    except Exception as e:  # noqa: BLE001
        run.status = "failure"
        run.errors.append(RunError(stage="list_candidates", message=str(e)[:200]))
        run.finished_at = datetime.now(UTC)
        repo.save_run(run)
        return _summarize(run)

    run.articles_attempted = len(candidates)

    for c in candidates:
        try:
            payload = await scraper.fetch_one(c)
        except Exception as e:  # noqa: BLE001
            run.errors.append(
                RunError(url=c.url, stage="fetch", message=str(e)[:200])
            )
            if fetch_delay_seconds > 0:
                await asyncio.sleep(fetch_delay_seconds)
            continue

        try:
            response = ingest.process(payload)
        except Exception as e:  # noqa: BLE001
            run.errors.append(
                RunError(url=c.url, stage="ingest", message=str(e)[:200])
            )
            if fetch_delay_seconds > 0:
                await asyncio.sleep(fetch_delay_seconds)
            continue

        if response.status == "ingested":
            run.articles_ingested += 1
            if response.meta:
                run.cost_usd += response.meta.cost_usd
        elif response.status == "duplicate":
            run.articles_skipped_dup += 1

        if fetch_delay_seconds > 0:
            await asyncio.sleep(fetch_delay_seconds)

    run.finished_at = datetime.now(UTC)
    if run.errors and run.articles_ingested > 0:
        run.status = "partial"
    elif run.errors and run.articles_ingested == 0:
        run.status = "failure"
    else:
        run.status = "success"

    repo.save_run(run)
    return _summarize(run)


def _summarize(run: Run) -> dict[str, Any]:
    return {
        "kind": run.kind,
        "source": run.source,
        "status": run.status,
        "attempted": run.articles_attempted,
        "ingested": run.articles_ingested,
        "skipped_dup": run.articles_skipped_dup,
        "errors": len(run.errors),
        "cost_usd": round(run.cost_usd, 6),
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }
```

- [ ] **Step 4: Add scraper factories + cron deps to `services/api/app/deps.py`**

Append to `services/api/app/deps.py`:

```python
import httpx

from app.http_client import make_client
from app.services.scrapers.base import BaseScraper
from app.services.scrapers.hn import HNScraper
from app.services.scrapers.reuters import ReutersScraper
from app.services.scrapers.wsj import WSJScraper


@lru_cache(maxsize=1)
def get_http_client() -> httpx.AsyncClient:
    return make_client()


def get_scraper(
    source: str,
    http: Annotated[httpx.AsyncClient, Depends(get_http_client)],
    secrets: Annotated[SecretClient, Depends(get_secrets)],
) -> BaseScraper:
    if source == "hn":
        return HNScraper(http=http)
    if source == "reuters":
        return ReutersScraper(http=http)
    if source == "wsj":
        cookie = secrets.get("WSJ_COOKIE")
        return WSJScraper(http=http, cookie=cookie)
    raise HTTPException(status_code=400, detail=f"unknown source: {source}")
```

- [ ] **Step 5: Implement `services/api/app/routers/cron.py`**

```python
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from app.deps import (
    get_http_client,
    get_ingest_service,
    get_repo,
    get_secrets,
    require_admin_token,
)
from app.services.firestore_repo import FirestoreRepo
from app.services.ingest_service import IngestService
from app.services.scrape_runner import run_scrape
from app.services.scrapers.hn import HNScraper
from app.services.scrapers.reuters import ReutersScraper
from app.services.scrapers.wsj import WSJScraper
from app.services.secrets import SecretClient

router = APIRouter(
    prefix="/cron",
    tags=["cron"],
    dependencies=[Depends(require_admin_token)],
)


@router.post("/scrape")
async def cron_scrape(
    source: Annotated[Literal["hn", "reuters", "wsj"], Query()],
    http=Depends(get_http_client),
    secrets: Annotated[SecretClient, Depends(get_secrets)] = ...,  # type: ignore[assignment]
    ingest: Annotated[IngestService, Depends(get_ingest_service)] = ...,  # type: ignore[assignment]
    repo: Annotated[FirestoreRepo, Depends(get_repo)] = ...,  # type: ignore[assignment]
) -> dict:
    if source == "hn":
        scraper = HNScraper(http=http)
        delay = 0.0
    elif source == "reuters":
        scraper = ReutersScraper(http=http)
        delay = 1.0
    else:
        scraper = WSJScraper(http=http, cookie=secrets.get("WSJ_COOKIE"))
        delay = 2.0

    return await run_scrape(
        scraper=scraper,
        ingest=ingest,
        repo=repo,
        candidate_limit=30 if source == "hn" else 50,
        fetch_delay_seconds=delay,
    )
```

- [ ] **Step 6: Wire cron router in `services/api/app/main.py`**

Edit `services/api/app/main.py`:

```python
from app.routers import cron, health, ingest

# In create_app():
app.include_router(cron.router)
```

- [ ] **Step 7: Run all tests, expect PASS**

```bash
cd services/api && uv run pytest -v
```

- [ ] **Step 8: Lint, type, commit**

```bash
cd services/api && uv run ruff format . && uv run ruff check . --fix && uv run mypy app
cd /Users/farron/code/Auralee
git add services/api/app/services/scrape_runner.py services/api/tests/test_scrape_runner.py \
        services/api/app/routers/cron.py services/api/app/deps.py services/api/app/main.py
git commit -m "feat(api): /cron/scrape with HN/Reuters/WSJ orchestration"
```

**Phase 4 done.** All three scrapers and the orchestration are wired. After deploying, you can `curl POST /cron/scrape?source=hn` to ingest a real batch.

---

## Phase 5 — Prices + Judge (M3)

Goal: two more cron handlers. `/cron/refresh-prices` pulls yfinance OHLC for active tickers. `/cron/eval-judge` runs Gemini 2.5 Pro over fresh articles to score quality (M3 evaluation).

### Task 5.1: yfinance wrapper

**Files:**
- Create: `services/api/app/services/prices.py`
- Create: `services/api/tests/test_prices.py`

- [ ] **Step 1: Write failing test (monkeypatch `yf.download`)**

`services/api/tests/test_prices.py`:

```python
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pandas as pd
import pytest

from app.services.prices import refresh_prices


def _make_fake_df() -> pd.DataFrame:
    dates = pd.to_datetime(["2026-04-22", "2026-04-23", "2026-04-24"])
    return pd.DataFrame(
        {
            "Open":  [100.0, 101.0, 102.0],
            "High":  [101.0, 102.0, 103.0],
            "Low":   [ 99.0, 100.0, 101.0],
            "Close": [100.5, 101.5, 102.5],
            "Volume": [1000, 2000, 3000],
            "Adj Close": [100.5, 101.5, 102.5],
        },
        index=dates,
    )


@pytest.mark.asyncio
async def test_refresh_prices_writes_daily_ohlc_per_ticker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = MagicMock()
    repo.list_active_tickers.return_value = ["AAPL"]

    fake_df = _make_fake_df()
    # yfinance returns a single-level df for one ticker
    monkeypatch.setattr("app.services.prices._yf_download", lambda tickers, **kw: fake_df)

    summary = await refresh_prices(repo=repo)

    assert summary["refreshed"] == 1
    # 3 dates -> 3 save_daily_ohlc calls
    assert repo.save_daily_ohlc.call_count == 3
    repo.update_ticker_refreshed.assert_called_once()


@pytest.mark.asyncio
async def test_refresh_prices_noop_when_no_active_tickers() -> None:
    repo = MagicMock()
    repo.list_active_tickers.return_value = []
    summary = await refresh_prices(repo=repo)
    assert summary["status"] == "noop"
    repo.save_daily_ohlc.assert_not_called()


@pytest.mark.asyncio
async def test_refresh_prices_handles_ticker_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = MagicMock()
    repo.list_active_tickers.return_value = ["AAPL", "BOGUS"]

    fake_df = _make_fake_df()
    call_count = {"n": 0}

    def fake_download(tickers, **kw):
        call_count["n"] += 1
        # Simulate multi-ticker shape: top-level cols are tickers
        arrays = [["AAPL", "AAPL", "AAPL", "AAPL", "AAPL", "AAPL"],
                  ["Open", "High", "Low", "Close", "Volume", "Adj Close"]]
        cols = pd.MultiIndex.from_arrays(arrays)
        df = fake_df.copy()
        df.columns = cols
        # BOGUS column missing on purpose
        return df

    monkeypatch.setattr("app.services.prices._yf_download", fake_download)

    summary = await refresh_prices(repo=repo)
    # AAPL refreshed, BOGUS errored
    assert summary["refreshed"] == 1
    assert summary["errors"] == 1
```

- [ ] **Step 2: Run, expect FAIL**

```bash
cd services/api && uv run pytest tests/test_prices.py -v
```

- [ ] **Step 3: Implement `services/api/app/services/prices.py`**

```python
import logging
from datetime import UTC, datetime
from typing import Any

import pandas as pd
import yfinance as yf

from app.models.price import DailyOHLC
from app.models.run import Run, RunError
from app.services.firestore_repo import FirestoreRepo

logger = logging.getLogger(__name__)


def _yf_download(tickers: list[str], **kw: Any) -> pd.DataFrame:
    """Indirection so tests can monkeypatch."""
    return yf.download(tickers, progress=False, **kw)


def _iter_ticker_frames(
    data: pd.DataFrame, tickers: list[str]
) -> dict[str, pd.DataFrame]:
    """Normalize yf.download output (single-ticker vs multi) into ticker -> DataFrame."""
    if len(tickers) == 1:
        return {tickers[0]: data}
    result: dict[str, pd.DataFrame] = {}
    if isinstance(data.columns, pd.MultiIndex):
        # MultiIndex columns: level 0 = ticker, level 1 = field
        for t in tickers:
            if t in data.columns.get_level_values(0):
                result[t] = data[t]
    return result


async def refresh_prices(repo: FirestoreRepo) -> dict[str, Any]:
    run = Run(id="", kind="refresh-prices", started_at=datetime.now(UTC))
    tickers = repo.list_active_tickers()
    if not tickers:
        run.status = "noop"
        run.finished_at = datetime.now(UTC)
        repo.save_run(run)
        return {"status": "noop", "refreshed": 0, "errors": 0}

    try:
        data = _yf_download(
            tickers, period="1mo", group_by="ticker", auto_adjust=False, threads=True,
        )
    except Exception as e:  # noqa: BLE001
        run.status = "failure"
        run.errors.append(RunError(stage="yf.download", message=str(e)[:200]))
        run.finished_at = datetime.now(UTC)
        repo.save_run(run)
        return {"status": "failure", "refreshed": 0, "errors": 1}

    frames = _iter_ticker_frames(data, tickers)

    for ticker in tickers:
        df = frames.get(ticker)
        if df is None or df.empty:
            run.errors.append(RunError(ticker=ticker, stage="extract", message="no data"))
            continue
        try:
            df = df.dropna(subset=["Close"])
            for date_idx, row in df.iterrows():
                ohlc = DailyOHLC(
                    date=pd.Timestamp(date_idx).date().isoformat(),
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=int(row["Volume"]),
                    adj_close=float(row["Adj Close"]),
                    fetched_at=datetime.now(UTC),
                    source="yfinance",
                )
                repo.save_daily_ohlc(ticker, ohlc)
            repo.update_ticker_refreshed(ticker, datetime.now(UTC))
            run.refreshed += 1
        except Exception as e:  # noqa: BLE001
            run.errors.append(RunError(ticker=ticker, stage="write", message=str(e)[:200]))

    run.finished_at = datetime.now(UTC)
    run.status = "partial" if run.errors and run.refreshed > 0 else (
        "failure" if run.errors else "success"
    )
    repo.save_run(run)
    return {
        "status": run.status,
        "refreshed": run.refreshed,
        "errors": len(run.errors),
    }
```

- [ ] **Step 4: Run test, expect PASS**

```bash
cd services/api && uv run pytest tests/test_prices.py -v
```

- [ ] **Step 5: Lint, type, commit**

```bash
cd services/api && uv run ruff format . && uv run ruff check . --fix && uv run mypy app
cd /Users/farron/code/Auralee
git add services/api/app/services/prices.py services/api/tests/test_prices.py
git commit -m "feat(api): yfinance daily OHLC refresh"
```

### Task 5.2: Judge prompt v1

**Files:**
- Create: `services/api/app/prompts/judge_v1.py`

- [ ] **Step 1: Implement `services/api/app/prompts/judge_v1.py`**

```python
"""Judge prompt — version 1. Bump if semantics change meaningfully."""

JUDGE_PROMPT_VERSION = "v1"

JUDGE_SYSTEM_INSTRUCTION = """\
You are evaluating a structured extraction from a financial news article.

Given the article text and the extraction, rate 0-10 on overall quality, considering:
- tickers: precision (no hallucinations) and recall (no missed US-listed equities)
- sentiment: correctness for the primary subject
- summary: factual accuracy and completeness
- core_thesis: whether it captures the news angle

Respond with JSON of this shape:
{
  "score": <float 0-10>,
  "issues": [<short tag strings>],   // e.g. ["missing_ticker:TSLA", "wrong_sentiment", "hallucinated_ticker:XYZ"]
  "reasoning": <one short paragraph>
}

Be strict but fair. Score 10 only for flawless extractions. Score <=4 for material errors.
"""


def build_judge_user_message(article_url: str, clean_text: str, extraction_json: str) -> str:
    return (
        f"ARTICLE URL: {article_url}\n\n"
        f"ARTICLE TEXT:\n---\n{clean_text[:6000]}\n---\n\n"
        f"EXTRACTION (to evaluate):\n{extraction_json}\n\n"
        f"Return the evaluation JSON."
    )
```

- [ ] **Step 2: Commit**

```bash
git add services/api/app/prompts/judge_v1.py
git commit -m "feat(api): judge prompt v1"
```

### Task 5.3: Judge service (Gemini Pro)

**Files:**
- Create: `services/api/app/services/judge.py`
- Create: `services/api/tests/test_judge.py`

- [ ] **Step 1: Write failing test**

`services/api/tests/test_judge.py`:

```python
from unittest.mock import MagicMock

from app.services.judge import GeminiJudge, JudgeResult


def test_judge_parses_response_into_pydantic_eval_score() -> None:
    fake_response = MagicMock()
    fake_response.text = (
        '{"score":8.5,"issues":["missing_ticker:TSLA"],"reasoning":"Solid extraction, minor miss."}'
    )
    fake_response.usage_metadata.prompt_token_count = 6000
    fake_response.usage_metadata.candidates_token_count = 300

    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = fake_response

    judge = GeminiJudge(model="gemini-2.5-pro", _client=fake_client)
    result: JudgeResult = judge.judge(
        article_url="https://x",
        clean_text="Some text." * 400,
        extraction_json='{"tickers":["AAPL"]}',
    )

    assert result.eval_score.score == 8.5
    assert result.eval_score.issues == ["missing_ticker:TSLA"]
    assert result.eval_score.judge_model == "gemini-2.5-pro"
    assert result.cost_usd > 0
```

- [ ] **Step 2: Run, expect FAIL**

```bash
cd services/api && uv run pytest tests/test_judge.py -v
```

- [ ] **Step 3: Implement `services/api/app/services/judge.py`**

```python
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from google import genai
from google.genai import types

from app.models.article import EvalScore
from app.prompts.judge_v1 import (
    JUDGE_PROMPT_VERSION,
    JUDGE_SYSTEM_INSTRUCTION,
    build_judge_user_message,
)

# Gemini 2.5 Pro pricing (USD per 1M tokens), late-2025
_PRICE_PRO_INPUT_PER_M = 1.25
_PRICE_PRO_OUTPUT_PER_M = 5.00


def _pro_cost(tokens_in: int, tokens_out: int) -> float:
    return (
        tokens_in / 1_000_000 * _PRICE_PRO_INPUT_PER_M
        + tokens_out / 1_000_000 * _PRICE_PRO_OUTPUT_PER_M
    )


@dataclass
class JudgeResult:
    eval_score: EvalScore
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int


class GeminiJudge:
    def __init__(
        self,
        model: str = "gemini-2.5-pro",
        project: str | None = None,
        location: str = "us-east1",
        _client: Any | None = None,
    ) -> None:
        self._model = model
        self._client = _client or genai.Client(
            vertexai=True,
            project=project,
            location=location,
        )

    def judge(self, *, article_url: str, clean_text: str, extraction_json: str) -> JudgeResult:
        user_msg = build_judge_user_message(article_url, clean_text, extraction_json)
        config = types.GenerateContentConfig(
            system_instruction=JUDGE_SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            temperature=0.1,
            max_output_tokens=2048,
        )
        t0 = time.perf_counter()
        response = self._client.models.generate_content(
            model=self._model, config=config, contents=[user_msg],
        )
        latency_ms = int((time.perf_counter() - t0) * 1000)

        raw = json.loads(response.text)
        eval_score = EvalScore(
            score=float(raw["score"]),
            judge_model=self._model,
            judged_at=datetime.now(UTC),
            issues=list(raw.get("issues", [])),
            reasoning=str(raw.get("reasoning", "")),
        )

        tokens_in = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
        tokens_out = getattr(response.usage_metadata, "candidates_token_count", 0) or 0
        return JudgeResult(
            eval_score=eval_score,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=_pro_cost(tokens_in, tokens_out),
            latency_ms=latency_ms,
        )
```

- [ ] **Step 4: Run test, expect PASS**

```bash
cd services/api && uv run pytest tests/test_judge.py -v
```

- [ ] **Step 5: Lint, type, commit**

```bash
cd services/api && uv run ruff format . && uv run ruff check . --fix && uv run mypy app
cd /Users/farron/code/Auralee
git add services/api/app/services/judge.py services/api/tests/test_judge.py
git commit -m "feat(api): M3 LLM-as-Judge wrapper (Gemini Pro)"
```

### Task 5.4: Judge runner + Firestore update

**Files:**
- Modify: `services/api/app/services/firestore_repo.py` (add `list_articles_to_judge`, `update_article_eval_score`)
- Create: `services/api/app/services/judge_runner.py`

- [ ] **Step 1: Add methods to `FirestoreRepo`**

Edit `services/api/app/services/firestore_repo.py` (add methods):

```python
from app.models.article import EvalScore

# Append inside class FirestoreRepo:
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
```

- [ ] **Step 2: Implement `services/api/app/services/judge_runner.py`**

```python
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from app.models.run import Run, RunError
from app.services.firestore_repo import FirestoreRepo
from app.services.gcs import RawHtmlArchiver  # noqa: F401 — reserved for re-read when clean_text not in doc
from app.services.judge import GeminiJudge

logger = logging.getLogger(__name__)


async def run_eval_judge(
    repo: FirestoreRepo,
    judge: GeminiJudge,
    lookback_hours: int = 24,
    limit: int = 200,
) -> dict[str, Any]:
    run = Run(id="", kind="eval-judge", started_at=datetime.now(UTC))
    after = datetime.now(UTC) - timedelta(hours=lookback_hours)
    articles = repo.list_articles_needing_judge(processed_after=after, limit=limit)
    run.articles_attempted = len(articles)

    for article in articles:
        # We store `clean_text_chars` only; reuse summary + core_thesis + title as judgeable surface.
        # If you want full-fidelity judging, fetch raw HTML from GCS here — deferred for now.
        proxy_text = (
            f"TITLE: {article.title}\n\n"
            f"SUMMARY: {article.summary}\n\n"
            f"CORE_THESIS: {article.core_thesis}"
        )
        extraction_snapshot = {
            "tickers": article.tickers,
            "sentiment": article.sentiment.model_dump(),
            "entities": [e.model_dump() for e in article.entities],
            "language": article.language,
        }

        try:
            result = judge.judge(
                article_url=article.url,
                clean_text=proxy_text,
                extraction_json=str(extraction_snapshot),
            )
        except Exception as e:  # noqa: BLE001
            run.errors.append(
                RunError(url=article.url, stage="judge", message=str(e)[:200])
            )
            continue

        try:
            repo.update_article_eval_score(article.id, result.eval_score)
            run.articles_ingested += 1  # reuse counter for "judged"
            run.cost_usd += result.cost_usd
        except Exception as e:  # noqa: BLE001
            run.errors.append(
                RunError(url=article.url, stage="write", message=str(e)[:200])
            )

    run.finished_at = datetime.now(UTC)
    run.status = (
        "partial" if run.errors and run.articles_ingested > 0
        else "failure" if run.errors else "success"
    )
    repo.save_run(run)
    return {
        "status": run.status,
        "judged": run.articles_ingested,
        "errors": len(run.errors),
        "cost_usd": round(run.cost_usd, 6),
    }
```

> **Note on judgeable surface:** judging on title+summary+thesis (vs. full article body) is a deliberate PoC simplification — it halves cost and avoids re-downloading HTML from GCS. Shared-bias risk in the spec already accepts this; if M2↔M3 disagreement rate ends up anomalously high, Week 2 can upgrade the judge to read full text from GCS.

- [ ] **Step 3: Lint, type, commit**

```bash
cd services/api && uv run ruff format . && uv run ruff check . --fix && uv run mypy app
cd /Users/farron/code/Auralee
git add services/api/app/services/judge_runner.py services/api/app/services/firestore_repo.py
git commit -m "feat(api): judge runner + Firestore eval_score update"
```

### Task 5.5: `/cron/refresh-prices` and `/cron/eval-judge` routes

**Files:**
- Modify: `services/api/app/routers/cron.py`
- Modify: `services/api/app/deps.py` (add judge factory)

- [ ] **Step 1: Add judge factory to `services/api/app/deps.py`**

Append:

```python
from app.services.judge import GeminiJudge


@lru_cache(maxsize=1)
def get_judge() -> GeminiJudge:
    s = get_settings()
    return GeminiJudge(
        model=s.judge_model,
        project=s.gcp_project,
        location=s.gcp_region,
    )
```

- [ ] **Step 2: Append routes to `services/api/app/routers/cron.py`**

```python
from app.deps import get_judge
from app.services.judge import GeminiJudge
from app.services.judge_runner import run_eval_judge
from app.services.prices import refresh_prices


@router.post("/refresh-prices")
async def cron_refresh_prices(
    repo: Annotated[FirestoreRepo, Depends(get_repo)],
) -> dict:
    return await refresh_prices(repo=repo)


@router.post("/eval-judge")
async def cron_eval_judge(
    repo: Annotated[FirestoreRepo, Depends(get_repo)],
    judge: Annotated[GeminiJudge, Depends(get_judge)],
) -> dict:
    return await run_eval_judge(repo=repo, judge=judge)
```

- [ ] **Step 3: Run all tests**

```bash
cd services/api && uv run pytest -v
```

- [ ] **Step 4: Lint, type, commit**

```bash
cd services/api && uv run ruff format . && uv run ruff check . --fix && uv run mypy app
cd /Users/farron/code/Auralee
git add services/api/app/routers/cron.py services/api/app/deps.py
git commit -m "feat(api): /cron/refresh-prices and /cron/eval-judge"
```

**Phase 5 done.** Price refresh + LLM-as-Judge are wired.

---

## Phase 6 — Metrics Aggregation + Admin Endpoints

Goal: pre-compute daily metrics for `/admin/stats` and add the rest of the `/admin/*` surface.

### Task 6.1: Metrics aggregator

**Files:**
- Create: `services/api/app/services/metrics.py`
- Create: `services/api/tests/test_metrics.py`

- [ ] **Step 1: Write failing test**

`services/api/tests/test_metrics.py`:

```python
from collections import Counter
from datetime import UTC, datetime

from app.models.article import (
    Article,
    EvalScore,
    GeminiMeta,
    SanityCheck,
    Sentiment,
)
from app.services.metrics import aggregate_daily_metrics


def _article(
    *, article_id: str, source: str, tickers: list[str], sentiment_label: str,
    sanity_pass: bool, judge_score: float | None, cost: float,
) -> Article:
    now = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)
    return Article(
        id=article_id, source=source, source_id="x", url=f"https://x/{article_id}",
        title="t", published_at=now, fetched_at=now, processed_at=now,
        language="en", summary="s", tickers=tickers,
        sentiment=Sentiment(score=0.0, label=sentiment_label),  # type: ignore[arg-type]
        core_thesis="c",
        gemini_meta=GeminiMeta(
            model="gemini-2.5-flash", tokens_in=10, tokens_out=5,
            cost_usd=cost, latency_ms=200, prompt_version="v1",
        ),
        sanity_check=SanityCheck(
            ticker_precision_pass=sanity_pass, checked_at=now, flags=[],
        ),
        eval_score=None if judge_score is None else EvalScore(
            score=judge_score, judge_model="gemini-2.5-pro", judged_at=now,
            issues=[], reasoning="r",
        ),
    )


def test_aggregate_counts_by_source_and_sentiment() -> None:
    arts = [
        _article(article_id="hn_1", source="hn", tickers=["AAPL"],
                 sentiment_label="bullish", sanity_pass=True, judge_score=8.0, cost=0.0001),
        _article(article_id="hn_2", source="hn", tickers=[],
                 sentiment_label="neutral", sanity_pass=True, judge_score=7.0, cost=0.0002),
        _article(article_id="wsj_1", source="wsj", tickers=["AAPL"],
                 sentiment_label="bearish", sanity_pass=False, judge_score=9.0, cost=0.0003),
    ]
    metrics = aggregate_daily_metrics(arts, date_str="2026-04-24")
    assert metrics["articles_total"] == 3
    assert metrics["by_source"] == {"hn": 2, "wsj": 1}
    assert metrics["by_sentiment"] == {"bullish": 1, "neutral": 1, "bearish": 1}
    assert metrics["m2_precision_pass_rate"] == pytest.approx(2 / 3)
    assert metrics["m3_avg_score"] == pytest.approx((8 + 7 + 9) / 3)
    assert metrics["ticker_extraction_rate"] == pytest.approx(2 / 3)
    assert metrics["unique_tickers_seen"] == 1


def test_aggregate_disagreement_rate() -> None:
    arts = [
        # M2 fail + M3 high: judge missed the issue
        _article(article_id="a", source="hn", tickers=["FAKE"],
                 sentiment_label="neutral", sanity_pass=False, judge_score=8.5, cost=0.0001),
        # M2 pass + M3 low: judge sees something M2 doesn't
        _article(article_id="b", source="hn", tickers=["AAPL"],
                 sentiment_label="bullish", sanity_pass=True, judge_score=3.0, cost=0.0001),
        # Agreement: both pass
        _article(article_id="c", source="hn", tickers=["MSFT"],
                 sentiment_label="bullish", sanity_pass=True, judge_score=8.0, cost=0.0001),
    ]
    m = aggregate_daily_metrics(arts, date_str="2026-04-24")
    assert m["m2_m3_disagreement_count"] == 2
    assert m["m2_m3_disagreement_rate"] == pytest.approx(2 / 3)


def test_aggregate_handles_empty_articles_safely() -> None:
    m = aggregate_daily_metrics([], date_str="2026-04-24")
    assert m["articles_total"] == 0
    assert m["m2_precision_pass_rate"] == 0.0
    assert m["m3_avg_score"] == 0.0
```

Add `import pytest` at top of file.

- [ ] **Step 2: Run, expect FAIL**

```bash
cd services/api && uv run pytest tests/test_metrics.py -v
```

- [ ] **Step 3: Implement `services/api/app/services/metrics.py`**

```python
from collections import Counter
from typing import Any

from app.models.article import Article


def aggregate_daily_metrics(articles: list[Article], date_str: str) -> dict[str, Any]:
    total = len(articles)
    by_source = Counter(a.source for a in articles)
    by_sentiment = Counter(a.sentiment.label for a in articles)
    ticker_counter: Counter[str] = Counter()
    for a in articles:
        ticker_counter.update(a.tickers)

    sanity_passes = sum(
        1 for a in articles if a.sanity_check and a.sanity_check.ticker_precision_pass
    )
    sanity_judged = sum(1 for a in articles if a.sanity_check is not None)

    judged = [a for a in articles if a.eval_score is not None]
    avg_judge = (
        sum(a.eval_score.score for a in judged if a.eval_score) / len(judged)
        if judged else 0.0
    )
    avg_latency = (
        sum(a.gemini_meta.latency_ms for a in articles) / total if total else 0
    )
    cost_total = sum(a.gemini_meta.cost_usd for a in articles)

    # M2 ↔ M3 disagreement
    disagreement = 0
    cross_evaluated = 0
    for a in articles:
        if not a.sanity_check or not a.eval_score:
            continue
        cross_evaluated += 1
        if a.sanity_check.ticker_precision_pass and a.eval_score.score < 4:
            disagreement += 1
        elif (not a.sanity_check.ticker_precision_pass) and a.eval_score.score > 7:
            disagreement += 1

    return {
        "date": date_str,
        "articles_total": total,
        "by_source": dict(by_source),
        "by_sentiment": dict(by_sentiment),
        "ticker_extraction_rate": (
            sum(1 for a in articles if a.tickers) / total if total else 0.0
        ),
        "unique_tickers_seen": len(ticker_counter),
        "top_tickers": [
            {"ticker": t, "count": c} for t, c in ticker_counter.most_common(10)
        ],
        "gemini_cost_usd_total": round(cost_total, 6),
        "gemini_avg_latency_ms": int(avg_latency),
        "ingest_errors_total": 0,  # populated separately from runs
        "m2_precision_pass_rate": (
            sanity_passes / sanity_judged if sanity_judged else 0.0
        ),
        "m3_avg_score": round(avg_judge, 3),
        "m2_m3_disagreement_count": disagreement,
        "m2_m3_disagreement_rate": (
            disagreement / cross_evaluated if cross_evaluated else 0.0
        ),
    }
```

- [ ] **Step 4: Run, expect PASS**

```bash
cd services/api && uv run pytest tests/test_metrics.py -v
```

- [ ] **Step 5: Lint, type, commit**

```bash
cd services/api && uv run ruff format . && uv run ruff check . --fix && uv run mypy app
cd /Users/farron/code/Auralee
git add services/api/app/services/metrics.py services/api/tests/test_metrics.py
git commit -m "feat(api): daily metrics aggregator with M2/M3 cross-check"
```

### Task 6.2: `/cron/aggregate-metrics` route + active-ticker maintenance

**Files:**
- Modify: `services/api/app/services/firestore_repo.py` (add `set_ticker_active_window`)
- Create: `services/api/app/services/metrics_runner.py`
- Modify: `services/api/app/routers/cron.py`

- [ ] **Step 1: Add ticker activity maintenance to `FirestoreRepo`**

Edit `services/api/app/services/firestore_repo.py` (append in class):

```python
    def list_all_tickers(self) -> list[str]:
        return [d.id for d in self._client.collection("prices").stream()]

    def set_ticker_active(self, ticker: str, active: bool) -> None:
        self._client.collection("prices").document(ticker).update({"is_active": active})
```

- [ ] **Step 2: Implement `services/api/app/services/metrics_runner.py`**

```python
import logging
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from app.models.run import Run
from app.services.firestore_repo import FirestoreRepo
from app.services.metrics import aggregate_daily_metrics

logger = logging.getLogger(__name__)


async def aggregate_yesterday_metrics(repo: FirestoreRepo) -> dict[str, Any]:
    run = Run(id="", kind="aggregate-metrics", started_at=datetime.now(UTC))
    today = datetime.now(UTC).date()
    yesterday = today - timedelta(days=1)
    start = datetime.combine(yesterday, datetime.min.time(), tzinfo=UTC)
    end = datetime.combine(today, datetime.min.time(), tzinfo=UTC)

    articles = repo.list_articles_in_range(start=start, end=end)
    metrics = aggregate_daily_metrics(articles, date_str=yesterday.strftime("%Y-%m-%d"))
    repo.save_metrics(yesterday.strftime("%Y%m%d"), metrics)

    # Update is_active for tickers (30-day window)
    window_start = datetime.now(UTC) - timedelta(days=30)
    recent = repo.list_articles_in_range(start=window_start, end=datetime.now(UTC))
    seen: set[str] = set()
    for a in recent:
        seen.update(a.tickers)
    for t in repo.list_all_tickers():
        repo.set_ticker_active(t, t in seen)

    run.finished_at = datetime.now(UTC)
    run.articles_attempted = len(articles)
    repo.save_run(run)
    return {"status": "success", "metrics": metrics, "active_tickers": len(seen)}
```

- [ ] **Step 3: Add route to `services/api/app/routers/cron.py`**

```python
from app.services.metrics_runner import aggregate_yesterday_metrics


@router.post("/aggregate-metrics")
async def cron_aggregate_metrics(
    repo: Annotated[FirestoreRepo, Depends(get_repo)],
) -> dict:
    return await aggregate_yesterday_metrics(repo=repo)
```

- [ ] **Step 4: Lint, type, commit**

```bash
cd services/api && uv run ruff format . && uv run ruff check . --fix && uv run mypy app
cd /Users/farron/code/Auralee
git add services/api/app/services/firestore_repo.py services/api/app/services/metrics_runner.py services/api/app/routers/cron.py
git commit -m "feat(api): /cron/aggregate-metrics + active ticker maintenance"
```

### Task 6.3: `/admin/articles`, `/admin/runs`, `/admin/stats`, `/admin/reingest`, `/admin/healthz-detail`

**Files:**
- Create: `services/api/app/routers/admin.py`
- Modify: `services/api/app/services/firestore_repo.py` (add `list_runs`, `get_run`)
- Modify: `services/api/app/main.py` (wire admin router)

- [ ] **Step 1: Add `list_runs`/`get_run` to `FirestoreRepo`**

Edit `services/api/app/services/firestore_repo.py`:

```python
from google.cloud import firestore  # already imported above

# Append in class:
    def list_runs(
        self, kind: str | None = None, source: str | None = None, limit: int = 50
    ) -> list[Run]:
        coll = self._client.collection("runs")
        query = coll.order_by("started_at", direction=firestore.Query.DESCENDING).limit(limit)
        if kind:
            query = query.where("kind", "==", kind)
        if source:
            query = query.where("source", "==", source)
        return [Run.model_validate(d.to_dict()) for d in query.stream()]

    def get_run(self, run_id: str) -> Run | None:
        doc = self._client.collection("runs").document(run_id).get()
        return Run.model_validate(doc.to_dict()) if doc.exists else None
```

- [ ] **Step 2: Implement `services/api/app/routers/admin.py`**

```python
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from app.deps import (
    get_archiver,
    get_extractor,
    get_repo,
    get_secrets,
    require_admin_token,
)
from app.models.article import Article
from app.models.ingest import IngestPayload, IngestResponse, RawHtml
from app.services.firestore_repo import FirestoreRepo
from app.services.gcs import RawHtmlArchiver
from app.services.gemini import GeminiExtractor
from app.services.ingest_service import IngestService
from app.services.secrets import SecretClient

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin_token)],
)


@router.get("/articles", response_model=list[Article])
async def list_articles(
    repo: Annotated[FirestoreRepo, Depends(get_repo)],
    source: Annotated[Literal["hn", "reuters", "wsj"] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[Article]:
    return repo.list_recent_articles(source=source, limit=limit)


@router.get("/articles/{article_id}", response_model=Article)
async def get_article(
    article_id: Annotated[str, Path()],
    repo: Annotated[FirestoreRepo, Depends(get_repo)],
) -> Article:
    article = repo.get_article(article_id)
    if not article:
        raise HTTPException(404, detail="article not found")
    return article


@router.get("/runs")
async def list_runs(
    repo: Annotated[FirestoreRepo, Depends(get_repo)],
    kind: Annotated[str | None, Query()] = None,
    source: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[dict]:
    runs = repo.list_runs(kind=kind, source=source, limit=limit)
    return [r.model_dump(mode="json") for r in runs]


@router.get("/runs/{run_id}")
async def get_run(
    run_id: Annotated[str, Path()],
    repo: Annotated[FirestoreRepo, Depends(get_repo)],
) -> dict:
    r = repo.get_run(run_id)
    if not r:
        raise HTTPException(404, detail="run not found")
    return r.model_dump(mode="json")


@router.get("/stats")
async def get_stats(
    repo: Annotated[FirestoreRepo, Depends(get_repo)],
    date: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
) -> dict:
    target = (
        datetime.strptime(date, "%Y-%m-%d").date()
        if date else (datetime.now(UTC).date() - timedelta(days=1))
    )
    metrics = repo.get_metrics(target.strftime("%Y%m%d"))
    if not metrics:
        raise HTTPException(404, detail=f"no metrics for {target.isoformat()}")
    return metrics


@router.get("/stats/summary")
async def get_stats_summary(
    repo: Annotated[FirestoreRepo, Depends(get_repo)],
    days: Annotated[int, Query(ge=1, le=30)] = 7,
) -> dict:
    today = datetime.now(UTC).date()
    rows: list[dict] = []
    for offset in range(1, days + 1):
        d = today - timedelta(days=offset)
        m = repo.get_metrics(d.strftime("%Y%m%d"))
        if m:
            rows.append(m)
    return {"days": len(rows), "rows": rows}


@router.get("/healthz-detail")
async def healthz_detail(
    repo: Annotated[FirestoreRepo, Depends(get_repo)],
    secrets: Annotated[SecretClient, Depends(get_secrets)],
    extractor: Annotated[GeminiExtractor, Depends(get_extractor)],
) -> dict:
    out = {
        "firestore": False,
        "secrets_wsj_cookie": False,
        "vertex_ai": False,
        "vertex_model": extractor.model,
    }
    try:
        repo.list_all_tickers()
        out["firestore"] = True
    except Exception as e:  # noqa: BLE001
        out["firestore_error"] = str(e)[:200]
    try:
        v = secrets.get("WSJ_COOKIE")
        out["secrets_wsj_cookie"] = bool(v)
    except Exception as e:  # noqa: BLE001
        out["secrets_wsj_cookie_error"] = str(e)[:200]
    try:
        extractor.check_health()
        out["vertex_ai"] = True
    except Exception as e:  # noqa: BLE001
        out["vertex_ai_error"] = str(e)[:200]
    return out


@router.post("/reingest/{article_id}", response_model=IngestResponse)
async def reingest_article(
    article_id: Annotated[str, Path()],
    repo: Annotated[FirestoreRepo, Depends(get_repo)],
    extractor: Annotated[GeminiExtractor, Depends(get_extractor)],
    archiver: Annotated[RawHtmlArchiver, Depends(get_archiver)],
) -> IngestResponse:
    article = repo.get_article(article_id)
    if not article:
        raise HTTPException(404, detail="article not found")
    if not article.raw_html_gcs_uri:
        raise HTTPException(409, detail="article has no archived HTML to re-extract from")

    # Read raw HTML from GCS (use a fresh storage client; small infra)
    from google.cloud import storage
    bucket_name, _, blob_path = article.raw_html_gcs_uri.removeprefix("gs://").partition("/")
    html = storage.Client().bucket(bucket_name).blob(blob_path).download_as_text()

    # Delete existing doc so process() doesn't bail on duplicate
    # (Firestore wrapper does not expose delete; do it here intentionally.)
    repo._client.collection("articles").document(article_id).delete()  # noqa: SLF001

    payload = IngestPayload(
        source=article.source,
        source_id=article.source_id,
        url=article.url,
        fetched_at=article.fetched_at,
        raw=RawHtml(kind="html", html=html),
    )
    svc = IngestService(repo=repo, extractor=extractor, archiver=archiver)
    return svc.process(payload)
```

- [ ] **Step 3: Wire admin router into `main.py`**

Edit `services/api/app/main.py`:

```python
from app.routers import admin, cron, health, ingest

# In create_app():
app.include_router(admin.router)
```

- [ ] **Step 4: Run all tests**

```bash
cd services/api && uv run pytest -v
```

- [ ] **Step 5: Lint, type, commit**

```bash
cd services/api && uv run ruff format . && uv run ruff check . --fix && uv run mypy app
cd /Users/farron/code/Auralee
git add services/api/app/routers/admin.py services/api/app/services/firestore_repo.py services/api/app/main.py
git commit -m "feat(api): /admin/* endpoints (articles, runs, stats, healthz-detail, reingest)"
```

**Phase 6 done.** Full admin surface and metric aggregation are wired. Service is feature-complete.

---

## Phase 7 — Deploy + Schedule + Evaluate

Goal: ship the service, create Cloud Scheduler jobs, run a live smoke test, scaffold the evaluation notebook, and define the Day-7 decision procedure.

### Task 7.1: Scheduler job creation script (08)

**Files:**
- Create: `infra/scripts/08-create-scheduler-jobs.sh`
- Modify: `infra/scripts/06-grant-iam.sh` (append scheduler→runinvoker binding now that service exists)

- [ ] **Step 1: Append scheduler run.invoker binding to `06-grant-iam.sh`**

This binding needs the Cloud Run service to exist, so it's safe to add now (post-first-deploy). Append to `infra/scripts/06-grant-iam.sh`:

```bash
# Scheduler SA can invoke the Cloud Run service (run once service is deployed).
if gcloud run services describe "${SERVICE_NAME}" --region="${REGION}" >/dev/null 2>&1; then
  log "Granting run.invoker on ${SERVICE_NAME} to scheduler SA"
  gcloud run services add-iam-policy-binding "${SERVICE_NAME}" \
    --region="${REGION}" \
    --member="serviceAccount:${SCHEDULER_SA}" \
    --role=roles/run.invoker >/dev/null
else
  log "Service ${SERVICE_NAME} not yet deployed; re-run 06 after first deploy."
fi
```

- [ ] **Step 2: Write `infra/scripts/08-create-scheduler-jobs.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"

require_cmd gcloud
ensure_project

SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" \
  --region="${REGION}" --format='value(status.url)')
if [[ -z "${SERVICE_URL}" ]]; then
  echo "Cloud Run service ${SERVICE_NAME} not found; deploy first."; exit 1
fi
log "Service URL: ${SERVICE_URL}"

upsert_job() {
  local name="$1"
  local schedule="$2"
  local uri="$3"
  if gcloud scheduler jobs describe "${name}" --location="${REGION}" >/dev/null 2>&1; then
    log "Updating scheduler job ${name}"
    gcloud scheduler jobs update http "${name}" \
      --location="${REGION}" \
      --schedule="${schedule}" \
      --time-zone="Etc/UTC" \
      --http-method=POST \
      --uri="${uri}" \
      --oidc-service-account-email="${SCHEDULER_SA}" \
      --oidc-token-audience="${SERVICE_URL}" \
      --attempt-deadline=600s
  else
    log "Creating scheduler job ${name}"
    gcloud scheduler jobs create http "${name}" \
      --location="${REGION}" \
      --schedule="${schedule}" \
      --time-zone="Etc/UTC" \
      --http-method=POST \
      --uri="${uri}" \
      --oidc-service-account-email="${SCHEDULER_SA}" \
      --oidc-token-audience="${SERVICE_URL}" \
      --attempt-deadline=600s
  fi
}

upsert_job scrape-hn-hourly       "5 * * * *"  "${SERVICE_URL}/cron/scrape?source=hn"
upsert_job scrape-reuters-hourly  "15 * * * *" "${SERVICE_URL}/cron/scrape?source=reuters"
upsert_job scrape-wsj-hourly      "25 * * * *" "${SERVICE_URL}/cron/scrape?source=wsj"
upsert_job refresh-prices-daily   "0 21 * * *" "${SERVICE_URL}/cron/refresh-prices"
upsert_job aggregate-metrics-daily "55 23 * * *" "${SERVICE_URL}/cron/aggregate-metrics"
upsert_job eval-judge-daily       "30 4 * * *" "${SERVICE_URL}/cron/eval-judge"

log "Done. 6 scheduler jobs active."
log "NOTE: crons use OIDC auth. They also need X-Admin-Token header to pass our auth dep."
log "Add it via: gcloud scheduler jobs update http JOB_NAME --update-headers=X-Admin-Token=\$ADMIN_TOKEN"
```

- [ ] **Step 3: Support `X-Admin-Token` header on scheduler jobs**

Extend `upsert_job` to accept and set the header. Replace in `08-create-scheduler-jobs.sh`:

```bash
# Replace prior upsert_job function with:
upsert_job() {
  local name="$1"
  local schedule="$2"
  local uri="$3"

  local admin_token
  admin_token=$(gcloud secrets versions access latest --secret=ADMIN_TOKEN)

  if gcloud scheduler jobs describe "${name}" --location="${REGION}" >/dev/null 2>&1; then
    log "Updating scheduler job ${name}"
    gcloud scheduler jobs update http "${name}" \
      --location="${REGION}" \
      --schedule="${schedule}" \
      --time-zone="Etc/UTC" \
      --http-method=POST \
      --uri="${uri}" \
      --oidc-service-account-email="${SCHEDULER_SA}" \
      --oidc-token-audience="${SERVICE_URL}" \
      --update-headers="X-Admin-Token=${admin_token}" \
      --attempt-deadline=600s
  else
    log "Creating scheduler job ${name}"
    gcloud scheduler jobs create http "${name}" \
      --location="${REGION}" \
      --schedule="${schedule}" \
      --time-zone="Etc/UTC" \
      --http-method=POST \
      --uri="${uri}" \
      --oidc-service-account-email="${SCHEDULER_SA}" \
      --oidc-token-audience="${SERVICE_URL}" \
      --headers="X-Admin-Token=${admin_token}" \
      --attempt-deadline=600s
  fi
}
```

The ADMIN_TOKEN Secret Manager value is fetched at job-create time — if you rotate ADMIN_TOKEN, re-run the script to refresh scheduler configs.

- [ ] **Step 4: Make executable, commit**

```bash
chmod +x infra/scripts/08-create-scheduler-jobs.sh
git add infra/scripts/06-grant-iam.sh infra/scripts/08-create-scheduler-jobs.sh
git commit -m "infra: scheduler jobs + scheduler run.invoker binding"
```

### Task 7.2: Deploy Phase 1-6 work and smoke-test live service

This is a human-executed sequence. The plan records expected outcomes.

- [ ] **Step 1: Push to trigger GitHub Actions**

```bash
git push origin main
```

Expected: GHA → Cloud Build → `gcloud run deploy` completes in ~3-5 min.

- [ ] **Step 2: Get the service URL and admin token**

```bash
SERVICE_URL=$(gcloud run services describe auralee-api --region=us-east1 --format='value(status.url)')
ADMIN=$(gcloud secrets versions access latest --secret=ADMIN_TOKEN)
echo "URL:   ${SERVICE_URL}"
echo "TOKEN: ${ADMIN}"
```

- [ ] **Step 3: Smoke-test `/healthz-detail`**

```bash
AUTH=$(gcloud auth print-identity-token)
curl -s -H "Authorization: Bearer ${AUTH}" -H "X-Admin-Token: ${ADMIN}" \
  "${SERVICE_URL}/admin/healthz-detail" | jq
```

Expected: JSON with `firestore: true`, `secrets_wsj_cookie: true`, and
`vertex_ai: true`. If Vertex is false, verify the API, model region, ADC, and
runtime `roles/aiplatform.user`; if the cookie is false, refresh that secret.

- [ ] **Step 4: Smoke-test `/cron/scrape?source=hn` (manually)**

```bash
curl -s -X POST -H "Authorization: Bearer ${AUTH}" -H "X-Admin-Token: ${ADMIN}" \
  "${SERVICE_URL}/cron/scrape?source=hn" | jq
```

Expected: JSON with `ingested: N > 0`, `errors: 0 or small`, `cost_usd > 0`.
If `ingested: 0` and `attempted: 0` → HN feed fetch failed; check logs.

- [ ] **Step 5: Smoke-test one WSJ scrape**

```bash
curl -s -X POST -H "Authorization: Bearer ${AUTH}" -H "X-Admin-Token: ${ADMIN}" \
  "${SERVICE_URL}/cron/scrape?source=wsj" | jq
```

Expected: `ingested >= 1`. If errors contain `cookie_expired` or all fetches hit paywall markers, re-upload WSJ cookie (see Task 0.12 Step 4).

- [ ] **Step 6: Check one article was actually saved**

```bash
curl -s -H "Authorization: Bearer ${AUTH}" -H "X-Admin-Token: ${ADMIN}" \
  "${SERVICE_URL}/admin/articles?limit=3" | jq '.[0]'
```

Expected: a full article object with populated `summary`, `tickers`, `sanity_check`.

- [ ] **Step 7: Tag the commit as "service live"**

```bash
git tag -a phase-7-live -m "Full service deployed, end-to-end smoke test passed"
git push origin phase-7-live
```

### Task 7.3: Create Cloud Scheduler jobs

- [ ] **Step 1: Run the scheduler setup script**

```bash
./infra/scripts/06-grant-iam.sh   # re-run so scheduler→runinvoker binding applies
./infra/scripts/08-create-scheduler-jobs.sh
```

Expected: 6 scheduler jobs visible in console.

- [ ] **Step 2: Verify in GCP console**

Open https://console.cloud.google.com/cloudscheduler?project=auralee-api-server and confirm:
- 6 jobs listed
- All show `ENABLED`
- URIs point at `https://auralee-api-*.run.app/cron/...`

- [ ] **Step 3: Force-run each job once to confirm wiring**

```bash
for j in scrape-hn-hourly scrape-reuters-hourly scrape-wsj-hourly \
         refresh-prices-daily aggregate-metrics-daily eval-judge-daily; do
  echo "---- ${j} ----"
  gcloud scheduler jobs run "${j}" --location=us-east1
  sleep 5
done
```

Expected: each returns `Success` in the Cloud Scheduler console (or an error in `runs` collection you can inspect via `/admin/runs`).

### Task 7.4: Evaluation notebook scaffold

**Files:**
- Create: `notebooks/analyze.ipynb`
- Create: `notebooks/requirements.txt` (so the Notebook env is reproducible)
- Modify: `.gitignore` (ensure `.ipynb_checkpoints/` + `notebooks/outputs/` ignored)

- [ ] **Step 1: Create `notebooks/requirements.txt`**

```
google-cloud-firestore>=2.19
pandas>=2.2
plotly>=5.24
```

- [ ] **Step 2: Create `notebooks/analyze.ipynb`**

Because this is a binary-like JSON file, use the following Python snippet to generate it programmatically (keeps the plan explicit and avoids malformed JSON):

```bash
cd /Users/farron/code/Auralee
python3 - <<'PY'
import json, pathlib

nb = {
    "cells": [
        {"cell_type": "markdown", "metadata": {}, "source": [
            "# Auralee Week-1 Evaluation Notebook\n",
            "\n",
            "Run: `gcloud auth application-default login` first so Firestore client can read.\n",
        ]},
        {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": [
            "from datetime import datetime, timedelta, timezone\n",
            "from google.cloud import firestore\n",
            "import pandas as pd\n",
            "import plotly.express as px\n",
            "\n",
            "db = firestore.Client(project=\"auralee-api-server\")\n",
            "cutoff = datetime.now(timezone.utc) - timedelta(days=7)\n",
        ]},
        {"cell_type": "markdown", "metadata": {}, "source": ["## Load articles (last 7 days)\n"]},
        {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": [
            "articles = pd.DataFrame([\n",
            "    d.to_dict() for d in\n",
            "    db.collection(\"articles\").where(\"processed_at\", \">=\", cutoff.isoformat()).stream()\n",
            "])\n",
            "if not articles.empty:\n",
            "    articles[\"published_at\"] = pd.to_datetime(articles[\"published_at\"])\n",
            "    articles[\"processed_at\"] = pd.to_datetime(articles[\"processed_at\"])\n",
            "print(f\"Loaded {len(articles)} articles\")\n",
        ]},
        {"cell_type": "markdown", "metadata": {}, "source": ["## 1. Volume by source per day\n"]},
        {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": [
            "daily = articles.groupby([articles['published_at'].dt.date, 'source']).size().unstack(fill_value=0)\n",
            "px.line(daily, title='Articles/day by source').show()\n",
        ]},
        {"cell_type": "markdown", "metadata": {}, "source": ["## 2. M2 sanity + M3 judge distributions\n"]},
        {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": [
            "sanity_pass = articles['sanity_check'].apply(lambda s: s and s.get('ticker_precision_pass'))\n",
            "print(f'M2 precision rate: {sanity_pass.mean():.3f}')\n",
            "\n",
            "scores = articles['eval_score'].apply(lambda e: e.get('score') if e else None).dropna()\n",
            "print(f'M3 avg score: {scores.mean():.2f}  (n={len(scores)})')\n",
            "px.histogram(scores, nbins=20, title='M3 judge score distribution').show()\n",
        ]},
        {"cell_type": "markdown", "metadata": {}, "source": ["## 3. M2 <-> M3 disagreement\n"]},
        {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": [
            "def disagrees(row):\n",
            "    s = row.get('sanity_check'); e = row.get('eval_score')\n",
            "    if not s or not e: return False\n",
            "    if s['ticker_precision_pass'] and e['score'] < 4: return True\n",
            "    if not s['ticker_precision_pass'] and e['score'] > 7: return True\n",
            "    return False\n",
            "disagreement = articles.apply(disagrees, axis=1)\n",
            "print(f'Disagreement rate: {disagreement.mean():.3f}')\n",
        ]},
        {"cell_type": "markdown", "metadata": {}, "source": ["## 4. Sentiment distribution\n"]},
        {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": [
            "scores = articles['sentiment'].apply(lambda s: s['score'])\n",
            "px.histogram(scores.rename('sentiment_score'), color=articles['source'],\n",
            "             title='Sentiment score distribution').show()\n",
        ]},
        {"cell_type": "markdown", "metadata": {}, "source": ["## 5. Price reaction (CORE hypothesis)\n"]},
        {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": [
            "def next_day_return(row):\n",
            "    tickers = row.get('tickers') or []\n",
            "    if not tickers: return None\n",
            "    t = tickers[0]\n",
            "    d0 = row['published_at'].date()\n",
            "    d1 = d0 + timedelta(days=1)\n",
            "    try:\n",
            "        a = db.collection('prices').document(t).collection('daily').document(d0.strftime('%Y%m%d')).get()\n",
            "        b = db.collection('prices').document(t).collection('daily').document(d1.strftime('%Y%m%d')).get()\n",
            "        if a.exists and b.exists:\n",
            "            return (b.to_dict()['close'] - a.to_dict()['close']) / a.to_dict()['close']\n",
            "    except Exception:\n",
            "        pass\n",
            "    return None\n",
            "articles['ndr'] = articles.apply(next_day_return, axis=1)\n",
            "analysis = articles.dropna(subset=['ndr']).copy()\n",
            "analysis['label'] = analysis['sentiment'].apply(lambda s: s['label'])\n",
            "print(analysis.groupby('label')['ndr'].agg(['mean', 'std', 'count']))\n",
        ]},
        {"cell_type": "markdown", "metadata": {}, "source": ["## 6. Error analysis (runs collection)\n"]},
        {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": [
            "runs = pd.DataFrame([d.to_dict() for d in\n",
            "    db.collection('runs').where('started_at', '>=', cutoff.isoformat()).stream()])\n",
            "if not runs.empty:\n",
            "    runs['ok'] = runs['status'].isin(['success', 'partial'])\n",
            "    print(runs.groupby(['kind', 'source'])['ok'].agg(['count', 'mean']))\n",
        ]},
        {"cell_type": "markdown", "metadata": {}, "source": ["## 7. Cost tracking\n"]},
        {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": [
            "articles['cost'] = articles['gemini_meta'].apply(lambda m: m['cost_usd'])\n",
            "print(f\"7-day Gemini cost: ${articles['cost'].sum():.2f}, avg ${articles['cost'].mean():.4f}/article\")\n",
        ]},
        {"cell_type": "markdown", "metadata": {}, "source": ["## 8. Week-1 Scorecard\n"]},
        {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": [
            "vol = articles.groupby(articles['published_at'].dt.date).size().mean()\n",
            "m2_rate = sanity_pass.mean()\n",
            "m3_avg = scores.mean() if len(scores) else 0\n",
            "disagree_rate = disagreement.mean()\n",
            "grouped = analysis.groupby('label')['ndr'].mean() if len(analysis) else pd.Series()\n",
            "spread = (grouped.get('bullish', 0) - grouped.get('bearish', 0)) if len(grouped) else 0\n",
            "avg_cost = articles['cost'].mean()\n",
            "wsj_runs = runs[(runs['kind'] == 'scrape') & (runs['source'] == 'wsj')] if not runs.empty else pd.DataFrame()\n",
            "wsj_ok = wsj_runs['ok'].mean() if len(wsj_runs) else 0\n",
            "\n",
            "scorecard = pd.DataFrame([\n",
            "    ('volume/day',           vol,          vol > 100),\n",
            "    ('m2_precision_rate',    m2_rate,      m2_rate > 0.90),\n",
            "    ('m3_avg_score',         m3_avg,       m3_avg > 7.0),\n",
            "    ('m2_m3_disagree_rate',  disagree_rate, disagree_rate < 0.05),\n",
            "    ('price_signal_spread',  spread,       spread > 0.01),\n",
            "    ('avg_cost_per_article', avg_cost,     avg_cost < 0.01),\n",
            "    ('wsj_success_rate',     wsj_ok,       wsj_ok > 0.80),\n",
            "], columns=['metric', 'value', 'pass'])\n",
            "scorecard\n",
        ]},
    ],
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3.12"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}
pathlib.Path("notebooks/analyze.ipynb").write_text(json.dumps(nb, indent=1))
print("wrote notebooks/analyze.ipynb")
PY
```

- [ ] **Step 3: Ensure `.gitignore` excludes notebook outputs**

Verify `.gitignore` already contains `*.ipynb_checkpoints/`. Add if missing:

```bash
grep -q 'ipynb_checkpoints' .gitignore || echo '*.ipynb_checkpoints/' >> .gitignore
```

- [ ] **Step 4: Commit**

```bash
git add notebooks/
git commit -m "feat(notebooks): week-1 evaluation scaffold with scorecard"
```

### Task 7.5: Define Day-7 decision procedure (document only)

- [ ] **Step 1: Create `notebooks/DECISION.md`**

```markdown
# Week-1 Decision Procedure

Run this on Day 7 (or later) to produce the go/no-go verdict.

## Steps

1. `cd /Users/farron/code/Auralee && gcloud auth application-default login`
2. `pip install -r notebooks/requirements.txt` (or use uv venv)
3. Open `notebooks/analyze.ipynb` in Jupyter / VS Code
4. Run all cells top to bottom
5. Read the final **Scorecard** DataFrame

## Verdict

- **7/7 pass** -> Proceed to Week 2 (desktop client + user memory). Open a new spec under `docs/superpowers/specs/`.
- **5-6/7 pass** -> Iterate one more week. Investigate red rows; common culprits:
  - `volume/day` red -> HN/Reuters/WSJ scrapers partly broken; check `runs` errors.
  - `m2_precision_rate` red -> ticker dictionary missing entries; expand `app/data/tickers.json`.
  - `m3_avg_score` red -> prompt quality; bump `PROMPT_VERSION` and re-run a sample.
  - `m2_m3_disagree_rate` red -> judge quality issue; widen judge input (full GCS HTML vs. proxy text).
  - `price_signal_spread` red -> CORE HYPOTHESIS at risk; DO NOT proceed to desktop app before
    re-examining product definition.
  - `avg_cost_per_article` red -> should not happen at PoC volume; investigate token usage.
  - `wsj_success_rate` red -> cookie expired or IP blocked.
- **Metric 5 (price_signal_spread) red with others green** -> product definition needs revisiting
  before desktop app. Brainstorm again.

## After the verdict

- GREEN: write Week 2 spec via `/superpowers:brainstorming` then `/superpowers:writing-plans`.
- YELLOW: file issues on GitHub for each red metric, fix, wait another 3-7 days, re-evaluate.
- RED: revisit product vision; do not proceed to UI work.
```

- [ ] **Step 2: Commit**

```bash
git add notebooks/DECISION.md
git commit -m "docs: week-1 decision procedure"
```

### Task 7.6: Update top-level README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace top-level `README.md`**

```markdown
# Auralee

> Personal macOS-native financial Agent app. Aggregates WSJ / Reuters / Hacker News,
> extracts structured insight via Gemini, correlates news with US equity prices, and
> builds per-user reading memory via RAG.

**Status:** Phase 1 (data pipeline viability PoC). See
[docs/superpowers/specs/2026-04-24-auralee-phase1-design.md](docs/superpowers/specs/2026-04-24-auralee-phase1-design.md).

## Monorepo layout

- `services/api/` — FastAPI backend on Cloud Run
- `apps/desktop/` — Tauri desktop client (Week 2+, empty placeholder)
- `infra/scripts/` — GCP setup (bash + gcloud)
- `notebooks/` — evaluation notebook + decision procedure
- `docs/superpowers/` — specs and plans

## Phase 1 quickstart

Prereq: GCP project `auralee-api-server` exists with billing.

```bash
# One-time GCP setup
./infra/scripts/00-bootstrap.sh
./infra/scripts/01-create-service-accounts.sh
./infra/scripts/02-create-secrets.sh
./infra/scripts/03-create-buckets.sh
./infra/scripts/04-create-firestore.sh
./infra/scripts/05-create-artifact-registry.sh
./infra/scripts/06-grant-iam.sh
./infra/scripts/07-setup-wif.sh
# Then: populate WSJ_COOKIE and ADMIN_TOKEN in Secret Manager;
# add GCP_PROJECT_NUMBER to GitHub repo secrets; push to main.

# Post-deploy
./infra/scripts/06-grant-iam.sh                # re-run for scheduler→runinvoker
./infra/scripts/08-create-scheduler-jobs.sh
```

## License

See [LICENSE](LICENSE).
```

- [ ] **Step 2: Commit + push**

```bash
git add README.md
git commit -m "docs: phase-1 README"
git push origin main
```

### Task 7.7: Collect 7 days of data, then decide

This is the actual PoC experiment. Nothing to write — just let the Scheduler fire.

- [ ] **Step 1: Wait 7 days**

Monitor periodically:
- `GET /admin/stats/summary?days=N` for daily aggregates
- `GET /admin/runs?kind=scrape&source=wsj&limit=10` to watch WSJ health
- Cloud Run console for error spikes
- Budget email alerts for unexpected spend

- [ ] **Step 2: On Day 7, refresh WSJ cookie if needed**

```bash
gcloud secrets versions access latest --secret=WSJ_COOKIE >/dev/null 2>&1 || echo "cookie missing!"
# If /admin/runs shows sustained cookie_expired errors:
pbpaste | gcloud secrets versions add WSJ_COOKIE --data-file=-
# Then force a deploy refresh:
gcloud run services update auralee-api --region=us-east1 \
  --update-secrets="WSJ_COOKIE=WSJ_COOKIE:latest"
```

- [ ] **Step 3: Run the notebook**

```bash
gcloud auth application-default login
cd notebooks && jupyter lab analyze.ipynb
# Run all cells, read the Scorecard
```

- [ ] **Step 4: Follow `notebooks/DECISION.md`**

Emit the verdict. Tag the result commit:

```bash
# If GREEN:
git tag -a phase-1-green -m "Week 1 scorecard green; proceeding to Week 2"
# If YELLOW:
git tag -a phase-1-yellow -m "Week 1 partial; iterating one more week"
# If RED:
git tag -a phase-1-red -m "Week 1 red; revisiting product definition"

git push origin --tags
```

**Phase 7 done.** Service live, scheduled, observable. Day-7 produces the verdict.

---

## Appendix A — Global commands cheat sheet

```bash
# Run all tests + lint + types
cd services/api && uv run pytest -v && uv run ruff check . && uv run mypy app

# Local boot
cd services/api && uv run uvicorn app.main:app --reload --port 8080

# Force-run a scheduler job
gcloud scheduler jobs run scrape-wsj-hourly --location=us-east1

# Tail Cloud Run logs
gcloud run services logs tail auralee-api --region=us-east1

# Re-deploy without code change (e.g. after secret rotation)
gcloud run services update auralee-api --region=us-east1 \
  --update-secrets="WSJ_COOKIE=WSJ_COOKIE:latest"

# Inspect a run
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
     -H "X-Admin-Token: $(gcloud secrets versions access latest --secret=ADMIN_TOKEN)" \
     "$(gcloud run services describe auralee-api --region=us-east1 --format='value(status.url)')/admin/runs?kind=scrape&limit=5" | jq
```

## Appendix B — Environment variable matrix

| Env var | Where set | Used by |
|---|---|---|
| `GCP_PROJECT` | Cloud Run `--set-env-vars` | `app.config.Settings.gcp_project` |
| `GCP_REGION` | Cloud Run `--set-env-vars` | Vertex AI client location |
| `LOG_LEVEL` | Cloud Run `--set-env-vars` | `logging_setup.configure_logging` |
| `PROMPT_VERSION` | Cloud Run `--set-env-vars` | Reserved (current prompts hard-code) |
| `WSJ_COOKIE` | Cloud Run `--set-secrets` | `WSJScraper` via `SecretClient` |
| `ADMIN_TOKEN` | Cloud Run `--set-secrets` | `require_admin_token` dep |
| `RAW_BUCKET` | defaulted in `Settings` | `RawHtmlArchiver` |
| `GCP_PROJECT_NUMBER` | GitHub repo secret | WIF auth in `deploy.yml` |

## Appendix C — Spec coverage map

| Spec section | Implementation task |
|---|---|
| §4 Topology | Task 0.3 + 0.6..0.11 + 7.3 |
| §4.2 Monorepo layout | Task 0.1 + 0.2 |
| §5 Firestore schema | Task 1.1 + 2.3 |
| §6 /ingest contract & prompt | Task 3.1..3.5 |
| §7.1 Common scaffolding | Task 4.1 + 4.5 |
| §7.2 HN scraper | Task 4.2 |
| §7.3 Reuters scraper | Task 4.3 |
| §7.4 WSJ scraper | Task 4.4 |
| §7.5 Price fetcher | Task 5.1 + 5.5 |
| §7.6 Cloud Scheduler jobs | Task 7.1 + 7.3 |
| §7.7 /cron/eval-judge | Task 5.2..5.5 |
| §8 Dockerfile/IAM/CI | Task 0.4..0.11 + 7.1 |
| §9.1 Cost estimate | Passive — verified by `/admin/stats` |
| §9.2 Monitoring | Task 7.2 + admin endpoints |
| §9.3 Alerts | **Manual in GCP console** (budget + log-based) — note 1 |
| §9.4 Evaluation methodology | Task 1.4 (M2) + 5.2..5.5 (M3) + 6.1 (aggregation) |
| §9.5 Evaluation notebook | Task 7.4 |
| §10 Admin endpoints | Task 6.3 |
| §12 Readiness checklist | Task 0.12 prerequisites |

**Note 1:** §9.3 alerts (budget + log-based) are configured manually in the GCP console, not in code. If you want them scripted, add an `infra/scripts/09-create-alerts.sh` as a follow-up. Not blocking PoC viability.
