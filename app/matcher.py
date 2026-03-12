import asyncio
import json
import logging

from app.ai_client import AIClient, parse_json_response

logger = logging.getLogger(__name__)

SCORING_PROMPT = """You are a job matching assistant. Compare this resume against the job description.

RESUME:
{resume}

JOB DESCRIPTION:
{job_description}

Return ONLY valid JSON with this exact structure:
{{
    "score": <0-100 integer>,
    "reasons": ["reason 1", "reason 2"],
    "concerns": ["concern 1"],
    "keywords": ["keyword to emphasize"]
}}

Scoring criteria:
- Skills overlap between resume and job requirements
- Seniority alignment (years of experience vs role level)
- Role relevance (how well the candidate's background fits)
- Remote compatibility if applicable
- Score 80+ = strong match, 60-79 = decent, below 60 = weak"""

BATCH_SCORING_PROMPT = """You are a job matching assistant. Compare this resume against EACH of the job descriptions below and score them independently.

RESUME:
{resume}

{jobs_block}

Return ONLY a valid JSON array with one object per job, in the same order as above. Each object must have this exact structure:
{{
    "job_index": <0-based index>,
    "score": <0-100 integer>,
    "reasons": ["reason 1", "reason 2"],
    "concerns": ["concern 1"],
    "keywords": ["keyword to emphasize"]
}}

Scoring criteria:
- Skills overlap between resume and job requirements
- Seniority alignment (years of experience vs role level)
- Role relevance (how well the candidate's background fits)
- Remote compatibility if applicable
- Score 80+ = strong match, 60-79 = decent, below 60 = weak"""


class JobMatcher:
    def __init__(self, client: AIClient, resume_text: str):
        self.client = client
        self.resume_text = resume_text

    async def score_job(self, job_description: str) -> dict:
        try:
            prompt = SCORING_PROMPT.format(
                resume=self.resume_text,
                job_description=job_description,
            )
            raw = await self.client.chat(prompt, max_tokens=1024)
            return parse_json_response(raw)
        except Exception as e:
            logger.error(f"Scoring failed: {e}")
            return {
                "score": 0,
                "reasons": [],
                "concerns": [f"Scoring error: {e}"],
                "keywords": [],
            }

    async def score_batch(self, jobs: list[dict]) -> list[dict]:
        jobs_block = "\n\n".join(
            f"--- JOB {i} ---\n{job['description']}"
            for i, job in enumerate(jobs)
        )
        prompt = BATCH_SCORING_PROMPT.format(
            resume=self.resume_text,
            jobs_block=jobs_block,
        )
        max_tokens = 512 * len(jobs)
        try:
            raw = await self.client.chat(prompt, max_tokens=max_tokens)
            parsed = self._parse_batch_response(raw, len(jobs))
            for i, result in enumerate(parsed):
                result["job_id"] = jobs[i]["id"]
            return parsed
        except Exception as e:
            logger.error(f"Batch scoring failed, falling back to individual: {e}")
            return await self._fallback_individual(jobs)

    def _parse_batch_response(self, raw: str, expected_count: int) -> list[dict]:
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            raw = raw.rsplit("```", 1)[0]
        data = json.loads(raw)
        if isinstance(data, dict) and len(data) == 1:
            data = list(data.values())[0]
        if not isinstance(data, list):
            raise ValueError(f"Expected JSON array, got {type(data)}")
        results = []
        for i in range(expected_count):
            entry = next((d for d in data if d.get("job_index") == i), None)
            if entry is None and i < len(data):
                entry = data[i]
            if entry:
                results.append({
                    "score": entry.get("score", 0),
                    "reasons": entry.get("reasons", []),
                    "concerns": entry.get("concerns", []),
                    "keywords": entry.get("keywords", []),
                })
            else:
                results.append({"score": 0, "reasons": [], "concerns": ["Missing from batch response"], "keywords": []})
        return results

    async def _fallback_individual(self, jobs: list[dict]) -> list[dict]:
        results = []
        for job in jobs:
            result = await self.score_job(job["description"])
            result["job_id"] = job["id"]
            results.append(result)
        return results

    async def batch_score(self, jobs: list[dict], delay: float = 2.0) -> list[dict]:
        results = []
        for job in jobs:
            result = await self.score_job(job["description"])
            result["job_id"] = job["id"]
            results.append(result)
            if job != jobs[-1] and delay > 0:
                await asyncio.sleep(delay)
        return results
