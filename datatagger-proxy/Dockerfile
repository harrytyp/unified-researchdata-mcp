FROM python:3.11-slim

WORKDIR /app

# Copy and install the datatagger-mcp library (pure MCP, no hosting)
COPY datatagger-mcp/ /app/datatagger-mcp/
RUN pip install /app/datatagger-mcp/ --no-deps && pip install "mcp[cli]>=1.2.0" httpx>=0.28.0

# Copy and install the proxy
COPY datatagger-proxy/ /app/datatagger-proxy/
RUN pip install uvicorn fastapi starlette && pip install -e /app/datatagger-proxy/

EXPOSE 8000
ENV URL_PREFIX=/dt

CMD ["python", "-m", "datatagger_proxy"]
