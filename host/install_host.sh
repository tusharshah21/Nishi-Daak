#!/usr/bin/env bash
# Nishi Daak host setup for the Arduino UNO Q (Debian side). Run once: sudo ./install_host.sh
# Installs the presence service and a local llama-server with a small Gemma model, both as systemd units.
set -euo pipefail

# Small Gemma GGUF for llama-server -hf. 2GB board: 270M (about 290 MB). 4GB board: 1B Q4_K_M (about 800 MB).
#   MODEL_REPO=ggml-org/gemma-3-1b-it-GGUF:Q4_K_M sudo -E ./install_host.sh
MODEL_REPO="${MODEL_REPO:-ggml-org/gemma-3-270m-it-GGUF}"
RUN_USER="${SUDO_USER:-arduino}"
NISHI_IFACE="${NISHI_IFACE:-wlan0}"
DIR=/opt/nishi
HERE="$(cd "$(dirname "$0")" && pwd)"

apt-get update
apt-get install -y arp-scan bluez git build-essential cmake libcurl4-openssl-dev python3
apt-get install -y python3-bleak || pip3 install --break-system-packages bleak

mkdir -p "$DIR"
install -m 755 "$HERE/presence_service.py" "$DIR/presence_service.py"

if [ ! -x "$DIR/llama.cpp/build/bin/llama-server" ]; then
  [ -d "$DIR/llama.cpp" ] || git clone --depth 1 https://github.com/ggml-org/llama.cpp "$DIR/llama.cpp"
  cmake -S "$DIR/llama.cpp" -B "$DIR/llama.cpp/build" -DCMAKE_BUILD_TYPE=Release -DLLAMA_CURL=ON
  cmake --build "$DIR/llama.cpp/build" --target llama-server -j2  # -j2: the board has little RAM
fi

cat > /etc/systemd/system/nishi-presence.service <<EOF
[Unit]
Description=Nishi Daak presence scanner (Wi-Fi ARP + BLE count)
After=network-online.target bluetooth.target
Wants=network-online.target

[Service]
Environment=NISHI_IFACE=$NISHI_IFACE
ExecStart=/usr/bin/python3 $DIR/presence_service.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/nishi-llm.service <<EOF
[Unit]
Description=Nishi Daak local Gemma (llama-server)
After=network-online.target
Wants=network-online.target

[Service]
User=$RUN_USER
ExecStart=$DIR/llama.cpp/build/bin/llama-server -hf $MODEL_REPO -c 2048 --host 0.0.0.0 --port 8080
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now nishi-presence.service nishi-llm.service
echo "Done. First start downloads the model; watch it with: journalctl -fu nishi-llm"
