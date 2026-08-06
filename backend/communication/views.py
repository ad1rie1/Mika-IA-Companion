"""HTTP endpoints: health (public), auth (login/logout/whoami/bootstrap), and
configuration views that require authentication.

The frontend is an *authenticated* surface: it is the one channel where Mika
can be certain who she is talking to, and the whole identity-certainty model
(``identity/trust.py``) hangs off that guarantee. Everything else — Telegram,
public rooms — has to earn recognition claim by claim.

That leaves the first-run problem: a fresh clone has no user, and refusing
every connection until someone runs ``createsuperuser`` in a terminal is a
bad first five minutes. ``bootstrap_view`` closes the gap — it creates the
first account and *only* the first, disabling itself the moment one exists.
"""

import json
import logging
import time

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.password_validation import (
    ValidationError, validate_password,
)
from django.http import JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from config.personality import personality

logger = logging.getLogger(__name__)

# Fenêtre glissante sur les échecs de connexion — même forme que le rate limit
# du consumer WebSocket (`channels/web_frontend.py`), qui compte déjà jusqu'aux
# frames de contrôle. Sans plafond, `/auth/login` est un oracle de mot de passe
# à débit illimité : le CSRF ne s'y oppose pas (un GET sur `/auth/whoami`
# distribue le jeton), et le compte visé est le superuser de `bootstrap_view`,
# qui donne à la fois `ChannelTrust.AUTHENTICATED` — donc la divulgation
# intégrale de la mémoire par personne — et `/gestion/`, donc les clés de
# providers. Sur `API_HOST=0.0.0.0`, c'est ouvert à tout le réseau local.
LOGIN_MAX_FAILURES = 5
LOGIN_WINDOW_SECONDS = 60.0

# (ip source, identifiant tenté) -> horodatages monotones des échecs récents.
# La clé porte les deux : sur l'IP seule, un tiers du réseau verrouillerait le
# compte du propriétaire en cinq requêtes ; sur l'identifiant seul, changer de
# nom d'utilisateur suffirait à contourner. Le couple ferme l'oracle — deviner
# un mot de passe impose de garder le même identifiant — sans offrir ce déni de
# service. Process-local et délibérément non persisté : le compteur n'est pas
# une sanction, juste un débit.
_login_failures: dict[tuple[str, str], list[float]] = {}

# Au-delà, on jette les entrées que la fenêtre ne protège plus. Un attaquant
# faisant tourner les identifiants crée une clé par tentative, et une entrée
# plus vieille que la fenêtre ne répond plus à rien.
_LOGIN_FAILURES_MAX_TRACKED = 1000


def health(request):
    """Public liveness probe — no auth required."""
    return JsonResponse({"status": "ok", "vtuber": personality.name})


def _no_users_yet() -> bool:
    return not get_user_model().objects.exists()


def _login_failure_key(request, username) -> tuple[str, str]:
    """Identifie la tentative : adresse source + identifiant visé.

    L'adresse est celle que voit le serveur, pas ``X-Forwarded-For`` — cet
    en-tête vient du client, et le lire ici rendrait le plafond contournable
    d'un header. Le backend écoute sur loopback par défaut ; derrière un
    reverse proxy, la limite se pose au niveau du proxy.

    L'identifiant est replié en casse : ``authenticate`` est sensible à la
    casse, donc varier « Owner » / « owner » ne devine aucun mot de passe mais
    ferait sinon repartir le compteur à zéro à chaque fois.
    """
    name = username if isinstance(username, str) else ""
    return (request.META.get("REMOTE_ADDR") or "?", name.strip().casefold()[:150])


def _prune_login_failures(now: float) -> None:
    if len(_login_failures) <= _LOGIN_FAILURES_MAX_TRACKED:
        return
    cutoff = now - LOGIN_WINDOW_SECONDS
    for key, stamps in list(_login_failures.items()):
        if stamps[-1] < cutoff:
            _login_failures.pop(key, None)


def _recent_login_failures(key: tuple[str, str]) -> list[float]:
    """Les échecs encore dans la fenêtre, l'entrée nettoyée au passage."""
    window_start = time.monotonic() - LOGIN_WINDOW_SECONDS
    recent = [t for t in _login_failures.get(key, ()) if t >= window_start]
    if recent:
        _login_failures[key] = recent
    else:
        _login_failures.pop(key, None)
    return recent


def _record_login_failure(key: tuple[str, str]) -> int:
    """Compte un échec et renvoie le total sur la fenêtre."""
    now = time.monotonic()
    recent = _recent_login_failures(key)
    recent.append(now)
    _login_failures[key] = recent
    _prune_login_failures(now)
    return len(recent)


