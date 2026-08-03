#!/bin/bash
set -e

echo "/app/plugins" > /opt/venv/lib/python3.12/site-packages/_bridge_plugins.pth 2>/dev/null

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
            NOMAD_PAT="$NOMAD_PAT" ELABFTW_API_KEY=78-ddda64df7e061243946e6055c68667bff8ee35fdce3ed00832f421d54d8cd0cbcc5f9dfbb959132df6cd78 ELABFTW_TEAM=29 python3 /app/plugins/nomad_processor.py watch 2>&1
            sleep 30
        done
    " > /tmp/tga-nomad-processor.log 2>&1 &
    echo "[startup] NOMAD TGA processor started"
fi
cd /app
exec python -m nomad.cli "$@"
