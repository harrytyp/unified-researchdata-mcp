# NOMAD MCP — read-only MCP server for the NOMAD API.
#
# Build context: the monorepo root (the nomad-mcp/ directory, nothing else):
#   docker build -f nomad-mcp/Dockerfile -t nomad-mcp .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY nomad-mcp/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY nomad-mcp/src /app/src
COPY nomad-mcp/pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir --no-deps -e /app

# The container runs unprivileged and writes nothing.
RUN useradd --system --uid 10001 --create-home nomad \
    && chown -R nomad:nomad /app
USER 10001

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

CMD ["python", "-m", "nomad_mcp"]
