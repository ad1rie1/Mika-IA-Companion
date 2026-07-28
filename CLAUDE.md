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

### Database — SQLite under permanent concurrent load

Six background loops write continuously (conscience 30s, consolidator 60s, sleep 60s, project runner 30s, module scheduler 1s tick, emotion snapshots), and every `sync_to_async` call runs in its own thread with its own connection. On the default `journal_mode=DELETE`, a single writer blocks every reader and Python's 5s busy timeout surfaces as `database is locked`.

[config/settings.py](backend/config/settings.py) therefore sets `OPTIONS`: **WAL** (readers proceed during writes — the actual access pattern here: a conversation turn reads memory/identity/projects while the loops keep writing), `synchronous=NORMAL`, `foreign_keys=ON`, a 32 MB page cache, and a 30s lock timeout (`DB_LOCK_TIMEOUT`). Note this is invisible in tests: pytest-django uses an in-memory database where WAL is a no-op, so the regression test asserts the declared `init_command`, not the runtime PRAGMA.

### Backend layout

- **Entry point**: [run.py](run.py) — adds `backend/` to sys.path, configures Django, launches Uvicorn
- **ASGI** [config/asgi.py](backend/config/asgi.py): `LifespanWrapper` runs startup (memory → emotion → conscience → modules) and shutdown
- **Communication channels** ([communication/](backend/communication/)): adapters that translate external inputs into `Perception` objects and hand them to `pipeline.router.perceive()`. No shared legacy handler — each channel builds its own Perception.
  - [communication/channels/web_frontend.py](backend/communication/channels/web_frontend.py) — `WebSocketConsumer`, greeting routed through `perceive()` as `INTERNAL_TRIGGER`
  - [communication/channels/telegram.py](backend/communication/channels/telegram.py) — Telegram channel. Text AND inbound media: photos / voice notes / audio / documents are downloaded (≤5 MB), lifted into a MIXED `Perception` with their caption, and preprocessed like any frontend upload (photo → vision caption, vocal → Whisper transcript, document → text extraction)
  - [communication/routing.py](backend/communication/routing.py), [communication/urls.py](backend/communication/urls.py), [communication/views.py](backend/communication/views.py) — WS routing + HTTP health/personality endpoints
- **Pipeline** ([pipeline/](backend/pipeline/)):
  - [pipeline/perception.py](backend/pipeline/perception.py) — `Perception`, `Part`, `Modality`, `Intent`, and constructors (`from_text`, `from_internal_trigger`, `from_mixed`)
  - [pipeline/router.py](backend/pipeline/router.py) — `perceive(Perception)` single entry point; saves media, runs preprocessors, dispatches by Intent
  - [pipeline/processor.py](backend/pipeline/processor.py) — `process_message(perception, *, context, broadcast, persist, emit_event)` full conversation pipeline; returns `SpeechOutput`
  - [pipeline/context.py](backend/pipeline/context.py) — `gather_context()` → `ConversationContext` (memory, emotion, drives, modules, history, tools, `self_concept`, `person_context`)
  - [pipeline/prompt.py](backend/pipeline/prompt.py) — `build_system_prompt()` + `format_conversation()`
  - [pipeline/response.py](backend/pipeline/response.py) — `call_ai_and_parse()` builds prompt, calls AI, extracts emotion
  - [pipeline/broadcast.py](backend/pipeline/broadcast.py) — `broadcast_to_websocket()`, `emit_communication_event()`, `persist_to_memory(..., attachments_meta)`
  - [pipeline/preprocessors/](backend/pipeline/preprocessors/) — modality-specific Part transformers, all three real now. `vision.py` captions via `AIRole.VISION_CAPTION` (any multimodal provider). `audio.py` transcribes via the OpenAI provider's Whisper endpoint (`ai_router.provider_by_name("openai")` — router cache, so credential rotation applies; no other provider exposes STT). `files.py` extracts text locally: text-like MIME/extensions (utf-8 → latin-1 fallback), HTML tag-stripping, PDF via `pypdf` (declared dep), DOCX via optional `python-docx`; parsing runs in a thread. Failures + timeouts produce a safe text placeholder so the pipeline keeps flowing — an error is never surfaced as content
  - [pipeline/media.py](backend/pipeline/media.py) — attachment validation + raw media persistence. Disk writes go through `asyncio.to_thread`: up to 5 MB × 5 attachments written synchronously would freeze all WebSocket traffic and every background loop for the duration of an upload
  - [pipeline/tracing.py](backend/pipeline/tracing.py) — `request_id` ContextVar + logging filter
