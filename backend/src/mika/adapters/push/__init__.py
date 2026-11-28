"""Les notifications du téléphone (ADR 0077) : Firebase Cloud Messaging (``fcm``) porte un message scellé pour le
seul téléphone qui l'attend (``seal``). L'application ne garde aucune connexion ouverte quand elle est fermée.

Les fonctions du scellé s'appellent par leur module (``seal.seal``, ``seal.payload``) : le paquet ne réexporte pas
``seal``, qui masquerait le module du même nom."""

from mika.adapters.push.fcm import (
    FAILED,
    GONE,
    SENT,
    UNCONFIGURED,
    FcmSender,
    SendResult,
    parse_service_account,
)
from mika.adapters.push.seal import key_from

__all__ = ["FAILED", "GONE", "SENT", "UNCONFIGURED", "FcmSender", "SendResult", "key_from", "parse_service_account"]
