"""Les fiches Teams, dessinées (ADR 0069, 0121) : une conversation et une réponse qu'elle a préparée.

- **Une conversation** : son fil en bulles — les autres à gauche, toi à droite, jour par jour —, les questions qui
  attendent une réponse, et ce qu'elle a préparé dans cette conversation (chaque réponse mène à sa fiche) ; le
  formulaire « Lui demander de préparer une réponse » reste celui de la console.
- **Une réponse** : le message auquel elle répond et, en face, exactement ce qui partira (la signature comprise), son
  parcours (proposée, décidée, posée, partie), et ce que tu peux en faire — l'envoyer, la retoucher, la refuser, la
  faire reprendre : les formulaires que la console a préparés.

Les données sont celles du plugin ``teams`` : son port (les conversations, les messages, les brouillons et leur aperçu)
et sa tranche (ce qu'elle a remarqué, ce qu'elle a proposé et ce que c'est devenu).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from markupsafe import Markup

from mika.app.handmade import Look, excerpt
from mika.app.handmade.fiche_parts import STYLES, draw, fact, rendered, shaped, tag, texts, tone
from mika.inspector.pages.subjects import fiche_url
from mika.inspector.ui import UI, Overview
from mika.kernel.clock import DAY
from mika.plugins.teams import APPROVED, EXPIRED, EXPIRER, GONE, REFUSED, WAITING, her, latest, under_way
from mika.plugins.teams.console import KIND_LABEL, MODE_LABEL, STATE_LABEL
from mika.ports.teams import to_fill

CONVERSATION = "conversation_teams"
REPLY = "reponse_teams"
#: le fil d'une conversation : ses derniers messages (comme l'onglet de la faculté)
THREAD = 60
#: ce qu'elle a préparé dans une conversation : au plus tant de réponses
DRAFTS_SHOWN = 8


def _port(ui: UI) -> Any:
    return ui.kernel.ports.get("teams")


def _state(ui: UI) -> Any:
    try:
        return ui.kernel.mind.frame().state("teams")
    except KeyError:
        return None


def _state_tag(state: str) -> dict[str, str]:
    label, value = STATE_LABEL.get(state, (state, ""))
    return tag(label, value)


def _journey(ui: UI, look: Look, seen: Any) -> list[dict[str, str]]:
    """Le parcours d'une réponse : proposée, décidée (par qui, sa note), puis ce que l'extension en a fait."""
    out = [{"what": "proposée", "when": look.ago(seen.at), "text": "à ta demande" if seen.asked else "d'elle-même",
            "tone": ""}]
    label, value = STATE_LABEL.get(seen.state, (seen.state, ""))
    if seen.state == WAITING:
        due = f"jusqu'à {look.day(seen.expires)}" if seen.expires else ""
        out.append({"what": label, "when": "", "text": due, "tone": "warn"})
        return out
    if seen.decided_at:
        note = texts(ui, (seen.note_ref,)).get(seen.note_ref, "(oubliée)") if seen.note_ref else seen.note
        refused = seen.state in (REFUSED, EXPIRED)
        by = f"par {ui.names.name_of(seen.by) or seen.by}" if seen.by and seen.by != EXPIRER else ""
        out.append({"what": label if refused else "approuvée", "when": look.ago(seen.decided_at),
                    "text": " — ".join(filter(None, (by, f"« {note} »" if note else ""))),
                    "tone": tone(value) if refused else "ok"})
        if refused:
            return out
    if seen.state != APPROVED or not seen.decided_at:
        out.append({"what": label, "when": "", "text": seen.result, "tone": tone(value)})
    return out


def _days(look: Look, messages: Sequence[Any], s: Any) -> list[dict[str, Any]]:
    """Le fil, jour par jour : chaque message en bulle — toi à droite —, ses questions marquées."""
    out: list[dict[str, Any]] = []
    for m in messages:
        day = look.date(m.at)
        if not out or out[-1]["day"] != day:
            out.append({"day": day, "messages": []})
        seen = s.messages.get(m.ref) if s is not None else None
        asks = bool(seen and seen.needs_reply)
        out[-1]["messages"].append({
            "mine": m.own, "who": "toi" if m.own else m.author or "quelqu'un", "text": m.text, "at": look.hm(m.at),
            "question": asks and not seen.answered,
            "answered": {"toi": "tu y as répondu", "elle": "sa réponse est partie"}.get(seen.answered, "")
            if asks and seen.answered else ""})
    return out


class ConversationFiche(Overview):
    """La fiche d'une conversation Teams : son en-tête, son fil dessiné en bulles."""

    slug = ""
    title = "Fil"
    styles = STYLES
    tabs = ("fil",)

    def render(self, ui: UI, key: str) -> Markup | None:
        return None

    def head(self, ui: UI, key: str) -> Markup | None:
        port = _port(ui)
        found = port.conversation(key) if port is not None else None
        if found is None:
            return None
        look = Look.of(ui, DAY)
        s = _state(ui)
        tags = []
        asking = sum(1 for m in s.messages.values() if m.conversation == key and m.needs_reply and not m.answered) \
            if s is not None else 0
        if asking:
            tags.append(tag(f"{asking} question{'s' if asking > 1 else ''} sans réponse", "warn"))
        if s is not None and under_way(s, key):
            tags.append(tag("une réponse en chemin", "info"))
        facts = [fact("messages", str(found.messages))]
        if found.last_at:
            facts.append(fact("le dernier", look.ago(found.last_at)))
        kind = KIND_LABEL.get(found.kind, "")
        return draw("tete.html", kicker="Conversation Teams" + (f" · {kind}" if kind and kind != "—" else ""),
                    title=port.title(key) or "Une conversation", lede="", tags=tags, facts=facts)

    def render_tab(self, ui: UI, key: str, tab: str, blocks: Sequence[Any], query: Mapping[str, str],
                   forms: Mapping[str, Any] | None = None) -> Any:
        if tab != "fil":
            return None
        port = _port(ui)
        if port is None or port.conversation(key) is None:
            return None
        look = Look.of(ui, DAY)
        s = _state(ui)
        thread = list(port.thread(key, THREAD))
        drafts = sorted((d for d in (s.drafts.values() if s is not None else ()) if d.conversation == key),
                        key=lambda d: -d.proposal)[:DRAFTS_SHOWN]
        mine = []
        for d in drafts:
            got = port.draft(d.draft) if d.draft else None
            mine.append({"state": _state_tag(d.state), "when": look.ago(d.at), "asked": d.asked,
                         "text": excerpt(got.body, 220) if got is not None else "(disparue)",
                         "href": fiche_url(REPLY, d.draft) if d.draft else ""})
        items = rendered(ui, blocks, query)
        return draw("teams_fil.html", forms=forms or {}, tables="cards", days=_days(look, thread, s),
                    count=len(thread), drafts=mine, under_way=s is not None and under_way(s, key),
                    ask=[shaped(d) for d in items if d["t"] in ("disclosure", "action")])


