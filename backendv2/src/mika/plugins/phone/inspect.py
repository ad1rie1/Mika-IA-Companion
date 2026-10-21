"""La console des messages du téléphone (ADR 0120) : ce que les téléphones lui ont montré, et les réponses qu'elle a
proposées — personne par personne, conversation par conversation (un contact, ou un groupe), et sur la fiche de
chacune (« Son téléphone », seulement s'il lui a montré quelque chose). Lecture seule ; un texte oublié se dit
« (oublié) »."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from mika.contracts import identity as identity_c
from mika.contracts import phone as c
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    Block,
    Cell,
    Column,
    InspectContext,
    Nav,
    NavItem,
    Note,
    Ref,
    Row,
    Table,
    Text,
    When,
)
from mika.plugins.phone import PHONE, Msg, Offer, PhoneState
from mika.vocab.people import is_internal

#: les conversations d'une personne montrées quand on regarde tout le monde (les autres : en la choisissant)
PER_PERSON = 8
#: les messages d'une conversation, dépliés sous elle
PER_THREAD = 30
#: les réponses proposées montrées
SHOWN = 60
FORGOTTEN = "(oublié)"
APPS = {"whatsapp": "WhatsApp", "whatsapp_business": "WhatsApp Business", "messages": "Messages",
        "samsung_messages": "Messages (Samsung)"}
STATES = {c.PREPARED: "préparée", c.OFFERED: "sur le téléphone, attend un geste", "sent": "partie",
          "other": "il a écrit autre chose", "copied": "copiée (plus de notification où répondre)",
          "ignored": "ignorée", "failed": "échec", c.EXPIRED: "expirée (pas de geste à temps)"}
#: la page de la console où vivent ces messages (son filtre par personne y mène)
PAGE = "/inspecteur/sens/messages"
#: le paramètre qui ne garde qu'une personne
WHO = "personne"


def _name(frame: Frame, person: str) -> str:
    return frame.get(identity_c.IDENTITY(person)).name or person


def _who(frame: Frame, person: str) -> Cell:
    if not person or is_internal(person):
        return Text("personne", "muted")
    return Ref.subject("person", person, _name(frame, person))


def threads(messages: Sequence[Msg]) -> list[list[Msg]]:
    """Les conversations (un contact, un groupe), la plus récente d'abord ; leurs messages aussi."""
    by: dict[tuple[str, str], list[Msg]] = {}
    for m in sorted(messages, key=lambda m: -m.seq):
        by.setdefault((m.source, m.thread), []).append(m)
    return list(by.values())


def _conversations(convs: Sequence[Sequence[Msg]], text: Callable[[str], str], *, title: str,
                   more: Ref | None = None) -> list[Block]:
    """Une ligne par conversation : avec qui, l'appli, son dernier message ; ses messages, dépliés dessous."""
    rows = []
    for msgs in convs:
        last = msgs[0]
        if last.group:
            label = text(last.title_ref) or "un groupe"
        else:
            other = next((m for m in msgs if not m.own and m.name_ref), None)
            label = text(other.name_ref) if other is not None else "—"
        said = "elle-même" if last.own else (text(last.name_ref) or "—")
        messages = Table((Column("quand", "fit"), Column("de", "fit"), "message", Column("journal", "fit")), tuple(
            Row((When(m.at), "elle-même" if m.own else (text(m.name_ref) or "—"), Text(text(m.text_ref)),
                 Ref("event", str(m.seq), f"#{m.seq}"))) for m in msgs[:PER_THREAD]),
            title=f"Ses {min(len(msgs), PER_THREAD)} derniers messages" if len(msgs) > PER_THREAD else "Ses messages")
        rows.append(Row((Text(label + (" (groupe)" if last.group else "")), APPS.get(last.source, last.source),
                         Text(f"{said} : {text(last.text_ref)}", clamp=200), When(last.at), str(len(msgs))),
                        detail=(messages,)))
    blocks: list[Block] = [Table((Column("conversation", role="title"), Column("appli", "fit"),
                                  Column("dernier message", role="body"), Column("quand", "fit"),
                                  Column("messages", "num")), tuple(rows), title=title, empty="aucune")]
    if more is not None:
        blocks.append(Nav((NavItem(more.text, more),)))
    return blocks


