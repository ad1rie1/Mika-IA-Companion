from django.urls import path

from communication.views import get_personality, health

urlpatterns = [
    path("health", health),
    path("personality", get_personality),
]
