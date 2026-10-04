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

**``/api/``** est l'API JSON d'administration : approbation des actions en
attente d'un projet (qui *exécute* leur charge — un envoi d'e-mail), création,
suppression et avance forcée de projets (la boucle d'outils de l'atelier :
python/node avec les droits du serveur), historique brut des prompts, commandes
de la Forge (effacer un module, lire sa source, ses journaux), réveils,
quotas, endpoints de développement du sommeil. Le portail suit **le même
réglage que le socket** (``CONSUMER_REQUIRE_AUTH``) et refuse en JSON, jamais
en redirection : l'appelant est ``fetch``, pas un navigateur.

Deux niveaux, ceux de ``identity/roles.py`` : un **anonyme** reçoit 401 ; un
**compte de conversation** — authentifié, pas ``is_staff`` — reçoit 403 sur
tout ce qui administre. Il exigeait seulement un compte : tout login créé dans
*Accès · Comptes* approuvait un envoi d'e-mail, effaçait une app forgée,
lançait un atelier et lisait les E/S brutes de l'IA. Le défaut est
**opérateur** sur tout le préfixe — une route ajoutée demain naît gatée —,
et ``CHAT_API_PREFIXES`` déclare ce qui reste ouvert à tout compte. La liste
est vide : le SPA parle à Mika par le WebSocket, et rien de ce qui est
« conversation » ne vit sous ``/api/`` aujourd'hui. Restent publics
``/auth/*`` (on ne peut pas exiger une session pour en ouvrir une),
``/health`` et ``/personality``.
"""
from __future__ import annotations

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect

from old.backend.identity.roles import is_operator_user

PREFIX = "/gestion/"
API_PREFIX = "/api/"
# La barre du dashboard rafraîchit ses vitaux en ``fetch`` : une redirection
# vers la page de connexion lui rendrait du HTML en 200, qu'elle ne saurait
# pas lire. Sous ce préfixe, le refus est un 401 JSON.
GESTION_API_PREFIX = "/gestion/api/"

# Sous ``/api/``, ce qu'un simple compte de conversation peut appeler. Tout
# le reste exige un opérateur. Déclarer ici, jamais décorer la vue : un
# préfixe absent de cette liste est gaté par défaut.
CHAT_API_PREFIXES: tuple[str, ...] = ()


class GestionAuthMiddleware:
    """Exige un utilisateur authentifié et membre du personnel sur /gestion/*,
    et — quand le socket exige un compte — un opérateur sur /api/*, hors
    préfixes déclarés « conversation »."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        refus = self._api_refus(request)
        if refus is not None:
            return refus
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
    def _api_refus(request) -> JsonResponse | None:
        """401 sans compte, 403 sans opérateur, ``None`` = laisser passer."""
        if not getattr(settings, "CONSUMER_REQUIRE_AUTH", True):
            return None
        if not request.path.startswith(API_PREFIX):
            return None
        user = getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            return JsonResponse({"error": "authentication required"}, status=401)
        if CHAT_API_PREFIXES and request.path.startswith(CHAT_API_PREFIXES):
            return None
        if is_operator_user(user):
            return None
        return JsonResponse({"error": "operator account required"}, status=403)
