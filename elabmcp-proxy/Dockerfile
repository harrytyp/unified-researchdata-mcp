# Dockerfile for elabmcp-proxy (multi-user auth-proxy wrapping elabrmcp)
# Build context: monorepo root (the elabR/ project, not the elabmcp-proxy dir)
#
# Build from repo root:
#   docker build -f elabmcp-proxy/Dockerfile -t elabmcp-proxy .
#
# This image contains:
#   - R + elabR + elabrmcp  (same R subprocess backend)
#   - Python + elabmcp-proxy (auth proxy frontend)

FROM rocker/r-ver:4.4.2

# ── System dependencies ──────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcurl4-gnutls-dev \
    libssl-dev \
    libxml2-dev \
    cmake \
    libmbedtls-dev \
    python3 \
    python3-pip \
    python3-venv \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/*

# ── Build environment tweaks ─────────────────────────────────────────────────
ENV MAKEFLAGS="-j1" \
    R_PARALLEL_PACKAGES=1 \
    R_DEFAULT_INTERNET_TIMEOUT=600

# ── Copy monorepo into /app ──────────────────────────────────────────────────
WORKDIR /app
COPY elabR /app

# ── Install CRAN dependencies ────────────────────────────────────────────────
RUN R -e "install.packages('remotes', repos='https://cloud.r-project.org')" \
 && R -e "install.packages(c('httr2','jsonlite','yaml','cli','rlang'), repos='https://cloud.r-project.org')"

# ── Install root elabR package ──────────────────────────────────────────────
RUN R -e "remotes::install_local('/app', dependencies = c('Depends','Imports'), upgrade = 'never')"

# ── Install ellmer and mcptools from CRAN ─────────────────────────────────
RUN R -e "install.packages(c('ellmer','mcptools'), repos='https://cloud.r-project.org')"

# ── Install elabrmcp subpackage ─────────────────────────────────────────────
RUN R -e "remotes::install_local('/app/mcp/elabrmcp', dependencies = c('Depends','Imports'), upgrade = 'never')"

# ── Install elabmcp-proxy (Python) ───────────────────────────────────────────
COPY elabmcp-proxy /elabmcp-proxy
RUN pip3 install --break-system-packages -r /elabmcp-proxy/requirements.txt \
 && pip3 install --break-system-packages -e /elabmcp-proxy

# ── OpenShift arbitrary UID compatibility ────────────────────────────────────
RUN mkdir -p /var/log/elabmcp-proxy \
 && chgrp -R 0 /app /usr/local/lib/R/site-library /elabmcp-proxy /var/log/elabmcp-proxy \
 && chmod -R g+rwX /app /usr/local/lib/R/site-library /elabmcp-proxy /var/log/elabmcp-proxy

EXPOSE 8081

CMD ["python3", "-m", "elabmcp_proxy"]
