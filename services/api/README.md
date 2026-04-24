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
