"""Main entry point — runs the elabrmcp auth-proxy on configurable host:port."""

import argparse
import os

import uvicorn

from .app import create_app


def main():
    parser = argparse.ArgumentParser(description="elabrmcp auth-proxy")
    parser.add_argument("--host", default=os.environ.get("ELABMCP_PROXY_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("ELABMCP_PROXY_PORT", "8081")))
    args = parser.parse_args()

    app = create_app()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
