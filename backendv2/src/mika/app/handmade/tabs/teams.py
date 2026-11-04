"""Relations & échanges › Teams : ses onglets, chacun dans sa forme (ADR 0177), alignés sur les fiches Teams déjà
dessinées (``teams_fiches.py`` : le fil en bulles, une réponse en face du message auquel elle répond).

- **Conversations** : comme une messagerie — une ligne par conversation, la plus récente d'abord : sa sorte, son
  dernier message (qui l'a écrit), l'heure ; les questions qui attendent une réponse et une réponse d'elle en
  chemin, dites. Sans extension branchée, comment la brancher.
- **Réponses** : une file à valider d'abord — celles qui attendent ton accord, chacune avec le message auquel elle
  répond et, en face, ce qu'elle a écrit, « Examiner et décider » sur sa ligne — puis, en liste, ce que les autres
  sont devenues.
- **Extension** : une extension par compte (ADR 0186). Un compte choisi (ou le seul) : où elle en est (branchée, son
  dernier envoi), une bande de chiffres (ce qu'elle a apporté, ce qui attend ta décision), ce compte Teams et sa clé
  (la créer, la retirer) ; comment la brancher, pas à pas. Plusieurs comptes : un par ligne, chacun mène au sien.

Chaque onglet commence par le choix « Les comptes de » (tout le monde, toi, elle, chaque personne qui a un compte
Teams) puis, s'il y en a plusieurs, celui d'un compte : les puces de la faculté (``Nav``), telles quelles.

Les données restent celles du plugin ``teams`` : ses blocs (leurs filtres, leur pagination, la bascule « Tableau »),
et, pour ce qu'ils ne disent pas, son port (le dernier message d'une conversation, le message auquel une réponse
répond) et sa tranche (une réponse en chemin, ce qui attend ta décision).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import unquote, urlencode

from markupsafe import Markup

from mika.app.handmade import excerpt
from mika.app.handmade.tabs import Got, Line, Tab, blank, pairs, text
from mika.inspector.ui import PREFIX
from mika.plugins.teams import WAITING, under_way
from mika.ports.teams import split_conversation_key

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
    """Ce que le plugin dit quand il n'a rien à montrer (pas branché ici, l'extension n'a rien apporté, aucun compte à
    qui on a choisi)."""
    return got.notes()


def _navs(got: Got) -> list[dict[str, Any]]:
    """Le choix « Les comptes de », puis celui d'un compte : les puces de la faculté."""
    return got.every("nav")


# ── Conversations ─────────────────────────────────────────────────────────


def _conversation(line: Line, port: Any, s: Any) -> dict[str, Any]:
    account, key = split_conversation_key(_key(line.href, CONVERSATION_LINK))
    last = None
    if port is not None and key:
        thread = port.thread(account, key, 1)
        if thread:
            m = thread[-1]
            last = {"who": "toi" if m.own else m.author or "quelqu'un", "text": excerpt(m.text, CITED), "own": m.own}
    title = line.text("conversation") or "sans nom"
    kind = line.text("sorte")
    questions = line.get("questions")
    return {"title": title, "initial": title[:1].upper(), "kind": kind, "mark": KINDS.get(kind, "other"),
            "href": line.href, "count": line.text("messages"), "when": line.get("le dernier"),
            "questions": None if blank(questions) else questions, "last": last, "account": line.text("compte"),
            "under_way": bool(s is not None and key and under_way(s, account, key))}


def conversations(got: Got) -> Markup | None:
    """Teams › Conversations : une ligne par conversation, son dernier message, ce qui attend."""
    table = got.table("Conversations")
    if table is None:
        notes = _notes(got)
        if not notes:
            return None
        return got.draw("handmade/teams/conversations.html", t=None, items=[], notes=notes, navs=_navs(got),
                        plugged=_port(got) is not None and not got.first("note", "Aucun compte"))
    port, s = _port(got), _state(got)
    items = [_conversation(x, port, s) for x in got.lines("Conversations")]
    waiting = sum(1 for x in items if x["questions"])
    return got.draw("handmade/teams/conversations.html", t=table, items=items, notes=[], plugged=True,
                    navs=_navs(got), lede=(f"{waiting} avec une question sans réponse · " if waiting else "")
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
        return got.draw("handmade/teams/reponses.html", t=None, waiting=[], done=[], notes=notes, about="",
                        navs=_navs(got))
    port = _port(got)
    items = [_reply(x, port) for x in got.lines("Réponses")]
    about = next((n["text"] for n in got.notes() if n.get("tone") == "info"), "")
    return got.draw("handmade/teams/reponses.html", t=table, waiting=[x for x in items if x["waiting"]],
                    done=[x for x in items if not x["waiting"]], notes=[], about=about, navs=_navs(got))


# ── Extension ─────────────────────────────────────────────────────────────


def extension(got: Got) -> Markup | None:
    """Teams › Extension : l'extension d'un compte — où elle en est, ses chiffres, ce compte et sa clé ; comment la
    brancher. Plusieurs comptes : un par ligne."""
    navs = _navs(got)
    accounts = got.table("Comptes Teams")
    if accounts is not None:
        return got.draw("handmade/teams/extension.html", facts={}, notes=[], plugged=True, band=[], how="",
                        navs=navs, accounts=accounts, keys=[])
    fields = got.fields("L'extension")
    if fields is None:
        notes = _notes(got)
        if not notes:
            return None
        return got.draw("handmade/teams/extension.html", facts={}, notes=notes, plugged=False, band=[], how="",
                        navs=navs, accounts=None, keys=[])
    port, s = _port(got), _state(got)
    facts = pairs(fields)
    account = text(facts.get("clé du compte"))  # le compte que la faculté a choisi (``?compte=``, ou le seul)
    plugged = bool(port is not None and account and port.configured(account))
    conversations = len(port.conversations(200, accounts=[account])) if plugged else 0
    waiting = sum(1 for d in s.drafts.values() if d.state == WAITING and d.account == account) if s is not None else 0
    # les chiffres mènent aux onglets du même compte
    chosen = "?" + urlencode({"compte": account}) if account else ""
    band = [
        {"label": "Dernier envoi", "value": facts.get("dernier envoi de l'extension"), "sub": "de l'extension",
         "tone": "" if plugged else "warn", "href": ""},
        {"label": "Conversations", "value": {"t": "text", "text": str(conversations)},
         "sub": "qu'elle a apportées", "tone": "", "href": f"{PREFIX}/teams/conversations{chosen}"},
        {"label": "Messages remarqués", "value": facts.get("messages remarqués (en tête)"),
         "sub": "qu'elle garde en tête", "tone": "", "href": ""},
        {"label": "Réponses à décider", "value": {"t": "text", "text": str(waiting)},
         "sub": "qui attendent ton accord", "tone": "warn" if waiting else "", "href": f"{PREFIX}/teams/reponses{chosen}"},
    ]
    return got.draw("handmade/teams/extension.html", facts=facts, notes=[], plugged=plugged, band=band,
                    how=next((n["text"] for n in got.notes()), ""), navs=navs, accounts=None,
                    keys=[a for a in got.every("action") if a.get("key") in ("teams.cle", "teams.retirer_cle")])


TABS: dict[str, Any] = {
    "teams/conversations": Tab(conversations, *STYLES),
    "teams/reponses": Tab(reponses, *STYLES),
    "teams/extension": Tab(extension, *STYLES),
}
