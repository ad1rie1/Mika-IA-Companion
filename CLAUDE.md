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
2. `WebSocketConsumer` (backend/communication/channels/web_frontend.py) receives it, calls `handle_message()`
3. `handle_message()` (backend/communication/handler.py) delegates to `pipeline.processor.process_message()` which runs the full pipeline:
   - **Context assembly** (`pipeline/context.py`): gathers memory context, emotion context, module context, conversation history, and available tools
   - **Prompt building** (`pipeline/prompt.py`): assembles system prompt from personality + contextual layers, formats conversation
   - **AI call** (`ai/client.py`): routes to configured provider via `ai_router`, with or without MCP tools
   - **Emotion processing**: `extract_emotion()` parses `[EMOTION:name:intensity]` tag, `EmotionEngine.process_emotion()` applies transitions/momentum/opposition/bleed
   - **Persistence**: saves messages to memory
   - **Broadcast**: sends response + emotion state to all WebSocket clients
4. Frontend receives `{"type":"speech","text":"...","emotion":"excited","emotion_intensity":0.75,"emotion_state":{...}}`, updates VRM blend shapes and chat UI

The same pipeline is used by `modules/manager.py` (`notify_ai`) and `conscience/engine.py` (`_act`) — all three entry points delegate to `process_message()` instead of duplicating the flow.

### Backend (Django + Channels)

- **Entry point**: `run.py` — adds `backend/` to sys.path, configures Django, launches Uvicorn with lifespan support
- **ASGI**: `config/asgi.py` — `LifespanWrapper` handles startup (memory init, emotion engine init, conscience init, module start) and shutdown
- **Communication hub** (`communication/`): central gateway for ALL user-facing channels. `handle_message()` (`communication/handler.py`) is the unified entry point — all channels converge here before delegating to `pipeline.processor.process_message()`.
  - `communication/channels/web_frontend.py` — `WebSocketConsumer` (Django Channels WebSocket, browser/frontend)
  - `communication/channels/telegram.py` — `TelegramModule` (Telegram bot, registered as a module for lifecycle/cron/tools)
  - `communication/channels/` — future channels: Discord, mobile app, etc.
  - `communication/handler.py` — `handle_message()` unified entry point
  - `communication/routing.py` — WebSocket URL patterns
  - `communication/urls.py` / `views.py` — HTTP endpoints (health, personality)
- **Pipeline** (conversation orchestration):
  - `pipeline/processor.py` — `process_message()` is the single entry point for all AI interactions. Orchestrates the steps below. Returns `SpeechOutput`.
  - `pipeline/context.py` — `gather_context()` assembles `ConversationContext` (memory + emotion + modules + tools) for a conversation turn
  - `pipeline/prompt.py` — `build_system_prompt()` (personality + contextual layers) and `format_conversation()` (history + message formatting)
  - `pipeline/response.py` — `call_ai_and_parse()` builds prompt, calls AI, extracts emotion from response
  - `pipeline/broadcast.py` — `broadcast_to_websocket()`, `emit_communication_event()`, `persist_to_memory()` — side-effects after AI processing
- **AI (multi-provider)**:
  - `ai/providers/` — `ClaudeProvider` (claude_agent_sdk), `OpenAIProvider` (openai package, supports any OpenAI-compatible API via `base_url`), `OllamaProvider` (local models via HTTP). Providers are lazy-instantiated.
  - `ai/router.py` — `AIRole` enum (6 roles: conversation, conversation_tools, email_triage, signal_interpretation, memory_extraction, validity_check) + `AIRouter` singleton (`ai_router`). Each role maps to a `provider:model` pair configured via `AI_ROLE_*` env vars. Defaults to Claude for backward compatibility. All AI calls pass through the router which provides unified logging (timing, role, provider, model, response size).
  - `ai/client.py` — `AIClient` with `complete()` (routes via `ai_router` for any provider). Pure call layer — receives ready-made prompts, returns raw text.
  - `ai/tool_client.py` — `complete_with_tools()` (Claude-only MCP tool support, uses `claude_agent_sdk.query()` with multi-turn tool_use/tool_result loops). Separated from simple completion due to different flow (streaming, bidirectional).
