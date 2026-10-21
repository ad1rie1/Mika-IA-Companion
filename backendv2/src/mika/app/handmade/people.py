"""Personnes : les gens qu'elle connaît, sur une page dessinée à la main (ADR 0121).

La destination Personnes avait trois onglets, un par faculté : l'annuaire (``identity``), les liens (``social``),
les présents (``presence``). « Qui connaît-elle, et où en est-elle avec chacun ? » les traverse : cette page les
croise, une carte par personne — ce qu'elle est pour elle, ce qu'elle ressent envers elle, l'attachement, ce qui se
passe entre elles (en ligne, une réponse attendue, un silence qui pèse), ce qu'elle en sait —, avec qui est là en ce
moment et qui lui manque. On cherche par nom, on filtre par proximité ou par présence ; les trois onglets restent,
sous « Le détail ». Elle se relit seule (``handmade/live.js``).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode

from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from mika.app.handmade import Look, excerpt, person_card, presences, read_parts
from mika.contracts import social as social_c
from mika.contracts import transcript as transcript_c
from mika.faculties.identity.inspect import people as everyone_of
from mika.faculties.social.sections import profile_parts, refs_of
from mika.inspector.ui import PREFIX, UI
from mika.kernel.clock import DAY
from mika.kernel.inspect import num_fr
from mika.vocab.people import fold, is_identifiable

#: la page (l'adresse de la destination), et le fragment qu'elle relit
BASE = f"{PREFIX}/personnes"
FRAGMENT = f"{PREFIX}/_personnes"
#: tant de cartes par page
PAGE = 30
#: les onglets de la destination que cette page résume : (titre, adresse), sous « Le détail »
DETAIL = (("L'annuaire des identités", "personnes"), ("Les liens, un par un", "liens"),
          ("Les connexions vivantes", "presents"))
#: les proximités qu'on choisit, dans l'ordre (vide : tout le monde)
LEVELS = (("", "Tout le monde"), (social_c.CLOSE, "Proches"), (social_c.FRIEND, "Amitiés"),
          (social_c.ACQUAINTANCE, "Connaissances"), (social_c.STRANGER, "Pas encore de lien"))
#: le filtre « en ligne »
ONLINE = "en-ligne"
#: ce qu'elle sait d'une personne, sur sa carte : au plus tant de lettres
SUMMARY = 180


def _href(query: Mapping[str, str], **change: str) -> str:
    """Cette page avec d'autres paramètres (la page repart à la première)."""
    kept = {k: v for k, v in query.items() if k in ("q", "proximite", "presence") and v}
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
    q, level, only_online = fold(query.get("q", "")), query.get("proximite", ""), query.get("presence") == ONLINE
    matched = []
    for person, handles in everyone_of(frame.state("identity"), frame).items():
        name = look.name(person)
        if q and q not in fold(name) and q not in fold(person) and not any(q in fold(h) for h in handles):
            continue
        closeness = frame.get(social_c.CLOSENESS(person)) if is_identifiable(person) else ""
        last = max((frame.get(transcript_c.LAST_FROM(h)) for h in handles), default=0)
        matched.append({"person": person, "handles": handles, "closeness": closeness, "last": last})
    levels = Counter(m["closeness"] for m in matched)
    shown = [m for m in matched if (not level or m["closeness"] == level) and (not only_online or m["person"] in online)]
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
    here = [{**person_card(look, p, h), "since": h["since"]} for p, h in online.items()]
    missed = [{"name": look.name(p), "href": look.href(p), "ratio": num_fr(r, 1)}
              for p, r in (frame.get(social_c.MISSED) or ())[:8]]
    return {
        "cards": cards, "chips": chips, "total": len(matched), "count": len(shown), "q": query.get("q", ""),
        "level": level, "only_online": only_online, "online": here, "missed": missed,
        "online_href": _href(query, presence="" if only_online else ONLINE),
        "page": page, "pages": pages,
        "prev": _page_href(query, page - 1) if page > 1 else "",
        "next": _page_href(query, page + 1) if page < pages else "",
        "detail": [{"title": t, "href": f"{BASE}/{slug}"} for t, slug in DETAIL],
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
        kept = {k: v for k, v in query.items() if k in ("q", "proximite", "presence", "page") and v}
        return FRAGMENT + ("?" + urlencode(kept) if kept else "")

    async def page(self, request: Request) -> Response:
        query = dict(request.query_params)
        return self.ui.page(request, "handmade/people/page.html", "Personnes", now=self.snapshot(query),
                            fragment=self._fragment_url(query), base=BASE)

    async def fragment(self, request: Request) -> Response:
        return self.ui.fragment("handmade/people/body.html", now=self.snapshot(dict(request.query_params)),
                                base=BASE)

    def routes(self) -> list[Route]:
        return [Route(BASE, self.ui.guarded(self.page), methods=["GET"]),
                Route(FRAGMENT, self.ui.guarded(self.fragment), methods=["GET"])]
