# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

**Backend** (Django + Channels on Uvicorn):
```bash
pip install -r backend/requirements.txt
python run.py                    # starts on http://localhost:8000, ws://localhost:8000/ws
```
Requires `.env` at project root with `ANTHROPIC_API_KEY` (see `.env.example`).

**Frontend** (Vite + Three.js + TypeScript):
```bash
cd frontend && npm install
npm run dev        # dev server on http://localhost:3000
npm run build      # tsc && vite build → dist/
```

**Database migrations** (Django):
```bash
cd backend && python ../run.py   # or directly:
python -c "import django; django.setup()" && python backend/manage.py migrate
```

No test framework is configured yet.

## Architecture

This is a VTuber engine: a 3D avatar driven by Claude AI responses with real-time emotion mapping.

### Data Flow
1. User sends message via WebSocket (`{"type":"chat","message":"..."}`)
2. `ChatConsumer` (backend/chat/consumers.py) receives it, calls `handle_chat()`
3. `handle_chat()` fetches conversation context from `MemoryManager`, sends to Claude API via `ClaudeClient`
4. Claude's response contains an `[EMOTION:xxx]` tag — `extract_emotion()` parses it out and returns clean text + `Emotion` enum
5. Response is persisted to SQLite via Django ORM, then broadcast to all connected WebSocket clients
6. Frontend receives `{"type":"speech","text":"...","emotion":"happy"}`, updates VRM blend shapes and chat UI

### Backend (Django + Channels)

- **Entry point**: `run.py` — adds `backend/` to sys.path, configures Django, launches Uvicorn with lifespan support
- **ASGI**: `config/asgi.py` — `LifespanWrapper` handles startup (memory init, module start) and shutdown
- **WebSocket**: `chat/consumers.py` — `ChatConsumer` handles connections; `handle_chat()` is the core message processing function (used by both frontend and Telegram)
- **AI**: `ai/client.py` — `ClaudeClient` wraps `anthropic.AsyncAnthropic`; `ai/emotions.py` — regex extraction of `[EMOTION:xxx]` tags
- **Personality**: `config/personality.py` — loads `personality.yaml` from project root, generates the Claude system prompt (includes emotion tag instructions)
- **Memory**: `memory/manager.py` — `MemoryManager` with in-memory short-term list (last 20 messages) + Django ORM long-term persistence (`Conversation`, `Message`, `Memory` models)
- **Modules**: Pluggable system via `modules/base.py` (`BaseModule` ABC with `on_start/on_stop/on_message`) and `modules/manager.py` (`ModuleManager` registry). Telegram bot is the existing module.

### Frontend (Vite + Three.js + VRM)

- **Entry**: `src/main.ts` — initializes 3D scene, loads VRM model, connects WebSocket
- **3D**: `src/scene/` — `SceneManager` (renderer, camera, animation loop), `Environment` (lighting), `CameraController`
- **VTuber**: `src/vtuber/` — `VTuberModel` (VRM loading via GLTFLoader + VRM plugin), `EmotionController` (maps emotions to VRM blend shapes with smooth lerping), `AnimationMixer`
- **UI**: `src/ui/` — `ChatOverlay` (message display + input), `EmotionDisplay` (emotion indicator)
- **Network**: `src/network/WebSocketClient.ts` — event-driven client with exponential backoff reconnect

A `.vrm` file must be placed at `frontend/public/models/default.vrm`. Without it, a placeholder capsule+sphere is rendered.

## Key Conventions

- **Emotions**: `neutral`, `happy`, `sad`, `angry`, `surprised`, `thinking`, `love` — defined in `ai/emotions.py` as `Emotion` enum
- **WebSocket protocol**: JSON messages with `type` field. Client sends `{"type":"chat","message":"..."}`, server broadcasts `{"type":"speech","text":"...","emotion":"...","source":"..."}`
- **Personality is config-driven**: edit `personality.yaml` to change the VTuber's name, language, tone, traits, and greeting — no code changes needed
- **Singletons**: `claude_client`, `memory_manager`, `personality`, `module_manager` are module-level instances imported throughout the backend
- **Django settings** in `backend/config/settings.py` — `PROJECT_ROOT` points to the repo root (where `.env` and `personality.yaml` live), `BASE_DIR` points to `backend/`

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | Yes | — | Claude API key |
| `TELEGRAM_TOKEN` | No | `""` | Telegram bot token |
| `VTUBER_NAME` | No | `Mika` | Display name |
| `CLAUDE_MODEL` | No | `claude-sonnet-4-5-20250929` | Model ID |
| `API_PORT` | No | `8000` | Backend port |
| `MEMORY_SHORT_TERM_LIMIT` | No | `20` | Messages kept in context |
