# PiGlot 🗣️🥧

**AI Language Learning Assistant** — A Raspberry Pi-powered voice assistant for learning languages, with Spotify integration.

> Replace your Alexa with something smarter — an open-source, privacy-first language tutor that lives on your desk.

## Features

- 🎤 **Voice conversation** — Talk in your target language, get corrections and responses
- 🗣️ **Pronunciation feedback** — Compares your speech to expected output
- 🎵 **Spotify integration** — "Play music in French", vocabulary quizzes from lyrics
- 🧠 **Adaptive learning** — Tracks your level, adjusts difficulty
- 🔊 **Wake word** — "Hey PiGlot" (customizable)
- 🌍 **Multi-language** — Any language supported by Whisper + TTS
- 🔒 **Privacy-first** — Runs locally, your data stays on your device

## Hardware Requirements

| Component | Recommended | Budget |
|-----------|------------|--------|
| Board | Raspberry Pi 4 (4GB) | Raspberry Pi 4 (2GB) |
| Microphone | ReSpeaker 4-Mic Array | ReSpeaker 2-Mic HAT |
| Speaker | Any USB/Bluetooth/3.5mm | 3.5mm mini speaker |
| Storage | 32GB+ microSD | 16GB microSD |
| Power | Official Pi 4 PSU (5V 3A) | Any 5V 3A USB-C |

**Estimated cost: ~€65-90**

## Architecture

```
┌─────────────────────────────────────────────┐
│                  PiGlot                      │
│                                              │
│  ┌──────────┐  ┌──────────┐  ┌───────────┐  │
│  │ Wake Word│  │  Audio   │  │  LED Ring  │  │
│  │ (OpenWake│→ │ Capture  │  │ Feedback   │  │
│  │  Word)   │  │          │  │ (optional) │  │
│  └──────────┘  └────┬─────┘  └───────────┘  │
│                     │                        │
│               ┌─────▼──────┐                 │
│               │   Whisper  │                 │
│               │   (STT)    │                 │
│               └─────┬──────┘                 │
│                     │                        │
│               ┌─────▼──────┐                 │
│               │   Brain    │                 │
│               │ (LLM API)  │                 │
│               │ - OpenAI   │                 │
│               │ - Anthropic│                 │
│               │ - Ollama   │                 │
│               └─────┬──────┘                 │
│                     │                        │
│        ┌────────────┼────────────┐           │
│        │            │            │           │
│  ┌─────▼─────┐ ┌───▼────┐ ┌────▼─────┐     │
│  │    TTS    │ │Spotify │ │ Learning │     │
│  │(Edge/Elev)│ │Control │ │ Tracker  │     │
│  └─────┬─────┘ └───┬────┘ └──────────┘     │
│        │           │                        │
│  ┌─────▼─────┐ ┌───▼────┐                  │
│  │  Speaker  │ │spotifyd│                   │
│  └───────────┘ └────────┘                   │
└─────────────────────────────────────────────┘
```

## Project Structure

```
piglot/
├── src/
│   ├── main.py              # Entry point
│   ├── config.py            # Configuration loader
│   ├── audio/
│   │   ├── capture.py       # Microphone input handling
│   │   ├── playback.py      # Speaker output
│   │   └── wake_word.py     # Wake word detection
│   ├── stt/
│   │   ├── engine.py        # STT engine interface
│   │   └── whisper_local.py # Local Whisper implementation
│   ├── tts/
│   │   ├── engine.py        # TTS engine interface
│   │   ├── edge_tts.py      # Edge TTS (free)
│   │   └── elevenlabs.py    # ElevenLabs (premium)
│   ├── brain/
│   │   ├── engine.py        # LLM interface
│   │   ├── prompts.py       # System prompts for language tutor
│   │   └── conversation.py  # Conversation state management
│   ├── spotify/
│   │   ├── client.py        # Spotify Web API client
│   │   └── player.py        # Playback control
│   ├── learning/
│   │   ├── tracker.py       # Progress tracking
│   │   ├── vocabulary.py    # Vocabulary database
│   │   └── exercises.py     # Exercise generators
│   └── hardware/
│       ├── leds.py          # LED feedback (optional)
│       └── button.py        # Physical button (optional)
├── config/
│   └── config.yaml          # User configuration
├── data/
│   └── .gitkeep             # User data (vocabulary, progress)
├── scripts/
│   ├── setup.sh             # Full setup script
│   └── install-spotifyd.sh  # Spotify Connect setup
├── systemd/
│   └── piglot.service       # Systemd service file
├── requirements.txt
├── pyproject.toml
├── Makefile
└── README.md
```

