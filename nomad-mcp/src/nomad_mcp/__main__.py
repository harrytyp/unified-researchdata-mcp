"""Run the hosted NOMAD MCP server."""

import uvicorn

from .config import settings


def main() -> None:
    uvicorn.run(
        "nomad_mcp.app:app",
        host=settings.host,
        port=settings.port,
        log_level="info",
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
