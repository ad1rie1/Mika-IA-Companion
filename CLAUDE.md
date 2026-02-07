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
3. `handle_chat()` fetches conversation context from `MemoryManager` + emotional state from `EmotionEngine`
4. Claude's response contains an `[EMOTION:name:intensity]` tag — `extract_emotion()` parses it into `EmotionData` (emotion + intensity)
5. `EmotionEngine.process_emotion()` applies transitions, momentum, opposition, and bleeds into global mood
6. Response is persisted to SQLite via Django ORM, then broadcast to all connected WebSocket clients with full emotion state
7. Frontend receives `{"type":"speech","text":"...","emotion":"excited","emotion_intensity":0.75,"emotion_state":{...}}`, updates VRM blend shapes and chat UI

### Backend (Django + Channels)

- **Entry point**: `run.py` — adds `backend/` to sys.path, configures Django, launches Uvicorn with lifespan support
- **ASGI**: `config/asgi.py` — `LifespanWrapper` handles startup (memory init, emotion engine init, module start) and shutdown
- **WebSocket**: `chat/consumers.py` — `ChatConsumer` handles connections with per-connection `person_id`; `handle_chat()` is the core message processing function (used by frontend, Telegram, and wake module)
- **AI**: `ai/client.py` — `ClaudeClient` wraps `anthropic.AsyncAnthropic`, accepts `emotion_context` for system prompt injection
- **Emotion system** (3 layers):
  - `ai/emotion_types.py` — 29 emotions in 4 categories (positive/negative/complex/neutral), `EmotionData` dataclass, `extract_emotion()` with `[EMOTION:name:intensity]` format
  - `ai/emotion_state.py` — `PersonMood`, `GlobalMood`, `Temperament`, `MessageEmotion` dataclasses
  - `ai/emotion_engine.py` — `EmotionEngine` singleton: per-person mood, global mood, message emotion blend, decay loop, transition naturalness, opposition detection, momentum
  - `ai/emotions.py` — backward-compatibility shim re-exporting from `emotion_types.py`
- **Personality**: `config/personality.py` — loads `personality.yaml` (including `temperament` block), generates Claude system prompt with 29 emotions + intensity format
- **Memory**: `memory/manager.py` — `MemoryManager` with in-memory short-term list (last 20 messages) + Django ORM long-term persistence (`Conversation`, `Message`, `Memory`, `Souvenir`, `Connaissance` models)
- **Modules**: Pluggable system via `modules/base.py` (`BaseModule` ABC) and `modules/manager.py` (`ModuleManager` registry). Modules: Telegram bot, Wake, Email.

### Emotion System (3 layers)

1. **Per-person mood** (`PersonMood`): how the VTuber feels about each specific person. If someone angers her, she's annoyed at THEM but not others. Tracked in `EmotionEngine.person_moods` dict keyed by `person_id`.
2. **Global mood** (`GlobalMood`): overall emotional state affecting all conversations. Strong emotions bleed into global via `temperament.global_bleed` factor.
3. **Message emotion** (`MessageEmotion`): computed blend (60% person + 40% global) sent to Claude and frontend. Not stored — recalculated per message.

**Mechanics:**
- Emotions start strong then decay over time (background asyncio loop, `EMOTION_DECAY_RATE` per second × `temperament.recovery_speed`)
- Dialogues can reinforce (same emotion), oppose (positive vs negative → reduces then inverts), or annulate (strong neutral → reset to default mood)
- Momentum builds with reinforcement and resists abrupt changes
- Temperament (in `personality.yaml`) controls: `volatility`, `intensity_base`, `recovery_speed`, `default_mood`, `global_bleed`

### Frontend (Vite + Three.js + VRM)

- **Entry**: `src/main.ts` — initializes 3D scene, loads VRM model, connects WebSocket
- **3D**: `src/scene/` — `SceneManager` (renderer, camera, animation loop), `Environment` (lighting), `CameraController`
- **VTuber**: `src/vtuber/` — `VTuberModel` (VRM loading via GLTFLoader + VRM plugin), `EmotionController` (maps emotions to VRM blend shapes with smooth lerping), `AnimationMixer`
- **UI**: `src/ui/` — `ChatOverlay` (message display + input), `EmotionDisplay` (emotion indicator)
- **Network**: `src/network/WebSocketClient.ts` — event-driven client with exponential backoff reconnect

A `.vrm` file must be placed at `frontend/public/models/default.vrm`. Without it, a placeholder capsule+sphere is rendered.

## Key Conventions

- **Emotions** (29 total): `neutral` | `happy`, `excited`, `love`, `proud`, `grateful`, `playful`, `amused`, `hopeful`, `relieved` | `sad`, `angry`, `scared`, `disgusted`, `frustrated`, `lonely`, `anxious`, `bored`, `jealous` | `surprised`, `thinking`, `confused`, `embarrassed`, `nostalgic`, `dreamy`, `determined`, `mischievous`, `curious`, `melancholic` — defined in `ai/emotion_types.py` as `Emotion` enum
- **Emotion tag format**: `[EMOTION:name:intensity]` (e.g. `[EMOTION:excited:0.8]`). Legacy `[EMOTION:name]` still supported (defaults to intensity 0.7)
- **WebSocket protocol**: JSON messages with `type` field. Client sends `{"type":"chat","message":"..."}`, server broadcasts `{"type":"speech","text":"...","emotion":"...","emotion_intensity":0.75,"emotion_state":{...},"source":"..."}`
- **Person identification**: each WebSocket connection gets a UUID `person_id`; Telegram uses `tg_{user_id}`; clients can pass `person_id` in chat messages
- **Personality is config-driven**: edit `personality.yaml` to change the VTuber's name, language, tone, traits, greeting, and temperament — no code changes needed
- **Singletons**: `claude_client`, `memory_manager`, `emotion_engine`, `personality`, `module_manager` are module-level instances imported throughout the backend
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
| `EMOTION_DECAY_RATE` | No | `0.02` | Emotion intensity lost per second |
| `EMOTION_MOOD_SHIFT_RATE` | No | `0.01` | How fast mood adapts |
