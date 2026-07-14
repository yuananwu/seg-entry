FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY seg_entry ./seg_entry
COPY main.py README.md ./
RUN uv sync --frozen --no-dev

FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN useradd --create-home --uid 10001 appuser

COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv
COPY --chown=appuser:appuser seg_entry ./seg_entry
COPY --chown=appuser:appuser main.py README.md ./

USER appuser

EXPOSE 8010

CMD ["uvicorn", "seg_entry.api:app", "--host", "0.0.0.0", "--port", "8010"]
