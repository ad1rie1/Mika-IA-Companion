"""Les fiches d'objets : une personne, une adresse, un but, une app… L'en-tête
vient de la faculté qui déclare le type d'objet ; chaque onglet, de la
faculté qui l'y ajoute — la console n'en connaît aucune. Et la recherche, et
l'oubli d'un objet qui est un sujet de contenus."""

from __future__ import annotations

from typing import Any
from unicodedata import combining, normalize
from urllib.parse import quote, urlencode

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

from mika.inspector import render
from mika.inspector.catalog import Builtin
from mika.inspector.ui import PREFIX, Forms, secure, wants_table
from mika.kernel.inspect import Download, Head, Note, Pager, Ref, Row, Table, Text, is_page_param
from mika.runtime import operations
from mika.runtime.boundary import Failed, call

#: Une page par type d'objet, sans plafond sur l'ensemble des résultats.
SEARCH_PAGE = 25


def search_text(text: str) -> str:
    """La navigation se cherche aussi sans les accents affichés dans ses titres."""
    return "".join(c for c in normalize("NFD", text.casefold()) if not combining(c))


def fiche_url(kind: str, key: str, tab: str = "") -> str:
    base = f"{PREFIX}/fiche/{quote(kind, safe='')}/{quote(key, safe='')}"
    return base + (f"?{urlencode({'onglet': tab})}" if tab else "")


def forget_form(ui: Any, request: Request, kind: str, key: str, shown: str = "") -> dict[str, Any]:
    """Le formulaire d'oubli : on retape **le nom affiché** (« Adrien »), pas une clé technique."""
    shown = shown or key
    return {"url": f"{PREFIX}/oublier/{quote(kind, safe='')}/{quote(key, safe='')}", "csrf": ui.csrf(request),
            "nonce": "", "back": fiche_url(kind, key), "title": "Oublier", "fields": [], "retype": True,
            "subject": key, "retype_as": shown, "danger": True, "button": "Oublier pour de bon", "errors": {},
            "id": f"oubli-{kind}",
            "description": "Efface tout ce qui concerne cette personne (messages, souvenirs, traces) ; le journal "
                           "garde des enveloppes vides. Les sauvegardes plus anciennes la contiennent encore.",
            "confirm": f"Oublier « {shown} » pour de bon ? C'est irréversible."}


