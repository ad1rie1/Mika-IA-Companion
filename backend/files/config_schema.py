"""Réglages du service de fichiers.

Les plafonds ici ne protègent pas le disque : ils protègent le *prompt*.
Le bloc « fichiers uploadés aujourd'hui » repart à chaque tour et à chaque
itération de la boucle d'outils, et une réponse d'outil reste dans
l'historique de cette boucle — une entrée pèse ~60 tokens (UUID et
horodatage ISO se tokenisent très mal).

Chaque constante rapatriée reste déclarée dans ``files/service.py`` et y
sert de repli ; le ``default`` ci-dessous lui est identique au bit près.
"""
from __future__ import annotations

from configs.types import ConfigGroup, ConfigItem, ConfigSection

CONFIG_SCHEMA = [
    ConfigSection(
        key="files", label="Fichiers", icon="◰", order=64,
        family="travail",
        summary="Ce que Mika voit des fichiers déposés : ce qui entre au "
                "prompt, ce qu'un outil en rend.",
        description="Ce que Mika voit des fichiers déposés : combien sont "
                    "listés dans son prompt, et combien un outil en rend.",
    ),
    ConfigGroup(
        section="files", key="Prompt système", order=10,
        description="Le bloc « fichiers uploadés aujourd'hui » repart à chaque "
                    "tour ET à chaque itération de la boucle d'outils. Ces "
                    "plafonds ne protègent pas le disque, ils protègent le "
                    "prompt : une entrée pèse ~60 tokens, un UUID et un "
                    "horodatage ISO se tokenisant très mal.",
    ),
    ConfigGroup(
        section="files", key="Outil files_list", order=20,
        description="Ce que rend l'outil quand Mika fouille elle-même. Les "
                    "deux valeurs sont interpolées dans la description MCP de "
                    "l'outil au moment de l'enregistrement — d'où le "
                    "redémarrage exigé : ce qui est annoncé au modèle ne se "
                    "rafraîchit qu'au démarrage.",
    ),
    ConfigGroup(
        section="files", key="Registre", order=30, advanced=True,
        description="La table chargée en RAM au démarrage, qui traduit un "
                    "identifiant de fichier pour files_read / analyze / move / "
                    "delete. Bornée large : au-delà, les fichiers les plus "
                    "anciens cessent d'être résolus par leur ID, et un "
                    "avertissement le dit au démarrage.",
    ),

    ConfigItem(
        key="files.max_today_lines", type="int", section="files",
        group="Prompt système",
        label="Fichiers du jour listés dans le prompt",
        default=6, min=0, max=100, hot_reload=True,
        description="Entrées détaillées inline dans le bloc « fichiers "
                    "uploadés aujourd'hui ». Le reste est compté sur une "
                    "ligne et reste joignable par files_list.",
        hint="Le bloc repart à chaque tour ET à chaque itération de la "
             "boucle d'outils : sans plafond, une journée de tri de "
             "documents y ajoutait une ligne par fichier, définitivement.",
    ),
    ConfigItem(
        key="files.max_name_chars", type="int", section="files",
        group="Prompt système",
        label="Longueur d'un nom de fichier affiché",
        default=80, min=8, max=255, hot_reload=True,
        description="Plafond de rendu du nom dans le prompt système.",
        hint="Volontairement indépendant du plafond d'écriture de "
             "pipeline.media : le rendu se défend seul, y compris pour les "
             "enregistrements antérieurs à cette borne.",
    ),

    ConfigItem(
        key="files.default_list_limit", type="int", section="files",
        group="Outil files_list",
        label="Fichiers rendus par défaut",
        default=25, min=1, max=500, restart_required=True,
        description="Taille de page de files_list quand le modèle ne "
                    "demande rien de précis.",
        hint="Redémarrage obligatoire : la valeur est interpolée dans la "
             "*description* de l'outil MCP au moment de l'enregistrement, "
             "donc le schéma annoncé au modèle ne se rafraîchit qu'au "
             "démarrage.",
    ),
    ConfigItem(
        key="files.max_list_limit", type="int", section="files",
        group="Outil files_list",
        label="Fichiers rendus au maximum",
        default=50, min=1, max=1000, restart_required=True,
        description="Plafond dur, quelle que soit la valeur demandée par "
                    "le modèle.",
        hint="Redémarrage obligatoire, même raison : la valeur est "
             "interpolée dans la description de l'outil MCP à "
             "l'enregistrement. La troncature est dite — la réponse porte "
             "`total` à côté de `shown`.",
    ),

    ConfigItem(
        key="files.max_registry_load", type="int", section="files",
        group="Registre",
        label="Entrées chargées en mémoire au démarrage",
        default=2000, min=100, max=100000, restart_required=True,
        description="Le registre sert aussi de table de résolution à "
                    "files_read / analyze / move / delete.",
        hint="Borne volontairement large : elle empêche une base "
             "pathologique de tout charger en RAM, pas l'usage normal. "
             "Au-delà, les fichiers les plus anciens ne sont plus résolus "
             "par leur ID (un avertissement le dit au démarrage).",
    ),
]
