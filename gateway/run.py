"""Run the PiGlot Cloud Gateway server."""

import asyncio
import logging
import os
import sys

# Add parent dir to path so we can import src.gateway
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aiohttp import web
from src.gateway.server import PiGlotGateway

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)


def main():
    port = int(os.environ.get("PORT", "8080"))
    admin_token = os.environ.get("PIGLOT_ADMIN_TOKEN", "")

    if not admin_token:
        logging.warning("⚠️  PIGLOT_ADMIN_TOKEN not set — admin endpoints are disabled")

    gateway = PiGlotGateway(port=port, admin_token=admin_token)
    app = gateway.create_app()

    logging.info("🌐 Starting PiGlot Gateway on port %d", port)
    web.run_app(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
