# Auralee

> Personal macOS-native financial research agent. The current backend collects Hacker News
> and MarketWatch RSS summaries (still stored under the legacy `reuters` source label), extracts
> structured insight with Gemini on Vertex AI, and correlates news with US equity prices. The
> planned desktop app adds local-first reading memory, WSJ access, and optional read-only Charles
> Schwab portfolio context.

**Status:** Phase 1 validation hardening. A deployed pipeline is not yet considered product
validation; the next gate is a reproducible 14–30 day live-data evaluation.

## Current planning

- [Roadmap](docs/roadmap.md) — validation gates, desktop sequence, and product milestones
- [Data-source strategy](docs/data-source-strategy.md) — recommended financial and AI sources
- [Schwab integration](docs/schwab-integration.md) — read-only OAuth design and trading boundary
- [Phase 1 design](docs/superpowers/specs/2026-04-24-auralee-phase1-design.md) — original PoC scope

## Monorepo layout

- `services/api/` — FastAPI backend on Cloud Run
- `apps/desktop/` — Tauri desktop client (planned; currently an empty placeholder)
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
# Then: populate ADMIN_TOKEN in Secret Manager. WSJ_COOKIE is optional and only
# used for an explicit server-side diagnostic; the scheduled WSJ job stays paused.
# add GCP_PROJECT_NUMBER to GitHub repo secrets; push to main.

# Post-deploy
./infra/scripts/09-create-firestore-indexes.sh # create required composite indexes
./infra/scripts/06-grant-iam.sh                # re-run for scheduler->runinvoker
./infra/scripts/08-create-scheduler-jobs.sh
```

## License

See [LICENSE](LICENSE).
