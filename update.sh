#!/usr/bin/env bash
# Pull the latest Life Poster and restart the service.  Run:  bash update.sh
set -euo pipefail
APPDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APPDIR"

echo "==> git pull"
git pull --ff-only

# swap: bump it if it's still tiny (the OOM fix)
SWAP_MB="$(free -m | awk '/Swap:/{print $2}')"
if [ "${SWAP_MB:-0}" -lt 512 ]; then
  echo "==> swap is only ${SWAP_MB:-0} MB - resizing"
  bash "$APPDIR/scripts/set-swap.sh" 1024 || echo "   (swap resize skipped)"
fi

# make sure Flask + waitress are in whatever venv the service runs
PY="$(sed -n 's/^ExecStart=\([^ ]*\).*/\1/p' /etc/systemd/system/lifeposter.service 2>/dev/null || true)"
if [ -x "$PY" ]; then
  echo "==> refreshing python deps in $PY"
  "$PY" -m pip install -q --upgrade Flask waitress || true
fi

echo "==> restarting service"
sudo systemctl restart lifeposter
sleep 2
systemctl --no-pager --lines=15 status lifeposter || true
echo
echo "Tail the log with:  journalctl -u lifeposter -f"
