FROM ghcr.io/astral-sh/uv:python3.11-bookworm

# Tsinghua mirror source.
RUN sed -i 's@deb.debian.org/debian@mirrors.tuna.tsinghua.edu.cn/debian@g; \
            s@security.debian.org/debian-security@mirrors.tuna.tsinghua.edu.cn/debian-security@g' \
    /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends ghostscript \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml uv.lock ./

COPY src/ src/

RUN uv sync --frozen --no-dev

ENV UPLOAD_DIR=/data/uploads

EXPOSE 8000

CMD ["uv", "run", "camelot-api"]
