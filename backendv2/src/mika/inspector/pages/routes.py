"""Les routes de la console : le rendu des destinations et de leurs onglets, des vues déclarées, des épisodes et des
événements, l'enregistrement des réglages, et la table des routes qui assemble le tout (la connexion : ``auth.py`` ;
les actions d'opérateur et les approbations : ``actions.py``)."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import quote, urlencode

from sqlalchemy import select
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

from mika.inspector import render
from mika.inspector.catalog import Builtin, Panel, destinations, menu_place
from mika.inspector.pages import accounts, params
from mika.inspector.pages.actions import Actions, per_row, safe_back
from mika.inspector.pages.auth import Auth
from mika.inspector.pages.canals import canals_post
from mika.inspector.pages.episode_drawn import episode_panel
from mika.inspector.pages.families import families_post
from mika.inspector.pages.journal import (
    EPISODE_TABS,
    episode_head,
    episode_tab,
    event_page,
    event_panel,
    replay_blocks,
    replay_panel,
)
from mika.inspector.pages.subjects import Subjects, fiche_url
from mika.inspector.pages.system import outbox_post
from mika.inspector.pages.tools import expose_post
from mika.inspector.pages.why import silence_page, why_page, why_panel
from mika.inspector.ui import PREFIX, UI, Forms, wants_table
from mika.kernel.faculty import InspectSpec
from mika.kernel.inspect import (
    Filters,
    Note,
    Param,
    Workspace,
    int_query,
    is_table_choice,
    walk_blocks,
)
from mika.ports.journal import JournalEvent
from mika.runtime.boundary import Failed, call

__all__ = ["Pages", "per_row"]

#: les anciennes adresses de l'inspecteur → la console
MOVED = {"chronologie": "systeme/chronologie", "etat": "systeme/etat", "contributions": "systeme/contributions",
         "sante": "systeme/sante", "appels": "systeme/appels", "rapports": "systeme/simulations",
         "facultes": "systeme/vues", "modeles": "reglages/fournisseurs", "persona": "reglages/identite",
         "parametres": "reglages/comportement", "forge": "apps",
         "comptes": "reglages/comptes"}


#: les anciens onglets qui ont pris leur propre place (la requête suit)
MOVED_TABS = {("reglages", "apps"): "apps", ("sens", "courrier"): "courrier/reception",
              ("courrier", "comptes"): "courrier/parametres",
              ("reglages", "modeles"): "reglages/fournisseurs", ("reglages", "personnalite"): "reglages/identite",
              ("reglages", "sens"): "reglages/plugins",
              ("reglages", "parametres"): "reglages/comportement",
              # le bloc Outils redessiné : la grille dit qui reçoit quoi et s'y règle ; ses apps, sous les services
              ("outils", "qui"): "outils/tous", ("outils", "texte"): "outils/tous",
              ("outils", "outils_apps"): "outils/serveurs",
              # un profil n'est qu'un préréglage du tempérament : il se choisit en haut de sa page
              ("reglages", "profil"): "reglages/temperament",
              # ce qui attend ta décision ne se décide que dans la file (ADR 0180)
              ("identites", "revendications"): "approbations/identites", ("identites", "noms"): "approbations/noms",
              # le fil de tous les messages : Conversations s'ouvre sur les personnes, leur filtre gardé (ADR 0181)
              ("fil", "messages"): "fil/conversations",
              # la place de chacun se lit avec les pièces, en sous-onglet (une ancre : « #… », après la requête)
              ("memoire", "place"): "memoire/recues#pieces-place"}

#: les anciennes pages d'un objet (des vues cachées, retirées) : sa fiche, ou sa liste si l'adresse ne le nomme pas
#: (ADR 0217) — l'ancienne adresse → (la sorte de fiche, le paramètre qui le nommait, la liste)
MOVED_VIEWS = {"identity/personne": ("handle", "handle", "identites/annuaire"), "forge/app": ("app", "app", "apps")}

#: l'ancien paramètre d'une liste qui ouvrait le détail d'un objet : sa fiche (ADR 0217) — (destination, onglet) →
#: (le paramètre, la sorte de fiche, l'onglet de la fiche)
MOVED_PARAMS = {("personnes", "liens"): ("person", "person", "lien")}

#: les anciens onglets de réglages qui recevaient des enregistrements (« canaux » et « sens » : les anciennes clés des
#: rubriques Carte et téléphone et Plugins, ADR 0197)
LEGACY_POSTS = frozenset({"modeles", "personnalite", "canaux", "sens"})

#: les listes où vivent les épisodes et les événements : leur fil d'Ariane y mène
EPISODES = "decisions/episodes"
JOURNAL = "systeme/chronologie"


def dest_url(key: str) -> str:
    return f"{PREFIX}/{key}"


class Pages(Actions):
    def __init__(self, ui: UI) -> None:
        self.ui = ui
        self.dests = destinations(ui.deps.navigation)
        #: la rubrique où chaque destination est rangée (``app/console.py``)
        self.homes = {d.key: g.label for g in ui.deps.navigation for d in g.items}

    # ── le fil d'Ariane ──
    def trail(self, target: str, *levels: tuple[str, str], title: str = "", link: str = "",
              group: str = "") -> list[tuple[str, str]]:
        """Le fil d'Ariane d'une page (ADR 0177, 0202), le seul : il part de la rubrique du menu dont un lien mène à
        ``target`` — la page du menu où elle vit (« destination/onglet » : son onglet, la liste d'une fiche) —, puis
        dit sa destination ; pour Réglages et Système, le lien de menu qui couvre la page (sa colonne, s'il en a une),
        ``group`` en repli quand seul l'annuaire la couvre. La page n'y ajoute que ses niveaux à elle (``levels`` :
        un compte par son nom, un événement par son numéro). Chaque niveau mène à sa page, sauf la page même
        (``title`` : son titre quand c'est une page du menu, vide pour une fiche). ``link`` : où mène le niveau de la
        destination quand on y revient ailleurs qu'à sa racine (la liste filtrée d'où vient la fiche)."""
        menu = self.ui.deps.menu
        dest = self.dests.get(target.split("/", 1)[0])
        own = list(levels)
        place = menu_place(menu, self.ui.deps.navigation, target)
        if place is None:
            return ([(dest.label, link or dest_url(dest.key))] if dest is not None else []) + own
        rubric_of, entry, route = menu[place[0]], menu[place[0]].items[place[1]], place[2]
        rubric = self.ui.her_name() if rubric_of.her else (rubric_of.short or rubric_of.label)
        # la page même du lien : son niveau se dit sans lien
        itself = bool(title) and not own and target == entry.target
        if dest is None:  # une page dessinée hors des destinations (En ce moment)
            return [(rubric, ""), (entry.label, "" if itself else f"{PREFIX}/{entry.target}")] + own
        if dest.layout != "menu":
            # une rubrique qui porte le nom de sa destination (« À valider ») ne se dit qu'une fois
            out = [] if rubric == dest.label else [(rubric, "")]
            here = bool(title) and not own and title == dest.label
            return out + [(dest.label, "" if here else link or dest_url(dest.key))] + own
        # Réglages, Système : des pages rangées par le menu ; leur lien dit le second niveau
        out = [(dest.label, dest_url(dest.key))] if rubric_of.label == self.homes.get(dest.key) else [(rubric, "")]
        if route == dest.key:  # seul l'annuaire la couvre : son groupe, en repli
            return out + ([(group, "")] if group else []) + own
        if entry.column:
            out.append((entry.column, ""))
            if not itself:
                out.append((entry.label, f"{PREFIX}/{entry.target}"))
        else:
            out.append((entry.label, "" if itself else f"{PREFIX}/{entry.target}"))
            # une page de faculté : sa famille (« Paramètres avancés · Émotions »), après le lien qui y mène ; elle
            # mène à la vue d'ensemble, ouverte sur cette famille (son ancre, ``handmade/reglages/comportement.html``)
            if group.startswith(entry.label + " · "):
                family = group.removeprefix(entry.label + " · ")
                out.append((family, f"{PREFIX}/{entry.target}#famille-{family.lower().replace(' ', '-')}"))
        return out + own

    def family(self, page: str) -> tuple[str, ...]:
        """Les pages d'un même sujet : celles du lien de menu qui nomme cette page (sa cible, puis ``also``, dans
        l'ordre déclaré) — la barre d'onglets d'une page de Réglages ou de Système (C7-03)."""
        place = menu_place(self.ui.deps.menu, self.ui.deps.navigation, page)
        if place is None or place[2] != page:
            return ()
        link = self.ui.deps.menu[place[0]].items[place[1]]
        return (link.target, *link.also)

    # ── utilitaires ──
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
                # ``crumbs`` : ses niveaux à elle, après ceux du menu ; ``back`` : la liste d'où l'on vient (``trail``)
                return {"blocks": list(got.get("blocks") or []), "filters": tuple(got.get("filters") or ()),
                        "panel": got.get("panel"), "messages": list(got.get("messages") or []),
                        "crumbs": list(got.get("crumbs") or []), "back": str(got.get("back") or "")}
            if isinstance(got, Panel):
                return {"blocks": [], "panel": got}
            return {"blocks": list(got or [])}
        blocks = await self.ui.inspection.arun(item, request.query_params, self.ui.when_long)
        return {"blocks": blocks, "filters": () if any(isinstance(b, Filters | Workspace) for b in walk_blocks(blocks)) else item.typed}

    def back(self, request: Request) -> str:
        return request.url.path + (f"?{request.url.query}" if request.url.query else "")

    def action_trail(self, spec: Any, back: str) -> tuple[Any, list[tuple[str, str]], tuple[str, str] | None]:
        """Le fil d'une page d'action : la destination de son objet (ou de sa section) depuis sa rubrique, et le
        retour vers la page d'où l'on vient, dit à part (il ne remplace pas le chemin, ADR 0202)."""
        home = self.dests.get(spec.section) if spec.section else next(
            (d for d in self.dests.values() if spec.subject and spec.subject in d.subjects), None)
        crumbs = self.trail(home.key) if home is not None else []
        same = back.rstrip("/") in (PREFIX, dest_url(home.key) if home is not None else PREFIX)
        return home, crumbs, None if same else ("Retour", back)

    def render_page(self, request: Request, *, title: str, active: str, blocks: Sequence[Any],
                    filters: Sequence[Param] = (), panel: Panel | None = None, keep: Sequence[tuple[str, str]] = (),
                    status: int = 200, subject: str = "", **ctx: Any) -> Response:
        query = {k: v for k, v in request.query_params.items()}
        keep = [*keep, *((k, v) for k, v in query.items() if is_table_choice(k, v) and k not in dict(keep))]
        env = self.ui.env()
        fctx, active_filter = render.filters_ctx(filters, query)
        # des filtres faits de petits choix : des boutons à choix au bout de la barre d'onglets, pas un formulaire
        quick = render.quick_filters(fctx, keep)
        if quick:
            fctx, ctx["quick"] = [], quick
        reset = request.url.path + ("?" + urlencode(dict(keep)) if keep else "")
        panel_ctx = dict(panel.context) if panel else {}
        if panel_ctx.get("page_heading"):
            ctx["heading"] = panel_ctx.pop("page_heading")
            title = ctx["heading"] + " · " + title
        if "page_subtitle" in panel_ctx:
            ctx["subtitle"] = panel_ctx.pop("page_subtitle")
        if "page_links" in panel_ctx:  # les actions de la page, à droite de son titre (ADR 0176)
            ctx["head_links"] = panel_ctx.pop("page_links")
        flash = self.ui.pop_flash(request.query_params.get("flash", ""))
        if flash:
            ctx["messages"] = [flash, *ctx.get("messages", [])]
        rendered = render.blocks(blocks, env, query)
        return self.ui.page(request, "page.html", title, active=active, status=status,
                            blocks=rendered, filters=fctx, filtered=active_filter,
                            keep=keep, reset=reset, panel=panel.template if panel else None,
                            panel_styles=panel.styles if panel else (),
                            forms=self.slot_forms(request, rendered, subject), **panel_ctx, **ctx)

    # ── destinations ──
    async def destination(self, request: Request, *, key: str = "", tab: str = "",
                          produced: dict[str, Any] | None = None, status: int = 200) -> Response:
        """Une destination et l'onglet demandé ; ``produced`` remplace le contenu de
        l'onglet (un formulaire refusé qu'on remontre, avec ``status``)."""
        key = key or request.path_params["key"]
        moved_param = MOVED_PARAMS.get((key, request.path_params.get("tab", "")))
        if moved_param and not tab and (named := request.query_params.get(moved_param[0])):
            return RedirectResponse(fiche_url(moved_param[1], named, moved_param[2]), status_code=301)
        moved_tab = MOVED_TABS.get((key, request.path_params.get("tab", "")))
        if moved_tab and not tab:
            query = dict(request.query_params)
            owner = query.pop("faculte", "")
            if moved_tab == "reglages/comportement" and owner:
                moved_tab = f"reglages/comportement-{owner}"
            if moved_tab == "reglages/fournisseurs" and query.get("section") not in (None, "modeles"):
                query.pop("section", None)
            path, _, anchor = moved_tab.partition("#")
            target = f"{PREFIX}/{path}" + ("?" + urlencode(query) if query else "") + (f"#{anchor}" if anchor else "")
            return RedirectResponse(target, status_code=301)
        if key in MOVED and "tab" not in request.path_params and not tab:
            return RedirectResponse(f"{PREFIX}/{MOVED[key]}", status_code=301)
        forms_ = self.ui.settings_forms
        asked = request.path_params.get("tab", "")
        if key == "reglages" and not tab and forms_ is not None and asked in forms_.pages \
                and forms_.pages[asked][1].home:  # une page de réglages qui vit ailleurs (Courrier › Paramètres)
            return RedirectResponse(forms_.url(asked, **dict(request.query_params)), status_code=301)
        d = self.dests.get(key)
        if d is None:
            return self.render_page(request, title="Page inconnue", active="", status=404,
                                    blocks=[Note("Cette page n'existe pas.", "warn")])
        tabs = self.ui.tabs_of(d)
        # l'onglet par défaut : le premier de la barre (pas un de ceux rangés derrière le bouton du haut)
        first = next((t[0] for t in tabs if t[0] not in d.gear), tabs[0][0] if tabs else "")
        slug = tab or request.path_params.get("tab", "") or first
        current = next((t for t in tabs if t[0] == slug), None)
        if current is None:
            return RedirectResponse(dest_url(d.key), status_code=303)
        item = current[2]
        got = produced if produced is not None else await self.produce(item, request)
        if "response" in got:
            return got["response"]
        drawn = self.drawn(request, f"{d.key}/{slug}", got) if produced is None else {}
        if drawn:
            got = {**got, "blocks": drawn.pop("blocks"), **({} if drawn.pop("panel") else {"panel": None})}
        tab_list = [{"title": t, "href": f"{dest_url(d.key)}/{s}", "on": s == slug, "badge": self.tab_badge(b),
                     "group": b.group if isinstance(b, Builtin) else "", "slug": s} for s, t, b in tabs]
        context = {k: request.query_params[k] for k in d.context if request.query_params.get(k)}
        if context:
            for t in tab_list:
                t["href"] += ("&" if "?" in t["href"] else "?") + urlencode(context)
        # ses paramètres : un bouton en haut à droite, pas un onglet de plus (ADR 0173)
        gear = [t for t in tab_list if t["slug"] in d.gear]
        tab_list = [t for t in tab_list if t["slug"] not in d.gear]
        if d.lead:  # sa page, dessinée à part (Personnes) : le premier onglet, qui y ramène (ADR 0176)
            tab_list.insert(0, {"title": d.lead, "href": dest_url(d.key), "on": False, "badge": 0, "group": "",
                                "slug": ""})
        # le fil d'Ariane (ADR 0176, 0202) : la rubrique du menu, puis la destination — un lien quand le titre est
        # celui de l'onglet (« Mika / Humeur et corps », puis « Besoins ») —, puis ce que l'onglet ajoute (l'outil
        # ouvert depuis la liste : « Outils / Ses outils / email_read », la destination menant à cette liste)
        group = next((t["group"] for t in tab_list if t["on"]), "")
        crumbs = self.trail(f"{d.key}/{slug}", *(got.get("crumbs") or ()), title=current[1],
                            link=got.get("back") or "", group=group)
        if d.layout == "menu":
            # des pages rangées par le menu : la page porte le titre de la sous-page
            description = item.description if isinstance(item, Builtin) else getattr(item, "description", "")
            # Les pages d'un même sujet restent côte à côte (ex. fournisseurs et rôles), dans l'ordre de leur lien
            # au menu ; pour les réglages, le répertoire complet est « Tous les réglages ».
            by_page = {t["href"].removeprefix(PREFIX + "/"): t for t in tab_list}
            related = [by_page[page] for page in self.family(f"{d.key}/{slug}") if page in by_page]
            return self.render_page(request, title=f"{current[1]} · {d.label}", heading=current[1], active=d.key,
                                    subtitle=description or "", tabs=related, blocks=got["blocks"],
                                    console_blocks=getattr(item, "owner", "") in self.ui.deps.plain_owners, **drawn,
                                    head_actions=self.head_actions(request, section=d.key) if d.automatic_actions else [],
                                    filters=got.get("filters") or (), panel=got.get("panel"),
                                    messages=got.get("messages") or [], crumbs=crumbs, status=status)
        return self.render_page(request, title=f"{current[1]} · {d.label}", heading=current[1], active=d.key,
                                subtitle=item.description or d.description, tabs=tab_list, gear=gear,
                                blocks=got["blocks"],
                                console_blocks=getattr(item, "owner", "") in self.ui.deps.plain_owners, **drawn,
                                head_actions=self.head_actions(request, section=d.key) if d.automatic_actions else [],
                                filters=got.get("filters") or (), panel=got.get("panel"),
                                messages=got.get("messages") or [],
                                crumbs=crumbs,
                                status=status)

    def drawn(self, request: Request, where: str, got: Mapping[str, Any]) -> dict[str, Any]:
        """Un onglet que la composition dessine (ADR 0121) : son HTML, ses feuilles, et les blocs que la console
        rend encore (ses formulaires) ; rien s'il ne l'est pas, ou si son dessin échoue (ses blocs, alors)."""
        known = self.ui.deps.drawn
        # « destination/préfixe-* » : tous les onglets qui commencent ainsi (les pages de réglages d'une faculté)
        drawn = known.get(where) or next((v for k, v in known.items() if k.endswith("*") and where.startswith(k[:-1])),
                                         None)
        if drawn is None or "blocks" not in got or wants_table(request.query_params):
            return {}
        blocks, query = list(got["blocks"]), dict(request.query_params)
        forms = Forms(self.slot_forms(request, render.blocks(blocks, self.ui.env(), query), ""),
                      lambda rendered, subject: self.slot_forms(request, rendered, subject), self.ui.csrf(request))
        out = call(drawn.render, self.ui, blocks, query, forms, label=f"onglet dessiné {where}")
        head: Any = ""
        if isinstance(out, tuple):
            html, rest = out[0], list(out[1])
            head = out[2] if len(out) > 2 else ""
        elif out is None or isinstance(out, Failed):
            return {}
        else:
            html, rest = out, []
        return {"blocks": rest, "panel": drawn.panel, "overview": html, "overview_last": drawn.last,
                "fiche_styles": drawn.styles, "fiche_scripts": drawn.scripts, "head_extra": head}

    async def view(self, request: Request) -> Response:
        owner, name = request.path_params["owner"], request.path_params["name"]
        if f"{owner}/{name}" in MOVED_VIEWS:
            kind, param, listing = MOVED_VIEWS[f"{owner}/{name}"]
            subject = request.query_params.get(param, "")
            return RedirectResponse(fiche_url(kind, subject) if subject else f"{PREFIX}/{listing}", status_code=301)
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
        # une vue cachée : dans sa destination ; une vue sans destination : sous Système › Toutes les vues
        crumbs = self.trail(d.key) if d else self.trail("systeme/vues")
        where = {} if d else {"menu_path": f"{PREFIX}/systeme/vues", "menu_tab": False}
        blocks = await self.ui.inspection.arun(spec, request.query_params, self.ui.when_long)
        return self.render_page(request, title=spec.title, active=d.key if d else "systeme", crumbs=crumbs,
                                blocks=blocks, filters=spec.typed, subtitle=spec.description,
                                console_blocks=spec.owner in self.ui.deps.plain_owners, **where)

    # ── épisode, événement ──
    async def episode(self, request: Request) -> Response:
        corr = request.path_params["corr"]
        info = episode_head(self.ui, corr)
        if info is None:
            if self.ui.kernel.mind.store.query_mind(
                    select(JournalEvent.seq).where(JournalEvent.correlation == corr).limit(1)):
                # une action d'opérateur, un effet, un processus : pas un épisode — ses événements, dans le journal
                return RedirectResponse(f"{PREFIX}/systeme/chronologie?" + urlencode({"correlation": corr}),
                                        status_code=303)
            return self.render_page(request, title="Épisode inconnu", active="decisions", status=404,
                                    blocks=[Note("Aucun épisode sous ce nom.", "warn")])
        # Les anciens liens paginés sans onglet continuent à ouvrir le journal.
        slug = request.query_params.get("onglet", "deroule" if "page" in request.query_params else "resume")
        if slug not in dict(EPISODE_TABS):
            slug = "resume"
        base = f"{PREFIX}/episode/{quote(corr, safe='')}"
        tabs = [{"title": t, "href": f"{base}?onglet={s}", "on": s == slug, "badge": 0} for s, t in EPISODE_TABS]
        panel = replay_panel(self.ui, corr, self.back(request)) if slug == "prompt" else None
        # dessinée (ADR 0121) ; ses blocs au repli, ou quand une liste est demandée en tableau
        drawn = None if wants_table(request.query_params) else episode_panel(
            self.ui, corr, slug, info, dict(request.query_params), self.ui.env(), panel)
        blocks = [] if drawn is not None else episode_tab(self.ui, corr, slug, info, request.query_params)
        return self.render_page(request, title=f"Épisode · {info['kind']}", heading=f"Un épisode : {info['kind']}",
                                subtitle=dict(EPISODE_TABS)[slug] + " · " + {
                                    "resume": "Le résultat, le déclencheur et les paroles produites, en un regard.",
                                    "deroule": "Les événements de cet épisode dans leur ordre d'exécution.",
                                    "dit": "Les paroles produites et ce qui a été montré à la personne.",
                                    "prompt": "Le contexte exact transmis au modèle, avec la provenance de chaque partie.",
                                    "outils": "Les outils appelés, leurs arguments et leurs résultats.",
                                    "appels": "Les appels de modèle associés, leur durée et leur coût.",
                                    "decision": "Le déclencheur de l'épisode et les raisons de la décision.",
                                }[slug],
                                active="decisions", crumbs=self.trail(EPISODES, ("Épisodes", f"{PREFIX}/{EPISODES}")),
                                head_badges=info["badges"], facts=info["facts"], tabs=tabs, blocks=blocks,
                                panel=drawn or panel)

    async def replay(self, request: Request) -> Response:
        """« Rejouer avec… » : le prompt gardé d'un épisode envoyé à un autre fournisseur (``journal.replay_blocks``).
        La réponse se lit sur cette page et n'est gardée nulle part ; un formulaire sans jeton ne part pas."""
        data = await self.ui.form(request)
        account = self.ui.operator(request)
        title = "Rejouer avec un autre modèle"
        if data is None or account is None:
            return self.render_page(request, title=title, active="decisions", status=403,
                                    blocks=[Note("Jeton de formulaire invalide : recharge la page.", "danger")])
        corr = str(data.get("episode", ""))[:300]
        backend = str(data.get("fournisseur", ""))[:200]
        back = safe_back(str(data.get("_retour", "")))
        blocks, status = await replay_blocks(self.ui, corr, backend, by=account.handle)
        # sous l'épisode qu'il rejoue (le formulaire y était : son onglet Prompt)
        crumbs = self.trail(EPISODES, ("Épisodes", f"{PREFIX}/{EPISODES}"),
                            ("Son épisode", f"{PREFIX}/episode/{quote(corr, safe='')}?onglet=prompt"))
        return self.render_page(request, title=title, heading=title, active="decisions", status=status,
                                subtitle=f"Le même prompt, envoyé à « {backend} » : ce qu'elle a vraiment dit, et ce "
                                         "que ce modèle répond.", crumbs=crumbs, blocks=blocks,
                                panel=replay_panel(self.ui, corr, back) if status == 200 else None)

    async def outbox(self, request: Request) -> Response:
        """Système › File de sortie : relancer un effet en échec, ou le marquer comme vu."""
        return await outbox_post(self.ui, request)

    async def canals(self, request: Request) -> Response:
        """Réglages › Canaux : le tableau d'un canal, enregistré d'un coup (ADR 0134)."""
        return await canals_post(self.ui, request)

    async def families(self, request: Request) -> Response:
        """Outils › Ses propres outils : le tableau d'une famille, enregistré d'un coup (ADR 0134)."""
        return await families_post(self.ui, request)

    async def expose(self, request: Request) -> Response:
        """Outils › Prêter à un agent : la console en MCP, ses points de prêt (ADR 0122)."""
        return await expose_post(self.ui, request)

    async def why(self, request: Request) -> Response:
        """« Pourquoi a-t-elle dit ça ? » : une de ses paroles, expliquée — et, pour un message reçu resté sans
        réponse, « Pourquoi n'a-t-elle pas répondu ? »."""
        seq = int_query(request.path_params["seq"], 0)
        spoken = why_page(self.ui, seq) if seq > 0 else None
        got = spoken or (silence_page(self.ui, seq) if seq > 0 else None)
        if got is None:
            return self.render_page(request, title="Parole introuvable", active="fil", status=404,
                                    blocks=[Note("Ce numéro n'est ni une de ses paroles, ni un message resté sans "
                                                 "réponse.", "warn")])
        env = self.ui.env()
        facts = [{"label": k, "cell": render.cell(v, env)} for k, v in got["facts"]]
        # une parole (ou un message resté sans réponse) par son numéro, sous les conversations ; son épisode est
        # dans ses faits
        crumbs = self.trail("fil", (f"n° {seq}", ""))
        panel = replay_panel(self.ui, got["correlation"], self.back(request)) if spoken and got["correlation"] else None
        # dessinée (ADR 0121), sauf au repli : ses blocs, si le dessin échoue ou si on demande le tableau
        drawn = None if wants_table(request.query_params) else why_panel(got, env, dict(request.query_params), panel)
        if drawn is not None:
            return self.render_page(request, title=got["title"], heading=got["title"], active="fil", facts=facts,
                                    blocks=[], crumbs=crumbs, panel=drawn)
        return self.render_page(request, title=got["title"], heading=got["title"], subtitle=got["subtitle"],
                                active="fil", facts=facts, blocks=got["blocks"], crumbs=crumbs, panel=panel)

    async def event(self, request: Request) -> Response:
        seq = int_query(request.path_params["seq"], 0)
        got = event_page(self.ui, seq, request.query_params) if seq > 0 else None
        if got is None:
            return self.render_page(request, title="Événement introuvable", active="systeme", status=404,
                                    blocks=[Note("Aucun événement à ce numéro.", "warn")])
        # dessinée (ADR 0121) ; ses blocs au repli
        drawn = None if wants_table(request.query_params) else event_panel(got, self.ui.env(),
                                                                           dict(request.query_params))
        # un événement par son numéro, sous le journal (« Système / Journaux / Journal d'événements / n° 93 ») : le
        # menu allume le journal, pas un de ses onglets
        crumbs = self.trail(JOURNAL, (f"n° {seq}", ""))
        where = {"menu_path": f"{PREFIX}/{JOURNAL}", "menu_tab": False}
        if drawn is not None:
            return self.render_page(request, title=got["title"], active="systeme", crumbs=crumbs, blocks=[],
                                    panel=drawn, **where)
        return self.render_page(request, title=got["title"], active="systeme", crumbs=crumbs, blocks=got["blocks"],
                                **where)

    # ── vitaux ──
    async def vitals(self, request: Request) -> Response:
        return self.ui.fragment("_vitals.html", vitals=self.ui.vitals())

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
        if tab in ("comportement", "parametres") or tab.startswith(params.FACULTY_PAGE):
            response, state, status = await params.parametres_post(self.ui, request)
            if response is not None:
                return response
            owner = state.get("owner", "")
            forms_ = self.ui.settings_forms
            page = forms_.carrying(owner, state.get("back", "")) if forms_ is not None else ""
            if page:  # refusés sur la page qui les porte (Courrier › Paramètres) : remontrés là
                panel = await forms_.panel(self.ui, request, page, {}, params=state)
                key, slug = forms_.home(page)
                return await self.destination(request, key=key, tab=slug, status=status,
                                              produced={"blocks": [], "panel": panel})
            target = f"{params.FACULTY_PAGE}{owner}" if owner and self.ui.builtins.get(
                f"reglages.{params.FACULTY_PAGE}{owner}") else "comportement"
            got = await params.faculty_page(self.ui, request, owner, state) if owner else \
                {"blocks": params.overview(self.ui), "messages": list(state.get("messages", []))}
            return await self.destination(request, key="reglages", tab=target, produced=got, status=status)
        forms_ = self.ui.settings_forms
        if forms_ is not None and tab not in forms_.pages and tab in LEGACY_POSTS:
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
        key, slug = forms_.home(tab)  # là où vit la page (Courrier › Paramètres), sinon Réglages
        return await self.destination(request, key=key, tab=slug, status=status,
                                      produced={"blocks": [], "panel": panel, "messages": general})

    async def settings_probe(self, request: Request) -> Response:
        """L'état d'une section de réglages en JSON (``SettingsSection.probe``), pour le script d'une de ses pages :
        la modale qui suit l'écriture de son caractère (ADR 0139). Une page sans sonde : 404, vide."""
        forms_ = self.ui.settings_forms
        found = forms_.pages.get(request.path_params["tab"]) if forms_ is not None else None
        section = found[0] if found else None
        if section is None or section.probe is None:
            return Response("{}", status_code=404, media_type="application/json")
        got = call(section.probe, label=f"état {section.key}")
        if isinstance(got, Failed):
            return Response("{}", status_code=500, media_type="application/json")
        return Response(json.dumps(dict(got), ensure_ascii=False), media_type="application/json")

    def routes(self) -> list[Route]:
        g = self.ui.guarded
        auth = Auth(self.ui)
        return [
            Route(PREFIX + "/reglages/{tab:str}", g(self.settings_post), methods=["POST"]),
            Route(PREFIX + "/reglages/{tab:str}/etat", g(self.settings_probe)),
            Route(PREFIX + "/connexion", auth.login, methods=["GET", "POST"]),
            Route(PREFIX + "/deconnexion", auth.logout, methods=["POST"]),
            Route(PREFIX + "/_vitals", g(self.vitals)),
            Route(PREFIX + "/approbations", g(self.approve), methods=["POST"]),
            Route(PREFIX + "/action/{key:str}", g(self.act), methods=["POST"]),
            Route(PREFIX + "/action/{key:str}", g(self.action_page), methods=["GET"]),
            Route(PREFIX + "/episode/{corr:str}", g(self.episode)),
            Route(PREFIX + "/rejouer", g(self.replay), methods=["POST"]),
            Route(PREFIX + "/parole/{seq:str}", g(self.why)),
            Route(PREFIX + "/evenement/{seq:str}", g(self.event)),
            Route(PREFIX + "/systeme/sorties", g(self.outbox), methods=["POST"]),
            Route(PREFIX + "/outils/exposer", g(self.expose), methods=["POST"]),
            Route(PREFIX + "/outils/familles/regler", g(self.families), methods=["POST"]),
            Route(PREFIX + "/reglages/canaux/regler", g(self.canals), methods=["POST"]),
            Route(PREFIX + "/facultes/{owner:str}/{name:str}", g(self.view)),
            *Subjects(self).routes(),
        ]

    def catchall(self) -> list[Route]:
        """Les destinations : en dernier (toute autre route passe avant ; la racine est l'accueil, dessiné à la
        main : ``app/handmade/home.py``)."""
        g = self.ui.guarded
        return [
            Route(PREFIX + "/{key:str}", g(self.destination)),
            Route(PREFIX + "/{key:str}/{tab:str}", g(self.destination)),
        ]
