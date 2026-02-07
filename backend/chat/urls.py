from django.urls import path

from chat.views import get_personality, health

urlpatterns = [
    path("health", health),
    path("personality", get_personality),
]
