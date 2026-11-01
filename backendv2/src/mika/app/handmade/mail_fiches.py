"""Les fiches du courrier, dessinées (ADR 0027, 0121) : une boîte aux lettres, un mail, un brouillon.

- **Une boîte** (``compte``) : si elle relève (son état, sa dernière erreur), ses dossiers et ce qu'ils ont de non lu
  (chacun mène à sa liste), comment elle y écrit, et « Écrire depuis cette boîte » ; « Sa voix » : les trois façons
  d'écrire (la sienne mise en avant), l'expéditeur tel qu'il partira, la signature, le texte exact qu'elle lit.
- **Un mail** : le message à lire — ses actions, son texte, ses pièces, le détail replié (les blocs du plugin) — et, à
  côté, ce qu'elle en sait et le fil où il s'inscrit ; « Fil » en conversation (reçus à gauche, partis à droite) ;
  « Ce qu'elle en sait » : ce qu'elle en a retenu en grand, ses mesures en tuiles, sa réponse, le reste en lignes.
- **Un brouillon** : l'enveloppe de ce qui partira (de, à, copie, objet, le texte tel qu'il partira) et ce que tu peux
  en faire ; à côté, d'où il vient et son parcours ; ses deux versions, quand tu l'as retouché. « Pourquoi » : le mail
  auquel il répond, ce qu'elle en avait retenu, les consignes ; « Historique » : son parcours et ses deux versions. Un
  brouillon disparu de la boîte garde sa fiche : ce qu'elle en sait.

Les données sont celles du plugin ``email`` : son port (les comptes, les dossiers, le message, l'aperçu exact d'un
brouillon), sa tranche, et ses propres onglets lus pour les cartes de côté (``side_view``). Les formulaires sont ceux
que la console a préparés pour l'onglet (répondre, ranger, envoyer, retoucher…), retrouvés dans ses blocs. Un mail est
un document venu d'ailleurs : ses textes restent du texte.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from markupsafe import Markup

from mika.adapters.mail.compose import sender
from mika.app.handmade import Look, excerpt
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
from mika.plugins.email import READ_AFTER_S, WAITING, params_of
from mika.plugins.email.console.accounts import signin_note
from mika.plugins.email.console.common import VOICE_LABEL, box_link, clip, draft_state, mail_key, resolve

ACCOUNT, MAIL, DRAFT = "compte", "mail", "brouillon"
#: le fil d'un mail, à côté du message : ses premiers messages
THREAD_SHOWN = 6
#: les trois façons d'écrire depuis une boîte, dites pour la page « Sa voix »
VOICES = (("elle", "Elle écrit comme elle-même, sous son nom d'expéditrice ; tu n'apparais pas."),
          ("assistante", "Elle écrit pour toi, en assistante : l'expéditeur dit son nom, pour le tien."),
          ("proprietaire", "Elle écrit à ta place, à la première personne : l'expéditeur et la signature sont les "
                           "tiens."))
#: ce que dit « Ce qu'elle en sait » d'un mail : ses mesures, en tuiles (le reste, en lignes)
TILES = {"pertinence estimée": "Pertinence estimée", "ce que son attention en a gardé": "Ce que son attention en a gardé",
         "important": "Important", "réponse attendue": "Réponse attendue"}
#: un début de mail, sous le mail auquel répond un brouillon
OPENING = 420


def _pairs(item: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Les faits d'un bloc rendu, par leur libellé."""
    return {p["label"]: p["value"] for p in item.get("pairs", [])}


def _text(cell: dict[str, Any] | None) -> str:
    text = str((cell or {}).get("text") or "")
    return "" if text == "—" else text


