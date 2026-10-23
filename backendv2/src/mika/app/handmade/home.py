"""L'accueil, dessiné à la main (ADR 0121) : ce que l'opératrice regarde en ouvrant la console.

Trois questions, dans cet ordre : qu'est-ce qui m'attend ? (les priorités de l'onglet « À traiter » : une réponse qui
échoue, ce qui attend un accord, un processus en panne, une sauvegarde à faire, un contrôle de santé) — comment
va-t-elle ? (son humeur en mots, son corps, ses besoins, qui est là, lus comme « En ce moment ») — qu'a-t-elle fait
aujourd'hui ? (la journée en chiffres, ses derniers épisodes). Les courbes de la journée sont sur « En ce moment ».

Les données restent celles de la console : les onglets de l'accueil (``inspector.pages.home``) et les lectures
d'« En ce moment » (``handmade.now``). Elle se relit seule (``handmade/live.js``) ; une partie qui échoue tait sa
carte.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from mika.app.handmade import Look, read_parts
from mika.app.handmade import now as now_page
from mika.app.handmade.lists import Roles, listing
from mika.contracts import attention as attention_c
from mika.contracts import runtime as rt
from mika.inspector import render
from mika.inspector.pages import home as tabs
from mika.inspector.ui import PREFIX, UI
from mika.kernel.clock import DAY
from mika.kernel.inspect import Note, Stats, Table, Text
from mika.runtime.boundary import Failed, acall

#: l'accueil (la racine de la console et son adresse nommée), et le fragment qu'il relit
BASES = (f"{PREFIX}/", f"{PREFIX}/accueil")
FRAGMENT = f"{PREFIX}/_accueil"
#: ses derniers épisodes : tant de lignes
EPISODES_SHOWN = 8
#: ses derniers épisodes, en lignes : ce qu'il était en titre, son issue, sa cible, son détail, l'heure à droite
EPISODE_ROLES = Roles(title="épisode", badges=("issue",), body=("détail",), time="quand")
#: un contrôle de santé qui ne va pas : sa page
HEALTH = f"{PREFIX}/systeme/sante"


def _text(value: Any) -> str:
    return value.text if isinstance(value, Text) else str(value)


def priorities(blocks: Sequence[Any]) -> dict[str, Any]:
    """L'onglet « À traiter » en lignes : une valeur, ce que c'est, pourquoi, où décider ; « tout va bien » à part."""
    rows, calm = [], None
    for b in blocks:
        if isinstance(b, Stats):
            rows += [{"value": _text(s.value), "label": s.label, "sub": s.sub, "tone": s.tone or "warn",
                      "href": render.href(s.href) if s.href else ""} for s in b.items]
        elif isinstance(b, Note) and b.tone == "ok":
            calm = {"title": b.title, "text": b.text}
        elif isinstance(b, Note):
            rows.append({"value": "!", "label": b.title, "sub": b.text, "tone": b.tone or "warn", "href": HEALTH})
    return {"rows": _merged(rows), "calm": calm if not rows else None}


#: la gravité d'une priorité : la plus grave l'emporte quand deux mènent à la même page
SEVERITY = {"danger": 0, "warn": 1, "info": 2}
#: ce que dit un badge qui n'en sait pas plus
VAGUE = "à regarder"


def _merged(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Une ligne par page où décider : un badge (« Système › Processus »), son cadre (« Processus en échec ») et un
    contrôle de santé disent souvent la même chose ; la plus grave reste, et à gravité égale, la plus précise."""
    best: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for r in rows:
        key = r["href"] or f"#{len(order)}"
        if key not in best:
            best[key] = r
            order.append(key)
            continue
        kept = best[key]
        rank = (SEVERITY.get(r["tone"], 3), r["sub"] in ("", VAGUE))
        if rank < (SEVERITY.get(kept["tone"], 3), kept["sub"] in ("", VAGUE)):
            best[key] = r
    return sorted((best[k] for k in order), key=lambda r: SEVERITY.get(r["tone"], 3))


def episodes(ui: UI, blocks: Sequence[Any], query: Mapping[str, str]) -> dict[str, Any] | None:
    """Les derniers épisodes de l'onglet « Aujourd'hui », en lignes (ses chiffres : ceux d'« En ce moment »)."""
    table = next((b for b in blocks if isinstance(b, Table)), None)
    if table is None:
        return None
    got = {**listing(table, ui.env(), query, roles=EPISODE_ROLES), "kind": "episodes",
           "link_label": "Comprendre le résultat", "pager": None, "dense": True}
    got["rows"] = got["rows"][:EPISODES_SHOWN]
    return got


def figures(look: Look) -> list[dict[str, Any]]:
    """La journée en chiffres, depuis minuit : comme « En ce moment »."""
    return now_page.today(look, look.recent([rt.EPISODE_ENDED], now_page.EPISODES_READ),
                          look.recent([attention_c.THOUGHT_BORN], 60))


#: d'« En ce moment » : son humeur, son corps, ses besoins, les gens, la journée en chiffres
PARTS = (("mood", now_page.mood), ("body", now_page.body), ("needs", now_page.needs), ("people", now_page.people),
         ("figures", figures))


class HomePage:
    """L'accueil et son fragment, dans le cadre de la console (son menu, ses vitaux)."""

    def __init__(self, ui: UI) -> None:
        self.ui = ui

    async def snapshot(self, request: Request) -> dict[str, Any]:
        look = Look.of(self.ui, DAY)
        local = look.frame.local(look.now)
        query = dict(request.query_params)
        attention = await acall(tabs.attention, self.ui, request, label="accueil : à traiter")
        today = await acall(tabs.today, self.ui, request, label="accueil : aujourd'hui")
        return {
            "her": self.ui.her_name(), "stamp": local.strftime("%H:%M:%S"), "today": look.date(look.now),
            "attention": None if isinstance(attention, Failed) else priorities(attention),
            "episodes": None if isinstance(today, Failed) else episodes(self.ui, today, query),
            **read_parts(look, PARTS, "l'accueil"),
        }

    async def page(self, request: Request) -> Response:
        snap = await self.snapshot(request)
        flash = self.ui.pop_flash(request.query_params.get("flash", ""))
        return self.ui.page(request, "handmade/home/page.html", "Vue d'ensemble", active="accueil", now=snap,
                            fragment=FRAGMENT, messages=[flash] if flash else [])

    async def fragment(self, request: Request) -> Response:
        return self.ui.fragment("handmade/home/body.html", now=await self.snapshot(request))

    def routes(self) -> list[Route]:
        return [*(Route(base, self.ui.guarded(self.page), methods=["GET"]) for base in BASES),
                Route(FRAGMENT, self.ui.guarded(self.fragment), methods=["GET"])]
