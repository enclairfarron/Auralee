from collections import Counter
from collections.abc import Sequence
from typing import Any

from app.models.article import Article
from app.models.run import Run


def aggregate_daily_metrics(
    articles: list[Article],
    date_str: str,
    *,
    scrape_runs: Sequence[Run] = (),
) -> dict[str, Any]:
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
        sum(a.eval_score.score for a in judged if a.eval_score) / len(judged) if judged else 0.0
    )
    avg_latency = sum(a.gemini_meta.latency_ms for a in articles) / total if total else 0
    cost_total = sum(a.gemini_meta.cost_usd for a in articles)

    # M2 <-> M3 disagreement
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

    scrape_funnel = _aggregate_scrape_funnel(scrape_runs)

    return {
        "date": date_str,
        "articles_total": total,
        "by_source": dict(by_source),
        "by_sentiment": dict(by_sentiment),
        "ticker_extraction_rate": (sum(1 for a in articles if a.tickers) / total if total else 0.0),
        "unique_tickers_seen": len(ticker_counter),
        "top_tickers": [{"ticker": t, "count": c} for t, c in ticker_counter.most_common(10)],
        "gemini_cost_usd_total": round(cost_total, 6),
        "gemini_avg_latency_ms": int(avg_latency),
        "ingest_errors_total": scrape_funnel["ingest_errors_total"],
        "pipeline_errors_total": scrape_funnel["pipeline_errors_total"],
        "scrape_funnel": scrape_funnel,
        "m2_precision_pass_rate": (sanity_passes / sanity_judged if sanity_judged else 0.0),
        "m3_avg_score": round(avg_judge, 3),
        "m2_m3_disagreement_count": disagreement,
        "m2_m3_disagreement_rate": (disagreement / cross_evaluated if cross_evaluated else 0.0),
    }


def _aggregate_scrape_funnel(runs: Sequence[Run]) -> dict[str, int | bool]:
    error_stages = Counter(error.stage for run in runs for error in run.errors)
    candidates_total = sum(run.articles_attempted for run in runs)
    ingested_total = sum(run.articles_ingested for run in runs)
    duplicates_total = sum(run.articles_skipped_dup for run in runs)
    skipped_short_total = sum(run.articles_skipped_short for run in runs)
    fetch_errors_total = error_stages["fetch"]
    ingest_errors_total = error_stages["ingest"]
    classified_total = (
        ingested_total
        + duplicates_total
        + skipped_short_total
        + fetch_errors_total
        + ingest_errors_total
    )
    outcome_delta = candidates_total - classified_total
    unclassified_total = max(outcome_delta, 0)
    overclassified_total = max(-outcome_delta, 0)
    counts_complete = all(run.outcome_counts_complete for run in runs)

    return {
        "runs_total": len(runs),
        "runs_failed_total": sum(run.status == "failure" for run in runs),
        "candidates_total": candidates_total,
        "ingested_total": ingested_total,
        "duplicates_total": duplicates_total,
        "skipped_short_total": skipped_short_total,
        "fetch_errors_total": fetch_errors_total,
        "ingest_errors_total": ingest_errors_total,
        "list_errors_total": error_stages["list_candidates"],
        "pipeline_errors_total": sum(error_stages.values()),
        "unclassified_total": unclassified_total,
        "overclassified_total": overclassified_total,
        "outcome_counts_complete": counts_complete and outcome_delta == 0,
    }
