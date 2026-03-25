from django.urls import path
from apps.users.consumers import TerminalConsumer

websocket_urlpatterns = [
    path("ws/admin/terminal/", TerminalConsumer.as_asgi()),
]
