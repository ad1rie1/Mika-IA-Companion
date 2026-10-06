"""Comment elle écrit depuis chaque boîte, et ce qu'elle voit de son courrier.

- **Sa voix** par compte (réglée par un opérateur : de confiance) : en son nom,
  en assistante, ou **à la place** de la personne qui s'occupe d'elle — à la
  première personne, sans évoquer sa nature, en laissant ``[À COMPLÉTER : …]``
  ce qu'elle ne sait pas plutôt que de l'inventer (un brouillon qui en
  contient ne part pas). Puis le ton, les consignes ; la signature est
  ajoutée à l'envoi.
- **Ce qu'elle voit** : ses mails non lus et ce qu'un opérateur a envoyé ;
  ses brouillons et ce qu'ils sont devenus ; pendant une tâche de rédaction,
  le mail et son fil, et ce qu'on a changé à ses derniers brouillons de cette
  boîte (les lignes retirées et ajoutées d'une retouche, les raisons d'un
  refus sur trente jours) : elle apprend d'une correction, pas seulement
  d'une consigne. **Tout ce qui vient d'un mail est cité** (un objet, un
  expéditeur, des destinataires : l'expéditeur les a choisis) — jamais dans
  une section de confiance. Seule sa voix, réglée par un opérateur, et ce
  qu'un opérateur lui demande d'y répondre le sont.
- **Pour qui** : ses propriétaires en privé, ou elle quand elle travaille ; un
  courrier est personnel (niveau « personnel », au titre de témoin : la
  propriétaire le reçoit, un salon jamais).
- **Quand** : c'est de l'arrière-plan. En initiative ou au travail, elle a
  tout sous les yeux ; en réponse à quelqu'un, seulement les mails
  importants, et seulement quand le ton de la personne est assez léger.
- **Ce qui est l'objet de l'épisode** (le mail qu'elle annonce, celui auquel
  elle prépare une réponse) est cité comme le reste, donc coupé en premier
  quand la place manque — mais jamais sous son plancher : elle ne rédige pas
  la réponse à un mail qu'elle ne voit plus, n'annonce pas un mail absent de
  son prompt.
"""

from __future__ import annotations

import difflib
from collections.abc import Mapping
from typing import Any

from mika.contracts import email as c
from mika.contracts import identity as identity_c
from mika.contracts import others as others_c
from mika.kernel.clock import DAY
from mika.kernel.faculty import Zone
from mika.kernel.frame import Frame
from mika.kernel.prompt import SectionBody
from mika.plugins.email import (
    EMAIL,
    FAILED,
    GONE,
    KEEPER,
    MENTION_FLOOR,
    MENTION_PROVENANCE,
    MENTION_TITLE,
    REFUSED,
    SENT_SHOWN_FOR,
    WAITING,
    DraftSeen,
    EmailState,
    SentSeen,
    announced,
    for_owner,
    keeper_name,
    keepers,
    name_of,
    params_of,
    task_mail,
)
from mika.ports.mail import AccountInfo, Draft, Mail, split_ref
from mika.ports.preprocess import inert
from mika.vocab.episodes import CONVERSATIONAL, WORKING, Kind
from mika.vocab.people import fold, is_identifiable
from mika.vocab.privacy import Sensitivity

#: ce que dit une voix au plus (le ton, les consignes)
VOICE_MAX = 1500
THREAD_MAX = 3
OUTCOMES_SHOWN = 4
TALK = [*CONVERSATIONAL, *WORKING]
ALL = [*CONVERSATIONAL, *WORKING, Kind.TASK]
#: un courrier est personnel ; sa propriétaire le reçoit (témoin), un salon jamais
LEVEL = int(Sensitivity.PERSONAL)
BACKGROUND = "TES MAILS NON LUS — de l'arrière-plan : réponds d'abord à ce qu'on vient de te dire"
#: le mail auquel elle prépare une réponse : ses en-têtes et le début de son texte restent, quoi qu'il arrive
TASK_MAIL_FLOOR = 1500
#: pendant une tâche de rédaction, ses dernières retouches et ses derniers refus (avec leur raison) dans cette boîte
EDITS_SHOWN = 3
#: ce que dit une retouche au plus (ses lignes retirées puis ajoutées)
EDIT_MAX = 400
#: un refus et sa raison lui servent encore à écrire pendant trente jours (« TES BROUILLONS » : deux)
REFUSALS_SHOWN_FOR = 30 * DAY


