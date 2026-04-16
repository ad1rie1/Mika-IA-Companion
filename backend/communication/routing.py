from django.urls import path

from communication.channels.camera import CameraConsumer
from communication.channels.web_frontend import WebSocketConsumer

websocket_urlpatterns = [
    path("ws", WebSocketConsumer.as_asgi()),
    path("ws/camera", CameraConsumer.as_asgi()),
]
