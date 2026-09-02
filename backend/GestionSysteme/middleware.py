"""Portails d'authentification : ``/gestion/`` (optionnel) et ``/api/``.

**``/gestion/``** sert tout l'historique de conversation et édite les clés
d'API des fournisseurs. Décorer chaque vue inviterait la prochaine route à
oublier le décorateur : le contrôle vit donc en un seul endroit et couvre le
préfixe.

**Désactivé par défaut** (``DASHBOARD_REQUIRE_AUTH``) : une installation neuve
n'a pas encore de superutilisateur, et enfermer quelqu'un dehors avant qu'il
puisse en créer un est pire que l'exposition sur une écoute en loopback.
L'activer tient en une variable d'environnement, et ``run.py`` avertit quand le
serveur écoute hors loopback sans elle.

Réservé au personnel : un compte créé pour le frontend de conversation ne doit
pas hériter de l'éditeur de configuration.

Le réglage garde son nom historique (``DASHBOARD_REQUIRE_AUTH``) : c'est une
variable d'environnement qu'une installation existante a peut-être déjà posée,
et la renommer transformerait une mise à jour silencieuse en portail
subitement ouvert.

**``/api/``** est l'API JSON du frontend de conversation : approbation des
actions en attente d'un projet (qui *exécute* leur charge — un envoi
d'e-mail), création et suppression de projets, commandes de la Forge
(effacer un module, lire sa source), endpoints de développement du sommeil.
Le WebSocket refuse une connexion anonyme depuis ``CONSUMER_REQUIRE_AUTH``,
mais ces routes HTTP n'exigeaient rien : sur une écoute LAN, n'importe qui
approuvait un envoi d'e-mail ou effaçait un module forgé sans compte. Le
portail suit **le même réglage que le socket** — le SPA est authentifié par la
même session, il ne voit donc aucune différence —, exige seulement un compte
(pas le personnel : c'est la définition existante du propriétaire côté
modules, ``is_owner`` reconnaît tout ``user_*``), et refuse en **401 JSON**,
jamais en redirection : l'appelant est ``fetch``, pas un navigateur. Restent
publics ``/auth/*`` (on ne peut pas exiger une session pour en ouvrir une),
``/health`` et ``/personality``.
"""
from __future__ import annotations

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect

PREFIX = "/gestion/"
API_PREFIX = "/api/"
# La barre du dashboard rafraîchit ses vitaux en ``fetch`` : une redirection
# vers la page de connexion lui rendrait du HTML en 200, qu'elle ne saurait
# pas lire. Sous ce préfixe, le refus est un 401 JSON.
GESTION_API_PREFIX = "/gestion/api/"


class GestionAuthMiddleware:
    """Exige un utilisateur authentifié et membre du personnel sur /gestion/*,
    et un utilisateur authentifié sur /api/* quand le socket l'exige aussi."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._api_blocked(request):
            return JsonResponse(
                {"error": "authentication required"}, status=401,
            )
        if self._is_blocked(request):
            if request.path.startswith(GESTION_API_PREFIX):
                return JsonResponse(
                    {"error": "authentication required"}, status=401,
                )
            return redirect(f"{settings.LOGIN_URL}?next={request.path}")
        return self.get_response(request)

    @staticmethod
    def _is_blocked(request) -> bool:
        if not getattr(settings, "DASHBOARD_REQUIRE_AUTH", False):
            return False
        if not request.path.startswith(PREFIX):
            return False
        user = getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            return True
        return not getattr(user, "is_staff", False)

    @staticmethod
    def _api_blocked(request) -> bool:
        if not getattr(settings, "CONSUMER_REQUIRE_AUTH", True):
            return False
        if not request.path.startswith(API_PREFIX):
            return False
        user = getattr(request, "user", None)
        return user is None or not getattr(user, "is_authenticated", False)
