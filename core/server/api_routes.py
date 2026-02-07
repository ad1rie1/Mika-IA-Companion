import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from core.ai.claude_client import ClaudeClient
from core.ai.emotion_engine import Emotion
from core.config import personality
from core.memory.memory_manager import MemoryManager
from core.server.ws_handler import manager

logger = logging.getLogger(__name__)

router = APIRouter()
claude = ClaudeClient()
memory = MemoryManager()

MAX_MESSAGE_LENGTH = 2000


@router.get("/health")
async def health():
    return {"status": "ok", "vtuber": personality.name}


@router.get("/personality")
async def get_personality():
    return {
        "name": personality.name,
        "description": personality.description,
        "greeting": personality.greeting,
    }


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)

    # Send greeting on connect
    await websocket.send_text(
        json.dumps(
            {
                "type": "speech",
                "text": personality.greeting,
                "emotion": Emotion.HAPPY.value,
            },
            ensure_ascii=False,
        )
    )

    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)

            if data.get("type") == "chat":
                message = data.get("message", "")
                if not isinstance(message, str) or not message.strip():
                    continue
                if len(message) > MAX_MESSAGE_LENGTH:
                    message = message[:MAX_MESSAGE_LENGTH]
                await handle_chat(message.strip(), source="frontend")

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error("WebSocket error: %s", e)
        manager.disconnect(websocket)


async def handle_chat(message: str, source: str = "frontend"):
    """Process a chat message from any source and broadcast response."""
    try:
        history = memory.get_conversation_context()
        response_text, emotion = await claude.chat(message, history)
    except Exception:
        logger.exception("Claude API error while processing message")
        response_text = "Oups, j'ai eu un petit bug... Tu peux réessayer ?"
        emotion = Emotion.SAD

    await memory.add_message("user", message, source=source)
    await memory.add_message("assistant", response_text)

    await manager.broadcast(
        {
            "type": "speech",
            "text": response_text,
            "emotion": emotion.value,
            "source": source,
        }
    )

    return response_text, emotion
