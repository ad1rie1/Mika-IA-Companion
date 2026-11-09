"""Connexions extérieures : ses onglets, chacun dans sa forme (ADR 0177). Les onglets de la fiche d'une personne
(« Son téléphone », « Sa position ») sont dans ``person/senses.py``, sur les mêmes morceaux.

- Flux RSS : où en est le relevé, en une phrase et une bande de chiffres (un flux en panne, en bandeau) ; puis en
  sous-onglets les derniers articles (leur pertinence, leur résumé à lire), ses flux (leur état, leur dernier relevé),
  ce qu'elle a remarqué (les titres de chaque jour), ce qui lui a fait penser à ses amies, et les mots qui la touchent.
- Caméra : ce qu'elle voit en ce moment, appareil par appareil, à côté de ses appareils (en direct ou silencieux, leur
  dernière image) ; puis ses regards, au journal.
- Dessins : ses dessins en chiffres, puis une entrée par dessin — ce qu'elle a demandé, pour qui, où il en est, ce
  qu'elle y voit ou pourquoi il a raté.
- Appareils : ses appareils à gauche (chacun filtre la page), ce qu'ils lui ont signalé à droite.
- Messages du téléphone (ADR 0120, 0123) : personne par personne, conversation par conversation (un contact, un
  groupe), ses messages en bulles comme dans les Échanges ; les réponses qu'elle a proposées et leur sort.
- Localisation (ADR 0119, 0123) : une ligne par personne (ses téléphones réunis), puis ce que les téléphones lui ont
  dit. Ces deux pages se lisent dans la tranche de leur plugin et leurs textes au magasin, comme leurs vues, qui restent
  leur source pour la console en MCP et le repli (un dessin qui échoue rend la main à leurs blocs).

Les réglages de Ses sens (les flux suivis, l'accès des appareils, la transcription) sont derrière la roue de la
destination, au bout de la barre de titre (ADR 0206) ; les liens d'une vue vers d'autres réglages ou une tâche (sa
``Nav`` : les paramètres avancés de la caméra, les fournisseurs d'images, connecter une caméra) vont dans la barre de
titre, avant elle (ADR 0176) ; sa phrase d'état (sa ``Note``) ouvre la page. Tout se lit dans les blocs que la vue du
plugin déclare : elle reste la source, pour la console en MCP comme pour le repli.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlencode

from markupsafe import Markup

from mika.app.handmade import Look, person_href
from mika.app.handmade.tabs import (
    Got,
    Line,
    Tab,
    anchored,
    blank,
    gauge,
    number,
    pairs,
    subpanes,
    text,
    tiles,
)
from mika.contracts import location as location_c
from mika.contracts import phone as phone_c
from mika.inspector.ui import env
from mika.kernel.clock import DAY
from mika.plugins.location.inspect import PAGE as POSITIONS
from mika.plugins.location.inspect import SHOWN as SAID
from mika.plugins.location.inspect import by_person
from mika.plugins.phone.inspect import APPS, FORGOTTEN, PER_PERSON, PER_THREAD, STATES, threads
from mika.plugins.phone.inspect import PAGE as MESSAGES
from mika.vocab.people import is_internal

STYLES = ("handmade/senses.css",)
#: les liens d'une page dans sa barre de titre : ses actions en boutons, ses réglages en roue
HEAD = "handmade/sens/head.html"


# ── Ce que partagent les onglets ──────────────────────────────────────────


def settings(got: Got, primary: Sequence[tuple[str, str]] = ()) -> Markup:
    """La barre de titre : les actions de la page (``primary``), puis les liens de sa ``Nav`` vers ses réglages."""
    gear = [(i["text"], i["href"]) for i in (got.nav() or {}).get("items", []) if i.get("href")]
    return got.draw(HEAD, primary=list(primary), gear=gear) if primary or gear else Markup("")


def state(got: Got) -> dict[str, Any] | None:
    """La phrase d'état de la vue : sa première note à la racine (pas celles de ses replis)."""
    note = next((b for b in got.items if b.get("t") == "note"), None)
    return {"text": note["text"], "tone": note.get("tone") or ""} if note else None


def _detail_prose(line: Line) -> str:
    return next((str(d.get("text") or "") for d in line.detail if d.get("t") == "prose"), "")


def _page(html: Markup, head: Markup) -> tuple[Markup, list[Any], Markup]:
    """Une page dessinée : son HTML, aucun bloc après lui, ses liens dans la barre de titre."""
    return html, [], head


