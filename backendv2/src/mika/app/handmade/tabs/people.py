"""Relations & échanges › Personnes : sa page d'entrée, « Vue d'ensemble » (ADR 0121), et ses onglets, chacun dans sa
forme (ADR 0177). Ses onglets disent une personne comme la vue d'ensemble — son initiale de la couleur de ce qu'elle
ressent envers elle, sa présence, ce qu'elle est pour elle — et montrent chacun ce que sa faculté sait de plus.

- **Vue d'ensemble** (``/inspecteur/personnes``, ``PeoplePage``, une page à part, dans le cadre de la console) : les
  gens qu'elle connaît. La destination Personnes avait trois onglets, un par faculté : l'annuaire (``identity``), les
  liens (``social``), les présents (``presence``). « Qui connaît-elle, et où en est-elle avec chacun ? » les traverse :
  cette page les croise, une carte par personne — ce qu'elle est pour elle, ce qu'elle ressent envers elle,
  l'attachement, ce qui se passe entre elles (en ligne, une réponse attendue, un silence qui pèse), ce qu'elle en
  sait —, avec qui est là en ce moment et qui lui manque. C'est ici, et seulement ici, qu'on cherche quelqu'un (par son
  nom ou un moyen de communication) et qu'on filtre par proximité : l'Annuaire et Liens se parcourent, et le titre
  « En ligne » de la bande mène à Présents (pas d'onglet qui répète un filtre, ADR 0176 ; un ancien ``?presence=``
  est ignoré). Les trois onglets des facultés suivent dans la barre, la même sur ses quatre pages (``Destination.lead``).
  Elle se relit seule (``handmade/live.js``).
- **Annuaire** : une entrée par personne, en deux colonnes sur un grand écran — par où elle lui écrit (chacun de ses
  moyens de communication et ce que son canal prouve), la certitude, depuis quand elle la connaît, son dernier
  message ; ses échanges et son lien à un clic.
- **Liens** : un bandeau si quelqu'un lui manque, une bande de chiffres, puis les liens rangés par proximité (proches,
  amitiés, connaissances, pas encore de lien) — chacun avec son échelon, s'il est déclaré ou vécu, le rythme de leurs
  échanges, le silence sur une jauge dont la moitié dit « elle lui manque », ce qu'elle en sait.
- **Présents** : qui est là en ce moment, une entrée par personne (en ligne depuis, en train d'écrire), et sous elle
  chacune de ses connexions — par où, le moyen de communication, l'audience (privée ou publique).

Les données restent celles des facultés (``identity``, ``social``, ``presence``) : leur pagination et la bascule
« Tableau » de l'annuaire aussi. Ce que leurs blocs ne disent pas se lit à leurs faits, au même instant
(``Look``) : les moyens de communication d'une personne, ce qu'elle ressent envers elle, qui écrit en ce moment —
et, pour un lien, d'où vient sa proximité et si son rythme est mesuré (``closeness_origin``, ``rhythm_of`` de la
faculté), jamais relus dans le texte d'une cellule.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode

from markupsafe import Markup
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from mika.app.handmade import Look, excerpt, person_card, presences, read_parts, span
from mika.app.handmade.subjects.handle import CHANNELS
from mika.app.handmade.tabs import Got, Line, Tab, blank, text, tiles
from mika.contracts import social as social_c
from mika.contracts import transcript as transcript_c
from mika.faculties.identity.faculty import handles_of
from mika.faculties.identity.inspect import TRUST_SHORT, TRUST_TONE, handle_label, principal
from mika.faculties.identity.inspect import people as everyone_of
from mika.faculties.social.inspect import (
    CLOSENESS_FR,
    DECLARED,
    OWNER_FLOOR,
    closeness_origin,
    owner_floor,
    rhythm_of,
)
from mika.faculties.social.sections import profile_parts, refs_of
from mika.inspector.catalog import destinations
from mika.inspector.pages.subjects import subject_url, subject_url_key
from mika.inspector.ui import PREFIX, UI
from mika.kernel.clock import DAY
from mika.kernel.inspect import num_fr
from mika.vocab.people import fold, is_identifiable

STYLES = ("handmade/personnes.css",)
#: une personne : au plus tant de moyens de communication nommés sur sa ligne (les autres : comptés)
HANDLES_SHOWN = 4
#: les échelons de la proximité, du plus proche au plus lointain (les groupes de « Liens »)
RUNGS = (social_c.CLOSE, social_c.FRIEND, social_c.ACQUAINTANCE, social_c.STRANGER)
#: le titre d'un groupe de « Liens »
RUNG_TITLES = {social_c.CLOSE: "Proches", social_c.FRIEND: "Amitiés", social_c.ACQUAINTANCE: "Connaissances",
               social_c.STRANGER: "Pas encore de lien"}


# ── Vue d'ensemble : la page d'entrée ─────────────────────────────────────

#: la page (l'adresse de la destination), et le fragment qu'elle relit
BASE = f"{PREFIX}/personnes"
FRAGMENT = f"{PREFIX}/_personnes"
#: tant de cartes par page
PAGE = 30
#: la destination dont cette page est le premier onglet
KEY = "personnes"
#: les proximités qu'on choisit, dans l'ordre (vide : tout le monde)
LEVELS = (("", "Tout le monde"), (social_c.CLOSE, "Proches"), (social_c.FRIEND, "Amitiés"),
          (social_c.ACQUAINTANCE, "Connaissances"), (social_c.STRANGER, "Pas encore de lien"))
#: ce qu'elle sait d'une personne, sur sa carte : au plus tant de lettres
SUMMARY = 180


def _href(query: Mapping[str, str], **change: str) -> str:
    """Cette page avec d'autres paramètres (la page repart à la première)."""
    kept = {k: v for k, v in query.items() if k in ("q", "proximite") and v}
    for k, v in change.items():
        if v:
            kept[k] = v
        else:
            kept.pop(k, None)
    return BASE + ("?" + urlencode(kept) if kept else "")


