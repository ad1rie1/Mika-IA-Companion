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

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.password_validation import (
    ValidationError, validate_password,
)
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from config.personality import personality

logger = logging.getLogger(__name__)


def health(request):
    """Public liveness probe — no auth required."""
    return JsonResponse({"status": "ok", "vtuber": personality.name})


def _no_users_yet() -> bool:
    return not get_user_model().objects.exists()


@csrf_exempt
@require_POST
def login_view(request):
    """Session login for owned frontends. CSRF-exempt for JSON/cross-origin
    clients; pair with explicit CORS origins + credentials in production."""
    try:
        data = json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        data = {}
    user = authenticate(
        request,
        username=data.get("username"),
        password=data.get("password"),
    )
    if user is None:
        return JsonResponse({"error": "invalid credentials"}, status=401)
    login(request, user)
    return JsonResponse({
        "authenticated": True,
        "username": user.get_username(),
        "display_name": _display_name(user),
        "person_id": f"user_{user.pk}",
    })


@csrf_exempt
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


def whoami(request):
    """Report the current session's authentication state.

    Also tells the client whether authentication is required at all and
    whether the bootstrap window is open, so the frontend can render the
    right screen without probing endpoints until one succeeds.
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
