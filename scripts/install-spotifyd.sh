#!/usr/bin/env bash
set -euo pipefail

echo "🎵 Installing spotifyd (Spotify Connect daemon)"
echo ""

ARCH=$(uname -m)
if [[ "$ARCH" == "aarch64" ]]; then
    BINARY="spotifyd-linux-aarch64-slim"
elif [[ "$ARCH" == "armv7l" ]]; then
    BINARY="spotifyd-linux-armhf-slim"
else
    echo "❌ Unsupported architecture: $ARCH"
    exit 1
fi

# Get latest release
echo "📥 Downloading spotifyd..."
LATEST=$(curl -s https://api.github.com/repos/Spotifyd/spotifyd/releases/latest | grep "browser_download_url.*${BINARY}" | head -1 | cut -d '"' -f 4)

if [[ -z "$LATEST" ]]; then
    echo "❌ Could not find download URL. Install manually from https://github.com/Spotifyd/spotifyd/releases"
    exit 1
fi

curl -L "$LATEST" -o /tmp/spotifyd.tar.gz
tar -xzf /tmp/spotifyd.tar.gz -C /tmp/
sudo mv /tmp/spotifyd /usr/local/bin/
sudo chmod +x /usr/local/bin/spotifyd
rm /tmp/spotifyd.tar.gz

echo ""
echo "📝 Creating config..."
mkdir -p ~/.config/spotifyd
cat > ~/.config/spotifyd/spotifyd.conf << 'EOF'
[global]
backend = "alsa"
device_name = "PiGlot"
bitrate = 160
volume_normalisation = true
device_type = "speaker"
EOF

echo ""
echo "📝 Creating systemd service..."
sudo tee /etc/systemd/system/spotifyd.service > /dev/null << 'EOF'
[Unit]
Description=Spotifyd - Spotify Connect
After=network-online.target sound.target
Wants=network-online.target

[Service]
Type=simple
User=pi
ExecStart=/usr/local/bin/spotifyd --no-daemon
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable spotifyd
sudo systemctl start spotifyd

echo ""
echo "✅ spotifyd installed and running!"
echo "   Device name: PiGlot"
echo "   Open Spotify on your phone → Connect → select 'PiGlot'"
