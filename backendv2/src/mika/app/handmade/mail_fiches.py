"""Les fiches du courrier, dessinées (ADR 0027, 0121) : une boîte aux lettres, un mail, un brouillon.

- **Une boîte** (``compte``) : si elle relève (son état, sa dernière erreur), ses dossiers et ce qu'ils ont de non lu
  (chacun mène à sa liste), comment elle y écrit, et « Écrire depuis cette boîte » ; « Sa voix » bloc par bloc.
- **Un mail** : le message à lire — ses actions, son texte, ses pièces, le détail replié (les blocs du plugin) — et, à
  côté, ce qu'elle en sait et le fil où il s'inscrit ; « Fil » et « Ce qu'elle en sait » bloc par bloc.
- **Un brouillon** : l'enveloppe de ce qui partira (de, à, copie, objet, le texte tel qu'il partira) et ce que tu peux
  en faire ; à côté, d'où il vient et son parcours ; ses deux versions, quand tu l'as retouché.

Les données sont celles du plugin ``email`` : son port (les comptes, les dossiers, le message, l'aperçu exact d'un
brouillon), sa tranche, et ses propres onglets lus pour les cartes de côté (``side_view``). Les formulaires sont ceux
que la console a préparés pour l'onglet (répondre, ranger, envoyer, retoucher…), retrouvés dans ses blocs. Un mail est
un document venu d'ailleurs : ses textes restent du texte.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from markupsafe import Markup

from mika.app.handmade import Look
from mika.app.handmade.fiche_parts import (
    STYLES,
    draw,
    faculty_head,
    head_of,
    rendered,
    safely,
    shaped,
    side_view,
    tag,
    whole,
)
from mika.inspector import render
from mika.inspector.pages.subjects import fiche_url
from mika.inspector.ui import UI, Overview
from mika.kernel.clock import DAY
from mika.plugins.email import WAITING
from mika.plugins.email.console.common import VOICE_LABEL, box_link, clip, mail_key, resolve

ACCOUNT, MAIL, DRAFT = "compte", "mail", "brouillon"
#: le fil d'un mail, à côté du message : ses premiers messages
THREAD_SHOWN = 6


def _port(ui: UI) -> Any:
    return ui.kernel.ports.get("mail")


def _state(ui: UI) -> Any:
    try:
        return ui.kernel.mind.frame().state("email")
    except KeyError:
        return None


# ── une boîte ──


def _account_state(info: Any, error: str) -> dict[str, str]:
    """Où en est une boîte, en un mot (comme sa liste le dit)."""
    if not info.enabled:
        return tag("inactive")
    if not info.ready:
        return tag("incomplète", "warn")
    if error:
        return tag("en erreur", "danger")
    return tag("prête", "ok")


class AccountFiche(Overview):
    """La fiche d'une boîte aux lettres : son en-tête, « État » dessiné ; « Sa voix » bloc par bloc."""

    slug = ""
    title = "État"
    styles = STYLES
    tabs = ("etat", "voix")

    def render(self, ui: UI, key: str) -> Markup | None:
        return None

    def head(self, ui: UI, key: str) -> Markup | None:
        got = faculty_head(ui, ACCOUNT, key)
        return head_of(ui, got, kicker="Boîte aux lettres") if got is not None else None

    def render_tab(self, ui: UI, key: str, tab: str, blocks: Sequence[Any], query: Mapping[str, str],
                   forms: Mapping[str, Any] | None = None) -> Any:
        if tab == "voix":
            return whole(ui, blocks, query, forms)
        if tab != "etat":
            return None
        port = _port(ui)
        info = port.account(key) if port is not None else None
        if info is None:
            return None
        look = Look.of(ui, DAY)
        status = port.status(key)
        folders = list(port.folders(key))
        inbox = next((f for f in folders if f.role == "inbox"), None)
        alerts = []
        if status.error:
            when = f" ({look.ago(status.error_at)})" if status.error_at else ""
            alerts.append({"tone": "danger", "text": f"Dernière erreur{when} : {status.error}"})
        if not info.ready:
            alerts.append({"tone": "warn", "text": "Il manque de quoi relever (serveur IMAP, utilisateur), ou la boîte "
                                                   "est inactive : rien n'arrive d'ici."})
        polled = sum(1 for f in folders if f.polled)
        state = _account_state(info, status.error)
        items = rendered(ui, blocks, query)
        return draw(
            "compte.html", forms=forms or {}, tables="cards", alerts=alerts,
            tiles=[{"label": "État", "value": state["text"], "sub": "elle peut envoyer" if info.can_send else
                    "lecture seule", "tone": state["tone"] if state["tone"] in ("warn", "danger") else ""},
                   {"label": "Dernier relevé", "value": look.ago(status.last_poll) if status.last_poll else "jamais",
                    "sub": "", "tone": ""},
                   {"label": "Non lus", "value": str(inbox.unseen) if inbox is not None else "—",
                    "sub": "dans la réception" if inbox is not None else "réception pas encore lue", "tone": ""},
                   {"label": "Dossiers relevés", "value": f"{polled} / {len(folders)}" if folders else "—",
                    "sub": "elle ne remarque que ceux-là", "tone": ""}],
            folders=[{"label": f.label, "name": f.name, "polled": f.polled, "unseen": f.unseen, "total": f.total,
                      "w": round(100 * f.unseen / f.total, 1) if f.total else 0.0,
                      "sync": look.ago(f.last_sync) if f.last_sync else "jamais relu",
                      "href": render.href(box_link(f.label, account=key, folder=f.name))} for f in folders],
            voice=VOICE_LABEL.get(info.voice, info.voice), sender=info.sender_name or info.display_name,
            signature=bool(info.signature.strip()), voice_tab=fiche_url(ACCOUNT, key, "voix"),
            details=list(info.details), write=[shaped(d) for d in items if d["t"] == "action"],
            box=render.href(box_link("", account=key)))