# ── Flux RSS ──────────────────────────────────────────────────────────────

#: les sous-onglets de Flux RSS, et le paramètre de pagination qui ramène à chacun
FEED_PANES = (("flux-articles", "page"), ("flux-feeds", "pg2"), ("flux-noticed", "page_remarques"),
              ("flux-friends", "page_amies"), ("flux-touch", ""))


def _article(line: Line) -> dict[str, Any]:
    return {"title": line["titre"], "feed": line.text("flux"), "when": line.get("paru"),
            "noticed": line.text("remarqué") == "remarqué", "score": gauge(line.get("pertinence")),
            "summary": _detail_prose(line)}


def _feed(line: Line) -> dict[str, Any]:
    error = line.text("erreur")
    return {"name": line["flux"], "state": line.get("état"), "ok_at": line.get("dernier succès"),
            "error": "" if blank(line.get("erreur")) else error, "broken": line.tone == "danger",
            "read": line.text("lus"), "new": line.text("nouveaux"), "cached": line.text("relevés"),
            "noticed": line.text("remarqués"), "detail": line.rest}


def _noticed(line: Line) -> dict[str, Any]:
    return {"when": line.get("remarqué"), "feed": line.text("flux"), "text": line["ce qu'elle a remarqué"],
            "score": gauge(line.get("pertinence")), "event": line.get("journal")}


def _friend(line: Line) -> dict[str, Any]:
    told = line.get("dit")
    return {"when": line.get("quand"), "who": line.get("pensé à"), "text": line["le titre"],
            "score": gauge(line.get("pertinence")), "told": text(told) == "dit", "event": line.get("journal")}


def flux(got: Got) -> tuple[Markup, list[Any], Markup] | None:
    """Connexions extérieures › Flux RSS : le relevé, puis ses articles, ses flux, ce qu'elle remarque."""
    band = got.stats()
    noticed, friends = got.table("Ce qu'elle a remarqué"), got.table("Ce qui lui a fait penser à ses amies")
    if band is None or noticed is None or friends is None:
        return None
    articles, feeds = got.table("Derniers articles relevés"), got.table("Flux suivis")
    feed_items = [_feed(x) for x in got.lines("Flux suivis")]
    broken = [f for f in feed_items if f["broken"]]
    touch = pairs(got.fields())
    words = [w.strip() for w in text(touch.get("les mots qui la touchent")).split(",") if w.strip() not in ("", "—")]
    figures = {**band, "items": [{**s, "href": "#flux-feeds"} if s["label"] == "flux suivis" else s
                                 for s in band["items"]]}
    for t, pane in ((articles, "flux-articles"), (feeds, "flux-feeds"), (noticed, "flux-noticed"),
                    (friends, "flux-friends")):
        anchored(t, pane)
    first = next((pane for pane, param in FEED_PANES if param and param != "page" and got.query.get(param)), "")
    panes = subpanes([{"id": pane} for pane, _ in FEED_PANES], first)
    html = got.draw("handmade/sens/flux.html", state=state(got), band=figures, broken=broken, articles=articles,
                    article_items=[_article(x) for x in got.lines("Derniers articles relevés")], feeds=feeds,
                    feed_items=feed_items, noticed=noticed, chart=got.chart("Titres remarqués"),
                    noticed_items=[_noticed(x) for x in got.lines("Ce qu'elle a remarqué")], friends=friends,
                    friend_items=[_friend(x) for x in got.lines("Ce qui lui a fait penser à ses amies")],
                    kept=text(touch.get("titres remarqués (gardés)")) or "0", words=words,
                    panes=[p["id"] for p in panes])
    return _page(html, settings(got))


# ── Caméra ────────────────────────────────────────────────────────────────


def _device(line: Line) -> dict[str, Any]:
    return {"name": line.text("appareil"), "live": line.text("envoie") == "oui", "last": line.get("dernière image"),
            "mime": "" if blank(line.get("format")) else line.text("format"),
            "size": "" if blank(line.get("taille")) else line.text("taille"),
            "digest": "" if blank(line.get("empreinte")) else line.text("empreinte")}


def _view(line: Line) -> dict[str, Any]:
    fresh, notable = line.get("fraîcheur"), line.get("notable")
    return {"device": line.text("appareil"), "when": line.get("vu"), "text": line["ce qu'elle a vu"],
            "fresh": (fresh or {}).get("tone") == "ok", "fresh_word": text(fresh),
            "notable": (notable or {}).get("tone") == "warn"}


