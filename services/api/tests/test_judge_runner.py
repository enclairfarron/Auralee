from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from app.services.judge_runner import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_LOOKBACK_HOURS,
    run_eval_judge,
)


@pytest.mark.asyncio
async def test_default_batch_is_bounded_and_looks_back_for_backlog() -> None:
    repo = MagicMock()
    repo.list_articles_needing_judge.return_value = []
    before = datetime.now(UTC)

    result = await run_eval_judge(repo=repo, judge=MagicMock())

    after = datetime.now(UTC)
    call = repo.list_articles_needing_judge.call_args
    assert call.kwargs["limit"] == DEFAULT_BATCH_SIZE == 20
    processed_after = call.kwargs["processed_after"]
    assert before - timedelta(hours=DEFAULT_LOOKBACK_HOURS) <= processed_after
    assert processed_after <= after - timedelta(hours=DEFAULT_LOOKBACK_HOURS)
    assert result == {"status": "success", "judged": 0, "errors": 0, "cost_usd": 0.0}
    repo.save_run.assert_called_once()
