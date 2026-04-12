"""Communication hub — central gateway for all user-facing channels.

All channels (WebSocket, Telegram, Discord, mobile…) converge to
``handle_message()`` which delegates to the pipeline processor.
"""

from communication.handler import handle_message

__all__ = ["handle_message"]
