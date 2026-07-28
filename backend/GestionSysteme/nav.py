"""Spécification de la navigation — source unique du menu et des onglets.

L'ancien tableau de bord alignait **23 entrées de menu** dans 7 groupes, plus
un groupe par module actif : le menu était un miroir du schéma de base de
données (« Souvenirs », « Connaissances », « Thèmes », « Entités »,
« Messages »… tous au même poids visuel) plutôt que des questions qu'on se
pose devant l'écran.

Ici : **9 entrées**, chacune regroupant ses tables en onglets. « Souvenirs » et
« Connaissances » sont deux vues de la mémoire, pas deux destinations.

Les onglets sont des segments d'URL (``/gestion/memoire/souvenirs/``), pas un
état en localStorage : un onglet se partage, se met en favori, et le retour
arrière du navigateur fonctionne.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Tab:
    """Un onglet dans une page. ``key`` est le segment d'URL."""
    key: str
    label: str
    count_key: str = ""     # clé dans le dict de compteurs, pour le badge


@dataclass(frozen=True)
class NavItem:
    key: str
    label: str
    icon: str
    url_name: str                       # nom de route sans espace de noms
    count_key: str = ""
    tabs: tuple[Tab, ...] = ()
    description: str = ""

    def tab(self, key: str | None) -> Tab | None:
        """Résout un segment d'onglet, avec repli sur le premier.

        Un segment inconnu retombe sur l'onglet par défaut plutôt que de
        lever une 404 : une URL périmée après renommage d'un onglet doit
        continuer à ouvrir la page, pas casser un favori.
        """
        if not self.tabs:
            return None
        if key:
            for t in self.tabs:
                if t.key == key:
                    return t
        return self.tabs[0]


@dataclass(frozen=True)
class NavGroup:
    label: str
    items: tuple[NavItem, ...] = field(default_factory=tuple)


# ── Les neuf destinations ───────────────────────────────────────────────

OVERVIEW = NavItem(
    key="overview", label="Vue d'ensemble", icon="▣", url_name="overview",
    description="L'état de Mika en un écran : humeur, énergie, activité des boucles, ce qui attend une décision.",
)

INNER = NavItem(
    key="inner", label="Vie intérieure", icon="◕", url_name="inner",
    description="Ce qu'elle ressent et ce qui la pousse à agir, indépendamment de toute conversation.",
    tabs=(
        Tab("emotions", "Émotions"),
        Tab("drives", "Drives"),
        Tab("ruminations", "Ruminations", count_key="ruminations"),
        Tab("rythme", "Rythme & sommeil"),
        Tab("historique", "Historique affectif"),
    ),
)

MEMORY = NavItem(
    key="memory", label="Mémoire", icon="▤", url_name="memory",
    description="Ce qu'elle a vécu, ce qu'elle sait, et les traces brutes dont tout cela est extrait.",
    tabs=(
        Tab("souvenirs", "Souvenirs", count_key="souvenirs"),
        Tab("connaissances", "Connaissances", count_key="connaissances"),
        Tab("themes", "Thèmes"),
        Tab("entites", "Entités"),
        Tab("messages", "Messages"),
        Tab("journaux", "Journaux & rêves"),
        Tab("recit", "Récit de soi"),
    ),
)

SOCIAL = NavItem(
    key="social", label="Social", icon="◍", url_name="social",
    description=(
        "Qui parle, à quel point elle en est sûre, et ce que cette certitude "
        "débloque. L'ordre des onglets suit celui du prompt : l'identité "
        "qualifie la fiche personne qui la suit."
    ),
    tabs=(
        Tab("identites", "Identités", count_key="identity"),
        Tab("demandes", "Revendications", count_key="claims"),
        Tab("personnes", "Personnes"),
        Tab("engagements", "Engagements", count_key="commitments"),
        Tab("politique", "Politique de confiance"),
    ),
)

CONSCIENCE = NavItem(
    key="conscience", label="Conscience", icon="◉", url_name="conscience",
    description="Ce qu'elle a perçu, ce qu'elle en a décidé, et ce qu'elle a prévu de faire.",
    tabs=(
        Tab("observations", "Observations", count_key="observations"),
        Tab("decisions", "Décisions"),
        Tab("planification", "Planification"),
    ),
)

PROJECTS = NavItem(
    key="projects", label="Projets", icon="▥", url_name="projects",
    count_key="pending_actions",
    description="Ses engagements de travail explicites — le mode professionnel, émotions coupées par défaut.",
    tabs=(
        Tab("actifs", "Projets"),
        Tab("attente", "En attente d'accord", count_key="pending_actions"),
        Tab("journal", "Journal d'exécution"),
    ),
)

MODULES = NavItem(
    key="modules", label="Modules", icon="▦", url_name="modules",
    count_key="modules_down",
    description="Les greffons installés, leur état, et l'accès à leur espace dédié.",
)

CONFIG = NavItem(
    key="config", label="Configuration", icon="⚙", url_name="config",
    description="Les paramètres du cœur. Ceux des modules vivent dans l'espace de chaque module.",
)

SYSTEM = NavItem(
    key="system", label="Système", icon="▩", url_name="system",
    count_key="degradations",
    description="Santé technique : pannes silencieuses, bus d'événements, quotas, routage IA, historique de config.",
    tabs=(
        Tab("sante", "Santé", count_key="degradations"),
        Tab("routage", "Routage IA"),
        Tab("quota", "Quotas"),
        Tab("consolidation", "Consolidation"),
        Tab("journal-config", "Journal de configuration"),
    ),
)


NAV: tuple[NavGroup, ...] = (
    NavGroup("", (OVERVIEW,)),
    NavGroup("État de l'IA", (INNER, MEMORY, SOCIAL, CONSCIENCE, PROJECTS)),
    NavGroup("Administration", (MODULES, CONFIG, SYSTEM)),
)


# Index par clé — les vues résolvent leur propre NavItem pour en tirer
# titre, description et onglets sans les redéclarer.
BY_KEY: dict[str, NavItem] = {
    item.key: item
    for group in NAV
    for item in group.items
}


def item_for(key: str) -> NavItem:
    try:
        return BY_KEY[key]
    except KeyError:  # pragma: no cover — faute de frappe dans une vue
        raise LookupError(f"Entrée de navigation inconnue : {key!r}") from None