def camera(got: Got) -> tuple[Markup, list[Any], Markup] | None:
    """Connexions extérieures › Caméra : ce qu'elle voit, ses appareils, ses regards."""
    views, looks = got.table("Ce qu'elle a vu en dernier"), got.timeline("Ses regards")
    if views is None or looks is None:
        return None
    devices = got.table("Appareils")
    shown = {x.text("appareil") for x in got.lines("Appareils")}
    # une caméra que les tuiles montrent sans que le tableau en tourne la page : sa ligne vient des tuiles
    extra = [{"name": label, "live": (s["value"] or {}).get("tone") == "ok", "last": None, "mime": "", "size": "",
              "digest": "", "sub": s.get("sub") or ""}
             for label, s in tiles(got.stats("Appareils")).items() if label not in shown and devices is None]
    html = got.draw("handmade/sens/camera.html", state=state(got), views=views,
                    view_items=[_view(x) for x in got.lines("Ce qu'elle a vu en dernier")], devices=devices,
                    device_items=[_device(x) for x in got.lines("Appareils")] + extra, looks=looks)
    return _page(html, settings(got))


# ── Dessins ───────────────────────────────────────────────────────────────

#: le titre de la bande de chiffres, avant la qualité par défaut
QUALITY = "qualité par défaut : "


def _for(got: Got, key: str) -> dict[str, str]:
    """Pour qui : son nom et sa fiche (la clé seule, si elle ne la connaît pas)."""
    person = got.ui.names.person_of(key) if key else ""
    return {"name": got.ui.names.name_of(key) or key or "—", "href": person_href(person) if person else "",
            "key": key}


def _drawing(got: Got, line: Line) -> dict[str, Any]:
    status = line.get("où il en est") or {}
    failed = status.get("tone") in ("danger", "muted")
    said = line.get("ce qu'elle y voit / pourquoi il a raté")
    return {"when": line.get("demandé"), "for": _for(got, line.text("pour")), "status": status,
            "failed": failed, "quality": line.text("qualité"),
            "backend": "" if blank(line.get("fournisseur")) else line.text("fournisseur"),
            "seconds": "" if blank(line.get("durée")) else line.text("durée"),
            "prompt": line["ce qu'elle a demandé au fournisseur"], "said": None if blank(said) else said}


def dessins(got: Got) -> tuple[Markup, list[Any], Markup] | None:
    """Connexions extérieures › Dessins : ses dessins en chiffres, puis un par entrée."""
    table, band = got.table("Dessins"), got.stats("Ses dessins")
    if table is None or band is None:
        return None
    title = str(band.get("title") or "")
    quality = title.split(QUALITY, 1)[1].rstrip(")") if QUALITY in title else ""
    html = got.draw("handmade/sens/dessins.html", state=state(got), quality=quality, band={**band, "title": ""},
                    t=table, items=[_drawing(got, x) for x in got.lines("Dessins")])
    return _page(html, settings(got))


# ── Appareils ─────────────────────────────────────────────────────────────


def _sensor(line: Line, chosen: str) -> dict[str, Any]:
    name = line.get("appareil") or {}
    return {"name": text(name), "href": name.get("href") or "", "count": line.text("signaux"),
            "last": line.get("le dernier"), "on": bool(chosen) and text(name) == chosen}


def _signal(line: Line) -> dict[str, Any]:
    emotion = line.get("émotion")
    return {"when": line.get("quand"), "device": line.text("appareil"), "text": line["ce qu'il signale"],
            "score": gauge(line.get("pertinence")), "event": line.get("journal"),
            "emotion": emotion if emotion and emotion.get("t") == "swatch" else None}


def appareils(got: Got) -> tuple[Markup, list[Any], Markup] | None:
    """Connexions extérieures › Appareils : ses appareils à gauche, ce qu'ils lui ont signalé à droite."""
    signals = got.table("Ce qu")
    if signals is None:
        notes = got.notes()
        if not notes:
            return None
        return _page(got.draw("handmade/sens/appareils.html", empty=notes[0]["text"]), settings(got))
    chosen = str(got.query.get("appareil") or "")
    devices = got.table("Tous les appareils")
    total = number({"text": str((devices or {}).get("count") or 0)})
    html = got.draw("handmade/sens/appareils.html", empty="", chosen=chosen, devices=devices,
                    device_items=[_sensor(x, chosen) for x in got.lines("Tous les appareils")],
                    total=int(total or 0), signals=signals, signal_items=[_signal(x) for x in got.lines("Ce qu")])
    return _page(html, settings(got))