def voice_text(info: AccountInfo, *, owner_fallback: str = KEEPER) -> str:
    """Comment écrire depuis cette boîte : sa voix, son ton, ses consignes."""
    owner = info.display_name.strip() or owner_fallback
    head = f"Boîte « {inert(info.name, 80)} » ({inert(info.address, 120) or 'sans adresse'}) : "
    if info.voice == "proprietaire":
        head += (f"tu y écris **à la place** de {owner}, à la première personne, comme cette personne le ferait "
                 f"(le mail part signé de son nom) ; tu n'évoques ni toi ni ta nature. Ce que {owner} saurait et que "
                 "tu ne sais pas (une date, un chiffre, un engagement), tu le laisses en [À COMPLÉTER : …] au lieu "
                 "de l'inventer : un brouillon qui en contient ne peut pas partir tel quel.")
    elif info.voice == "assistante":
        head += (f"tu y écris en assistante de {owner} : en ton nom, pour {owner}, et tu le dis simplement "
                 f"(« je vous réponds pour {owner} »). Tu ne promets rien en son nom que tes consignes ne "
                 "permettent pas.")
    else:
        head += "tu y écris en ton nom."
    lines = [head]
    if info.tone.strip():
        lines.append(f"Ton : {info.tone.strip()[:VOICE_MAX]}")
    if info.instructions.strip():
        lines.append(f"Consignes : {info.instructions.strip()[:VOICE_MAX]}")
    if info.signature.strip():
        lines.append("La signature est ajoutée à l'envoi : ne l'écris pas.")
    return "\n".join(lines)


def _pending_work(s: EmailState, frame: Frame) -> bool:
    """Elle a de quoi écrire : un mail qui attend une réponse, une demande, un brouillon en cours."""
    return bool(s.asked) or any(d.state == WAITING for d in s.drafts.values()) \
        or any(m.needs_reply for m in frame.get(c.UNREAD)[:10])


def _recent_sent(s: EmailState, frame: Frame) -> list[tuple[str, SentSeen]]:
    return sorted(((k, m) for k, m in s.sent.items() if frame.now - m.at <= SENT_SHOWN_FOR),
                  key=lambda kv: -kv[1].seq)[:3]


def _outcomes(s: EmailState, frame: Frame) -> list[Any]:
    return sorted((d for d in s.drafts.values() if d.state == WAITING
                   or (d.state in (GONE, REFUSED, FAILED) and frame.now - (d.decided_at or d.at) <= SENT_SHOWN_FOR)),
                  key=lambda d: -d.proposal)[:OUTCOMES_SHOWN]


def _refused(s: EmailState, frame: Frame, box: str) -> list[DraftSeen]:
    """Ses brouillons de cette boîte refusés avec une raison, sur trente jours — sauf ceux que « TES
    BROUILLONS DE MAILS » montre déjà."""
    shown = {d.proposal for d in _outcomes(s, frame)}
    return sorted((d for d in s.drafts.values() if d.state == REFUSED and d.account == box
                   and (d.note_ref or d.note) and d.proposal not in shown
                   and frame.now - (d.decided_at or d.at) <= REFUSALS_SHOWN_FOR),
                  key=lambda d: -d.proposal)[:EDITS_SHOWN]


def _task_box(mail: str, found: Mail | None) -> str:
    """La boîte d'une tâche de rédaction : celle du mail, sinon celle que dit sa référence."""
    return found.account if found is not None else split_ref(mail)[0]


def light(frame: Frame) -> bool:
    """Le courrier est de l'arrière-plan : en réponse à quelqu'un, il ne vient que si le ton du
    moment de la personne est assez léger (une initiative, un travail : toujours)."""
    ep = frame.episode
    if ep is None or ep.kind != Kind.REPLY:
        return True
    if not ep.target or not is_identifiable(ep.target):
        return False
    reading = frame.get(others_c.MIND(frame.get(identity_c.PERSON(ep.target))))
    return reading.current_valence >= params_of(frame).background_from


def _shown_unread(frame: Frame) -> list[c.MailView]:
    """Les mails non lus qu'elle a sous les yeux : tous (cinq) en initiative ou au travail ; en
    réponse à quelqu'un, les importants seulement, et rien si la conversation est lourde. Ceux qu'une
    initiative annonce ont leur propre section."""
    told = set(announced(frame))
    unread = [m for m in frame.get(c.UNREAD) if m.mail not in told]
    ep = frame.episode
    if ep is not None and ep.kind == Kind.REPLY:
        if not light(frame):
            return []
        p = params_of(frame)
        unread = [m for m in unread if m.importance >= p.mention_from]
    return unread[:5]


