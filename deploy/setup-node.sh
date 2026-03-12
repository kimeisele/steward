#!/usr/bin/env bash
# Setup a new Steward federation node.
# Usage: sudo bash deploy/setup-node.sh [FEDERATION_WIKI_REPO_URL]
#
# Example:
#   sudo bash deploy/setup-node.sh git@github.com:kimeisele/steward.wiki.git

set -euo pipefail

FEDERATION_REPO="${1:-}"
STEWARD_HOME="/opt/steward"
WORKSPACE="${STEWARD_HOME}/workspace"
FEDERATION_DIR="${STEWARD_HOME}/federation"
VENV="${STEWARD_HOME}/venv"

echo "=== Steward Node Setup ==="

# 1. Create steward user (if not exists)
if ! id -u steward &>/dev/null; then
    useradd --system --home-dir "$STEWARD_HOME" --shell /bin/bash steward
    echo "Created user: steward"
fi

# 2. Create directory structure
mkdir -p "$STEWARD_HOME" "$WORKSPACE" "$FEDERATION_DIR"
chown -R steward:steward "$STEWARD_HOME"

# 3. Clone or update the steward repo
if [ ! -d "${WORKSPACE}/.git" ]; then
    echo "Clone the steward workspace repo into ${WORKSPACE}"
    echo "  git clone <your-repo> ${WORKSPACE}"
fi

# 4. Setup Python virtualenv
if [ ! -d "$VENV" ]; then
    python3 -m venv "$VENV"
    echo "Created virtualenv: ${VENV}"
fi
"${VENV}/bin/pip" install --upgrade pip
"${VENV}/bin/pip" install -e "${WORKSPACE}[providers,dev]"
echo "Installed steward-agent into virtualenv"

# 5. Clone federation wiki repo (if provided)
if [ -n "$FEDERATION_REPO" ]; then
    if [ ! -d "${FEDERATION_DIR}/.git" ]; then
        sudo -u steward git clone "$FEDERATION_REPO" "$FEDERATION_DIR"
        echo "Cloned federation repo: ${FEDERATION_REPO}"
    else
        sudo -u steward git -C "$FEDERATION_DIR" pull --rebase
        echo "Updated federation repo"
    fi
    # Configure git identity for federation commits
    sudo -u steward git -C "$FEDERATION_DIR" config user.email "steward@$(hostname)"
    sudo -u steward git -C "$FEDERATION_DIR" config user.name "steward-daemon"
fi

# 6. Setup environment file
if [ ! -f "${STEWARD_HOME}/.env" ]; then
    cp "${WORKSPACE}/deploy/env.example" "${STEWARD_HOME}/.env"
    chmod 600 "${STEWARD_HOME}/.env"
    # Set federation dir if repo was provided
    if [ -n "$FEDERATION_REPO" ]; then
        echo "STEWARD_FEDERATION_DIR=${FEDERATION_DIR}" >> "${STEWARD_HOME}/.env"
    fi
    echo "Created .env — edit ${STEWARD_HOME}/.env with your API keys"
fi

# 7. Install systemd service
cp "${WORKSPACE}/deploy/steward.service" /etc/systemd/system/
systemctl daemon-reload
echo "Installed systemd service"

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit API keys:  sudo nano ${STEWARD_HOME}/.env"
echo "  2. Start daemon:   sudo systemctl enable --now steward"
echo "  3. Watch logs:     journalctl -u steward -f"
echo "  4. Check status:   sudo systemctl status steward"
echo ""
