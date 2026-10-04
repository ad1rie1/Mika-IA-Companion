"""Atelier de la Forge, inspection des apps et adaptation du contrat v2."""
from __future__ import annotations

import logging

from old.backend.GestionSysteme import panels as P
from old.backend.GestionSysteme import tables
from old.backend.GestionSysteme.formatting import display_text

MAX_SOURCE_DISPLAY = 200_000

logger = logging.getLogger("module.forge")

_TONS_STATUT = {
    "actif": "ok",
    "désactivé": "",
    "cassé": "danger",
    "non chargé": "warn",
}


# ── Modules ─────────────────────────────────────────────────────────────

def modules_panel(host):
    def handler(request):
        infos = sorted(host.module_infos(), key=lambda i: i["name"])
        fs = tables.FilterSet(per_page=tables.read_per_page(request))
        search = fs.add(tables.search_filter(request, "q", "Recherche", placeholder="nom, titre"))
        if search.value:
            infos = [i for i in infos if search.value.casefold() in (i["name"] + " " + str(i.get("title") or "")).casefold()]
        page = tables.paginate(request, infos, per_page=fs.per_page)

        blocs = [P.Note(
            "Chaque app a son propre espace (menu « Forge apps ») : sa "
            "configuration, ses pages et ses commandes y tiennent ensemble. "
            "Cette table est l'atelier — l'état de tout ce qui est forgé.",
            tone="info",
        )]

        blocs.append(P.Table(
            caption="Modules forgés",
            columns=[
                P.Column("Nom"),
                P.Column("Titre"),
                P.Column("Statut", align="fit"),
                P.Column("Cadence", align="fit"),
                P.Column("Événements"),
                P.Column("Échecs", align="num"),
                P.Column("Dernière erreur"),
            ],
            rows=[_ligne_module(request, i) for i in page.rows], page=page, filters=fs,
            empty=(
                "Aucun module forgé. Mika en crée elle-même via ses outils "
                "forge_write_module / forge_test_module."
            ),
        ))
        return P.Blocks(items=blocs)

    return handler


def _ligne_module(request, info: dict) -> P.Row:
    from django.urls import reverse

    statut = info.get("status", "?")
    echecs = int(info.get("failures", 0) or 0)
    return P.Row(
        # La ligne mène à l'espace de l'app, pas à une fiche locale : une app
        # ne doit se lire qu'à un seul endroit.
        href=reverse("gestionsysteme:forge-app", args=[info["name"]]),
        cells=(
            P.mono(info["name"]),
            P.text(info.get("title") or "—"),
            P.badge(statut, tone=_TONS_STATUT.get(statut, "")),
            P.mono(info.get("schedule") or "—"),
            P.text(", ".join(info.get("events") or []) or "—"),
            # Le disjoncteur désactive à cinq échecs consécutifs : le compteur
            # mérite d'être lisible avant d'y arriver.
            P.badge(echecs, tone="danger" if echecs >= 3 else ""),
            P.text((info.get("last_error") or info.get("status_detail") or "—"), clamp=True),
        ),
    )


