"""Relever ses boîtes, trier ce qui arrive, et dire à sa propriétaire qu'un mail
important est arrivé."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from typing import Any

from mika.contracts import body as body_c
from mika.contracts import email as c
from mika.contracts import identity as identity_c
from mika.contracts import presence as presence_c
from mika.contracts import self_ as self_c
from mika.kernel.arbitration import Candidate
from mika.kernel.clock import HOUR, MINUTE
from mika.kernel.events import Content
from mika.kernel.faculty import CatchUp
from mika.kernel.frame import Frame
from mika.kernel.guards import floor
from mika.kernel.state import FrozenDict
from mika.plugins.email import (
    BUNDLE,
    EMAIL,
    MENTION_ARG,
    MENTION_TITLE,
    POLL_ASKED,
    READ,
    EmailState,
    announceable,
    keeper_name,
    name_of,
    params_of,
)
from mika.ports.llm import LLMRequest, Message
from mika.ports.preprocess import inert
from mika.vocab.affect import Emotion, named_feeling
from mika.vocab.episodes import Kind
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import Sensitivity

log = logging.getLogger(__name__)


def triage_system(name: str, persona: str) -> str:
    """La consigne du tri, pour la boîte de celle qui lit (son nom, celui de sa persona : jamais écrit ici) ; les
    émotions qu'un mail peut lui faire sont celles de son vocabulaire (ADR 0147), et ce qu'il lui fait se juge à qui
    elle est (``persona``, sa persona rendue : ``self.portrayed``, ADR 0153)."""
    return phrase("email.triage.system", name=name,
                  names=", ".join(e.value for e in Emotion if e is not Emotion.NEUTRAL)) + "\n\n" + phrase(
        "self.portrayed.intro", name=name, persona=persona)

#: les dossiers où ses consignes de tri ne rangent jamais (ADR 0243)
UNFILED = ("drafts", "sent")
#: ce qu'on garde des consignes de tri d'une boîte dans le prompt du tri
RULES_MAX = 2000
#: comment elle a quitté ses non-lus un mail que sa consigne a rangé (comme ``email_tidy``)
MOVED = "déplacé"


def triage_rules(info: Any, folders: Sequence[Any]) -> str:
    """Les consignes de tri d'une boîte, à la suite de la consigne du tri, avec ses dossiers où ranger ; rien sans
    consigne (ADR 0243)."""
    text = (getattr(info, "triage_instructions", "") or "").strip()
    if not text:
        return ""
    names = [inert(f.name, 80) for f in folders if f.role not in UNFILED]
    return phrase("email.triage.rules", instructions=inert(text, RULES_MAX),
                  folders=", ".join(names) or phrase("email.triage.no_folders"))


def filed_into(wanted: str, folders: Sequence[Any], here: str) -> str:
    """Le dossier où sa consigne range un mail : un dossier qui existe dans sa boîte (son nom exact, sinon son nom
    ou son libellé sans la casse), jamais ses brouillons ni ses envoyés, ni celui où il est déjà ; sinon rien."""
    wanted = wanted.strip()
    if not wanted:
        return ""
    allowed = [f for f in folders if f.role not in UNFILED]
    found = next((f for f in allowed if f.name == wanted), None) or next(
        (f for f in allowed if wanted.casefold() in (f.name.casefold(), getattr(f, "label", f.name).casefold())), None)
    return found.name if found is not None and found.name != here else ""


_JSON = re.compile(r"\{.*\}", re.S)
#: au-delà, un mail qu'elle annonce ne « vient » plus d'arriver : elle dit l'heure où il est arrivé
FRESH_FOR = 30 * MINUTE
#: des mails attendent encore son tri : le relevé suivant vient au plus tard dans ce délai (ADR 0240)
BEHIND_EVERY = 2 * MINUTE


def heuristic(m: Any) -> dict[str, Any]:
    """Sans le modèle (un envoi en masse, un tri en panne ou retenu par le quota) : l'importance, devinée ; jamais une
    réponse attendue (ADR 0240 : un « ? » de pied de page ou « ne pas répondre » la faisaient deviner à tort), jamais
    une émotion — ce qu'un mail lui fait, seul le modèle le dit (ADR 0147)."""
    low = f"{m.subject} {m.body[:500]}".lower()
    importance = 0.1 if m.bulk else 0.8 if any(w in low for w in ("urgent", "important", "asap")) else 0.45
    return {"importance": importance, "resume": "", "reponse": False, "emotion": "", "intensite": 0.0,
            "dossier": "", "prevenir": False}


