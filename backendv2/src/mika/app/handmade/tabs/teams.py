"""Relations & échanges › Teams : ses onglets, chacun dans sa forme (ADR 0177), alignés sur les fiches Teams déjà
dessinées (``teams_fiches.py`` : le fil en bulles, une réponse en face du message auquel elle répond).

- **Conversations** : comme une messagerie — une ligne par conversation, la plus récente d'abord : sa sorte, son
  dernier message (qui l'a écrit), l'heure ; les questions qui attendent une réponse et une réponse d'elle en
  chemin, dites. Sans extension branchée, comment la brancher.
- **Réponses** : une file à valider d'abord — celles qui attendent ton accord, chacune avec le message auquel elle
  répond et, en face, ce qu'elle a écrit, « Examiner et décider » sur sa ligne — puis, en liste, ce que les autres
  sont devenues.
- **Extension** : où elle en est (branchée, son dernier envoi), une bande de chiffres (ce qu'elle a apporté, ce qui
  attend ta décision), ton compte Teams et ce qui va avec ; comment la brancher, pas à pas.

Les données restent celles du plugin ``teams`` : ses blocs (leurs filtres, leur pagination, la bascule « Tableau »),
et, pour ce qu'ils ne disent pas, son port (le dernier message d'une conversation, le message auquel une réponse
répond) et sa tranche (une réponse en chemin, ce qui attend ta décision).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import unquote

from markupsafe import Markup

from mika.app.handmade import excerpt
from mika.app.handmade.tabs import Got, Line, Tab, blank, pairs
from mika.inspector.ui import PREFIX
from mika.plugins.teams import WAITING, under_way

STYLES = ("handmade/teams.css",)
#: les fiches Teams, telles qu'un lien du plugin y mène
CONVERSATION_LINK = f"{PREFIX}/fiche/conversation_teams/"
REPLY_LINK = f"{PREFIX}/fiche/reponse_teams/"
#: un message cité : au plus tant de lettres
CITED = 160
#: la sorte d'une conversation (le mot du plugin) → sa marque
KINDS = {"tête-à-tête": "dm", "groupe": "group", "canal": "channel", "réunion": "meeting"}


def _key(href: str, base: str) -> str:
    return unquote(href[len(base):].split("?", 1)[0]) if href.startswith(base) else ""


def _port(got: Got) -> Any:
    return got.ui.kernel.ports.get("teams")


def _state(got: Got) -> Any:
    try:
        return got.ui.kernel.mind.frame().state("teams")
    except KeyError:
        return None


def _notes(got: Got) -> list[dict[str, Any]]:
    """Ce que le plugin dit quand il n'a rien à montrer (pas branché ici, l'extension n'a rien apporté)."""
    return got.notes()


# ── Conversations ─────────────────────────────────────────────────────────


def _conversation(line: Line, port: Any, s: Any) -> dict[str, Any]:
    key = _key(line.href, CONVERSATION_LINK)
    last = None
    if port is not None and key:
        thread = port.thread(key, 1)
        if thread:
            m = thread[-1]
            last = {"who": "toi" if m.own else m.author or "quelqu'un", "text": excerpt(m.text, CITED), "own": m.own}
    title = line.text("conversation") or "sans nom"
    kind = line.text("sorte")
    questions = line.get("questions")
    return {"title": title, "initial": title[:1].upper(), "kind": kind, "mark": KINDS.get(kind, "other"),
            "href": line.href, "count": line.text("messages"), "when": line.get("le dernier"),
            "questions": None if blank(questions) else questions, "last": last,
            "under_way": bool(s is not None and key and under_way(s, key))}


def conversations(got: Got) -> Markup | None:
    """Teams › Conversations : une ligne par conversation, son dernier message, ce qui attend."""
    table = got.table("Conversations")
    if table is None:
        notes = _notes(got)
        if not notes:
            return None
        return got.draw("handmade/teams/conversations.html", t=None, items=[], notes=notes,
                        plugged=_port(got) is not None)
    port, s = _port(got), _state(got)
    items = [_conversation(x, port, s) for x in got.lines("Conversations")]
    waiting = sum(1 for x in items if x["questions"])
    return got.draw("handmade/teams/conversations.html", t=table, items=items, notes=[], plugged=True,
                    lede=(f"{waiting} avec une question sans réponse · " if waiting else "")
                    + "la plus récente d'abord ; une conversation s'ouvre sur son fil")


# ── Réponses ──────────────────────────────────────────────────────────────


def _reply(line: Line, port: Any) -> dict[str, Any]:
    key = _key(line.href, REPLY_LINK)
    draft = port.draft(key) if port is not None and key else None
    answered = port.message(draft.reply_to) if draft is not None and draft.reply_to else None
    return {
        "conversation": line.text("conversation"), "text": line.text("réponse"), "why": line.get("pourquoi"),
        "when": line.get("proposée"), "state": line.get("état"), "edited": line.get("retouche"),
        "waiting": line.tone == "warn", "href": line.href,
        "answered": {"who": answered.author or "quelqu'un", "text": excerpt(answered.text, CITED)}
        if answered is not None else None,
    }


def reponses(got: Got) -> Markup | None:
    """Teams › Réponses : celles qui attendent ton accord, chacune en face du message ; puis les autres."""
    table = got.table("Réponses")
    if table is None:
        notes = _notes(got)
        if not notes:
            return None
        return got.draw("handmade/teams/reponses.html", t=None, waiting=[], done=[], notes=notes, about="")
    port = _port(got)
    items = [_reply(x, port) for x in got.lines("Réponses")]
    about = next((n["text"] for n in got.notes() if n.get("tone") == "info"), "")
    return got.draw("handmade/teams/reponses.html", t=table, waiting=[x for x in items if x["waiting"]],
                    done=[x for x in items if not x["waiting"]], notes=[], about=about)


# ── Extension ─────────────────────────────────────────────────────────────


def extension(got: Got) -> Markup | None:
    """Teams › Extension : où elle en est, ses chiffres, ton compte ; comment la brancher."""
    fields = got.fields("L'extension")
    if fields is None:
        notes = _notes(got)
        if not notes:
            return None
        return got.draw("handmade/teams/extension.html", facts={}, notes=notes, plugged=False, band=[], how="")
    port, s = _port(got), _state(got)
    facts = pairs(fields)
    plugged = bool(port is not None and port.configured())
    conversations = len(port.conversations(200)) if plugged else 0
    waiting = sum(1 for d in s.drafts.values() if d.state == WAITING) if s is not None else 0
    band = [
        {"label": "Dernier envoi", "value": facts.get("dernier envoi de l'extension"), "sub": "de l'extension",
         "tone": "" if plugged else "warn", "href": ""},
        {"label": "Conversations", "value": {"t": "text", "text": str(conversations)},
         "sub": "qu'elle a apportées", "tone": "", "href": f"{PREFIX}/teams/conversations"},
        {"label": "Messages remarqués", "value": facts.get("messages remarqués (en tête)"),
         "sub": "qu'elle garde en tête", "tone": "", "href": ""},
        {"label": "Réponses à décider", "value": {"t": "text", "text": str(waiting)},
         "sub": "qui attendent ton accord", "tone": "warn" if waiting else "", "href": f"{PREFIX}/teams/reponses"},
    ]
    return got.draw("handmade/teams/extension.html", facts=facts, notes=[], plugged=plugged, band=band,
                    how=next((n["text"] for n in got.notes()), ""))


TABS: dict[str, Any] = {
    "teams/conversations": Tab(conversations, *STYLES),
    "teams/reponses": Tab(reponses, *STYLES),
    "teams/extension": Tab(extension, *STYLES),
}
