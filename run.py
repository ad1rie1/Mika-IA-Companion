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
from pipeline.media import MAX_ATTACHMENTS, MAX_FILE_SIZE_BYTES

# Taille maximale d'un frame WebSocket entrant.
#
# Le défaut d'uvicorn (16 Mio) est plus bas que ce que les limites
# applicatives autorisent : 5 pièces jointes de 5 Mo encodées en base64 dans
# un frame JSON pèsent ~35 Mio. Le frame était alors refusé *au niveau du
# transport* — connexion fermée en 1009 avant d'atteindre le consumer, donc
# sans ack ni la moindre trace applicative. On l'aligne sur ce que
# validate_attachments accepte déjà : base64 = 4/3 des octets décodés, plus
# 1 Mio pour la légende et l'enveloppe JSON.
WS_MAX_FRAME_BYTES = MAX_ATTACHMENTS * MAX_FILE_SIZE_BYTES * 4 // 3 + 1024 * 1024


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

    host = settings.API_HOST

    logger.info("Starting VTuber Engine for %s", settings.VTUBER_NAME)
    logger.info("API: http://localhost:%d", settings.API_PORT)
    logger.info("WebSocket: ws://localhost:%d/ws", settings.API_PORT)
    logger.info("Admin: http://localhost:%d/admin/", settings.API_PORT)
    logger.info("Dashboard: http://localhost:%d/gestion/", settings.API_PORT)

    # The dashboard can read the whole conversation history and rewrite the
    # config (including provider API keys). Binding it to every interface
    # without an auth gate exposes all of that to the local network.
    if host not in ("127.0.0.1", "localhost", "::1"):
        if settings.DASHBOARD_REQUIRE_AUTH:
            logger.info("Bound to %s with dashboard auth required", host)
        else:
            logger.warning(
                "SECURITY: bound to %s with DASHBOARD_REQUIRE_AUTH=False — "
                "anyone on this network can read your conversations and edit "
                "your API keys. Set DASHBOARD_REQUIRE_AUTH=1 (and create a "
                "superuser with `python backend/manage.py createsuperuser`), "
                "or leave API_HOST=127.0.0.1.", host,
            )

    uvicorn.run(
        "config.asgi:application",
        host=host,
        port=settings.API_PORT,
        lifespan="on",
        app_dir=str(backend_dir),
        ws_max_size=WS_MAX_FRAME_BYTES,
    )


if __name__ == "__main__":
    main()
