"""Le plugin ``phone`` : les messages du téléphone de sa propriétaire (ADR 0120).

- **Ce que le téléphone donne** : l'application Android lit les notifications de WhatsApp et de Messages, si la
  personne l'a permis (un réglage coupé par défaut), et pousse chaque message (``POST /api/phone/inbox``). La porte
  (``app/phone.py``) en fait un ``phone.received`` par message : la forme ``memory.Relayed``, que la mémoire relit
  une fois la conversation posée — ce qu'on écrit à la personne devient un souvenir, « confié » par l'expéditeur et
  par la personne qui le lui montre.
- **Les consulter** (``phone_messages``) : en tête-à-tête, avec la personne dont c'est le téléphone, et seulement ses
  messages à elle. Ce n'est pas une section : elle regarde quand la conversation s'y prête (la leçon du décor,
  ADR 0119). Tout ce qui vient du téléphone est cité.
- **Répondre à sa place** (``phone_draft``) : un brouillon (``phone.drafted``, son texte est un contenu), proposé par
  la capacité ``phone.send``, qui l'envoie au téléphone par Firebase ; c'est lui qui demande l'autorisation, et le
  geste de la personne vaut accord. Son sort revient (``phone.settled``) ; sans geste à temps, il expire.
- **L'oubli** : textes et noms sont des contenus, la personne, son adresse et l'expéditeur pour sujets ; oublier l'un
  les efface, et la tranche le retire.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from mika.contracts import identity as identity_c
from mika.contracts import phone as c
from mika.contracts import runtime as rt
from mika.kernel.builtin import SUBJECT_FORGOTTEN
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.events import Content
from mika.kernel.faculty import Faculty, ToolResult, Zone
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.operate import Preview
from mika.kernel.prompt import SectionBody
from mika.kernel.state import FrozenDict
from mika.ports.phone import COPIED, FAILED, IGNORED, OTHER, RESULTS, SENT
from mika.ports.preprocess import cite, inert
from mika.vocab import flows
from mika.vocab.episodes import Kind, is_work_target
from mika.vocab.people import clean_display_name, fold
from mika.vocab.phrasebook import family, phrase
from mika.vocab.privacy import ChannelTrust, Sensitivity

BUNDLE = "phone"
#: les messages qu'elle garde en tête (leurs textes restent au journal, en contenus)
KEEP = 500
#: les réponses proposées qu'elle garde en tête
OFFERS_KEPT = 100
#: les contacts dont elle garde la clé
CONTACTS_KEPT = 2000
LEVEL = int(Sensitivity.PERSONAL)
#: ce qu'une réponse peut faire au plus (elle part dans une notification : Firebase borne ce qu'elle porte)
BODY_MAX = 1500
#: une réponse encore en chemin (une autre ne se prépare pas dans la même conversation)
UNDER_WAY = frozenset({c.PREPARED, c.OFFERED})
#: ce qui est réglé : un sort qui arrive ensuite ne le change plus
SETTLED_STATES = frozenset({*RESULTS, c.EXPIRED})


class PhoneParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: Annotated[bool, Knob(
        label="Messages du téléphone", group="Lire",
        help="Coupé, la porte refuse ce que le téléphone pousse et plus rien ne part vers lui ; ce qu'elle a déjà lu "
             "reste (la mémoire, le journal).")] = True
    listed: Annotated[int, Knob(
        label="Messages montrés à la fois", group="Lire", lo=5, hi=60,
        help="Quand elle consulte les messages du téléphone, au plus autant de messages (les plus récents).")] = 20
    offer_ttl_us: Annotated[int, Knob(
        label="Une réponse proposée vaut", group="Répondre", lo=10 * MINUTE, hi=DAY,
        help="Passé ce délai sans geste sur le téléphone, sa réponse proposée ne part plus (la notification "
             "disparaît).")] = 2 * HOUR
    outcomes_shown_us: Annotated[int, Knob(
        label="Ce que sont devenues ses réponses, montré pendant", group="Répondre", lo=HOUR, hi=3 * DAY,
        help="Elle sait ce que sont devenues ses réponses proposées (parties, laissées…) pendant ce temps.")] = 12 * HOUR


@dataclass(frozen=True, slots=True)
class Msg:
    """Un message reçu (ou écrit par la personne) sur son téléphone : ses textes par référence."""

    seq: int
    handle: str
    person: str
    thread: str
    source: str
    sender: str
    own: bool
    group: bool
    at: int
    text_ref: str = ""
    name_ref: str = ""
    title_ref: str = ""


@dataclass(frozen=True, slots=True)
class Offer:
    """Une réponse qu'elle a préparée (``seq`` : ``phone.drafted``) et ce qu'elle est devenue."""

    seq: int
    handle: str
    person: str
    thread: str
    source: str
    reply_to: int
    to: str
    at: int
    body_ref: str = ""
    expires: int = 0
    #: la proposition (``effect.proposed``) qui l'a envoyée au téléphone
    proposal: int = 0
    state: str = c.PREPARED
    reason: str = ""
    decided_at: int = 0


@dataclass(frozen=True, slots=True)
class PhoneState:
    messages: FrozenDict[int, Msg] = field(default_factory=FrozenDict)
    #: l'empreinte d'un contact → sa clé (le nom de la première fois : un contact renommé la garde)
    contacts: FrozenDict[str, str] = field(default_factory=FrozenDict)
    offers: FrozenDict[int, Offer] = field(default_factory=FrozenDict)


PHONE = Faculty("phone", state=PhoneState, init=lambda p: PhoneState(), params=PhoneParams)
PHONE.declare(*c.ALL)
PHONE.bundle(BUNDLE, phrase("phone.bundle"))


def params(p: PhoneParams | None) -> PhoneParams:
    return p if p is not None else PhoneParams()


def params_of(frame: Frame) -> PhoneParams:
    return params(frame.env.params_of("phone", frame.root))


def _pruned(items: FrozenDict[Any, Any], keep: int) -> FrozenDict[Any, Any]:
    if len(items) <= keep:
        return items
    for k in sorted(items)[: len(items) - keep]:
        items = items.delete(k)
    return items


def _ref(content: Content | None) -> str:
    return (content.ref or "") if content is not None else ""


# ── Réducteurs ────────────────────────────────────────────────────────────


@PHONE.reducer(c.RECEIVED)
def _received(s: PhoneState, e, cx) -> PhoneState:
    d = e.data
    msg = Msg(e.seq, d.handle, d.recipient, d.thread, d.source, d.sender, d.own, d.group, d.sent_at or e.at,
              _ref(d.text), _ref(d.sender_name), _ref(d.title))
    contacts = s.contacts
    if d.sender:
        digest = d.sender.split(":", 2)[1] if d.sender.count(":") >= 2 else ""
        if digest and digest not in contacts:
            contacts = contacts.set(digest, d.sender)
            if len(contacts) > CONTACTS_KEPT:
                contacts = FrozenDict(list(contacts.items())[-CONTACTS_KEPT:])
    return replace(s, messages=_pruned(s.messages.set(e.seq, msg), KEEP), contacts=contacts)


@PHONE.reducer(c.DRAFTED)
def _drafted(s: PhoneState, e, cx) -> PhoneState:
    d = e.data
    offer = Offer(e.seq, d.handle, d.person, d.thread, d.source, d.reply_to, d.to, e.at, _ref(d.body),
                  expires=e.at + params(cx.params).offer_ttl_us)
    return replace(s, offers=_pruned(s.offers.set(e.seq, offer), OFFERS_KEPT))


def _draft_of(args_json: str) -> int:
    try:
        data = json.loads(args_json or "{}")
    except ValueError:
        return 0
    try:
        return int(data.get("draft") or 0) if isinstance(data, dict) else 0
    except (TypeError, ValueError):
        return 0


@PHONE.reducer(rt.EFFECT_PROPOSED)
def _proposed(s: PhoneState, e, cx) -> PhoneState:
    d = e.data
    if d.owner != c.OWNER or d.capability != c.SEND:
        return s
    found = s.offers.get(_draft_of(d.args_json))
    if found is None:
        return s
    return replace(s, offers=s.offers.set(found.seq, replace(found, proposal=e.seq)))


@PHONE.reducer(rt.EFFECT_EXECUTED)
def _executed(s: PhoneState, e, cx) -> PhoneState:
    """Envoyée au téléphone (elle y attend le geste de la personne), ou pas : aucun téléphone à notifier."""
    d = e.data
    found = next((o for o in s.offers.values() if o.proposal and o.proposal == d.proposal), None)
    if found is None or found.state != c.PREPARED:
        return s
    state = c.OFFERED if d.ok else FAILED
    return replace(s, offers=s.offers.set(found.seq, replace(found, state=state, reason="" if d.ok else "no_phone",
                                                            decided_at=0 if d.ok else e.at)))


@PHONE.reducer(c.SETTLED)
def _settled(s: PhoneState, e, cx) -> PhoneState:
    d = e.data
    found = s.offers.get(d.draft)
    if found is None or found.state in SETTLED_STATES or d.result not in SETTLED_STATES:
        return s
    return replace(s, offers=s.offers.set(found.seq, replace(found, state=d.result, reason=d.reason[:40],
                                                            decided_at=e.at)))


@PHONE.reducer(SUBJECT_FORGOTTEN)
def _forgotten(s: PhoneState, e, cx) -> PhoneState:
    """Oublier une personne, son adresse ou un contact retire ce qu'elle en gardait en tête (les textes, déjà, par
    leurs sujets)."""
    who = e.data.subject
    messages = FrozenDict({k: m for k, m in s.messages.items() if who not in (m.handle, m.person, m.sender)})
    offers = FrozenDict({k: o for k, o in s.offers.items() if who not in (o.handle, o.person, o.to)})
    contacts = FrozenDict({k: v for k, v in s.contacts.items() if v != who})
    if len(messages) == len(s.messages) and len(offers) == len(s.offers) and len(contacts) == len(s.contacts):
        return s
    return replace(s, messages=messages, offers=offers, contacts=contacts)


# ── Pour qui ──────────────────────────────────────────────────────────────


def offered(audience: Any) -> bool:
    """En tête-à-tête, avec une personne qui a un compte et qui parle en propriétaire : ce sont les messages de son
    téléphone à elle — jamais dans un salon, jamais à quelqu'un d'autre."""
    return bool(getattr(audience, "persons", ())) and not audience.public and not getattr(audience, "room", None) \
        and audience.trust == ChannelTrust.AUTHENTICATED.value and bool(getattr(audience, "owner", False))


def whose(frame: Frame) -> str | None:
    """La personne dont elle peut lire le téléphone dans cet épisode (celle à qui elle répond), sinon ``None``."""
    ep, aud = frame.episode, frame.audience
    target = ep.target if ep is not None else None
    if not target or is_work_target(target) or aud is None or not offered(aud) or target not in aud.persons:
        return None
    return frame.get(identity_c.PERSON(target)) or target


def her_person_name(frame: Frame, person: str) -> str:
    return clean_display_name(frame.get(identity_c.IDENTITY(person)).name) or phrase("phone.someone")


def app_name(source: str) -> str:
    apps = family("phone.apps")
    return apps.get(source, apps["other"])


def when(frame: Frame, at: int) -> str:
    then = frame.local(at)
    days = (frame.local().date() - then.date()).days
    hour, minute = then.hour, f"{then.minute:02d}"
    if days == 0:
        return phrase("phone.when.today", hour=hour, minute=minute)
    if days == 1:
        return phrase("phone.when.yesterday", hour=hour, minute=minute)
    return phrase("phone.when.date", day=f"{then.day:02d}", month=f"{then.month:02d}", hour=hour, minute=minute)


def recipient_of(s: PhoneState, texts: Mapping[str, str], thread: str, person: str) -> tuple[str, str]:
    """À qui répondre dans cette conversation : la clé du dernier contact qui y a écrit (vide pour un groupe) et le
    nom à montrer (le sien, ou celui du groupe)."""
    mine = sorted((m for m in s.messages.values() if m.thread == thread and m.person == person),
                  key=lambda m: m.seq)
    group = next((m for m in reversed(mine) if m.group and m.title_ref), None)
    if group is not None:
        title = inert(texts.get(group.title_ref) or "", 80)
        return "", phrase("phone.tools.draft.group_to", title=title) if title else phrase("phone.someone")
    last = next((m for m in reversed(mine) if not m.own and m.sender), None)
    if last is None:
        return "", phrase("phone.someone")
    return last.sender, inert(texts.get(last.name_ref) or "", 60) or phrase("phone.someone")


# ── Outils ────────────────────────────────────────────────────────────────


class MessagesArgs(BaseModel):
    contact: str = Field(default="", max_length=60, description=phrase("phone.tools.messages.contact"))
    limit: int = Field(default=15, ge=1, le=60)


class DraftArgs(BaseModel):
    message: str = Field(min_length=1, max_length=24, description=phrase("phone.tools.draft.message"))
    body: str = Field(min_length=1, max_length=BODY_MAX, description=phrase("phone.tools.draft.body"))


def _texts(ctx: Any, messages: list[Msg]) -> dict[str, str]:
    store = ctx.ports.get("store")
    refs = [r for m in messages for r in (m.text_ref, m.name_ref, m.title_ref) if r]
    return store.content(refs) if store is not None and refs else {}


def _line(frame: Frame, m: Msg, texts: Mapping[str, str], owner: str) -> str:
    who = owner if m.own else inert(texts.get(m.name_ref) or "", 60) or phrase("phone.someone")
    title = inert(texts.get(m.title_ref) or "", 80) if m.group else ""
    if title:
        who = phrase("phone.tools.messages.in_group", who=who, title=title)
    return phrase("phone.tools.messages.line", ref=c.message_ref(m.seq), when=when(frame, m.at),
                  app=app_name(m.source), who=who, text=inert(texts.get(m.text_ref) or "", 600))


@PHONE.tool("phone_messages", description=phrase("phone.tools.messages.description"), args=MessagesArgs,
            bundle=BUNDLE, episodes=[Kind.REPLY], max_calls_per_episode=3, when=offered)
async def phone_messages(args: MessagesArgs, ctx: Any) -> Any:
    frame: Frame = ctx.frame
    person = whose(frame)
    if person is None:
        return ToolResult(ok=False, content=phrase("phone.tools.messages.not_here"))
    s: PhoneState = ctx.state
    p = params_of(frame)
    mine = sorted((m for m in s.messages.values() if m.person == person), key=lambda m: m.seq)
    if not mine:
        return ToolResult(content=phrase("phone.tools.messages.none"))
    texts = _texts(ctx, mine[-KEEP:])
    wanted = " ".join(fold(args.contact).split())
    if wanted:
        threads = {m.thread for m in mine if wanted in fold(texts.get(m.name_ref) or "")
                   or wanted in fold(texts.get(m.title_ref) or "")}
        mine = [m for m in mine if m.thread in threads]
        if not mine:
            return ToolResult(content=phrase("phone.tools.messages.none_for", contact=inert(args.contact, 60)))
    shown = [m for m in mine if texts.get(m.text_ref)][-min(args.limit, p.listed):]
    if not shown:
        return ToolResult(content=phrase("phone.tools.messages.none"))
    owner = her_person_name(frame, person)
    body = "\n".join(_line(frame, m, texts, owner) for m in shown)
    return f"{phrase('phone.tools.messages.data')}\n{cite(body, 12000)}\n\n" \
           f"{phrase('phone.tools.messages.to_answer', name=owner)}"


@PHONE.tool("phone_draft", description=phrase("phone.tools.draft.description"), args=DraftArgs, bundle=BUNDLE,
            episodes=[Kind.REPLY], max_calls_per_episode=2, when=offered)
async def phone_draft(args: DraftArgs, ctx: Any) -> Any:
    frame: Frame = ctx.frame
    person = whose(frame)
    if person is None:
        return ToolResult(ok=False, content=phrase("phone.tools.messages.not_here"))
    if not params_of(frame).enabled:
        return ToolResult(ok=False, content=phrase("phone.tools.draft.disabled"))
    s: PhoneState = ctx.state
    seq = c.message_seq(args.message)
    m = s.messages.get(seq) if seq is not None else None
    if m is None or m.person != person:
        return ToolResult(ok=False, content=phrase("phone.tools.draft.unknown"))
    if any(o.thread == m.thread and o.person == person and o.state in UNDER_WAY and o.expires > frame.now
           for o in s.offers.values()):
        return ToolResult(ok=False, content=phrase("phone.tools.draft.under_way"))
    texts = _texts(ctx, [x for x in s.messages.values() if x.thread == m.thread and x.person == person])
    to_key, to_name = recipient_of(s, texts, m.thread, person)
    # récrite par l'autrice du téléphone, s'il y en a une (ADR 0124) : ce à quoi elle répond, cité
    said = f"{inert(texts.get(m.name_ref) or '', 60)} :\n{cite(texts.get(m.text_ref) or '', 2000)}"
    body = (await flows.written(ctx, flows.PHONE, args.body.strip(), said)).strip()
    commit = await ctx.emit(c.DRAFTED.draft(handle=m.handle, person=person, thread=m.thread, source=m.source,
                                            reply_to=m.seq, to=to_key, body=Content.of(body, level=LEVEL)))
    draft = commit.seqs[-1]
    owner = her_person_name(frame, person)
    app = app_name(m.source)
    summary = phrase("phone.tools.draft.summary", app=app, to=to_name, name=owner)
    await ctx.propose(rt.EFFECT_PROPOSED.draft(
        capability=c.SEND, owner=c.OWNER, args_json=json.dumps({"draft": draft}, sort_keys=True),
        summary=Content.of(summary[:400], level=LEVEL), approval=False, context="phone",
        about=tuple(dict.fromkeys(k for k in (m.handle, person, to_key) if k))))
    return phrase("phone.tools.draft.done", name=owner, app=app, to=to_name, text=body)


# ── Ce qui part ───────────────────────────────────────────────────────────


def _offer_text(args: Mapping[str, Any], ports: Mapping[str, Any]) -> tuple[Offer | None, str, str, Frame | None]:
    """La réponse proposée, son texte et à qui (ce que la notification montrera)."""
    store, frame_of = ports.get("store"), ports.get("frame")
    if store is None or frame_of is None:
        return None, "", "", None
    frame = frame_of()
    s: PhoneState = frame.state("phone")
    try:
        offer = s.offers.get(int(args.get("draft") or 0))
    except (TypeError, ValueError):
        offer = None
    if offer is None or not offer.body_ref:
        return None, "", "", frame
    texts = store.content([offer.body_ref, *(r for m in s.messages.values() if m.thread == offer.thread
                                             and m.person == offer.person for r in (m.name_ref, m.title_ref) if r)])
    _key, to = recipient_of(s, texts, offer.thread, offer.person)
    return offer, texts.get(offer.body_ref) or "", to, frame


def preview(args: Mapping[str, Any], ports: Mapping[str, Any]) -> Preview | None:
    """Exactement ce que la notification proposera d'envoyer."""
    offer, text, to, _frame = _offer_text(args, ports)
    if offer is None or not text:
        gone = phrase("phone.send.gone")
        return Preview(gone, "", blocked=gone)
    shown = phrase("phone.send.preview", app=app_name(offer.source), to=to, text=text)
    return Preview(shown, hashlib.sha256(shown.encode()).hexdigest())


