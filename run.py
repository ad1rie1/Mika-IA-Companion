"""Launch the VTuber Engine backend (Django + Channels)."""
import os
import sys
from pathlib import Path

# Add backend/ to Python path
backend_dir = Path(__file__).parent / "backend"
sys.path.insert(0, str(backend_dir))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.conf import settings


def main():
    import logging

    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    # Silence noisy httpx logs (Telegram polling)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logger = logging.getLogger("vtuber")

    logger.info("Starting VTuber Engine for %s", settings.VTUBER_NAME)
    logger.info("API: http://localhost:%d", settings.API_PORT)
    logger.info("WebSocket: ws://localhost:%d/ws", settings.API_PORT)
    logger.info("Admin: http://localhost:%d/admin/", settings.API_PORT)

    uvicorn.run(
        "config.asgi:application",
        host="0.0.0.0",
        port=settings.API_PORT,
        lifespan="on",
        app_dir=str(backend_dir),
    )


if __name__ == "__main__":
    main()
