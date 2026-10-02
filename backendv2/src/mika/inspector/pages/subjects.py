"""Les fiches d'objets : une personne, une adresse, un but, une app… L'en-tête
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
from mika.kernel.inspect import Download, Head, Note, Pager, Ref, Row, Table, Text, is_page_param
from mika.runtime import operations

#: Une page par type d'objet, sans plafond sur l'ensemble des résultats.
SEARCH_PAGE = 25


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
        slug = request.query_params.get("onglet", "") or (head.default_tab if isinstance(head, Head) else "") \
            or (tabs[0].name if tabs else "")
        current = next((t for t in tabs if t.name == slug), tabs[0] if tabs else None)
        blocks: list[Any] = [head] if isinstance(head, Note) else []
        if current is not None:
            blocks += await self.ui.inspection.arun(current, request.query_params, self.ui.when_long, subject=key)
        context = {k: v for k, v in request.query_params.items() if k not in ("onglet", "flash", "page", "taille")
                   and not is_page_param(k) and not k.startswith(("avant", "pg", "pile"))}
        tab_list = [{"title": t.title, "href": fiche_url(kind, key, t.name) + ("&" + urlencode(context) if context else ""), "on": current is not None
                     and t.name == current.name, "badge": 0} for t in tabs]
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
                "local", f"{PREFIX}/decisions/envers", "que ferait-elle envers elle ?", (("personne", key),)), env)})
        badges = [{"text": b.text, "tone": b.tone} for b in (head.badges if isinstance(head, Head) else ())]
        return self.pages.render_page(
            request, title=f"{title} · {spec.label}", heading=title, active=home.key if home else "",
            subtitle=head.subtitle if isinstance(head, Head) else "", head_badges=badges, facts=facts,
            crumbs=crumbs, tabs=tab_list, blocks=blocks,
            view_description=current.description if current is not None else "",
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
        views = [v for v in self.ui.inspection.views() if q and q.lower() in v.title.lower()]
        if views:
            blocks.append(Table(("vue", "faculté"), tuple((Ref.view(v.owner, v.name, v.title),
                                                          Text(self.ui.names.faculty(v.owner), hint=v.owner))
                                                         for v in views), title="Vues"))
        if not blocks:
            blocks = [Note("Rien ne correspond." if q else "Tape un nom, un numéro d'événement, un titre.", "muted")]
        return self.pages.render_page(request, title="Recherche", heading=f"Recherche : « {q} »" if q else "Recherche",
                                      active="", blocks=blocks, search_q=q,
                                      subtitle="Trouve une personne, un projet, un message ou une app, puis ouvre sa fiche.")

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
        keys = [key, *(head.aliases if isinstance(head, Head) else ())]
        removed = 0
        for k in dict.fromkeys(keys):
            got = await self.ui.kernel.forget(k)
            removed += sum(v for v in got.values() if isinstance(v, int)) if isinstance(got, dict) else int(got or 0)
        await operations.audit(self.ui.kernel, f"console.oublier.{kind}", by=account.handle, subject_kind=kind,
                               subject=key)
        self.ui.flash(f"oubli-{key}", "ok", f"« {shown} » est oublié·e ({removed} contenu(s) effacé(s)).")
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