@require_POST
def login_view(request):
    """Session login for owned frontends.

    CSRF-protected like every other mutating endpoint: the client picks up the
    token from the cookie ``whoami`` sets and echoes it in ``X-CSRFToken``.

    Plafonné à ``LOGIN_MAX_FAILURES`` échecs par fenêtre : c'est le seul
    endpoint qui distribue une identité, et il le faisait sans rien compter.
    Un succès referme la fenêtre — un utilisateur distrait qui finit par
    retrouver son mot de passe ne traîne pas de compteur derrière lui.
    """
    try:
        data = json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        data = {}
    key = _login_failure_key(request, data.get("username"))
    if len(_recent_login_failures(key)) >= LOGIN_MAX_FAILURES:
        logger.warning(
            "Connexion refusee (trop de tentatives) pour %r depuis %s", key[1], key[0],
        )
        response = JsonResponse(
            {"error": "trop de tentatives — reessaie dans une minute"}, status=429,
        )
        response["Retry-After"] = str(int(LOGIN_WINDOW_SECONDS))
        return response

    user = authenticate(
        request,
        username=data.get("username"),
        password=data.get("password"),
    )
    if user is None:
        failures = _record_login_failure(key)
        # Un échec isolé est un utilisateur distrait ; une série est une
        # attaque, et rien ne les distinguait dans les journaux.
        log = logger.warning if failures >= LOGIN_MAX_FAILURES else logger.info
        log(
            "Echec de connexion pour %r depuis %s (%d/%d sur la fenetre)",
            key[1], key[0], failures, LOGIN_MAX_FAILURES,
        )
        return JsonResponse({"error": "invalid credentials"}, status=401)
    _login_failures.pop(key, None)
    login(request, user)
    return JsonResponse({
        "authenticated": True,
        "username": user.get_username(),
        "display_name": _display_name(user),
        "person_id": f"user_{user.pk}",
    })


@require_POST
def bootstrap_view(request):
    """Create the very first account, then permanently disable itself.

    Open only while the user table is empty — the window between "just
    cloned the repo" and "has an account". Once anyone exists this returns
    409 forever, so it cannot be used to add a second account.
    """
    if not _no_users_yet():
        return JsonResponse(
            {"error": "un compte existe deja — utilise /auth/login"}, status=409,
        )

    try:
        data = json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        data = {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        return JsonResponse({"error": "username et password requis"}, status=400)

    try:
        validate_password(password)
    except ValidationError as exc:
        return JsonResponse({"error": " ".join(exc.messages)}, status=400)

    User = get_user_model()
    # Staff + superuser: the first account is the owner's, and it doubles as
    # the dashboard login (see DASHBOARD_REQUIRE_AUTH).
    user = User.objects.create_superuser(
        username=username, password=password,
        **({"email": data.get("email") or ""} if hasattr(User, "email") else {}),
    )
    login(request, user)
    logger.info("Bootstrap account created: %s", username)
    return JsonResponse({
        "authenticated": True,
        "username": user.get_username(),
        "display_name": _display_name(user),
        "person_id": f"user_{user.pk}",
        "created": True,
    })


def logout_view(request):
    logout(request)
    return JsonResponse({"ok": True})


@ensure_csrf_cookie
def whoami(request):
    """Report the current session's authentication state.

    Also tells the client whether authentication is required at all and
    whether the bootstrap window is open, so the frontend can render the
    right screen without probing endpoints until one succeeds.

    Carries ``@ensure_csrf_cookie`` because it is the client's *first* call:
    login and bootstrap are CSRF-protected POSTs, and without the cookie
    being set here there would be no token for them to echo back.
    """
    from django.conf import settings

    payload = {
        "authenticated": False,
        "auth_required": bool(getattr(settings, "CONSUMER_REQUIRE_AUTH", True)),
        "needs_bootstrap": _no_users_yet(),
    }
    if request.user.is_authenticated:
        payload.update({
            "authenticated": True,
            "username": request.user.get_username(),
            "display_name": _display_name(request.user),
            "person_id": f"user_{request.user.pk}",
        })
    return JsonResponse(payload)


def _display_name(user) -> str:
    """The name Mika should use — full name when set, else the username."""
    full = (getattr(user, "get_full_name", lambda: "")() or "").strip()
    return full or user.get_username()


def get_personality(request):
    """Configuration view — requires authentication."""
    if not request.user.is_authenticated:
        return JsonResponse({"error": "authentication required"}, status=401)
    return JsonResponse({
        "name": personality.name,
        "description": personality.description,
        "greeting": personality.greeting,
    })
