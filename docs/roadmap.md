# Auralee Roadmap

**Updated:** 2026-07-21
**Current stage:** Phase 1 validation hardening
**Next decision:** whether the data and extraction pipeline is reliable enough to justify a desktop MVP

## Guiding rule

Do not treat a successful deployment as product validation. Phase 2 starts only after the
evaluation pipeline produces a reproducible scorecard from real data and the result has been
recorded with its sample size and coverage.

## P0 — Restore a trustworthy validation baseline

Target: 2–4 engineering days.

- Fix the evaluation notebook and add empty/partial-data safeguards.
- Preserve source `published_at` separately from `fetched_at` throughout ingestion.
- Use a New York session-aware daily-bar protocol; exclude regular-session articles until
  intraday bars are available.
- Report evaluated sample counts and coverage beside every pass/fail metric.
- Archive the exact permitted HTML or RSS text sent to extraction so quality can be audited.
- Remove the obsolete Gemini API-key dependency after the Vertex AI migration.
- Declare the runtime service account's Vertex AI role in the infrastructure scripts.
- Create the committed Firestore indexes and wait until every index reports `READY` before
  relying on admin queries.
- Generate `ADMIN_TOKEN` without a trailing newline and rotate any older newline-bearing value.
- Verify the deployed Cloud Run service, Scheduler jobs, recent runs, data volume, and cost.

### P0 exit criteria

- Unit tests, Ruff, and strict mypy pass.
- The notebook executes top-to-bottom against an empty fixture and a representative fixture.
- A live-data run produces all scorecard values without manual cell edits.
- Each metric includes its numerator/denominator or effective sample count.
- `infra/scripts/09-create-firestore-indexes.sh` completes and the index list reports `READY`.

## P1 — Run the viability experiment

Target: 14–30 calendar days of collection after P0.

- Collect Hacker News and MarketWatch continuously.
- Run extraction, price refresh, judge, and aggregation jobs on schedule.
- Evaluate extraction quality against archived source text, not generated summaries alone.
- Expand the ticker universe beyond the current small static dictionary.
- Segment results by source, content length, ticker count, and publication session.
- Add confidence intervals to the bullish-minus-bearish return spread.
- Replace the conservative weekday-only price proxy with an official NYSE session calendar and
  keep `missing_price` distinct from exchange holidays/closures.
- Add market- or sector-adjusted returns; raw close-to-close returns alone are not a product gate.
- Record data loss explicitly: short content, missing prices, missing judge results, and job errors.
- Freeze the P1 source mix. Run proposed SEC/AI adapters in isolated shadow storage so they do
  not change the measured baseline mid-window.

### Source naming migration

Reuters RSS is no longer the implementation behind the `reuters` source value; MarketWatch is.
New writes should eventually use `marketwatch`, while reads must remain compatible with legacy
`reuters` documents until a one-time Firestore migration is completed. Scheduler job renaming
must be coordinated with that migration so the old and new jobs do not run concurrently.

### WSJ boundary

Server-side WSJ article fetching is not part of the P1 collection baseline because datacenter IPs
are blocked. The scheduler setup script pauses the old WSJ job if it exists, and WSJ is not a P1
scorecard metric. WSJ validation moves to a small desktop-side spike that keeps subscription
cookies on the user's machine and uploads only the minimum content required by the backend.

### P1 decision gate

The revised scorecard covers volume, extraction quality, evaluator agreement, price signal, cost,
and HN/MarketWatch collection reliability. A metric cannot pass without sufficient coverage. In
particular, the price-signal metric must report per-class sample counts and uncertainty; a point
estimate above 1% from a small sample is not a green result.

- **Green:** extraction quality and operational reliability pass, and the price signal is stable
  enough to justify the current product hypothesis.
- **Yellow:** pipeline quality passes but price evidence is inconclusive; extend collection or
  reposition the product around research synthesis and reading memory.
- **Red:** extraction/source reliability fails or the price hypothesis is contradicted; revisit
  sources and product definition before building the full UI.

## P2 — Desktop vertical slice

Start only after the P1 decision is recorded. Build one complete user journey:

1. Configure the local WSJ session without sending the cookie to the server.
2. Fetch and clean one article from the residential network.
3. Submit content for extraction and persist the result.
4. Show a feed and article detail view.
5. Record read, save, and feedback events.
6. Retrieve related prior reading for a simple "what have I seen before?" experience.

The Schwab portal/OAuth feasibility spike can run in parallel, but implement portfolio sync only
after that vertical slice is stable. The [Schwab integration plan](schwab-integration.md) covers
OAuth linking, protected local storage, position/transaction sync, and portfolio-aware ranking.
Trading remains a separate approval gate.

Authentication, per-user data isolation, macOS signing/notarization, and a privacy review are part
of this milestone. Knowledge graphs, complex autonomous agents, and Bloomberg ingestion are not.

## P3 — Product hardening

- Operational dashboards, alerts, retries, quotas, and cost limits.
- Source adapters with explicit provenance and content-retention policy.
- Signed releases, auto-update, crash reporting, and support diagnostics.
- Multi-user invitation flow and deletion/export controls. Invited users get no Schwab linking
  until a commercial integration is approved.
- Split the Cloud Run monolith only when measured load or failure isolation requires it.
