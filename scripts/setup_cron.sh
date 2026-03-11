#!/usr/bin/env bash
# Setup cron for steward autonomous mode (every 15 minutes).
# Usage: ./scripts/setup_cron.sh [steward-directory]
STEWARD_DIR="${1:-$(pwd)}"
CRON_LINE="*/15 * * * * cd $STEWARD_DIR && python -m steward --autonomous >> .steward/autonomous.log 2>&1"
echo "$CRON_LINE"
echo "# Install: (crontab -l 2>/dev/null; echo '$CRON_LINE') | crontab -"
