"""Les fiches d'objets : une personne, une adresse, un but, une app… L'en-tête
vient de la faculté qui déclare le type d'objet ; chaque onglet, de la
faculté qui l'y ajoute — la console n'en connaît aucune. Et la recherche, et
l'oubli d'un objet qui est un sujet de contenus."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote, unquote, urlencode, urlsplit

from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

from mika.inspector import render
from mika.inspector.catalog import Builtin, Panel
from mika.inspector.framed import FRAME_CSP, FRAME_CSP_REMOTE, framed_html
from mika.inspector.pages import settings_directory
from mika.inspector.ui import PREFIX, Forms, secure, wants_table
from mika.kernel.inspect import Download, Head, Note, Pager, Ref, Row, Section, Table, Text, is_page_param
from mika.kernel.text import fold
from mika.runtime import operations
from mika.runtime.boundary import Failed, call

#: Une page par type d'objet, sans plafond sur l'ensemble des résultats.
SEARCH_PAGE = 25


def fiche_url(kind: str, key: str, tab: str = "") -> str:
    """L'adresse de la fiche d'un objet : la seule aide de la console pour l'écrire (``tab`` : l'onglet ouvert)."""
    return render.href(Ref.subject(kind, key, "", tab))


def fiche_key(href: str, kind: str) -> str:
    """La clé de l'objet dont ce lien ouvre la fiche, si c'est une fiche de cette sorte ; sinon « ». L'inverse de
    ``fiche_url`` : ce qu'une page dessinée relit au lien rendu par la faculté."""
    base, path = fiche_url(kind, ""), urlsplit(href).path
    return unquote(path[len(base):]) if path.startswith(base) else ""


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


#: la recherche dessinée, et sa feuille
SEARCH_TEMPLATE = "handmade/recherche/recherche.html"
SEARCH_STYLES = ("handmade/episode.css",)
#: les vues brutes des facultés : la recherche y mène, sans les lister (ADR 0202)
VIEWS = f"{PREFIX}/systeme/vues"
TECHNICAL = "Chercher dans les vues techniques"


def search_view(blocks: list[Any], query: dict[str, str], q: str, only: str, technical: int = 0,
                shown: render.Env | None = None) -> dict[str, Any]:
    """Ce que dessine la recherche : chaque groupe de résultats (ses tableaux de liens) en carte, ses liens et leur
    détail, sa pagination ; ou ce que dit sa note (rien trouvé, rien demandé). ``technical`` : combien de vues brutes
    des facultés portent ce mot dans leur titre — un lien vers Système › Toutes les vues, pas une sorte de résultat."""
    def plain(cell: Any) -> str:
        if isinstance(cell, Text):
            return cell.text
        if isinstance(cell, Ref):
            return cell.text
        return "" if cell in (None, "—") else str(cell)

    groups, note = [], ""
    for b in blocks:
        if isinstance(b, Note):
            note = b.text
            continue
        if not isinstance(b, Table):
            continue
        items = []
        for raw in b.rows:
            cells = raw.cells if isinstance(raw, Row) else tuple(raw)
            link = cells[0] if cells and isinstance(cells[0], Ref) else None
            items.append({"label": plain(cells[0]) if cells else "", "href": render.href(link, shown) if link else "",
                          "sub": plain(cells[1]) if len(cells) > 1 else ""})
        # sa section (un sous-onglet, ADR 0176) : sa pagination y ramène
        key = f"r-{len(groups) + 1}"
        pager = render.pager_ctx(b.pager, query)
        paged = bool(pager and any(pager.get(k) for k in ("prev", "next", "older", "newer")))
        if pager:
            pager = {**pager, **{k: v + "#" + key for k, v in pager.items() if k in PAGER_LINKS and v},
                     "links": [{**x, "href": x["href"] + "#" + key} if x.get("href") else x
                               for x in pager.get("links") or []]}
        groups.append({"title": b.title, "items": items, "empty": b.empty, "pager": pager, "paged": paged, "id": key,
                       "shown": pager["total"] if paged and pager.get("total") else len(items)})
    return {"q": q, "only": only, "groups": groups, "note": note,
            "technical": {"count": technical, "href": VIEWS, "text": TECHNICAL} if technical else None}