- **Emotion system** (`emotion/`, standalone Django app — 3 layers):
  - `emotion/types.py` — 29 emotions in 4 categories (positive/negative/complex/neutral), `EmotionData` dataclass, `extract_emotion()` with `[EMOTION:name:intensity]` format
  - `emotion/state.py` — `PersonMood`, `GlobalMood`, `Temperament`, `MessageEmotion` dataclasses
  - `emotion/engine.py` — `EmotionEngine` singleton: per-person mood, global mood, message emotion blend, decay loop, transition naturalness, opposition detection, momentum
  - Backward-compat shims in `conscience/emotion_*.py` re-export from `emotion/`
- **Personality**: `config/personality.py` — loads `personality.yaml` (including `temperament` block), generates Claude system prompt with 29 emotions + intensity format
- **Memory** (`memory/`):
  - `memory/manager.py` — `MemoryManager` singleton: unified interface. In-memory short-term list (last 20 messages) + Django ORM long-term persistence
  - `memory/models.py` — Django ORM models (`Conversation`, `Message`, `Memory`, `Souvenir`, `Connaissance`, `EmotionSnapshot`, `EmotionalSummary`, `ConsolidationLog`)
  - `memory/storage/` — ChromaDB vector store (`vector_store.py`) and background consolidation loop (`consolidator.py`)
  - `memory/extraction/` — AI-powered extraction of souvenirs + connaissances from conversations (`extractor.py`)
  - `memory/retrieval/` — semantic search + reranking with person_id boost and recency bias (`retriever.py`)
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
### Conscience Layer (`conscience/`)

The Conscience is Mika's **waking brain** — a layer above modules that observes, interprets, memorizes, and decides. It is NOT a module; it's a Django app at the same level as `ai/`, `memory/`, `communication/`. The emotion system has been extracted to its own `emotion/` app.

**Metaphor**: Conscience = waking state, Consolidator = dreaming state.

- **Engine**: `conscience/engine.py` — `ConscienceEngine` singleton: decision loop (every 30s), memory maintenance, action execution. Wired to the event bus via `module_manager.set_conscience()`. Uses `pipeline.processor.process_message()` for AI interactions.
- **Scoring**: `conscience/scoring.py` — pure functions for decision scoring (`compute_decision_score()`, `check_time_trigger()`). Extracted for testability — no side effects, no DB, no async.
- **Interpreter**: `conscience/interpreter.py` — `SignalInterpreter` classifies events. Heuristic fast-path for known events (`chat.message`, `chat.connect`), Claude Haiku for rich events (emails, RSS).
- **MemoryBridge**: `conscience/memory_bridge.py` — R/W interface to long-term memory. Can read (vector search, retrieve souvenirs), create (new souvenirs from signals), modify (boost/reduce importance), and invalidate (contradict connaissances). Activates `check_connaissance_validity()` from `memory/extraction/extractor.py`.
- **Models**: `conscience/models.py` — `Observation` (interpreted signal buffer), `ConscienceLog` (decision audit trail), `ScheduledAction` (deferred actions).

**Decision scoring** (unified, replaces 4 hardcoded triggers):
- Observation pertinence (0.4 weight) + accumulated urgency (0.3) + mood overflow (0.25) + idle time (0.3) + time greeting (0.35). Threshold: 0.5.

**Memory powers**: The Conscience can modify memory without speaking — boost souvenir importance for pertinent signals, check and invalidate contradicted connaissances, create souvenirs directly from interpreted observations.

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

- **Entry**: `src/main.ts` — initializes 3D scene, loads VRM model, connects WebSocket, wires TTS + lip-sync + emotions
- **3D**: `src/scene/` — `SceneManager` (renderer, camera, animation loop), `Environment` (lighting), `CameraController`
- **VTuber**: `src/vtuber/` — `VTuberModel` (VRM loading via GLTFLoader + VRM plugin), `EmotionController` (maps all 29 emotions to VRM blend shapes with intensity-based weighting and smooth lerping), `AnimationMixer` (blink + breathing)
- **Audio**: `src/audio/` — `TTSService` (Web Speech API TTS with emotion-based pitch/rate modulation, speech queue), `LipSyncController` (text-driven phoneme-based lip sync with French vowel/consonant mapping, audio-driven mode ready for future Web Audio integration)
- **UI**: `src/ui/` — `ChatOverlay` (message display + input), `EmotionDisplay` (29 emotion labels in French with intensity %)
- **Network**: `src/network/WebSocketClient.ts` — event-driven client with exponential backoff reconnect

