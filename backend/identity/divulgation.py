"""La divulgation graduée — ce que Mika peut raconter d'autrui, et à qui.

La porte de ``identity/trust.py`` (``may_disclose_private_context``) reste
la porte de la *fiche* de l'interlocuteur lui-même : elle ne change pas. Ce
module répond à l'autre question, celle que la porte binaire écrasait :
**jusqu'à quel niveau de sensibilité ce que Mika sait des AUTRES peut-il
entrer dans ce tour ?**

Un humain ne répète pas une confidence à un inconnu, mais avec un ami très
proche, en confiance, une anecdote peut lui échapper — et ce qui échappe est
rarement le secret le plus lourd. D'où trois sensibilités sur les lignes de
mémoire (``anodin`` / ``personnel`` / ``confidence``, notées par
l'extracteur) et un **niveau divulgable** par tour, fonction de cinq faits :

* la certitude d'identité, déjà clampée par le canal — inchangée ;
* le canal (une salle publique → jamais plus qu'``anodin``) ;
* la proximité de l'interlocuteur (``PersonProfile.closeness``) ;
* la chaleur de l'ancre affective envers lui ;
* sa proximité avec la personne concernée (il était là quand ça s'est dit).

Au-dessus du niveau : retiré mécaniquement. Au niveau ou en dessous mais pas
``anodin`` : **rendu avec un tag** pour que Mika arbitre — comme elle
arbitre déjà le tampon partagé. La ``confidence`` ne sort qu'en privé, à
certitude ≥ 0,85, pour la personne concernée elle-même ou un proche.

Pur, comme ``trust.py`` : aucune lecture de registre. Les seuils réglables
arrivent dans un ``DivulgationTuning`` résolu au bord (``identity.resolver``).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from identity.trust import PRIVATE_CONTEXT_THRESHOLD, Certainty, ChannelTrust


class Niveau(str, Enum):
    """Ce qui peut sortir sur autrui. ``str`` : la valeur est celle stockée
    sur ``Souvenir.sensibilite`` / ``Connaissance.sensibilite`` pour les
    trois derniers membres, et part telle quelle dans les journaux."""

    #: Rien sur personne d'autre — le repli fermé (panne d'identité, acte
    #: sans destinataire). Vaut mot pour mot l'ancienne porte binaire fermée.
    RIEN = "rien"
    #: « Alice aime le café ». Passe partout où quelqu'un écoute.
    ANODIN = "anodin"
    #: « Alice cherche un nouveau boulot ». Confié, pas secret.
    PERSONNEL = "personnel"
    #: « Alice m'a dit qu'elle a rechuté ». Le plus lourd.
    CONFIDENCE = "confidence"


RANG: dict[Niveau, int] = {
    Niveau.RIEN: 0,
    Niveau.ANODIN: 1,
    Niveau.PERSONNEL: 2,
    Niveau.CONFIDENCE: 3,
}

#: Les trois sensibilités qu'une ligne de mémoire peut porter (jamais RIEN).
SENSIBILITES: tuple[str, ...] = (
    Niveau.ANODIN.value, Niveau.PERSONNEL.value, Niveau.CONFIDENCE.value,
)

#: Ordre des proximités de ``PersonProfile.closeness``. Une valeur inconnue
#: ou vide compte comme un inconnu.
_RANG_CLOSENESS: dict[str, int] = {
    "stranger": 0, "acquaintance": 1, "friend": 2, "close": 3,
}


def niveau_de(valeur: str | Niveau | None) -> Niveau:
    """Le ``Niveau`` d'une valeur stockée ; une valeur illisible est lue
    ``PERSONNEL`` — une ligne dont on ne sait rien n'est jamais anodine."""
    if isinstance(valeur, Niveau):
        return valeur
    try:
        return Niveau(str(valeur or "").strip().lower())
    except ValueError:
        return Niveau.PERSONNEL


def rang_closeness(closeness: str | None) -> int:
    return _RANG_CLOSENESS.get(str(closeness or "").strip().lower(), 0)


@dataclass(frozen=True)
class DivulgationTuning:
    """Les seuils, tels qu'ils *peuvent* être réglés.

    Défauts = constantes du module = calibration documentée. La barre du
    ``personnel`` est **la même** que celle de la fiche
    (``identity.private_context_threshold``) : une seconde clé pour la même
    barre serait le doublon que le rapatriement en configuration a coûté à
    nettoyer.
    """

    #: Sous cette certitude, rien de plus qu'``anodin`` sur autrui.
    barre_personnel: float = PRIVATE_CONTEXT_THRESHOLD
    #: À partir de cette certitude (et en privé), une ``confidence`` peut
    #: sortir pour la personne concernée ou un proche.
    barre_confidence: float = float(Certainty.BOUND)
    #: Chaleur d'ancre (composante plaisir du fond affectif, ∈ [0, 1]) à
    #: partir de laquelle un lien tiède compte comme un lien.
    chaleur_min: float = 0.3


DEFAULT_DIVULGATION_TUNING = DivulgationTuning()