def read_triage(text: str, fallback: dict[str, Any]) -> dict[str, Any]:
    found = _JSON.search(text or "")
    if not found:
        return fallback
    try:
        data = json.loads(found.group(0))
    except ValueError:
        return fallback
    if not isinstance(data, dict):
        return fallback
    try:
        importance = max(0.0, min(1.0, float(data.get("importance", fallback["importance"]))))
    except (TypeError, ValueError):
        importance = fallback["importance"]
    emotion, intensity = named_feeling(data.get("emotion"), data.get("intensite"))
    return {"importance": importance, "resume": str(data.get("resume") or "")[:300],
            "reponse": bool(data.get("reponse")), "emotion": emotion, "intensite": intensity,
            "dossier": str(data.get("dossier") or "")[:200], "prevenir": data.get("prevenir") is True}


@EMAIL.process("email.poll", wake_on=[*body_c.ALL, POLL_ASKED], catch_up=CatchUp.ONCE,
               max_quantum_s=1800, priority=70)
class Poll:
    def __init__(self) -> None:
        self.unconfigured = False  # rien de configuré : on revérifie d'heure en heure
        self.behind = False  # des mails attendent son tri (au-delà de ceux du dernier relevé) : on y revient vite

    def next_due(self, s: EmailState, frame: Frame, last_run: int | None) -> int | None:
        if s.poll_asked and s.poll_asked > (last_run or 0):
            return frame.now  # un opérateur l'a demandé : maintenant, même si elle dort
        if frame.get(body_c.SLEEP) is not body_c.SleepPhase.AWAKE:
            return None  # elle lira au réveil
        p = params_of(frame)
        # la cadence vit dans l'ordonnanceur : un relevé vide ne s'écrit pas (le monde n'est pas sa vie)
        every = max(p.poll_every_us, HOUR) if self.unconfigured else p.poll_every_us
        if self.behind:
            every = min(every, BEHIND_EVERY)
        return max(frame.now, (last_run or 0) + every)

    async def run(self, ctx: Any) -> None:
        port = ctx.ports.get("mail")
        frame: Frame = ctx.frame
        self.unconfigured = port is None or not port.configured()
        if self.unconfigured:
            return
        p = params_of(frame)
        known = ctx.state.mails
        fetched = await port.fetch_new(p.per_poll)
        mails = [m for m in fetched if m.ref not in known]
        accounts = {a.key: a for a in port.accounts()}
        labels = {k: a.name for k, a in accounts.items()}
        several = len(labels) > 1
        drafts: list[Any] = []
        base = triage_system(self_c.name_of(frame.get(self_c.PERSONA)), frame.get(self_c.PORTRAYED("compact"))) \
            if mails else ""
        # par boîte : la consigne du tri, ses consignes de tri à elle (ADR 0243), et ses dossiers où ranger
        boxes: dict[str, tuple[str, str, list[Any]]] = {}
        moves: list[tuple[str, str, bool]] = []  # (réf, dossier, prévenir) : rangés après l'événement
        # le budget de « Mails triés par le modèle » ne compte que les appels faits : un envoi en masse n'en prend
        # aucun ; au-delà, un mail n'est ni deviné ni remarqué : il attend le relevé suivant, sans accusé — sauf
        # quand le tri par le modèle est coupé (0) : tout se devine (ADR 0240)
        budget = p.triage_per_poll
        later: set[str] = set()
        for i, m in enumerate(mails):
            if m.account not in boxes:
                folders = port.folders(m.account)
                rules = triage_rules(accounts.get(m.account), folders)
                boxes[m.account] = (base + ("\n\n" + rules if rules else ""), rules, folders)
            system, rules, folders = boxes[m.account]
            guess = heuristic(m)
            triage, how = guess, c.TRIAGE_BULK if m.bulk else c.TRIAGE_FALLBACK
            # une boîte qui a des consignes de tri fait lire au modèle ses envois en masse aussi : ce sont eux, le
            # plus souvent, qu'on veut ranger
            if (not m.bulk or rules) and p.triage_per_poll:
                if budget <= 0:
                    later.add(m.ref)
                    continue
                budget -= 1
                req = LLMRequest(role="triage", call_id=f"{ctx.run_id}#{i}", system_stable=system,
                                 messages=(Message("user", phrase("email.header.from", who=m.sender) + "\n"
                                                   + phrase("email.header.subject", subject=m.subject)
                                                   + f"\n\n{m.body[:3000]}"),),
                                 max_tokens=300 if rules else 200, lane="background", priority=3)
                resp = await ctx.ask(req)  # un tri raté n'empêche pas de remarquer le mail : le repli le juge
                triage = read_triage(resp.text, guess) if resp is not None else guess
                how = c.TRIAGE_FALLBACK if triage is guess else c.TRIAGE_MODEL
            # ce que ses consignes de tri en font, quand le modèle l'a lu : prévenir (il devient important), ranger
            ruled = bool(rules) and how == c.TRIAGE_MODEL
            alert = ruled and triage["prevenir"]
            file_to = filed_into(triage["dossier"], folders, m.folder) if ruled else ""
            importance = max(triage["importance"], p.mention_from) if alert else triage["importance"]
            if file_to:
                moves.append((m.ref, file_to, alert))
            # l'expéditeur a choisi son nom et son objet : rendus inertes (ni titre de section, ni fin d'état
            # interne), ce résumé devient une pensée et voyage dans ses prompts
            who = inert(name_of(m.sender), 80)
            where = phrase("email.noticed.box", box=inert(labels.get(m.account, m.account), 60)) if several else ""
            summary = phrase("email.noticed.line", who=who, where=where, subject=inert(m.subject, 200)) + (
                phrase("email.noticed.summary", summary=inert(triage["resume"], 300)) if triage["resume"] else "")
            if getattr(m, "twin", False):
                summary += phrase("email.noticed.twin")
            answered = ctx.state.sent.get(m.in_reply_to) if m.in_reply_to else None
            if answered is not None:
                author = keeper_name(frame, answered.by) if answered.by and not answered.draft else \
                    phrase("email.noticed.you")
                summary = phrase("email.noticed.answer", who=author) + summary
            # ce qu'il lui fait, tel que le tri le dit : la veille le dose comme pour toute source (ADR 0147)
            drafts.append(c.NOTICED.draft(
                source="email", kind=c.MAIL, summary=Content.of(summary[:400], level=int(Sensitivity.PERSONAL)),
                pertinence=importance, emotion=triage["emotion"], intensity=triage["intensite"],
                sensitivity=int(Sensitivity.PERSONAL), bundle=BUNDLE, mail=m.ref,
                sender=m.sender[:200], address=m.address, importance=importance,
                needs_reply=bool(triage["reponse"]) and not m.bulk, account=m.account, folder=m.folder,
                triage=how, alert=alert, file_to=file_to, about=tuple(h for h in (c.address_handle(m.address),) if h), dedupe_key=f"mail:{m.ref}"))
            # déjà lu (ou répondu) ailleurs avant ce relevé : elle sait qu'il est arrivé, mais il n'est ni
            # à annoncer, ni à préparer, ni à montrer comme non lu
            if m.seen or m.answered:
                drafts.append(READ.draft(mail=m.ref, how="répondu" if m.answered else "ailleurs",
                                         dedupe_key=f"lu-ailleurs:{m.ref}"))
        # ce qui a été lu ailleurs (dans un autre client) : elle n'en parlera plus
        for ref in port.seen_elsewhere():
            seen = known.get(ref)
            if seen is not None and not seen.read:
                drafts.append(READ.draft(mail=ref, how="ailleurs", dedupe_key=f"lu-ailleurs:{ref}"))
        if drafts:
            await ctx.emit(*drafts)
        # le geste suit l'événement : ranger sur le serveur ce que sa consigne range ; elle n'en parlera plus, sauf
        # d'un mail dont elle doit prévenir (ADR 0243)
        tidied: list[Any] = []
        for ref, folder, alert in moves:
            try:
                await port.move(ref, folder)
            except (OSError, RuntimeError, ValueError) as exc:  # une erreur IMAP est une OSError ou une ImapError
                log.warning("courrier : sa consigne de tri n'a pas pu ranger un mail dans %s (%s)", folder,
                            type(exc).__name__)
                continue
            if not alert:
                tidied.append(READ.draft(mail=ref, how=MOVED, dedupe_key=f"rangé:{ref}"))
        if tidied:
            await ctx.emit(*tidied)
        # remarqués (ou déjà connus) : le relevé ne les rendra plus ; un passage interrompu avant ce point
        # (préempté, échu) les retrouve au relevé suivant, comme ceux que son tri n'a pas encore lus
        port.ack([m.ref for m in fetched if m.ref not in later])
        self.behind = bool(later)


