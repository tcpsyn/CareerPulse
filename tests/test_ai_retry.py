from unittest.mock import AsyncMock, patch, MagicMock

import httpx
import pytest

from app.ai_client import AIClient


def _make_response(status_code: int) -> httpx.Response:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx.Response(status_code, request=request)
    return resp


@pytest.fixture
def client():
    return AIClient("anthropic", api_key="test-key")


@pytest.mark.asyncio
async def test_retries_on_rate_limit(client):
    import anthropic

    mock_create = AsyncMock(
        side_effect=[
            anthropic.RateLimitError(
                message="rate limited",
                response=_make_response(429),
                body=None,
            ),
            anthropic.RateLimitError(
                message="rate limited",
                response=_make_response(429),
                body=None,
            ),
            MagicMock(content=[MagicMock(text="success")]),
        ]
    )

    with patch("anthropic.AsyncAnthropic") as mock_cls:
        mock_cls.return_value.messages.create = mock_create
        result = await client.chat("hello", max_tokens=10)

    assert result == "success"
    assert mock_create.call_count == 3


@pytest.mark.asyncio
async def test_retries_on_server_error(client):
    import anthropic

    mock_create = AsyncMock(
        side_effect=[
            anthropic.InternalServerError(
                message="server error",
                response=_make_response(500),
                body=None,
            ),
            MagicMock(content=[MagicMock(text="recovered")]),
        ]
    )

    with patch("anthropic.AsyncAnthropic") as mock_cls:
        mock_cls.return_value.messages.create = mock_create
        result = await client.chat("hello", max_tokens=10)

    assert result == "recovered"
    assert mock_create.call_count == 2


@pytest.mark.asyncio
async def test_retries_on_transport_error():
    ollama_client = AIClient("ollama", base_url="http://localhost:11434")

    mock_post = AsyncMock(
        side_effect=[
            httpx.ConnectError("connection refused"),
            MagicMock(
                status_code=200,
                raise_for_status=MagicMock(),
                json=MagicMock(return_value={"message": {"content": "ok"}}),
            ),
        ]
    )

    with patch("httpx.AsyncClient") as mock_http:
        mock_http.return_value.__aenter__ = AsyncMock(
            return_value=MagicMock(post=mock_post)
        )
        mock_http.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await ollama_client.chat("hello", max_tokens=10)

    assert result == "ok"
    assert mock_post.call_count == 2


@pytest.mark.asyncio
async def test_no_retry_on_auth_error(client):
    import anthropic

    mock_create = AsyncMock(
        side_effect=anthropic.AuthenticationError(
            message="invalid api key",
            response=_make_response(401),
            body=None,
        )
    )

    with patch("anthropic.AsyncAnthropic") as mock_cls:
        mock_cls.return_value.messages.create = mock_create
        with pytest.raises(anthropic.AuthenticationError):
            await client.chat("hello", max_tokens=10)

    assert mock_create.call_count == 1


@pytest.mark.asyncio
async def test_no_retry_on_bad_request(client):
    import anthropic

    mock_create = AsyncMock(
        side_effect=anthropic.BadRequestError(
            message="bad request",
            response=_make_response(400),
            body=None,
        )
    )

    with patch("anthropic.AsyncAnthropic") as mock_cls:
        mock_cls.return_value.messages.create = mock_create
        with pytest.raises(anthropic.BadRequestError):
            await client.chat("hello", max_tokens=10)

    assert mock_create.call_count == 1


@pytest.mark.asyncio
async def test_max_retries_exhausted(client):
    import anthropic

    mock_create = AsyncMock(
        side_effect=anthropic.RateLimitError(
            message="rate limited",
            response=_make_response(429),
            body=None,
        )
    )

    with patch("anthropic.AsyncAnthropic") as mock_cls:
        mock_cls.return_value.messages.create = mock_create
        with pytest.raises(anthropic.RateLimitError):
            await client.chat("hello", max_tokens=10)

    # 1 initial + 3 retries = 4 total
    assert mock_create.call_count == 4


@pytest.mark.asyncio
async def test_retries_on_httpx_status_error():
    ollama_client = AIClient("ollama", base_url="http://localhost:11434")

    request = httpx.Request("POST", "http://localhost:11434/api/chat")
    mock_post = AsyncMock(
        side_effect=[
            httpx.HTTPStatusError(
                "Server Error",
                request=request,
                response=httpx.Response(503, request=request),
            ),
            MagicMock(
                status_code=200,
                raise_for_status=MagicMock(),
                json=MagicMock(return_value={"message": {"content": "ok"}}),
            ),
        ]
    )

    with patch("httpx.AsyncClient") as mock_http:
        mock_http.return_value.__aenter__ = AsyncMock(
            return_value=MagicMock(post=mock_post)
        )
        mock_http.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await ollama_client.chat("hello", max_tokens=10)

    assert result == "ok"
    assert mock_post.call_count == 2


@pytest.mark.asyncio
async def test_no_retry_on_httpx_client_error():
    ollama_client = AIClient("ollama", base_url="http://localhost:11434")

    request = httpx.Request("POST", "http://localhost:11434/api/chat")
    mock_post = AsyncMock(
        side_effect=httpx.HTTPStatusError(
            "Forbidden",
            request=request,
            response=httpx.Response(403, request=request),
        )
    )

    with patch("httpx.AsyncClient") as mock_http:
        mock_http.return_value.__aenter__ = AsyncMock(
            return_value=MagicMock(post=mock_post)
        )
        mock_http.return_value.__aexit__ = AsyncMock(return_value=False)
        with pytest.raises(httpx.HTTPStatusError):
            await ollama_client.chat("hello", max_tokens=10)

    assert mock_post.call_count == 1
