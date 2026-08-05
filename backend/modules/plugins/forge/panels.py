"""Panneaux de la Forge pour GestionSystème.

Remplacent la vue unique à onglets déclarée dans ``views.py`` — laquelle
restait rendue par un script générique côté navigateur. Ce que le portage
apporte :

- **Trois panneaux au lieu d'un onglet client** : Modules, Journal, Stockage.
  Chacun a sa propre URL, donc son propre état de pagination et de filtres.
- **Le journal est filtrable et paginé côté serveur.** L'ancienne vue en
  chargeait 200 lignes d'un coup, sans filtre : sur une installation où
  plusieurs modules forgés tournent en boucle, c'est la seule table qui
  grossit vite, et c'est celle qu'on lit quand quelque chose casse.
- **Les commandes sont des boutons.** Le disjoncteur désactive un module
  après cinq échecs consécutifs ; le réactiver demandait jusqu'ici un outil
  MCP ou un appel HTTP.
- **Les vues des modules forgés deviennent des panneaux.** Leur charge utile
  est produite par du code que l'IA écrit à l'exécution : elle passe par le
  convertisseur de charges utiles historiques, donc par des cellules typées.
  Le rendu n'a aucun chemin d'une clé de charge utile vers du balisage.
"""
from __future__ import annotations

import logging

from GestionSysteme import panels as P
from GestionSysteme import tables

logger = logging.getLogger("module.forge")

MAX_CODE = 8000

_TONS_STATUT = {
    "actif": "ok",
    "désactivé": "",
    "cassé": "danger",
    "non chargé": "warn",
}


# ── Modules ─────────────────────────────────────────────────────────────

def modules_panel(host):
    def handler(request):
        infos = host.module_infos()

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
            rows=[_ligne_module(request, i) for i in infos],
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
    if manifeste:
        blocs.append(P.Prose(title="manifest.yaml", text=manifeste))
    if code:
        blocs.append(P.Prose(title="module.py", text=code))

    blocs.append(P.Table(
        caption="Journal",
        columns=[
            P.Column("Quand", align="fit"),
            P.Column("Niveau", align="fit"),
            P.Column("Source", align="fit"),
            P.Column("Message"),
        ],
        rows=[_ligne_journal(r, avec_module=False) for r in _journal(nom, 30)],
        empty="Aucune entrée pour cette app.",
    ))
    return blocs


def _source(nom: str) -> tuple[str, str]:
    """Manifeste et code du module, lus sur disque.

    Une lecture impossible devient un texte explicite plutôt qu'une page en
    erreur : c'est précisément un module cassé qu'on vient inspecter.
    """
    import yaml

    from modules.plugins.forge import store

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
    if len(code) > MAX_CODE:
        code = code[:MAX_CODE] + "\n… (tronqué)"
    return manifeste, code


# ── Journal ─────────────────────────────────────────────────────────────

def journal_panel(host):
    def handler(request):
        from modules.plugins.forge.models import ForgeLog

        # ``order_by()`` vide avant ``distinct()`` : le modèle déclare un
        # ``Meta.ordering`` sur ``created_at``, que Django ajoute alors au
        # SELECT — la colonne de tri entre dans la clé de dédoublonnage et
        # chaque ligne de journal ressort comme un module distinct. Le plafond
        # de 100 ne gardait donc que les modules ayant écrit le plus
        # récemment : les autres disparaissaient du filtre.
        noms = sorted(
            ForgeLog.objects
            .order_by()
            .values_list("module_name", flat=True)
            .distinct()[:100]
        )

        fs = tables.FilterSet(per_page=tables.read_per_page(request, default=50))
        module = fs.add(tables.select_filter(
            request, "module", "Module", [(n, n) for n in noms if n],
        ))
        niveau = fs.add(tables.select_filter(
            request, "niveau", "Niveau",
            [(v, v) for v, _ in ForgeLog.Level.choices],
        ))
        recherche = fs.add(tables.search_filter(
            request, "q", "Recherche", placeholder="dans le message",
        ))

        qs = ForgeLog.objects.all()
        if module.value:
            qs = qs.filter(module_name=module.value)
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
            empty="Aucune entrée.",
        )

    return handler


_TONS_NIVEAU = {"error": "danger", "warning": "warn", "info": "", "debug": ""}


def _ligne_journal(entree, *, avec_module: bool = True) -> P.Row:
    from GestionSysteme.formatting import dt_full

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
    from modules.plugins.forge.models import ForgeLog

    return list(
        ForgeLog.objects.filter(module_name=nom).order_by("-created_at")[:limite]
    )


# ── Stockage ────────────────────────────────────────────────────────────

def stockage_panel(host):
    def handler(request):
        from django.db.models import Count

        from modules.plugins.forge.models import ForgeRecord

        lignes = (
            ForgeRecord.objects.values("module_name", "collection")
            .annotate(n=Count("id"))
            .order_by("module_name", "collection")
        )
        page = tables.paginate(request, list(lignes), per_page=50)

        return P.Table(
            caption="Stockage par module",
            columns=[
                P.Column("Module"),
                P.Column("Collection"),
                P.Column("Lignes", align="num"),
            ],
            rows=[
                P.Row(cells=(
                    P.mono(r["module_name"]),
                    P.text(r["collection"]),
                    P.num(r["n"]),
                ))
                for r in page.rows
            ],
            page=page,
            empty=(
                "Aucune donnée stockée. Les modules forgés n'ont jamais de DDL : "
                "ils écrivent dans une table partagée, par collection."
            ),
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
    Sa charge utile passe par le convertisseur historique — donc par des
    cellules typées — et le résultat reste borné en taille par
    ``views._normalize_view_result``.
    """
    from modules.plugins.forge.views import _make_data_handler

    brut = _make_data_handler(host, module_forge.name, vue.key)

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
        description="Page déclarée par cette app.",
    )


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
