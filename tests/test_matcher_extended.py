import json

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.matcher import JobMatcher


SAMPLE_RESUME = "Senior Engineer, 10 years, AWS, Python, K8s"


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.provider = "test"
    client.base_url = "http://localhost"
    client.chat = AsyncMock()
    return client


def _make_response(score=75, reasons=None, concerns=None, keywords=None):
    return json.dumps({
        "score": score,
        "reasons": reasons or ["Good match"],
        "concerns": concerns or [],
        "keywords": keywords or ["python"],
    })


async def test_score_job_with_resume_override(mock_client):
    mock_client.chat = AsyncMock(return_value=_make_response(90))
    matcher = JobMatcher(mock_client, SAMPLE_RESUME)
    result = await matcher.score_job("DevOps role", resume_text="Custom resume text")
    assert result["score"] == 90
    prompt = mock_client.chat.call_args[0][0]
    assert "Custom resume text" in prompt
    assert SAMPLE_RESUME not in prompt


async def test_score_job_connection_error(mock_client):
    mock_client.chat = AsyncMock(side_effect=Exception("Connection refused"))
    matcher = JobMatcher(mock_client, SAMPLE_RESUME)
    result = await matcher.score_job("Some job")
    assert result is None  # Transient errors return None


async def test_score_job_circuit_breaker_error(mock_client):
    mock_client.chat = AsyncMock(side_effect=Exception("circuit breaker open"))
    matcher = JobMatcher(mock_client, SAMPLE_RESUME)
    result = await matcher.score_job("Some job")
    assert result is None  # Transient errors return None


async def test_score_job_empty_description(mock_client):
    mock_client.chat = AsyncMock(return_value=_make_response(10))
    matcher = JobMatcher(mock_client, SAMPLE_RESUME)
    result = await matcher.score_job("")
    assert "score" in result


async def test_score_batch_uses_batch_prompt(mock_client):
    batch_response = [
        {"job_index": 0, "score": 80, "reasons": ["a"], "concerns": [], "keywords": ["x"]},
        {"job_index": 1, "score": 60, "reasons": ["b"], "concerns": [], "keywords": ["y"]},
    ]
    mock_client.chat = AsyncMock(return_value=json.dumps(batch_response))
    matcher = JobMatcher(mock_client, SAMPLE_RESUME)
    jobs = [{"id": 10, "description": "job A"}, {"id": 20, "description": "job B"}]
    results = await matcher.score_batch(jobs)
    assert len(results) == 2
    assert results[0]["job_id"] == 10
    assert results[0]["score"] == 80
    assert results[1]["job_id"] == 20
    assert results[1]["score"] == 60


async def test_score_batch_fallback_on_error(mock_client):
    call_count = 0

    async def side_effect(prompt, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("batch parse failed")
        return _make_response(50)

    mock_client.chat = AsyncMock(side_effect=side_effect)
    matcher = JobMatcher(mock_client, SAMPLE_RESUME)
    jobs = [{"id": 1, "description": "job"}, {"id": 2, "description": "job2"}]
    results = await matcher.score_batch(jobs)
    assert len(results) == 2
    assert all(r["score"] == 50 for r in results)


async def test_parse_batch_response_dict_wrapper(mock_client):
    mock_client.chat = AsyncMock(return_value=json.dumps({
        "results": [
            {"job_index": 0, "score": 70, "reasons": [], "concerns": [], "keywords": []},
        ]
    }))
    matcher = JobMatcher(mock_client, SAMPLE_RESUME)
    jobs = [{"id": 1, "description": "job"}]
    results = await matcher.score_batch(jobs)
    assert results[0]["score"] == 70


async def test_parse_batch_response_missing_entry(mock_client):
    mock_client.chat = AsyncMock(return_value=json.dumps([
        {"job_index": 0, "score": 85, "reasons": [], "concerns": [], "keywords": []},
    ]))
    matcher = JobMatcher(mock_client, SAMPLE_RESUME)
    jobs = [{"id": 1, "description": "a"}, {"id": 2, "description": "b"}]
    results = await matcher.score_batch(jobs)
    assert results[0]["score"] == 85
    # Second job should get a 0-score fallback
    assert results[1]["score"] == 0


async def test_batch_score_individual_with_delay(mock_client):
    mock_client.chat = AsyncMock(return_value=_make_response(70))
    matcher = JobMatcher(mock_client, SAMPLE_RESUME)
    jobs = [{"id": 1, "description": "a"}, {"id": 2, "description": "b"}]
    results = await matcher.batch_score(jobs, delay=0)
    assert len(results) == 2
    assert mock_client.chat.call_count == 2
