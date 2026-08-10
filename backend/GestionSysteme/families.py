"""Les familles de la barre latérale de Configuration.

Une famille est un intertitre au-dessus des sections. Elle existe parce que la
liste est devenue plate et longue : trente et une sections rangées par un
simple ``order``, où « Mémoire » et « Pulsions » se cherchaient au même endroit
que « Comptes » et « Providers ».

Le classement d'avant devinait la famille à partir du préfixe de la clé
(``comm_`` → Communication, ``ai_`` → IA) et jetait **tout le reste** dans un
groupe nommé « Cœur ». Tant qu'il y avait quatre sections dedans ça tenait ;
il y en a maintenant quinze, et un fourre-tout de quinze entrées n'est pas un
classement, c'est la liste plate avec une étiquette dessus.

Les familles sont donc **déclarées**, et une section dit à laquelle elle
appartient (``ConfigSection.family``). Deux conséquences voulues :

- un module peut poser sa propre famille sans que cette liste le sache ;
- une section qui ne déclare rien retombe sur l'heuristique de préfixe, donc
  la migration se fait section par section sans jamais casser l'écran.

L'ordre est celui de la lecture, pas celui de l'alphabet : on commence par qui
a le droit d'entrer, puis par qui elle est, puis par ce qui la fait tourner,
et on finit par la plomberie.
"""
from __future__ import annotations

from configs.types import ConfigFamily

#: Rangée en dernier, et *nommée*, plutôt qu'un « Cœur » implicite : une
#: section qui atterrit là n'a pas déclaré sa famille, et l'étiquette doit le
#: dire au lieu de faire croire à un rangement.
FAMILLE_DEFAUT = "autres"

FAMILIES = [
    ConfigFamily(
        key="acces", label="Accès", icon="⚿", order=10,
        description="Qui peut ouvrir cet écran, et le reste.",
    ),
    ConfigFamily(
        key="personnage", label="Personnage", icon="✦", order=20,
        description="Qui elle est, comment elle parle, à quel rythme elle vit.",
    ),
    ConfigFamily(
        key="intelligence", label="Intelligence", icon="⟠", order=30,
        description="Fournisseurs, modèles, rôles, budget de contexte.",
    ),
    ConfigFamily(
        key="vie_interieure", label="Vie intérieure", icon="❋", order=40,
        description="Émotion, pulsions, conscience, mémoire — ce qui tourne "
                    "même quand personne ne parle.",
    ),
    ConfigFamily(
        key="conversation", label="Conversation", icon="⟳", order=50,
        description="Ce qui se passe entre un message reçu et une réponse dite.",
    ),
    ConfigFamily(
        key="canaux", label="Canaux", icon="◇", order=60,
        description="Par où les messages entrent et sortent.",
    ),
    ConfigFamily(
        key="travail", label="Travail", icon="◱", order=70,
        description="Projets, fichiers — sa part professionnelle.",
    ),
    ConfigFamily(
        key="systeme", label="Système", icon="▦", order=80,
        description="Plomberie : modules, cadences, garde-fous.",
    ),
    ConfigFamily(
        key=FAMILLE_DEFAUT, label="Non classé", icon="·", order=999,
        description="Sections qui n'ont pas encore déclaré leur famille.",
    ),
]

#: Repli tant que toutes les sections n'ont pas déclaré leur ``family``.
#: Volontairement court : il ne doit pas devenir un second classement à
#: entretenir, seulement un pont le temps de la migration.
PREFIXES_DE_REPLI: tuple[tuple[str, str], ...] = (
    ("comm_", "canaux"),
    ("telegram", "canaux"),
    ("ai_", "intelligence"),
    ("pipeline_", "conversation"),
    ("personnalite", "personnage"),
    ("module_", "systeme"),
)


def family_of(section) -> str:
    """La famille d'une section : déclarée, sinon devinée, sinon « non classé »."""
    if getattr(section, "family", ""):
        return section.family
    for prefixe, famille in PREFIXES_DE_REPLI:
        if section.key.startswith(prefixe):
            return famille
    return FAMILLE_DEFAUT
