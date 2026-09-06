#!/usr/bin/env bash
# Life Poster installer - Raspberry Pi OS (Bookworm or Trixie) on a Pi Zero W
# with a Pimoroni Inky Impression 7.3" (Spectra 6).
# Run as your normal user (NOT root):   bash install.sh
set -euo pipefail

APPDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_USER="${SUDO_USER:-$USER}"
[ "$RUN_USER" = "root" ] && { echo "Run as your normal user, not root."; exit 1; }
echo "==> Life Poster installing into: $APPDIR   (user: $RUN_USER)"

# --------------------------------------------------------------------------- #
# 1. System libraries
# --------------------------------------------------------------------------- #
echo "==> Installing system packages…"
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
  python3 python3-venv python3-pip git \
  libopenblas0 libgfortran5 \
  fonts-dejavu-core i2c-tools raspi-config

echo "==> Enabling SPI and I2C…"
sudo raspi-config nonint do_spi 0 || true
sudo raspi-config nonint do_i2c 0 || true
for g in spi gpio i2c; do sudo adduser "$RUN_USER" "$g" >/dev/null 2>&1 || true; done

# --------------------------------------------------------------------------- #
# 2. Pick a Python venv that already has a working `inky`, else build one
# --------------------------------------------------------------------------- #
find_inky_venv() {
  for p in "$HOME/.virtualenvs/pimoroni/bin/python" "$HOME/.virtualenvs"/*/bin/python; do
    [ -x "$p" ] || continue
    if "$p" -c "import inky, numpy" >/dev/null 2>&1; then echo "$p"; return 0; fi
  done
  return 1
}

VENV_PY=""
if VENV_PY="$(find_inky_venv)"; then
  echo "==> Reusing existing Inky venv: $VENV_PY"
else
  echo "==> No working Inky venv found - building one at $APPDIR/.venv"
  sudo apt-get install -y --no-install-recommends \
    python3-numpy python3-pil python3-spidev python3-lgpio python3-gpiod \
    libjpeg62-turbo libopenjp2-7 libtiff6 || \
  sudo apt-get install -y --no-install-recommends \
    python3-numpy python3-pil python3-spidev python3-lgpio python3-gpiod
  python3 -m venv --system-site-packages "$APPDIR/.venv"
  "$APPDIR/.venv/bin/pip" install --upgrade pip
  "$APPDIR/.venv/bin/pip" install "inky>=2.1.0"
  VENV_PY="$APPDIR/.venv/bin/python"
fi

echo "==> Adding Flask + waitress to that venv…"
"$VENV_PY" -m pip install --upgrade Flask==3.0.3 waitress==3.0.2

# --------------------------------------------------------------------------- #
# 3. Probe the panel
# --------------------------------------------------------------------------- #
echo "==> Probing the Inky panel…"
"$VENV_PY" - <<'PY' || echo "   (panel not detected yet - Life Poster will run in mock mode until it is)"
from inky.auto import auto
d = auto(ask_user=False, verbose=False)
print(f"   detected: {type(d).__module__}  {tuple(d.resolution)}")
PY

# --------------------------------------------------------------------------- #
# 4. systemd service
# --------------------------------------------------------------------------- #
echo "==> Installing systemd service…"
sed -e "s#__USER__#$RUN_USER#g" -e "s#__APPDIR__#$APPDIR#g" -e "s#__PYTHON__#$VENV_PY#g" \
    "$APPDIR/lifeposter.service.tmpl" | sudo tee /etc/systemd/system/lifeposter.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now lifeposter.service

sleep 2
IP="$(hostname -I | awk '{print $1}')"
echo
echo "======================================================================"
echo " Life Poster is running:"
echo "   http://${IP:-<pi-ip>}:8080/     (or http://$(hostname).local:8080/)"
echo
echo " Status:   systemctl status lifeposter"
echo " Logs:     journalctl -u lifeposter -f"
echo " Restart:  sudo systemctl restart lifeposter"
echo
echo " If SPI/I2C were just enabled, reboot once:  sudo reboot"
echo "======================================================================"