def _thread(port: Any, mail: Mail) -> list[Mail]:
    """Ce à quoi ce mail répond (du plus récent au plus ancien), dans le cache."""
    out: list[Mail] = []
    parent = mail.in_reply_to
    while parent and len(out) < THREAD_MAX:
        ref = f"{mail.account}:{parent}" if mail.account else parent
        found = port.cached_one(ref)
        if found is None:
            gone = port.sent_mail(parent)
            if gone is None:
                break
            out.append(Mail(gone.message_id, "toi (depuis cette boîte)", "", gone.subject, gone.date, gone.body,
                            to=gone.to, in_reply_to=split_ref(gone.in_reply_to)[1], account=mail.account))
            parent = split_ref(gone.in_reply_to)[1]
            continue
        out.append(found)
        parent = found.in_reply_to
    return out


@EMAIL.enricher("mail", episodes=ALL, deadline_ms=500)
async def _gather(s: EmailState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, Any] | None:
    store, port = ports.get("store"), ports.get("mail")
    if store is None or not for_owner(frame):
        return None
    out: dict[str, Any] = {"texts": {}, "accounts": {}, "drafts": {}, "task": None, "edits": [], "refused": []}
    refs = [m.summary_ref for m in _shown_unread(frame) if m.summary_ref]
    refs += [m.summary_ref for m in _announced_unread(frame) if m.summary_ref]
    refs += [m.summary_ref for _, m in _recent_sent(s, frame) if m.summary_ref]
    refs += [d.note_ref for d in _outcomes(s, frame) if d.note_ref]
    mail = task_mail(frame)
    ask = s.asked.get(mail) if mail else None
    if ask is not None and ask.instruction_ref:
        refs.append(ask.instruction_ref)
    found = port.cached_one(mail) if port is not None and mail else None
    if mail:  # ce qu'on a refusé de ses brouillons de cette boîte, et pourquoi
        out["refused"] = _refused(s, frame, _task_box(mail, found))
        refs += [d.note_ref for d in out["refused"] if d.note_ref]
    out["texts"] = store.content(refs) if refs else {}
    if port is not None:
        out["accounts"] = {a.key: a for a in port.accounts()}
        for d in [*_outcomes(s, frame), *out["refused"]]:
            got = port.draft(d.draft) if d.draft else None
            if got is not None:
                out["drafts"][d.draft] = (got.to, got.subject)
        if mail:
            out["task"] = (found, _thread(port, found)) if found is not None else None
            out["edits"] = port.recent_edits(_task_box(mail, found), EDITS_SHOWN)
    return out


def _announced_unread(frame: Frame) -> list[c.MailView]:
    """Les mails qu'annonce l'initiative en cours, s'ils sont toujours non lus, dans l'ordre de l'annonce."""
    told = announced(frame)
    if not told:
        return []
    unread = {m.mail: m for m in frame.get(c.UNREAD)}
    return [unread[ref] for ref in told if ref in unread]


# ── Ce qui est arrivé (cité) ──────────────────────────────────────────────


@EMAIL.section("mail_mention", zone=Zone.VOLATILE, episodes=[Kind.INITIATIVE], trim_rank=90, floor_chars=MENTION_FLOOR,
               title=MENTION_TITLE, untrusted=True, reads=[c.UNREAD])