**Speech flow**: WebSocket `speech` event → validate emotion (29 names) → `EmotionController.setEmotion(name, intensity)` scales blend shapes by intensity → `TTSService.speak(text, emotion)` modulates pitch/rate per emotion → `LipSyncController` animates mouth shapes from French phoneme approximation → `AnimationMixer` handles blink/breathing independently.

A `.vrm` file must be placed at `frontend/public/models/default.vrm`. Without it, a placeholder capsule+sphere is rendered.

## Key Conventions

- **Emotions** (29 total): `neutral` | `happy`, `excited`, `love`, `proud`, `grateful`, `playful`, `amused`, `hopeful`, `relieved` | `sad`, `angry`, `scared`, `disgusted`, `frustrated`, `lonely`, `anxious`, `bored`, `jealous` | `surprised`, `thinking`, `confused`, `embarrassed`, `nostalgic`, `dreamy`, `determined`, `mischievous`, `curious`, `melancholic` — defined in `emotion/types.py` as `Emotion` enum
- **Emotion tag format**: `[EMOTION:name:intensity]` (e.g. `[EMOTION:excited:0.8]`). Legacy `[EMOTION:name]` still supported (defaults to intensity 0.7)
- **WebSocket protocol**: JSON messages with `type` field. Client sends `{"type":"chat","message":"..."}`, server broadcasts `{"type":"speech","text":"...","emotion":"...","emotion_intensity":0.75,"emotion_state":{...},"source":"..."}`
- **Person identification**: each WebSocket connection gets a UUID `person_id`; Telegram uses `tg_{user_id}`; clients can pass `person_id` in chat messages
- **Personality is config-driven**: edit `personality.yaml` to change the VTuber's name, language, tone, traits, greeting, and temperament — no code changes needed
- **Singletons**: `ai_client` (`ai.client`), `memory_manager` (`memory.manager`), `emotion_engine` (`emotion.engine`), `personality` (`config.personality`), `module_manager` (`modules.manager`) are module-level instances imported throughout the backend
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
| `CLAUDE_MODEL` | No | `claude-opus-4-6` | Default Claude model (heavy) |
| `CLAUDE_MODEL_LIGHT` | No | `claude-sonnet-4-5` | Default Claude model (light) |
| `OPENAI_API_KEY` | No | `""` | OpenAI API key (only if using OpenAI provider) |
| `OPENAI_BASE_URL` | No | `""` | Custom OpenAI-compatible endpoint URL |
| `OLLAMA_BASE_URL` | No | `http://localhost:11434` | Ollama server URL |
| `AI_ROLE_CONVERSATION` | No | `claude:CLAUDE_MODEL` | Provider:model for main chat |
| `AI_ROLE_CONVERSATION_TOOLS` | No | `claude:CLAUDE_MODEL` | Provider:model for chat with tools (Claude-only) |
| `AI_ROLE_EMAIL_TRIAGE` | No | `claude:CLAUDE_MODEL_LIGHT` | Provider:model for email analysis |
| `AI_ROLE_SIGNAL_INTERPRETATION` | No | `claude:CLAUDE_MODEL_LIGHT` | Provider:model for signal interpretation |
| `AI_ROLE_MEMORY_EXTRACTION` | No | `claude:CLAUDE_MODEL_LIGHT` | Provider:model for memory extraction |
| `AI_ROLE_VALIDITY_CHECK` | No | `claude:CLAUDE_MODEL_LIGHT` | Provider:model for knowledge validation |
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
| `CONSCIENCE_DECISION_INTERVAL` | No | `30` | Seconds between conscience decision cycles |
| `CONSCIENCE_COOLDOWN_SECONDS` | No | `300` | Min seconds between conscience actions |
| `CONSCIENCE_ACT_THRESHOLD` | No | `0.5` | Score threshold to trigger conscience action |