def _owner_addresses(frame: Frame) -> list[str]:
    """Où annoncer : à chacune de ses propriétaires, l'adresse où elle est ; si aucune n'est là, celle où l'on
    peut lui écrire absente (sa messagerie : l'application de son téléphone). Une adresse par personne (deux
    écrans ne font pas deux annonces), et seulement une adresse qui parle en propriétaire (``SPEAKS_AS_OWNER``,
    comme le contenu qu'elle verra) : jamais une adresse reliée par simple recoupement. Une propriétaire présente
    l'entend : on ne fait pas sonner le téléphone d'une autre."""
    here = frame.get(presence_c.PRESENT)
    present: list[str] = []
    away: list[str] = []
    for person in frame.get(identity_c.OWNERS):
        handles = frame.get(identity_c.HANDLES(person)) or (person,)
        found = [h for h in here if h in handles and frame.get(identity_c.SPEAKS_AS_OWNER(h))]
        if found:
            present.append(found[0])
            continue
        found = [h for h in frame.get(identity_c.REACHABLE(person)) if frame.get(identity_c.SPEAKS_AS_OWNER(h))]
        if found:
            away.append(found[0])
    return present or away


def _arrived(frame: Frame, at: int) -> str:
    """Quand un mail est arrivé, comme elle le dirait (« à 10 h », « hier à 22 h 30 »)."""
    then = frame.local(at)
    days = (frame.local().date() - then.date()).days
    at = phrase("email.arrived.at_minutes", hour=then.hour, minute=f"{then.minute:02d}") if then.minute else \
        phrase("email.arrived.at", hour=then.hour)
    if days == 0:
        return at
    return phrase("email.arrived.yesterday", at=at) if days == 1 else phrase("email.arrived.day_before", at=at)


