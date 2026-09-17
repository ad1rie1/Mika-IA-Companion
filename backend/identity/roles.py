"""Les trois niveaux de compte : parler à Mika, l'administrer, la posséder.

Un ``person_id`` transporte *qui* parle ; ce module dit *ce que ce compte a le
droit de faire* en dehors de la conversation. Trois niveaux, emboîtés :

* **Compte de conversation** — ``user_<pk>`` : un login du frontend. Il parle
  à Mika sur le WebSocket, lit sa propre conversation, touche ses propres
  fichiers. Rien d'autre.
* **Opérateur** — un compte de conversation dont le ``User`` Django porte
  ``is_staff`` (et ``is_active``). C'est lui qui administre : ``/gestion/``,
  l'API d'administration (projets, Forge, approbations, endpoints de
  développement), l'ensemble des fichiers déposés.
* **Propriétaire** — le niveau du contexte privé des modules (objets des
  e-mails non lus, réveils en attente) et du récit intégral d'un chantier.
  Ce sont **les opérateurs, plus** les handles listés dans
  ``OWNER_PERSON_IDS`` (un ``tg_<id>`` : l'opérateur sur un autre transport,
  qui n'a pas de ``User`` Django), plus les canaux internes de Mika
  (``conscience*``, ``module_*`` — sa propre vie intérieure n'est pas un
  invité). Choix documenté : un opérateur est propriétaire par défaut, parce
  que ``/gestion/`` lui montre déjà toute la conversation et toute la
  configuration — lui cacher le contexte des modules ne protégerait rien.

Avant ce module, ``is_owner`` rendait vrai pour **tout** ``user_*`` : créer un
compte de conversation dans *Accès · Comptes* faisait un administrateur, sur
``/api/*`` (approuver un envoi d'e-mail, effacer une app forgée, lancer la
boucle d'outils d'un atelier) comme dans le prompt (le contexte privé de
chaque module). C'est la distinction que ce fichier introduit.

**Le cache des opérateurs.** ``is_owner`` / ``is_operator`` sont appelés en
synchrone depuis des coroutines (l'assemblage du contexte, chaque ``op_*`` du
service de fichiers, le choix d'un confident dans la conscience) et à chaque
tour — une requête ORM par appel est inacceptable, et une requête ORM *sur la
boucle* lève ``SynchronousOnlyOperation``. La réponse est un ensemble en RAM
des ``pk`` des comptes opérateurs, rempli à la première lecture, **invalidé
par signal** (``post_save`` / ``post_delete`` sur ``User`` — le tableau de
bord promeut et rétrograde par ``save()``, ``connect_signals`` est branché
dans ``identity/apps.py``) et, ceinture et bretelles, périmé après
``CACHE_TTL_S`` pour qu'une modification faite hors processus (``manage.py
shell``, un second worker) finisse par être vue. Le remplissage depuis une
coroutine passe par un fil auxiliaire : une requête courte, rare (au plus une
par TTL ou par modification de compte), qui bloque la boucle le temps d'un
``SELECT`` sur une table de quelques lignes. Une lecture qui échoue (table
absente avant ``migrate``, base verrouillée) **ferme la porte** — personne
n'est opérateur — et se mémorise ``FAILURE_RETRY_S`` : réessayer à chaque
appel sous une base verrouillée, c'est payer le délai d'attente du verrou
à chaque tour.

N'importe ni ``pipeline`` ni ``modules`` : les deux le consomment.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings

logger = logging.getLogger(__name__)

# Préfixe des handles de compte, tel que ``/auth/whoami`` les frappe.
ACCOUNT_PREFIX = "user_"

# Les canaux internes de Mika — propriétaires par construction.
INTERNAL_OWNER_PREFIXES = ("conscience", "module_")

# Péremption du cache des opérateurs, pour les modifications hors processus.
CACHE_TTL_S = 60.0
# Après une lecture en échec, on ne réessaie pas avant ce délai.
FAILURE_RETRY_S = 5.0

_lock = threading.Lock()
_staff_pks: frozenset[int] = frozenset()
_loaded_at: float = 0.0        # 0 = jamais chargé, ou invalidé
_failed_at: float = 0.0
# Un seul fil : le remplissage est rare et sérialisé sous ``_lock``.
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="roles-cache")


# ── Handles ───────────────────────────────────────────────────────


def account_pk(person_id: str) -> int | None:
    """Le ``pk`` du ``User`` derrière un handle ``user_<pk>``, sinon ``None``."""
    if not person_id or not person_id.startswith(ACCOUNT_PREFIX):
        return None
    reste = person_id[len(ACCOUNT_PREFIX):]
    return int(reste) if reste.isdigit() else None


def person_id_of(user) -> str:
    """Le handle d'un ``request.user`` — vide pour un anonyme."""
    if user is None or not getattr(user, "is_authenticated", False):
        return ""
    return f"{ACCOUNT_PREFIX}{user.pk}"


