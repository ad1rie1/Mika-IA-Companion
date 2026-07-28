from django.urls import path

from communication.views import (
    bootstrap_view,
    get_personality,
    health,
    login_view,
    logout_view,
    whoami,
)
from communication.debug_views import (
    force_dream,
    force_digest,
    force_journal,
    force_phase,
    sleep_status,
    wake_up,
)

urlpatterns = [
    path("health", health),
    path("personality", get_personality),
    # Session auth for the frontend (owned consumers).
    path("auth/login", login_view),
    path("auth/logout", logout_view),
    path("auth/whoami", whoami),
    # First-run only: creates the initial account, 409s forever after.
    path("auth/bootstrap", bootstrap_view),
    # Developer sleep-cycle controls. Gated by settings.DEBUG at the
    # view level — no-op in production even if the routes remain mounted.
    path("api/dev/sleep/phase", force_phase),
    path("api/dev/sleep/journal", force_journal),
    path("api/dev/sleep/dream", force_dream),
    path("api/dev/sleep/digest", force_digest),
    path("api/dev/sleep/wake", wake_up),
    path("api/dev/sleep/status", sleep_status),
]
