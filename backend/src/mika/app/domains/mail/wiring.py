"""Le câblage du courrier (ADR 0027, 0166, 0238, 0308, 0310) : son client IMAP/SMTP, qui est le port ``mail`` du noyau
(le courrier relevé, hors du journal) ; la connexion Microsoft de ses boîtes, scellée dans ses réglages ; et, quand le
serveur sert pour de bon, le courrier en direct — ce qui arrive est rangé tout de suite, même quand elle dort. Le
direct écoute sa base. Une fois le noyau construit, la fin de l'attente d'un code Microsoft se dit au direct
(``bind``). Ses réglages donnent aux paramètres du plugin ``email`` ses boîtes : lesquelles sont décochées, à qui est
chacune, avec qui elle est partagée, et les tableaux de ses canaux (``inputs``)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mika.adapters.mail import ImapSmtpMail, MailWatch
from mika.adapters.mail.oauth import mail_signin
from mika.adapters.signin.microsoft import MicrosoftSignIn
from mika.app.connections import ConnectionSettings
from mika.app.domains.mail.live import signed
from mika.app.domains.mail.settings import MailSettings
from mika.app.wiring import Wiring

NAME = "mail"


@dataclass(slots=True)
class MailParts:
    """Ce que le courrier tient en vie (``Live.parts["mail"]``)."""

    #: le parcours de connexion Microsoft de ses boîtes (ADR 0166)
    signin: MicrosoftSignIn
    #: le courrier en direct (ADR 0308) : une connexion IDLE par boîte, sinon une relève par minute ; ``None`` quand
    #: le serveur ne sert pas pour de bon (un test, l'aperçu)
    watch: MailWatch | None = None


def wire(w: Wiring) -> None:
    """Avant le noyau : son client, le port ``mail``."""
    own = w.settings.of(MailSettings)
    # une boîte Microsoft garde sa connexion (son jeton de renouvellement) scellée dans les réglages
    # (ADR 0166), et entre par l'application de l'instance quand elle n'en déclare pas (ADR 0238 : un réglage du
    # cadre, ADR 0318)
    microsoft = mail_signin(own, application=w.settings.of(ConnectionSettings).microsoft_application)
    mail = w.ports[NAME] = ImapSmtpMail(own.email, w.bases["mail"], her=w.her, microsoft=microsoft, images=own)
    parts = w.parts[NAME] = MailParts(microsoft)
    # le direct (ADR 0308) : sa base prévient de ses écritures validées
    w.watched.append(mail)
    # le courrier en direct (ADR 0308) : ce qui arrive est rangé tout de suite, même quand elle dort — hors de
    # l'ordonnanceur, que son sommeil arrête ; il se règle à chaque enregistrement des boîtes
    if w.serving:
        parts.watch = MailWatch(mail)
        own.mail_saved = parts.watch.nudge


def bind(w: Wiring) -> None:
    """Une fois le noyau construit : la fin de l'attente d'un code Microsoft (connectée, refusée, échue) se dit au
    direct — lu à l'appel : il naît après."""
    w.parts[NAME].signin.on_state = lambda box: signed(w.live.changes, box)


def inputs(settings: Any) -> dict[str, dict[str, Any]]:
    """Ce que ses réglages donnent aux paramètres du plugin ``email``."""
    # les tableaux de ses canaux (ADR 0134) : le courrier y lit ce qu'elle envoie à ta place
    canaux = settings.canals().model_dump(mode="json")
    boxes = settings.of(MailSettings).email().accounts
    off = sorted(k for k, a in boxes.items() if not a.enabled)
    # à qui est chaque boîte (ADR 0185 ; vide : à toi) : ses outils ne lui montrent que celles de qui est en face
    owners = {k: a.owner for k, a in sorted(boxes.items())}
    # avec qui chacune est partagée, et ce que la personne en a (ADR 0188)
    shares = {k: dict(sorted(a.shares.items())) for k, a in sorted(boxes.items()) if a.shares}
    return {"email": {"canaux": canaux, "boxes_off": off, "owners": owners, "shares": shares}}


async def start(w: Wiring) -> None:
    """Le direct en marche : le courrier en direct démarre (ce qu'il range part aux écrans)."""
    watch = w.parts[NAME].watch
    if watch is not None:
        watch.start()


async def stop(w: Wiring) -> None:
    """Dès l'arrêt, avant le direct."""
    watch = w.parts[NAME].watch
    if watch is not None:
        await watch.stop()
