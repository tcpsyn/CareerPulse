import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.cover_letter import generate_cover_letter


@pytest.mark.asyncio
async def test_cover_letter_generation():
    mock_client = MagicMock()
    mock_client.chat = AsyncMock(return_value=json.dumps({
        "cover_letter": "Dear Hiring Manager,\n\nI am excited to apply for the Senior DevOps role at TechCorp..."
    }))

    result = await generate_cover_letter(
        client=mock_client,
        job_title="Senior DevOps Engineer",
        company="TechCorp",
        job_description="We need a DevOps engineer with K8s experience...",
        resume_text="10 years DevOps experience with Kubernetes, AWS, Terraform...",
        profile={"full_name": "John Doe", "location": "Denver, CO"},
        match_reasons=["Strong Kubernetes experience", "AWS certified"],
    )
    assert "cover_letter" in result
    assert len(result["cover_letter"]) > 0
    mock_client.chat.assert_called_once()
    prompt = mock_client.chat.call_args[0][0]
    assert "TechCorp" in prompt
    assert "DevOps" in prompt


@pytest.mark.asyncio
async def test_cover_letter_handles_ai_error():
    mock_client = MagicMock()
    mock_client.chat = AsyncMock(side_effect=Exception("API error"))

    result = await generate_cover_letter(
        client=mock_client,
        job_title="Test",
        company="Co",
        job_description="desc",
        resume_text="resume",
        profile={},
    )
    assert result["cover_letter"] == ""
