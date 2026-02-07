from django.urls import path

from modules.views import wake, wake_now

urlpatterns = [
    path("wake", wake),
    path("wake/now", wake_now),
]
