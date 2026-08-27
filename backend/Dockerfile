FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:0.11.9 /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock* README.md /app/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
COPY backend /app/backend
COPY schemas /app/schemas
COPY configs /app/configs
COPY third_party /app/third_party
COPY docs/gamse-source-map.md /app/docs/gamse-source-map.md
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/backend/src"

CMD ["sprite-api"]
