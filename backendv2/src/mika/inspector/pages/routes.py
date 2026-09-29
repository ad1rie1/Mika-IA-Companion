"""Les routes de la console : destinations et leurs onglets, vues déclarées,
épisodes, événements, vitaux, connexion, approbations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import quote, urlencode

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

from mika.inspector import render
from mika.inspector.catalog import Builtin, Destination, Panel, destinations
from mika.inspector.formview import action_view, slot_key
from mika.inspector.pages import reglages
from mika.inspector.pages.journal import EPISODE_TABS, episode_head, episode_tab, event_blocks
from mika.inspector.pages.subjects import Subjects
from mika.inspector.ui import PREFIX, SESSION_COOKIE, UI, secure
from mika.kernel.faculty import InspectSpec
from mika.kernel.inspect import ActionSlot, Disclosure, Grid, Note, Param, Row, Section, Table
from mika.runtime.operations import dynamic_fields, fixed_values, offered, perform

#: les anciennes adresses de l'inspecteur → la console
MOVED = {"chronologie": "systeme/chronologie", "etat": "systeme/etat", "contributions": "systeme/contributions",
         "sante": "systeme/sante", "appels": "systeme/appels", "rapports": "systeme/simulations",
         "facultes": "systeme/vues", "modeles": "reglages/modeles", "persona": "reglages/personnalite",
         "parametres": "reglages/parametres", "canaux": "reglages/canaux", "forge": "apps",
         "comptes": "reglages/comptes"}


#: les anciens onglets qui ont pris leur propre place
MOVED_TABS = {("reglages", "apps"): "apps"}


def safe_back(target: str) -> str:
    """Un retour dans la console seulement (jamais une autre adresse)."""
    if target.startswith(PREFIX + "/") and "//" not in target and "\\" not in target and len(target) < 2000:
        return target
    return PREFIX + "/"


def dest_url(key: str) -> str:
    return f"{PREFIX}/" if key == "accueil" else f"{PREFIX}/{key}"


def filters_ctx(specs: Sequence[Param], raw: Mapping[str, str]) -> tuple[list[dict[str, Any]], bool]:
    out, active = [], False
    for p in specs:
        value = str(raw.get(p.name, "") or "")
        active |= bool(value)
        out.append({"name": p.name, "label": p.label, "kind": p.kind, "choices": p.choices, "value": value,
                    "placeholder": p.placeholder})
    return out, active


class Pages:
    def __init__(self, ui: UI) -> None:
        self.ui = ui
        self.dests = destinations(ui.deps.navigation)

    # ── utilitaires ──
    def tabs_of(self, d: Destination) -> list[tuple[str, str, Builtin | InspectSpec]]:
        out: list[tuple[str, str, Builtin | InspectSpec]] = []
        for key in d.builtin:
            b = self.ui.builtins[key]
            out.append((b.slug, b.title, b))
        for v in self.ui.inspection.in_section(d.key):
            out.append((v.name, v.title, v))
        return out

    def tab_badge(self, item: Builtin | InspectSpec) -> int:
        if isinstance(item, Builtin):
            return int(item.badge(self.ui) or 0) if item.badge else 0
        b = self.ui.inspection.badge(item)
        return b[0] if b else 0

    async def produce(self, item: Builtin | InspectSpec, request: Request) -> dict[str, Any]:
        """Les blocs (et les filtres, un gabarit à part) d'un onglet."""
        if isinstance(item, Builtin):
            got = await item.fn(self.ui, request)
            if isinstance(got, Response):
                return {"response": got}
            if isinstance(got, dict):
                return {"blocks": list(got.get("blocks") or []), "filters": tuple(got.get("filters") or ()),
                        "panel": got.get("panel"), "messages": list(got.get("messages") or []),
                        "crumbs": list(got.get("crumbs") or [])}
            if isinstance(got, Panel):
                return {"blocks": [], "panel": got}
            return {"blocks": list(got or [])}
        return {"blocks": await self.ui.inspection.arun(item, request.query_params, self.ui.when_long),
                "filters": item.typed}

    def back(self, request: Request) -> str:
        return request.url.path + (f"?{request.url.query}" if request.url.query else "")

    def slot_forms(self, request: Request, blocks: Sequence[Any], subject: str) -> dict[str, Any]:
        """Les formulaires des actions posées dans les blocs (``ActionSlot``), même
        dans le détail d'une ligne."""
        out: dict[str, Any] = {}
        csrf, back = self.ui.csrf(request), self.back(request)

        def walk(items: Sequence[Any]) -> None:
            for b in items:
                if isinstance(b, ActionSlot):
                    spec = self.ui.inspection.action(b.action)
                    if spec is not None:
                        initial = dict(b.initial)
                        dynamic = dynamic_fields(self.ui.kernel, spec, subject, initial) if spec.fields else None
                        out[slot_key(b.action, b.initial)] = action_view(spec, csrf=csrf, back=back, subject=subject,
                                                                          initial=initial, dynamic=dynamic)
                elif isinstance(b, Grid | Section | Disclosure):
                    walk(b.items)
                elif isinstance(b, Table):
                    walk([x for r in b.rows if isinstance(r, Row) for x in r.detail])

        walk(blocks)
        return out

    def head_actions(self, request: Request, *, section: str = "", kind: str = "", subject: str = "") -> list[Any]:
        specs = self.ui.inspection.actions_for(section=section) if section else \
            self.ui.inspection.actions_for(subject=kind)
        csrf, back = self.ui.csrf(request), self.back(request)
        return [action_view(a, csrf=csrf, back=back, subject=subject) for a in specs
                if offered(self.ui.kernel, a, subject)]

    def render_page(self, request: Request, *, title: str, active: str, blocks: Sequence[Any],
                    filters: Sequence[Param] = (), panel: Panel | None = None, keep: Sequence[tuple[str, str]] = (),
                    status: int = 200, subject: str = "", **ctx: Any) -> Response:
        query = {k: v for k, v in request.query_params.items()}
        env = self.ui.env()
        fctx, active_filter = filters_ctx(filters, query)
        reset = request.url.path + ("?" + urlencode(dict(keep)) if keep else "")
        panel_ctx = dict(panel.context) if panel else {}
        flash = self.ui.pop_flash(request.query_params.get("flash", ""))
        if flash:
            ctx["messages"] = [flash, *ctx.get("messages", [])]
        return self.ui.page(request, "page.html", title, active=active, status=status,
                            blocks=render.blocks(blocks, env, query), filters=fctx, filtered=active_filter,
                            keep=keep, reset=reset, panel=panel.template if panel else None,
                            forms=self.slot_forms(request, blocks, subject), **panel_ctx, **ctx)

    # ── destinations ──
    async def destination(self, request: Request, *, key: str = "", tab: str = "",
                          produced: dict[str, Any] | None = None, status: int = 200) -> Response:
        """Une destination et l'onglet demandé ; ``produced`` remplace le contenu de
        l'onglet (un formulaire refusé qu'on remontre, avec ``status``)."""
        key = key or request.path_params.get("key", "accueil")
        moved_tab = MOVED_TABS.get((key, request.path_params.get("tab", "")))
        if moved_tab and not tab:
            return RedirectResponse(f"{PREFIX}/{moved_tab}", status_code=301)
        if key in MOVED and "tab" not in request.path_params and not tab:
            return RedirectResponse(f"{PREFIX}/{MOVED[key]}", status_code=301)
        d = self.dests.get(key)
        if d is None:
            return self.render_page(request, title="Page inconnue", active="", status=404,
                                    blocks=[Note("Cette page n'existe pas.", "warn")])
        tabs = self.tabs_of(d)
        if d.layout == "stack":
            blocks: list[Any] = []
            for _slug, title, item in tabs:
                got = await self.produce(item, request)
                if "response" in got:
                    continue
                blocks.append(Section(title, tuple(got["blocks"])))
            return self.render_page(request, title=d.label, active=d.key, blocks=blocks, subtitle=d.description)
        slug = tab or request.path_params.get("tab", "") or (tabs[0][0] if tabs else "")
        current = next((t for t in tabs if t[0] == slug), None)
        if current is None:
            return RedirectResponse(dest_url(d.key), status_code=303)
        item = current[2]
        if isinstance(item, Builtin) and item.href:
            return RedirectResponse(item.href, status_code=303)
        got = produced if produced is not None else await self.produce(item, request)
        if "response" in got:
            return got["response"]
        tab_list = [{"title": t, "href": (b.href if isinstance(b, Builtin) and b.href else f"{dest_url(d.key)}/{s}"
                                          if d.key != "accueil" else f"{PREFIX}/accueil/{s}"),
                     "on": s == slug, "badge": self.tab_badge(b)} for s, t, b in tabs]
        return self.render_page(request, title=f"{current[1]} · {d.label}", heading=d.label, active=d.key,
                                subtitle=d.description, tabs=tab_list, blocks=got["blocks"],
                                head_actions=self.head_actions(request, section=d.key),
                                filters=got.get("filters") or (), panel=got.get("panel"),
                                messages=got.get("messages") or [], crumbs=got.get("crumbs") or [],
                                status=status)

    async def view(self, request: Request) -> Response:
        owner, name = request.path_params["owner"], request.path_params["name"]
        spec = self.ui.inspection.find(owner, name)
        if spec is None:
            return self.render_page(request, title="Vue inconnue", active="", status=404,
                                    blocks=[Note("Cette vue n'existe pas.", "warn")])
        d = self.dests.get(spec.section)
        crumbs = [(d.label, dest_url(d.key))] if d else [("Toutes les vues", f"{PREFIX}/systeme/vues")]
        blocks = await self.ui.inspection.arun(spec, request.query_params, self.ui.when_long)
        return self.render_page(request, title=spec.title, active=d.key if d else "systeme", crumbs=crumbs,
                                blocks=blocks, filters=spec.typed, subtitle=spec.description)

    # ── épisode, événement ──
    async def episode(self, request: Request) -> Response:
        corr = request.path_params["corr"]
        info = episode_head(self.ui, corr)
        if info is None:
            return self.render_page(request, title="Épisode inconnu", active="decisions", status=404,
                                    blocks=[Note("Aucun événement pour cette corrélation.", "warn")])
        slug = request.query_params.get("onglet", "deroule")
        if slug not in dict(EPISODE_TABS):
            slug = "deroule"
        base = f"{PREFIX}/episode/{quote(corr, safe='')}"
        tabs = [{"title": t, "href": f"{base}?onglet={s}", "on": s == slug, "badge": 0} for s, t in EPISODE_TABS]
        blocks = episode_tab(self.ui, corr, slug, info)
        return self.render_page(request, title=f"Épisode · {info['kind']}", heading=f"Un épisode : {info['kind']}",
                                active="decisions", crumbs=[("Décisions", f"{PREFIX}/decisions/episodes")],
                                head_badges=info["badges"], facts=info["facts"], tabs=tabs, blocks=blocks)

    async def event(self, request: Request) -> Response:
        try:
            seq = int(request.path_params["seq"])
        except ValueError:
            seq = 0
        got = event_blocks(self.ui, seq) if seq > 0 else None
        if got is None:
            return self.render_page(request, title="Événement introuvable", active="systeme", status=404,
                                    blocks=[Note("Aucun événement à ce numéro.", "warn")])
        title, blocks = got
        return self.render_page(request, title=title, active="systeme",
                                crumbs=[("Chronologie", f"{PREFIX}/systeme/chronologie")], blocks=blocks)

    # ── vitaux, connexion ──
    async def vitals(self, request: Request) -> Response:
        return self.ui.fragment("_vitals.html", vitals=self.ui.vitals())

    async def login(self, request: Request) -> Response:
        error = ""
        if request.method == "POST":
            data = await self.ui.form(request)
            if data is None:
                error = "Jeton de formulaire invalide : recharge la page."
            else:
                acc = self.ui.deps.accounts.authenticate(data.get("username", ""), data.get("password", ""))
                if acc is None or not acc.operator:
                    error = "Identifiants invalides, ou compte non opérateur."
                else:
                    key = await self.ui.deps.accounts.open_session(acc)
                    response = RedirectResponse(PREFIX + "/", status_code=303)
                    response.set_cookie(SESSION_COOKIE, key, httponly=True, samesite="lax",
                                        secure=self.ui.cookie_secure)
                    return secure(response)
        return self.ui.bare(request, "login.html", "Connexion", error=error)

    async def logout(self, request: Request) -> Response:
        data = await self.ui.form(request)
        if data is not None:
            key = request.cookies.get(SESSION_COOKIE)
            if key:
                await self.ui.deps.accounts.close_session(key)
        response = RedirectResponse(PREFIX + "/connexion", status_code=303)
        response.delete_cookie(SESSION_COOKIE)
        return secure(response)

    async def act(self, request: Request) -> Response:
        """Exécuter une action déclarée : valider, exécuter, revenir (ou remontrer
        le formulaire avec ses erreurs)."""
        key = request.path_params["key"]
        spec = self.ui.inspection.action(key)
        got = await self.ui.form_lists(request)
        account = self.ui.operator(request)
        if spec is None:
            return self.render_page(request, title="Action inconnue", active="", status=404,
                                    blocks=[Note("Cette action n'existe pas.", "warn")])
        if got is None or account is None:
            return self.render_page(request, title=spec.title, active="", status=403,
                                    blocks=[Note("Jeton de formulaire invalide : recharge la page.", "danger")])
        single, lists = got
        back = safe_back(single.get("_retour", ""))
        subject = single.get("_sujet", "")
        outcome = await perform(self.ui.kernel, key, lists, by=account.handle, subject=subject,
                                nonce=single.get("_op", ""))
        if not outcome.ok and outcome.errors:
            fixed = fixed_values(lists)
            dynamic = dynamic_fields(self.ui.kernel, spec, subject, fixed) if spec.fields else None
            form = action_view(spec, csrf=self.ui.csrf(request), back=back, subject=subject, initial=fixed,
                               values={k: v for k, v in single.items() if not k.startswith("_") and k not in fixed},
                               errors=outcome.errors, dynamic=dynamic)
            return self.render_page(request, title=spec.title, active="", status=400, crumbs=[("Retour", back)],
                                    blocks=[], head_actions=[], messages=[("danger", outcome.message)],
                                    panel=Panel("_action_page.html", {"form": form}))
        if outcome.show:
            return self.render_page(request, title=spec.title, active="", crumbs=[("Retour", back)],
                                    blocks=list(outcome.show), messages=[(outcome.tone, outcome.message)])
        token = single.get("_op", "") or key
        self.ui.flash(token, outcome.tone if outcome.ok else "danger", outcome.message)
        target = render.href(outcome.go) if outcome.go else back
        sep = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{sep}flash={quote(token, safe='')}", status_code=303)

    async def approve(self, request: Request) -> Response:
        data = await self.ui.form(request)
        account = self.ui.operator(request)
        target = f"{PREFIX}/approbations"
        if data is None or account is None:
            return RedirectResponse(target + "?fait=jeton", status_code=303)
        try:
            proposal = int(data.get("proposal", "0"))
        except ValueError:
            proposal = 0
        approved = data.get("decision") == "approve"
        status = await self.ui.deps.port.resolve_effect(proposal, approved, by=account.handle,
                                                        note=data.get("note", "")[:500])
        if status != "unknown" and self.ui.deps.after_decision is not None:
            await self.ui.deps.after_decision()
        outcome = "inconnu" if status == "unknown" else ("oui" if approved else "non")
        return RedirectResponse(f"{target}?fait={outcome}", status_code=303)

    async def settings_post(self, request: Request) -> Response:
        """Enregistrer une section de réglages, ou des surcharges de paramètres."""
        tab = request.path_params["tab"]
        if tab == "parametres":
            response, state, status = await reglages.parametres_post(self.ui, request)
            if response is not None:
                return response
            got = await reglages.parametres(self.ui, request, state)
            produced = got if isinstance(got, dict) else {"blocks": list(got),
                                                          "messages": list(state.get("messages", []))}
            return await self.destination(request, key="reglages", tab=tab, produced=produced, status=status)
        forms_ = self.ui.settings_forms
        if forms_ is None or tab not in forms_.tabs:
            return self.render_page(request, title="Réglage inconnu", active="reglages", status=404,
                                    blocks=[Note("Cette page de réglages n'existe pas.", "warn")])
        response, states, status = await forms_.post(self.ui, request, tab)
        if response is not None:
            return response
        panel = await forms_.panel(self.ui, request, tab, states)
        general = [m for st in states.values() for m in st.messages] if "" in states else []
        return await self.destination(request, key="reglages", tab=tab, status=status,
                                      produced={"blocks": [], "panel": panel, "messages": general})

    def routes(self) -> list[Route]:
        g = self.ui.guarded
        return [
            Route(PREFIX + "/reglages/{tab:str}", g(self.settings_post), methods=["POST"]),
            Route(PREFIX + "/connexion", self.login, methods=["GET", "POST"]),
            Route(PREFIX + "/deconnexion", self.logout, methods=["POST"]),
            Route(PREFIX + "/_vitals", g(self.vitals)),
            Route(PREFIX + "/approbations", g(self.approve), methods=["POST"]),
            Route(PREFIX + "/action/{key:str}", g(self.act), methods=["POST"]),
            Route(PREFIX + "/episode/{corr:str}", g(self.episode)),
            Route(PREFIX + "/evenement/{seq:str}", g(self.event)),
            Route(PREFIX + "/facultes/{owner:str}/{name:str}", g(self.view)),
            *Subjects(self).routes(),
        ]

    def catchall(self) -> list[Route]:
        """Les destinations : en dernier (toute autre route passe avant)."""
        g = self.ui.guarded
        return [
            Route(PREFIX + "/", g(self.destination)),
            Route(PREFIX + "/{key:str}", g(self.destination)),
            Route(PREFIX + "/{key:str}/{tab:str}", g(self.destination)),
        ]