class ReplyFiche(Overview):
    """La fiche d'une réponse Teams : son en-tête, ce qui partira en face du message, ce que tu peux en faire."""

    slug = ""
    title = "Réponse"
    styles = STYLES
    tabs = ("reponse",)

    def render(self, ui: UI, key: str) -> Markup | None:
        return None

    def head(self, ui: UI, key: str) -> Markup | None:
        port, s = _port(ui), _state(ui)
        got = port.draft(key) if port is not None else None
        seen = latest(s, key) if s is not None else None
        if got is None and seen is None:
            return None
        look = Look.of(ui, DAY)
        title = port.title(got.conversation) if got is not None and port is not None else ""
        tags = [_state_tag(seen.state)] if seen is not None else []
        if got is not None and to_fill(got.body):
            tags.append(tag("à compléter", "warn"))
        if got is not None and got.edited:
            tags.append(tag("retouchée", "warn"))
        facts = []
        if seen is not None:
            facts.append(fact("proposée", look.ago(seen.at)))
            facts.append(fact("mode", MODE_LABEL.get(seen.mode, seen.mode).split(" — ")[0] or "—"))
        if got is not None:
            facts.append(fact("conversation", title or "ouvrir", fiche_url(CONVERSATION, got.conversation)))
        why = "demandée" if seen is not None and seen.asked else "d'elle-même"
        return draw("tete.html", kicker=f"Réponse Teams · {why}", title=f"Réponse dans « {title or 'une conversation'} »",
                    lede="", tags=tags, facts=facts)

    def render_tab(self, ui: UI, key: str, tab: str, blocks: Sequence[Any], query: Mapping[str, str],
                   forms: Mapping[str, Any] | None = None) -> Any:
        if tab != "reponse":
            return None
        port, s = _port(ui), _state(ui)
        got = port.draft(key) if port is not None else None
        if got is None:
            return None
        look = Look.of(ui, DAY)
        seen = latest(s, got.id) if s is not None else None
        shown = port.preview(got.id, her=her(look.frame))
        answered = port.message(got.reply_to) if got.reply_to else None
        text = got.final or (shown.text if shown is not None else got.body)
        items = rendered(ui, blocks, query)
        waiting = seen is not None and seen.state == WAITING and got.state == "brouillon"
        return draw(
            "teams_reponse.html", forms=forms or {}, tables="cards", waiting=waiting,
            answered={"who": answered.author or "quelqu'un", "text": answered.text, "at": look.ago(answered.at)}
            if answered is not None else None,
            text=text, sent=got.sent_text if got.sent_text and got.edited else "",
            blocked=shown.blocked if shown is not None and waiting else "",
            reason=got.reason, gone=seen is not None and seen.state == GONE,
            steps=_journey(ui, look, seen) if seen is not None else [],
            mode=MODE_LABEL.get(seen.mode, seen.mode) if seen is not None else "",
            conversation=fiche_url(CONVERSATION, got.conversation),
            actions=[shaped(d) for d in items if d["t"] in ("action", "disclosure")],
            notes=[d for d in items if d["t"] == "note" and not waiting])
