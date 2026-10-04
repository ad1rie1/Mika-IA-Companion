"""Confiance et divulgation : qui parle, à quel point elle en est sûre, et ce
qu'elle peut dire d'autrui devant cette audience.

Deux notions orthogonales :

- la **confiance du canal** est une propriété du transport (une session
  authentifiée prouve le compte ; un compte sur un réseau extérieur — forum,
  messagerie, réseau social où elle échangerait d'elle-même — prouve seulement
  que le même compte est revenu ; un salon public ne prouve rien). Elle donne un
  plancher et impose un **plafond** : aucune conversation ne rend une
  affirmation faite en public aussi sûre qu'une connexion ;
- la **certitude** est une propriété du lien adresse → personne ; elle bouge
  avec les preuves, bornée par le plafond du canal.

La **divulgation** est graduée : chaque contenu sur autrui porte une
sensibilité (anodin, personnel, confidence) et chaque audience un niveau. Au
public, jamais plus qu'anodin ; sous la barre de certitude, anodin ; un lien
ouvre le personnel — être amie ou proche, ou de la chaleur pour quelqu'un
qu'elle connaît déjà (la chaleur seule, pour une inconnue, n'ouvre rien sur
autrui), ou avoir été là quand ça s'est dit (témoin) ; la confidence ne sort
qu'en privé, à haute certitude, pour une amie qui était là — ou pour une
proche **qui a un lien avec la personne concernée** (elles se sont parlé
ensemble, ou la personne concernée l'a nommée elle-même : ``tied``). Être
proche de Mika ne suffit pas : c'est l'anecdote qui échappe en grande
confiance, pas la confidence lourde de quelqu'un qu'on ne connaît pas — et
prononcer un nom ne crée aucun lien (ADR 0058).
Ce que quelqu'un a demandé de ne répéter à personne (un secret) ne ressort
que devant qui l'a confié : ce n'est pas un niveau, c'est la mémoire qui le
garde (``faculties/memory``). La fiche de l'interlocuteur lui-même est une
porte à part (``own_file``).

C'est une **politique**, pas du caractère : elle ne se calibre jamais.
Fonctions pures, sans lecture d'état.
"""

from __future__ import annotations

import enum
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from mika.vocab.people import EXTERNAL_PREFIX, clean_display_name


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

#: le web : l'application, avec ou sans compte
WEB = "web"
#: un compte sur un réseau extérieur (forum, messagerie, réseau social), adresses ``ext_…`` : un compte
#: stable, rien ne prouve qui le tient — le nom générique d'un canal non sécurisé
EXTERNAL = "external"
#: l'application du téléphone (ADR 0062) : toujours authentifiée (un compte, par son jeton), et une
#: **messagerie** — elle reçoit hors ligne (une notification), on la lit quand on y pense
MOBILE = "mobile"
#: les canaux d'un compte stable en conversation privée. Ce sont aussi des **messageries** : un message s'y
#: lit quand on y pense (pas quand il arrive), et elle peut y écrire à quelqu'un d'absent
_ACCOUNT_CHANNELS = frozenset({EXTERNAL, "discord", "signal", "email"})
#: les messageries : les comptes extérieurs, et l'application du téléphone — qui n'est pas un « compte » au
#: sens de la confiance (sans session, elle ne prouverait rien : un transport non décrit reste public)
_MESSAGING = _ACCOUNT_CHANNELS | {MOBILE}
_INTERNAL_CHANNELS = frozenset({"conscience", "internal", "module", "system"})
_ALIASES = MappingProxyType({"frontend": "web", "websocket": "web", "ws": "web"})


def normalize_channel(channel: str | None) -> str:
    name = (channel or "").strip().lower()
    return _ALIASES.get(name, name)


def channel_of(handle: str) -> str:
    """Le canal d'une adresse d'après sa forme, pour une adresse qui n'a encore jamais écrit (un opérateur
    la relie d'avance) : ``ext_…`` est un compte extérieur, le reste le web."""
    return EXTERNAL if handle.startswith(EXTERNAL_PREFIX) else WEB


