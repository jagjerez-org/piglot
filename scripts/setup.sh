#!/usr/bin/env bash
set -euo pipefail

echo "🥧 PiGlot Setup Script"
echo "======================"

# Check we're on a Pi (or at least Linux ARM)
if [[ "$(uname -m)" != "aarch64" && "$(uname -m)" != "armv7l" ]]; then
    echo "⚠️  Warning: This doesn't look like a Raspberry Pi ($(uname -m))"
    echo "   Continuing anyway..."
fi

echo ""
echo "📦 Installing system dependencies..."
sudo apt-get update -qq
sudo apt-get install -y -qq \
    python3-pip \
    python3-venv \
    python3-dev \
    portaudio19-dev \
    libsndfile1 \
    ffmpeg \
    alsa-utils

echo ""
echo "🐍 Creating Python virtual environment..."
python3 -m venv .venv
source .venv/bin/activate

echo ""
echo "📥 Installing PiGlot..."
pip install -e . 2>&1 | tail -5

echo ""
echo "🔊 Testing audio devices..."
echo "Input devices:"
python3 -c "import sounddevice; print([d for d in sounddevice.query_devices() if d['max_input_channels'] > 0])" 2>/dev/null || echo "  (sounddevice not ready yet)"
echo ""
echo "Output devices:"
python3 -c "import sounddevice; print([d for d in sounddevice.query_devices() if d['max_output_channels'] > 0])" 2>/dev/null || echo "  (sounddevice not ready yet)"

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "  1. cp config/config.yaml.example config/config.yaml"
echo "  2. nano config/config.yaml  (add your API keys)"
echo "  3. make run"
echo ""
echo "For auto-start on boot:"
echo "  make install-service"
