FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app/ app/

EXPOSE 8085

CMD ["uv", "run", "uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8085"]
