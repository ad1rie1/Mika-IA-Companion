from django.urls import path

from communication.consumers import CommunicationConsumer

websocket_urlpatterns = [
    path("ws", CommunicationConsumer.as_asgi()),
]
