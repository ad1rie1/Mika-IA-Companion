from django.urls import path

from old.backend.communication.channels.camera import CameraConsumer
from old.backend.communication.channels.web_frontend import WebSocketConsumer

websocket_urlpatterns = [
    path("ws", WebSocketConsumer.as_asgi()),
    path("ws/camera", CameraConsumer.as_asgi()),
]
