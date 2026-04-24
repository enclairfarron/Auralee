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
# Then: populate GEMINI_API_KEY, WSJ_COOKIE, ADMIN_TOKEN in Secret Manager;
# add GCP_PROJECT_NUMBER to GitHub repo secrets; push to main.

# Post-deploy
./infra/scripts/06-grant-iam.sh                # re-run for scheduler->runinvoker
./infra/scripts/08-create-scheduler-jobs.sh
```

## License

See [LICENSE](LICENSE).
