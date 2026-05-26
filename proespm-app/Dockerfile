FROM python:3.13-slim-bookworm

# Install git for uv, build deps for numpy, and system libs for opencv (GUI, GL, X11)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    gcc \
    g++ \
    libxcb1 \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install uv package manager
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1

# Install proespm-py3 and streamlit in a single venv
RUN uv venv /opt/venv && \
    . /opt/venv/bin/activate && \
    uv pip install git+https://github.com/matkrin/proespm-py3 streamlit

ENV PATH="/opt/venv/bin:${PATH}" \
    VIRTUAL_ENV="/opt/venv"

# Copy the Streamlit app
COPY main.py /app/main.py
WORKDIR /app

# Streamlit needs to bind on 0.0.0.0 inside Docker
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0
ENV STREAMLIT_SERVER_PORT=8501
ENV STREAMLIT_SERVER_FILE_WATCHER_TYPE=none

EXPOSE 8501

CMD ["streamlit", "run", "main.py", "--server.port=8501"]
