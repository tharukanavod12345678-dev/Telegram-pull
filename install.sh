#!/bin/bash
set -e

USERNAME=$(whoami)
HOME_DIR="/home/$USERNAME"
TGPULL_DIR="$HOME_DIR/tg-pull"

echo "[1/6] System packages..."
sudo apt update -qq
sudo apt install -y -qq python3 python3-pip python3-venv unzip

echo "[2/6] Folders..."
mkdir -p "$TGPULL_DIR/_downloads"

echo "[3/6] Placing files..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp "$SCRIPT_DIR/app.py" "$TGPULL_DIR/"
cp "$SCRIPT_DIR/agent.py" "$TGPULL_DIR/"
cp "$SCRIPT_DIR/requirements.txt" "$TGPULL_DIR/"
cp "$SCRIPT_DIR/.env" "$TGPULL_DIR/.env"
cp "$SCRIPT_DIR/tgpull.service" "$TGPULL_DIR/"
cp "$SCRIPT_DIR/tgagent.service" "$TGPULL_DIR/"
chmod 600 "$TGPULL_DIR/.env"

echo "[4/6] Python venv..."
cd "$TGPULL_DIR"
python3 -m venv venv
./venv/bin/pip install --quiet --upgrade pip
./venv/bin/pip install --quiet -r requirements.txt

echo "[5/6] systemd services & sudoers..."
sed "s|USERNAME|$USERNAME|g" "$SCRIPT_DIR/tgpull.service" | \
    sudo tee /etc/systemd/system/tgpull.service > /dev/null
sed "s|USERNAME|$USERNAME|g" "$SCRIPT_DIR/tgagent.service" | \
    sudo tee /etc/systemd/system/tgagent.service > /dev/null

SYSTEMCTL_PATH=$(which systemctl)
echo "$USERNAME ALL=(ALL) NOPASSWD: $SYSTEMCTL_PATH start tgpull, $SYSTEMCTL_PATH reset-failed tgpull, $SYSTEMCTL_PATH stop tgagent" | \
    sudo tee /etc/sudoers.d/agent-restart > /dev/null
sudo chmod 0440 /etc/sudoers.d/agent-restart

sudo systemctl daemon-reload
sudo systemctl enable tgpull
sudo systemctl disable tgagent

echo "[6/6] Starting main bot..."
sudo systemctl restart tgpull

echo "✅ Setup complete."
