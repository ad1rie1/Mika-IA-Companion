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
COMMANDES = ("reload", "enable", "disable", "rollback")

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

        blocs = []
        fiche = _fiche_module(host, request, infos)
        if fiche is not None:
            blocs.extend(fiche)

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
    statut = info.get("status", "?")
    echecs = int(info.get("failures", 0) or 0)
    return P.Row(
        href=tables.url_with(request, module=info["name"]),
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


def _fiche_module(host, request, infos: list[dict]):
    nom = (request.GET.get("module") or "").strip()
    if not nom:
        return None

    info = next((i for i in infos if i["name"] == nom), None)
    if info is None:
        return [P.Note(f"Module forgé « {nom} » introuvable.", tone="warn")]

    champs = [
        P.Field("Nom", nom, kind="mono"),
        P.Field("Statut", info.get("status", "?"), kind="badge",
                tone=_TONS_STATUT.get(info.get("status", ""), "")),
    ]
    if info.get("status_detail"):
        champs.append(P.Field("Détail", info["status_detail"]))
    champs += [
        P.Field("Activé", "oui" if info.get("enabled") else "non"),
        P.Field("Cadence", info.get("schedule") or "—", kind="mono"),
        P.Field("Handlers", ", ".join(info.get("handlers") or []) or "—"),
        P.Field("Prochain passage", str(info.get("next_run_at") or "—")),
        P.Field("Version", str(info.get("version") or "—")),
        P.Field("Fermer la fiche", "retour à la liste", kind="link",
                href=tables.url_with(request, module=None)),
    ]

    blocs = [P.Fields(title=f"Module · {nom}", items=champs)]

    manifeste, code = _source(nom)
    if manifeste:
        blocs.append(P.Prose(title="manifest.yaml", text=manifeste))
    if code:
        blocs.append(P.Prose(title="module.py", text=code))

    blocs.append(P.Table(
        caption=f"Journal · {nom}",
        columns=[
            P.Column("Quand", align="fit"),
            P.Column("Niveau", align="fit"),
            P.Column("Source", align="fit"),
            P.Column("Message"),
        ],
        rows=[_ligne_journal(r, avec_module=False) for r in _journal(nom, 30)],
        empty="Aucune entrée pour ce module.",
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

        noms = sorted(
            ForgeLog.objects.values_list("module_name", flat=True).distinct()[:100]
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


def _commande(host, commande: str):
    """Applique une commande au module ouvert dans la fiche.

    Le nom vient de la chaîne de requête (``?module=…``), que le formulaire
    d'action conserve : une action porte sur ce que l'écran montre, pas sur
    le panneau en général. Sans fiche ouverte, elle refuse plutôt que de
    deviner une cible.
    """
    def handler(request):
        from asgiref.sync import async_to_sync

        nom = (request.GET.get("module") or "").strip()
        if not nom:
            return P.Note(
                "Ouvre d'abord la fiche d'un module : la commande porte sur lui.",
                tone="warn",
            )
        resultat = async_to_sync(host.command)(nom, commande)
        message = resultat.get("message") or f"« {commande} » exécuté."
        return P.Note(message, tone="ok" if resultat.get("ok", True) else "danger")

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
        key=f"{module_forge.name}--{vue.key}",
        label=f"{module_forge.manifest.title} · {vue.label}",
        icon=vue.icon or "▦",
        order=200 + vue.order,
        handler=handler,
        description="Page déclarée par un module forgé.",
    )


# ── Déclaration ─────────────────────────────────────────────────────────

def _actions_modules(host) -> tuple:
    """« Tout recharger », puis une commande par verbe du disjoncteur.

    Les commandes par module s'appliquent à la fiche ouverte : le formulaire
    d'action conserve la chaîne de requête, donc ``?module=…`` leur parvient.
    """
    return (
        P.PanelAction(
            key="tout_recharger", label="Tout recharger",
            handler=_tout_recharger(host),
            confirm="Recharger tous les modules forgés ?",
        ),
    ) + tuple(
        P.PanelAction(
            key=f"cmd_{verbe}", label=verbe.capitalize(),
            handler=_commande(host, verbe),
            confirm=(
                "Revenir à la version précédente de ce module ?"
                if verbe == "rollback" else ""
            ),
        )
        for verbe in COMMANDES
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

    for lm in list(host._loaded.values()):
        for vue in lm.manifest.views:
            if f"view_{vue.key}" not in lm.handlers:
                continue  # déclarée mais pas implémentée → pas de page morte
            panneaux.append(_panneau_forge(host, lm, vue))

    return panneaux