def _page_href(query: Mapping[str, str], page: int) -> str:
    base = _href(query)
    return f"{base}{'&' if '?' in base else '?'}page={page}"


def directory(look: Look, query: Mapping[str, str]) -> dict[str, Any]:
    frame = look.frame
    online = presences(look)
    q, level = fold(query.get("q", "")), query.get("proximite", "")
    matched = []
    for person, handles in everyone_of(frame.state("identity"), frame).items():
        name = look.name(person)
        if q and q not in fold(name) and q not in fold(person) and not any(q in fold(h) for h in handles):
            continue
        closeness = frame.get(social_c.CLOSENESS(person)) if is_identifiable(person) else ""
        last = max((frame.get(transcript_c.LAST_FROM(h)) for h in handles), default=0)
        matched.append({"person": person, "handles": handles, "closeness": closeness, "last": last})
    levels = Counter(m["closeness"] for m in matched)
    shown = [m for m in matched if not level or m["closeness"] == level]
    # qui est là d'abord, puis qui a écrit le plus récemment
    shown.sort(key=lambda m: (m["person"] not in online, -m["last"], look.name(m["person"]).casefold()))
    pages = max(1, -(-len(shown) // PAGE))
    raw = str(query.get("page", "1"))
    page = min(max(1, int(raw)) if raw.isdigit() else 1, pages)
    chunk = shown[(page - 1) * PAGE: page * PAGE]
    profiles = frame.state("social").profiles
    texts = look.texts([r for m in chunk if (p := profiles.get(m["person"])) is not None for r in refs_of(p)])
    cards = []
    for m in chunk:
        card = person_card(look, m["person"], online.get(m["person"]))
        contact = frame.get(social_c.CONTACT(m["person"])) if is_identifiable(m["person"]) else None
        profile = profiles.get(m["person"])
        summary = profile_parts(profile, texts)[0] if profile is not None and not getattr(profile, "masked", False) \
            else None
        card.update({
            "handles": len(m["handles"]),
            "rhythm": f"écrit tous les {num_fr(contact.usual_days, 1)} j" if contact is not None
            and contact.measured and contact.usual_days else "",
            "summary": excerpt(summary, SUMMARY) if summary else "",
        })
        cards.append(card)
    chips = [{"label": label, "count": len(matched) if not key else levels.get(key, 0), "on": level == key,
              "href": _href(query, proximite=key)} for key, label in LEVELS if not key or levels.get(key)]
    here = [person_card(look, p, h) for p, h in online.items()]
    missed = [{"name": look.name(p), "href": look.href(p), "ratio": num_fr(r, 1)}
              for p, r in (frame.get(social_c.MISSED) or ())[:8]]
    return {
        "cards": cards, "chips": chips, "total": len(matched), "count": len(shown), "q": query.get("q", ""),
        "level": level, "online": here, "missed": missed,
        "page": page, "pages": pages,
        "prev": _page_href(query, page - 1) if page > 1 else "",
        "next": _page_href(query, page + 1) if page < pages else "",
    }


class PeoplePage:
    """La page Personnes et son fragment, dans le cadre de la console (son menu, ses vitaux)."""

    def __init__(self, ui: UI) -> None:
        self.ui = ui

    def snapshot(self, query: Mapping[str, str]) -> dict[str, Any]:
        look = Look.of(self.ui, DAY)
        return {"stamp": look.frame.local(look.now).strftime("%H:%M:%S"),
                **read_parts(look, (("people", lambda lk: directory(lk, query)),), "personnes")}

    def _fragment_url(self, query: Mapping[str, str]) -> str:
        kept = {k: v for k, v in query.items() if k in ("q", "proximite", "page") and v}
        return FRAGMENT + ("?" + urlencode(kept) if kept else "")

    def tabs(self) -> list[dict[str, Any]]:
        """La barre d'onglets de la destination, la même sur ses autres onglets (ADR 0176) : cette page d'abord, sous
        le titre que la destination lui donne, puis les onglets des facultés."""
        lead = destinations(self.ui.deps.navigation)[KEY].lead
        return [{"title": lead, "href": BASE, "on": True},
                *({"title": v.title, "href": f"{BASE}/{v.name}", "on": False}
                  for v in self.ui.inspection.in_section(KEY))]

    async def page(self, request: Request) -> Response:
        query = dict(request.query_params)
        return self.ui.page(request, "handmade/personnes/page.html", "Personnes", now=self.snapshot(query),
                            fragment=self._fragment_url(query), base=BASE, tabs=self.tabs())

    async def fragment(self, request: Request) -> Response:
        return self.ui.fragment("handmade/personnes/body.html", now=self.snapshot(dict(request.query_params)),
                                base=BASE)

    def routes(self) -> list[Route]:
        return [Route(BASE, self.ui.guarded(self.page), methods=["GET"]),
                Route(FRAGMENT, self.ui.guarded(self.fragment), methods=["GET"])]


# ── Ce que partagent les onglets ──────────────────────────────────────────


def person_of(c: Mapping[str, Any] | None) -> str:
    """La personne qu'une cellule nomme : la clé de la fiche où son lien mène (vide : ce n'est pas une personne)."""
    return subject_url_key(str((c or {}).get("href") or ""), "person")


def _face(look: Look, person: str, online: Mapping[str, dict[str, Any]], c: Mapping[str, Any] | None) -> dict[str, Any]:
    """Une personne comme la vue d'ensemble la dit (``person_card``) ; une cellule qui ne mène à personne (une
    connexion de passage) : son nom seul, au neutre."""
    if person:
        return person_card(look, person, online.get(person))
    name = text(c) or "?"
    return {"name": name, "initial": name[:1].upper(), "href": "", "closeness": "", "close": False, "owner": False,
            "felt": None, "online": False, "composing": False, "notes": []}


def _emotion(face: Mapping[str, Any]) -> str:
    return face["felt"]["emotion"] if face.get("felt") else "neutral"


# ── Annuaire ──────────────────────────────────────────────────────────────


def _handles(look: Look, person: str) -> tuple[list[dict[str, str]], int]:
    """Ses moyens de communication, le principal d'abord (celui dont le canal prouve le plus) : leur nom, ce que
    leur canal prouve, leur fiche ; et combien d'autres ne sont pas nommés."""
    s = look.frame.state("identity")
    keys = [k for k in handles_of(s, person) if k in s.handles]
    main = principal(s, person)
    keys.sort(key=lambda k: (k != main, -s.handles[k].first_seen, k))
    out = [{"label": handle_label(s, k), "href": subject_url("handle", k), "trust": TRUST_SHORT[s.handles[k].trust],
            "tone": TRUST_TONE[s.handles[k].trust], "main": k == main and len(keys) > 1}
           for k in keys[:HANDLES_SHOWN]]
    return out, max(0, len(keys) - HANDLES_SHOWN)


def _listed(look: Look, line: Line, online: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    who = line.get("personne")
    person = person_of(who)
    face = _face(look, person, online, who)
    handles, more = _handles(look, person) if person else ([], 0)
    last = line.get("dernier message reçu")
    known = is_identifiable(person)
    return {**face, "who": who, "emotion": _emotion(face), "handles": handles, "more": more,
            "count": text(line.get("moyens de communication")),
            "certainty": "" if blank(line.get("certitude")) else line.text("certitude"),
            "first": None if blank(line.get("vue pour la première fois")) else line.get("vue pour la première fois"),
            "last": last if last and last.get("t") == "when" else None,
            "exchanges": subject_url("person", person, "echanges") if known else "",
            "link": subject_url("person", person, "lien") if known else ""}


def annuaire(got: Got) -> Markup | None:
    """Personnes › Annuaire : une entrée par personne — par où elle lui écrit, la certitude, depuis quand."""
    table, stats = got.table("Personnes"), got.stats()
    if table is None or stats is None:
        return None
    look = Look.of(got.ui, DAY)
    online = presences(look)
    s = tiles(stats)
    several = text(s.get("avec plusieurs moyens de communication", {}).get("value"))
    owners = text(s.get("propriétaires", {}).get("value"))
    counts = [{"value": owners, "label": "propriétaire" + ("s" if owners not in ("0", "1") else "")}]
    if several and several != "0":
        counts.append({"value": several, "label": "avec plusieurs moyens de communication"})
    return got.draw("handmade/personnes/annuaire.html", t=table, counts=counts,
                    people=[_listed(look, x, online) for x in got.lines("Personnes")])


# ── Liens ─────────────────────────────────────────────────────────────────


def _origin(look: Look, person: str) -> str:
    """D'où vient son échelon, en mots : la clé que la faculté rend (``closeness_origin``), à son état."""
    origin = closeness_origin(look.frame.state("social"), look.frame, person)
    if origin == DECLARED:
        return "déclarée par un opérateur"
    if origin == OWNER_FLOOR:
        return f"née de leur histoire · au moins « {owner_floor(look.frame)} », car c'est sa propriétaire"
    return "née de leur histoire"


def _bond(look: Look, line: Line, online: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    who = line.get("personne")
    person = person_of(who)
    face = _face(look, person, online, who)
    level = look.frame.get(social_c.CLOSENESS(person)) if person else social_c.STRANGER
    silence = line.get("silence ÷ rythme")
    every, measured = rhythm_of(look.frame.get(social_c.CONTACT(person))) if person else ("", False)
    unanswered = line.text("initiatives sans réponse")
    summary = line.get("ce qu'elle en sait") or {}
    return {
        **face, "who": who, "emotion": _emotion(face), "level": level if level in RUNGS else social_c.STRANGER,
        "rung": RUNGS[::-1].index(level) if level in RUNGS else 0, "word": CLOSENESS_FR.get(level, level),
        "origin": _origin(look, person) if person else "", "every": every, "measured": measured,
        "silence": {"w": round(100 * float(silence["ratio"]), 1), "text": silence["text"],
                    "missed": silence.get("tone") == "warn"} if silence and silence.get("t") == "meter" else None,
        "quiet": "" if not silence or silence.get("t") == "meter" else text(silence),
        "last": line.get("dernier message reçu"), "href": line.href,
        "unanswered": unanswered if unanswered not in ("", "0", "—") else "",
        "summary": "" if summary.get("kind") == "muted" or text(summary) in ("pas encore de profil", "—")
        else text(summary),
    }


def liens(got: Got) -> Markup | None:
    """Personnes › Liens : un bandeau si quelqu'un lui manque, la bande de chiffres, les liens par proximité."""
    table, stats = got.table("Liens"), got.stats()
    if table is None or stats is None:
        return None
    look = Look.of(got.ui, DAY)
    online = presences(look)
    bonds = [_bond(look, x, online) for x in got.lines("Liens")]
    s = tiles(stats)
    missed = s.get("qui lui manquent", {})
    groups = [{"key": k, "title": RUNG_TITLES[k], "items": [b for b in bonds if b["level"] == k]} for k in RUNGS]
    return got.draw("handmade/personnes/liens.html", t=table, band=stats["items"],
                    missed=missed.get("sub", "") if missed.get("tone") == "warn" else "",
                    groups=[g for g in groups if g["items"]])


# ── Présents ──────────────────────────────────────────────────────────────


def _channel(said: str) -> str:
    return CHANNELS.get(said, (said or "un canal inconnu",))[0]


def _handle(look: Look, c: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Un moyen de communication, nommé comme sa fiche le nomme (« Béa · compte ») plutôt que par sa clé."""
    key = subject_url_key(str((c or {}).get("href") or ""), "handle")
    if not key:
        return dict(c) if c else None
    return {**c, "text": handle_label(look.frame.state("identity"), key)}


def presents(got: Got) -> Markup | None:
    """Personnes › Présents : qui est là, une entrée par personne, ses connexions sous elle."""
    table, stats = got.table("Présents"), got.stats()
    if table is None or stats is None:
        return None
    look = Look.of(got.ui, DAY)
    online = presences(look)
    people: dict[str, dict[str, Any]] = {}
    for x in got.lines("Présents"):
        who = x.get("personne")
        person = person_of(who)
        key = person or text(x.get("moyen de communication"))
        if key not in people:
            face = _face(look, person, online, who)
            here = online.get(person) if person else None
            since = here["since"] if here and here["since"] else 0
            people[key] = {**face, "who": who, "emotion": _emotion(face), "online": True,
                           "since": span(look.now - since) if since else "", "links": []}
        people[key]["links"].append({
            "handle": _handle(look, x.get("moyen de communication")), "channel": _channel(x.text("canal")),
            "connection": x.text("connexion"), "since": x.get("présente depuis"), "audience": x.get("audience")})
    counts = [f"{text(s['value'])} {s['label']}" for s in stats["items"]]
    return got.draw("handmade/personnes/presents.html", t=table, counts=counts, people=list(people.values()))


TABS: dict[str, Any] = {
    "personnes/personnes": Tab(annuaire, *STYLES),
    "personnes/liens": Tab(liens, *STYLES),
    "personnes/presents": Tab(presents, *STYLES),
}
