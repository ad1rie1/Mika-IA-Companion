"""Cadence des appels de fond et disjoncteur par provider.

Deux instruments du routeur, tous deux en RAM et par provider, lus depuis le
tableau de bord (Système › Santé) sur un thread synchrone — d'où le verrou.

**Le budget d'appels de fond** — un compteur glissant sur une heure des
appels qui ne servent personne qui attend : extraction mémoire, interprétation
des signaux, tri des mails, pas de chantier, actes spontanés, voix intérieure,
compaction, travail de projet. Chaque mécanisme calculait jusqu'ici son propre
rythme (``pas_par_heure_max`` pour les chantiers, la cadence du consolidateur,
l'intervalle du lanceur de projets…) et rien ne les sommait : sur un serveur
local à un seul créneau, c'est pourtant leur *somme* qui décide si un tour de
conversation trouve le modèle libre. Le plafond est par provider
(``ai.<provider>.appels_de_fond_par_heure``, 0 = illimité) et un appel refusé
n'est jamais silencieux : compté ici par provider et par rôle, et au registre
de dégradation.

Ce qui est « de fond » se lit de deux façons, parce que le rôle seul ne suffit
pas : un pas de chantier et un acte de la conscience passent par
``conversation_tools``, le rôle même d'un tour de conversation. Le rôle donne
la première réponse (``est_role_de_fond``) ; l'appelant donne la seconde en
posant le marqueur ``en_fond()`` — un ContextVar, qui suit les ``await`` et
les tâches créées dedans, donc couvre un outil qui relance le modèle depuis
l'intérieur d'un pas. Un tour ``REQUEST_RESPONSE`` n'est jamais de fond et
n'est jamais refusé, provider saturé ou non.

**Le disjoncteur** — ``k`` pannes de *transport* consécutives (timeout
d'acquisition ou d'appel, connexion refusée) ouvrent le provider pendant
``repos_s`` : tout appel échoue immédiatement avec ``ProviderIndisponible``.
Sans lui, un Ollama figé (pas éteint : il accepte la connexion et ne répond
jamais) coûtait 120 s à chaque tour avant le texte de repli, et derrière le
sémaphore à un créneau chaque tour suivant attendait le précédent. À
l'expiration du repos, exactement un appel d'essai passe ; son succès referme,
son échec rouvre. Une 400 de paramètre, une réponse vide ou un quota ne sont
pas des pannes de transport : le provider a répondu, la série est rompue.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable

from old.backend.ai.quota import QuotaExceeded

#: Les rôles qui servent un humain en attente d'une réponse. Tout autre
#: membre de ``AIRole`` est de fond. Valeurs de l'énumération et non membres :
#: ``ai.router`` importe ce module, l'inverse serait circulaire. Le routeur
#: dérive ``ROLES_DE_FOND`` de l'énumération elle-même, et un test vérifie
#: que chaque valeur listée ici nomme bien un membre — une faute de frappe
#: rangerait un rôle humain parmi les rôles de fond sans rien dire.
ROLES_AU_SERVICE_D_UN_HUMAIN: frozenset[str] = frozenset({
    "conversation", "conversation_tools", "vision_caption", "preparation",
})

FENETRE_S = 3600.0

# Défauts du disjoncteur, appliqués quand la configuration est illisible.
# Mêmes valeurs que ``ai.<provider>.disjoncteur.*`` dans le schéma.
DISJONCTEUR_ECHECS = 3
DISJONCTEUR_REPOS_S = 60.0


def est_role_de_fond(role_value: str) -> bool:
    return str(role_value) not in ROLES_AU_SERVICE_D_UN_HUMAIN


# ── Marqueurs d'appelant ─────────────────────────────────────────────────

# Posé par l'appelant qui sait que personne n'attend (conscience, notify_ai).
_de_fond: ContextVar[bool] = ContextVar("ai_appel_de_fond", default=False)

# Providers déjà comptés par un appel englobant : un outil qui relance le
# modèle depuis la boucle d'outils tourne *dans* l'appel compté, il n'en est
# pas un second — même règle que le créneau de sémaphore partagé.
_comptes: ContextVar[frozenset[str]] = ContextVar(
    "ai_appels_de_fond_comptes", default=frozenset()
)


@contextmanager
def en_fond():
    """Tout appel routé dans ce bloc est de fond, quel que soit son rôle."""
    token = _de_fond.set(True)
    try:
        yield
    finally:
        _de_fond.reset(token)


def appelant_de_fond() -> bool:
    return _de_fond.get()


# ── Exceptions ───────────────────────────────────────────────────────────


class BudgetDeFondEpuise(QuotaExceeded):
    """Le plafond horaire d'appels de fond du provider est atteint.

    Un ``QuotaExceeded`` : les consommateurs le traitent déjà — le processeur
    sert son texte de quota, le lanceur de projets reporte le prochain run,
    l'interpréteur retombe sur son signal heuristique.
    """

    def __init__(self, provider: str, role: str, used: int, limit: int):
        self.provider = provider
        self.role = role
        super().__init__(
            f"fond:{provider}:heure", used, limit,
            detail=f"appel '{role}' différé (ai.{provider}.appels_de_fond_par_heure)",
        )


class ProviderIndisponible(asyncio.TimeoutError):
    """Le disjoncteur du provider est ouvert : l'appel n'a pas été tenté.

    Un ``TimeoutError`` : c'est ce que l'appel aurait fini par lever, en
    120 s de plus — et c'est la branche que chaque consommateur sait déjà
    traiter (texte de repli « je réfléchis plus lentement », signal
    heuristique, run reporté) sans qu'un traceback parte à chaque tick.
    """

    def __init__(self, provider: str, reste_s: float):
        self.provider = provider
        self.reste_s = reste_s
        super().__init__(
            f"provider '{provider}' indisponible (disjoncteur ouvert, "
            f"réessai dans {reste_s:.0f} s)"
        )


# ── Compteur glissant ────────────────────────────────────────────────────


class CadenceDeFond:
    """Appels de fond de la dernière heure, par provider et par rôle."""

    def __init__(self, *, horloge: Callable[[], float] = time.monotonic,
                 fenetre_s: float = FENETRE_S):
        self._horloge = horloge
        self._fenetre_s = fenetre_s
        self._lock = threading.Lock()
        # provider → (instant, rôle, refusé)
        self._journal: dict[str, deque[tuple[float, str, bool]]] = {}

    def _file(self, provider: str, maintenant: float) -> deque:
        file = self._journal.setdefault(provider, deque())
        limite = maintenant - self._fenetre_s
        while file and file[0][0] <= limite:
            file.popleft()
        return file

    def utilises(self, provider: str) -> int:
        with self._lock:
            file = self._file(provider, self._horloge())
            return sum(1 for _, _, refuse in file if not refuse)

    def disponible(self, provider: str, plafond: int) -> bool:
        """Reste-t-il un appel dans l'heure ? ``plafond`` 0 = illimité."""
        if plafond <= 0:
            return True
        return self.utilises(provider) < plafond

    def reserver(self, provider: str, role: str, plafond: int) -> bool:
        """Compter un appel s'il tient dans le plafond, sinon compter un refus.

        Test-and-set sous le verrou : deux appels ne peuvent pas partager
        le dernier créneau de l'heure.
        """
        with self._lock:
            maintenant = self._horloge()
            file = self._file(provider, maintenant)
            accepte = plafond <= 0 or (
                sum(1 for _, _, refuse in file if not refuse) < plafond
            )
            file.append((maintenant, str(role), not accepte))
            return accepte

    def refuser(self, provider: str, role: str) -> None:
        """Compter un appel qu'un consommateur a différé sans le tenter."""
        with self._lock:
            maintenant = self._horloge()
            self._file(provider, maintenant).append((maintenant, str(role), True))

    def snapshot(self, *, plafond: Callable[[str], int],
                 providers: tuple[str, ...] = ()) -> dict:
        """``{"providers": [...], "roles": [...]}`` pour la page Santé.

        ``providers`` complète la liste avec ceux qui n'ont rien appelé :
        un plafond se lit aussi quand il n'a pas encore servi.
        """
        with self._lock:
            maintenant = self._horloge()
            noms = sorted(set(providers) | set(self._journal))
            lignes = []
            par_role: dict[str, dict] = {}
            for nom in noms:
                file = self._file(nom, maintenant)
                utilises = sum(1 for _, _, refuse in file if not refuse)
                refuses = len(file) - utilises
                borne = int(plafond(nom))
                lignes.append({
                    "provider": nom,
                    "utilises": utilises,
                    "plafond": borne,
                    "refuses": refuses,
                    "sature": borne > 0 and utilises >= borne,
                })
                for _, role, refuse in file:
                    ligne = par_role.setdefault(
                        (role, nom), {"role": role, "provider": nom,
                                      "utilises": 0, "refuses": 0},
                    )
                    ligne["refuses" if refuse else "utilises"] += 1
        return {
            "providers": lignes,
            "roles": [par_role[k] for k in sorted(par_role)],
        }

    def reset(self) -> None:
        with self._lock:
            self._journal.clear()