# ── Messages du téléphone et Localisation ─────────────────────────────────

#: le paramètre qui ne garde qu'une personne (le même que celui des vues des plugins)
WHO = "personne"


def slice_of(look: Look, owner: str) -> Any:
    try:
        return look.frame.state(owner)
    except KeyError:  # ce plugin n'est pas composé ici
        return None


def _person(look: Look, person: str) -> dict[str, str]:
    if not person or is_internal(person):
        return {"name": "personne", "href": ""}
    return {"name": look.name(person), "href": look.href(person)}


def _when(look: Look, at: int) -> str:
    """Quand : « aujourd'hui à 14:02 », « hier à 9:10 », sinon « mardi 14 oct. à 18:30 »."""
    said = look.day(at)
    return said if said.startswith(("aujourd'hui", "hier")) else f"{look.date(at)} à {look.hm(at)}"


def _link(page: str, **params: Any) -> str:
    """Une page, et ces paramètres en plus de ceux qu'elle a."""
    return page + ("&" if "?" in page else "?") + urlencode(params) if params else page


def _chips(look: Look, page: str, people: Mapping[str, int], chosen: str) -> list[dict[str, Any]]:
    """Le filtre par personne : tout le monde, puis chacune (son compte)."""
    if len(people) < 2:
        return []
    return [{"text": "Tout le monde", "href": page, "on": not chosen, "count": len(people)},
            *({"text": look.name(p), "href": f"{page}?" + urlencode({WHO: p}), "on": p == chosen, "count": n}
              for p, n in people.items())]


# ── le téléphone ──

def conversation_of(look: Look, msgs: Sequence[Any], text: Any, owner: str) -> dict[str, Any]:
    """Une conversation : avec qui, l'appli, son dernier message ; ses messages en bulles, jour par jour. ``owner`` :
    le nom de la personne dont c'est le téléphone (ce qu'elle a écrit elle-même)."""
    last = msgs[0]
    if last.group:
        label = text(last.title_ref) or "un groupe"
    else:
        other = next((m for m in msgs if not m.own and m.name_ref), None)
        label = text(other.name_ref) if other is not None else "—"
    days: list[dict[str, Any]] = []
    for m in reversed(msgs[:PER_THREAD]):  # dans l'ordre où ils ont été écrits
        day = look.date(m.at)
        if not days or days[-1]["day"] != day:
            days.append({"day": day, "messages": []})
        days[-1]["messages"].append({"mine": m.own, "text": text(m.text_ref) or FORGOTTEN, "time": look.hm(m.at),
                                     "who": "" if m.own or not m.group else text(m.name_ref)})
    said = owner if last.own else (text(last.name_ref) or "—")
    return {"label": label, "group": last.group, "app": APPS.get(last.source, last.source),
            "preview": f"{said} : {text(last.text_ref) or FORGOTTEN}", "when": _when(look, last.at),
            "count": len(msgs), "cut": max(0, len(msgs) - PER_THREAD), "days": days}


def reader_of(look: Look, msgs: Sequence[Any], offers: Sequence[Any]) -> Any:
    refs = [r for m in msgs for r in (m.text_ref, m.name_ref, m.title_ref) if r] + [o.body_ref for o in offers]
    texts = look.texts(refs)

    def text(ref: str) -> str:
        return texts.get(ref, FORGOTTEN) if ref else ""
    return text


def offers_of(look: Look, offers: Sequence[Any], text: Any) -> list[dict[str, Any]]:
    return [{"who": _person(look, o.person), "app": APPS.get(o.source, o.source), "text": text(o.body_ref),
             "state": STATES.get(o.state, o.state) + (f" ({o.reason})" if o.reason else ""),
             "tone": "ok" if o.state == "sent" else "warn" if o.state == phone_c.OFFERED else
             "danger" if o.state == "failed" else "", "when": _when(look, o.at)} for o in offers]