## Quick Start

### 1. Flash Raspberry Pi OS

Use [Raspberry Pi Imager](https://www.raspberrypi.com/software/) — Raspberry Pi OS Lite (64-bit).

Enable SSH and Wi-Fi during setup.

### 2. Install PiGlot

```bash
# SSH into your Pi
ssh pi@piglot.local

# Clone and setup
git clone https://github.com/jagjerez-org/piglot.git
cd piglot
make setup
```

### 3. Configure

```bash
cp config/config.yaml.example config/config.yaml
nano config/config.yaml
```

Set your:
- Target language(s)
- LLM API key (OpenAI/Anthropic)
- Spotify credentials (optional)
- Wake word preference

### 4. Run

```bash
# Test run
make run

# Install as service (auto-start on boot)
make install-service
```

## Configuration

```yaml
# config/config.yaml
piglot:
  wake_word: "piglot"       # or "hey piglot", custom
  language: "en"             # your native language
  target_language: "fr"      # language you're learning
  level: "beginner"          # beginner / intermediate / advanced

audio:
  input_device: "default"    # or specific device name
  output_device: "default"
  sample_rate: 16000

stt:
  engine: "whisper_local"    # whisper_local | whisper_api
  model: "base"              # tiny | base | small (local only)

tts:
  engine: "edge"             # edge | elevenlabs
  voice: "fr-FR-DeniseNeural"  # depends on engine + language
  # elevenlabs_api_key: ""   # only if using elevenlabs

brain:
  provider: "openai"         # openai | anthropic | ollama
  model: "gpt-4o-mini"       # cost-effective for conversation
  api_key: "${OPENAI_API_KEY}"
  # For local (ollama):
  # provider: "ollama"
  # model: "llama3"
  # base_url: "http://localhost:11434"

spotify:
  enabled: false
  client_id: ""
  client_secret: ""
  device_name: "PiGlot"

learning:
  session_duration_minutes: 15
  daily_goal_minutes: 30
  review_interval_hours: 24
```

## Learning Modes

### 🗣️ Free Conversation
Just talk. PiGlot responds in your target language, corrects mistakes, and teaches new vocabulary naturally.

### 📝 Vocabulary Review
Spaced repetition flashcards by voice. PiGlot says a word, you translate.

### 🎵 Music Mode
"Play music in French" → plays a song → pauses → quizzes you on lyrics/vocabulary.

### 🎯 Exercises
Grammar drills, fill-in-the-blank, translation challenges — all by voice.

### 🗞️ News Discussion
Fetches a headline in target language, reads it, discusses with you.

## API Keys

| Service | Required | Free Tier | Purpose |
|---------|----------|-----------|---------|
| OpenAI / Anthropic | Yes (pick one) | Limited | LLM brain |
| Spotify | Optional | Yes (Premium for playback) | Music features |
| ElevenLabs | Optional | 10k chars/mo | Premium voice quality |

Edge TTS and local Whisper are **completely free**.

## Development

```bash
# Install dev dependencies
make dev-setup

# Run tests
make test

# Lint
make lint

# Run in debug mode
make run-debug
```

## Roadmap

- [x] Project architecture
- [ ] Core audio pipeline (capture → STT → LLM → TTS → playback)
- [ ] Wake word detection
- [ ] Language tutor brain prompts
- [ ] Spotify integration
- [ ] Vocabulary tracker with spaced repetition
- [ ] LED feedback for listening/thinking/speaking states
- [ ] Web dashboard for progress stats
- [ ] Multi-user support (voice fingerprinting)
- [ ] Offline mode (Ollama + local TTS)

## License

MIT

---

*Built with ❤️ and a Raspberry Pi*
