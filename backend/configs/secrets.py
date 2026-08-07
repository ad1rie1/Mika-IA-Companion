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
import os
from functools import lru_cache

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)

# Un seul endroit nomme la variable : la clé n'était lue que comme attribut
# de settings, qu'aucun module ne déclarait — le `getattr` renvoyait donc
# toujours "" et le chemin PBKDF2 était le seul jamais emprunté. Une
# déclaration manquante ailleurs ne doit plus pouvoir la rendre inerte.
ENV_KEY_NAME = "CONFIG_ENCRYPTION_KEY"


def _cle_declaree() -> str:
    """Clé fournie par l'opérateur, ou ``""`` si elle n'est pas configurée.

    Lue dans l'environnement plutôt que dans le registre de configuration :
    c'est précisément ce registre qu'elle déchiffre. ``settings`` est
    interrogé d'abord — il reste le point de surcharge d'un test — mais
    l'environnement fait autorité, ``config/settings.py`` chargeant le
    ``.env`` dans ``os.environ`` au démarrage.
    """
    raw = getattr(settings, ENV_KEY_NAME, "") or os.environ.get(ENV_KEY_NAME, "") or ""
    if isinstance(raw, bytes):
        raw = raw.decode("ascii", "ignore")
    return raw.strip()


@lru_cache(maxsize=1)
def _fernet():
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        logger.warning(
            "cryptography not installed — secret values stored in plaintext"
        )
        return None

    raw = _cle_declaree()
    if raw:
        key = raw.encode("ascii")
    else:
        # PBKDF2 from SECRET_KEY — 100k iterations is plenty for this use
        seed = settings.SECRET_KEY.encode("utf-8")
        dk = hashlib.pbkdf2_hmac("sha256", seed, b"configs.secrets", 100_000, dklen=32)
        key = base64.urlsafe_b64encode(dk)
    try:
        return Fernet(key)
    except Exception as exc:
        if not raw:
            raise
        # Une clé mal formée ne se voit sinon qu'au premier `encrypt`, très
        # loin de sa cause — et la retirer ne répare rien, les secrets déjà
        # stockés attendent la vraie clé.
        raise ImproperlyConfigured(
            f"{ENV_KEY_NAME} n'est pas une cle Fernet valide : il faut 32 "
            "octets encodes en base64 url-safe, tels que produits par "
            "`python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"`. Corrige la variable "
            "plutot que de la supprimer : les secrets deja enregistres sont "
            "chiffres avec elle."
        ) from exc


def verifier_cle() -> None:
    """Construit la Fernet maintenant, au démarrage de l'app ``configs``.

    Sans cet appel, une ``CONFIG_ENCRYPTION_KEY`` mal formée n'échoue qu'au
    premier chiffrement — c'est-à-dire au premier enregistrement de la
    configuration, plusieurs écrans après la faute de frappe.
    """
    _fernet()


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
