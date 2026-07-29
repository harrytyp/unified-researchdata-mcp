#!/bin/bash
# =============================================================================
# econversion-NOMAD: One-click Setup
# =============================================================================
# Run this on a NOMAD Oasis server to install the elabFTW bridge plugin.
# Uses the OFFICIAL NOMAD image — no custom Docker build needed.
# Official updates work via: docker compose pull && docker compose up -d
#
# Usage:
#   git clone https://github.com/harrytyp/econversion-nomad.git
#   cd econversion-nomad && bash setup.sh
# =============================================================================

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
err()   { echo -e "${RED}[✗]${NC} $1"; }

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
DISTRO_DIR="${NOMAD_DISTRO_DIR:-$HOME/nomad-distro-template}"

echo "=== econversion-NOMAD Setup ==="
echo ""

# Check dependencies
for cmd in docker git python3; do
    if ! command -v $cmd &>/dev/null; then
        err "$cmd is required"
        exit 1
    fi
done

# ---- Step 1: Clone/pull nomad-distro-template ---------------------------
if [ ! -d "$DISTRO_DIR" ]; then
    git clone https://github.com/FAIRmat-NFDI/nomad-distro-template.git "$DISTRO_DIR"
    info "nomad-distro-template cloned"
else
    warn "Updating nomad-distro-template..."
    cd "$DISTRO_DIR" && git pull --ff-only 2>/dev/null && info "Updated" || warn "Could not update (local changes?)"
fi

cd "$DISTRO_DIR"

# ---- Step 2: Copy bridge plugin files ------------------------------------
mkdir -p plugins
cp -r "$REPO_DIR/plugins/three_way_sync" plugins/
cp -r "$REPO_DIR/plugins/three_way_nomad_bridge.egg-info" plugins/ 2>/dev/null || true
cp "$REPO_DIR/plugins/startup.sh" plugins/ && chmod +x plugins/startup.sh
cp "$REPO_DIR/docs/elabftw-integration/user-guide.html" plugins/three_way_sync/ 2>/dev/null || true

# Pre-download the FAIRmat elabFTW base plugin (so no git needed at startup)
warn "Downloading FAIRmat elabFTW plugin..."
curl -sL -o plugins/nomad-external-eln-integrations.tar.gz \
  "https://github.com/FAIRmat-NFDI/nomad-external-eln-integrations/archive/master.tar.gz"
info "FAIRmat plugin downloaded"

info "Bridge plugin files copied"

# ---- Step 3: Patch docker-compose.yaml ------------------------------------
warn "Patching docker-compose.yaml..."
python3 "$REPO_DIR/scripts/patch-nomad-distro.py" "$DISTRO_DIR"
info "docker-compose.yaml patched"

# ---- Step 4: Pull latest official image ----------------------------------
warn "Pulling latest official NOMAD image..."
docker compose pull app north worker 2>&1 | tail -3
info "Official image up to date"

# ---- Step 5: Restart services --------------------------------------------
warn "Restarting NOMAD services..."
docker compose up -d app north worker 2>&1 | tail -3
info "Services restarted"

# ---- Step 6: Reload nginx ------------------------------------------------
sleep 10
docker exec nomad_oasis_proxy nginx -s reload 2>/dev/null || true

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Official NOMAD image used — updates work via:"
echo "  cd ~/nomad-distro-template && docker compose pull && docker compose up -d"
echo ""
echo "After logging into NOMAD, CREATE FROM SCHEMA should show:"
echo "  - elabFTW Settings (set your API key once)"
echo "  - elabFTW Linked Entry (link experiments/items)"
echo ""
echo "User guide: https://researchmcp.duckdns.org/nomad-oasis/docs/elabftw/user-guide.html"
