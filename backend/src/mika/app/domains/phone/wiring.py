"""Le câblage des messages du téléphone (ADR 0120, 0310) : leur porte, qui est aussi le port ``phone`` du noyau, et
l'application du téléphone que l'API par personne sert (ADR 0190)."""

from __future__ import annotations

from mika.app.domains.phone.api import APK_NAME
from mika.app.domains.phone.desk import PhoneDesk
from mika.app.wiring import Wiring

NAME = "phone"


def wire(w: Wiring) -> None:
    # les messages du téléphone (ADR 0120) : la porte de ``/api/phone/…``, et l'envoi d'une réponse proposée
    desk = PhoneDesk()
    w.ports[NAME] = w.parts[NAME] = desk
    w.web[NAME] = desk
    # l'application qu'on dépose dans le dossier de données (``telephone/``), servie à qui est connecté
    w.me["apk"] = w.data / "telephone" / APK_NAME


def bind(w: Wiring) -> None:
    """Une fois le noyau construit : son port d'entrée, et les notifications des téléphones (l'envoi d'une réponse
    proposée)."""
    desk = w.parts[NAME]
    desk.port = w.port
    desk.push = w.push