def niveau_divulgable(
    certitude: float,
    canal: ChannelTrust,
    *,
    closeness: str = "",
    chaleur: float = 0.0,
    proximite_avec_concerne: bool = False,
    audience_publique: bool = False,
    tuning: DivulgationTuning | None = None,
) -> Niveau:
    """Le niveau de sensibilité, sur autrui, que ce tour peut porter.

    Les règles, du plus fermé au plus ouvert :

    * canal **interne** (personne n'écoute) → ``confidence`` : sa mémoire
      entière, comme un pas de chantier ;
    * **salle publique** (canal ``PUBLIC`` ou ``audience_publique``) →
      ``anodin`` au plus, quel que soit le reste — le risque y est
      l'auditoire, pas l'erreur d'identité ;
    * certitude **sous la barre** (0,70) → ``anodin`` : on ne raconte pas
      l'histoire d'Alice à quelqu'un dont on n'est pas sûr que c'est Thomas ;
    * à partir de la barre → ``personnel`` si le lien existe : ami ou proche,
      OU ancre affective chaude, OU l'interlocuteur était là (il partage le
      souvenir avec la personne concernée) ; sinon ``anodin`` ;
    * ``confidence`` seulement en privé, certitude ≥ 0,85, ET (proche, OU
      personne concernée elle-même — c'est le sens de
      ``proximite_avec_concerne`` quand il est vrai).

    Ne rend jamais ``RIEN`` : ce repli est celui du bord, sur une panne.
    """
    t = tuning or DEFAULT_DIVULGATION_TUNING

    if canal is ChannelTrust.INTERNAL:
        return Niveau.CONFIDENCE
    if audience_publique or canal is ChannelTrust.PUBLIC:
        return Niveau.ANODIN
    if certitude < t.barre_personnel:
        return Niveau.ANODIN

    lien = (
        rang_closeness(closeness) >= _RANG_CLOSENESS["friend"]
        or chaleur >= t.chaleur_min
        or proximite_avec_concerne
    )
    if not lien:
        return Niveau.ANODIN

    if certitude >= t.barre_confidence and (
        rang_closeness(closeness) >= _RANG_CLOSENESS["close"]
        or proximite_avec_concerne
    ):
        return Niveau.CONFIDENCE
    return Niveau.PERSONNEL


@dataclass(frozen=True)
class Divulgation:
    """Le niveau du tour, en deux facettes.

    ``niveau`` vaut pour une ligne qui concerne un tiers *seul* ;
    ``avec_temoin`` pour une ligne où l'interlocuteur figure aussi parmi
    les personnes concernées — il était là, la proximité avec la personne
    concernée est acquise gratuitement (``proximite_avec_concerne=True``),
    sans requête. Le calcul est fait une fois par tour ; le retriever choisit
    la facette ligne par ligne d'après les entités déjà chargées.
    """

    niveau: Niveau = Niveau.RIEN
    avec_temoin: Niveau = Niveau.RIEN
    #: La fiche de l'interlocuteur LUI-MÊME est ouverte — c'est
    #: ``may_disclose_private_context``, inchangé, porté ici pour que la
    #: voie épisodique chaude (SON verbatim) n'ait pas à le redemander.
    fiche_ouverte: bool = False

    def admet(self, sensibilite: str | Niveau, *, temoin: bool = False) -> bool:
        """Cette sensibilité peut-elle sortir dans ce tour ?"""
        borne = self.avec_temoin if temoin else self.niveau
        return RANG[niveau_de(sensibilite)] <= RANG[borne]

    @property
    def ferme(self) -> bool:
        return self.niveau is Niveau.RIEN and self.avec_temoin is Niveau.RIEN


#: Le repli fermé : rien sur personne d'autre.
FERME = Divulgation(Niveau.RIEN, Niveau.RIEN, fiche_ouverte=False)
#: Sa mémoire entière — un tour interne, un pas de chantier.
TOUT = Divulgation(Niveau.CONFIDENCE, Niveau.CONFIDENCE, fiche_ouverte=True)


def decider(
    certitude: float,
    canal: ChannelTrust,
    *,
    closeness: str = "",
    chaleur: float = 0.0,
    audience_publique: bool = False,
    fiche_ouverte: bool = False,
    tuning: DivulgationTuning | None = None,
) -> Divulgation:
    """Les deux facettes d'un coup, à partir des faits résolus au bord.
    ``fiche_ouverte`` est recopié tel quel : il vient de la porte binaire."""
    commun = dict(
        closeness=closeness, chaleur=chaleur,
        audience_publique=audience_publique, tuning=tuning,
    )
    return Divulgation(
        niveau=niveau_divulgable(certitude, canal, proximite_avec_concerne=False, **commun),
        avec_temoin=niveau_divulgable(certitude, canal, proximite_avec_concerne=True, **commun),
        fiche_ouverte=bool(fiche_ouverte),
    )


def expliquer_fr(divulgation: Divulgation) -> str:
    """Une ligne lisible du niveau — pour le tableau de bord, jamais le prompt."""
    libelles = {
        Niveau.RIEN: "rien sur personne d'autre",
        Niveau.ANODIN: "l'anodin seulement",
        Niveau.PERSONNEL: "le personnel, tagué pour qu'elle arbitre",
        Niveau.CONFIDENCE: "jusqu'aux confidences, taguées",
    }
    base = libelles[divulgation.niveau]
    if divulgation.avec_temoin is not divulgation.niveau:
        return f"{base} ; {libelles[divulgation.avec_temoin]} pour ce qu'elle a vécu avec elle"
    return base