@PHONE.capability("send", description=phrase("phone.send.description"), preview=preview, idempotent=True)
async def send(args: Mapping[str, Any], context: str, ports: Mapping[str, Any]) -> tuple[bool, str]:
    """L'envoyer au téléphone, qui demande l'autorisation : rien ne part d'ici vers WhatsApp ou Messages."""
    phone = ports.get("phone")
    offer, text, to, frame = _offer_text(args, ports)
    if phone is None or frame is None:
        return False, phrase("phone.send.not_plugged")
    if offer is None or not text:
        return False, phrase("phone.send.gone")
    if not params_of(frame).enabled:
        return False, phrase("phone.send.disabled")
    if offer.expires <= frame.now:
        return False, phrase("phone.send.expired")
    sent = await phone.offer(offer.handle, {"id": offer.seq, "app": offer.source, "thread": offer.thread,
                                            "to": to, "text": text, "exp": offer.expires // 1000})
    if not sent:
        return False, phrase("phone.send.no_phone")
    return True, phrase("phone.send.offered")


# ── Ce qu'elle en sait ────────────────────────────────────────────────────


def _outcomes(s: PhoneState, frame: Frame, person: str) -> list[Offer]:
    p = params_of(frame)
    return sorted((o for o in s.offers.values() if o.person == person and frame.now - (o.decided_at or o.at)
                   <= p.outcomes_shown_us), key=lambda o: -o.seq)[:4]


@PHONE.enricher("phone", episodes=[Kind.REPLY], deadline_ms=300)
async def _gather(s: PhoneState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, Any] | None:
    store = ports.get("store")
    person = whose(frame)
    if store is None or person is None:
        return None
    offers = _outcomes(s, frame, person)
    if not offers:
        return None
    threads = {o.thread for o in offers}
    refs = [r for m in s.messages.values() if m.thread in threads and m.person == person
            for r in (m.name_ref, m.title_ref) if r]
    return {"texts": store.content(refs) if refs else {}}


@PHONE.section("phone_offers", zone=Zone.VOLATILE, episodes=[Kind.REPLY], trim_rank=30,
               title=phrase("phone.offers.title"), untrusted=True)
def _offers(s: PhoneState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    person = whose(frame)
    got = enrich.get("phone")
    if person is None or got is None:
        return None
    texts = got.get("texts") or {}
    owner = her_person_name(frame, person)
    said = family("phone.offers")
    lines = []
    for o in _outcomes(s, frame, person):
        if o.state == c.OFFERED and o.expires <= frame.now:
            continue  # l'échéance va la régler
        _key, to = recipient_of(s, texts, o.thread, person)
        line = said.get(o.state)
        if line:
            lines.append(line.replace("{to}", to).replace("{app}", app_name(o.source)).replace("{name}", owner))
    return SectionBody("\n".join(lines), level=LEVEL, witness=True) if lines else None


__all__ = ["PHONE", "PhoneParams", "PhoneState", "Msg", "Offer", "offered", "COPIED", "IGNORED", "OTHER", "SENT"]

from mika.plugins.phone import expire as expire  # noqa: E402 — s'enregistre sur PHONE
from mika.plugins.phone import inspect as inspect  # noqa: E402 — s'enregistre sur PHONE
