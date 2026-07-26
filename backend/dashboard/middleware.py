"""Optional auth gate for the admin dashboard.

The dashboard serves the whole conversation history and the config editor —
including provider API keys — over 66 URL patterns, none of which checked
authentication. Decorating each one invites the next route to be added
without the decorator, so the gate lives in one place and covers the prefix.

Off by default (`DASHBOARD_REQUIRE_AUTH`): a fresh single-user install has no
superuser yet, and locking someone out of their own admin before they can
create one is worse than the exposure on a loopback bind. Turning it on is
one env var, and `run.py` warns when the server is bound off-loopback
without it.

HTML requests get redirected to the login page; API requests get a 401 JSON
body so the front-end can react rather than parsing a redirect.
"""
from __future__ import annotations

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect

DASHBOARD_PREFIX = "/dashboard/"
API_PREFIX = "/dashboard/api/"


class DashboardAuthMiddleware:
    """Require an authenticated staff user for /dashboard/* when enabled."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._is_blocked(request):
            if request.path.startswith(API_PREFIX):
                return JsonResponse(
                    {"error": "authentication required"}, status=401,
                )
            return redirect(f"{settings.LOGIN_URL}?next={request.path}")
        return self.get_response(request)

    @staticmethod
    def _is_blocked(request) -> bool:
        if not getattr(settings, "DASHBOARD_REQUIRE_AUTH", False):
            return False
        if not request.path.startswith(DASHBOARD_PREFIX):
            return False
        user = getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            return True
        # Staff-only: a regular account created for the chat frontend must not
        # inherit access to the config editor.
        return not getattr(user, "is_staff", False)
