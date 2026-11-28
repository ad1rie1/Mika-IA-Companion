"""La part du courrier dans le direct (ADR 0308, 0310) : ce que le journal et le courrier relevé y changent, et qui le
voit.

Ce qui change dans une boîte va à qui la tient, à son niveau (``BOXES`` : les boîtes de la personne, les siennes et
celles qu'on lui partage — la règle même de ses routes, ``api.boxes``) ; un mail (``boîte:<id>``) est à la boîte qui
le porte. Un brouillon qu'elle prépare est aussi un effet du moteur (proposé, décidé, parti) et une tâche
(``effect``, ``work``). La fin de l'attente d'un code Microsoft se dit d'elle-même (``signed``, posée par le
câblage).
"""

from __future__ import annotations

from typing import Any

from mika.app.domains.domain import LivePart
from mika.app.domains.mail import api as mail_me
from mika.app.domains.mail.settings import EMAIL_KEY, MAIL_GRANTS_KEY, MAIL_IMAGES_KEY
from mika.app.me.api import Call
from mika.app.me.touches import OWN, PREPARE, READ, Touch
from mika.app.me.touches import both as _both
from mika.app.me.touches import state_of as _state
from mika.contracts import email as email_c
from mika.plugins import email as email_p
from mika.ports.changes import CONTACTS, MAIL, MAIL_DRAFTS, MAIL_WORK, ME, SETTINGS, Change
from mika.ports.mail import split_ref

#: à qui va une touche du courrier : ce que dit une boîte (ses propriétaires et ses partages)
BOXES = "boxes"


def _email(e: Any, frame: Any, kernel: Any) -> list[Touch]:
    d, name = e.data, e.type.name
    if name == email_p.POLL_ASKED.name:
        return []
    ref = str(getattr(d, "mail", "") or "")
    box = str(getattr(d, "account", "") or "") or split_ref(ref)[0]
    out = [Touch(MAIL, BOXES, keys=_both(box))]
    if name == email_c.DRAFT_ASKED.name and ref:  # elle s'y met (``work`` : « waiting »)
        out.append(Touch(MAIL_WORK, BOXES, PREPARE, keys=(ref,)))
    if name == email_c.SENT.name and getattr(d, "draft", ""):  # un de ses brouillons est parti
        out += [Touch(MAIL_DRAFTS, BOXES, PREPARE, keys=_both(box)), Touch(ME, BOXES, OWN, owners=_both(box))]
    return out


def from_change(change: Change) -> list[Touch]:
    """Une écriture du courrier relevé, une fois validée : ses boîtes."""
    return [Touch(change.topic, BOXES, PREPARE if change.topic == MAIL_DRAFTS else READ, keys=change.accounts)]


def effect(proposal: int, frame: Any, kernel: Any, event: Any = None) -> list[Touch] | None:
    """Un effet du moteur est-il un de ses brouillons (ce que sa tranche en garde, par sa proposition) ? Ses touches,
    ou ``None``."""
    mail = _state(frame, email_p.EMAIL.name)
    seen = mail.drafts.get(proposal) if mail is not None else None
    if seen is None:
        return None
    box = _both(seen.account)
    out = [Touch(MAIL_DRAFTS, BOXES, PREPARE, keys=box), Touch(MAIL, BOXES, keys=box),
           Touch(ME, BOXES, OWN, owners=box)]
    return out + ([Touch(MAIL_WORK, BOXES, PREPARE, keys=(seen.mail,))] if seen.mail else [])


def work(ref: str, frame: Any, kernel: Any) -> list[Touch]:
    """Où elle en est d'une réponse à un mail (ADR 0306)."""
    return [Touch(MAIL_WORK, BOXES, PREPARE, keys=(ref,))]


def levels(call: Call) -> dict[str, str]:
    """Ses boîtes et son niveau sur chacune (les siennes, celles qu'on lui partage)."""
    return {key: level for key, (_, level) in mail_me.boxes(call).items()}


def owner_of(topic: str, key: str) -> str:
    """La boîte d'une clé : celle d'une référence, quand la clé nomme un mail."""
    return split_ref(key)[0] if topic == MAIL_WORK else key


def signed(changes: Any, box: str) -> None:
    """L'attente d'un code Microsoft a fini pour cette boîte (``MicrosoftSignIn.on_state`` : connectée, refusée,
    échue) : à qui la lit, et ses réglages à qui en est propriétaire. ``changes`` : le direct (``LiveChanges``)."""
    changes.add([Touch(MAIL, BOXES, keys=(box,)), Touch(SETTINGS, BOXES, OWN, owners=(box,))])


LIVE = LivePart(
    events={email_c.OWNER: _email},
    # ce que change le réglage du courrier (``kernel.params_changed``) : qui voit quoi, ce qui se règle — à toutes —,
    # les contacts compris (qui voit ceux d'une boîte suit ses propriétaires et ses partages : ``contacts.reach``)
    params={email_c.OWNER: (SETTINGS, MAIL, MAIL_DRAFTS, ME, CONTACTS)},
    # une boîte (ses serveurs, ses dossiers, sa connexion Microsoft), ses images permises (``Settings._put``, par
    # leur clé)
    saved={EMAIL_KEY: (SETTINGS, MAIL, MAIL_DRAFTS, ME, CONTACTS), MAIL_GRANTS_KEY: (SETTINGS, MAIL),
           MAIL_IMAGES_KEY: (SETTINGS, MAIL)},
    changes={MAIL: from_change, MAIL_DRAFTS: from_change},
    levels={BOXES: levels},
    owner_of={BOXES: owner_of},
    # ses boîtes telles que ses réglages les disent : lues une fois par envoi, sur la boucle
    listed={"mail": lambda port: port.accounts()},
    effects=effect,
    tasks={email_c.OWNER: work},
)
