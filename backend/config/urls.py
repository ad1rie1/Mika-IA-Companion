from django.conf import settings
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("communication.urls")),
    path("api/modules/", include("modules.urls")),
    path("", include("projects.urls")),
    path("", include("ai.urls")),
    path("gestion/", include("GestionSysteme.urls")),
]

if settings.DEBUG:
    # Serve static files from every app's ``static/`` directory in dev.
    # Replaces the older ``static(STATIC_URL, document_root=STATIC_ROOT)``
    # which only served the collectstatic output.
    from django.contrib.staticfiles.urls import staticfiles_urlpatterns
    urlpatterns += staticfiles_urlpatterns()
