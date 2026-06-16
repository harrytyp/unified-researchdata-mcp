#!/bin/bash
set -e

cd /app

# Build caches if they don't exist yet
if [ ! -f /app/data/abstracts_cache.json ]; then
    echo "[entrypoint] Building abstracts cache..."
    python src/scripts/build_abstracts_cache.py
fi

if [ ! -f /app/data/pis_cache.json ]; then
    echo "[entrypoint] Building PIs cache..."
    python src/scripts/build_pis_cache.py
fi

if [ ! -f /app/data/embeddings_cache.npz ]; then
    echo "[entrypoint] Building embeddings cache..."
    python src/scripts/build_embeddings_cache.py
fi

if [ ! -f /app/data/proposal_summary.md ]; then
    echo "[entrypoint] Extracting proposal summary..."
    python src/scripts/extract_proposal_summary.py
fi

echo "[entrypoint] Starting Streamlit app..."
exec streamlit run src/app.py
