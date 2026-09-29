"""Les fiches d'objets : une personne, une poignée, un but, une app… L'en-tête
vient de la faculté qui déclare le type d'objet ; chaque onglet, de la
faculté qui l'y ajoute — la console n'en connaît aucune. Et la recherche, et
l'oubli d'un objet qui est un sujet de contenus."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlencode

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

from mika.inspector import render
from mika.inspector.ui import PREFIX, secure
from mika.kernel.inspect import Head, Note, Ref, Table
from mika.runtime import operations


def fiche_url(kind: str, key: str, tab: str = "") -> str:
    base = f"{PREFIX}/fiche/{quote(kind, safe='')}/{quote(key, safe='')}"
    return base + (f"?{urlencode({'onglet': tab})}" if tab else "")


def forget_form(ui: Any, request: Request, kind: str, key: str) -> dict[str, Any]:
    return {"url": f"{PREFIX}/oublier/{quote(kind, safe='')}/{quote(key, safe='')}", "csrf": ui.csrf(request),
            "nonce": "", "back": fiche_url(kind, key), "title": "Oublier", "fields": [], "retype": True,
            "subject": key, "danger": True, "button": "Oublier pour de bon", "errors": {}, "id": f"oubli-{kind}",
            "description": "Efface tout ce qui la concerne (messages, souvenirs, traces) ; le journal garde des "
                           "enveloppes vides. Les sauvegardes plus anciennes la contiennent encore.",
            "confirm": "Oublier pour de bon ? C'est irréversible."}


class Subjects:
    def __init__(self, pages: Any) -> None:
        self.pages = pages
        self.ui = pages.ui

    async def fiche(self, request: Request) -> Response:
        kind, key = request.path_params["kind"], request.path_params["key"]
        spec = self.ui.inspection.subject(kind)
        if spec is None:
            return self.pages.render_page(request, title="Fiche inconnue", active="", status=404,
                                          blocks=[Note("Ce type d'objet n'existe pas.", "warn")])
        head = self.ui.inspection.head(kind, key, self.ui.when_long)
        if head is None:
            return self.pages.render_page(request, title=f"{spec.label} inconnue", active="", status=404,
                                          blocks=[Note(f"Aucun objet « {key} » de ce type.", "warn")])
        if isinstance(head, Head) and head.key != key:
            return RedirectResponse(fiche_url(kind, head.key, request.query_params.get("onglet", "")),
                                    status_code=303)
        tabs = self.ui.inspection.tabs(kind)
        slug = request.query_params.get("onglet", "") or (tabs[0].name if tabs else "")
        current = next((t for t in tabs if t.name == slug), tabs[0] if tabs else None)
        blocks: list[Any] = [head] if isinstance(head, Note) else []
        if current is not None:
            blocks += await self.ui.inspection.arun(current, request.query_params, self.ui.when_long, subject=key)
        tab_list = [{"title": t.title, "href": fiche_url(kind, key, t.name), "on": current is not None
                     and t.name == current.name, "badge": 0} for t in tabs]
        actions = self.pages.head_actions(request, kind=kind, subject=key)
        if spec.forgettable:
            actions.append(forget_form(self.ui, request, kind, key))
        title = head.title if isinstance(head, Head) else key
        env = self.ui.env()
        facts = [{"label": k, "cell": render.cell(v, env)} for k, v in (head.facts if isinstance(head, Head) else ())]
        badges = [{"text": b.text, "tone": b.tone} for b in (head.badges if isinstance(head, Head) else ())]
        return self.pages.render_page(
            request, title=f"{title} · {spec.label}", heading=title, active="",
            subtitle=head.subtitle if isinstance(head, Head) else "", head_badges=badges, facts=facts,
            crumbs=[(spec.plural, f"{PREFIX}/recherche?sorte={quote(kind)}")], tabs=tab_list, blocks=blocks,
            filters=current.typed if current is not None else (), head_actions=actions, subject=key,
            keep=(("onglet", current.name),) if current is not None else ())

    async def search(self, request: Request) -> Response:
        q = request.query_params.get("q", "").strip()[:200]
        only = request.query_params.get("sorte", "")
        blocks: list[Any] = []
        kinds = [k for k in self.ui.kernel.registry.subjects if not only or k == only]
        for kind in sorted(kinds):
            spec = self.ui.inspection.subject(kind)
            if spec is None or spec.search is None:
                continue
            found = self.ui.inspection.search(kind, q, 50)
            if found or only:
                blocks.append(Table(("", "détail"), tuple(
                    (Ref.subject(kind, f.key, f.title), f.subtitle or "—") for f in found),
                    title=spec.plural, empty="Aucun résultat."))
        if q.isdigit():
            blocks.insert(0, Table(("événement",), ((Ref("event", q, f"l'événement n° {q}"),),), title="Journal"))
        views = [v for v in self.ui.inspection.views() if q and q.lower() in v.title.lower()]
        if views:
            blocks.append(Table(("vue", "faculté"), tuple((Ref.view(v.owner, v.name, v.title), v.owner)
                                                         for v in views), title="Vues"))
        if not blocks:
            blocks = [Note("Rien ne correspond." if q else "Tape un nom, un numéro d'événement, un titre.", "muted")]
        return self.pages.render_page(request, title="Recherche", heading=f"Recherche : « {q} »" if q else "Recherche",
                                      active="", blocks=blocks)

    async def forget(self, request: Request) -> Response:
        kind, key = request.path_params["kind"], request.path_params["key"]
        spec = self.ui.inspection.subject(kind)
        data = await self.ui.form(request)
        account = self.ui.operator(request)
        if spec is None or not spec.forgettable or data is None or account is None:
            return self.pages.render_page(request, title="Oubli refusé", active="", status=403,
                                          blocks=[Note("Jeton invalide, ou cet objet ne s'oublie pas.", "danger")])
        if data.get("_confirmer", "").strip() != key:
            return self.pages.render_page(request, title="Oubli refusé", active="", status=400,
                                          blocks=[Note(f"Retape « {key} » pour confirmer.", "danger")],
                                          crumbs=[("Retour", fiche_url(kind, key))])
        head = self.ui.inspection.head(kind, key)
        keys = [key, *(head.aliases if isinstance(head, Head) else ())]
        removed = 0
        for k in dict.fromkeys(keys):
            got = await self.ui.kernel.forget(k)
            removed += sum(v for v in got.values() if isinstance(v, int)) if isinstance(got, dict) else int(got or 0)
        await operations.audit(self.ui.kernel, f"console.oublier.{kind}", by=account.handle, subject_kind=kind,
                               subject=key)
        self.ui.flash(f"oubli-{key}", "ok", f"« {key} » est oublié·e ({removed} contenu(s) effacé(s)).")
        return secure(RedirectResponse(f"{PREFIX}/?flash={quote('oubli-' + key, safe='')}", status_code=303))

    def routes(self) -> list[Any]:
        g = self.ui.guarded
        return [Route(PREFIX + "/fiche/{kind:str}/{key:str}", g(self.fiche)),
                Route(PREFIX + "/recherche", g(self.search)),
                Route(PREFIX + "/oublier/{kind:str}/{key:str}", g(self.forget), methods=["POST"])]

