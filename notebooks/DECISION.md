# Viability Decision Procedure

Run this only after P0 is complete and the pipeline has collected an uninterrupted 14–30 day
window. A deployment or a single good day is not a product-validation result.

## Before evaluation

1. Confirm the required Firestore indexes report `READY`.
2. Confirm the HN and MarketWatch scheduler jobs covered at least 80% of their hourly schedule.
3. Confirm the source mix did not change during the measured window; keep new adapters in shadow
   storage.
4. From the repository root, run `gcloud auth application-default login`.
5. Install `notebooks/requirements.txt` in a notebook environment.
6. Set `EVALUATION_DAYS` in `notebooks/analyze.ipynb` to the completed 14–30 day window, then run
   every cell top to bottom without manual data edits.

## Read the scorecard

The current scorecard has eight rows:

1. `volume/day`
2. `m2_precision_rate`
3. `m3_avg_score`
4. `m2_m3_disagree_rate`
5. `price_signal_spread`
6. `avg_cost_per_article`
7. `candidate_success_rate` — worse of HN and MarketWatch
8. `source_run_success_rate` — worse of HN and MarketWatch

`evaluable=false` is **insufficient evidence**, never a pass. WSJ is deliberately absent: its
cloud job is paused, and the residential desktop experiment is a separate milestone.

## Verdict

- **Green:** every quality, cost, and collection row is evaluable and passes; the price result has
  adequate bullish/bearish samples, confidence intervals, and a market/sector-adjusted robustness
  check. Record the decision, then start the desktop vertical slice in `docs/roadmap.md`.
- **Yellow:** the pipeline gates pass but the price evidence is inconclusive, or a metric lacks
  coverage. Extend the fixed-source collection window or reposition the product around research
  synthesis and reading memory. Do not call the point estimate a pass.
- **Red:** extraction quality or per-source delivery fails, or sufficiently powered price evidence
  contradicts the core hypothesis. Revisit the source or product definition before expanding UI.

## Diagnosis map

- `volume/day`: inspect HN/MarketWatch runs and candidate counts by source.
- `m2_precision_rate`: review ticker dictionary and false positives against archived source input.
- `m3_avg_score`: review prompt/schema failures against the immutable raw archive before changing
  `PROMPT_VERSION`.
- `m2_m3_disagree_rate`: inspect only the both-evaluated sample; do not fill missing judge results.
- `price_signal_spread`: inspect session class, missing-bar status, per-class counts, uncertainty,
  and adjusted returns. Regular-session articles require intraday data.
- `avg_cost_per_article`: inspect token use and source content scope.
- `candidate_success_rate`: inspect fetch/clean/duplicate outcomes for the worse source.
- `source_run_success_rate`: inspect scheduler coverage and zero-attempt/list-candidate failures for
  the worse source.

Write the dated verdict, window boundaries, code revision, sample sizes, coverage, and known data
loss into the project decision log before changing the experiment or beginning the next phase.