# ── Disjoncteur ──────────────────────────────────────────────────────────


class _EtatDisjoncteur:
    __slots__ = ("echecs", "ouvert_jusqua", "essai_en_cours", "ouvertures",
                 "derniere_panne")

    def __init__(self):
        self.echecs = 0
        self.ouvert_jusqua: float | None = None
        self.essai_en_cours = False
        self.ouvertures = 0
        self.derniere_panne = ""


class Disjoncteurs:
    """Un disjoncteur par provider : fermé, ouvert, ou en essai."""

    def __init__(self, *, horloge: Callable[[], float] = time.monotonic):
        self._horloge = horloge
        self._lock = threading.Lock()
        self._etats: dict[str, _EtatDisjoncteur] = {}

    def _etat(self, provider: str) -> _EtatDisjoncteur:
        return self._etats.setdefault(provider, _EtatDisjoncteur())

    def verifier(self, provider: str) -> bool:
        """Laisse passer ou lève ``ProviderIndisponible``.

        Rend True quand l'appel est *l'essai* qui suit un repos : l'appelant
        doit alors rendre un verdict (``succes``/``echec``) ou libérer
        l'essai s'il n'en a aucun (annulation).
        """
        with self._lock:
            etat = self._etats.get(provider)
            if etat is None or etat.ouvert_jusqua is None:
                return False
            maintenant = self._horloge()
            if maintenant < etat.ouvert_jusqua:
                raise ProviderIndisponible(provider, etat.ouvert_jusqua - maintenant)
            if etat.essai_en_cours:
                # Un essai suffit ; les autres attendent son verdict.
                raise ProviderIndisponible(provider, 0.0)
            etat.essai_en_cours = True
            return True

    def succes(self, provider: str) -> None:
        """Le provider a répondu — la série de pannes est rompue."""
        with self._lock:
            etat = self._etats.get(provider)
            if etat is None:
                return
            etat.echecs = 0
            etat.ouvert_jusqua = None
            etat.essai_en_cours = False

    def echec(self, provider: str, exc: BaseException | None, *,
              seuil: int, repos_s: float) -> bool:
        """Une panne de transport. Rend True si le disjoncteur vient de s'ouvrir.

        ``seuil`` 0 = jamais d'ouverture (compte quand même).
        """
        with self._lock:
            etat = self._etat(provider)
            etat.echecs += 1
            etat.derniere_panne = (
                f"{type(exc).__name__}: {exc}" if exc is not None else ""
            )
            deja_ouvert = etat.ouvert_jusqua is not None
            if seuil <= 0 or (not deja_ouvert and etat.echecs < seuil):
                return False
            # Ouverture, ou réouverture après un essai raté.
            etat.ouvert_jusqua = self._horloge() + max(0.0, float(repos_s))
            etat.essai_en_cours = False
            etat.ouvertures += 1
            return True

    def liberer_essai(self, provider: str) -> None:
        """L'essai n'a rendu aucun verdict (annulé) : le suivant le refera."""
        with self._lock:
            etat = self._etats.get(provider)
            if etat is not None:
                etat.essai_en_cours = False

    def est_ouvert(self, provider: str) -> bool:
        with self._lock:
            etat = self._etats.get(provider)
            return etat is not None and etat.ouvert_jusqua is not None

    def snapshot(self, *, reglage: Callable[[str], tuple[int, float]],
                 providers: tuple[str, ...] = ()) -> list[dict]:
        with self._lock:
            maintenant = self._horloge()
            noms = sorted(set(providers) | set(self._etats))
            lignes = []
            for nom in noms:
                etat = self._etats.get(nom) or _EtatDisjoncteur()
                seuil, repos_s = reglage(nom)
                if etat.ouvert_jusqua is None:
                    libelle, reste = "ferme", 0.0
                elif etat.essai_en_cours:
                    libelle, reste = "essai", 0.0
                else:
                    reste = max(0.0, etat.ouvert_jusqua - maintenant)
                    libelle = "ouvert" if reste > 0 else "essai"
                lignes.append({
                    "provider": nom,
                    "etat": libelle,
                    "echecs": etat.echecs,
                    "seuil": seuil,
                    "repos_s": repos_s,
                    "ouvertures": etat.ouvertures,
                    "reouverture_dans_s": reste,
                    "derniere_panne": etat.derniere_panne,
                })
        return lignes

    def reset(self) -> None:
        with self._lock:
            self._etats.clear()


# Noms de classes, dans la MRO, qui disent « le transport a lâché » — sans
# importer les SDK : anthropic/openai ``APIConnectionError`` (dont
# ``APITimeoutError`` hérite), httpx ``TransportError`` (dont
# ``ConnectError`` et ``TimeoutException`` héritent, et que le SDK Ollama
# laisse remonter tel quel), et les natifs ``ConnectionError`` /
# ``TimeoutError``.
_PANNES_DE_TRANSPORT = frozenset({
    "APIConnectionError", "TransportError", "ConnectionError", "TimeoutError",
})


def est_panne_de_transport(exc: BaseException) -> bool:
    """Le provider n'a pas répondu — par opposition à « il a répondu non »."""
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, ConnectionError)):
        return not isinstance(exc, ProviderIndisponible)
    return any(cls.__name__ in _PANNES_DE_TRANSPORT for cls in type(exc).__mro__)


cadence_de_fond = CadenceDeFond()
disjoncteurs = Disjoncteurs()
