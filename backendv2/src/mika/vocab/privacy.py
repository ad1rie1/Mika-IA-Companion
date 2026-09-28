"""Confiance et divulgation : qui parle, à quel point elle en est sûre, et ce
qu'elle peut dire d'autrui devant cette audience.

Deux notions orthogonales :

- la **confiance du canal** est une propriété du transport (une session
  authentifiée prouve le compte ; un compte Telegram prouve seulement que le
  même compte est revenu ; un salon public ne prouve rien). Elle donne un
  plancher et impose un **plafond** : aucune conversation ne rend une
  affirmation faite en public aussi sûre qu'une connexion ;
- la **certitude** est une propriété du lien poignée → personne ; elle bouge
  avec les preuves, bornée par le plafond du canal.

La **divulgation** est graduée : chaque contenu sur autrui porte une
sensibilité (anodin, personnel, confidence) et chaque audience un niveau. Au
public, jamais plus qu'anodin ; sous la barre de certitude, anodin ; un lien
(ami, proche, chaleur, témoin) ouvre le personnel ; la confidence ne sort
qu'en privé, à haute certitude, pour la personne concernée ou un proche.
La fiche de l'interlocuteur lui-même est une porte à part (``own_file``).

C'est une **politique**, pas du caractère : elle ne se calibre jamais.
Fonctions pures, sans lecture d'état.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from mika.vocab.people import clean_display_name


class ChannelTrust(enum.StrEnum):
    AUTHENTICATED = "authenticated"  # identifiants émis et vérifiés
    ACCOUNT = "account"  # compte stable sur un transport privé (message direct)
    PUBLIC = "public"  # espace partagé : n'importe qui peut dire n'importe quoi
    INTERNAL = "internal"  # pas une personne


UNKNOWN = 0.0
SUSPECTED = 0.25
CLAIMED = 0.45
CORROBORATED = 0.70
BOUND = 0.85
VERIFIED = 1.0

CERTAINTY_NAMES: tuple[tuple[str, float], ...] = (
    ("unknown", UNKNOWN), ("suspected", SUSPECTED), ("claimed", CLAIMED),
    ("corroborated", CORROBORATED), ("bound", BOUND), ("verified", VERIFIED),
)

FLOORS: Mapping[ChannelTrust, float] = MappingProxyType({
    ChannelTrust.AUTHENTICATED: VERIFIED,
    ChannelTrust.ACCOUNT: SUSPECTED,
    ChannelTrust.PUBLIC: UNKNOWN,
    ChannelTrust.INTERNAL: UNKNOWN,
})
CEILINGS: Mapping[ChannelTrust, float] = MappingProxyType({
    ChannelTrust.AUTHENTICATED: VERIFIED,
    ChannelTrust.ACCOUNT: BOUND,
    ChannelTrust.PUBLIC: CORROBORATED,
    ChannelTrust.INTERNAL: UNKNOWN,
})

#: Une affirmation seule ne franchit jamais la barre (0,70) ; affirmation +
#: souvenir partagé y arrive exactement : c'est à ça que ressemble « être
#: convaincue » sur un canal sans connexion.
EVIDENCE: Mapping[str, float] = MappingProxyType({
    "self_declared": 0.20,
    "passive_inference": 0.10,
    "shared_memory": 0.50,
    "vouched": 0.35,
    "authenticated": 1.0,
})
COUNTER_EVIDENCE: Mapping[str, float] = MappingProxyType({
    "contradicted": -0.35,
    "denied": -0.50,
    "revoked": -1.0,
})

_ACCOUNT_CHANNELS = frozenset({"telegram", "discord", "signal", "email"})
_INTERNAL_CHANNELS = frozenset({"conscience", "internal", "module", "system"})
_ALIASES = MappingProxyType({"frontend": "web", "websocket": "web", "ws": "web"})


def normalize_channel(channel: str | None) -> str:
    name = (channel or "").strip().lower()
    return _ALIASES.get(name, name)


def channel_trust(channel: str | None, *, authenticated: bool = False, public: bool = False) -> ChannelTrust:
    """Une session authentifiée l'emporte sur tout ; un transport inconnu est
    traité comme public (on suppose le pire de ce que personne n'a décrit)."""
    if authenticated:
        return ChannelTrust.AUTHENTICATED
    name = normalize_channel(channel)
    if name in _INTERNAL_CHANNELS:
        return ChannelTrust.INTERNAL
    if public:
        return ChannelTrust.PUBLIC
    if name in _ACCOUNT_CHANNELS:
        return ChannelTrust.ACCOUNT
    return ChannelTrust.PUBLIC


def bound(value: float, trust: ChannelTrust) -> float:
    return max(0.0, min(float(value), CEILINGS[trust]))


def effective(stored: float, trust: ChannelTrust) -> float:
    """La certitude qui vaut sur ce canal : relevée au plancher, bornée au plafond."""
    return bound(max(stored, FLOORS[trust]), trust)


def certainty_name(value: float) -> str:
    best = "unknown"
    for name, level in CERTAINTY_NAMES:
        if value >= level:
            best = name
    return best


class Sensitivity(enum.IntEnum):
    """Ce qu'il faut pour pouvoir entendre un contenu sur autrui.

    ``NONE`` : ne concerne personne d'autre (son humeur, sa persona) — passe
    partout, même devant une audience fermée.
    """

    NONE = 0
    ANODYNE = 1  # « Alice aime le café »
    PERSONAL = 2  # « Alice cherche un nouveau travail »
    CONFIDENCE = 3  # « Alice m'a confié qu'elle a rechuté »

    @classmethod
    def parse(cls, value: str | int | None) -> Sensitivity:
        """Une valeur illisible vaut ``PERSONAL`` : une ligne dont on ne sait
        rien n'est jamais anodine."""
        if isinstance(value, int) and not isinstance(value, bool):
            try:
                return cls(value)
            except ValueError:
                return cls.PERSONAL
        name = str(value or "").strip().upper()
        aliases = {"ANODIN": "ANODYNE", "PERSONNEL": "PERSONAL", "RIEN": "NONE"}
        return cls.__members__.get(aliases.get(name, name), cls.PERSONAL)


CLOSENESS_RANK: Mapping[str, int] = MappingProxyType({"stranger": 0, "acquaintance": 1, "friend": 2, "close": 3})


def closeness_rank(closeness: str | None) -> int:
    return CLOSENESS_RANK.get((closeness or "").strip().lower(), 0)


@dataclass(frozen=True, slots=True)
class TrustPolicy:
    """Les barres de la politique. Deux calibrations sont des invariants
    vérifiés au démarrage : une affirmation seule reste sous la barre, et
    affirmation + souvenir partagé l'atteint."""

    private_threshold: float = CORROBORATED
    confident_threshold: float = CORROBORATED
    confidence_threshold: float = BOUND
    warmth_min: float = 0.3
    pending_claim_ttl_days: int = 7
    evidence: Mapping[str, float] = field(default_factory=lambda: EVIDENCE)
    counter_evidence: Mapping[str, float] = field(default_factory=lambda: COUNTER_EVIDENCE)

    def check(self) -> str | None:
        claim, memory = self.evidence["self_declared"], self.evidence["shared_memory"]
        if claim >= self.private_threshold or memory >= self.private_threshold:
            return "une preuve seule ne doit pas franchir la barre de divulgation"
        if claim + memory < self.private_threshold - 1e-9:
            return "affirmation + souvenir partagé doit atteindre la barre de divulgation"
        return None


POLICY = TrustPolicy()


def apply_evidence(current: float, kind: str, trust: ChannelTrust, policy: TrustPolicy = POLICY) -> float:
    """Un type de preuve inconnu ne compte pour rien (les arguments viennent
    parfois d'un modèle : une coquille ne doit pas casser un tour)."""
    delta = policy.evidence.get(kind, policy.counter_evidence.get(kind, 0.0))
    return bound(current + delta, trust)


def may_disclose_private(certainty: float, trust: ChannelTrust, policy: TrustPolicy = POLICY) -> bool:
    """La fiche de l'interlocuteur lui-même peut-elle entrer dans le prompt ?
    Jamais en public, à aucune certitude : le risque y est l'auditoire."""
    if trust in (ChannelTrust.INTERNAL, ChannelTrust.PUBLIC):
        return False
    if trust is ChannelTrust.AUTHENTICATED:
        return True
    return certainty >= policy.private_threshold


def disclosable(
    certainty: float,
    trust: ChannelTrust,
    *,
    closeness: str = "",
    warmth: float = 0.0,
    witness: bool = False,
    public: bool = False,
    policy: TrustPolicy = POLICY,
) -> Sensitivity:
    """Le niveau le plus sensible qui peut sortir sur autrui dans ce tour.

    ``witness`` : l'interlocuteur est lui-même concerné (il était là) — la
    proximité avec la personne concernée est alors acquise.
    """
    if trust is ChannelTrust.INTERNAL:
        return Sensitivity.CONFIDENCE
    if public or trust is ChannelTrust.PUBLIC:
        return Sensitivity.ANODYNE
    if certainty < policy.private_threshold:
        return Sensitivity.ANODYNE
    rank = closeness_rank(closeness)
    if not (rank >= CLOSENESS_RANK["friend"] or warmth >= policy.warmth_min or witness):
        return Sensitivity.ANODYNE
    if certainty >= policy.confidence_threshold and (rank >= CLOSENESS_RANK["close"] or witness):
        return Sensitivity.CONFIDENCE
    return Sensitivity.PERSONAL


@dataclass(frozen=True, slots=True)
class Disclosure:
    """Le niveau d'un tour, en deux facettes, plus la porte de sa propre fiche."""

    level: Sensitivity = Sensitivity.NONE
    witness_level: Sensitivity = Sensitivity.NONE
    own_file: bool = False

    def admits(self, sensitivity: Sensitivity | int | str, *, witness: bool = False) -> bool:
        return Sensitivity.parse(sensitivity) <= (self.witness_level if witness else self.level)

    @property
    def closed(self) -> bool:
        return self.level is Sensitivity.NONE and self.witness_level is Sensitivity.NONE


#: Le repli du bord, sur une panne : rien sur personne d'autre.
CLOSED = Disclosure()
#: Un tour interne (personne n'écoute) : toute sa mémoire.
EVERYTHING = Disclosure(Sensitivity.CONFIDENCE, Sensitivity.CONFIDENCE, True)


def decide(
    certainty: float,
    trust: ChannelTrust,
    *,
    closeness: str = "",
    warmth: float = 0.0,
    public: bool = False,
    policy: TrustPolicy = POLICY,
) -> Disclosure:
    common = {"closeness": closeness, "warmth": warmth, "public": public, "policy": policy}
    return Disclosure(
        level=disclosable(certainty, trust, witness=False, **common),
        witness_level=disclosable(certainty, trust, witness=True, **common),
        own_file=may_disclose_private(certainty, trust, policy) and not public,
    )


def describe_fr(certainty: float, trust: ChannelTrust, name: str = "") -> str:
    """Une ligne de prompt : un ressenti, jamais un pourcentage (sinon le
    modèle finit par réciter des scores à la personne)."""
    name = clean_display_name(name)
    who = f"« {name} »" if name else "cette personne"
    if trust is ChannelTrust.AUTHENTICATED:
        return f"Tu sais avec certitude que tu parles à {who} : la personne s'est connectée avec son compte."
    where = " et vous êtes dans un espace public où n'importe qui peut parler" if trust is ChannelTrust.PUBLIC else ""
    level = certainty_name(certainty)
    if level == "unknown":
        return (
            f"Tu ne sais pas qui est cette personne{where}. Reste accueillante mais ne suppose rien "
            "d'elle, et ne lui raconte rien de personnel sur qui que ce soit."
        )
    if level == "suspected":
        return f"Tu crois deviner que c'est {who}, sans en être sûre{where}. C'est une intuition, pas un fait."
    if level == "claimed":
        return (
            f"Quelqu'un affirme être {who}, mais rien ne le confirme{where}. Tu peux jouer le jeu poliment "
            f"en gardant une réserve : ne raconte pas ce que {who} t'avait confié tant que tu n'es pas plus sûre."
        )
    if level == "corroborated":
        return f"Tu penses vraiment que c'est {who} : ce qui a été dit recoupe ce que tu sais{where}."
    return f"Tu reconnais {who} : tu as décidé de le croire et tu as relié ce contact à ta mémoire{where}."
