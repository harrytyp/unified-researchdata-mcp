FROM python:3.11-slim

WORKDIR /app

# System dependencies for sentence-transformers / torch
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy app code from submodule root
COPY econversion/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY econversion/ .

# Create data directory for caches
RUN mkdir -p /app/data

# Streamlit config
RUN mkdir -p ~/.streamlit && \
    echo "[server]" > ~/.streamlit/config.toml && \
    echo "address = \"0.0.0.0\"" >> ~/.streamlit/config.toml && \
    echo "port = 8501" >> ~/.streamlit/config.toml && \
    echo "maxUploadSize = 10" >> ~/.streamlit/config.toml

EXPOSE 8501

COPY econversion-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
