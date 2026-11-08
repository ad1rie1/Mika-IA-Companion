"""La machinerie des portes à clé (ADR 0213) : ce que les points appelés avec un secret se recopiaient.

Teams et les réveils (``/api/teams/…``, ``/api/wake/…``), les prêts et la console en MCP (``/mcp/pret/…``,
``/mcp/console``), les jetons de compte, les cadences du chat, du téléphone et de la connexion : l'empreinte d'un jeton
et sa comparaison en temps constant, la fabrique d'une clé, les fenêtres glissantes, le nettoyage de ce qui arrive du
dehors. C'est du code de sécurité : une correction faite ici vaut pour toutes.

**La réponse, elle, reste propre à chaque porte, et ne s'uniformise pas : elle suit son exposition.**

- *Ouverte au réseau* (Teams, réveils) : une clé absente et une mauvaise clé se répondent pareil, chaque clé rangée est
  comparée du même coût ; rien ne dit qu'un nom existe, ni combien il y en a.
- *Là où seuls la boucle locale ou un jeton d'opérateur entrent* (prêts, console MCP) : un point sans jeton n'existe pas
  (404), une mauvaise clé répond 401. Qui arrive là sait déjà ce qu'on a déclaré : il n'y a pas de nom à lui cacher.

Les issues de Teams, du téléphone et des réveils sont dans ``ports/gate.py``, leur statut HTTP dans une seule table
(``GATE_STATUS``, ``adapters/web/app.py``) ; les prêts et la console en MCP répondent leur statut eux-mêmes. Le texte
d'une réponse, et le choix de ne rien dire, restent à chaque porte.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import deque
from collections.abc import Callable, Container
from typing import Any

#: l'empreinte qu'on compare quand il n'y a rien à comparer (aucune clé, un nom inconnu) : le même temps de calcul
NOTHING = hashlib.sha256(b"").hexdigest()
#: une clé présentée, au plus (au-delà, ce n'est pas une clé : elle ne se compare pas)
KEY_MAX = 200
#: une date plausible (ms) : ni avant 2015, ni plus d'un jour dans le futur
EPOCH_2015_MS = 1_420_070_400_000
DAY_MS = 86_400_000


def token_digest(token: str) -> str:
    """L'empreinte d'un jeton porteur (SHA-256, en hexadécimal) : ce qu'on garde, ce qu'on compare."""
    return hashlib.sha256(token.encode()).hexdigest()


def new_key(prefix: str = "") -> str:
    """Une clé neuve : son préfixe (une clé se reconnaît, et ne se confond pas avec une autre), puis 32 octets tirés."""
    return prefix + secrets.token_urlsafe(32)


def presented(key: str, prefix: str) -> str:
    """L'empreinte d'une clé présentée à une porte ; ``NOTHING`` si elle n'a pas la forme de ses clés (du même coût)."""
    return token_digest(key) if key.startswith(prefix) and len(key) <= KEY_MAX else NOTHING


def matches(given: str, wanted: str) -> bool:
    """Deux empreintes comparées en temps constant. Rien d'attendu ne s'ouvre jamais, et coûte le même calcul."""
    return hmac.compare_digest(given, wanted or NOTHING) and bool(wanted)


class SlidingWindow:
    """Des fenêtres glissantes, une par clé : au plus ``n`` événements par ``window`` secondes.

    Deux usages. ``allow`` juge et compte d'un geste : une cadence (sans clé : une seule fenêtre). ``blocked`` et
    ``fail`` séparent les deux : des échecs, comptés seulement s'ils arrivent ; ``forgive`` rend un essai compté
    d'avance. ``n=`` remplace le plafond pour un appel (celui d'un réveil se règle réveil par réveil). Les clés vides
    sont oubliées, et la mémoire est bornée : un balayage d'adresses ne la fait pas grossir sans fin."""

    MAX_KEYS = 10_000

    def __init__(self, n: int, window: float, *, monotonic: Callable[[], float] = time.monotonic) -> None:
        self.n = n
        self.window = window
        self._now = monotonic
        self._hits: dict[str, deque[float]] = {}

    def _prune(self, key: str, now: float) -> deque[float] | None:
        q = self._hits.get(key)
        if q is None:
            return None
        while q and now - q[0] >= self.window:
            q.popleft()
        if not q:
            del self._hits[key]
            return None
        return q

    def _full(self, key: str, now: float, n: int | None) -> bool:
        q = self._prune(key, now)
        return q is not None and len(q) >= (self.n if n is None else n)

    def _add(self, key: str, now: float) -> None:
        if len(self._hits) >= self.MAX_KEYS:
            for k in list(self._hits):
                self._prune(k, now)
            while len(self._hits) >= self.MAX_KEYS:  # encore plein : les plus anciennes clés partent
                del self._hits[next(iter(self._hits))]
        self._hits.setdefault(key, deque()).append(now)

    def allow(self, now: float | None = None, *, key: str = "", n: int | None = None) -> bool:
        """Sous le plafond, et l'événement compté."""
        at = self._now() if now is None else now
        if self._full(key, at, n):
            return False
        self._add(key, at)
        return True

    def blocked(self, key: str = "", *, n: int | None = None) -> bool:
        return self._full(key, self._now(), n)

    def fail(self, key: str = "") -> None:
        """Un événement de plus dans la fenêtre de cette clé (un échec, ou un appel qui vient d'aboutir)."""
        self._add(key, self._now())

    def forgive(self, key: str) -> None:
        """Rendre un essai compté d'avance (``fail`` avant de vérifier, pour que des essais lancés ensemble ne
        passent pas tous la porte avant le premier échec) quand il a réussi."""
        q = self._hits.get(key)
        if q:
            q.pop()
            if not q:
                del self._hits[key]

    def wait_s(self, key: str = "") -> int:
        """Dans combien de secondes une place se libère (1 au moins) : ce que dit un ``Retry-After``."""
        now = self._now()
        q = self._prune(key, now)
        return max(1, int(self.window - (now - q[0]))) if q else 1

    def keep(self, keys: Container[str]) -> None:
        """Oublier les fenêtres des clés qui n'en sont plus (un réveil retiré)."""
        self._hits = {k: q for k, q in self._hits.items() if k in keys}

    def __len__(self) -> int:
        return len(self._hits)


def clean_text(text: str) -> str:
    """Un texte sans octet nul ni demi-caractère (une coupe au milieu d'un emoji laisse un « surrogate » seul)."""
    return text.replace("\x00", "").encode("utf-8", "replace").decode("utf-8")


def clean_fields(raw: Any) -> Any:
    """Les textes d'un élément reçu, réparés avant d'être lus (un demi-caractère ferait refuser l'élément entier)."""
    return {k: clean_text(v) if isinstance(v, str) else v for k, v in raw.items()} if isinstance(raw, dict) else raw


def one_line(text: str, limit: int) -> str:
    """Un nom ou un titre sur une ligne, sans caractères de contrôle."""
    return " ".join("".join(ch for ch in clean_text(text) if ch.isprintable() or ch == " ").split())[:limit]


def plausible_ms(ms: int, now_ms: int) -> bool:
    """Une date reçue (ms) qui peut être vraie : ni avant 2015, ni plus d'un jour dans le futur."""
    return EPOCH_2015_MS <= ms <= now_ms + DAY_MS