def blocs_app(host, nom: str, info: dict) -> list:
    """Fiche d'une app forgée : état, source, journal.

    Rendue dans l'espace de l'app (« Forge apps »), plus dans l'atelier :
    c'était la même fiche derrière ``?module=…``, mais à côté de la table de
    toutes les apps plutôt qu'à côté de la configuration et des pages de
    celle qu'on regarde.
    """
    champs = [
        P.Field("Nom", nom, kind="mono"),
        P.Field("Statut", info.get("status", "?"), kind="badge",
                tone=_TONS_STATUT.get(info.get("status", ""), "")),
    ]
    if info.get("status_detail"):
        champs.append(P.Field("Détail", info["status_detail"]))
    champs += [
        P.Field("Activée", "oui" if info.get("enabled") else "non"),
        P.Field("Cadence", info.get("schedule") or "—", kind="mono"),
        P.Field("Événements écoutés", ", ".join(info.get("events") or []) or "—"),
        P.Field("Handlers", ", ".join(info.get("handlers") or []) or "—"),
        P.Field("Prochain passage", str(info.get("next_run_at") or "—")),
        P.Field("Version", str(info.get("version") or "—")),
        P.Field("Échecs consécutifs", str(info.get("failures") or 0)),
    ]
    if info.get("context"):
        champs.append(P.Field("Injecté dans son prompt", info["context"]))
    if info.get("last_error"):
        champs.append(P.Field("Dernière erreur", info["last_error"]))

    blocs = [P.Fields(title="État", items=champs)]

    manifeste, code = _source(nom)
    sources = []
    if manifeste:
        sources.append(P.Code(title="manifest.yaml", text=manifeste))
    if code:
        sources.append(P.Code(title="module.py", text=code))
    if sources:
        blocs.append(P.Disclosure("Source et manifeste", sources))

    blocs.append(P.Table(
        caption="Journal · 30 dernières entrées",
        columns=[
            P.Column("Quand", align="fit"),
            P.Column("Niveau", align="fit"),
            P.Column("Source", align="fit"),
            P.Column("Message"),
        ],
        rows=[_ligne_journal(r, avec_module=False) for r in _journal(nom, 30)],
        empty="Aucune entrée pour cette app.",
    ))
    from django.urls import reverse
    from urllib.parse import urlencode
    blocs.append(P.Fields([P.Field("Historique complet", "Ouvrir le journal filtré", kind="link",
        href=reverse("gestionsysteme:module-panel", args=["forge", "journal"]) + "?" + urlencode({"module": nom}))]))
    return blocs


def _source(nom: str) -> tuple[str, str]:
    """Manifeste et code du module, lus sur disque.

    Une lecture impossible devient un texte explicite plutôt qu'une page en
    erreur : c'est précisément un module cassé qu'on vient inspecter.
    """
    import yaml

    from old.backend.modules.plugins.forge import store

    try:
        data = store.read_module(nom)
    except Exception as exc:
        return f"(illisible : {exc})", ""
    try:
        manifeste = yaml.safe_dump(
            data["manifest_raw"], allow_unicode=True, sort_keys=False,
        )
    except Exception as exc:
        manifeste = f"(non sérialisable : {exc})"
    code = data.get("code") or ""
    return display_text(manifeste, MAX_SOURCE_DISPLAY), display_text(code, MAX_SOURCE_DISPLAY)


# ── Journal ─────────────────────────────────────────────────────────────

def journal_panel(host):
    def handler(request):
        from old.backend.modules.plugins.forge.models import ForgeLog

        fs = tables.FilterSet(per_page=tables.read_per_page(request, default=50))
        module = fs.add(tables.search_filter(request, "module", "Module", placeholder="Rechercher une app", suggestions="forge-modules"))
        niveau = fs.add(tables.select_filter(
            request, "niveau", "Niveau",
            [(v, v) for v, _ in ForgeLog.Level.choices],
        ))
        recherche = fs.add(tables.search_filter(
            request, "q", "Recherche", placeholder="dans le message",
        ))

        qs = ForgeLog.objects.all()
        if module.value:
            qs = qs.filter(module_name__iexact=module.value)
        if niveau.value:
            qs = qs.filter(level=niveau.value)
        if recherche.value:
            qs = qs.filter(message__icontains=recherche.value)
        qs = qs.order_by("-created_at")

        page = tables.paginate(request, qs, per_page=fs.per_page)

        return P.Table(
            caption="Journal des modules forgés",
            filters=fs,
            columns=[
                P.Column("Quand", align="fit"),
                P.Column("Module", align="fit"),
                P.Column("Niveau", align="fit"),
                P.Column("Source", align="fit"),
                P.Column("Message"),
            ],
            rows=[_ligne_journal(r) for r in page.rows],
            page=page,
            empty="Aucune entrée pour ces filtres." if fs.active else "Aucun événement enregistré par les apps forgées.",
        )

    return handler


