"""HTTP endpoints: health (public), auth (login/logout/whoami), and
configuration views that require authentication.
"""

import json

from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from config.personality import personality


def health(request):
    """Public liveness probe — no auth required."""
    return JsonResponse({"status": "ok", "vtuber": personality.name})


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
    return JsonResponse({"authenticated": True, "username": user.get_username()})


def logout_view(request):
    logout(request)
    return JsonResponse({"ok": True})


def whoami(request):
    """Report the current session's authentication state."""
    if request.user.is_authenticated:
        return JsonResponse(
            {"authenticated": True, "username": request.user.get_username()}
        )
    return JsonResponse({"authenticated": False})


def get_personality(request):
    """Configuration view — requires authentication."""
    if not request.user.is_authenticated:
        return JsonResponse({"error": "authentication required"}, status=401)
    return JsonResponse({
        "name": personality.name,
        "description": personality.description,
        "greeting": personality.greeting,
    })