def is_chat_account(person_id: str) -> bool:
    """Un login du frontend — le niveau plancher, sans droit d'administration."""
    return account_pk(person_id) is not None


def is_internal(person_id: str) -> bool:
    return bool(person_id) and person_id.startswith(INTERNAL_OWNER_PREFIXES)


# ── Niveaux depuis un person_id ──────────────────────────────────


def is_operator(person_id: str) -> bool:
    """Un compte ``user_<pk>`` dont le ``User`` est ``is_staff`` et actif."""
    pk = account_pk(person_id)
    if pk is None:
        return False
    return pk in _operator_pks()


def is_owner(person_id: str) -> bool:
    """Peut lire le contexte privé des modules et tout ce qui est « à Mika ».

    Opérateurs + ``OWNER_PERSON_IDS`` + canaux internes. Un ``user_*`` qui
    n'est pas opérateur est un invité authentifié : pas propriétaire.
    """
    if not person_id:
        return False
    if is_internal(person_id):
        return True
    if person_id in getattr(settings, "OWNER_PERSON_IDS", []):
        return True
    return is_operator(person_id)


# ── Niveaux depuis un request.user ───────────────────────────────


def is_operator_user(user) -> bool:
    """Le même verdict que ``is_operator``, lu sur l'objet déjà chargé.

    Pas de cache ici : ``request.user`` porte ``is_staff``, et la session
    d'un compte désactivé est déjà anonyme (``user_can_authenticate``).
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    return bool(getattr(user, "is_staff", False))


def is_owner_user(user) -> bool:
    if is_operator_user(user):
        return True
    pid = person_id_of(user)
    return bool(pid) and pid in getattr(settings, "OWNER_PERSON_IDS", [])


# ── Cache des opérateurs ─────────────────────────────────────────


def invalidate() -> None:
    """Oublie l'ensemble chargé ; la prochaine lecture relit la base."""
    global _loaded_at, _failed_at
    with _lock:
        _loaded_at = 0.0
        _failed_at = 0.0


def _operator_pks() -> frozenset[int]:
    global _staff_pks, _loaded_at, _failed_at
    now = time.monotonic()
    with _lock:
        if _loaded_at and now - _loaded_at < CACHE_TTL_S:
            return _staff_pks
        if _failed_at and now - _failed_at < FAILURE_RETRY_S:
            return _staff_pks
        try:
            pks = _lire_les_operateurs()
        except Exception as exc:  # noqa: BLE001 — porte fermée, pas d'exception sur le chemin chaud
            logger.warning("Lecture des comptes operateurs impossible : %s", exc)
            _staff_pks = frozenset()
            _failed_at = now
            _loaded_at = 0.0
            return _staff_pks
        _staff_pks = pks
        _loaded_at = now
        _failed_at = 0.0
        return _staff_pks


def _lire_les_operateurs() -> frozenset[int]:
    """La requête, sur ce fil si aucune boucle n'y tourne, sinon sur le fil
    auxiliaire (l'ORM refuse une requête synchrone sur la boucle)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return _requete()
    return _executor.submit(_requete_puis_fermer).result(timeout=30)


def _requete() -> frozenset[int]:
    from django.contrib.auth import get_user_model

    qs = get_user_model().objects.filter(is_staff=True, is_active=True)
    return frozenset(int(pk) for pk in qs.values_list("pk", flat=True))


def _requete_puis_fermer() -> frozenset[int]:
    """Sur le fil auxiliaire, la connexion est propre à ce fil : on la ferme
    derrière soi plutôt que d'en garder une ouverte entre deux remplissages."""
    from django.db import connection

    try:
        return _requete()
    finally:
        connection.close()


def connect_signals() -> None:
    """Branche l'invalidation sur les écritures de ``User``.

    Appelé depuis ``IdentityConfig.ready()`` : ``get_user_model()`` n'est pas
    disponible à l'import de ce module.
    """
    from django.contrib.auth import get_user_model
    from django.db.models.signals import post_delete, post_save

    def _sur_ecriture(sender, **kwargs):
        invalidate()

    modele = get_user_model()
    post_save.connect(_sur_ecriture, sender=modele,
                      dispatch_uid="identity.roles.post_save", weak=False)
    post_delete.connect(_sur_ecriture, sender=modele,
                        dispatch_uid="identity.roles.post_delete", weak=False)