#: les liens d'une pagination (``render.pager_ctx``) qui changent de page
PAGER_LINKS = frozenset({"prev", "next", "older", "newer", "first"})


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
        tabs = self.ui.inspection.tabs(kind, key)
        asked = request.query_params.get("onglet", "")
        # une vue d'ensemble dessinée à la main (ADR 0121) : le premier onglet, ouvert par défaut
        overview = self.ui.deps.overviews.get(kind) if isinstance(head, Head) else None
        # sans ``slug``, elle ne dessine que des onglets (``tabs``) : pas de vue d'ensemble à elle
        shown = call(overview.render, self.ui, key, label=f"vue d'ensemble {kind}") \
            if overview is not None and overview.slug and asked in ("", overview.slug) else None
        if isinstance(shown, Failed):  # elle a échoué : la fiche retombe sur ses onglets (l'échec est au journal)
            shown = None
        drawn = call(overview.head, self.ui, key, label=f"en-tête {kind}") if overview is not None else None
        if isinstance(drawn, Failed):  # l'en-tête de la faculté, alors
            drawn = None
        # des onglets réunis sous un autre (``Overview.joined``) : hors de la barre, leur adresse mène au sien
        by_name = {t.name: t for t in tabs}
        joined = {host: [by_name[g] for g in guests if g in by_name and g != host]
                  for host, guests in (overview.joined.items() if overview is not None else ()) if host in by_name}
        host_of = {g.name: host for host, guests in joined.items() for g in guests}
        if asked in host_of:
            query = urlencode({**dict(request.query_params), "onglet": host_of[asked]})
            return RedirectResponse(f"{fiche_url(kind, key)}?{query}#{quote(asked, safe='')}", status_code=303)
        tabs = [t for t in tabs if t.name not in host_of]
        slug = asked or (head.default_tab if isinstance(head, Head) else "") or (tabs[0].name if tabs else "")
        current = None if shown is not None else next((t for t in tabs if t.name == slug), tabs[0] if tabs else None)
        blocks: list[Any] = [head] if isinstance(head, Note) else []
        guests = joined.get(current.name, []) if current is not None else []
        if current is not None:
            got = await self.ui.inspection.arun(current, request.query_params, self.ui.when_long, subject=key)
            if guests:  # ses onglets réunis : une section par onglet, à son titre, la sienne d'abord
                got = [Section(current.title, tuple(got), current.description)]
                for g in guests:
                    got.append(Section(g.title, tuple(await self.ui.inspection.arun(
                        g, request.query_params, self.ui.when_long, subject=key)), g.description))
            blocks += got
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
        counts = call(overview.counts, self.ui, key, label=f"comptes {kind}") if overview is not None else {}
        if counts and not isinstance(counts, Failed):  # combien chaque onglet en compte, en petit (la maquette)
            by_href = {fiche_url(kind, key, name): n for name, n in counts.items()}
            for t in tab_list:
                t["count"] = by_href.get(t["href"].split("&", 1)[0], 0)
        tabs_more: list[dict[str, Any]] = []
        if overview is not None and overview.slug:
            tab_list.insert(0, {"title": overview.title, "href": fiche_url(kind, key),
                                "on": shown is not None and current is None, "badge": 0})
        if overview is not None:
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
        links = call(overview.links, self.ui, key, label=f"liens {kind}") if overview is not None else ()
        if not isinstance(links, Failed):
            actions += [{"page": href, "title": text} for text, href in links or ()]
        home = next((d for d in self.pages.dests.values() if kind in d.subjects), None)
        back = request.query_params.get("retour", "")
        from_list = back.startswith(PREFIX + "/") and "//" not in back and "\\" not in back and len(back) < 2000
        crumbs, returning, menu_path = self.trail(key, head, home, back if from_list else "")
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
            crumbs=crumbs, crumbs_back=returning, tabs=tab_list, gear=gear, blocks=blocks,
            # le menu allume la page d'où l'on vient (un brouillon : « À valider »), pas seulement la rubrique
            menu_path=menu_path,
            # l'onglet du menu ne s'allume que pour la liste d'où l'on vient, pas pour la destination de la fiche
            menu_tab=from_list,
            view_description=overview.description if shown is not None and current is None else
            "" if shown is not None else " ".join(filter(None, (current.description, *(g.description for g in guests))))
            if current is not None else "",
            overview=shown, fiche_head=drawn,
            fiche_styles=overview.styles if overview is not None and (shown or drawn) else (),
            fiche_scripts=overview.scripts if overview is not None and shown is not None and current is None else (),
            tabs_more=tabs_more, tabs_more_title=overview.folded_title if overview is not None else "",
            filters=current.typed if current is not None else (), head_actions=actions, subject=key,
            console_blocks=current is not None and current.owner in self.ui.deps.plain_owners,
            keep=(("onglet", current.name),) if current is not None else ())

    def home_trail(self, kind: str) -> list[tuple[str, str]]:
        """Le fil d'une page qui accompagne une fiche (un oubli refusé, un document parti) : la destination où vit ce
        type d'objet, depuis sa rubrique ; la fiche se rejoint par le retour, dit à part."""
        home = next((d for d in self.pages.dests.values() if kind in d.subjects), None)
        return self.pages.trail(home.key) if home is not None else []

    def trail(self, key: str, head: Any, home: Any,
              listed: str) -> tuple[list[tuple[str, str]], tuple[str, str] | None, str]:
        """Le fil d'Ariane d'une fiche (ADR 0177, 0202) : sa rubrique, sa destination, l'objet par son numéro
        (« Activité / Projets / n° 257 »), ou par son nom quand il n'en a pas d'autre que sa clé (son titre est sa
        clé : « Outils / Ses outils / web », comme un outil), par le constructeur de toute la console
        (``Pages.trail``) ; un objet que son titre nomme autrement (une personne, un mail) s'arrête à sa destination,
        sa clé interne ne se dit pas. Un retour ne le remplace pas : celui que déclare la faculté (``Head.back``)
        devient le lien de la destination quand il y mène (la liste filtrée d'où vient un mail), et se dit à part sinon
        (« ← Ses pièces », sur la fiche d'une personne) ; la liste d'où l'on vient (``listed``, ``?retour=``) se dit à
        part, « ← Retour à la liste ». Rend aussi la page que le menu allume : cette liste, sinon le retour déclaré qui
        mène à la destination, sinon la destination."""
        own = [(f"n° {key}", "")] if key.isdigit() else \
            [(key, "")] if isinstance(head, Head) and head.title == key else []
        declared = head.back if isinstance(head, Head) else None
        target = render.href(declared, self.ui.env()) if declared is not None else ""
        base = f"{PREFIX}/{home.key}" if home is not None else ""
        path = target.split("#", 1)[0].split("?", 1)[0]
        within = bool(base) and (path == base or path.startswith(base + "/"))
        crumbs = self.pages.trail(home.key, *own, link=target if within else "") if home is not None else own
        returning = ("Retour à la liste", listed) if listed else \
            (declared.text or "Retour", target) if declared is not None and not within else None
        return crumbs, returning, listed or (target if within else base)

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
            # leurs dates écrites comme partout dans la console (le sous-titre d'un mail), jamais l'horodatage brut
            found = self.ui.inspection.search(kind, q, SEARCH_PAGE + 1, offset=offset, when=self.ui.when)
            if found or only or offset:
                pager = Pager(param=param, older=((param, str(offset + SEARCH_PAGE)),) if len(found) > SEARCH_PAGE else ())
                blocks.append(Table((spec.label.lower(), "détail"), tuple(
                    Row((Ref.subject(kind, f.key, f.title), f.subtitle or "—"), href=Ref.subject(kind, f.key, ""))
                    for f in found[:SEARCH_PAGE]), title=spec.plural, pager=pager,
                    empty="Aucun résultat."))
        lead: list[Any] = []  # en tête, dans cet ordre : les pages, les réglages, les textes, le journal
        if q and not only:
            pages = self.pages_found(q)
            if pages:
                lead.append(Table(("page", "rubrique"), pages, title="Pages de la console"))
            settings = self.settings_found(q)
            if settings:
                lead.append(Table(("réglage", "où"), settings, title="Réglages"))
        # les vues qui cherchent dans leurs textes (un filtre « q » : les messages) — la recherche ne lit pas les
        # messages elle-même, elle y mène
        texts = [v for v in self.ui.inspection.views()
                 if q and not v.subject and not v.hidden and any(p == "q" for p, _l in v.params)]
        if texts:
            lead.append(Table(("chercher dans", "faculté"), tuple(
                (Ref.view(v.owner, v.name, f"« {q} » dans {v.title.lower()}", q=q),
                 Text(self.ui.names.faculty(v.owner), hint=v.owner)) for v in texts), title="Dans les textes"))
        if q.isdigit():
            lead.append(Table(("événement",), ((Ref("event", q, f"l'événement n° {q}"),),), title="Journal"))
        blocks = lead + blocks
        # les vues brutes des facultés ne sont plus une sorte de résultat : elles doublaient les pages sous des titres
        # techniques (ADR 0202) ; un lien mène à Système › Toutes les vues quand l'une porte ce mot dans son titre
        technical = sum(1 for v in self.ui.inspection.views() if q and fold(q) in fold(v.title))
        if not blocks:
            blocks = [Note("Rien ne correspond." if q else "Tape un nom, un numéro d'événement, un titre.", "muted")]
        heading = f"Recherche : « {q} »" if q else "Recherche"
        subtitle = "Retrouve une page, un réglage, une personne, un projet ou un message."
        # dessinée (ADR 0121) : chaque sorte de résultat en carte ; ses blocs au repli
        drawn = None if wants_table(request.query_params) else call(
            search_view, blocks, dict(request.query_params), q, only, technical, self.ui.env(), label="recherche dessinée")
        if isinstance(drawn, dict):
            return self.pages.render_page(request, title="Recherche", heading=heading, active="", blocks=[],
                                          search_q=q, subtitle=subtitle,
                                          panel=Panel(SEARCH_TEMPLATE, {"v": drawn}, styles=SEARCH_STYLES))
        if technical:
            blocks.append(Table(("vues techniques",), ((Ref("local", VIEWS, TECHNICAL),),), title="Vues techniques"))
        return self.pages.render_page(request, title="Recherche", heading=heading, active="", blocks=blocks,
                                      search_q=q, subtitle=subtitle)

    def pages_found(self, q: str) -> tuple[tuple[Ref, str], ...]:
        """Les pages de la console qui répondent à ``q`` (ses liens de menu, ses destinations, leurs onglets) : elles
        ne sont pas des sujets. Chacune avec le chemin de son fil d'Ariane (ADR 0202) ; une destination, avec sa
        seule rubrique ; un lien du menu, avec sa rubrique et sa colonne."""
        matches: list[tuple[Ref, str]] = []
        needle = fold(q)
        her = self.ui.her_name()
        for group in self.ui.deps.menu:
            label = her if group.her else group.label
            for link in group.items:
                if needle in fold(f"{label} {link.column} {link.label}"):
                    matches.append((Ref("local", f"{PREFIX}/{link.target}", link.label),
                                    " › ".join(filter(None, (label, link.column))) or "Accueil"))
        for group in self.ui.deps.navigation:
            for dest in group.items:
                base = f"{PREFIX}/{dest.key}"
                if needle in fold(dest.label):
                    above = [text for text, _href in self.pages.trail(dest.key)][:-1]
                    matches.append((Ref("local", base, dest.label), " › ".join(above) or dest.label))
                for slug, title, spec in self.ui.tabs_of(dest):
                    family = spec.group if isinstance(spec, Builtin) else ""
                    if needle in fold(f"{dest.label} {family} {title}"):
                        path = self.pages.trail(f"{dest.key}/{slug}", title=title, group=family)
                        matches.append((Ref("local", f"{base}/{slug}", title), " › ".join(t for t, _h in path)))
        unique: dict[str, tuple[Ref, str]] = {}
        for row in matches:
            unique.setdefault(row[0].key, row)
        return tuple(unique.values())

    def settings_found(self, q: str) -> tuple[Row, ...]:
        """Les réglages qui répondent à ``q`` (C1-09) : les entrées de l'annuaire (Réglages › Tous les réglages),
        trouvées comme il les trouve — même pliage, le nom et l'aide de chaque champ —, chacune vers sa page, avec le
        champ où le mot a été trouvé."""
        rows = []
        for entry, hits in settings_directory.find(self.ui, q):
            where = "Trouvé dans : " + ", ".join(hits) if hits else entry.group
            rows.append(Row((Ref("local", entry.href, entry.title), where), href=Ref("local", entry.href, "")))
        return tuple(rows)

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
                                          crumbs=self.home_trail(kind), crumbs_back=("Retour à la fiche",
                                                                                     fiche_url(kind, key)))
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
                crumbs=self.home_trail(kind), crumbs_back=("Retour à la fiche", fiche_url(kind, key)))
        name = result.name.replace("\\", "/").rsplit("/", 1)[-1]
        name = "".join(c for c in name if c.isprintable())[:200] or "document"
        return secure(Response(result.data, media_type="application/octet-stream", headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(name, safe=""),
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}))

    async def document(self, request: Request) -> Response:
        """Le cadre d'un document HTML natif (ADR 0169) : sa propre politique, sans script ni rien du dehors."""
        kept = self.ui.documents.get(request.path_params["digest"])
        page = framed_html(kept.html, kept.images, remote=kept.remote) if kept is not None else \
            framed_html("<p>Ce message n'est plus prêt : recharge la page pour le relire.</p>")
        # des images distantes permises (ADR 0175) : chargées sans référent, rien d'autre du dehors
        policy = FRAME_CSP_REMOTE if kept is not None and kept.remote else FRAME_CSP
        return secure(HTMLResponse(page, status_code=200 if kept is not None else 404, headers={
            "Content-Security-Policy": policy, "Referrer-Policy": "no-referrer"}))

    def routes(self) -> list[Any]:
        g = self.ui.guarded
        return [Route(PREFIX + "/fiche/{kind:str}/{key:str}", g(self.fiche)),
                Route(PREFIX + "/telecharger/{kind:str}/{key:str}", g(self.download)),
                Route(PREFIX + "/document/{digest:str}", g(self.document)),
                Route(PREFIX + "/recherche", g(self.search)),
                Route(PREFIX + "/oublier/{kind:str}/{key:str}", g(self.forget), methods=["POST"])]
