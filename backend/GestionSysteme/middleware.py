"""Portail d'authentification optionnel pour ``/gestion/``.

Cette interface sert tout l'historique de conversation et édite les clés d'API
des fournisseurs. Décorer chaque vue inviterait la prochaine route à oublier le
décorateur : le contrôle vit donc en un seul endroit et couvre le préfixe.

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
"""
from __future__ import annotations

from django.conf import settings
from django.shortcuts import redirect

PREFIX = "/gestion/"


class GestionAuthMiddleware:
    """Exige un utilisateur authentifié et membre du personnel sur /gestion/*."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._is_blocked(request):
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