def retyped(given: str, shown: str, key: str) -> bool:
    """Le nom retapé confirme-t-il l'oubli ? Le nom affiché (casse et espaces près) ou la clé exacte."""
    folded = " ".join(given.split()).casefold()
    return bool(folded) and (folded == " ".join(shown.split()).casefold() or given.strip() == key)


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
            query = urlencode(dict(request.query_params))
            return RedirectResponse(fiche_url(kind, head.key) + ("?" + query if query else ""),
                                    status_code=303)
        tabs = self.ui.inspection.tabs(kind)
        asked = request.query_params.get("onglet", "")
        # une vue d'ensemble dessinée à la main (ADR 0121) : le premier onglet, ouvert par défaut
        overview = self.ui.deps.overviews.get(kind) if isinstance(head, Head) else None
        shown = call(overview.render, self.ui, key, label=f"vue d'ensemble {kind}") \
            if overview is not None and asked in ("", overview.slug) else None
        if isinstance(shown, Failed):  # elle a échoué : la fiche retombe sur ses onglets (l'échec est au journal)
            shown = None
        drawn = call(overview.head, self.ui, key, label=f"en-tête {kind}") if overview is not None else None
        if isinstance(drawn, Failed):  # l'en-tête de la faculté, alors
            drawn = None
        slug = asked or (head.default_tab if isinstance(head, Head) else "") or (tabs[0].name if tabs else "")
        current = None if shown is not None else next((t for t in tabs if t.name == slug), tabs[0] if tabs else None)
        blocks: list[Any] = [head] if isinstance(head, Note) else []
        if current is not None:
            blocks += await self.ui.inspection.arun(current, request.query_params, self.ui.when_long, subject=key)
        # un onglet que la vue d'ensemble dessine : les mêmes données, une autre forme (ses blocs sinon)
        if overview is not None and current is not None and current.name in overview.tabs \
                and not wants_table(request.query_params):
            query = dict(request.query_params)
            # ses formulaires préparés au nom de l'objet de la fiche, comme ceux d'une destination (ADR 0121)
            forms = Forms(self.pages.slot_forms(request, render.blocks(blocks, self.ui.env(), query), key),
                          lambda rendered, subject: self.pages.slot_forms(request, rendered, subject))
            drawn_tab = call(overview.render_tab, self.ui, key, current.name, blocks, query, forms,
                             label=f"onglet dessiné {kind}/{current.name}")
            if isinstance(drawn_tab, tuple):  # ce qu'elle a dessiné, et ce qu'elle laisse à la console
                shown, blocks = drawn_tab[0], list(drawn_tab[1])
            elif drawn_tab is not None and not isinstance(drawn_tab, Failed):
                shown, blocks = drawn_tab, []
        context = {k: v for k, v in request.query_params.items() if k not in ("onglet", "flash", "page", "taille")
                   and not is_page_param(k) and not k.startswith(("avant", "pg", "pile"))}
        tab_list, gear = self.tab_bar(request, kind, key, tabs, current, head, context)
        tabs_more: list[dict[str, Any]] = []
        if overview is not None:
            tab_list.insert(0, {"title": overview.title, "href": fiche_url(kind, key),
                                "on": shown is not None and current is None, "badge": 0})
            # ce qu'elle résume : au bout de la barre, sous un seul menu
            folded = [{"name": t.name, "title": t.title} for t in tabs if t.name in overview.folded]
            tabs_more = [{"title": f["title"], "href": fiche_url(kind, key, f["name"]),
                          "on": current is not None and current.name == f["name"]} for f in folded]
            hidden = {fiche_url(kind, key, f["name"]) for f in folded}
            tab_list = [t for t in tab_list if t["href"].split("&", 1)[0] not in hidden]
        actions = self.pages.head_actions(request, kind=kind, subject=key) \
            if not isinstance(head, Head) or (head.automatic_actions and
                (not head.action_tabs or current is not None and current.name in head.action_tabs)) else []
        title = head.title if isinstance(head, Head) else key
        if spec.forgettable:
            actions.append(forget_form(self.ui, request, kind, key, title))
        home = next((d for d in self.pages.dests.values() if kind in d.subjects), None)
        crumbs = ([(home.label, f"{PREFIX}/{home.key}")] if home else []) + \
            ([] if home and home.label == spec.plural else [(spec.plural, f"{PREFIX}/recherche?sorte={quote(kind)}")])
        if isinstance(head, Head) and head.back:
            crumbs = [(head.back.text or "Retour", render.href(head.back))]
        back = request.query_params.get("retour", "")
        if back.startswith(PREFIX + "/") and "//" not in back and "\\" not in back and len(back) < 2000:
            crumbs = [("Retour à la liste", back)]
        env = self.ui.env()
        facts = [{"label": k, "cell": render.cell(v, env)} for k, v in (head.facts if isinstance(head, Head) else ())]
        if kind == "person" and isinstance(head, Head):
            # ce qu'elle ferait maintenant envers cette personne, et ce qui la retient (lecture seule)
            facts.append({"label": "maintenant", "cell": render.cell(Ref(
                "local", f"{PREFIX}/decisions/envers", "que ferait-elle envers cette personne ?", (("personne", key),)), env)})
        badges = [{"text": b.text, "tone": b.tone} for b in (head.badges if isinstance(head, Head) else ())]
        return self.pages.render_page(
            request, title=f"{title} · {spec.label}", heading=title, active=home.key if home else "",
            subtitle=head.subtitle if isinstance(head, Head) else "", head_badges=badges, facts=facts,
            crumbs=crumbs, tabs=tab_list, gear=gear, blocks=blocks,
            # le menu allume la page d'où l'on vient (un brouillon : « À valider »), pas seulement la rubrique
            menu_path=crumbs[0][1] if crumbs else "",
            view_description=overview.description if shown is not None and current is None else
            "" if shown is not None else current.description if current is not None else "",
            overview=shown, fiche_head=drawn,
            fiche_styles=overview.styles if overview is not None and (shown or drawn) else (),
            fiche_scripts=overview.scripts if overview is not None and shown is not None and current is None else (),
            tabs_more=tabs_more, tabs_more_title=overview.folded_title if overview is not None else "",
            filters=current.typed if current is not None else (), head_actions=actions, subject=key,
            console_blocks=current is not None and current.owner in self.ui.deps.plain_owners,
            keep=(("onglet", current.name),) if current is not None else ())

    @staticmethod
    def tab_bar(request: Request, kind: str, key: str, tabs: Any, current: Any, head: Any,
                context: dict[str, str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Les onglets d'une fiche et ceux de sa roue. Un objet qui a ses propres pages (``Head.pages``) les montre
        en onglets à la place de ``Head.pages_tab`` ; ce que ``Head.gear`` nomme passe derrière la roue, en haut à
        droite (ADR 0104)."""
        pages = head.pages if isinstance(head, Head) else ()
        pages_tab = head.pages_tab if isinstance(head, Head) else ""
        geared = head.gear if isinstance(head, Head) else ()
        extra = "&" + urlencode(context) if context else ""
        bar: list[dict[str, Any]] = []
        for t in tabs:
            if t.name in geared:
                continue
            if pages and t.name == pages_tab:
                here = current is not None and current.name == t.name
                chosen = [i for i, ref in enumerate(pages)
                          if all(request.query_params.get(k, "") == v for k, v in ref.params if k != "onglet")]
                on = chosen[0] if chosen else 0
                bar += [{"title": ref.text, "href": render.href(ref), "on": here and i == on, "badge": 0}
                        for i, ref in enumerate(pages)]
                continue
            bar.append({"title": t.title, "href": fiche_url(kind, key, t.name) + extra,
                        "on": current is not None and t.name == current.name, "badge": 0})
        by_name = {t.name: t for t in tabs}
        gear = [{"title": by_name[n].title, "href": fiche_url(kind, key, n),
                 "on": current is not None and current.name == n} for n in geared if n in by_name]
        return bar, gear

    async def search(self, request: Request) -> Response:
        q = request.query_params.get("q", "").strip()[:200]
        only = request.query_params.get("sorte", "")
        blocks: list[Any] = []
        kinds = [k for k in self.ui.kernel.registry.subjects if not only or k == only]
        for kind in sorted(kinds):
            spec = self.ui.inspection.subject(kind)
            if spec is None or spec.search is None:
                continue
            param = "avant_" + kind
            ctx = self.ui.inspection.context(request.query_params)
            offset = max(0, ctx.int_param(param, 0))
            found = self.ui.inspection.search(kind, q, SEARCH_PAGE + 1, offset=offset)
            if found or only or offset:
                pager = Pager(param=param, older=((param, str(offset + SEARCH_PAGE)),) if len(found) > SEARCH_PAGE else ())
                blocks.append(Table((spec.label.lower(), "détail"), tuple(
                    Row((Ref.subject(kind, f.key, f.title), f.subtitle or "—"), href=Ref.subject(kind, f.key, ""))
                    for f in found[:SEARCH_PAGE]), title=spec.plural, pager=pager,
                    empty="Aucun résultat."))
        if q.isdigit():
            blocks.insert(0, Table(("événement",), ((Ref("event", q, f"l'événement n° {q}"),),), title="Journal"))
        # les vues qui cherchent dans leurs textes (un filtre « q » : les messages) — la recherche ne lit pas les
        # messages elle-même, elle y mène
        texts = [v for v in self.ui.inspection.views() if q and not v.subject and any(p == "q" for p, _l in v.params)]
        if texts:
            blocks.insert(0, Table(("chercher dans", "faculté"), tuple(
                (Ref.view(v.owner, v.name, f"« {q} » dans {v.title.lower()}", q=q),
                 Text(self.ui.names.faculty(v.owner), hint=v.owner)) for v in texts), title="Dans les textes"))
        views = [v for v in self.ui.inspection.views() if q and q.lower() in v.title.lower()]
        if views:
            blocks.append(Table(("vue", "faculté"), tuple((Ref.view(v.owner, v.name, v.title),
                                                          Text(self.ui.names.faculty(v.owner), hint=v.owner))
                                                         for v in views), title="Vues"))
        if q and not only:
            # Les réglages et les pages natives doivent se trouver aussi : ils ne sont pas des sujets.
            matches = []
            needle = search_text(q)
            for group in self.ui.deps.menu:
                for link in group.items:
                    if needle in search_text(f"{group.label} {link.label}"):
                        matches.append((Ref("local", f"{PREFIX}/{link.target}", link.label), group.label or "Accueil"))
            for group in self.ui.deps.navigation:
                for dest in group.items:
                    base = f"{PREFIX}/{dest.key}" if dest.key != "accueil" else f"{PREFIX}/"
                    if needle in search_text(dest.label):
                        matches.append((Ref("local", base, dest.label), group.label or "Accueil"))
                    if dest.layout == "stack":
                        continue
                    for slug, title, spec in self.pages.tabs_of(dest):
                        family = spec.group if isinstance(spec, Builtin) else ""
                        if needle in search_text(f"{dest.label} {family} {title}"):
                            url = spec.href if isinstance(spec, Builtin) and spec.href else f"{base}/{slug}"
                            matches.append((Ref("local", url, title), " › ".join(filter(None, (dest.label, family)))))
            if matches:
                unique = {}
                for row in matches:
                    unique.setdefault(row[0].key, row)
                blocks.insert(0, Table(("page", "rubrique"), tuple(unique.values()), title="Pages de la console"))
        if not blocks:
            blocks = [Note("Rien ne correspond." if q else "Tape un nom, un numéro d'événement, un titre.", "muted")]
        return self.pages.render_page(request, title="Recherche", heading=f"Recherche : « {q} »" if q else "Recherche",
                                      active="", blocks=blocks, search_q=q,
                                      subtitle="Retrouve une page, un réglage, une personne, un projet ou un message.")

    async def forget(self, request: Request) -> Response:
        kind, key = request.path_params["kind"], request.path_params["key"]
        spec = self.ui.inspection.subject(kind)
        data = await self.ui.form(request)
        account = self.ui.operator(request)
        if spec is None or not spec.forgettable or data is None or account is None:
            return self.pages.render_page(request, title="Oubli refusé", active="", status=403,
                                          blocks=[Note("Jeton invalide, ou cet objet ne s'oublie pas.", "danger")])
        head = self.ui.inspection.head(kind, key)
        shown = head.title if isinstance(head, Head) else key
        if not retyped(str(data.get("_confirmer", "")), shown, key):
            return self.pages.render_page(request, title="Oubli refusé", active="", status=400,
                                          blocks=[Note(f"Retape « {shown} » pour confirmer.", "danger")],
                                          crumbs=[("Retour", fiche_url(kind, key))])
        # le même oubli que la ligne de commande : la clé et ses alias (ses adresses, ses noms)
        gone = await operations.forget_subject(self.ui.kernel, kind, key, by=account.handle,
                                               action=f"console.oublier.{kind}")
        self.ui.flash(f"oubli-{key}", "ok", f"« {shown} » est oublié·e ({gone.total} contenu(s) effacé(s)).")
        return secure(RedirectResponse(f"{PREFIX}/?flash={quote('oubli-' + key, safe='')}", status_code=303))

    async def download(self, request: Request) -> Response:
        kind, key = request.path_params["kind"], request.path_params["key"]
        result = await self.ui.inspection.download(kind, key, request.query_params.get("fichier", "source")[:300])
        if not isinstance(result, Download):
            return self.pages.render_page(request, title="Téléchargement indisponible", active="",
                status=404, blocks=[result if isinstance(result, Note) else Note("Ce document n'est plus disponible.", "warn")],
                crumbs=[("Retour à la fiche", fiche_url(kind, key))])
        name = result.name.replace("\\", "/").rsplit("/", 1)[-1]
        name = "".join(c for c in name if c.isprintable())[:200] or "document"
        return secure(Response(result.data, media_type="application/octet-stream", headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(name, safe=""),
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}))

    def routes(self) -> list[Any]:
        g = self.ui.guarded
        return [Route(PREFIX + "/fiche/{kind:str}/{key:str}", g(self.fiche)),
                Route(PREFIX + "/telecharger/{kind:str}/{key:str}", g(self.download)),
                Route(PREFIX + "/recherche", g(self.search)),
                Route(PREFIX + "/oublier/{kind:str}/{key:str}", g(self.forget), methods=["POST"])]