def _alert(item: dict[str, Any]) -> dict[str, str]:
    """Une note de la faculté, dite en tête (son ton ; une note sans ton, discrète)."""
    return {"tone": item.get("tone") if item.get("tone") in ("info", "ok", "warn", "danger") else "", "text": item["text"]}


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
            return self._voice(ui, key, blocks, query) or whole(ui, blocks, query, forms)
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
        signin = port.signin(key)  # une boîte Microsoft : sa connexion (ADR 0166)
        said = signin_note(signin, look.hm(signin.until) if signin is not None and signin.until else "")
        if said is not None:
            alerts.append({"tone": said[0], "text": said[1]})
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


    def _voice(self, ui: UI, key: str, blocks: Sequence[Any], query: Mapping[str, str]) -> Markup | None:
        """« Sa voix » : les trois façons d'écrire (la sienne mise en avant), l'expéditeur tel qu'il partira, la
        signature, ce qu'elle prépare d'elle-même, et le texte exact qu'elle lit avant d'écrire."""
        port = _port(ui)
        info = port.account(key) if port is not None else None
        items = rendered(ui, blocks, query)
        facts = next((_pairs(d) for d in items if d["t"] == "fields"), None)
        if info is None or facts is None:
            return None
        her = _text(facts.get("son nom d'expéditrice"))
        reads = next((d["text"] for d in items if d["t"] == "prose" and d["title"].startswith("Ce qu'elle lit")), "")
        prepares = _text(facts.get("réponses préparées d'elle-même"))
        return draw(
            "compte_voix.html", tables="cards",
            voices=[{"label": VOICE_LABEL.get(v, v), "text": text, "on": v == info.voice} for v, text in VOICES],
            sender=sender(info, her) if her else sender(info), owner=info.display_name.strip(), her=her,
            signature=info.signature.strip(), reads=reads, prepares=prepares == "oui",
            alerts=[_alert(d) for d in items if d["t"] == "note" and d.get("tone") == "warn"],
            canals=(facts.get("pour qui, et comment elles partent") or {}).get("href", ""),
            edit=(facts.get("modifier") or {}).get("href", ""))


# ── un mail ──


class MailFiche(Overview):
    """La fiche d'un mail : son en-tête, « Message » dessiné (le message, ce qu'elle en sait, le fil) ; ses autres
    onglets bloc par bloc."""

    slug = ""
    title = "Message"
    styles = STYLES
    #: « ouvrir un mail le marque lu » (ADR 0175), appliqué par le script du courrier
    scripts = ("handmade/courrier.js",)
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
        if tab == "fil":
            return _thread(ui, key, blocks, query) or whole(ui, blocks, query, forms)
        if tab == "remarque":
            return _known(ui, blocks, query) or whole(ui, blocks, query, forms)
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
                    thread_tab=fiche_url(MAIL, key, "fil"), known_tab=fiche_url(MAIL, key, "remarque"),
                    read_after=READ_AFTER_S.get(params_of(ui.kernel.mind.frame()).read_on_open))


def _thread(ui: UI, key: str, blocks: Sequence[Any], query: Mapping[str, str]) -> Markup | None:
    """« Fil » : la conversation dans l'ordre — les mails reçus à gauche, ceux partis de sa boîte à droite, ce mail
    en évidence ; la pagination de la faculté."""
    items = rendered(ui, blocks, query)
    timeline = next((d for d in items if d["t"] == "timeline"), None)
    if timeline is None:
        return None
    entries = [{**e, "sent": e["title"].startswith("↗ ") or e["tone"] == "info",
                "title": e["title"].removeprefix("↗ "), "here": bool(e["meta"])} for e in timeline["entries"]]
    pager = timeline.get("pager") or {}
    return draw("mail_fil.html", tables="cards", entries=entries, empty=timeline["empty"], pager=timeline.get("pager"),
                paged=any(pager.get(k) for k in ("prev", "next", "older", "newer")),
                total=pager.get("total") if isinstance(pager.get("total"), int) else len(entries),
                notes=[d["text"] for d in items if d["t"] == "note"])


def _known(ui: UI, blocks: Sequence[Any], query: Mapping[str, str]) -> Markup:
    """« Ce qu'elle en sait » : ce qu'elle en a retenu en grand, ses mesures en tuiles, sa réponse (le brouillon et où
    il en est), ce qu'il faut savoir en tête, le reste en lignes."""
    out: dict[str, Any] = {"alerts": [], "quiet": [], "tiles": [], "facts": [], "facts_title": "", "quotes": [],
                           "reply": []}
    for d in rendered(ui, blocks, query):
        if d["t"] == "fields" and d["title"] == "Sa réponse":
            out["reply"] = d["pairs"]
        elif d["t"] == "fields":
            out["facts_title"] = d["title"]
            for p in d["pairs"]:
                (out["tiles"] if p["label"] in TILES else out["facts"]).append(
                    {**p, "label": TILES.get(p["label"], p["label"])})
        elif d["t"] == "prose":
            out["quotes"].append({"title": d["title"], "text": d["text"]})
        elif d["t"] == "note" and d.get("tone") != "muted":  # une demande en cours, close : en tête
            out["alerts"].append(_alert(d))
        elif d["t"] == "note":
            out["quiet"].append(d["text"])
    return draw("mail_remarque.html", tables="cards", **out)


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
        if tab == "pourquoi":
            return _why(ui, key, blocks, query) or whole(ui, blocks, query, forms)
        if tab == "historique":
            return _history(ui, blocks, query) or whole(ui, blocks, query, forms)
        if tab != "brouillon":
            return None
        port = _port(ui)
        got = port.draft(key) if port is not None else None
        if got is None:
            return _gone(ui, key)
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