def is_messaging(channel: str | None) -> bool:
    """Une messagerie : on y lit quand on y pense, et elle peut y écrire à quelqu'un d'absent (en privé).
    L'écran (le web) est l'inverse : on y répond en minutes, et seulement si on est là."""
    return normalize_channel(channel) in _MESSAGING


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
    tied: bool = False,
    public: bool = False,
    policy: TrustPolicy = POLICY,
) -> Sensitivity:
    """Le niveau le plus sensible qui peut sortir sur autrui dans ce tour.

    ``witness`` : l'interlocuteur était là quand ça s'est dit — il l'a
    entendu lui-même, le personnel lui est ouvert ; la confidence, seulement
    s'il est au moins un ami (un simple témoin n'est pas un confident).
    ``tied`` : l'interlocuteur a un lien avec la personne concernée (ils se
    sont parlé ensemble devant elle, ou cette personne l'a nommé elle-même) —
    une proche qui a ce lien peut recevoir sa confidence ; une proche sans ce
    lien, l'anecdote seulement (ADR 0058).
    La chaleur seule n'ouvre rien sur autrui à une inconnue : il faut au moins
    la connaître.
    """
    if trust is ChannelTrust.INTERNAL:
        return Sensitivity.CONFIDENCE
    if public or trust is ChannelTrust.PUBLIC:
        return Sensitivity.ANODYNE
    if certainty < policy.private_threshold:
        return Sensitivity.ANODYNE
    rank = closeness_rank(closeness)
    warm = warmth >= policy.warmth_min and rank >= CLOSENESS_RANK["acquaintance"]
    if not (rank >= CLOSENESS_RANK["friend"] or warm or witness):
        return Sensitivity.ANODYNE
    if certainty >= policy.confidence_threshold and (
            (tied and rank >= CLOSENESS_RANK["close"]) or (witness and rank >= CLOSENESS_RANK["friend"])):
        return Sensitivity.CONFIDENCE
    return Sensitivity.PERSONAL


@dataclass(frozen=True, slots=True)
class Disclosure:
    """Le niveau d'un tour, en trois facettes — ce qu'elle peut dire d'autrui ;
    quand l'interlocuteur était là (témoin) ; quand il a un lien avec la
    personne concernée (``tied``) —, plus la porte de sa propre fiche."""

    level: Sensitivity = Sensitivity.NONE
    witness_level: Sensitivity = Sensitivity.NONE
    own_file: bool = False
    tied_level: Sensitivity = Sensitivity.NONE

    def admits(self, sensitivity: Sensitivity | int | str, *, witness: bool = False, tied: bool = False) -> bool:
        limit = self.witness_level if witness else self.level
        if tied:
            limit = max(limit, self.tied_level)
        return Sensitivity.parse(sensitivity) <= limit

    @property
    def closed(self) -> bool:
        return (self.level is Sensitivity.NONE and self.witness_level is Sensitivity.NONE
                and self.tied_level is Sensitivity.NONE)


#: Le repli du bord, sur une panne : rien sur personne d'autre.
CLOSED = Disclosure()
#: Un tour interne (personne n'écoute) : toute sa mémoire.
EVERYTHING = Disclosure(Sensitivity.CONFIDENCE, Sensitivity.CONFIDENCE, True, Sensitivity.CONFIDENCE)


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
        tied_level=disclosable(certainty, trust, tied=True, **common),
    )


def tied_to(others: Collection[str], ties: Collection[str]) -> bool:
    """L'interlocuteur a-t-il un lien avec **toutes** les personnes concernées
    (``others`` : celles qui ne sont pas lui) ? Un nom dont on lui a parlé
    (``name:…``) ne compte pas — c'est un détail de l'histoire de qui le
    raconte ; il faut au moins une personne identifiée, et un lien avec chacune."""
    persons = [o for o in others if not o.startswith("name:")]
    return bool(persons) and all(o in ties for o in persons)


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


def hearable(about: tuple[str, ...], sensitivity: int, interlocutor: str | None, level: int, witness_level: int,
             own_file: bool, *, tied_level: int = 0, ties: Collection[str] = ()) -> bool:
    """Ce qu'on peut dire devant une audience : ce qui ne concerne personne
    d'identifié passe s'il est anodin ou si l'audience peut l'entendre (un
    mail reçu n'est pas à tout le monde) ; ce qui ne concerne que
    l'interlocuteur, s'il est anodin ou si sa fiche est ouverte ; ce qui
    concerne d'autres, jusqu'au niveau de l'audience (le niveau « témoin »
    quand l'interlocuteur en est aussi, le niveau « lié » quand il a un lien
    avec chacune des autres personnes concernées — ``ties``)."""
    if not about:
        return sensitivity <= max(Sensitivity.ANODYNE, level)
    others = [a for a in about if a != interlocutor]
    if not others:
        return sensitivity <= Sensitivity.ANODYNE or own_file
    limit = witness_level if interlocutor in about else level
    if tied_to(others, ties):
        limit = max(limit, tied_level)
    return sensitivity <= limit
