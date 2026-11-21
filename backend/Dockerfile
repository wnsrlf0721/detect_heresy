FROM node:24-bookworm-slim AS node
FROM ghcr.io/astral-sh/uv:latest AS uv

FROM python:3.12-slim-bookworm
COPY --from=uv /uv /usr/local/bin/uv
COPY --from=node /usr/local/bin/node /usr/local/bin/node

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend
ENV PATH="/app/backend/.venv/bin:$PATH" \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --locked --no-dev

COPY backend/app ./app
COPY backend/scripts ./scripts
COPY data ../data

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
