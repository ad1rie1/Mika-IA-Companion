# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

**Authentication** (choose ONE method):

*Method 1: OAuth Token* (recommended — uses your Claude.ai login):
```bash
# Create .env at project root with:
CLAUDE_OAUTH_TOKEN=your-oauth-token-here
```

*Method 2: API Key* (requires paid Anthropic account):
```bash
ANTHROPIC_API_KEY=sk-ant-xxxxx
```

**Backend** (Django + Channels on Uvicorn):
```bash
pip install -r backend/requirements.txt
python run.py                    # http://localhost:8000, ws://localhost:8000/ws
```

**Frontend** (Vite + Three.js + TypeScript):
```bash
cd frontend && npm install
npm run dev        # http://localhost:3000
npm run build
```

**Database migrations**:
```bash
cd backend && python manage.py migrate
```

**Tests** (pytest + pytest-django):
```bash
python -m pytest backend/tests/                    # full suite
python -m pytest backend/tests/test_perception.py  # single file
```

## Architecture

VTuber engine: a 3D avatar driven by Claude AI responses with real-time emotion mapping, evolving self-concept, theory of mind, and intrinsic drives.

### Core model: Perception → Router → Pipeline

Every input entering Mika (chat text, Telegram, internal conscience initiatives, module notifications, future camera/audio/files) becomes a `Perception`. A central router dispatches it based on `Intent`; the processor does the AI call only when a response is needed. Silence is a valid outcome.

```
Sources (WebSocket, Telegram, Conscience, Modules, future: Camera/Audio/File/Sensor)
   │  each source builds a Perception
   ▼
pipeline.router.perceive(Perception)
   ├─ save raw media (if non-text)
   ├─ run modality preprocessors (vision/audio/files → text)
   └─ dispatch by Intent
        ├─ REQUEST_RESPONSE  → process_message(perception)  → broadcast answer
        ├─ INTERNAL_TRIGGER  → process_message(perception)  → broadcast, no event
        └─ OBSERVATION       → module_manager.emit_event    → conscience decides later
```

### Data Flow (text chat turn)

1. Client sends `{"type":"chat","message":"...","person_id":"...","attachments":[...]}` via WebSocket
2. `WebSocketConsumer.receive()` ([backend/communication/channels/web_frontend.py](backend/communication/channels/web_frontend.py)) validates, builds a `Perception` (text-only or mixed), calls `perceive()`
3. `pipeline.router.perceive()` saves any raw media, runs preprocessors to transform image/audio/file parts into text descriptions, then routes by intent
4. `pipeline.processor.process_message(perception)` runs the full pipeline:
   - **Context assembly** ([pipeline/context.py](backend/pipeline/context.py)): memory + emotion + drives + modules + self-concept + per-person context
   - **Prompt building** ([pipeline/prompt.py](backend/pipeline/prompt.py)): personality → self-concept → person-context → modules → emotion → memory
   - **AI call** ([pipeline/response.py](backend/pipeline/response.py)): wrapped in `asyncio.wait_for(timeout=AI_CALL_TIMEOUT)`; routes to provider via `ai_router`
   - **Emotion processing**: `[EMOTION:name:intensity]` tag extracted, applied as an impulse on the person's PAD oscillator
   - **Persistence**: user Message + assistant Message saved with `attachments_meta`
   - **Broadcast**: response + emotion state + blend to all WebSocket clients
5. Frontend receives `{"type":"speech","text":"...","emotion":"excited","emotion_intensity":0.75,"emotion_blend":[...],"emotion_state":{...}}`, updates VRM blend shapes and chat UI

On AI error or timeout: fallback text returned, **no emotion impulse toward the user**, **no persistence**, **no chat.message event** — a failed exchange is not a real exchange.

### Backend layout

