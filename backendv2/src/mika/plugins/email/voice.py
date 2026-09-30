"""Comment elle écrit depuis chaque boîte, et ce qu'elle voit de son courrier.

- **Sa voix** par compte (réglée par un opérateur : de confiance) : en son nom,
  en assistante, ou **à la place** de son opérateur — à la première personne,
  sans évoquer sa nature, en laissant ``[À COMPLÉTER : …]`` ce qu'elle ne sait
  pas plutôt que de l'inventer (un brouillon qui en contient ne part pas).
  Puis le ton, les consignes ; la signature est ajoutée à l'envoi.
- **Ce qu'elle voit** : ses mails non lus et ce qu'un opérateur a envoyé
  (**cités** : ce sont des données) ; ses brouillons et ce qu'ils sont
  devenus ; pendant une tâche de rédaction, le mail et son fil (cités) et ce
  que son opérateur veut y dire. Tout cela pour ses propriétaires seulement,
  ou pour elle quand elle travaille.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mika.contracts import email as c
from mika.kernel.faculty import Zone
from mika.kernel.frame import Frame
from mika.kernel.prompt import SectionBody
from mika.plugins.email import (
    EMAIL,
    FAILED,
    GONE,
    REFUSED,
    SENT_SHOWN_FOR,
    WAITING,
    EmailState,
    SentSeen,
    for_owner,
    operator_name,
    task_mail,
)
from mika.ports.mail import AccountInfo, Mail, split_ref
from mika.vocab.episodes import CONVERSATIONAL, Kind
from mika.vocab.privacy import Sensitivity

#: ce que dit une voix au plus (le ton, les consignes)
VOICE_MAX = 1500
THREAD_MAX = 3
OUTCOMES_SHOWN = 4
TALK = [*CONVERSATIONAL, Kind.STEP]
ALL = [*CONVERSATIONAL, Kind.STEP, Kind.TASK]


def voice_text(info: AccountInfo, *, owner_fallback: str = "ton opérateur") -> str:
    """Comment écrire depuis cette boîte : sa voix, son ton, ses consignes."""
    owner = info.display_name.strip() or owner_fallback
    head = f"Boîte « {info.name} » ({info.address or 'sans adresse'}) : "
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
    out: dict[str, Any] = {"texts": {}, "accounts": {}, "drafts": {}, "task": None}
    refs = [m.summary_ref for m in frame.get(c.UNREAD)[:5] if m.summary_ref]
    refs += [m.summary_ref for _, m in _recent_sent(s, frame) if m.summary_ref]
    mail = task_mail(frame)
    ask = s.asked.get(mail) if mail else None
    if ask is not None and ask.instruction_ref:
        refs.append(ask.instruction_ref)
    out["texts"] = store.content(refs) if refs else {}
    if port is not None:
        out["accounts"] = {a.key: a for a in port.accounts()}
        for d in _outcomes(s, frame):
            got = port.draft(d.draft) if d.draft else None
            if got is not None:
                out["drafts"][d.draft] = (got.to, got.subject)
        if mail:
            found = port.cached_one(mail)
            out["task"] = (found, _thread(port, found)) if found is not None else None
    return out


# ── Ce qui est arrivé (cité) ──────────────────────────────────────────────


@EMAIL.section("mails", zone=Zone.VOLATILE, episodes=TALK, trim_rank=20, title="TES MAILS NON LUS",
               untrusted=True, reads=[c.UNREAD])
def _mails(s: EmailState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    got = enrich.get("mail") or {}
    texts, accounts = got.get("texts") or {}, got.get("accounts") or {}
    if not texts or not for_owner(frame):
        return None
    several = len(accounts) > 1
    lines = []
    for m in frame.get(c.UNREAD)[:5]:
        text = texts.get(m.summary_ref)
        if text:
            flag = " (important)" if m.importance >= 0.8 else ""
            flag += " (attend une réponse)" if m.needs_reply else ""
            box = f" [{accounts[m.account].name}]" if several and m.account in accounts else ""
            lines.append(f"[{m.mail}]{box}{flag} {text}")
    for k, m in _recent_sent(s, frame):
        text = texts.get(m.summary_ref)
        if text:
            who = "toi, retouché par " + operator_name(frame, m.by) if m.edited else (
                operator_name(frame, m.by) if m.by and not m.draft else "toi")
            lines.append(f"[{k}] (parti de ta boîte, écrit par {who}) {text}")
    return SectionBody("\n".join(lines), level=int(Sensitivity.NONE)) if lines else None


# ── Ses brouillons (ce qu'elle a fait : de confiance) ─────────────────────


@EMAIL.section("drafts", zone=Zone.VOLATILE, episodes=ALL, trim_rank=30, title="TES BROUILLONS DE MAILS")
def _drafts(s: EmailState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    got = enrich.get("mail") or {}
    known = got.get("drafts") or {}
    if not for_owner(frame):
        return None
    lines = []
    for d in _outcomes(s, frame):
        to, subject = known.get(d.draft, ("?", "?"))
        what = f"Ton brouillon à {to} (« {subject} »)"
        if d.state == WAITING:
            lines.append(f"{what} attend l'accord de ton opérateur.")
        elif d.state == GONE:
            lines.append(f"{what} est parti.")
        elif d.state == REFUSED:
            note = f" : « {d.note} »" if d.note else ""
            lines.append(f"{what} a été refusé par {operator_name(frame, d.by)}{note}.")
        elif d.state == FAILED:
            lines.append(f"{what} n'a pas pu partir ({d.result or 'une erreur'}).")
    return SectionBody("\n".join(lines)) if lines else None


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
        found = (got.get("task") or (None, ()))[0]
        key = found.account if found is not None else split_ref(mail)[0]
        chosen = [accounts[key]] if key in accounts else []
    elif _pending_work(s, frame):
        chosen = [a for a in accounts.values() if a.enabled]
    else:
        return None
    text = "\n\n".join(voice_text(a) for a in chosen)
    return SectionBody(text) if text else None


# ── Une tâche de rédaction ────────────────────────────────────────────────


def _render_mail(m: Mail) -> str:
    head = [f"De : {m.sender}", f"À : {m.to}"] + ([f"Cc : {m.cc}"] if m.cc else [])
    head.append(f"Objet : {m.subject}")
    if m.attachments:
        head.append("Pièces jointes : " + ", ".join(a.name for a in m.attachments[:10]))
    return "\n".join(head) + "\n\n" + m.body[:6000]


@EMAIL.section("task_mail", zone=Zone.VOLATILE, episodes=[Kind.TASK], trim_rank=90,
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
    return SectionBody(text, level=int(Sensitivity.NONE))


@EMAIL.section("task_ask", zone=Zone.VOLATILE, episodes=[Kind.TASK], trim_rank=95,
               title="CE QUE TON OPÉRATEUR VEUT Y RÉPONDRE")
def _task_ask(s: EmailState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    mail = task_mail(frame)
    ask = s.asked.get(mail) if mail else None
    if ask is None:
        return None
    text = ((enrich.get("mail") or {}).get("texts") or {}).get(ask.instruction_ref, "") if ask.instruction_ref \
        else ""
    who = operator_name(frame, ask.by)
    said = f"{who[:1].upper()}{who[1:]} te demande de préparer une réponse à ce mail"
    return SectionBody(f"{said}. Ce qu'il faut y dire :\n{text}" if text else f"{said}.")
