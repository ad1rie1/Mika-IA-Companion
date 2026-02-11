# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

**Authentication** (Choose ONE method):

*Method 1: OAuth Token* (Recommended - uses your Claude.ai login):
```bash
# Create .env at project root with:
CLAUDE_OAUTH_TOKEN=your-oauth-token-here
```

*Method 2: API Key* (Legacy - requires paid Anthropic API account):
```bash
# Create .env at project root with:
ANTHROPIC_API_KEY=sk-ant-xxxxx
```

**Backend** (Django + Channels on Uvicorn):
```bash
pip install -r backend/requirements.txt
python run.py                    # starts on http://localhost:8000, ws://localhost:8000/ws
```

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
- **WebSocket**: `chat/consumers.py` — `ChatConsumer` handles connections with per-connection `person_id`; `handle_chat()` is the core message processing function (used by frontend). Modules use `notify_ai()` instead. `handle_chat()` auto-detects available module tools and uses `chat_with_tools()` when tools are present.
- **AI**:
  - `ai/client.py` — `ClaudeClient` uses `claude_agent_sdk.query()` for Claude API communication. Two methods: `chat()` (single turn, no tools) and `chat_with_tools()` (multi-turn with MCP tools, `max_turns=10`, `permission_mode="bypassPermissions"`). Module context, emotion context, and memory context are injected into the system prompt. Reads `CLAUDE_OAUTH_TOKEN` from settings and sets `CLAUDE_CODE_OAUTH_TOKEN` env var for the SDK, or uses `ANTHROPIC_API_KEY` as fallback.
- **Emotion system** (3 layers):
  - `ai/emotion_types.py` — 29 emotions in 4 categories (positive/negative/complex/neutral), `EmotionData` dataclass, `extract_emotion()` with `[EMOTION:name:intensity]` format
  - `ai/emotion_state.py` — `PersonMood`, `GlobalMood`, `Temperament`, `MessageEmotion` dataclasses
  - `ai/emotion_engine.py` — `EmotionEngine` singleton: per-person mood, global mood, message emotion blend, decay loop, transition naturalness, opposition detection, momentum
  - `ai/emotions.py` — backward-compatibility shim re-exporting from `emotion_types.py`
- **Personality**: `config/personality.py` — loads `personality.yaml` (including `temperament` block), generates Claude system prompt with 29 emotions + intensity format
- **Memory**: `memory/manager.py` — `MemoryManager` with in-memory short-term list (last 20 messages) + Django ORM long-term persistence (`Conversation`, `Message`, `Memory`, `Souvenir`, `Connaissance` models)
- **Module plugin system**: Full plugin infrastructure via `modules/base.py` (`BaseModule` ABC) and `modules/manager.py` (`ModuleManager` singleton). Each module lives in its own subfolder with its own `models.py`. `modules/models.py` re-exports all models for Django discovery.
- **Module capabilities**: Each module can implement:
  - `instantiate()` / `shutdown()` — lifecycle (start/stop resources)
  - `worker_cron()` — periodic task, per-module `CRON_INTERVAL` (or global `CRON_TICK_INTERVAL`)
  - `return_tools()` — expose AI tools to Claude (via in-process MCP server using `claude_agent_sdk.SdkMcpTool`)
  - `notify_ai(notification)` — wake Claude with structured info, Claude decides what to do (with tools available)
  - `get_routes()` — declare HTTP endpoints, auto-mounted under `/api/modules/{name}/`
  - `get_context()` — inject text into Claude system prompt (e.g. "Tu as 3 emails non lus")
  - `on_event(event)` — react to inter-module events via event bus
  - `get_status()` — monitoring/debug introspection
  - `is_available()` — check preconditions before starting
- **AI tools**: `ModuleManager` collects tools from all modules, builds an MCP server via `create_sdk_mcp_server()`, injects it into `ClaudeAgentOptions.mcp_servers`. The SDK handles tool_use/tool_result loops automatically when `max_turns > 1`.
- **Cron scheduler**: Built into `ModuleManager`, ticks every second, dispatches `worker_cron()` per module at their own `CRON_INTERVAL`. Default global interval: `CRON_TICK_INTERVAL` (60s).
- **Email module** (`modules/email/`): IMAP/SMTP integration. On each tick (60s), checks inbox for unread emails, sends them to Haiku for triage (notify? memorize? reply?), stores `ProcessedEmail` for dedup, creates `Souvenir`/`Connaissance` memories, notifies AI via `notify_ai()`, optionally auto-replies via SMTP. Exposes `list_recent_emails` and `send_email` tools. Disabled gracefully if no IMAP config.

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

## Authentication

The VTuber engine supports **two authentication methods**:

1. **OAuth Token** (Recommended): Uses your Claude.ai OAuth token. Set `CLAUDE_OAUTH_TOKEN` in `.env`. The system internally converts this to `CLAUDE_CODE_OAUTH_TOKEN` for the Claude Agent SDK.
2. **API Key** (Legacy): Set `ANTHROPIC_API_KEY` in `.env`. Requires a paid Anthropic API account.

The client will try OAuth token first, then fall back to API key if available.

**Technical details:**
- OAuth tokens start with `sk-ant-oat01-` and are session tokens from Claude.ai
- API keys start with `sk-ant-api...` and require a paid Anthropic account
- The `claude_agent_sdk` expects `CLAUDE_CODE_OAUTH_TOKEN` for OAuth authentication
- The backend automatically handles the conversion from `CLAUDE_OAUTH_TOKEN` → `CLAUDE_CODE_OAUTH_TOKEN`

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CLAUDE_OAUTH_TOKEN` | No* | `""` | Claude OAuth token (*required if not using API key) |
| `ANTHROPIC_API_KEY` | No* | `""` | Claude API key (*required if not using OAuth token) |
| `TELEGRAM_TOKEN` | No | `""` | Telegram bot token |
| `VTUBER_NAME` | No | `Mika` | Display name |
| `CLAUDE_MODEL` | No | `claude-sonnet-4-5-20250929` | Model ID |
| `API_PORT` | No | `8000` | Backend port |
| `MEMORY_SHORT_TERM_LIMIT` | No | `20` | Messages kept in context |
| `EMOTION_DECAY_RATE` | No | `0.02` | Emotion intensity lost per second |
| `EMOTION_MOOD_SHIFT_RATE` | No | `0.01` | How fast mood adapts |
| `CRON_TICK_INTERVAL` | No | `60` | Scheduler tick interval in seconds |
| `IMAP_HOST` | No | `""` | IMAP server hostname |
| `IMAP_PORT` | No | `993` | IMAP server port (SSL) |
| `IMAP_USER` | No | `""` | IMAP login email |
| `IMAP_PASSWORD` | No | `""` | IMAP login password |
| `SMTP_HOST` | No | `""` | SMTP server hostname |
| `SMTP_PORT` | No | `587` | SMTP server port (TLS) |
| `SMTP_USER` | No | `""` | SMTP login email |
| `SMTP_PASSWORD` | No | `""` | SMTP login password |