# ── un mail ──


class MailFiche(Overview):
    """La fiche d'un mail : son en-tête, « Message » dessiné (le message, ce qu'elle en sait, le fil) ; ses autres
    onglets bloc par bloc."""

    slug = ""
    title = "Message"
    styles = STYLES
    tabs = ("message", "fil", "remarque")

    def render(self, ui: UI, key: str) -> Markup | None:
        return None

    def head(self, ui: UI, key: str) -> Markup | None:
        got = faculty_head(ui, MAIL, key)
        if got is None:
            return None
        port, s = _port(ui), _state(ui)
        ref = resolve(s, port, key) if s is not None else None
        sent = ref is not None and (port is not None and port.sent_mail(ref) is not None or ref in s.sent)
        return head_of(ui, got, kicker="Mail parti de sa boîte" if sent else "Mail reçu")

    def render_tab(self, ui: UI, key: str, tab: str, blocks: Sequence[Any], query: Mapping[str, str],
                   forms: Mapping[str, Any] | None = None) -> Any:
        if tab in ("fil", "remarque"):
            return whole(ui, blocks, query, forms)
        if tab != "message":
            return None
        port, s = _port(ui), _state(ui)
        ref = resolve(s, port, key) if s is not None else None
        if ref is None:
            return None
        look = Look.of(ui, DAY)
        thread, total = [], 0
        if port is not None:
            page = safely(lambda: port.thread_page(ref, 1, THREAD_SHOWN), "fil d'un mail")
            if page is not None:
                total = page.total
                thread = [{"subject": clip(m.subject, 90) or "(sans objet)", "who": clip(m.who, 60), "sent": m.sent,
                           "when": look.day(m.date) if m.date else "", "here": m.ref == ref,
                           "href": fiche_url(MAIL, mail_key(m.ref))} for m in page.items]
        return draw("mail.html", forms=forms or {}, tables="cards",
                    message=[shaped(d) for d in rendered(ui, blocks, query)],
                    known=side_view(ui, "email", "remarque", key, "remarque"),
                    thread=thread if total > 1 else [], more=total > len(thread), total=total,
                    thread_tab=fiche_url(MAIL, key, "fil"), known_tab=fiche_url(MAIL, key, "remarque"))


# ── un brouillon ──


class DraftFiche(Overview):
    """La fiche d'un brouillon : son en-tête, « Brouillon » dessiné (l'enveloppe, ce que tu peux en faire, d'où il
    vient, son parcours) ; ses autres onglets bloc par bloc."""

    slug = ""
    title = "Brouillon"
    styles = STYLES
    tabs = ("brouillon", "pourquoi", "historique")

    def render(self, ui: UI, key: str) -> Markup | None:
        return None

    def head(self, ui: UI, key: str) -> Markup | None:
        got = faculty_head(ui, DRAFT, key)
        if got is None:
            return None
        seen = _seen(ui, key)
        why = "demandé" if seen is not None and seen.asked else "d'elle-même" if seen is not None else "écrit d'ici"
        return head_of(ui, got, kicker=f"Brouillon · {why}")

    def render_tab(self, ui: UI, key: str, tab: str, blocks: Sequence[Any], query: Mapping[str, str],
                   forms: Mapping[str, Any] | None = None) -> Any:
        if tab in ("pourquoi", "historique"):
            return whole(ui, blocks, query, forms)
        if tab != "brouillon":
            return None
        port = _port(ui)
        got = port.draft(key) if port is not None else None
        if got is None:
            return None
        seen = _seen(ui, key)
        shown = port.preview(got.id)
        answered = port.cached_one(got.reply_to) if got.reply_to else None
        items = [shaped(d) for d in rendered(ui, blocks, query)]
        waiting = seen is not None and seen.state == WAITING and got.state == "brouillon"
        history = side_view(ui, "email", "historique", key, "historique")
        return draw(
            "brouillon.html", forms=forms or {}, tables="cards", waiting=waiting,
            envelope={"from": shown.sender, "to": shown.to, "cc": shown.cc, "subject": shown.subject}
            if shown is not None else None,
            answered={"text": clip(answered.subject, 100) or "(sans objet)",
                      "href": fiche_url(MAIL, mail_key(answered.ref))} if answered is not None else None,
            blocked=shown.blocked if shown is not None else "",
            text=[d for d in items if d["t"] in ("prose", "nav") or _long(d)],
            actions=[d for d in items if d["t"] in ("action", "disclosure")],
            notes=[d for d in items if d["t"] == "note" and not _long(d) and d.get("tone") != "warn"],
            why=side_view(ui, "email", "pourquoi", key, "pourquoi"),
            history=[d for d in history if d["t"] != "grid"], versions=[d for d in history if d["t"] == "grid"])


def _long(item: dict[str, Any]) -> bool:
    """La note d'un texte long, lu par parties : elle va avec le texte."""
    return item["t"] == "note" and str(item.get("text", "")).startswith("Message long")


def _seen(ui: UI, key: str) -> Any:
    """Sa dernière proposition (``None`` : un brouillon qu'elle n'a jamais proposé)."""
    s = _state(ui)
    found = [d for d in s.drafts.values() if d.draft == key] if s is not None else []
    return max(found, key=lambda d: d.proposal) if found else None
