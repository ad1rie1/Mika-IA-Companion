"""La console des messages du téléphone (ADR 0120) : ce que les téléphones lui ont montré, et les réponses qu'elle a
proposées. Lecture seule ; un texte oublié se dit « (oublié) »."""

from __future__ import annotations

from typing import Any

from mika.contracts import identity as identity_c
from mika.contracts import phone as c
from mika.kernel.frame import Frame
from mika.kernel.inspect import Block, Cell, Column, InspectContext, Note, Ref, Row, Table, Text, When
from mika.plugins.phone import PHONE, PhoneState
from mika.vocab.people import is_internal

#: les derniers messages montrés
SHOWN = 60
FORGOTTEN = "(oublié)"
APPS = {"whatsapp": "WhatsApp", "whatsapp_business": "WhatsApp Business", "messages": "Messages",
        "samsung_messages": "Messages (Samsung)"}
STATES = {c.PREPARED: "préparée", c.OFFERED: "sur le téléphone, attend un geste", "sent": "partie",
          "other": "il a écrit autre chose", "copied": "copiée (plus de notification où répondre)",
          "ignored": "ignorée", "failed": "échec", c.EXPIRED: "expirée (pas de geste à temps)"}


def _who(frame: Frame, person: str) -> Cell:
    if not person or is_internal(person):
        return Text("personne", "muted")
    name = frame.get(identity_c.IDENTITY(person)).name
    return Ref.subject("person", person, f"{name} ({person})" if name else person)


@PHONE.inspect("messages", title="Messages du téléphone", section="sens", order=46,
               description="Ce que les téléphones lui ont montré (WhatsApp, Messages), si la personne l'a permis "
                           "dans l'application Android, et les réponses qu'elle a proposées à sa place. Elle ne les "
                           "lit qu'en tête-à-tête avec la personne dont c'est le téléphone ; une réponse ne part "
                           "que si la personne appuie sur « Envoyer » sur son téléphone.")
def _inspect(s: PhoneState, frame: Frame, ctx: InspectContext) -> list[Block]:
    if not s.messages and not s.offers:
        return [Note("Aucun téléphone ne lui a montré de message. Dans l'application Android : Paramètres › « Lui "
                     "montrer mes messages ».", tone="muted")]
    shown = sorted(s.messages.values(), key=lambda m: -m.seq)[:SHOWN]
    offers = sorted(s.offers.values(), key=lambda o: -o.seq)[:SHOWN]
    refs = [r for m in shown for r in (m.text_ref, m.name_ref, m.title_ref) if r]
    refs += [o.body_ref for o in offers if o.body_ref]
    texts: dict[str, Any] = ctx.store.content(refs) if refs else {}

    def text(ref: str) -> str:
        return texts.get(ref, FORGOTTEN) if ref else ""

    received = Table(
        (Column("quand", "fit"), "personne", Column("appli", "fit"), "de", "message", Column("journal", "fit")),
        tuple(Row((When(m.at), _who(frame, m.person), APPS.get(m.source, m.source),
                   "elle-même" if m.own else (text(m.name_ref) or "—") + (f" · {text(m.title_ref)}" if m.group
                                                                         else ""),
                   Text(text(m.text_ref), clamp=300), Ref("event", str(m.seq), f"#{m.seq}"))) for m in shown),
        title="Derniers messages", empty="aucun")
    proposed = Table(
        (Column("quand", "fit"), "personne", Column("appli", "fit"), "réponse", "sort", Column("journal", "fit")),
        tuple(Row((When(o.at), _who(frame, o.person), APPS.get(o.source, o.source), Text(text(o.body_ref), clamp=300),
                   STATES.get(o.state, o.state) + (f" ({o.reason})" if o.reason else ""),
                   Ref("event", str(o.seq), f"#{o.seq}"))) for o in offers),
        title="Ses réponses proposées", empty="aucune")
    return [received, proposed]
