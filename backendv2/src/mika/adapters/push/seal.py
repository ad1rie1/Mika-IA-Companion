"""Ce qu'une notification emporte, scellé pour le seul téléphone qui l'attend (ADR 0077).

Le téléphone tire une clé AES de 256 bits à sa connexion et la confie au serveur avec son jeton Firebase
(``POST /auth/push``, sous le jeton de l'application). Chaque notification part chiffrée par elle : AES-GCM, un
nonce de 96 bits tiré à chaque envoi, les données associées ``AAD`` (un chiffré d'un autre usage ne s'ouvre pas
ici). Google ne transporte qu'un chiffré ; l'application le déchiffre et l'affiche elle-même.

Le clair est un petit JSON : ``{"t": "speech", "id": …, "text": …, "ts": …, "files": …}`` — l'identifiant du
message dans le fil, son texte (jetons prosodiques retirés, coupé à ``TEXT_MAX_BYTES`` octets : Firebase refuse
plus de 4 Kio de données), l'heure (ms depuis l'époque) et le nombre de fichiers joints. Le scellé :
``{"v": "1", "n": <nonce base64>, "c": <chiffré base64>}``, base64 standard avec bourrage.
"""

from __future__ import annotations

import base64
import binascii
import json
import secrets
from collections.abc import Mapping
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

VERSION = "1"
#: lié au sens du chiffré : le même que l'application (``PushPayload.AAD``)
AAD = b"fr.qwartz.mika/push/v1"
KEY_BYTES = 32
NONCE_BYTES = 12
#: le texte d'un message, au plus (octets UTF-8)…
TEXT_MAX_BYTES = 2400
#: … et le clair entier, échappements JSON compris (un saut de ligne, un guillemet en coûtent deux) : chiffré et en
#: base64, le scellé reste sous les 4 Kio de données de Firebase
PLAIN_MAX_BYTES = 2600
ELLIPSIS = "…"
SPEECH = "speech"


def key_from(text: str) -> bytes:
    """La clé confiée par le téléphone (base64 de 32 octets) ; ``ValueError`` en français sinon."""
    try:
        raw = base64.b64decode(text.strip(), validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("La clé de notification n'est pas du base64.") from None
    if len(raw) != KEY_BYTES:
        raise ValueError(f"La clé de notification doit faire {KEY_BYTES} octets.")
    return raw


def clip(text: str, max_bytes: int = TEXT_MAX_BYTES) -> str:
    """Le texte, coupé sur un caractère entier pour tenir en ``max_bytes`` octets UTF-8 (« … » compris)."""
    if len(text.encode()) <= max_bytes:
        return text
    budget = max_bytes - len(ELLIPSIS.encode())
    if budget <= 0:
        return ""
    cut = text.encode()[:budget].decode(errors="ignore").rstrip()
    return cut + ELLIPSIS


def payload(*, message_id: int, text: str, ts_ms: int, files: int = 0) -> dict[str, Any]:
    """Le clair d'une notification de parole, sous ``PLAIN_MAX_BYTES`` une fois sérialisé."""
    body = {"t": SPEECH, "id": int(message_id), "text": clip(text), "ts": int(ts_ms), "files": max(0, int(files))}
    if len(_plain(body)) <= PLAIN_MAX_BYTES:
        return body
    # trop d'échappements (des sauts de ligne, des guillemets) : le plus long texte qui tient, par dichotomie
    lo, hi = 0, TEXT_MAX_BYTES
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if len(_plain(body | {"text": clip(text, mid)})) <= PLAIN_MAX_BYTES:
            lo = mid
        else:
            hi = mid - 1
    return body | {"text": clip(text, lo)}


def _plain(body: Mapping[str, Any]) -> bytes:
    return json.dumps(dict(body), ensure_ascii=False, separators=(",", ":")).encode()


def seal(key: bytes, body: Mapping[str, Any], nonce: bytes | None = None) -> dict[str, str]:
    """Le scellé de ``body`` (ce qui part dans les données du message Firebase, des chaînes seulement)."""
    nonce = nonce if nonce is not None else secrets.token_bytes(NONCE_BYTES)
    sealed = AESGCM(key).encrypt(nonce, _plain(body), AAD)
    return {"v": VERSION, "n": base64.b64encode(nonce).decode(), "c": base64.b64encode(sealed).decode()}


def unseal(key: bytes, data: Mapping[str, str]) -> dict[str, Any]:
    """L'inverse de ``seal`` (ce que fait l'application) ; lève sur un scellé d'une autre version ou abîmé."""
    if data.get("v") != VERSION:
        raise ValueError("version de scellé inconnue")
    plain = AESGCM(key).decrypt(base64.b64decode(data["n"]), base64.b64decode(data["c"]), AAD)
    return dict(json.loads(plain))
