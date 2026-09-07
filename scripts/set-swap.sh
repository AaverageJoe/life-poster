#!/usr/bin/env bash
# Give the Pi Zero W a bigger swap area so image processing + the Inky buffers
# don't get OOM-killed.  Usage:  bash scripts/set-swap.sh [SIZE_MB]   (default 1024)
set -euo pipefail
SIZE_MB="${1:-1024}"

echo "==> Target swap: ${SIZE_MB} MB"

if [ -f /etc/dphys-swapfile ]; then
  echo "==> Using dphys-swapfile"
  sudo dphys-swapfile swapoff 2>/dev/null || true
  sudo sed -i "s/^#\?CONF_SWAPSIZE=.*/CONF_SWAPSIZE=${SIZE_MB}/" /etc/dphys-swapfile
  if grep -q '^#\?CONF_MAXSWAP=' /etc/dphys-swapfile; then
    sudo sed -i "s/^#\?CONF_MAXSWAP=.*/CONF_MAXSWAP=${SIZE_MB}/" /etc/dphys-swapfile
  else
    echo "CONF_MAXSWAP=${SIZE_MB}" | sudo tee -a /etc/dphys-swapfile >/dev/null
  fi
  sudo dphys-swapfile setup
  sudo dphys-swapfile swapon
else
  echo "==> dphys-swapfile not present - using a plain /swapfile"
  if swapon --show=NAME --noheadings | grep -qx /swapfile; then
    sudo swapoff /swapfile
  fi
  sudo rm -f /swapfile
  sudo fallocate -l "${SIZE_MB}M" /swapfile 2>/dev/null || \
    sudo dd if=/dev/zero of=/swapfile bs=1M count="${SIZE_MB}" status=none
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile >/dev/null
  sudo swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || \
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

# be less eager to swap; only lean on it under real pressure
sudo sysctl -w vm.swappiness=20 >/dev/null || true
if [ -d /etc/sysctl.d ]; then
  echo 'vm.swappiness=20' | sudo tee /etc/sysctl.d/99-lifeposter.conf >/dev/null
fi

echo "==> Done:"
free -h
