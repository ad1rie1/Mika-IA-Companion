"""À qui raconter un chantier fini, et avec quel degré de détail.

Un être humain qui termine quelque chose ne le crie pas au salon : il le
raconte à *quelqu'un*, et il ne raconte pas la même chose à tout le monde.
Le degré de confidence suit le lien — l'administrateur de sa vie reçoit tout,
un proche ou quelqu'un du même domaine reçoit l'essentiel, un ami reçoit la
mention, et devant les autres il garde ça pour lui (le murmure global INNER
reste alors le comportement d'avant).

Module **pur** : la table des niveaux est une politique de relation, pas un
réglage — même famille que les planchers de canal de ``identity/trust.py``
(« qu'un inconnu ne reçoive pas le récit intégral » n'est pas une préférence).
Les entrées sont trois faits résolus par l'appelant :

* ``est_owner`` — la définition EXISTANTE du propriétaire
  (``identity.roles.is_owner`` : opérateurs ``is_staff``, ``OWNER_PERSON_IDS``
  et canaux internes — un simple compte de conversation n'en est pas un).
  On ne fabrique pas une seconde échelle de confiance.
* ``closeness`` — ce que la théorie de l'esprit sait du lien
  (``PersonProfile.closeness``).
* ``concerne`` — la personne est-elle liée au *sujet* du chantier
  (``who_is_concerned`` sur le titre et les thèmes : le « même domaine »).
"""

from __future__ import annotations

from enum import Enum


class NiveauRecit(str, Enum):
    """Combien elle raconte. ``str`` : la valeur part dans les journaux."""

    #: Le récit complet — ce qu'elle a réellement produit.
    INTEGRAL = "integral"
    #: L'essentiel — le résumé que le verdict a déclaré.
    ESSENTIEL = "essentiel"
    #: La mention — le titre, rien du contenu.
    MENTION = "mention"
    #: Rien d'adressé — le murmure global reste.
    RIEN = "rien"


#: Rang de préférence entre confidents (plus haut = raconté d'abord).
RANG_NIVEAU: dict[NiveauRecit, int] = {
    NiveauRecit.INTEGRAL: 3,
    NiveauRecit.ESSENTIEL: 2,
    NiveauRecit.MENTION: 1,
    NiveauRecit.RIEN: 0,
}


def niveau_de_recit(
    *,
    est_owner: bool = False,
    closeness: str = "",
    concerne: bool = False,
) -> NiveauRecit:
    """Le degré de confidence que ce lien autorise.

    La table, du plus ouvert au plus fermé :

    * **owner** → intégral. L'administrateur de sa vie n'a pas de secret de
      chantier — c'est aussi lui qui lit le tableau de bord.
    * **proche ET concerné** → intégral. Le meilleur ami du même domaine
      reçoit l'histoire entière, comme chez les humains.
    * **proche** → l'essentiel.
    * **ami concerné** → l'essentiel — le sujet le regarde, pas les détails.
    * **ami** → la mention. « Au fait, j'ai fini un truc » entre copains.
    * **le reste** → rien d'adressé. Une connaissance ou un inconnu n'a pas
      à recevoir un message spontané sur sa vie intérieure ; le murmure
      global, non adressé, reste ce qu'ils peuvent surprendre.
    """
    if est_owner:
        return NiveauRecit.INTEGRAL
    lien = str(closeness or "").strip().lower()
    if lien == "close":
        return NiveauRecit.INTEGRAL if concerne else NiveauRecit.ESSENTIEL
    if lien == "friend":
        return NiveauRecit.ESSENTIEL if concerne else NiveauRecit.MENTION
    return NiveauRecit.RIEN


#: Bornes de recopie — gardes de lecteur, comme dans ``verdict.py``.
_ESSENTIEL_MAX_CHARS = 300
_TITRE_MAX_CHARS = 120


def composer_recit(
    niveau: NiveauRecit,
    *,
    dit: str = "",
    resume: str = "",
    titre: str = "",
) -> str:
    """Le texte à dire pour ce niveau. Chaîne vide = ne rien adresser.

    La MENTION ne contient **jamais** ``dit`` ni ``resume`` : c'est sa
    définition — le titre est ce qu'un ami reçoit, le contenu ne fuit pas
    par un gabarit. L'ESSENTIEL préfère le résumé du verdict (la phrase
    qu'elle a elle-même choisie pour dire « ce que je viens de faire ») et
    ne retombe sur ``dit`` que tronqué.
    """
    dit = str(dit or "").strip()
    resume = str(resume or "").strip()
    titre = str(titre or "").strip()[:_TITRE_MAX_CHARS]

    if niveau is NiveauRecit.INTEGRAL:
        return dit or resume or _mention(titre)
    if niveau is NiveauRecit.ESSENTIEL:
        essentiel = resume or dit[:_ESSENTIEL_MAX_CHARS].strip()
        if not essentiel:
            return _mention(titre)
        if titre:
            return f"Ça y est, j'ai été au bout de « {titre} » : {essentiel}"
        return essentiel
    if niveau is NiveauRecit.MENTION:
        return _mention(titre)
    return ""


def _mention(titre: str) -> str:
    if not titre:
        return ""
    return f"Au fait — j'ai été au bout d'un petit truc de mon côté : « {titre} »."
