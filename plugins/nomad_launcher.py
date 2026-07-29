#!/usr/bin/env python3
"""NOMAD launcher with _plugins cleanup and __main__ guard."""
import os
import sys

if __name__ == "__main__":
    sys.path.insert(0, "/app/plugins")

    # Clean stale _plugins entries
    from nomad.config import _plugins
    if _plugins:
        opts = _plugins.get("entry_points", {}).get("options", {})
        for k in list(opts.keys()):
            if k.startswith("example_uploads/"):
                del opts[k]

    # Ensure .nomad_pat exists
    if not os.path.exists("/app/.nomad_pat"):
        for src in ["/app/plugins/.nomad_pat"]:
            if os.path.exists(src):
                import shutil
                shutil.copy(src, "/app/.nomad_pat")
                os.chmod("/app/.nomad_pat", 0o600)

    # Run NOMAD CLI
    from nomad.cli.cli import run_cli
    run_cli()