def _mention_section(s: EmailState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """Le mail qu'elle va annoncer à sa propriétaire : l'objet de l'initiative (cité). Sa provenance
    (``mail:<référence>``) dit, une fois l'énoncé écrit, ce qu'elle a annoncé : c'est cela, et cela seul, qui
    sera signalé."""
    mails = _announced_unread(frame)
    if not mails or not for_owner(frame):
        return None
    texts = (enrich.get("mail") or {}).get("texts") or {}
    lines = [f"[{m.mail}] {inert(texts.get(m.summary_ref) or f'Un mail de {name_of(m.sender)}')}" for m in mails]
    return SectionBody("\n".join(lines), level=LEVEL, witness=True,
                       provenance=tuple(f"{MENTION_PROVENANCE}{m.mail}" for m in mails))


@EMAIL.section("mails", zone=Zone.VOLATILE, episodes=TALK, trim_rank=20, title="TES MAILS NON LUS",
               untrusted=True, reads=[c.UNREAD, others_c.MIND, identity_c.PERSON])
def _mails(s: EmailState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    got = enrich.get("mail") or {}
    texts, accounts = got.get("texts") or {}, got.get("accounts") or {}
    if not texts or not for_owner(frame):
        return None
    several = len(accounts) > 1
    lines = []
    for m in _shown_unread(frame):
        text = texts.get(m.summary_ref)
        if text:
            flag = " (important)" if m.importance >= 0.8 else ""
            flag += " (attend une réponse)" if m.needs_reply else ""
            box = f" [{inert(accounts[m.account].name, 60)}]" if several and m.account in accounts else ""
            lines.append(f"[{m.mail}]{box}{flag} {inert(text)}")
    for k, m in _recent_sent(s, frame):
        text = texts.get(m.summary_ref)
        if text:
            who = "toi, retouché par " + keeper_name(frame, m.by) if m.edited else (
                keeper_name(frame, m.by) if m.by and not m.draft else "toi")
            lines.append(f"[{k}] (parti de ta boîte, écrit par {who}) {inert(text)}")
    if not lines:
        return None
    ep = frame.episode
    title = BACKGROUND if ep is not None and ep.kind == Kind.REPLY else None
    return SectionBody("\n".join(lines), level=LEVEL, witness=True, title=title)


# ── Ses brouillons : ce qu'elle a fait, mais à qui et à quel propos vient d'un mail (cité) ─


@EMAIL.section("drafts", zone=Zone.VOLATILE, episodes=ALL, trim_rank=30, title="TES BROUILLONS DE MAILS",
               untrusted=True)
def _drafts(s: EmailState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    got = enrich.get("mail") or {}
    known, texts = got.get("drafts") or {}, got.get("texts") or {}
    if not for_owner(frame):
        return None
    lines = []
    for d in _outcomes(s, frame):
        to, subject = known.get(d.draft, ("?", "?"))
        what = f"Ton brouillon à {inert(to, 120)} (« {inert(subject, 160)} »)"
        if d.state == WAITING:
            lines.append(f"{what} attend l'accord de {keepers(frame)}.")
        elif d.state == GONE:
            lines.append(f"{what} est parti.")
        elif d.state == REFUSED:
            said = texts.get(d.note_ref, "") if d.note_ref else d.note
            note = f" : « {inert(said, 300)} »" if said else ""
            lines.append(f"{what} a été refusé par {keeper_name(frame, d.by)}{note}.")
        elif d.state == FAILED:
            lines.append(f"{what} n'a pas pu partir ({inert(d.result, 200) or 'une erreur'}).")
    return SectionBody("\n".join(lines), level=LEVEL, witness=True) if lines else None


# ── Sa voix (réglée par un opérateur : de confiance) ──────────────────────


@EMAIL.section("voice", zone=Zone.VOLATILE, episodes=ALL, trim_rank=60,
               title="COMMENT TU ÉCRIS DEPUIS TES BOÎTES")
def _voice(s: EmailState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    got = enrich.get("mail") or {}
    accounts: dict[str, AccountInfo] = got.get("accounts") or {}
    if not accounts or not for_owner(frame):
        return None
    mail = task_mail(frame)
    if mail:
        key = _task_box(mail, (got.get("task") or (None, ()))[0])
        chosen = [accounts[key]] if key in accounts else []
    elif _pending_work(s, frame):
        chosen = [a for a in accounts.values() if a.enabled]
    else:
        return None
    text = "\n\n".join(voice_text(a) for a in chosen)
    return SectionBody(text) if text else None


# ── Une tâche de rédaction ────────────────────────────────────────────────


def _render_mail(m: Mail) -> str:
    head = [f"De : {inert(m.sender, 200)}", f"À : {inert(m.to, 300)}"] + ([f"Cc : {inert(m.cc, 300)}"] if m.cc else [])
    head.append(f"Objet : {inert(m.subject, 300)}")
    if m.attachments:
        head.append("Pièces jointes : " + ", ".join(inert(a.name, 80) for a in m.attachments[:10]))
    if m.twin:
        head.append("(attention : un autre mail de cette boîte porte le même identifiant — l'un des deux peut "
                    "être une imitation)")
    return "\n".join(head) + "\n\n" + m.body[:6000]


@EMAIL.section("task_mail", zone=Zone.VOLATILE, episodes=[Kind.TASK], trim_rank=90, floor_chars=TASK_MAIL_FLOOR,
               title="LE MAIL AUQUEL TU PRÉPARES UNE RÉPONSE", untrusted=True)
def _task_mail(s: EmailState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    got = enrich.get("mail") or {}
    found = got.get("task")
    if not task_mail(frame) or found is None:
        return None
    mail, thread = found
    text = f"[{task_mail(frame)}]\n" + _render_mail(mail)
    for older in thread:
        text += f"\n\n— plus tôt dans le fil —\n{_render_mail(older)[:2000]}"
    return SectionBody(text, level=LEVEL, witness=True)


@EMAIL.section("task_ask", zone=Zone.VOLATILE, episodes=[Kind.TASK], trim_rank=95,
               title="CE QU'ON TE DEMANDE D'Y RÉPONDRE")
def _task_ask(s: EmailState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    mail = task_mail(frame)
    ask = s.asked.get(mail) if mail else None
    if ask is None:
        return None
    text = ((enrich.get("mail") or {}).get("texts") or {}).get(ask.instruction_ref, "") if ask.instruction_ref \
        else ""
    who = keeper_name(frame, ask.by)
    said = f"{who[:1].upper()}{who[1:]} te demande de préparer une réponse à ce mail"
    return SectionBody(f"{said}. Ce qu'il faut y dire :\n{text}" if text else f"{said}.")


# ── Ce qu'on change à ses brouillons (cité : des bouts de mails) ──────────


EDITS_TITLE = "CE QU'ON CHANGE À TES BROUILLONS"


def _change(before: str, after: str) -> str:
    """Ce qu'une retouche a changé, en mots : ses lignes retirées puis ajoutées (blancs ignorés), borné."""
    old = [" ".join(line.split()) for line in before.splitlines() if line.strip()]
    new = [" ".join(line.split()) for line in after.splitlines() if line.strip()]
    lines: list[str] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag in ("delete", "replace"):
            lines += [f"a retiré : {inert(line, EDIT_MAX)}" for line in old[i1:i2]]
        if tag in ("insert", "replace"):
            lines += [f"a ajouté : {inert(line, EDIT_MAX)}" for line in new[j1:j2]]
    text = "\n".join(lines)
    return text if len(text) <= EDIT_MAX else text[:EDIT_MAX - 1].rstrip() + "…"


def _edits_title(names: set[str]) -> str:
    """« CE QU'ADRIEN CHANGE À TES BROUILLONS » (élidé devant une voyelle) ; plusieurs personnes : « on »."""
    if len(names) != 1:
        return EDITS_TITLE
    name = next(iter(names))
    head = "CE QU'" if fold(name)[:1] in ("a", "e", "i", "o", "u") else "CE QUE "
    return f"{head}{name.upper()} CHANGE À TES BROUILLONS"


@EMAIL.section("edits", zone=Zone.VOLATILE, episodes=[Kind.TASK], trim_rank=40, title=EDITS_TITLE, untrusted=True)
def _edits(s: EmailState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """Pendant une tâche de rédaction, ce qu'on a changé à ses derniers brouillons de cette boîte : les lignes
    qu'une retouche a retirées et ajoutées avant l'envoi, la raison d'un refus. Un brouillon parti tel quel
    n'y figure pas ; une autre boîte ne la change pas."""
    got = enrich.get("mail") or {}
    if not task_mail(frame) or not for_owner(frame):
        return None
    known, texts = got.get("drafts") or {}, got.get("texts") or {}
    lines: list[str] = []
    names: set[str] = set()
    edits: list[Draft] = got.get("edits") or []
    for d in edits:
        change = _change(d.original_body, d.body)
        if change:
            name = keeper_name(frame, d.edited_by)
            names.add(name)
            lines.append(f"Ton brouillon « {inert(d.subject, 160)} » : {name} l'a retouché avant l'envoi.\n{change}")
    for r in got.get("refused") or []:
        said = texts.get(r.note_ref, "") if r.note_ref else r.note
        if said:
            name = keeper_name(frame, r.by)
            names.add(name)
            subject = known.get(r.draft, ("", ""))[1]
            what = f"Ton brouillon « {inert(subject, 160)} »" if subject else "Un de tes brouillons"
            lines.append(f"{what} a été refusé par {name} : « {inert(said, 300)} »")
    if not lines:
        return None
    return SectionBody("\n\n".join(lines), level=LEVEL, witness=True, title=_edits_title(names))
