#!/bin/bash
set -e

echo "/app/plugins" > /opt/venv/lib/python3.12/site-packages/_bridge_plugins.pth 2>/dev/null

# Ensure instrument_data plugin entry_points are registered (survives container recreates)
SP_DIR=/opt/venv/lib/python3.12/site-packages
DIST=$SP_DIR/instrument_data-0.1.0.dist-info
if [ ! -f "$DIST/entry_points.txt" ]; then
    mkdir -p "$DIST"
    printf '[nomad.plugin]
instrument-schema = instrument_data.entrypoint:instrument_schema
tga-parser = instrument_data.entrypoint:tga_parser_entry_point
' > "$DIST/entry_points.txt"
    printf 'Metadata-Version: 2.1
Name: instrument-data
Version: 0.1.0
' > "$DIST/METADATA"
    printf '
' > "$DIST/RECORD"
    echo "[startup] instrument_data entry_points registered"
fi


python3 << "INNER"
import sys; sys.path.insert(0, "/app/plugins")
from instrument_data.entrypoint import instrument_schema
p = instrument_schema.load()
p.init_metainfo()
INNER
export NOMAD_CONFIG=/app/nomad.yaml
if [ -f /app/plugins/nomad_processor.py ]; then
    nohup bash -c "
        while true; do
            NOMAD_PAT="$NOMAD_PAT" ELABFTW_API_KEY="$ELABFTW_API_KEY" ELABFTW_TEAM="$ELABFTW_TEAM" python3 /app/plugins/nomad_processor.py watch 2>&1
            sleep 30
        done
    " > /tmp/tga-nomad-processor.log 2>&1 &
    echo "[startup] NOMAD TGA processor started"
fi
cd /app

# Admin list patch: admins see all uploads in GET /uploads (file patch)
bash /app/plugins/patch_uploads_admin.sh

exec python -m nomad.cli "$@"
