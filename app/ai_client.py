import json
import logging
import os

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
    before_sleep_log,
)

from app.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)

_ai_breaker = CircuitBreaker(failure_threshold=5, cooldown_seconds=300.0)

RETRYABLE_STATUS_CODES = {429, 500, 502, 503}


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRYABLE_STATUS_CODES
    if isinstance(exc, httpx.TransportError):
        return True
    try:
        import anthropic
        if isinstance(exc, anthropic.RateLimitError):
            return True
        if isinstance(exc, anthropic.InternalServerError):
            return True
    except ImportError:
        pass
    try:
        import openai
        if isinstance(exc, openai.RateLimitError):
            return True
        if isinstance(exc, openai.InternalServerError):
            return True
    except ImportError:
        pass
    return False


_ai_retry = retry(
    retry=retry_if_exception(_is_retryable),
    stop=stop_after_attempt(4),  # 1 initial + 3 retries
    wait=wait_exponential_jitter(initial=2, max=30),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)


def _resolve_ollama_url(url: str) -> str:
    """Rewrite localhost URLs to host.docker.internal when running in Docker."""
    if os.path.exists("/.dockerenv"):
        return url.replace("localhost", "host.docker.internal").replace("127.0.0.1", "host.docker.internal")
    return url


OPENAI_COMPAT_PROVIDERS = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o",
    },
    "google": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "default_model": "gemini-2.0-flash",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "anthropic/claude-sonnet-4",
    },
}

ALL_PROVIDERS = ["anthropic", "ollama", "openai", "google", "openrouter"]


class AIClient:
    """Unified async AI client supporting Anthropic, Ollama, OpenAI, Google, and OpenRouter."""

    def __init__(self, provider: str, api_key: str = "", model: str = "",
                 base_url: str = ""):
        self.provider = provider
        self.api_key = api_key
        self.model = model or self._default_model()
        self.base_url = base_url or self._default_base_url()

    def _default_model(self):
        if self.provider == "anthropic":
            return "claude-sonnet-4-20250514"
        if self.provider == "ollama":
            return "llama3"
        if self.provider in OPENAI_COMPAT_PROVIDERS:
            return OPENAI_COMPAT_PROVIDERS[self.provider]["default_model"]
        return ""

    def _default_base_url(self):
        if self.provider == "ollama":
            return "http://localhost:11434"
        if self.provider in OPENAI_COMPAT_PROVIDERS:
            return OPENAI_COMPAT_PROVIDERS[self.provider]["base_url"]
        return ""

    async def chat(self, prompt: str, max_tokens: int = 1024) -> str:
        service = f"ai:{self.provider}"
        if _ai_breaker.is_open(service):
            raise RuntimeError(f"Circuit breaker open for {service}")
        try:
            result = await self._chat_with_retry(prompt, max_tokens)
            _ai_breaker.record_success(service)
            return result
        except ValueError:
            raise
        except RuntimeError:
            raise
        except Exception:
            _ai_breaker.record_failure(service)
            raise

    @_ai_retry
    async def _chat_with_retry(self, prompt: str, max_tokens: int) -> str:
        if self.provider == "anthropic":
            return await self._anthropic_chat(prompt, max_tokens)
        elif self.provider == "ollama":
            return await self._ollama_chat(prompt, max_tokens)
        elif self.provider in OPENAI_COMPAT_PROVIDERS:
            return await self._openai_chat(prompt, max_tokens)
        else:
            raise ValueError(f"Unknown provider: {self.provider}")

    async def _anthropic_chat(self, prompt: str, max_tokens: int) -> str:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=self.api_key)
        message = await client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text

    async def _openai_chat(self, prompt: str, max_tokens: int) -> str:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        response = await client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content

    async def _ollama_chat(self, prompt: str, max_tokens: int) -> str:
        url = f"{_resolve_ollama_url(self.base_url).rstrip('/')}/api/chat"
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"num_predict": max_tokens},
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["message"]["content"]


def parse_json_response(raw: str) -> dict:
    """Strip markdown code fences and parse JSON from AI response."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        raw = raw.rsplit("```", 1)[0]
    return json.loads(raw)
