FROM python:3.13-slim-bookworm

# Install git for uv tool install from git URL
# Also install build dependencies for numpy/scipy
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Install uv package manager
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install proespm-py3 from GitHub
RUN uv tool install git+https://github.com/matkrin/proespm-py3

# Install streamlit
RUN uv tool install streamlit

# Add uv tool bin directory to PATH
ENV PATH="/root/.local/bin:${PATH}"

# Copy the Streamlit app
COPY main.py /app/main.py
WORKDIR /app

# Streamlit needs to bind on 0.0.0.0 inside Docker
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0
ENV STREAMLIT_SERVER_PORT=8501
ENV STREAMLIT_SERVER_FILE_WATCHER_TYPE=none

EXPOSE 8501

CMD ["streamlit", "run", "main.py", "--server.port=8501"]