- **Entry point**: [run.py](run.py) — adds `backend/` to sys.path, configures Django, launches Uvicorn
- **ASGI** [config/asgi.py](backend/config/asgi.py): `LifespanWrapper` runs startup (memory → emotion → conscience → modules) and shutdown
- **Communication channels** ([communication/](backend/communication/)): adapters that translate external inputs into `Perception` objects and hand them to `pipeline.router.perceive()`. No shared legacy handler — each channel builds its own Perception.
  - [communication/channels/web_frontend.py](backend/communication/channels/web_frontend.py) — `WebSocketConsumer`, greeting routed through `perceive()` as `INTERNAL_TRIGGER`
  - [communication/channels/telegram.py](backend/communication/channels/telegram.py) — Telegram module, builds text Perceptions
  - [communication/routing.py](backend/communication/routing.py), [communication/urls.py](backend/communication/urls.py), [communication/views.py](backend/communication/views.py) — WS routing + HTTP health/personality endpoints
- **Pipeline** ([pipeline/](backend/pipeline/)):
  - [pipeline/perception.py](backend/pipeline/perception.py) — `Perception`, `Part`, `Modality`, `Intent`, and constructors (`from_text`, `from_internal_trigger`, `from_mixed`)
  - [pipeline/router.py](backend/pipeline/router.py) — `perceive(Perception)` single entry point; saves media, runs preprocessors, dispatches by Intent
  - [pipeline/processor.py](backend/pipeline/processor.py) — `process_message(perception, *, context, broadcast, persist, emit_event)` full conversation pipeline; returns `SpeechOutput`
  - [pipeline/context.py](backend/pipeline/context.py) — `gather_context()` → `ConversationContext` (memory, emotion, drives, modules, history, tools, `self_concept`, `person_context`)
  - [pipeline/prompt.py](backend/pipeline/prompt.py) — `build_system_prompt()` + `format_conversation()`
  - [pipeline/response.py](backend/pipeline/response.py) — `call_ai_and_parse()` builds prompt, calls AI, extracts emotion
  - [pipeline/broadcast.py](backend/pipeline/broadcast.py) — `broadcast_to_websocket()`, `emit_communication_event()`, `persist_to_memory(..., attachments_meta)`
  - [pipeline/preprocessors/](backend/pipeline/preprocessors/) — modality-specific Part transformers. `vision.py` is wired to a real LLM via `AIRole.VISION_CAPTION` (any provider with multimodal support); `audio.py` and `files.py` are still stubs. Failures + timeouts produce a safe text placeholder so the pipeline keeps flowing
  - [pipeline/media.py](backend/pipeline/media.py) — attachment validation + raw media persistence
  - [pipeline/tracing.py](backend/pipeline/tracing.py) — `request_id` ContextVar + logging filter
