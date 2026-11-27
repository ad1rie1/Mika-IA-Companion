"""Connexions extérieures : ses onglets, chacun dans sa forme (ADR 0177). Les morceaux des pages du téléphone et de la
localisation sont à leur domaine (``app/domains/phone/console/messages.py``, ``app/domains/maps/console/location.py``) :
ces onglets les lisent là, comme les onglets de la fiche d'une personne (« Son téléphone », « Sa position ») que
dessinent les parts du téléphone et de la carte (``app/domains/phone/console/person.py``,
``app/domains/maps/console/person.py``).

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

from mika.app.domains.maps.console.location import fix_of, said_of
from mika.app.domains.phone.console.messages import conversation_of, offers_of, reader_of
from mika.app.handmade import Look, person_href, person_link
from mika.app.handmade.person.common import state_slice
from mika.app.handmade.tabs import (
    HEAD,
    Got,
    Line,
    Tab,
    anchored,
    blank,
    gauge,
    number,
    pairs,
    state,
    subpanes,
    text,
    tiles,
)
from mika.inspector.ui import env
from mika.kernel.clock import DAY
from mika.plugins.location.inspect import PAGE as POSITIONS
from mika.plugins.location.inspect import by_person
from mika.plugins.phone.inspect import PAGE as MESSAGES
from mika.plugins.phone.inspect import PER_PERSON, PER_THREAD, threads

STYLES = ("handmade/sens.css",)


# ── Ce que partagent les onglets ──────────────────────────────────────────


def settings(got: Got, primary: Sequence[tuple[str, str]] = ()) -> Markup:
    """La barre de titre : les actions de la page (``primary``), puis les liens de sa ``Nav`` vers ses réglages."""
    gear = [(i["text"], i["href"]) for i in (got.nav() or {}).get("items", []) if i.get("href")]
    return got.draw(HEAD, primary=list(primary), gear=gear) if primary or gear else Markup("")


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


def _chips(look: Look, page: str, people: Mapping[str, int], chosen: str) -> list[dict[str, Any]]:
    """Le filtre par personne : tout le monde, puis chacune (son compte)."""
    if len(people) < 2:
        return []
    return [{"text": "Tout le monde", "href": page, "on": not chosen, "count": len(people)},
            *({"text": look.name(p), "href": f"{page}?" + urlencode({WHO: p}), "on": p == chosen, "count": n}
              for p, n in people.items())]


# ── le téléphone ──

def messages(got: Got) -> Markup | None:
    """Connexions extérieures › Messages du téléphone : le téléphone de chaque personne, ses conversations."""
    look = Look.of(got.ui, DAY)
    s = state_slice(look, "phone")
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
    phones = [{**person_link(look, p), "count": len(people[p]),
               "conversations": [conversation_of(look, t, text, look.name(p)) for t in (ts[:PER_PERSON] if cut else ts)],
               "more": len(ts) - PER_PERSON if cut and len(ts) > PER_PERSON else 0, "total": len(ts),
               "only": f"{MESSAGES}?" + urlencode({WHO: p})} for p, ts in convs.items()]
    return Markup(env.get_template("handmade/sens/messages.html").render(
        chips=_chips(look, MESSAGES, {p: len(m) for p, m in people.items()}, chosen), phones=phones,
        offers=offers_of(look, offers, text), who=not chosen))


# ── la localisation ──

def positions(got: Got) -> Markup | None:
    """Connexions extérieures › Localisation : où est chaque personne, puis ce que les téléphones lui ont dit."""
    look, query = Look.of(got.ui, DAY), got.query
    s = state_slice(look, "location")
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
    where = [{**person_link(look, p), **fix_of(look, fs[0], texts), "phones": len(fs),
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
