.PHONY: setup dev-setup run run-debug test lint install-service

setup:
	@echo "🥧 Setting up PiGlot..."
	sudo apt-get update
	sudo apt-get install -y python3-pip python3-venv portaudio19-dev ffmpeg
	python3 -m venv .venv
	.venv/bin/pip install -e .
	@echo "✅ Setup complete! Copy config/config.yaml.example to config/config.yaml and edit it."

dev-setup: setup
	.venv/bin/pip install -e ".[dev]"

run:
	.venv/bin/piglot

run-debug:
	PIGLOT_DEBUG=1 .venv/bin/piglot

test:
	.venv/bin/pytest tests/ -v

lint:
	.venv/bin/ruff check src/
	.venv/bin/mypy src/

install-service:
	sudo cp systemd/piglot.service /etc/systemd/system/
	sudo systemctl daemon-reload
	sudo systemctl enable piglot
	sudo systemctl start piglot
	@echo "✅ PiGlot service installed and started"

uninstall-service:
	sudo systemctl stop piglot
	sudo systemctl disable piglot
	sudo rm /etc/systemd/system/piglot.service
	sudo systemctl daemon-reload

install-spotify:
	bash scripts/install-spotifyd.sh
