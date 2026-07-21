# auralee-api

Phase 1 backend service. See [/docs/superpowers/specs/2026-04-24-auralee-phase1-design.md](../../docs/superpowers/specs/2026-04-24-auralee-phase1-design.md).

## Local development

```bash
cd services/api
uv sync
uv run uvicorn app.main:app --reload --port 8080
```

Health check: `curl http://localhost:8080/health`

Gemini calls use Vertex AI with Application Default Credentials. Set
`GCP_PROJECT` and `GCP_REGION`; no Gemini API key is required. The runtime
service account needs `roles/aiplatform.user`.

## Tests

```bash
uv run pytest
uv run ruff check .
uv run mypy app
```

## Deployment

Push to `main` triggers GitHub Actions which builds the image via Cloud
Build and deploys to Cloud Run in `us-east1`. See
`.github/workflows/deploy.yml` for the pipeline.