_TONS_NIVEAU = {"error": "danger", "warning": "warn", "info": "", "debug": ""}


def _ligne_journal(entree, *, avec_module: bool = True) -> P.Row:
    from old.backend.GestionSysteme.formatting import dt_full

    cellules = [P.mono(dt_full(entree.created_at))]
    if avec_module:
        cellules.append(P.mono(entree.module_name))
    cellules += [
        P.badge(entree.level, tone=_TONS_NIVEAU.get(entree.level, "")),
        P.badge(entree.source or "—"),
        P.text(entree.message, clamp=True),
    ]
    return P.Row(cells=tuple(cellules))


def _journal(nom: str, limite: int):
    from old.backend.modules.plugins.forge.models import ForgeLog

    return list(
        ForgeLog.objects.filter(module_name=nom).order_by("-created_at")[:limite]
    )


# ── Stockage ────────────────────────────────────────────────────────────

def stockage_panel(host):
    def handler(request):
        import json
        from django.db.models import Count
        from old.backend.modules.plugins.forge.models import ForgeRecord
        from old.backend.GestionSysteme.formatting import dt_full

        collection = tables.read_text(request, "collection")
        module = tables.read_text(request, "module")
        if module and collection:
            fs = tables.FilterSet(per_page=tables.read_per_page(request))
            query = fs.add(tables.search_filter(request, "q", "Clé"))
            fs.hidden = [("module", module), ("collection", collection)]
            fs.reset_url = tables.url_with(request, q=None, page=None)
            qs = ForgeRecord.objects.filter(module_name=module, collection=collection)
            if query.value:
                qs = qs.filter(key__icontains=query.value)
            page = tables.paginate(request, qs.order_by("-updated_at", "-pk"), per_page=fs.per_page)
            return P.Blocks([
                P.Fields([P.Field("Collections", "← Retour aux collections", kind="link", href=request.path)]),
                P.Table([P.Column("Clé"), P.Column("Modifiée le"), P.Column("Valeur")], [
                    P.Row((P.mono(r.key), P.text(dt_full(r.updated_at)), P.text("Données JSON")),
                          detail=P.Code(json.dumps(r.value, ensure_ascii=False, indent=2), title=r.key))
                    for r in page.rows
                ], page=page, filters=fs, caption=f"{module} / {collection}", empty="Aucune donnée pour ces filtres."),
            ])
        qs = ForgeRecord.objects.values("module_name", "collection").annotate(n=Count("id")).order_by("module_name", "collection")
        page = tables.paginate(request, qs, per_page=50)
        return P.Table(
            caption="Collections stockées",
            columns=[P.Column("Module"), P.Column("Collection"), P.Column("Lignes", align="num")],
            rows=[P.Row((P.mono(r["module_name"]), P.text(r["collection"]), P.num(r["n"])),
                        href=tables.url_with(request, module=r["module_name"], collection=r["collection"], page=None))
                  for r in page.rows],
            page=page, empty="Aucune donnée stockée par les apps.",
        )
    return handler


# ── Actions ─────────────────────────────────────────────────────────────

def _tout_recharger(host):
    def handler(request):
        from asgiref.sync import async_to_sync

        noms = list(host._loaded) + list(host._load_errors)
        if not noms:
            return P.Note("Aucun module forgé à recharger.", tone="info")
        echecs = []
        for nom in noms:
            resultat = async_to_sync(host.command)(nom, "reload")
            if not resultat.get("ok", True):
                echecs.append(f"{nom} : {resultat.get('message', '?')}")
        if echecs:
            return P.Note(
                f"{len(noms) - len(echecs)}/{len(noms)} rechargés. "
                + " · ".join(echecs),
                tone="warn",
            )
        return P.Note(f"{len(noms)} module(s) rechargé(s).", tone="ok")

    return handler


# ── Vues déclarées par les modules forgés ───────────────────────────────

