"""Symmetric encryption for ``sensitive`` config values.

Key material:
  - ``CONFIG_ENCRYPTION_KEY`` env var if set (base64-urlsafe 32 bytes)
  - Else derived from Django ``SECRET_KEY`` via PBKDF2

The derivation is deterministic — as long as SECRET_KEY doesn't rotate,
the DB contents stay decryptable. Rotating SECRET_KEY without a proper
re-encrypt job will break existing secrets; the log output makes this
loud when it happens.

Relies on ``cryptography.fernet`` (already required by Channels).
"""
from __future__ import annotations

import base64
import hashlib
import logging
from functools import lru_cache

from django.conf import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _fernet():
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        logger.warning(
            "cryptography not installed — secret values stored in plaintext"
        )
        return None

    raw = getattr(settings, "CONFIG_ENCRYPTION_KEY", "") or ""
    if raw:
        key = raw.encode() if isinstance(raw, str) else raw
    else:
        # PBKDF2 from SECRET_KEY — 100k iterations is plenty for this use
        seed = settings.SECRET_KEY.encode("utf-8")
        dk = hashlib.pbkdf2_hmac("sha256", seed, b"configs.secrets", 100_000, dklen=32)
        key = base64.urlsafe_b64encode(dk)
    return Fernet(key)


def encrypt(plaintext: str) -> str:
    """Return an opaque base64 token or the raw plaintext if encryption
    is unavailable (logged + tolerated in dev)."""
    if plaintext is None:
        return None
    f = _fernet()
    if f is None:
        return plaintext
    return f.encrypt(str(plaintext).encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    if token is None:
        return None
    f = _fernet()
    if f is None:
        return token
    try:
        return f.decrypt(token.encode("ascii")).decode("utf-8")
    except Exception:
        # The stored value wasn't a valid Fernet token — either a
        # legacy plaintext from a dev setup, or SECRET_KEY rotated.
        logger.warning("Secret decrypt failed — returning raw value")
        return token


def redact(value: str | None, visible: int = 4) -> dict:
    """UI-safe representation. Never echoes the full secret."""
    if value is None or value == "":
        return {"has_value": False, "preview": "", "length": 0}
    s = str(value)
    tail = s[-visible:] if len(s) > visible else ""
    return {
        "has_value": True,
        "preview": ("•" * max(4, min(12, len(s) - visible))) + tail,
        "length": len(s),
    }
