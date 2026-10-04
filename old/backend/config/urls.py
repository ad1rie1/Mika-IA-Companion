from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("communication.urls")),
    path("api/modules/", include("modules.urls")),
    path("", include("projects.urls")),
    path("", include("ai.urls")),
    path("gestion/", include("GestionSysteme.urls")),
    # The three includes above mount their routes at the root prefix but none
    # of them claims the bare "/", so opening the backend in a browser landed
    # on a 404. Last in the list so it only catches what nothing else did.
    path("", RedirectView.as_view(url="/gestion/", permanent=False)),
]

if settings.DEBUG:
    # Serve static files from every app's ``static/`` directory in dev.
    # Replaces the older ``static(STATIC_URL, document_root=STATIC_ROOT)``
    # which only served the collectstatic output.
    from django.contrib.staticfiles.urls import staticfiles_urlpatterns
    urlpatterns += staticfiles_urlpatterns()
