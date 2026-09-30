"""Les routes de la console : destinations et leurs onglets, vues déclarées,
épisodes, événements, vitaux, connexion, approbations."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from urllib.parse import quote, urlencode

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

from mika.inspector import render
from mika.inspector.catalog import Builtin, Destination, Panel, builtin_keys, destinations
from mika.inspector.formview import action_view, visible_fields
from mika.inspector.pages import accounts, reglages
from mika.inspector.pages.journal import EPISODE_TABS, episode_head, episode_tab, event_blocks
from mika.inspector.pages.subjects import Subjects
from mika.inspector.ui import PREFIX, SESSION_COOKIE, UI, secure
from mika.kernel.faculty import InspectSpec
from mika.kernel.inspect import Filters, Note, Param, Section, Workspace, walk_blocks
from mika.runtime.operations import dynamic_fields, fixed_values, offered, perform

#: les anciennes adresses de l'inspecteur → la console
MOVED = {"chronologie": "systeme/chronologie", "etat": "systeme/etat", "contributions": "systeme/contributions",
         "sante": "systeme/sante", "appels": "systeme/appels", "rapports": "systeme/simulations",
         "facultes": "systeme/vues", "modeles": "reglages/modeles", "persona": "reglages/personnalite",
         "parametres": "reglages/parametres", "canaux": "reglages/canaux", "forge": "apps",
         "comptes": "reglages/comptes"}


#: les anciens onglets qui ont pris leur propre place (la requête suit)
MOVED_TABS = {("reglages", "apps"): "apps", ("sens", "courrier"): "courrier/reception",
              ("courrier", "comptes"): "reglages/boites",
              ("reglages", "modeles"): "reglages/fournisseurs", ("reglages", "personnalite"): "reglages/identite",
              ("reglages", "canaux"): "reglages/telegram", ("reglages", "sens"): "reglages/boites",
              ("reglages", "parametres"): "reglages/comportement"}


#: une action à plus de champs s'ouvre sur sa propre page, pas en panneau
PANEL_FIELDS_MAX = 2
#: un champ « sujet » propose au plus tant d'objets connus
SUBJECT_CHOICES = 300

#: au-delà, les rubriques d'un sous-menu qui ne contiennent pas la page se replient
SUBMENU_OPEN_MAX = 18

#: les anciens onglets de réglages qui recevaient des enregistrements
LEGACY_POSTS = {("modeles", ""), ("personnalite", ""), ("canaux", ""), ("sens", "")}


def safe_back(target: str) -> str:
    """Un retour dans la console seulement (jamais une autre adresse)."""
    if target.startswith(PREFIX + "/") and "//" not in target and "\\" not in target and len(target) < 2000:
        return target
    return PREFIX + "/"


def dest_url(key: str) -> str:
    return f"{PREFIX}/" if key == "accueil" else f"{PREFIX}/{key}"


class Pages:
    def __init__(self, ui: UI) -> None:
        self.ui = ui
        self.dests = destinations(ui.deps.navigation)

    # ── utilitaires ──
    def tabs_of(self, d: Destination) -> list[tuple[str, str, Builtin | InspectSpec]]:
        out: list[tuple[str, str, Builtin | InspectSpec]] = []
        for key in builtin_keys(d, self.ui.builtins):
            b = self.ui.builtins[key]
            out.append((b.slug, b.title, b))
        for v in self.ui.inspection.in_section(d.key):
            out.append((v.name, v.title, v))
        if d.order:
            rank = {name: i for i, name in enumerate(d.order)}
            out.sort(key=lambda t: rank.get(t[0], len(rank)))
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
        blocks = await self.ui.inspection.arun(item, request.query_params, self.ui.when_long)
        return {"blocks": blocks, "filters": () if any(isinstance(b, Filters | Workspace) for b in walk_blocks(blocks)) else item.typed}

    def back(self, request: Request) -> str:
        return request.url.path + (f"?{request.url.query}" if request.url.query else "")

    def slot_forms(self, request: Request, blocks: Sequence[Any], subject: str) -> dict[str, Any]:
        """Les formulaires des actions posées dans les blocs (``ActionSlot``), même
        dans le détail d'une ligne."""
        out: dict[str, Any] = {}
        csrf, back = self.ui.csrf(request), self.back(request)

        def walk(items: Sequence[Any]) -> None:
            for b in items:
                if b["t"] == "action":
                    spec = self.ui.inspection.action(b["key"])
                    if spec is not None and offered(self.ui.kernel, spec, subject):
                        initial = b["initial"]
                        dynamic = dynamic_fields(self.ui.kernel, spec, subject, initial) if spec.fields else None
                        view = action_view(spec, csrf=csrf, back=back, subject=subject,
                                           initial=initial, dynamic=dynamic, subjects=self.subject_choices)
                        if b["title"]:
                            view["title"] = b["title"]
                            view["button"] = initial.get("_bouton") or b["title"]
                        out[b["slot"]] = view
                elif b["t"] in ("grid", "section", "disclosure", "workspace", "toolbar"):
                    walk(b.get("sidebar", []) + b["items"])
                elif b["t"] == "table":
                    walk([x for r in b["rows"] for x in r["detail"]])

        walk(blocks)
        return out

    def subject_choices(self, kind: str) -> list[tuple[str, str]]:
        """Les objets connus d'un type (une personne, un but) : ce qu'un champ « sujet » propose."""
        return [(f.key, f"{f.title} — {f.subtitle}" if f.subtitle else f.title)
                for f in self.ui.inspection.search(kind, "", SUBJECT_CHOICES)]

    def head_actions(self, request: Request, *, section: str = "", kind: str = "", subject: str = "") -> list[Any]:
        """Les actions d'une page : une action courte s'ouvre en panneau ; une action à plus de deux champs a
        sa propre page (``/action/<clé>``), qui ramène ici."""
        specs = self.ui.inspection.actions_for(section=section) if section else \
            self.ui.inspection.actions_for(subject=kind)
        csrf, back = self.ui.csrf(request), self.back(request)
        out = []
        for a in specs:
            if not offered(self.ui.kernel, a, subject):
                continue
            view = action_view(a, csrf=csrf, back=back, subject=subject, subjects=self.subject_choices)
            if visible_fields(view) > PANEL_FIELDS_MAX:
                view["page"] = f"{PREFIX}/action/{quote(a.key, safe='')}?" + urlencode(
                    {"retour": back, **({"sujet": subject} if subject else {})})
            out.append(view)
        return out

    async def action_page(self, request: Request) -> Response:
        """Une action sur sa propre page : son formulaire en entier, chaque champ expliqué."""
        key = request.path_params["key"]
        spec = self.ui.inspection.action(key)
        subject = request.query_params.get("sujet", "")[:300]
        back = safe_back(request.query_params.get("retour", ""))
        if spec is None:
            return self.render_page(request, title="Action inconnue", active="", status=404,
                                    blocks=[Note("Cette action n'existe pas.", "warn")])
        if not offered(self.ui.kernel, spec, subject):
            return self.render_page(request, title=spec.title, active="", status=409, crumbs=[("Retour", back)],
                                    blocks=[Note("Cette action n'est pas possible maintenant (l'objet a changé ?).",
                                                 "warn")])
        dynamic = dynamic_fields(self.ui.kernel, spec, subject, {}) if spec.fields else None
        form = action_view(spec, csrf=self.ui.csrf(request), back=back, subject=subject, dynamic=dynamic,
                           subjects=self.subject_choices)
        form["description"] = ""  # dite en sous-titre de la page
        home = self.dests.get(spec.section) if spec.section else next(
            (d for d in self.dests.values() if spec.subject and spec.subject in d.subjects), None)
        crumbs = ([(home.label, dest_url(home.key))] if home else []) + [("Retour", back)]
        return self.render_page(request, title=spec.title, heading=spec.title, subtitle=spec.description,
                                active=home.key if home else "", crumbs=crumbs, blocks=[],
                                panel=Panel("_action_page.html", {"form": form}))

    def render_page(self, request: Request, *, title: str, active: str, blocks: Sequence[Any],
                    filters: Sequence[Param] = (), panel: Panel | None = None, keep: Sequence[tuple[str, str]] = (),
                    status: int = 200, subject: str = "", **ctx: Any) -> Response:
        query = {k: v for k, v in request.query_params.items()}
        env = self.ui.env()
        fctx, active_filter = render.filters_ctx(filters, query)
        reset = request.url.path + ("?" + urlencode(dict(keep)) if keep else "")
        panel_ctx = dict(panel.context) if panel else {}
        if panel_ctx.get("page_heading"):
            ctx["heading"] = panel_ctx.pop("page_heading")
            title = ctx["heading"] + " · " + title
        flash = self.ui.pop_flash(request.query_params.get("flash", ""))
        if flash:
            ctx["messages"] = [flash, *ctx.get("messages", [])]
        rendered = render.blocks(blocks, env, query)
        return self.ui.page(request, "page.html", title, active=active, status=status,
                            blocks=rendered, filters=fctx, filtered=active_filter,
                            keep=keep, reset=reset, panel=panel.template if panel else None,
                            forms=self.slot_forms(request, rendered, subject), **panel_ctx, **ctx)

    # ── destinations ──
    async def destination(self, request: Request, *, key: str = "", tab: str = "",
                          produced: dict[str, Any] | None = None, status: int = 200) -> Response:
        """Une destination et l'onglet demandé ; ``produced`` remplace le contenu de
        l'onglet (un formulaire refusé qu'on remontre, avec ``status``)."""
        key = key or request.path_params.get("key", "accueil")
        moved_tab = MOVED_TABS.get((key, request.path_params.get("tab", "")))
        if moved_tab and not tab:
            query = dict(request.query_params)
            owner = query.pop("faculte", "")
            if moved_tab == "reglages/comportement" and owner:
                moved_tab = f"reglages/comportement-{owner}"
            if moved_tab == "reglages/fournisseurs" and query.get("section") not in (None, "modeles"):
                query.pop("section", None)
            target = f"{PREFIX}/{moved_tab}" + ("?" + urlencode(query) if query else "")
            return RedirectResponse(target, status_code=301)
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
                blocks.append(Section(title, tuple(got["blocks"]),
                                      item.description if isinstance(item, Builtin) else ""))
            return self.render_page(request, title=d.label, active=d.key, blocks=blocks, subtitle=d.description,
                                    head_actions=self.head_actions(request, section=d.key) if d.automatic_actions else [])
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
                     "on": s == slug, "badge": self.tab_badge(b),
                     "group": b.group if isinstance(b, Builtin) else ""} for s, t, b in tabs]
        context = {k: request.query_params[k] for k in d.context if request.query_params.get(k)}
        if context:
            for t in tab_list:
                t["href"] += ("&" if "?" in t["href"] else "?") + urlencode(context)
        if d.layout == "menu":
            # un sous-menu rangé par rubrique : la page porte le titre de la sous-page
            submenu: list[dict[str, Any]] = []
            for t in tab_list:
                if not submenu or submenu[-1]["title"] != t["group"]:
                    submenu.append({"title": t["group"], "items": []})
                submenu[-1]["items"].append(t)
            group = next((t["group"] for t in tab_list if t["on"]), "")
            long_menu = len(tab_list) > SUBMENU_OPEN_MAX
            for g in submenu:
                g["open"] = not long_menu or any(t["on"] for t in g["items"]) or not g["title"]
            crumbs = [(d.label, dest_url(d.key))] + ([(group, "")] if group else []) + list(got.get("crumbs") or [])
            description = item.description if isinstance(item, Builtin) else getattr(item, "description", "")
            return self.render_page(request, title=f"{current[1]} · {d.label}", heading=current[1], active=d.key,
                                    subtitle=description or "", submenu=submenu, blocks=got["blocks"],
                                    head_actions=self.head_actions(request, section=d.key) if d.automatic_actions else [],
                                    filters=got.get("filters") or (), panel=got.get("panel"),
                                    messages=got.get("messages") or [], crumbs=crumbs, status=status)
        return self.render_page(request, title=f"{current[1]} · {d.label}", heading=current[1], active=d.key,
                                eyebrow=d.label if current[1] != d.label else "",
                                subtitle=item.description or d.description, tabs=tab_list, blocks=got["blocks"],
                                head_actions=self.head_actions(request, section=d.key) if d.automatic_actions else [],
                                filters=got.get("filters") or (), panel=got.get("panel"),
                                messages=got.get("messages") or [],
                                crumbs=got.get("crumbs") or [],
                                status=status)

    async def view(self, request: Request) -> Response:
        owner, name = request.path_params["owner"], request.path_params["name"]
        spec = self.ui.inspection.find(owner, name)
        if spec is None:
            return self.render_page(request, title="Vue inconnue", active="", status=404,
                                    blocks=[Note("Cette vue n'existe pas.", "warn")])
        d = self.dests.get(spec.section)
        if d is not None and not spec.hidden:
            target = f"{dest_url(d.key)}/{spec.name}"
            if request.url.query:
                target += "?" + request.url.query
            return RedirectResponse(target, status_code=303)
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
        blocks = episode_tab(self.ui, corr, slug, info, request.query_params)
        return self.render_page(request, title=f"Épisode · {info['kind']}", heading=f"Un épisode : {info['kind']}",
                                subtitle=dict(EPISODE_TABS)[slug] + " · " + {
                                    "deroule": "Les événements de cet épisode dans leur ordre d'exécution.",
                                    "dit": "Les paroles produites et ce qui a été montré à la personne.",
                                    "prompt": "Le contexte exact transmis au modèle, avec la provenance de chaque partie.",
                                    "outils": "Les outils appelés, leurs arguments et leurs résultats.",
                                    "appels": "Les appels de modèle associés, leur durée et leur coût.",
                                    "decision": "Le déclencheur de l'épisode et les raisons de la décision.",
                                }[slug],
                                active="decisions", crumbs=[("Décisions", f"{PREFIX}/decisions/episodes")],
                                head_badges=info["badges"], facts=info["facts"], tabs=tabs, blocks=blocks)

    async def event(self, request: Request) -> Response:
        try:
            seq = int(request.path_params["seq"])
        except ValueError:
            seq = 0
        got = event_blocks(self.ui, seq, request.query_params) if seq > 0 else None
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
                               errors=outcome.errors, dynamic=dynamic, subjects=self.subject_choices)
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
                                                        note=data.get("note", "")[:500], seen=data.get("seen", ""))
        if status in ("approved", "rejected") and self.ui.deps.after_decision is not None:
            await self.ui.deps.after_decision()
        outcome = {"approved": "oui", "rejected": "non", "changed": "change", "blocked": "bloque"}.get(status,
                                                                                                    "inconnu")
        return RedirectResponse(f"{target}?fait={outcome}", status_code=303)

    async def settings_post(self, request: Request) -> Response:
        """Enregistrer une page de configuration : une section de réglages, les
        paramètres d'une faculté, un compte."""
        tab = request.path_params["tab"]
        if tab == "comptes":
            response, state, status = await accounts.post(self.ui, request)
            if response is not None:
                return response
            produced = await accounts.page(self.ui, request, state)
            return await self.destination(request, key="reglages", tab=tab, produced=produced, status=status)
        if tab in ("comportement", "parametres") or tab.startswith(reglages.FACULTY_PAGE):
            response, state, status = await reglages.parametres_post(self.ui, request)
            if response is not None:
                return response
            owner = state.get("owner", "")
            target = f"{reglages.FACULTY_PAGE}{owner}" if owner and self.ui.builtins.get(
                f"reglages.{reglages.FACULTY_PAGE}{owner}") else "comportement"
            got = await reglages.faculty_page(self.ui, request, owner, state) if owner else \
                {"blocks": reglages.overview(self.ui), "messages": list(state.get("messages", []))}
            return await self.destination(request, key="reglages", tab=target, produced=got, status=status)
        forms_ = self.ui.settings_forms
        if forms_ is not None and tab not in forms_.pages and (tab, "") in LEGACY_POSTS:
            # une ancienne adresse d'enregistrement (un onglet par section) : la page qui montre ce champ
            data = await request.form()
            path = str(data.get("_enregistrement") or data.get("_supprimer") or data.get("_champs") or "")
            tab = forms_.page_for(str(data.get("_section") or ""), path) or tab
        if forms_ is None or tab not in forms_.pages:
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
            Route(PREFIX + "/action/{key:str}", g(self.action_page), methods=["GET"]),
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
