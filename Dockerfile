# Personal Brain MCP server.
# Records are mounted read-only at /data/records; the index lives in a writable volume.
# /data/auth (OAuth database) is created here, owned by uid 10001 with mode 700, so a new
# named volume mounted there inherits that ownership and needs no preparation container.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.10 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

RUN useradd --system --uid 10001 --no-create-home brain \
    && mkdir -p /data/records /data/index /data/auth \
    && chown brain /data/index /data/auth \
    && chmod 700 /data/auth
USER brain
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

# The index is rebuilt from the records at every start (docs/adr/003-sqlite-fts5-index.md).
CMD ["personal-brain", "serve", "--transport", "http", "--host", "0.0.0.0", "--port", "8000", \
     "--records", "/data/records", "--db", "/data/index/index.db"]
