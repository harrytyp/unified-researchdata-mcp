FROM python:3.13-slim-bookworm

# Install git for uv tool install from git URL
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install uv package manager
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install elab-app from GitHub
RUN uv tool install git+https://github.com/ffelsen/elab_app

# Add uv tool bin directory to PATH
ENV PATH="/root/.local/bin:${PATH}"

# Pre-configure default elabFTW host to TUM instance
# (users can still override this via the app's config UI)
RUN elab-app config set elab_host https://elntest.ub.tum.de/api/v2

# Streamlit needs to bind on 0.0.0.0 inside Docker
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0
ENV STREAMLIT_SERVER_PORT=8501
# Disable file watcher in container (no live reload needed)
ENV STREAMLIT_SERVER_FILE_WATCHER_TYPE=none

EXPOSE 8501

CMD ["elab-app", "start"]