- **AI (multi-provider)** ([ai/](backend/ai/)):
  - `ai/providers/` — `ClaudeProvider`, `OpenAIProvider` (OpenAI-compatible via `base_url`), `OllamaProvider`. Lazy-instantiated. All three accept an `attachments=[MediaAttachment]` kwarg with image support: Claude uses `{"type": "image", "source": {...}}` blocks, OpenAI uses `image_url` data-URIs, Ollama passes base64 via the `images` message field (silently ignored if the model isn't vision-capable).
  - `ai/router.py` — `AIRole` enum (8 roles incl. `VISION_CAPTION` and `INNER_VOICE`) + `AIRouter` singleton. Each role maps to `provider:model` via `AI_ROLE_*` env vars. Unified logging. `attachments=[MediaAttachment]` kwarg is forwarded to the provider for multimodal calls. `provider_by_name(name)` gives public access to a cached provider instance for capability-specific call sites outside the role system (Whisper STT in the audio preprocessor + `files_service.op_transcribe`) — same cache + credential-change eviction as role-routed calls, never a fresh instance pinning an old key.
  - Provider instances are cached, but **evicted when their credentials change**: `_PROVIDER_CONFIG_PREFIXES` subscribes to `ai.<provider>.*`, so rotating a leaked key in the dashboard actually takes effect (it previously returned `{"ok": true}` while the process kept authenticating with the old one). Those config items are marked `hot_reload=True` so the UI says so.
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
  - **Every drive now has a real relief path**: `on_conversation` (SOCIAL+CURIOSITY, incoming), `on_act` (EXPRESSION full, spontaneous speech), `on_reply` (EXPRESSION ×0.4 + activity — called by the processor on every successful reactive answer; without it a Mika who chatted all day was still pushed to speak "spontaneously" as if silent), and **sleep relieves REST** (`SLEEP_REST_RECOVERY` per sleeping tick — before, REST was write-only and she woke up as tired as she fell asleep).
- **Personality**: [config/personality.py](backend/config/personality.py) — loads [personality.yaml](personality.yaml) (name, description, tone, traits, quirks, temperament block)
- **Memory** ([memory/](backend/memory/)):
  - `memory/manager.py` — `MemoryManager` singleton: short-term (RAM deque, `MEMORY_SHORT_TERM_LIMIT` messages) + ORM persistence + consolidator lifecycle. **Survives restarts**: `initialize()` reattaches to the conversation in progress when the last message is under `resume_window_minutes` (120) old, then `_rehydrate_short_term()` reloads the tail of that conversation into the RAM buffer. `get_conversation_context()` is the *only* history the LLM sees and was never populated from the DB, so a restart mid-chat used to be total conversational amnesia — "et le deuxième alors ?" landed on nothing — even though her mood toward the person was correctly restored from `EmotionSnapshot`. Internal scaffolding (`is_internal`) is skipped: it was never part of the dialogue
  - `memory/models.py` — `Conversation`, `Message` (with `attachments_meta` JSONField), `Theme`, `Entity`, `Souvenir`, `Connaissance`, `EmotionSnapshot`, `EmotionalSummary`, `ConsolidationLog`, `SelfNarrative`, `PersonProfile`, `Commitment`, `DailyJournal`, `Dream`
  - `memory/storage/` — `vector_store.py` (ChromaDB) + `consolidator.py` (background loop: extraction → indexing → decay → emotion aggregation → narrative regen → person profile regen → sleep cycle)
    - **Decay is relative, not absolute**: `importance *= decay_rate ** days_since(Souvenir.decayed_at)`. The old `decay_rate ** age` recomputed an absolute value each tick, which wiped every conscience boost and inflated a freshly-created importance-0.3 souvenir to ~1.0. `decayed_at` only advances when a write actually happens, so sub-threshold elapsed time accumulates instead of being dropped (migration `memory/0012`).
    - **`Connaissance` had the same bug and no anchor at all** (migration `memory/0014`). Decay was measured from `updated_at`, which is `auto_now` — and Django only refreshes an `auto_now` field when it is among the columns being written, which `save(update_fields=["confidence"])` never is. The anchor never advanced, so every pass re-subtracted the *entire* elapsed decay: measured, a 30-day-old fact went 1.0 → 0.914 → 0.828 → 0.742 over three passes, hitting the 0.2 floor in about ten minutes of 60s ticks. Now anchored on `Connaissance.decayed_at`, exactly like souvenirs.
    - **The decay sweep is throttled and narrowed**: `_apply_decay` runs hourly (`DECAY_INTERVAL_S`), not on every 60s tick — decay is measured in days, so 1440 sweeps/day applied changes only visible after hours, and it ran on the "no new messages" path too, so an idle install paid full price forever. Each sweep now selects only rows whose anchor is older than `DECAY_MIN_AGE` (1h) and caps the batch at `DECAY_BATCH` (500), because every write also re-embeds into ChromaDB. Nothing is lost: a row left out keeps its anchor and its elapsed time. Commitment expiry keeps its own cadence — cheap indexed UPDATEs, and it's what stops a stale promise being re-asserted in every prompt.
    - **Checkpoint reads the ceiling first**, then messages `id__lte` it. Reading messages first and taking `max(id)` afterwards let a turn persisted between the two queries be counted by the checkpoint but never extracted — that exchange was skipped forever.
    - **Internal scaffolding is excluded by a flag, not a source denylist**: `Message.is_internal` (migration `memory/0013`) marks the "user" prompt of an `INTERNAL_TRIGGER` perception (greeting brief, module `notify_ai` text). Those instructions used to reach the extractor and become bogus souvenirs. Her *reply* (`role=assistant`) stays included.
  - `memory/extraction/extractor.py` — AI-powered extraction of 3 types: souvenirs (1st-person episodes), connaissances (3rd-person facts), commitments (promises Mika made). The extraction call also receives the current **pending commitments** and can return `commitment_resolved` entries when the conversation shows one was honored ("voila la playlist !") or became moot
  - **Commitment lifecycle actually closes** (was: created `pending`, never resolved, re-asserted in every prompt forever): (1) the consolidator marks `honored`/`dropped` from `commitment_resolved` extractions, (2) Mika resolves explicitly mid-chat via the `memory_resolve_commitment` tool, (3) `_expire_commitments` drops anything past `due_at` or pending > 30 days (`COMMITMENT_MAX_AGE_DAYS`)
  - `memory/module.py` — **memory_tools** SYSTEM module (registered in `memory/apps.py`, same piggyback as `files`): active recall via MCP tools `memory_search` (semantic, souvenirs+connaissances), `memory_recent_souvenirs`, `memory_read_journal` (reread any DailyJournal), `memory_list_commitments`, `memory_resolve_commitment`. Before this, recall was push-only — Mika couldn't dig into her own memory on demand
  - `memory/retrieval/retriever.py` — semantic search + person_id boost + recency bias + confidence
  - `memory/narrative.py` — `NarrativeGenerator`: regenerates `SelfNarrative` (1st-person autobiographical paragraph) when ≥24h old AND ≥5 new souvenirs
  - `memory/person_profile.py` — `PersonProfileGenerator`: theory of mind. Per person-entity, synthesizes closeness, preferred tone, topics of interest, sensitive topics. Gated per-person (≥24h + ≥3 new souvenirs mentioning them); capped at 3 persons/cycle
  - `memory/sleep.py` — `SleepCycle` singleton. Nighttime creative/narrative/healing work. See "Sleep Cycle" section below.
- **Conscience** ([conscience/](backend/conscience/)): Mika's waking brain. See dedicated section below.
- **Retention sweep** ([memory/retention.py](backend/memory/retention.py)): declarative ceilings on append-only tables, applied hourly from the consolidator tick (both paths — with and without new messages). `POLICIES` is a tuple of `Policy(app_label, model_name, date_field, keep_days, keep_rows, protect)`. Motivation: `ConscienceLog` gets a row on **every** decision cycle regardless of outcome, so at a 30s interval it grows ~2 880 rows/day — over a million a year on an install nobody talks to. Also covers `ConsolidationLog` (only the newest row is ever read), faded `Rumination`s (active/resolved are protected — journals and digestion still reference them), and `ProjectLog`. A broken policy is logged and skipped, never fatal. A test asserts every policy names a real model + field and has at least one ceiling.
- **Module plugin system**: [modules/base.py](backend/modules/base.py) (`BaseModule` ABC) + [modules/manager.py](backend/modules/manager.py) (`ModuleManager` singleton). Each module is a subfolder with its own `models.py`. `modules/models.py` re-exports for Django discovery.
- **Module capabilities** (opt-in): `instantiate`/`shutdown`, `worker_cron`, `return_tools`, `notify_ai`, `get_routes`, `get_views`, `get_context`, `on_event`, `get_status`, `is_available`
- **AI tools**: `ModuleManager` collects tools from all modules, builds an MCP server via `create_sdk_mcp_server()`, injected into `ClaudeAgentOptions.mcp_servers` when `complete_with_tools` is used
- **Cron scheduler**: built into `ModuleManager`, 1-second tick, per-module `CRON_INTERVAL` or global `CRON_TICK_INTERVAL`. Each tick runs **detached** (`_spawn_cron`): awaiting them inline made the shared scheduler only as fast as its slowest module — an IMAP fetch or an RSS poll held up Forge, wake and camera for as long as it ran, and a hung socket held them up forever. One task per module at a time; an overlapping tick is skipped, not queued, so a module slower than its own interval degrades to "as often as it can" instead of accumulating a backlog. `stop_all()` reaps in-flight ticks.
- **notify_ai**: modules call their injected callback which constructs an `INTERNAL_TRIGGER` Perception and routes it via `perceive()` — so module initiatives flow through the same pipeline as any other input
- **Email module** ([modules/email/](backend/modules/email/)): IMAP/SMTP. Polls inbox (60s), triages with Haiku, stores `ProcessedEmail`, creates souvenirs/connaissances, notifies via `notify_ai`. Exposes `list_recent_emails`, `send_email` tools. Disabled gracefully if no config.
- **Forge** ([modules/plugins/forge/](backend/modules/plugins/forge/)): AI-self-managed modules. One host plugin (`forge`) loads N sandboxed mini-modules that **Mika writes herself** into the confined dir `data/forge_modules/` (`FORGE_DIR`). See dedicated section below.

### Admin interface — access control and payload safety

The dashboard reads the entire conversation history and writes the config, including provider API keys. Three layers now stand between that and the network:

- **Loopback by default** — `API_HOST` defaults to `127.0.0.1` (was a hardcoded `0.0.0.0`). Set `API_HOST=0.0.0.0` to serve the LAN; [run.py](run.py) then logs a `SECURITY:` warning if `DASHBOARD_REQUIRE_AUTH` is off.
- **Optional auth gate** — [dashboard/middleware.py](backend/dashboard/middleware.py) `DashboardAuthMiddleware` covers the whole `/dashboard/` prefix when `DASHBOARD_REQUIRE_AUTH=1`: HTML requests redirect to `LOGIN_URL` (default `/admin/login/`, so the Django admin account doubles as the dashboard account) with `?next=`, API requests get a 401 JSON body. Staff-only, so an account created for the chat frontend doesn't inherit the config editor. **Off by default** — a fresh install has no superuser, and locking the owner out of their own admin before they can run `createsuperuser` is worse than loopback exposure. One middleware rather than 66 decorators: the next route added can't forget it.
- **CORS is not wildcarded** — `CORS_ALLOW_ALL_ORIGINS` defaults to `False` with the dev frontend origins allow-listed. It previously followed `DEBUG`, so any page the user visited could read `/dashboard/api/messages` and `PATCH` the config cross-origin without needing credentials (nothing was authenticated).

**Payload sanitization** ([dashboard/sanitize.py](backend/dashboard/sanitize.py)) — the generic renderer injects `html` keys via `innerHTML`, so `view_data` / `view_item` strip `html`/`js`/`template` recursively from **every** module's payload, not just forged ones. `ModuleView.allow_raw_html=True` is the explicit opt-in for a module that owns and escapes its own markup. The Forge re-exports the shared implementation instead of keeping a second copy.

**Config write path** — record-list rows go through the same `_coerce` + `_validate` as scalar items (the local copy they used handled only int/float/bool, silently kept the raw string on failure, and checked neither `select` choices nor min/max), row CRUD invalidates the cache before notifying subscribers, `registry.register_replace()` invalidates each replaced key (a forged module's hot reload could change a `default` behind a memoized value), and `config_service.set()` on a blank sensitive field returns a **redacted** marker rather than handing the decrypted current secret back to the caller.

**Known remaining gap**: `CsrfViewMiddleware` is still absent, so the many `@csrf_exempt` decorators are redundant and mutating endpoints have no CSRF token check. With a loopback bind and non-wildcard CORS the drive-by vector is closed, but adding the middleware (plus `{% csrf_token %}` in the templates and the token in `app.js`) is the proper fix.

### Module dashboard views

Each module can surface one or more **visualization pages** in the dashboard (boîte de réception, historique RSS, comptes configurés, stats…) symmetrically to `config_schema()`. The core knows nothing module-specific — the shell discovers views at render-time and auto-mounts their URLs.

**Module-author guide**: [backend/modules/plugins/README.md](backend/modules/plugins/README.md) documents the full contract + both rendering approaches with worked examples. Below is a quick reference.

**Contract** ([modules/types.py](backend/modules/types.py::ModuleView)) — a module returns a list of `ModuleView` from `get_views()`:

- `key` / `label` / `icon` / `order` — sidebar shape (slug unique within the module)
- `data_handler` — `async (request) -> dict`. For the generic renderer return `{columns, rows, total, page, limit}` (single server-paginated table); reads `request.GET` for `page`, `limit`, `q` (pagination is the handler's responsibility). Alternatively return `{tabs: [{key,label,columns,rows} | {key,label,html} | {key,label,...flatJson}]}` to render a tab bar (one payload, client-side paginated table tabs). Anything else is pretty-printed as JSON. Shared frontend helpers on `window.Dash` (loaded on every dashboard page): `pager` (server pagination), `clientPager` (in-memory list pagination), `tabs` (localStorage-persisted tab bar) — usable from any Option-B custom view JS
- `detail_handler` — `async (request, item_id) -> dict | None`. When set, the generic renderer auto-appends a "Voir" column to rows whose `row[id_field]` is non-null; clicking opens a modal rendering either `{fields: [{label,value}]}` or any flat dict as key/value
- `id_field` — per-row key holding the identifier passed to `detail_handler` (default `"id"`)
- `template` — optional template name (e.g. `"email/inbox.html"`) resolved from the module's own `modules/plugins/<name>/templates/` directory. Falls back to `dashboard/module_view.html` (generic shell)
- `js` — optional static path loaded via `<script>`. When unset, `dashboard/js/views/module_default.js` is used (generic table + detail-modal renderer)
- `actions` — optional list of `ModuleViewAction(key, label, handler, method, confirm)`. Each gets a button above the content and a POST endpoint

**Two rendering approaches**, freely mixable within a module:

- **Option A (generic shell)** — return `{columns, rows}` + declare `detail_handler`, zero files shipped by the module. Table + "Voir" button + modale auto-rendered.
- **Option B (custom template + JS)** — ship `modules/plugins/<m>/templates/<m>/<view>.html` + `modules/plugins/<m>/static/<m>/views/<view>.js`, set `template=` / `js=` on the view. Full control over the layout, same data/detail/action endpoints.

Example: [modules/plugins/email/views.py](backend/modules/plugins/email/views.py) uses B for `inbox` (split master/detail mail renderer) and A for `contacts` (auto key/value modal).

**Auto-mounting** — at render time, [pages._build_module_menu](backend/dashboard/views/pages.py) snapshots `module_manager.collect_views()` (running modules only). URLs wired once in [dashboard/urls.py](backend/dashboard/urls.py):

```
GET  /dashboard/modules/<module>/<view>/                          HTML shell
GET  /dashboard/api/modules/<module>/views                        list of views
GET  /dashboard/api/modules/<module>/views/<view>                 data_handler
GET  /dashboard/api/modules/<module>/views/<view>/items/<id>      detail_handler
POST /dashboard/api/modules/<module>/views/<view>/actions/<key>   action handler
```

A view is only visible in the sidebar when the module is **enabled AND running**. Disabling a module makes its pages vanish from the nav on the next render. The `/dashboard/api/modules` row also carries a `views: [{key,label,icon,url}]` field, surfaced as chips in the Modules admin page.

**Template + static discovery** — `settings.py` scans `backend/modules/plugins/*/templates` and `backend/modules/plugins/*/static` at import time and adds them to `TEMPLATES[0]['DIRS']` + `STATICFILES_DIRS`. Plugins are sub-packages of the `modules` app, not installed apps themselves, so Django's `APP_DIRS` / `AppDirectoriesFinder` wouldn't find them otherwise. Drop a file in `modules/plugins/email/templates/email/inbox.html` and it resolves as `email/inbox.html` template name; same for static.

### Forge — AI-self-managed modules ([modules/plugins/forge/](backend/modules/plugins/forge/))

Confined space where **Mika creates/edits/tests/deletes her own mini-modules** at runtime (hot reload, no restart). Full doc: [modules/plugins/forge/README.md](backend/modules/plugins/forge/README.md).

- **Layout**: each forged module lives in `data/forge_modules/<slug>/` — `manifest.yaml` (declarative: title, `schedule`, `events` patterns, `views`, `config` fields, `allowed_domains`, `context`) + `module.py` (sandboxed code) + `state.json` (host-managed: enabled, disabled_reason) + `_versions/` (auto-snapshots, rollback) ; erased modules go to `_trash/`.
- **Sandbox** ([sandbox.py](backend/modules/plugins/forge/sandbox.py)): AST validation at write time (no `import`, no async, no `_`-prefixed attribute access, no `eval/exec/open/getattr/type/...`, no `.format`), curated builtins + read-only safe modules (`math json re datetime random statistics collections itertools functools hashlib base64 uuid copy string`) at exec time, per-handler deadline via `sys.settrace` in a dedicated 2-worker thread pool. Handlers are sync; the host wraps them async — a slow forged module never blocks the shared scheduler (ticks run in a background task).
  - **Two escapes closed (2026-07)**, both verified exploitable before the fix:
    - *Frame walk*: `f_* / gi_* / cr_* / ag_* / tb_*` attributes are **not** `_`-prefixed, so `gen.gi_frame.f_back` climbed into host frames whose `f_builtins` holds the real `__import__` → arbitrary RCE. Those prefixes are now an explicit denylist (`FORBIDDEN_ATTR_PREFIXES`).
    - *Catchable deadline*: `ForgeTimeout` derived from `Exception`, so `while True: try: ... except Exception: pass` swallowed its own timeout and pinned a worker thread forever — two such modules exhausted the 2-worker pool and hung all Forge operations, without ever tripping the breaker. It now derives from `BaseException`, and the validator rejects bare `except:` plus any reference to `BaseException`/`ForgeTimeout`/`SystemExit`/`KeyboardInterrupt`/`GeneratorExit`.
  - Hot reload calls `_unregister_config()` before re-registering (`register_replace` can only add/replace, so a config field dropped from a manifest lingered in the dashboard until restart). `_trash/` is capped at `MAX_TRASH_KEPT = 20`. `ForgeLog` pruning is amortized every 50 inserts per module instead of sampling the wall clock (which only fired ~5% of the time and could never fire for a module logging on fixed seconds).
- **Capability API** ([api.py](backend/modules/plugins/forge/api.py)): `api.storage` (per-module JSON KV by collections in shared `ForgeRecord` table, quotas — forged modules never get DDL), `api.config` (reads `forge.<module>.<key>` from the standard config service, dashboard-edited, secrets decrypted, `record_list` supported), `api.log/warn/error` + `print` → `ForgeLog`, `api.notify_ai` (rate-limited by `forge.notify_cooldown_s`), `api.emit` → `forge.<module>.<type>` on the bus (Conscience observes; sibling forged modules subscribed via `events` receive it, never the emitter), `api.http_get` (manifest `allowed_domains` only, redirects off, private/loopback IPs blocked, size-capped), `api.state` (RAM dict).
- **Circuit breaker**: `forge.max_consecutive_failures` (5) tick/event failures → module auto-disabled (persisted in `state.json`), unloaded, and Mika notified once with the error so she can `forge_read_module` → fix → `forge_command(enable)`.
- **Dynamic config**: at load, the host registers a `ConfigSection` "Forge · <title>" + items via `registry.register_replace()` (new registry method; `registry.unregister()` on erase). Values persist in `ConfigValue` across reload/disable.
- **Views**: forged views are namespaced into the host's `get_views()` as `<module>__<viewkey>` (generic Option-A renderer only; payloads sanitized — `html`/`js`/`template` keys stripped so forged code can never inject markup into the dashboard).
- **MCP tools** (in every tools-enabled conversation): `forge_list_modules`, `forge_read_module`, `forge_write_module` (create/update: manifest merge + AST validation + version archive + hot reload; on failure the old version keeps running), `forge_command` (`enable|disable|reload|rollback|erase|reset_storage`), `forge_test_module` (run any handler NOW, returns result + logs — the iteration loop), `forge_read_logs`.
- **HTTP routes**: `GET /api/modules/forge/` (list), `POST /api/modules/forge/command`, `GET /api/modules/forge/source?name=`, `GET /api/modules/forge/logs` — plus a "Forge" dashboard page (Modules/Journal/Stockage tabs, per-module detail modal, reload-all action).
- **Scheduling** reuses [projects/schedule.py](backend/projects/schedule.py) (`interval:`/`cron:`/`idle:`/`manual`); event-driven wake-up goes through manifest `events`, not `schedule`.
- Models `ForgeRecord`/`ForgeLog` are shared host tables (regular migration `modules/0010`); threat model is accident-prevention + prompt-injection hardening, not OS-grade isolation (in-process execution — documented in the README).

### Conscience Layer ([conscience/](backend/conscience/))

The Conscience is Mika's **waking brain** — a layer above modules that observes, interprets, memorizes, and decides. Django app at the same level as `ai/`, `memory/`, `emotion/`, `drives/`.

**Metaphor**: Conscience = waking state, Consolidator = dreaming state.

- **Engine** [conscience/engine.py](backend/conscience/engine.py) — `ConscienceEngine` singleton: decision loop (every `CONSCIENCE_DECISION_INTERVAL`s), memory maintenance, action execution. `_act()` builds an `INTERNAL_TRIGGER` Perception and routes it through the processor (never calls `process_message` directly). The high-pertinence fast-path (`p > 0.85`) is **scheduled**, not awaited (`_spawn_decision()`): `observe()` runs inside `ModuleManager.emit_event`, which the email/RSS pollers await, so an inline decision blocked the emitting module's loop for two LLM calls. Tasks are held in a set so they aren't GC'd mid-flight, and failures are logged rather than vanishing.
- **Scoring** [conscience/scoring.py](backend/conscience/scoring.py) — pure functions. **11 weighted factors**: pertinence, accumulated urgency, mood overflow, idle time, time greeting, scheduled actions, pressure (consecutive waits), ignored-acts penalty, **drives** (signed: REST subtracts), **rumination pressure**, **fatigue penalty** (energy < 0.5 subtracts up to 0.25 — tired Mika is less spontaneous). Threshold: `CONSCIENCE_ACT_THRESHOLD` (0.5).
- **Interpreter** [conscience/interpreter.py](backend/conscience/interpreter.py) — `SignalInterpreter` classifies events. **Every event outside the fast-path costs a Haiku call**, and `emit_event` awaits `observe()`, so those calls run strictly in series inside the emitting module's tick. The fast-path therefore covers everything high-volume: `chat.*`, `telegram.message`, `rss.new_entry`, and any `forge.*` prefix (`heuristic_for()` matches exact types then prefixes). Before that, a first poll of 5 RSS feeds meant ~75 sequential LLM calls with the scheduler frozen throughout — to decide that headlines are mildly interesting. RSS pertinence is now scored from theme keyword matches; forged-module events are low-pertinence by default (a forged module that wants attention uses `api.notify_ai`, a different path). `email.received` deliberately still goes through the LLM: an email is genuinely rich content whose importance can't be read off a keyword table, and there are few enough of them.
- **MemoryBridge** [conscience/memory_bridge.py](backend/conscience/memory_bridge.py) — R/W interface to long-term memory: create souvenirs, boost importance, check/invalidate connaissances, recall for context.
- **Models** [conscience/models.py](backend/conscience/models.py):
  - `Observation` — interpreted signal buffer with state machine (`pending`/`acted`/`skipped`/`failed`)
  - `ConscienceLog` — decision audit trail
  - `ScheduledAction` — deferred actions (`schedule_action` tool)
  - `Rumination` — persistent unresolved thoughts (promoted from stale pertinent Observations). Each cycle: decays 5%, bleeds emotional charge into global mood, halved when Mika acts. States: `active`/`resolved`/`faded`.

**Greeting state is committed only on "act"** — `check_time_trigger` marks a period greeted inside the scoring pass, but the greeting factor is worth 0.35 against a 0.5 threshold. Committing immediately spent the day's greeting on a cycle that decided to stay silent, so Mika almost never greeted anyone. `_compute_score()` now stashes the tentative state and `_commit_greeting()` persists it from the `act` branch only.

**Memory powers**: the Conscience reshapes memory without speaking — boost souvenir importance for pertinent signals, invalidate contradicted connaissances, promote stale pertinent observations to Ruminations, decay ruminations over time.

### Emotion + Drives + Rumination (the "inner life")

Three complementary systems feed the conscience scoring and the system prompt:

- **Emotion** (`emotion/`): physics-based affective state. Two separate prompts blocks:
  - `emotion_context` = Mika's **global mood** only (standalone affective state) + drives descriptions
  - `person_context` = Mika's **affective stance toward the current person** (via `get_person_affect_context`), alongside her semantic profile and pending commitments
- **Drives** (`drives/`): intrinsic motivational tensions (CURIOSITY, SOCIAL, EXPRESSION, REST). Grow with time, assuaged by actions. Contribute signed to the conscience score (REST subtracts). Inject a French description into the prompt.
- **Rumination** (`conscience/models.py::Rumination`): short-term persistent thoughts — signals that were pertinent but unactioned. Decay, bleed emotion into global mood, and can push the conscience to eventually speak up.

### Identity & trust ([identity/](backend/identity/))

Who Mika is talking to, **how sure she is**, and what that certainty allows her to say. Everything per-person downstream — theory of mind, commitments, emotional history, concern-based routing — resolves through this layer.

**The bug it replaces**: `Identity.entity` was never populated (`link_entity` existed but nothing called it), and per-person memory was looked up with `PersonProfile.filter(entity__name=person_id)`. That only matches when a person's memory Entity happens to be named after their transport handle, which never happens: the consolidator names entities after what people are *called* ("Thomas") while handles are `web_6f3e22ccb0ae`. Two disjoint rows per person, joined by nothing — the whole theory-of-mind layer returned `""` on every turn, silently. On the dev database, 95 `Identity` rows all carried `entity_id = NULL`.

**Two orthogonal notions** ([identity/trust.py](backend/identity/trust.py), pure functions, no DB):

- **`ChannelTrust`** — what the *transport* proves. `AUTHENTICATED` (verified Django session) > `ACCOUNT` (stable platform id: a Telegram DM proves the same account came back, not who holds it) > `PUBLIC` (group chat, unknown transport — proves nothing) > `INTERNAL` (not a person). Each grants a **floor** and imposes a **ceiling**.
- **`Certainty`** — how sure she is that *this handle is that person*: `UNKNOWN` 0.0 → `SUSPECTED` 0.25 → `CLAIMED` 0.45 → `CORROBORATED` 0.70 → `BOUND` 0.85 → `VERIFIED` 1.0. Moves with evidence, clamped by the channel ceiling. **No amount of talking makes a public-room claim as good as a login.**

**Three ways an identity gets established:**

1. **Authenticated** — `bind_authenticated()` on connect. The session proves it; the memory Entity is created eagerly under the account's display name so profile/commitments resolve from the first turn. No deliberation.
2. **Passive** — [identity/detection.py](backend/identity/detection.py) reads "moi c'est Thomas" off an ordinary turn (pure regex, no LLM: it runs on *every* inbound message). Files an `IdentityClaim` as `PENDING` and **binds nothing**. Deliberately conservative — `_NOT_NAMES` rejects states and roles ("je suis fatigué", "je suis développeur"), and a greedy two-word capture falls back to one word so "je ne suis pas Thomas en fait" still reads as a denial.
3. **Active** — Mika's own MCP tools. Accepting a claim is what actually binds the handle to an Entity.

**Se laisser convaincre** — on a channel with no login, recognition is earned. `EVIDENCE_WEIGHTS` is calibrated against the disclosure bar (0.70): `self_declared` 0.20 alone never clears it, `shared_memory` 0.50 alone never clears it (knowing a fact about Thomas doesn't make you Thomas), but **claim + corroboration lands exactly on it**. `corroboration_score()` measures lexical overlap between what was just said and what memory holds about the claimed person (≥3 distinct content words — one is coincidence, two is a common topic). Counter-evidence subtracts: `contradicted` −0.35, `denied` −0.50, `revoked` −1.0.

**Disclosure gating** — `may_disclose_private_context()` decides whether per-person memory reaches the prompt at all:
- authenticated → always
- account channel → needs `CORROBORATED`
- **public room → never, at any certainty**. The risk in a group isn't mistaken identity, it's the audience. She can greet someone warmly and talk normally; she just doesn't read out their file. A turn happening in public overrides whatever the private handle earned.

`_fetch_person_context()` returns only the affective stance below the bar — Mika's own feeling toward the handle is hers, the other person's history is not.

**Denial applies immediately**, without waiting for deliberation: if she's calling a stranger by a friend's name, everything downstream is already wrong. It unbinds when it targets the current binding.

- **Models** ([identity/models.py](backend/identity/models.py)): `Identity` (+`certainty`, `bound_at`, `bound_via`, `binding_reason`), `IdentityHandle` (+`trust`, `is_ephemeral`), `IdentityClaim` (the audit ledger: every reason to believe or stop believing, with what it was worth). Migrations `identity/0002`, `identity/0003` (flags legacy `anon_*` handles).
- **MCP tools** ([identity/module.py](backend/identity/module.py), registered via `identity/apps.py`): `identity_whoami_with`, `identity_check_story`, `identity_accept_claim`, `identity_reject_claim`, `identity_record_evidence`, `identity_forget_binding`. The current person is ambient via a ContextVar ([pipeline/tracing.py](backend/pipeline/tracing.py)) — from inside a turn "the person" is implicit, so the model never has to repeat an id it never sees.
- **Prompt**: `--- QUI TU AS EN FACE ---` sits immediately before `--- CE QUE TU SAIS DE CETTE PERSONNE ---`, because it qualifies it ("here is Thomas's history" reads very differently after "someone *claims* to be Thomas"). Never prints a number — prompt text reads as a feeling, or the model starts quoting percentages back at the user.
- **Consolidator**: souvenirs are now linked to the *interlocutor's* entity, not only to entities the extractor happened to name in the content. A conversation where nobody says their own name used to produce souvenirs attached to nobody, so `PersonProfile` never had material to generate from.
- **Retention**: ephemeral `anon_*` handles expire after 7 days, orphan `Identity` rows are swept, resolved claims kept 180 days (pending ones protected).

**Frontend is authenticated** — `CONSUMER_REQUIRE_AUTH` defaults to `True`; the WebSocket refuses anonymous connections. `GET /auth/whoami` reports `auth_required` + `needs_bootstrap` so the client renders the right screen, and `POST /auth/bootstrap` creates the **first** account (409 forever after) so a fresh clone isn't locked out before `createsuperuser` is run. `AUTH_PASSWORD_VALIDATORS` is now configured — without it `validate_password` was a no-op and the account owning the dashboard (conversation history + provider API keys) could have been "123".

### Self-concept and theory of mind

Two layers built on top of the memory system regenerate periodically during consolidation:

- **Self-narrative** (`memory/narrative.py` → `SelfNarrative` model): first-person paragraph "Je suis quelqu'un qui…" synthesized from recent souvenirs + connaissances + emotional summary. Regenerated every ~24h if ≥5 new souvenirs. Injected into the system prompt between personality and person-context, so Mika has an evolving sense of who she's becoming.
- **Person profile** (`memory/person_profile.py` → `PersonProfile` + `Commitment` models): per-person model — summary, closeness (stranger/acquaintance/friend/close), preferred tone, topics of interest, sensitive topics, pending commitments ("tu lui avais dit que..."). Regenerated per active person (seen in last 14 days, ≥3 new souvenirs, ≥24h since last). Injected in the prompt when Mika talks to a known person.

Commitments are a 3rd type of extraction produced by the same consolidator LLM call that extracts souvenirs/connaissances.

### Sleep Cycle ([memory/sleep.py](backend/memory/sleep.py))

Counterpart to the Conscience. The consolidator runs all day doing maintenance; the Sleep Cycle runs **only at night** doing creative, narrative, and healing work the reactive pipeline cannot.

**Triple gate** — all must pass for any sleep phase to run:
1. Current hour ∈ [23h, 6h) (`_is_night()`)
2. `conscience.get_idle_seconds() ≥ 900` (15 min without interaction) — always applies: an interaction wakes her mid-night
3. `drive_engine.states[REST].tension ≥ 0.5` (Mika earned her sleep) — **entry only**: once asleep for the night (`_asleep_night` hysteresis) the REST gate is skipped, because each sleeping tick *relieves* REST (`SLEEP_REST_RECOVERY` satisfy → tension melts over the first hours) and draining it must not bounce her awake. Morning-Mika actually wakes rested; before this, REST was never satisfied by anything.

**Three phases** (invoked by `run_if_due()`, driven from its **own dedicated background loop** started at ASGI lifespan — cadence `memory.sleep_check_interval`, default 60s; decoupled from the consolidator since 2026-04 so a 45s sleep LLM call never delays memory consolidation):

1. **Light sleep** — `_write_journal_if_due()`. One LLM call produces a `DailyJournal` for the date just ended: 1st-person recap narrative (2-4 sentences), key moment ids, dominant emotion, persons interacted, unresolved-at-sleep rumination snapshots. One row per date; re-runs refresh in place.

2. **REM** — `_maybe_dream()`. Picks 2-3 souvenirs of **distinct themes** (greedy anti-duplicate) + optionally one active rumination ≥ 0.3. Classifies the dream: `nightmare` (dominant negative or strong negative rumination), `pleasant` (dominant positive), `associative` (mixed), `mundane` (weak emotional signal). LLM generates a short oneiric narrative. `DREAM_PROBABILITY = 0.6`, `MAX_DREAMS_PER_NIGHT = 2`.

3. **Deep sleep** — `_digest_ruminations()` (03h-06h, once per night). For active ruminations older than 120min:
   - Decay ×3 (15% intensity lost per pass vs 5% normal)
   - Forced emotion drift via `DIGESTION_DRIFT` (e.g. `frustrated → relieved`, `anxious → relieved`, `angry → thinking`)
   - Intensity ≥ 0.4 → converted into a **reflective Souvenir** ("Après y avoir repensé cette nuit: …")
   - Intensity < 0.15 post-decay → marked `faded`

**Observable phase state** (`SleepPhase`): `awake | light_sleep | rem | deep_sleep`. Transitions call `_set_phase()` which pushes a `broadcast_inner_state_update` event so the frontend reacts immediately (dim lights, close eyes, slow breath). Singleton `sleep_cycle` at module level.

A phase is entered **only when it has work to do**, and the tick ends by settling into `DEEP_SLEEP`. Announcing `LIGHT_SLEEP` then `REM` unconditionally every tick made the frontend replay its 1.2–1.8s eye/lighting eases twice a minute all night. REM attempts are additionally spaced by `DREAM_ATTEMPT_INTERVAL_S` (45 min) — closer to real REM cycles, and it stops the loop re-entering REM on every 60s tick.

**Prompt integration** — morning recall (6h-14h): a non-recalled `Dream` with `vividness ≥ 0.6` for last night gets injected as the `--- CE QUE TU AS REVE CETTE NUIT ---` block, then auto-marked `recalled_at` so it never repeats. Framed as "tu peux le mentionner si ça tombe" — Mika can spontaneously talk about it or not. Yesterday's `DailyJournal` is injected all day as `--- TON FIL D'HIER ---` (see system prompt structure), and any journal is re-readable on demand via the `memory_read_journal` tool. Note the journal is dated the day it **covers**: readers (`inner_state`, `/dashboard/api/sleep`) query most-recent-of-{today, yesterday}, not strictly today — strict matching left the panel blank from midnight to 23h.

**Frontend integration** (end-to-end, live):
- `sleep_phase`, `today_journal`, `last_dream` included in every `inner_state` payload (both `speech` and the new standalone `inner_state_update` events)
- `AnimationMixer.setSleepPhase()` — eyes close (0.85-1.0), breath × 0.45-0.7, REM flicker, head tilt 0.12-0.25 rad, 1.2s eased transitions
- `Environment.setSleepPhase()` — lights × 0.22-0.55, background tint lerps toward dark blue, 1.8s eased
- `TTSService.requestWakeUpDelay(ms)` — first reply after waking gets 1.3s of silence to sound like waking up, not a bot responding instantly
- `InnerLifePanel` — "Rêve de cette nuit" + "Journal d'aujourd'hui" sections, sleep badge in header when not awake

**Debug endpoints** ([communication/debug_views.py](backend/communication/debug_views.py)) — all gated by `settings.DEBUG`:
- `POST /api/dev/sleep/phase {phase}` — force a phase, bypasses gates
- `POST /api/dev/sleep/journal` — run light-sleep LLM call NOW
- `POST /api/dev/sleep/dream` — run REM LLM call NOW (bypasses probability + cap)
- `POST /api/dev/sleep/digest` — run deep-sleep digestion NOW
- `POST /api/dev/sleep/wake` — reset to AWAKE
- `GET  /api/dev/sleep/status` — current phase + today's journal + last dream

**Metaphor recap**: Conscience = waking state (observe + act). Consolidator = maintenance bookkeeper. Sleep Cycle = dreaming state — creativity (dreams), narrative coherence (journal), emotional healing (digestion).

### Projects ([projects/](backend/projects/))

Standalone Django app. Mika as an **agent with explicit work engagements**: projects have a title, a frame of execution (tone, emotion policy, instructions, out-of-scope), allowed resources (modules, paths, contacts), a schedule, and a task list. User-confided or self-initiated.

**Critical default** — projects have **`emotion_policy = OFF`** out of the box. When a project is active and matches the current turn (or runs on schedule), Mika drops her [EMOTION:] tag, variability block, and all affective reasoning. She's in professional mode. Turn this back on explicitly (`muted` or `full`) only if the user asks.

**Models** ([projects/models.py](backend/projects/models.py)):
- `Project` — title, description, origin (user/self), status, priority, `tone_directive`, `emotion_policy`, `instructions[]`, `out_of_scope[]`, `requires_approval`, `allowed_modules[]`, `resource_paths[]`, `contacts[]`, `schedule_rule`, `next_run_at`, `runs_since_user_input`, owner (FK Entity)
- `ProjectTask` — per-project granular work (`todo` / `in_progress` / `done` / `blocked`) with `order`, `result`, `blocked_reason`
- `ProjectLog` — audit trail, one row per advance/report/error
- `ProjectPendingAction` — queue of side-effect actions awaiting user approval (payload dispatched on approve)
- `ProjectPromptHistory` — rolling buffer of (system_prompt, user_prompt, raw_response, parsed_output, outcome, duration_ms) per project. Size controlled by `PROJECT_PROMPT_HISTORY_SIZE` (default 30, `0` disables). Pruned automatically after each insert by `_prune_history`. Admin-visible, read-only.

**Schedule rules** ([projects/schedule.py](backend/projects/schedule.py)):
- `""` / `"manual"` — advance only on explicit push
- `"interval:5m"` / `"interval:30s"` / `"interval:2h"` — recurring interval (floor 5s)
- `"cron:0 9 * * MON-FRI"` — cron expression (uses `croniter` if installed, falls back to a minimal 5-field parser supporting DOW names + ranges)
- `"idle:30m"` — fires when conscience idle seconds >= window **and** `next_run_at` has passed. Without the second condition an `idle:` project advanced on *every* runner tick once the window was reached, burning 10 back-to-back LLM calls in ~5 min until `runs_since_user_input` capped it
- `"event:email.received"` — `ModuleManager.emit_event` calls `runner.notify_event(event_type)` after the conscience + module fan-out, which sets `next_run_at = now` on exact-matching active projects. (The hook was missing until 2026-07: the rule parsed but could never fire.)

**Runner** ([projects/runner.py](backend/projects/runner.py)): `project_runner` singleton with its **own dedicated background loop** started at ASGI lifespan — cadence `projects.runner_interval`, default 30s; decoupled from the consolidator since 2026-04 so `interval:30s` actually fires at 30s and a blocked 90s LLM advance never starves memory consolidation. Per tick: lists due projects, advances up to 3 in priority order, builds a scoped context (no emotion/ruminations/circadian — just project frame + tasks + recent logs + resources), calls the LLM (Haiku), parses a structured JSON output (`summary`, `task_updates`, `new_tasks`, `report_to_user`, `proposed_action`), writes DB changes, logs the tick, bumps `next_run_at`. Side-effect actions on `requires_approval=True` projects queue as `ProjectPendingAction` instead of executing.

**Runner safeguards**: `runs_since_user_input` caps infinite auto-advance at 10 ticks without user feedback. `MAX_ADVANCES_PER_TICK = 3` prevents LLM bursts.

**Detection in conversation** ([projects/detection.py](backend/projects/detection.py)): heuristic (no LLM) matching message tokens vs `title` + `keywords` + owner. When a match above threshold 0.4 is found:
- `project_context` is injected as `--- PROJET EN COURS ---` in the system prompt
- If `emotion_policy=OFF`: the variability block and mandatory [EMOTION:] instruction are removed from the personality prompt; the emotion context block is suppressed entirely; the per-person PAD impulse is skipped on reply; the post-action audit rumination is skipped.
- `ConversationContext.project_id` is propagated so downstream hooks know what's active.

**MCP tools** ([modules/project_tools/module.py](backend/modules/project_tools/module.py)) — registered as a module so Mika can call them during a normal conversation:
- `create_project` — formalize a user-confided engagement, full field set (title, tone, emotion_policy, schedule_rule, requires_approval, ...)
- `list_projects`, `get_project_details`, `add_project_task`, `update_project_task`
- `propose_project_action` — queue a side-effect action for approval
- `update_project` — pause / retune / reschedule

**HTTP API** ([projects/urls.py](backend/projects/urls.py), [projects/views.py](backend/projects/views.py)):
```
GET    /api/projects/                          list
POST   /api/projects/create                    create
GET    /api/projects/<id>                      detail + tasks + recent logs + pending
PATCH  /api/projects/<id>                      update fields
DELETE /api/projects/<id>
POST   /api/projects/<id>/tasks                add task
PATCH  /api/projects/<id>/tasks/<tid>          update task
DELETE /api/projects/<id>/tasks/<tid>
GET    /api/projects/pending/                  list pending actions
POST   /api/projects/pending/<id>/approve      approve + execute payload
                                               (send_email goes through the email
                                                module's real async send via the
                                                public `EmailModule.send_email`
                                                façade; a failed send marks the
                                                action FAILED, never "executed")
POST   /api/projects/pending/<id>/reject       reject with note (writes a ProjectLog)
GET    /api/projects/<id>/history              last N prompt/response pairs
                                               (query: limit=30 cap 100, full=1 for
                                                the raw system_prompt + raw_response)
```

**Frontend** — [InnerLifePanel](frontend/src/ui/InnerLifePanel.ts) gains:
- A `⚠ Actions en attente de ton accord` section at the top with Approve/Reject buttons (click → `POST /api/projects/pending/<id>/...`)
- A `Projets en cours` section with progress bar, priority icon, schedule, next run time, blocked task count
- New WS message type `project_report` — silent message pushed to chat overlay when the runner finishes a tick with user-facing text (no TTS, no emotion animation)

**Metaphor**: Projects = Mika's **professional self**. Silent work that progresses during her idle time; activated on-demand with a strict frame when her attention is invoked. Kept orthogonal to the emotional/relational life by default.

### Voice output — a routed modality ([pipeline/voice.py](backend/pipeline/voice.py))

Speech is **not** a frontend detail: text and audio leave Mika through the *same* channels, and whether she speaks is a routing decision made backend-side.

**Delivery registry** ([communication/delivery.py](backend/communication/delivery.py)) — `presence_registry` says *where* a person is reachable; this registry says *who can send* there. Needed because a communication channel isn't necessarily a module: `TelegramChannel` lives in `communication/channels/` and is never registered with `module_manager`, so `get_module("telegram")` always returned `None` and the caller fell back to a global broadcast (leaking a message composed for one person to every connected browser). `get_channel(name)` resolves registered channels first, then modules. Targeted messages that cannot be delivered are now **logged and dropped**, never broadcast.

**Three sinks**, with genuinely different context rules:

| Sink | Where | Policy |
|------|-------|--------|
| `SCREEN` | frontend app (browser TTS) | speaks by default; silent with no client connected |
| `MESSAGE` | async voice note (Telegram voice, SMS) | time of day is irrelevant — the recipient plays it when they choose. Only an explicit mute suppresses it |
| `SPEAKER` | open-air speaker in a shared room | strictest: silent during quiet hours (22h–8h), while Mika sleeps, and (for addressed speech) when nobody's in the room |

`decide_voice(sink, *, hour, sleep_phase, person_present, muted, persona) -> VoiceDecision(speak, reason)` is a **pure function** — the whole policy is unit-testable without a running system. The reason string is logged and shipped to the frontend so silence is never mysterious.

**Two voice personas** — `VoicePersona.SPEAKING` (addressed to a person) and `VoicePersona.INNER` (thinking out loud). Her inner monologue gets its own vocal identity via `VOICE_PROFILES`: quieter (gain 0.45), slower (rate ×0.9), slightly lower (pitch ×0.94) — it reads as thought overheard, not a sentence said to you. Two policy consequences: an inner thought is **never** sent as a voice note (you don't mail your stray musings to someone's phone), and it **may** be spoken to an empty room (nobody is disturbed, and that is exactly how a mind at work sounds). `persona_for_source(source, addressed=)` classifies a turn: `INNER_SOURCES = {conscience, drive, rumination}` unless the turn deliberately targets a person.

**Audible inner monologue** ([pipeline/inner_voice.py](backend/pipeline/inner_voice.py)) — when Mika acts on her own, she murmurs *"oh tiens, si j'envoyais un message à Alice..."*, *"mmm... oh mais c'est génial ça, je continue !"*. That murmur is **generated, not reused**: `generate_inner_thought(action, result, *, mood)` makes a dedicated small-model call (`AIRole.INNER_VOICE`, 12s timeout) from *what she's about to do* + *what just came back*. Never the raw action summary, which reads like a report. Output is cleaned (quotes/prefixes stripped) and capped at 160 chars — a long thought stops sounding like a thought. Every failure path (quota, timeout, blank output) returns `None`: **silence is a valid outcome**, an error is never surfaced as a thought. Wired into `project_runner._murmur()` after each advance tick; broadcast with `source="conscience"` so the INNER persona applies.

**Pluggable synthesis** — `register_synthesizer(synth)` installs a `SpeechSynthesizer` (Piper, edge-tts, an API). **None is registered by default**: the frontend does its own TTS, so `MESSAGE`/`SPEAKER` delivery falls back to text until one is installed. `synthesize()` never raises — a broken TTS degrades to text delivery, it does not drop the message. Telegram declares `VOICE_SINK = MESSAGE` and implements `deliver_voice()` (OGG/Opus → `send_voice`, anything else → `send_audio`, captioned with the text).

**Frontend contract** — the `speech` payload carries `speak` (bool), `voice_reason` (str), `voice_persona`, and `voice_profile` ({pitch, rate, gain}). [main.ts](frontend/src/main.ts) honours `speak: false` by showing the text and animating the avatar without speaking; `TTSService.speak(text, emotion, profile)` applies the persona multipliers **on top of** the emotion modulation (an excited *thought* is still quieter than an excited sentence), clamped to the Web Speech API's accepted pitch/rate ranges.

### System prompt structure

Assembled by `build_system_prompt()` ([pipeline/prompt.py](backend/pipeline/prompt.py)) in this order:

1. **Personality** (static, from `personality.yaml`) — includes a `--- VARIABILITÉ NATURELLE ---` sub-block encouraging variable response length, backchannels ("hmm", "attends"), hesitations, selective echo, non-mandatory relances, and prosodic tokens (`[SIGH]`, `[LAUGH]`, `[PAUSE:ms]`, `[BREATH]`). *Stripped* when an active project has `emotion_policy=OFF` (professional mode).
2. **`--- QUI TU ES DEVENUE ---`** (self-concept, evolving paragraph)
2bis. **`--- QUI TU AS EN FACE ---`** (identity certainty + pending identity claims — see "Identity & trust"). Qualifies the block below; silent for internal person_ids.
3. **`--- CE QUE TU SAIS DE CETTE PERSONNE ---`** (person profile + affect + weekly trend + commitments). **Gated on identity certainty**: below the disclosure bar only the affective stance is injected, never the profile/history/commitments.
4. **`--- CE QUE TU PERCOIS DE SON ETAT ---`** (heuristic read of user's current emotional tone: caps, punctuation, lexique, emojis, length — `detect_user_mood_hint` in `pipeline/context.py`)
5. **`--- TON RYTHME ---`** (circadian phase + energy level, from `emotion/circadian.py`)
6. **`--- ETAT COGNITIF ---`** (fatigue fog: 4 tiers below energy 0.5 shaping the TONE, not just the act/wait threshold)
7. **`--- CE QUI TE TROTTE DANS LA TETE ---`** (active ruminations — previously only visible during `_act()`, now every turn)
8. **`--- CE QUE TU AS REVE CETTE NUIT ---`** (non-recalled dream with vividness ≥ 0.6, morning 6h-14h window only, auto-marked recalled on first injection)
8bis. **`--- TON FIL D'HIER ---`** (yesterday's `DailyJournal` narrative, capped ~450 chars + persons + dominant emotion — day-to-day continuity all day long, skipped for internal person_ids)
9. **`--- PROJET EN COURS ---`** (current engagement that matches the turn — title, tone_directive, instructions, out_of_scope, emotion_policy, todo tasks). When `emotion_policy=OFF`, suppresses the emotion block below.
10. **`--- CONTEXTE MODULES ---`** (email backlog, RSS unread, etc.)
11. **`--- TON ETAT EMOTIONNEL ACTUEL ---`** (global mood with ambivalent blend phrasing + drives). *Suppressed* when active project is in professional mode.
12. Memory context (semantic retrieval of relevant souvenirs/connaissances)

Personality + self-concept + person-context + circadian are the "slow" layers (stable over a session or shifting by the hour); module/emotion/memory/user-mood/fatigue/ruminations/dream/project are recomputed every turn. Recency bias places the latter last.

### Frontend (Vite + Three.js + VRM)

- **Entry**: [frontend/src/main.ts](frontend/src/main.ts) — initializes 3D scene, loads VRM, connects WebSocket, wires TTS + lip-sync + face emotions + a single `AnimationSystem` facade for ALL body animation
- **Shared types**: `src/types/` — `EmotionName` (29, derived from a const array + `isEmotionName` guard), `SleepPhase`, wire message interfaces (`SpeechMessage`, `InnerState`, `ServerMessageMap`…), animation/manifest types, and the **reserved v2** `avatar_state` contract (`AvatarStateSnapshot`: backend-authoritative body-state broadcast, designed not implemented). These types are NEVER re-declared per file.
- **3D**: `src/scene/` — `SceneManager` (render loop; `clock.getDelta()` clamped to 50ms so tab-restore spikes can't explode the spring bones), `Environment` (`setSleepPhase()` light dimming + bg tint; `getAnchor()` v2 locomotion seam, returns undefined for now), `CameraController` (orbit target follows the avatar root via `setFollowTarget(object3d, offset)`; falls back to the legacy constant on the placeholder path)
- **VTuber**: `src/vtuber/` — `VTuberModel` (VRM under an `AvatarRoot` group at (0,0,-0.5) rot Y-π — v2 locomotion moves this root, clips animate in model-local space), `EmotionController` (FACE only: 29 emotions → blend shapes with rich-model fallback)
- **Body animation**: `src/vtuber/animation/` — Mixamo-clip-based layered system:
  - `AnimationSystem` — facade main.ts wires; per-frame order: `humanoid.resetNormalizedPose()` + `applyRestPose()` → state machine → `THREE.AnimationMixer` (rooted at `normalizedHumanBonesRoot`) → additive overlays (breathing spine, sleep neck tilt, emotion head pose — quaternion compose, never absolute Euler writes) → `HandAnimator` (30 finger bones, absolute — finger tracks are stripped from clips) → `GazeController` (eye bones, absolute — Mixamo has no eye bones) → `BlinkController` → `FaceIdleController`
  - **Face layers** — four writers on **disjoint** expression-name sets, so they compose with no arbitration: `EmotionController` owns the emotion shapes (`Smile1`, `Angry1`…, with a few-percent breathing pulse on the written value so a held emotion never freezes), `LipSyncController` owns `aa`/`oh`/`ih`/`ee`, `BlinkController` owns `blink` (three flavours — quick / double / soft — with an emotion-modulated cadence, faster while speaking), and `FaceIdleController` drives the model's **ARKit perfect-sync** shapes (`BrowInnerUp`, `MouthDimpleLeft`, `CheekSquintRight`…): continuous micro-drift with deliberately different L/R noise rates, plus per-emotion brow/nose/cheek accents. That last layer exists because `neutral` maps to an **empty** expression set on this model — without it the face only blinks and reads as a mask next to a clip-animated body. Amplitudes stay small on purpose: VRM expression binds ACCUMULATE (`+=`) and the custom emotion shapes already bind some of the same morph targets. Shapes are resolved against the model once, so a VRM without perfect-sync degrades to blink + emotions.
  - `mixamoRetarget.ts` — runtime FBX→VRM retarget (official three-vrm algorithm): prefix detection, rest-pose conjugation, VRM0 x/z flip (`metaVersion "0"`), hips position scaled by `normalizedRestPose` height ratio (LOCAL position — cm-space trap), finger/scale/non-hips-position tracks stripped, per-clip report
  - `AnimationStateMachine` — states idle/talking/gesture/sleeping (+ reserved v2 walking/interacting behind `LOCOMOTION_ENABLED=false`); single `playClip` crossfade primitive (reset→play→crossFadeTo, never a snap); one-shot gestures fade back BEFORE clip end with `clampWhenFinished` as safety net; weighted idle pools with per-clip `hold`; talk-pool rotation at 4-9s IS the talk-beat cadence
  - `ClipLibrary` — manifest-driven ([public/animations/manifest.json](frontend/public/animations/manifest.json)); synthetic rest clip (A-pose) always available so missing assets degrade to a breathing, blinking, finger-fidgeting Mika — never frozen, never T-pose; first idle clip loads with priority, rest streams at concurrency 3, per-file failures isolated
  - `gestures.ts` — `EMOTION_GESTURE` table (`satisfies Record<EmotionName, …>` = compile-checked 29-way exhaustiveness) + pure `decideGesture()` with gate order: sleep → inner-persona → ambivalence (blend[1] ≥ 0.85×blend[0] = stillness) → per-emotion threshold → 8s cooldown (oneshots only). ~13 one-shots, 3 idle variants (weight-0 manifest entries: never picked spontaneously), ~11 face-only
  - `AnimationDebugger` — Alt+M cycle clips (THE retarget check), Alt+K skeleton, Alt+J report, Alt+S/E/T/G force sleep/emotion/talking/gestures, Alt+D panel (`?animdebug=1` auto-opens)
  - Mixamo FBX files are downloaded manually by the user (Adobe account required) — [frontend/public/animations/README.md](frontend/public/animations/README.md) has the ~19-clip list + exact export settings (FBX Binary, Without Skin, 30 FPS, no keyframe reduction)
- **Audio**: `src/audio/` — `TTSService` (Web Speech API, emotion-based pitch/rate, `requestWakeUpDelay(ms)`, `onProsodicCue` callback fires on `[SIGH]/[LAUGH]/[BREATH]` in sync with their audio → body gesture beats), `LipSyncController` (French phoneme mapping, expressions only)
- **UI**: `src/ui/` — `ChatOverlay`, `EmotionDisplay` (29 emotion labels in French with intensity %), `InnerLifePanel` (drives + emotion blend + self-narrative + ruminations + person profile + sleep badge + dream-of-the-night + today's journal, with `onSleepPhaseChange` pub-sub)
- **Network**: `src/network/WebSocketClient.ts` — event-driven client with exponential backoff; typed `on()` overloads over `ServerMessageMap` (`speech`, `inner_state_update`, `project_report`, + local `connection`)
- **Frontend tests**: vitest (`cd frontend && npx vitest run`) — retarget math (prefix detection, VRM0 flip, hips scale, finger stripping, degenerate-track rejection), gesture gating, face-layer amplitude safety (micro + accent can never sum past 1.0 on a shared shape), type guards, plus a smoke suite that runs the real FBXLoader + retarget over every downloaded clip in `public/animations/` (auto-skips when none are present; excluded from `tsc` since it reads the filesystem). Not part of `npm run build` (tsc stays the hard gate).

**Speech flow**: WebSocket `speech` event → `isEmotionName` validation → face (`EmotionController`) + body (`AnimationSystem.setEmotion`: gaze bias, hand mood, head-pose overlay, gated gesture) + UI → TTS + lip-sync. TTS `onSpeakStart/End` → `AnimationSystem.setSpeaking` (talking clip pool). If Mika was asleep within 10s, TTS is prefixed by 1.3s of silence (wake-up pause).

**Sleep visual flow**: backend `SleepCycle._set_phase()` triggers `broadcast_inner_state_update` → frontend `WebSocketClient` dispatches `inner_state_update` → `InnerLifePanel` applies state → `onSleepPhaseChange` fans out to `AnimationSystem.setSleepPhase()` (crossfade to the slowed sleep clip + eye closure + doze tilt + deep breathing) + `Environment.setSleepPhase()` (scene dims). Frontend also stamps `lastAsleepAt` to wire the TTS wake-up delay.

A `.vrm` file at [frontend/public/models/default.vrm](frontend/public/models/default.vrm). Without it, a placeholder capsule+sphere is rendered.

## Key Conventions

- **29 emotions**: `neutral` | `happy`, `excited`, `love`, `proud`, `grateful`, `playful`, `amused`, `hopeful`, `relieved` | `sad`, `angry`, `scared`, `disgusted`, `frustrated`, `lonely`, `anxious`, `bored`, `jealous` | `surprised`, `thinking`, `confused`, `embarrassed`, `nostalgic`, `dreamy`, `determined`, `mischievous`, `curious`, `melancholic` — in `emotion/types.py::Emotion`
- **Emotion tag**: `[EMOTION:name:intensity]`. Legacy `[EMOTION:name]` = intensity 0.7
- **WebSocket protocol**:
  - Client → server: `{"type":"chat","message":"...","person_id":"...","attachments":[...]}`
  - Server → client (reply): `{"type":"speech","text":"...","emotion":"...","emotion_intensity":0.75,"emotion_blend":[{"emotion":"...","weight":0.x}, ...],"emotion_state":{...},"source":"...","inner_state":{...},"speak":true,"voice_reason":"screen_ok","voice_persona":"speaking|inner","voice_profile":{"pitch":1.0,"rate":1.0,"gain":1.0}}` — the voice fields come from [pipeline/voice.py](backend/pipeline/voice.py); `speak:false` means show the text but stay silent
  - Client → server (identity handshake, first frame): `{"type":"identify","person_id":"...","display_name":"..."}`. A `person_id` smuggled in a later `chat` frame is **ignored** — identity is bound at connect/identify time only
  - Server → client (state refresh, no TTS): `{"type":"inner_state_update","inner_state":{...}}` — pushed by `broadcast_inner_state_update()` when inner state changes outside of a conversation turn (e.g. sleep phase transitions during the night, project pending action queued). Frontend merges it into the `InnerLifePanel` + scene/animation without invoking TTS.
  - Server → client (project report, no TTS): `{"type":"project_report","project_id","project_title","text"}` — emitted when the project runner produces user-facing text from a tick. Shown as a prefixed message in the chat overlay.
  - `inner_state` payload shape: `{drives, energy, circadian, sleep_phase, today_journal?, last_dream?, projects?, pending_project_actions?, self_narrative?, ruminations, person_profile?, pending_commitments?}`
- **Perception Intent**:
  - `REQUEST_RESPONSE` — user/channel expects an answer (default)
  - `OBSERVATION` — passive stimulus (camera frame, ambient audio, file drop). No forced response; conscience observes.
  - `INTERNAL_TRIGGER` — Mika-driven (conscience `_act`, module `notify_ai`, drive overflow, rumination resurfacing). Broadcasts; `emit_event=False`.
- **Person identification**: transport handles (`user_{pk}`, `web_*`, `tg_{user_id}`, `anon_*`) are resolved to memory `Entity` rows **through the identity layer**, never by name equality — see the "Identity & trust" section. Internal IDs `conscience_mika`, `__global__`, `anonymous` are reserved and never identified.
- **Personality is config-driven**: edit [personality.yaml](personality.yaml) (name, language, tone, traits, quirks, values, temperament) — no code changes needed
- **Singletons** (module-level, imported throughout): `ai_router` (`ai.router`), `ai_client` (`ai.client`), `memory_manager` (`memory.manager`), `emotion_engine` (`emotion.engine`), `drive_engine` (`drives.engine`), `personality` (`config.personality`), `module_manager` (`modules.manager`), `conscience_engine` (`conscience.engine`), `narrative_generator` (`memory.narrative`), `person_profile_generator` (`memory.person_profile`), `sleep_cycle` (`memory.sleep`), `project_runner` (`projects.runner`). Circadian is pure-function only (no singleton) — any caller passes the current `datetime` + the personality's `CircadianProfile`.
- **Django settings** in [config/settings.py](backend/config/settings.py): `PROJECT_ROOT` = repo root (where `.env` and `personality.yaml` live), `BASE_DIR` = `backend/`
- **INSTALLED_APPS**: `ai`, `communication`, `emotion`, `drives`, `memory`, `conscience`, `modules`, `projects`, `identity`, `files`, `dashboard`, `configs`
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
| `AI_ROLE_INNER_VOICE` | No | `claude:CLAUDE_MODEL_LIGHT` | Murmured inner monologue. Fires far more often than a chat turn — keep a small model |
| `TIME_ZONE` | No | `Europe/Paris` | Aligns ORM `__date` bucketing with the naive local wall clock used by circadian/sleep/journal logic. Django's own default (`America/Chicago`) shifted day boundaries ~7h |
| `CORS_ALLOW_ALL_ORIGINS` | No | `False` | **Not** wildcarded in DEBUG: the dashboard API is unauthenticated, so `*` let any visited page read the conversation history and rewrite the config |
| `CORS_ALLOWED_ORIGINS` | No | `localhost:3000,127.0.0.1:3000,localhost:4173,127.0.0.1:4173` | Dev frontend origins, allow-listed explicitly |
| `AI_CALL_TIMEOUT` | No | `60` | Seconds before `process_message` gives up waiting on the AI |
| `DB_LOCK_TIMEOUT` | No | `30` | SQLite busy timeout (s). The 5s default surfaced as `database is locked` under the background loops |
| `API_PORT` | No | `8000` | Backend port |
| `API_HOST` | No | `127.0.0.1` | Bind address. Loopback by default because the dashboard is unauthenticated unless gated |
| `DASHBOARD_REQUIRE_AUTH` | No | `False` | Require an authenticated **staff** user for `/dashboard/*`. Needs a superuser (`python backend/manage.py createsuperuser`) |
| `CONSUMER_REQUIRE_AUTH` | No | `True` | Refuse unauthenticated WebSocket connections. On by default: the frontend is the one channel where Mika is *certain* who she is talking to. First run is handled by `POST /auth/bootstrap` (creates the first account, 409s forever after), so this does not lock out a fresh clone |
| `LOGIN_URL` | No | `/admin/login/` | Where the dashboard gate redirects unauthenticated HTML requests |
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
| `SLEEP_CYCLE_ENABLED` | No | `True` | Master switch for the nighttime sleep cycle (journal + dreams + digestion) |
| `SLEEP_CHECK_INTERVAL` | No | `60` | Cadence of the dedicated sleep-cycle loop (s). Restart required on change. |
| `PROJECT_PROMPT_HISTORY_SIZE` | No | `30` | Rolling-buffer size of LLM prompt/response pairs kept per project (audit/debug). Set to `0` to disable capture entirely. |
| `PROJECT_RUNNER_INTERVAL` | No | `30` | Cadence of the dedicated project runner loop (s). Restart required on change. |
| `FORGE_DIR` | No | `data/forge_modules` | Confined directory holding AI-forged modules. Runtime limits (`forge.*`: handler timeout, quotas, breaker threshold…) are config-service keys, not env vars. |

## Testing notes

- `pytest.ini` uses `pytest-django` and `asyncio_mode=auto`
- Scoring tests share a `_score(ctx)` helper that pre-marks all greeting periods as done, isolating them from wall-clock time (otherwise tests run at 7–10h, 18–20h, or 23h+ get an extra +0.35 from the time-greeting factor)
- DB tests with `transaction=True` often need an autouse fixture to truncate leaked rows from prior non-transactional `django_db` tests — this pattern appears in `test_self_narrative.py`, `test_person_profile.py`, `test_sleep.py`
- **Sleep cycle tests** (`test_sleep.py`, `test_sleep_debug_views.py`): cover phase gates, night detection, dream classification, rumination digestion, dream persistence, phase transition broadcasts, and the debug HTTP endpoints. LLM calls are mocked — the LLM prompts themselves are not unit-tested.
- **Project tests** (`test_projects.py`): schedule parser (interval/cron/idle/event/manual), model defaults (critical: `emotion_policy` defaults to OFF), project detection heuristic, prompt injection + emotion suppression, runner JSON extraction, HTTP endpoints (create/list/detail/patch, task add/update, pending approve/reject, prompt history), MCP `create_project` handler, rolling-buffer prune (respects `PROJECT_PROMPT_HISTORY_SIZE=0` as disable).
- **Forge tests** (`test_forge_sandbox.py`, `test_forge_store.py`, `test_forge_api.py`, `test_forge_host.py`): AST validator (rejects imports/dunders/`_`-attrs/`.format`/async, accepts legit code), frozen exec env, deadline tracer, manifest validation, version archive/rollback/trash, storage quotas + module isolation, HTTP allowlist + private-IP block, notify cooldown / emit rate limit, and the full host lifecycle (write→load→tick→events→breaker→commands→views sanitization→dynamic config→MCP tools). `test_forge_host.py` uses `django_db(transaction=True)` because forged handlers run in worker threads (committed rows must be visible cross-connection).
- **Dashboard auth tests** (`test_dashboard_auth.py`): gate off = pass-through, HTML redirect vs API 401, staff-only, non-`/dashboard/` paths never gated, and the three secure defaults (`DASHBOARD_REQUIRE_AUTH=False`, `API_HOST=127.0.0.1`, CORS not wildcarded).
- **Sanitization tests** (`test_dashboard_sanitize.py`): `html`/`js`/`template` stripped at every nesting level including inside `rows` and `tabs`, depth cap, the `allow_raw_html` opt-in, and that the Forge re-exports the shared implementation.
- **Config record tests** (`test_config_record_validation.py`): a row with `temperature: "hot"`, an out-of-range value, or an unknown `provider` is rejected at write time rather than blowing up later in the AI router.
- **Retention tests** (`test_retention.py`): both policy shapes (age, row ceiling), the `protect` filter, throttling to once per hour, and a consistency test asserting every policy targets a real model/field with at least one ceiling — it caught `ConsolidationLog` using `ran_at` rather than `created_at`.
- **Identity tests** (4 files, ~110 tests):
  - `test_identity_trust.py` — pure policy: channel classification, floors/ceilings (a public claim can never reach `BOUND`), evidence arithmetic, and a **calibration guard** asserting `self_declared + shared_memory ≥ PRIVATE_CONTEXT_THRESHOLD` while neither alone clears it. Changing a weight without revisiting the threshold is exactly how a bare claim quietly becomes enough to unlock a private history.
  - `test_identity_detection.py` — self-introductions, denials, and the expensive false positives ("je suis fatigué", "je suis développeur", `Agent007`); greedy two-word capture falling back to one word; corroboration overlap thresholds.
  - `test_identity_resolver.py` — handle upsert idempotence, trust raised-never-lowered, the three binding paths, "accepting with proof actually unlocks disclosure", public-room override, denial unbinding, and `handles_for_entity_names` (dead until entities were actually bound).
  - `test_identity_tools.py` — the MCP surface, ambient person_id resolution, and that bad LLM-supplied arguments are *answered*, never raised.
- **Frontend auth tests** (`test_frontend_auth.py`): bootstrap window opens/closes, weak passwords rejected, `whoami` reports the server-issued `person_id`, and the consumer refuses anonymous sockets when required.
- **Runtime hardening tests** (`test_runtime_hardening.py`): the four fixes that cost real time or money on an install nobody is talking to — WAL/busy-timeout declared, a slow module no longer blocking the scheduler (and overlapping ticks skipped, finished ticks not leaked), RSS/forge events never reaching the LLM while `email.received` still does, and decay not compounding per tick (a 30-day-old connaissance decays once, then no-ops) while fresh rows aren't re-read at all.
- **Restart-continuity tests** (`test_memory_restart_continuity.py`): conversation resume window, chronological rehydration, scaffolding excluded, short-term limit respected.
- **Provider-cache tests** (`test_ai_router_provider_cache.py`): credential change evicts only that provider, and every entry in `_PROVIDER_CLASSES` has a credential prefix (a new provider added without one would silently keep stale keys).
- **Voice routing tests** (`test_voice_routing.py`): the per-sink context policy (quiet hours, sleep phase, presence, mute), the two voice personas, the voice→text delivery fallback chain, and the inner-thought generator (mocked LLM — asserts action *and* result both reach the prompt, that failures yield silence rather than an error string, and that output is de-quoted and length-capped).
- **Memory decay tests** (`test_memory_decay.py`): decay is relative to `Souvenir.decayed_at`, so conscience boosts survive, fresh low-importance souvenirs are not inflated, and a second immediate pass is a no-op.
- **Consolidator selection tests** (`test_consolidator_selection.py`): internal scaffolding excluded / reply kept, and a message inserted mid-pass is picked up on the next pass instead of being skipped forever.
- **Preprocessor tests** (`test_preprocessors.py`): vision caption path, audio transcription (mocked STT provider: bytes+filename reach it, base64 decoded, failures → placeholder, transcript capped), files extraction (text/json/html/latin-1/pdf-mocked/corrupt/unknown, truncation).
- **Telegram media tests** (`test_telegram_media.py`): voice/photo/document download → MediaAttachment, largest photo resolution picked, oversize rejected with notice, MIXED perception routed with caption.
- **Commitment lifecycle tests** (`test_commitment_lifecycle.py`): pending commitments fed to the extractor, `commitment_resolved` → honored/dropped, expiry (due_at, max age), extractor prompt block presence.
- **Memory tools tests** (`test_memory_tools.py`): tool surface, semantic search fan-out + kind filter, journal read (recent/date/missing), commitment list/resolve.
- **Journal context tests** (`test_journal_context.py`): yesterday-only injection, cap, prompt block.
- **Sleep REST recovery tests** (`test_sleep_rest_recovery.py`): entry-vs-stay hysteresis, interaction always wakes, sleeping tick relieves REST, daytime tick doesn't.
- Two tests are currently flaky due to wall-clock/circadian bias at run time (they assert positions that depend on the phase_bias home vector): `test_emotion_engine.py::TestTemperamentVariants::test_melancholic_returns_to_melancholic` and `test_scenario_troll.py::TestTrollWithStoicTemperament::test_stoic_global_barely_moves`. They pre-date the sleep work and are typically excluded in CI runs via `--deselect`.