- **AI (multi-provider)** ([ai/](backend/ai/)):
  - `ai/providers/` — `ClaudeProvider`, `OpenAIProvider` (OpenAI-compatible via `base_url`), `OllamaProvider`. Lazy-instantiated. All three accept an `attachments=[MediaAttachment]` kwarg with image support: Claude uses `{"type": "image", "source": {...}}` blocks, OpenAI uses `image_url` data-URIs, Ollama passes base64 via the `images` message field (silently ignored if the model isn't vision-capable).
  - `ai/router.py` — `AIRole` enum (7 roles incl. `VISION_CAPTION`) + `AIRouter` singleton. Each role maps to `provider:model` via `AI_ROLE_*` env vars. Unified logging. `attachments=[MediaAttachment]` kwarg is forwarded to the provider for multimodal calls.
  - `ai/client.py` — `complete()` simple text completion
  - `ai/tool_client.py` — `complete_with_tools()` (Claude-only, MCP tool loops)
- **Emotion system** ([emotion/](backend/emotion/) — standalone Django app):
  - `emotion/types.py` — 29 emotions in 4 categories, `EmotionData`, `extract_emotion()`
  - `emotion/pad.py` — PAD (Pleasure/Arousal/Dominance) space anchors, `pad_to_label()`, `pad_to_blend()` (top-K ambivalence)
  - `emotion/dynamics.py` — damped harmonic oscillator (semi-implicit Euler)
  - `emotion/state.py` — `PersonMood`, `GlobalMood`, `Temperament`, `MessageEmotion` (with `blend` tuple + `is_ambivalent`)
  - `emotion/circadian.py` — pure-function layer: `current_phase()`, `current_state()`, `phase_bias()`, `energy_level()`. 4 phases (morning/afternoon/evening/night), cosine energy curve peaking ~14h. `CircadianProfile` loaded from `personality.yaml::circadian_profile` (phase boundaries, anchor emotions, energy peak/amplitude/baseline) so a nocturnal character is a YAML edit.
  - `emotion/engine.py` — `EmotionEngine` singleton: PAD oscillators per person + global mood. `_home_vector()` = default_mood × 0.15 + phase_bias × 0.35, so the oscillator's rest state drifts across the day without losing the character's identity. Two context accessors: `get_global_mood_context()` (Mika alone) and `get_person_affect_context(person_id)` (relational).
- **Drives system** ([drives/](backend/drives/) — standalone Django app):
  - `drives/state.py` — `DriveKind` (CURIOSITY, SOCIAL, EXPRESSION, REST), `DriveState`, per-drive parameters
  - `drives/engine.py` — `DriveEngine` singleton: tension grows over time, satisfied by actions, contributes signed to conscience scoring. REST pressure rises with activity, falls during idle. Exposes `energy_level()` that combines circadian energy (70%) with REST drive (30%) → used by conscience Factor 11 (fatigue penalty) and by the system prompt / frontend. All in-RAM (ephemeral across restarts — matches human intuition).
- **Personality**: [config/personality.py](backend/config/personality.py) — loads [personality.yaml](personality.yaml) (name, description, tone, traits, quirks, temperament block)
- **Memory** ([memory/](backend/memory/)):
  - `memory/manager.py` — `MemoryManager` singleton: short-term (RAM deque, `MEMORY_SHORT_TERM_LIMIT` messages) + ORM persistence + consolidator lifecycle
  - `memory/models.py` — `Conversation`, `Message` (with `attachments_meta` JSONField), `Theme`, `Entity`, `Souvenir`, `Connaissance`, `EmotionSnapshot`, `EmotionalSummary`, `ConsolidationLog`, `SelfNarrative`, `PersonProfile`, `Commitment`
  - `memory/storage/` — `vector_store.py` (ChromaDB) + `consolidator.py` (background loop: extraction → indexing → decay → emotion aggregation → narrative regen → person profile regen)
  - `memory/extraction/extractor.py` — AI-powered extraction of 3 types: souvenirs (1st-person episodes), connaissances (3rd-person facts), commitments (promises Mika made)
  - `memory/retrieval/retriever.py` — semantic search + person_id boost + recency bias + confidence
  - `memory/narrative.py` — `NarrativeGenerator`: regenerates `SelfNarrative` (1st-person autobiographical paragraph) when ≥24h old AND ≥5 new souvenirs
  - `memory/person_profile.py` — `PersonProfileGenerator`: theory of mind. Per person-entity, synthesizes closeness, preferred tone, topics of interest, sensitive topics. Gated per-person (≥24h + ≥3 new souvenirs mentioning them); capped at 3 persons/cycle
- **Conscience** ([conscience/](backend/conscience/)): Mika's waking brain. See dedicated section below.
- **Module plugin system**: [modules/base.py](backend/modules/base.py) (`BaseModule` ABC) + [modules/manager.py](backend/modules/manager.py) (`ModuleManager` singleton). Each module is a subfolder with its own `models.py`. `modules/models.py` re-exports for Django discovery.
- **Module capabilities** (opt-in): `instantiate`/`shutdown`, `worker_cron`, `return_tools`, `notify_ai`, `get_routes`, `get_context`, `on_event`, `get_status`, `is_available`
- **AI tools**: `ModuleManager` collects tools from all modules, builds an MCP server via `create_sdk_mcp_server()`, injected into `ClaudeAgentOptions.mcp_servers` when `complete_with_tools` is used
- **Cron scheduler**: built into `ModuleManager`, 1-second tick, per-module `CRON_INTERVAL` or global `CRON_TICK_INTERVAL`
- **notify_ai**: modules call their injected callback which constructs an `INTERNAL_TRIGGER` Perception and routes it via `perceive()` — so module initiatives flow through the same pipeline as any other input
- **Email module** ([modules/email/](backend/modules/email/)): IMAP/SMTP. Polls inbox (60s), triages with Haiku, stores `ProcessedEmail`, creates souvenirs/connaissances, notifies via `notify_ai`. Exposes `list_recent_emails`, `send_email` tools. Disabled gracefully if no config.

### Conscience Layer ([conscience/](backend/conscience/))

The Conscience is Mika's **waking brain** — a layer above modules that observes, interprets, memorizes, and decides. Django app at the same level as `ai/`, `memory/`, `emotion/`, `drives/`.

**Metaphor**: Conscience = waking state, Consolidator = dreaming state.

- **Engine** [conscience/engine.py](backend/conscience/engine.py) — `ConscienceEngine` singleton: decision loop (every `CONSCIENCE_DECISION_INTERVAL`s), memory maintenance, action execution. `_act()` builds an `INTERNAL_TRIGGER` Perception and routes it through the processor (never calls `process_message` directly).
- **Scoring** [conscience/scoring.py](backend/conscience/scoring.py) — pure functions. **11 weighted factors**: pertinence, accumulated urgency, mood overflow, idle time, time greeting, scheduled actions, pressure (consecutive waits), ignored-acts penalty, **drives** (signed: REST subtracts), **rumination pressure**, **fatigue penalty** (energy < 0.5 subtracts up to 0.25 — tired Mika is less spontaneous). Threshold: `CONSCIENCE_ACT_THRESHOLD` (0.5).
- **Interpreter** [conscience/interpreter.py](backend/conscience/interpreter.py) — `SignalInterpreter` classifies events. Heuristic fast-path for `chat.message`/`chat.connect`; Claude Haiku for rich events (emails, RSS).
- **MemoryBridge** [conscience/memory_bridge.py](backend/conscience/memory_bridge.py) — R/W interface to long-term memory: create souvenirs, boost importance, check/invalidate connaissances, recall for context.
- **Models** [conscience/models.py](backend/conscience/models.py):
  - `Observation` — interpreted signal buffer with state machine (`pending`/`acted`/`skipped`/`failed`)
  - `ConscienceLog` — decision audit trail
  - `ScheduledAction` — deferred actions (`schedule_action` tool)
  - `Rumination` — persistent unresolved thoughts (promoted from stale pertinent Observations). Each cycle: decays 5%, bleeds emotional charge into global mood, halved when Mika acts. States: `active`/`resolved`/`faded`.

**Memory powers**: the Conscience reshapes memory without speaking — boost souvenir importance for pertinent signals, invalidate contradicted connaissances, promote stale pertinent observations to Ruminations, decay ruminations over time.

### Emotion + Drives + Rumination (the "inner life")

Three complementary systems feed the conscience scoring and the system prompt:

- **Emotion** (`emotion/`): physics-based affective state. Two separate prompts blocks:
  - `emotion_context` = Mika's **global mood** only (standalone affective state) + drives descriptions
  - `person_context` = Mika's **affective stance toward the current person** (via `get_person_affect_context`), alongside her semantic profile and pending commitments
- **Drives** (`drives/`): intrinsic motivational tensions (CURIOSITY, SOCIAL, EXPRESSION, REST). Grow with time, assuaged by actions. Contribute signed to the conscience score (REST subtracts). Inject a French description into the prompt.
- **Rumination** (`conscience/models.py::Rumination`): short-term persistent thoughts — signals that were pertinent but unactioned. Decay, bleed emotion into global mood, and can push the conscience to eventually speak up.

### Self-concept and theory of mind

Two layers built on top of the memory system regenerate periodically during consolidation:

- **Self-narrative** (`memory/narrative.py` → `SelfNarrative` model): first-person paragraph "Je suis quelqu'un qui…" synthesized from recent souvenirs + connaissances + emotional summary. Regenerated every ~24h if ≥5 new souvenirs. Injected into the system prompt between personality and person-context, so Mika has an evolving sense of who she's becoming.
- **Person profile** (`memory/person_profile.py` → `PersonProfile` + `Commitment` models): per-person model — summary, closeness (stranger/acquaintance/friend/close), preferred tone, topics of interest, sensitive topics, pending commitments ("tu lui avais dit que..."). Regenerated per active person (seen in last 14 days, ≥3 new souvenirs, ≥24h since last). Injected in the prompt when Mika talks to a known person.

Commitments are a 3rd type of extraction produced by the same consolidator LLM call that extracts souvenirs/connaissances.

### System prompt structure

Assembled by `build_system_prompt()` ([pipeline/prompt.py](backend/pipeline/prompt.py)) in this order:

1. **Personality** (static, from `personality.yaml`)
2. **`--- QUI TU ES DEVENUE ---`** (self-concept, evolving paragraph)
3. **`--- CE QUE TU SAIS DE CETTE PERSONNE ---`** (person profile + affect + weekly trend + commitments)
4. **`--- TON RYTHME ---`** (circadian phase + energy level, from `emotion/circadian.py`)
5. **`--- CONTEXTE MODULES ---`** (email backlog, RSS unread, etc.)
6. **`--- TON ETAT EMOTIONNEL ACTUEL ---`** (global mood only + drives)
7. Memory context (semantic retrieval of relevant souvenirs/connaissances)

Personality + self-concept + person-context + circadian are the "slow" layers (stable over a session or shifting by the hour); module/emotion/memory are recomputed every turn. Recency bias places the latter last.

### Frontend (Vite + Three.js + VRM)

- **Entry**: [frontend/src/main.ts](frontend/src/main.ts) — initializes 3D scene, loads VRM, connects WebSocket, wires TTS + lip-sync + emotions
- **3D**: `src/scene/` — `SceneManager`, `Environment`, `CameraController`
- **VTuber**: `src/vtuber/` — `VTuberModel` (VRM via GLTFLoader + VRM plugin), `EmotionController` (29 emotions → blend shapes with intensity-based weighting), `AnimationMixer` (blink + breathing)
- **Audio**: `src/audio/` — `TTSService` (Web Speech API, emotion-based pitch/rate), `LipSyncController` (French phoneme mapping)
- **UI**: `src/ui/` — `ChatOverlay`, `EmotionDisplay` (29 emotion labels in French with intensity %)
- **Network**: `src/network/WebSocketClient.ts` — event-driven client with exponential backoff

**Speech flow**: WebSocket `speech` event → emotion validation → `EmotionController.setEmotion(name, intensity)` → TTS + lip-sync → independent blink/breathing.

A `.vrm` file at [frontend/public/models/default.vrm](frontend/public/models/default.vrm). Without it, a placeholder capsule+sphere is rendered.

## Key Conventions

- **29 emotions**: `neutral` | `happy`, `excited`, `love`, `proud`, `grateful`, `playful`, `amused`, `hopeful`, `relieved` | `sad`, `angry`, `scared`, `disgusted`, `frustrated`, `lonely`, `anxious`, `bored`, `jealous` | `surprised`, `thinking`, `confused`, `embarrassed`, `nostalgic`, `dreamy`, `determined`, `mischievous`, `curious`, `melancholic` — in `emotion/types.py::Emotion`
- **Emotion tag**: `[EMOTION:name:intensity]`. Legacy `[EMOTION:name]` = intensity 0.7
- **WebSocket protocol**:
  - Client → server: `{"type":"chat","message":"...","person_id":"...","attachments":[...]}`
  - Server → client: `{"type":"speech","text":"...","emotion":"...","emotion_intensity":0.75,"emotion_blend":[{"emotion":"...","weight":0.x}, ...],"emotion_state":{...},"source":"..."}`
- **Perception Intent**:
  - `REQUEST_RESPONSE` — user/channel expects an answer (default)
  - `OBSERVATION` — passive stimulus (camera frame, ambient audio, file drop). No forced response; conscience observes.
  - `INTERNAL_TRIGGER` — Mika-driven (conscience `_act`, module `notify_ai`, drive overflow, rumination resurfacing). Broadcasts; `emit_event=False`.
- **Person identification**: each WebSocket connection gets a per-connection UUID; clients can pass a persistent `person_id` in chat messages; Telegram uses `tg_{user_id}`. Internal IDs `conscience_mika`, `__global__`, `anonymous` are reserved and never matched to `PersonProfile`.
- **Personality is config-driven**: edit [personality.yaml](personality.yaml) (name, language, tone, traits, quirks, values, temperament) — no code changes needed
- **Singletons** (module-level, imported throughout): `ai_router` (`ai.router`), `ai_client` (`ai.client`), `memory_manager` (`memory.manager`), `emotion_engine` (`emotion.engine`), `drive_engine` (`drives.engine`), `personality` (`config.personality`), `module_manager` (`modules.manager`), `conscience_engine` (`conscience.engine`), `narrative_generator` (`memory.narrative`), `person_profile_generator` (`memory.person_profile`). Circadian is pure-function only (no singleton) — any caller passes the current `datetime` + the personality's `CircadianProfile`.
- **Django settings** in [config/settings.py](backend/config/settings.py): `PROJECT_ROOT` = repo root (where `.env` and `personality.yaml` live), `BASE_DIR` = `backend/`
- **INSTALLED_APPS**: `ai`, `communication`, `emotion`, `drives`, `memory`, `conscience`, `modules`
- **Adding a new input source** (e.g. Discord, webhook): write an adapter that builds a `Perception` and calls `pipeline.router.perceive()`. No pipeline changes needed.
- **Adding a new modality** (e.g. ultrasound sensor): add a preprocessor in [pipeline/preprocessors/](backend/pipeline/preprocessors/) and register its dispatch entry. Router + processor pick it up automatically.

## Authentication

1. **OAuth Token** (recommended): `CLAUDE_OAUTH_TOKEN` in `.env`. Backend converts internally to `CLAUDE_CODE_OAUTH_TOKEN` for the Claude Agent SDK.
2. **API Key**: `ANTHROPIC_API_KEY` in `.env` (requires paid Anthropic account).

OAuth tried first, API key as fallback. OAuth tokens start with `sk-ant-oat01-`; API keys start with `sk-ant-api`.

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CLAUDE_OAUTH_TOKEN` | No* | `""` | Claude OAuth token (*required if no API key) |
| `ANTHROPIC_API_KEY` | No* | `""` | Claude API key (*required if no OAuth) |
| `TELEGRAM_TOKEN` | No | `""` | Telegram bot token |
| `VTUBER_NAME` | No | `Mika` | Display name |
| `CLAUDE_MODEL` | No | `claude-opus-4-6` | Heavy model |
| `CLAUDE_MODEL_LIGHT` | No | `claude-sonnet-4-5` | Light model |
| `OPENAI_API_KEY` | No | `""` | OpenAI provider (if used) |
| `OPENAI_BASE_URL` | No | `""` | Custom OpenAI-compatible endpoint |
| `OLLAMA_BASE_URL` | No | `http://localhost:11434` | Ollama server |
| `AI_ROLE_CONVERSATION` | No | `claude:CLAUDE_MODEL` | Main chat |
| `AI_ROLE_CONVERSATION_TOOLS` | No | `claude:CLAUDE_MODEL` | Chat with tools (Claude-only) |
| `AI_ROLE_EMAIL_TRIAGE` | No | `claude:CLAUDE_MODEL_LIGHT` | Email analysis |
| `AI_ROLE_SIGNAL_INTERPRETATION` | No | `claude:CLAUDE_MODEL_LIGHT` | Signal interpretation |
| `AI_ROLE_MEMORY_EXTRACTION` | No | `claude:CLAUDE_MODEL_LIGHT` | Memory extraction + narrative + person profile |
| `AI_ROLE_VALIDITY_CHECK` | No | `claude:CLAUDE_MODEL_LIGHT` | Connaissance validity checks |
| `AI_ROLE_VISION_CAPTION` | No | `claude:CLAUDE_MODEL_LIGHT` | Image → text description (vision preprocessor) |
| `AI_CALL_TIMEOUT` | No | `60` | Seconds before `process_message` gives up waiting on the AI |
| `API_PORT` | No | `8000` | Backend port |
| `MEMORY_SHORT_TERM_LIMIT` | No | `20` | Messages kept in RAM context |
| `CONSOLIDATION_INTERVAL` | No | `60` | Consolidator loop period (s) |
| `MEMORY_DECAY_RATE` | No | `0.95` | Per-day souvenir importance decay |
| `MEMORY_MIN_IMPORTANCE` | No | `0.1` | Prune threshold |
| `MEMORY_RETRIEVAL_SOUVENIRS` | No | `5` | Souvenirs returned by retriever |
| `MEMORY_RETRIEVAL_CONNAISSANCES` | No | `10` | Connaissances returned |
| `EMBEDDING_MODEL` | No | `paraphrase-multilingual-MiniLM-L12-v2` | Sentence-transformer model for ChromaDB |
| `EMOTION_DECAY_RATE` | No | `0.02` | Emotion intensity lost per second |
| `EMOTION_SNAPSHOT_INTERVAL` | No | `30` | Seconds between `EmotionSnapshot` writes per person |
| `EMOTION_SNAPSHOT_RETENTION_DAYS` | No | `2` | How long snapshots persist before summary fallback |
| `CRON_TICK_INTERVAL` | No | `60` | Default scheduler tick period |
| `IMAP_HOST` / `IMAP_PORT` / `IMAP_USER` / `IMAP_PASSWORD` | No | `""` / `993` | Email fetch |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` | No | `""` / `587` | Email send |
| `CONSCIENCE_DECISION_INTERVAL` | No | `30` | Seconds between conscience decisions |
| `CONSCIENCE_COOLDOWN_SECONDS` | No | `300` | Min seconds between conscience actions |
| `CONSCIENCE_ACT_THRESHOLD` | No | `0.5` | Score threshold for `act` decision |
| `RSS_FEEDS` | No | `""` | Comma-separated `"name|url"` pairs |
| `RSS_POLL_INTERVAL` | No | `600` | RSS fetch period (s) |
| `CHROMA_PERSIST_DIR` | No | `data/chromadb` | ChromaDB on-disk location |

## Testing notes

- `pytest.ini` uses `pytest-django` and `asyncio_mode=auto`
- Scoring tests share a `_score(ctx)` helper that pre-marks all greeting periods as done, isolating them from wall-clock time (otherwise tests run at 7–10h, 18–20h, or 23h+ get an extra +0.35 from the time-greeting factor)
- DB tests with `transaction=True` often need an autouse fixture to truncate leaked rows from prior non-transactional `django_db` tests — this pattern appears in `test_self_narrative.py`, `test_person_profile.py`
