"""Tests for scoring failure handling — transient errors should not create permanent score=0 entries."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.matcher import JobMatcher


SAMPLE_RESUME = "Senior Engineer with 10 years experience in Python, AWS, Kubernetes"
SAMPLE_JOB = "Senior DevOps Engineer - Remote. Requirements: AWS, Kubernetes."


@pytest.fixture
def matcher_with_failing_client():
    """Matcher whose AI client raises on chat()."""
    mock_client = MagicMock()
    mock_client.provider = "anthropic"
    mock_client.base_url = ""
    return JobMatcher(client=mock_client, resume_text=SAMPLE_RESUME)


class TestScoreJobTransientFailures:
    """score_job should return None on transient errors, not score=0."""

    @pytest.mark.asyncio
    async def test_circuit_breaker_returns_none(self, matcher_with_failing_client):
        matcher = matcher_with_failing_client
        matcher.client.chat = AsyncMock(
            side_effect=RuntimeError("Circuit breaker open for ai:anthropic")
        )
        result = await matcher.score_job(SAMPLE_JOB)
        assert result is None

    @pytest.mark.asyncio
    async def test_connection_refused_returns_none(self, matcher_with_failing_client):
        matcher = matcher_with_failing_client
        matcher.client.chat = AsyncMock(
            side_effect=ConnectionError("Connection refused")
        )
        result = await matcher.score_job(SAMPLE_JOB)
        assert result is None

    @pytest.mark.asyncio
    async def test_rate_limit_returns_none(self, matcher_with_failing_client):
        matcher = matcher_with_failing_client
        matcher.client.chat = AsyncMock(
            side_effect=RuntimeError("Rate limit exceeded")
        )
        result = await matcher.score_job(SAMPLE_JOB)
        assert result is None

    @pytest.mark.asyncio
    async def test_generic_error_returns_none(self, matcher_with_failing_client):
        matcher = matcher_with_failing_client
        matcher.client.chat = AsyncMock(
            side_effect=RuntimeError("Some unexpected error")
        )
        result = await matcher.score_job(SAMPLE_JOB)
        assert result is None

    @pytest.mark.asyncio
    async def test_successful_score_returns_dict(self):
        mock_client = MagicMock()
        mock_client.chat = AsyncMock(return_value=json.dumps({
            "score": 85, "reasons": ["Good match"], "concerns": [], "keywords": ["python"]
        }))
        matcher = JobMatcher(client=mock_client, resume_text=SAMPLE_RESUME)
        result = await matcher.score_job(SAMPLE_JOB)
        assert result is not None
        assert result["score"] == 85


class TestFallbackIndividual:
    """_fallback_individual should skip None results and abort on consecutive failures."""

    @pytest.mark.asyncio
    async def test_skips_none_results(self):
        mock_client = MagicMock()
        call_count = 0

        async def alternating_chat(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count % 2 == 0:
                raise RuntimeError("Circuit breaker open")
            return json.dumps({
                "score": 75, "reasons": ["ok"], "concerns": [], "keywords": []
            })

        mock_client.chat = alternating_chat
        mock_client.provider = "anthropic"
        mock_client.base_url = ""
        matcher = JobMatcher(client=mock_client, resume_text=SAMPLE_RESUME)
        jobs = [
            {"id": 1, "description": "Job 1"},
            {"id": 2, "description": "Job 2"},
            {"id": 3, "description": "Job 3"},
            {"id": 4, "description": "Job 4"},
        ]
        results = await matcher._fallback_individual(jobs)
        # Only successful scores should be in results
        assert all(r["score"] > 0 for r in results)
        assert all("job_id" in r for r in results)

    @pytest.mark.asyncio
    async def test_aborts_after_3_consecutive_failures(self):
        mock_client = MagicMock()
        mock_client.chat = AsyncMock(side_effect=RuntimeError("Circuit breaker open"))
        mock_client.provider = "anthropic"
        mock_client.base_url = ""
        matcher = JobMatcher(client=mock_client, resume_text=SAMPLE_RESUME)
        jobs = [{"id": i, "description": f"Job {i}"} for i in range(10)]
        results = await matcher._fallback_individual(jobs)
        assert results == []
        # Should have stopped after 3 failures, not tried all 10
        assert mock_client.chat.call_count == 3


class TestScoreBatchFailure:
    """score_batch should return empty list when all scoring fails."""

    @pytest.mark.asyncio
    async def test_batch_failure_then_individual_failure_returns_empty(self):
        mock_client = MagicMock()
        mock_client.chat = AsyncMock(side_effect=RuntimeError("Circuit breaker open"))
        mock_client.provider = "anthropic"
        mock_client.base_url = ""
        matcher = JobMatcher(client=mock_client, resume_text=SAMPLE_RESUME)
        jobs = [{"id": i, "description": f"Job {i}"} for i in range(5)]
        results = await matcher.score_batch(jobs)
        assert results == []


class TestClearFailedScores:
    """clear_failed_scores should remove error entries so jobs can be rescored."""

    @pytest.mark.asyncio
    async def test_clears_error_scores(self, db):
        job_id = await db.insert_job(
            title="Test Job", company="TestCo", location="Remote",
            salary_min=None, salary_max=None, description="desc",
            url="https://example.com/test-clear", posted_date=None,
            application_method="url", contact_email=None,
        )
        await db.set_job_location_region(job_id, "Remote")

        # Insert a failed score
        await db.insert_score(
            job_id, 0, [], ["anthropic unavailable (too many failures, will retry after cooldown)"], []
        )

        # Job should NOT appear as unscored (it has a score row)
        unscored = await db.get_unscored_jobs(limit=10)
        assert not any(j["id"] == job_id for j in unscored)

        # Clear failed scores
        cleared = await db.clear_failed_scores()
        assert cleared >= 1

        # Now job should appear as unscored again
        unscored = await db.get_unscored_jobs(limit=10)
        assert any(j["id"] == job_id for j in unscored)

    @pytest.mark.asyncio
    async def test_does_not_clear_real_zero_scores(self, db):
        job_id = await db.insert_job(
            title="Bad Match", company="Co", location="Remote",
            salary_min=None, salary_max=None, description="desc",
            url="https://example.com/test-real-zero", posted_date=None,
            application_method="url", contact_email=None,
        )
        # Insert a real score of 0 (genuinely poor match, no error message)
        await db.insert_score(job_id, 0, [], ["No relevant experience"], [])

        cleared = await db.clear_failed_scores()
        # Real zero score should NOT be cleared
        score = await db.get_score(job_id)
        assert score is not None
        assert score["match_score"] == 0


class TestRoleMatchPersistence:
    """role_match should round-trip through insert_score/get_score."""

    @pytest.mark.asyncio
    async def test_role_match_false_persists(self, db):
        job_id = await db.insert_job(
            title="Full-Stack Dev", company="Co", location="Remote",
            salary_min=None, salary_max=None, description="desc",
            url="https://example.com/test-role-false", posted_date=None,
            application_method="url", contact_email=None,
        )
        await db.insert_score(job_id, 45, [], ["Wrong role track"], [], role_match=False)
        score = await db.get_score(job_id)
        assert score is not None
        assert score["role_match"] is False
        assert score["match_score"] == 45

    @pytest.mark.asyncio
    async def test_role_match_true_persists(self, db):
        job_id = await db.insert_job(
            title="SRE", company="Co", location="Remote",
            salary_min=None, salary_max=None, description="desc",
            url="https://example.com/test-role-true", posted_date=None,
            application_method="url", contact_email=None,
        )
        await db.insert_score(job_id, 85, ["Strong match"], [], [], role_match=True)
        score = await db.get_score(job_id)
        assert score is not None
        assert score["role_match"] is True

    @pytest.mark.asyncio
    async def test_role_match_defaults_true(self, db):
        job_id = await db.insert_job(
            title="Default", company="Co", location="Remote",
            salary_min=None, salary_max=None, description="desc",
            url="https://example.com/test-role-default", posted_date=None,
            application_method="url", contact_email=None,
        )
        # Call without role_match — should default to True
        await db.insert_score(job_id, 70, [], [], [])
        score = await db.get_score(job_id)
        assert score["role_match"] is True


@pytest.fixture
async def db():
    """Provide a test database."""
    from app.database import Database
    db = Database(":memory:")
    await db.init()
    yield db
    await db.close()
