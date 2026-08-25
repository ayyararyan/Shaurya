#!/usr/bin/env bash
set -euo pipefail
sudo apt-get update
sudo apt-get install -y build-essential cmake ninja-build pkg-config libssl-dev libcurl4-openssl-dev libboost-all-dev python3 python3-venv chrony unzip zip
sudo systemctl enable --now chrony
mkdir -p build state stats logs
printf 'Bootstrap complete. Next: scripts/build_release.sh\n'