def messages(got: Got) -> Markup | None:
    """Connexions extérieures › Messages du téléphone : le téléphone de chaque personne, ses conversations."""
    look = Look.of(got.ui, DAY)
    s = slice_of(look, "phone")
    if s is None:
        return None
    if not s.messages and not s.offers:
        return Markup(env.get_template("handmade/sens/messages.html").render(empty=True))
    people: dict[str, list[Any]] = {}
    for m in sorted(s.messages.values(), key=lambda m: -m.seq):
        people.setdefault(m.person, []).append(m)
    chosen = str(got.query.get(WHO, ""))
    chosen = chosen if chosen in people else ""
    cut = not chosen and len(people) > 1  # tout le monde : quelques conversations par personne
    shown = {chosen: people[chosen]} if chosen else people
    convs = {p: threads(msgs) for p, msgs in shown.items()}
    offers = sorted((o for o in s.offers.values() if not chosen or o.person == chosen), key=lambda o: -o.seq)[:60]
    text = reader_of(look, [m for ts in convs.values() for t in (ts[:PER_PERSON] if cut else ts)
                          for m in t[:PER_THREAD]], offers)
    phones = [{**_person(look, p), "count": len(people[p]),
               "conversations": [conversation_of(look, t, text, look.name(p)) for t in (ts[:PER_PERSON] if cut else ts)],
               "more": len(ts) - PER_PERSON if cut and len(ts) > PER_PERSON else 0, "total": len(ts),
               "only": f"{MESSAGES}?" + urlencode({WHO: p})} for p, ts in convs.items()]
    return Markup(env.get_template("handmade/sens/messages.html").render(
        chips=_chips(look, MESSAGES, {p: len(m) for p, m in people.items()}, chosen), phones=phones,
        offers=offers_of(look, offers, text), who=not chosen))


# ── la localisation ──

def _accuracy(m: int) -> str:
    return f"à {m} m près" if m else "précision inconnue"


def fix_of(look: Look, f: Any, texts: Mapping[str, str]) -> dict[str, Any]:
    return {"place": texts.get(f.label_ref, FORGOTTEN) if f.label_ref else "", "coords": texts.get(f.coords_ref,
            FORGOTTEN), "accuracy": _accuracy(f.accuracy_m), "when": _when(look, f.fixed_at),
            "ago": look.ago(f.fixed_at), "handle": f.handle}


def said_of(look: Look, query: Mapping[str, str], person: str, page: str) -> dict[str, Any]:
    """Ce que les téléphones lui ont dit (d'une personne, ou de tous), du plus récent, par pages."""
    before = int(query.get("avant", 0) or 0) if str(query.get("avant", "")).isdigit() else 0
    got = look.ui.inspection.context().events([location_c.LOCATED, location_c.CLEARED], SAID,
                                              before=before or None, where=("person", person) if person else None)
    entries = []
    for e in got:
        d = e.data
        cleared = e.type.name == location_c.CLEARED.name
        entries.append({"when": _when(look, e.at), "who": _person(look, d.person), "cleared": cleared,
                        "place": "" if cleared or d.label is None else (d.label.text or FORGOTTEN),
                        "coords": "" if cleared else (d.coords.text or FORGOTTEN),
                        "accuracy": "" if cleared else _accuracy(int(d.accuracy_m))})
    keep = {k: v for k, v in query.items() if k not in ("avant", "flash", "onglet")}
    older = _link(page, **keep, avant=got[-1].seq) if len(got) == SAID else ""
    newer = _link(page, **keep) if before else ""
    return {"entries": entries, "older": older, "newer": newer}


def positions(got: Got) -> Markup | None:
    """Connexions extérieures › Localisation : où est chaque personne, puis ce que les téléphones lui ont dit."""
    look, query = Look.of(got.ui, DAY), got.query
    s = slice_of(look, "location")
    if s is None:
        return None
    if not s.fixes:
        return Markup(env.get_template("handmade/sens/positions.html").render(
            empty=True, said=said_of(look, query, "", POSITIONS), who=True))
    people = by_person(s)
    chosen = str(query.get(WHO, ""))
    chosen = chosen if chosen in people else ""
    shown = {chosen: people[chosen]} if chosen else people
    texts = look.texts([r for fs in shown.values() for f in fs for r in (f.coords_ref, f.label_ref)])
    where = [{**_person(look, p), **fix_of(look, fs[0], texts), "phones": len(fs),
              "others": [fix_of(look, f, texts) for f in fs[1:]]} for p, fs in shown.items()]
    return Markup(env.get_template("handmade/sens/positions.html").render(
        chips=_chips(look, POSITIONS, {p: len(fs) for p, fs in people.items()}, chosen), where=where,
        said=said_of(look, query, chosen, POSITIONS), who=not chosen))


TABS: dict[str, Any] = {
    "sens/flux": Tab(flux, *STYLES),
    "sens/camera": Tab(camera, *STYLES),
    "sens/dessins": Tab(dessins, *STYLES),
    "sens/appareils": Tab(appareils, *STYLES),
    "sens/messages": Tab(messages, *STYLES),
    "sens/positions": Tab(positions, *STYLES),
}