def _panneau_forge(host, module_forge, vue):
    """Adapte une vue déclarée dans le manifeste d'un module forgé.

    Le gestionnaire est du code écrit par l'IA, exécuté dans le bac à sable.
    Sa charge utile respecte le contrat v2, décodé en composants typés.
    Le résultat reste borné en taille par
    ``views._normalize_view_result``.
    """
    from old.backend.modules.plugins.forge.views import _make_data_handler

    brut = _make_data_handler(host, module_forge.name, vue.key, page_params=vue.page_params)

    def handler(request):
        from asgiref.sync import async_to_sync

        charge = async_to_sync(brut)(request)
        if isinstance(charge, dict) and charge.get("error"):
            return P.Note(str(charge["error"]), tone="danger",
                          title=f"{module_forge.name} · {vue.key}")
        return charge

    return P.ModulePanel(
        key=vue.key,
        label=vue.label,
        icon=vue.icon or "▦",
        order=vue.order,
        handler=handler,
        description=vue.description or "Page déclarée par cette app.",
        actions=tuple(P.PanelAction(
            key=a["key"], label=a["label"], confirm=a["confirm"], danger=a["danger"],
            description=a["description"], fields=a["fields"],
            handler=_action_handler(host, module_forge.name, vue.key, a["key"]),
        ) for a in vue.actions),
    )


def _action_handler(host, app, view, action):
    async def handler(request):
        lm = host._loaded.get(app)
        if lm is None:
            return P.Note("Cette app n'est pas chargée.", tone="danger")
        handler_name = f"action_{view}_{action}"
        if handler_name not in lm.handlers:
            return P.Note(f"Action non implémentée : {handler_name}", tone="danger")
        ok, result, error = await host._run_handler(
            lm, handler_name, (request.panel_data,), source="action", count_failure=False,
        )
        if not ok:
            return P.Note(str(error)[:500], tone="danger")
        if isinstance(result, dict):
            return P.Note(str(result.get("message", "Action exécutée."))[:500],
                          tone="ok" if result.get("ok", True) else "danger")
        return P.Note(str(result or "Action exécutée.")[:500], tone="ok")
    return handler


# ── Déclaration ─────────────────────────────────────────────────────────

def _actions_modules(host) -> tuple:
    """Seule action de l'atelier : tout recharger.

    Les commandes visant **une** app (activer, recharger, revenir en
    arrière, effacer) vivent dans l'espace de cette app : elles portaient
    ici sur « la fiche ouverte », c'est-à-dire sur une chaîne de requête que
    rien ne rendait visible à côté du bouton.
    """
    return (
        P.PanelAction(
            key="tout_recharger", label="Tout recharger",
            handler=_tout_recharger(host),
            confirm="Recharger toutes les apps forgées ?",
        ),
    )


def build_panels(host) -> list:
    panneaux = [
        P.ModulePanel(
            key="modules", label="Modules", icon="⚒", order=10,
            handler=modules_panel(host),
            description="État des modules que Mika a écrits elle-même.",
            actions=_actions_modules(host),
        ),
        P.ModulePanel(
            key="journal", label="Journal", icon="▤", order=20,
            handler=journal_panel(host),
            description="Logs applicatifs et événements système, par module.",
        ),
        P.ModulePanel(
            key="stockage", label="Stockage", icon="◈", order=30,
            handler=stockage_panel(host),
            description="Lignes écrites par chaque module, par collection.",
        ),
    ]

    return panneaux


def panels_for_app(host, nom: str) -> list:
    """Pages déclarées **et** implémentées par une app forgée.

    Elles ne sont plus greffées dans l'espace de l'hôte : une app forgée a
    son propre espace (« Forge apps »), où sa configuration et ses pages
    tiennent ensemble. Greffées ici, dix apps donnaient trente onglets à un
    module qui n'en déclare que trois, et la config partait ailleurs encore.
    """
    lm = host._loaded.get(nom)
    if lm is None:
        return []
    return [
        _panneau_forge(host, lm, vue)
        for vue in lm.manifest.views
        # Déclarée mais pas implémentée → pas de page morte.
        if f"view_{vue.key}" in lm.handlers
    ]
