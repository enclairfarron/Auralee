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