@EMAIL.propose(kinds=[Kind.INITIATIVE], reasons={c.MENTION: (0.0, 8.0)},
               reads=[presence_c.PRESENT, identity_c.OWNERS, identity_c.HANDLES, identity_c.REACHABLE,
                      identity_c.SPEAKS_AS_OWNER])
def _mention(s: EmailState, frame: Frame) -> list[Candidate]:
    """Un mail important arrivé depuis peu, pas encore dit : elle a envie de le dire à sa propriétaire, là où elle
    est, sinon sur sa messagerie (prévenir, comme un rappel échu, va où la personne peut le lire). Les droits
    tiennent à l'adresse qui parle (``SPEAKS_AS_OWNER``, comme le contenu qu'elle verra) : une adresse reliée à sa
    propriétaire par simple recoupement ne reçoit pas l'annonce. L'initiative porte les mails qu'elle annonce : ce
    sont eux, et eux seuls, qui seront signalés une fois dits."""
    p = params_of(frame)
    fresh = announceable(s, frame.now, p)
    if not fresh:
        return []
    several = len(fresh) > 1
    arrived = min(s.mails[k].at for k in fresh)
    if frame.now - arrived <= FRESH_FOR:
        brief = phrase("email.mention.fresh_many", title=MENTION_TITLE) if several else \
            phrase("email.mention.fresh_one", title=MENTION_TITLE)
    else:  # elle n'a pas pu le dire tout de suite : elle ne fait pas comme s'il arrivait
        when = _arrived(frame, arrived)
        brief = phrase("email.mention.late_many", when=when, title=MENTION_TITLE) if several else \
            phrase("email.mention.late_one", when=when, title=MENTION_TITLE)
    args = FrozenDict({"brief:email": brief, MENTION_ARG: "\n".join(fresh)})
    return [Candidate(Kind.INITIATIVE, handle, c.MENTION, p.mention_evidence,
                      resources=frozenset({floor(handle)}), args=args)
            for handle in _owner_addresses(frame)]
