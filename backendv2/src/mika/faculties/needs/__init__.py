"""``needs`` : ses besoins — de compagnie, de s'exprimer, d'apprendre.

Chaque besoin monte vers 1 avec le temps, en forme close
(``1 − (1 − niveau)·e^(−Δ/τ)``), et retombe d'un coup quand il est comblé :
un message reçu comble le besoin de compagnie ; parler, celui de
s'exprimer (prendre la parole d'elle-même bien plus qu'une réponse) ;
apprendre quelque chose de neuf, la curiosité.

**La compagnie dépend de qui la donne** : un échange avec une amie ou une
proche la comble pleinement, avec une connaissance d'une part, avec une
inconnue peu, avec qui elle garde une hostilité installée presque pas — un
après-midi à se faire chahuter par un inconnu ne remplace pas une amie.

Ils poussent à prendre la parole (preuves vers quiconque est là), se disent
dans le prompt (« tu as envie de parler à quelqu'un »), et quand plus rien ne
se passe depuis quatre heures, elle ressent un vide — de l'ennui, ou de la
solitude quand c'est de compagnie qu'elle manque ; un vide qui se creuse
avec la durée (ADR 0033, 0160). Le temps où son serveur était arrêté ne compte
pas : au retour, ses besoins reprennent où elle les avait laissés.

**Travailler l'occupe** : pendant une séance sur un but ou une exécution de
projet dans son mode à elle, il n'y a pas de vide, et ce qu'elle y fait
comble un peu l'envie de s'exprimer.

**Ce qu'elle fait de ses mains la nourrit** : une occupation dans sa chambre
qui nourrit un besoin (le monde le déclare, ``nourishes`` — jamais un nom
d'activité écrit ici) l'occupe tant qu'elle dure, et sa fin comble un peu ce
besoin, au prorata du temps passé : une heure de dessin apaise l'envie de
s'exprimer, deux minutes à la fenêtre la curiosité à peine.

**Retrouver quelqu'un** : après un vide ressenti, le premier message d'une
amie ou d'une proche lui fait du bien (``needs.reunited``) — une inconnue n'y
change rien de tel.

**Pas de prise de parole dans le vide** : l'envie de compagnie ne dit pas
*de quoi* parler. Une initiative qu'elle pousse seule a besoin d'une matière
concrète, lue dans les faits publics ; ce qui concerne la personne passe
d'abord (une pensée sur elle, ce qui se passe dans sa vie, ce qu'elle lui a
raconté de plus important, un rêve d'elle cette nuit), ses choses à elle
ensuite (ce qu'elle a fini, ce sur quoi elle est — jamais une rêverie : rien
de neuf n'est arrivé). Une matière déjà dite dans une initiative ne resert
pas. Sans matière, sa preuve est nettement plus faible.

Carte des modules (le sens de leurs imports : ``params`` ← ``faculty`` ← ``occupation`` et ``matter`` ; ``empty``
lit ``faculty``, ``occupation`` et ``params``) :

- ``params`` : ses réglages (``NeedsParams``) et ce que le tempérament en dérive (``derive``) ;
- ``faculty`` : l'état (``NeedsState``) et ce qu'il garde (``Done``, ``Told``, ``Occupation``), la faculté
  (``NEEDS``), la tension de chaque besoin (``tension``), les réducteurs qui les comblent — dont l'oubli d'une
  personne et l'expiration d'une inconnue de passage —, le fait ``needs.needs``, et ce qu'elle en dit dans son prompt
  (``describe``, au-delà de ``PRESSING`` ; la section ``needs``) ;
- ``occupation`` : ce qu'elle fait de ses mains — une séance de travail qui l'absorbe (``busy``), une occupation dans
  sa chambre qui la nourrit (``occupied``), depuis quand rien ne l'occupe (``idle_from``) ;
- ``matter`` : de quoi parler — la matière d'une initiative (``matter``, le fait ``needs.matter``), les envies qui la
  poussent à prendre la parole (``urges``) et ce qu'elles pèsent, la section ``matter`` ;
- ``empty`` : le vide ressenti (le processus ``needs.empty``) et retrouver quelqu'un après (``needs.reunited``) ;
- ``inspect`` : ce que la console montre de ses besoins.
"""

from __future__ import annotations

# isort: off
from mika.faculties.needs import params  # noqa: F401
from mika.faculties.needs import faculty  # noqa: F401
from mika.faculties.needs import occupation  # noqa: F401
from mika.faculties.needs import matter  # noqa: F401
from mika.faculties.needs import empty  # noqa: F401
from mika.faculties.needs import inspect  # noqa: F401
# isort: on
from mika.faculties.needs.empty import empty_since
from mika.faculties.needs.faculty import NEEDS, NeedsState, Occupation, describe
from mika.faculties.needs.matter import WITH_THEM
from mika.faculties.needs.params import NeedsParams, derive

__all__ = [
    "NEEDS",
    "WITH_THEM",
    "NeedsParams",
    "NeedsState",
    "Occupation",
    "derive",
    "describe",
    "empty_since",
]