def _gone(ui: UI, key: str) -> Markup | None:
    """Un brouillon que la boîte n'a plus (supprimé, la boîte vidée) mais qu'elle a proposé : sa fiche dit ce qu'elle en
    sait — où il en était, d'où il venait, son parcours ; son texte, lui, n'est plus là."""
    seen = _seen(ui, key)
    if seen is None:
        return None
    history = side_view(ui, "email", "historique", key, "historique")
    state, tone = draft_state(seen.state)
    return draw("brouillon.html", forms={}, tables="cards", gone=True, waiting=False, envelope=None, answered=None,
                blocked="", text=[], actions=[], notes=[], state={"text": state, "tone": tone},
                was_waiting=seen.state == WAITING, why=side_view(ui, "email", "pourquoi", key, "pourquoi"),
                history=[d for d in history if d["t"] != "grid"], versions=[d for d in history if d["t"] == "grid"])


def _why(ui: UI, key: str, blocks: Sequence[Any], query: Mapping[str, str]) -> Markup | None:
    """« Pourquoi » : le mail auquel il répond (son objet, qui l'a écrit, quand, son début), ce qu'elle en avait retenu,
    pourquoi elle l'a écrit (demandé, ou d'elle-même), les consignes données, la proposition au journal."""
    items = rendered(ui, blocks, query)
    facts = next((_pairs(d) for d in items if d["t"] == "fields"), None)
    if facts is None:
        return None
    port, seen = _port(ui), _seen(ui, key)
    got = port.draft(key) if port is not None else None
    ref = got.reply_to if got is not None and got.reply_to else seen.mail if seen is not None else ""
    m = port.cached_one(ref) if port is not None and ref else None
    look = Look.of(ui, DAY)
    origin = {"subject": clip(m.subject, 160) or "(sans objet)", "sender": m.sender, "href": fiche_url(MAIL, mail_key(m.ref)),
              "when": look.day(m.date) if m.date else "", "opening": excerpt(m.body, OPENING)} if m is not None else None
    link = facts.get("le mail")
    return draw("brouillon_pourquoi.html", tables="cards", origin=origin,
                missing=link["href"] if origin is None and link and link.get("href") else "",
                retained=_text(facts.get("ce qu'elle en avait retenu")), asked=bool(seen is not None and seen.asked), known=seen is not None,
                needs_reply=_text(facts.get("réponse attendue")), proposal=facts.get("la proposition"),
                asks=[{"title": d["title"], "text": d["text"]} for d in items if d["t"] == "prose"])


def _history(ui: UI, blocks: Sequence[Any], query: Mapping[str, str]) -> Markup | None:
    """« Historique » : son parcours (écrit, retouché, proposé, décidé, parti), puis ses deux versions côte à côte quand
    il a été retouché."""
    items = rendered(ui, blocks, query)
    timeline = next((d for d in items if d["t"] == "timeline"), None)
    if timeline is None:
        return None
    grid = next((d for d in items if d["t"] == "grid"), None)
    versions = [{"title": x["title"], "text": x["text"]} for x in grid["items"] if x["t"] == "prose"] if grid else []
    return draw("brouillon_historique.html", tables="cards", entries=timeline["entries"], empty=timeline["empty"],
                versions=versions)


def _long(item: dict[str, Any]) -> bool:
    """La note d'un texte long, lu par parties : elle va avec le texte."""
    return item["t"] == "note" and str(item.get("text", "")).startswith("Message long")


def _seen(ui: UI, key: str) -> Any:
    """Sa dernière proposition (``None`` : un brouillon qu'elle n'a jamais proposé)."""
    s = _state(ui)
    found = [d for d in s.drafts.values() if d.draft == key] if s is not None else []
    return max(found, key=lambda d: d.proposal) if found else None
