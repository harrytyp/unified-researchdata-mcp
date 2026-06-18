"""Entry point for the hosted datatagger-proxy."""
import os
import uvicorn

def main():
    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("MCP_PORT", "8000"))
    uvicorn.run("datatagger_proxy.app:app", host=host, port=port, log_level="info")

if __name__ == "__main__":
    main()