def _proposed(offers: Sequence[Offer], frame: Frame, text: Callable[[str], str], *, who: bool) -> Table:
    head: tuple[Any, ...] = (Column("quand", "fit"), *(("personne",) if who else ()), Column("appli", "fit"),
                             "réponse", "sort", Column("journal", "fit"))
    return Table(head, tuple(
        Row((When(o.at), *((_who(frame, o.person),) if who else ()), APPS.get(o.source, o.source),
             Text(text(o.body_ref), clamp=300), STATES.get(o.state, o.state) + (f" ({o.reason})" if o.reason else ""),
             Ref("event", str(o.seq), f"#{o.seq}"))) for o in offers),
        title="Ses réponses proposées", empty="aucune")


def _reader(ctx: InspectContext, messages: Sequence[Msg], offers: Sequence[Offer]) -> Callable[[str], str]:
    refs = [r for m in messages for r in (m.text_ref, m.name_ref, m.title_ref) if r]
    refs += [o.body_ref for o in offers if o.body_ref]
    texts: dict[str, Any] = ctx.store.content(refs) if refs else {}

    def text(ref: str) -> str:
        return texts.get(ref, FORGOTTEN) if ref else ""
    return text


@PHONE.inspect("messages", title="Messages du téléphone", section="sens", order=46,
               description="Ce que les téléphones lui ont montré (WhatsApp, Messages), si la personne l'a permis "
                           "dans l'application Android, personne par personne et conversation par conversation, et "
                           "les réponses qu'elle a proposées à sa place. Elle ne les lit qu'en tête-à-tête avec la "
                           "personne dont c'est le téléphone ; une réponse ne part que si la personne appuie sur "
                           "« Envoyer » sur son téléphone.")
def _inspect(s: PhoneState, frame: Frame, ctx: InspectContext) -> list[Block]:
    if not s.messages and not s.offers:
        return [Note("Aucun téléphone ne lui a montré de message. Dans l'application Android : Paramètres › « Lui "
                     "montrer mes messages ».", tone="muted")]
    people: dict[str, list[Msg]] = {}
    for m in sorted(s.messages.values(), key=lambda m: -m.seq):
        people.setdefault(m.person, []).append(m)
    chosen = ctx.param(WHO)
    if chosen not in people:
        chosen = ""
    shown = {chosen: people[chosen]} if chosen else people
    convs = {p: threads(msgs) for p, msgs in shown.items()}
    offers = sorted((o for o in s.offers.values() if not chosen or o.person == chosen), key=lambda o: -o.seq)[:SHOWN]
    cut = not chosen and len(people) > 1  # tout le monde : quelques conversations par personne
    text = _reader(ctx, [m for ts in convs.values() for t in (ts[:PER_PERSON] if cut else ts)
                         for m in t[:PER_THREAD]], offers)
    blocks: list[Block] = []
    if len(people) > 1:
        blocks.append(Nav((NavItem("Tout le monde", Ref("local", PAGE, "Tout le monde"), len(people), not chosen),
                           *(NavItem(_name(frame, p), Ref("local", PAGE, _name(frame, p), ((WHO, p),)), len(msgs),
                                     p == chosen) for p, msgs in people.items())), title="Personne"))
    for person, ts in convs.items():
        name = _name(frame, person) if person and not is_internal(person) else "personne"
        more = Ref("local", PAGE, f"Toutes les conversations de {name} ({len(ts)})", ((WHO, person),)) \
            if cut and len(ts) > PER_PERSON else None
        blocks += _conversations(ts[:PER_PERSON] if cut else ts, text, title=f"Le téléphone de {name}", more=more)
    blocks.append(_proposed(offers, frame, text, who=not chosen))
    return blocks


def _has_messages(s: PhoneState, person: str) -> bool:
    return any(m.person == person for m in s.messages.values()) or any(o.person == person for o in s.offers.values())


@PHONE.inspect("telephone", title="Son téléphone", subject="person", order=67, shown=_has_messages,
               description="Ce que son téléphone lui a montré (WhatsApp, Messages), conversation par conversation, "
                           "et les réponses qu'elle a proposées à sa place. Elle ne les lit qu'en tête-à-tête avec "
                           "cette personne.")
def _person_tab(s: PhoneState, frame: Frame, ctx: InspectContext) -> list[Block]:
    person = ctx.subject
    convs = threads([m for m in s.messages.values() if m.person == person])
    offers = sorted((o for o in s.offers.values() if o.person == person), key=lambda o: -o.seq)[:SHOWN]
    if not convs and not offers:
        return [Note("Son téléphone ne lui a rien montré.", tone="muted")]
    text = _reader(ctx, [m for t in convs for m in t[:PER_THREAD]], offers)
    return [*_conversations(convs, text, title="Ses conversations"), _proposed(offers, frame, text, who=False)]
