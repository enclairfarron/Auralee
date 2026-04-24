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
