#!/bin/bash
set -e

cd /app

# Cache paths — new layout: sources/ (input) + cache/ (derived)
# Build caches only if the cache file is missing.
# Fallback: if an old flat-layout file exists, move it into cache/ first.

if [ ! -f /app/data/cache/abstracts_cache.json ]; then
    if [ -f /app/data/abstracts_cache.json ]; then
        echo "[entrypoint] Moving legacy abstracts cache..."
        mv /app/data/abstracts_cache.json /app/data/cache/abstracts_cache.json
    else
        echo "[entrypoint] Building abstracts cache..."
        python src/scripts/build_abstracts_cache.py
    fi
fi

if [ ! -f /app/data/cache/pis_cache.json ]; then
    if [ -f /app/data/pis_cache.json ]; then
        echo "[entrypoint] Moving legacy PIs cache..."
        mv /app/data/pis_cache.json /app/data/cache/pis_cache.json
    else
        echo "[entrypoint] Building PIs cache..."
        python src/scripts/build_pis_cache.py
    fi
fi

if [ ! -f /app/data/cache/embeddings_cache.npz ]; then
    if [ -f /app/data/embeddings_cache.npz ]; then
        echo "[entrypoint] Moving legacy embeddings cache..."
        mv /app/data/embeddings_cache.npz /app/data/cache/embeddings_cache.npz
    else
        echo "[entrypoint] Building embeddings cache..."
        python src/scripts/build_embeddings_cache.py
    fi
fi

if [ ! -f /app/data/cache/proposal_summary.md ]; then
    if [ -f /app/data/proposal_summary.md ]; then
        echo "[entrypoint] Moving legacy proposal summary..."
        mv /app/data/proposal_summary.md /app/data/cache/proposal_summary.md
    else
        echo "[entrypoint] Extracting proposal summary..."
        python src/scripts/extract_proposal_summary.py
    fi
fi

echo "[entrypoint] Starting Streamlit app..."
exec streamlit run src/app.py
