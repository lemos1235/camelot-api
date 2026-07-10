FROM ghcr.io/astral-sh/uv:python3.11-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends ghostscript \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src/ src/
RUN uv sync --frozen --no-dev

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "camelot_api.server:app", "--host", "0.0.0.0", "--port", "8000"]
