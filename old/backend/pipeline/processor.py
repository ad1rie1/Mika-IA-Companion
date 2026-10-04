"""Conversation processor — the full pipeline from Perception to broadcast.

Orchestrates: context -> response -> emotion -> persist -> broadcast.
Each step lives in its own module for readability and testability.

Entry point takes a ``Perception`` built by the router. Multimodal and
multi-part content flows through without string serialization: preprocessors
upstream enrich non-text parts with text descriptions that end up in
``perception.text`` when we need a prompt, but the structured parts are
preserved in the persisted ``Message.attachments_meta``.
"""

import asyncio
import dataclasses
import logging
import random
from dataclasses import dataclass

from old.backend.ai.quota import QuotaExceeded
from old.backend.ai.router import UnconfiguredRoleError
from old.backend.emotion.engine import emotion_engine
from old.backend.emotion.types import Emotion, EmotionData
from old.backend.identity.resolver import identity_resolver
from old.backend.pipeline.broadcast import (
    broadcast_to_websocket,
    emit_communication_event,
    persist_assistant_message,
    persist_user_message,
)
from old.backend.pipeline.context import ConversationContext, gather_context
from old.backend.pipeline.perception import Intent, Perception
from old.backend.pipeline.response import call_ai_and_parse


class _ReponseVide(Exception):
    """L'appel a réussi et n'a produit aucun texte.

    Mesuré sur ollama_cloud : ``thinking`` actif sur un tour outillé, et le
    plafond de sortie part entièrement dans le raisonnement — l'API répond
    200 avec ``response=0 chars``, sortie pile au plafond. Sans ce garde-fou
    la trame ``speech`` partait vide *et parlée*, la phrase vide était
    persistée comme quelque chose que Mika avait dit, et le tour comptait
    comme un échange réussi : impulsion émotionnelle, événement de chat,
    annonce ``_turn.completed``. Une réponse vide n'est pas une réponse.
    """

from old.backend.pipeline.signals import publish_turn_completed
from old.backend.pipeline.tracing import set_current_person_id, set_new_request_id
from old.backend.utils.degradation import degradations

logger = logging.getLogger(__name__)


def _compute_thinking_delay(
    response_text: str, energy: float, source: str
) -> float:
    """Return the seconds of simulated "thinking" to insert before broadcast.

    Purely cosmetic — the LLM call latency is already the bulk of the
    wait. This adds a human-sized floor so short responses ("ouais",
    "mdr") don't pop back instantly, which feels bot-like.

    Scaling:
      - Base: 250-600ms random jitter (always)
      - + ~8ms per word, capped at 1500ms
      - × (1.6 if tired, energy < 0.3)
      - × (0.7 if energetic, energy > 0.75)
      - Skipped entirely for internal triggers (conscience acted
        deliberately — shouldn't hesitate on top of her own decision)

    Total cap: 2000ms. We never want to make the user wait on us.
    """
    if source == "conscience":
        return 0.0
    if not response_text.strip():
        return 0.0

    word_count = len(response_text.split())
    jitter = 0.25 + random.random() * 0.35            # 250-600ms
    per_word = min(1.5, 0.008 * word_count)           # max 1500ms
    raw = jitter + per_word

    if energy < 0.3:
        raw *= 1.6
    elif energy > 0.75:
        raw *= 0.7

    return min(2.0, raw)


@dataclass
class SpeechOutput:
    """Result of processing a message through the pipeline."""
    text: str
    # What the reply's [EMOTION:] tag said, raw — ``None`` when it declared
    # nothing. Deliberately not the policy-filtered value: a module reading
    # this wants to know what the model said, not what the project mode did
    # with it.
    emotion_data: EmotionData | None
    emotion_name: str
    emotion_intensity: float
    emotion_state: dict
    tool_calls: list[str]
    request_id: str = "-"
    # Top-K emotion components for ambivalence display on the frontend.
    # List of {"emotion": str, "weight": float}.
    emotion_blend: list | None = None
    # True when the text is an error fallback, not a real AI answer.
    # Downstream: never spoken via TTS, and callers (conscience) must not
    # count it as a successful act.
    ai_failed: bool = False
    # Persistence cursors, carried into the broadcast so a client can tell
    # "this is the reply I was waiting for" from "this is a message I have
    # already displayed", and can ask for everything after it on reconnect.
    # None when the turn was not persisted (persist=False, or a write that
    # failed — a message the server did not record must not advance the
    # client's cursor past it).
    message_id: int | None = None
    user_message_id: int | None = None
    # Echo of the client-generated id the browser attached to its own bubble,
    # so a locally-painted message can be reconciled with its server row
    # instead of appearing twice after a history merge.
    client_msg_id: str | None = None
    # Le salon d'où la question est venue, sur le canal ``source`` — ce que
    # la diffusion préfère, pour une réponse réactive, à l'adresse mémorisée
    # dans le registre de présence (« le dernier salon où ce compte a été
    # vu »). ``None`` pour un tour qui n'en déclare pas (web, initiative
    # interne) : la diffusion garde alors ses règles.
    reply_ref: str | None = None


# -- Main entry point ---------------------------------------------------------


async def process_message(
    perception: Perception,
    *,
    context: ConversationContext | None = None,
    broadcast: bool = True,
    persist: bool = True,
    emit_event: bool = True,
    emotion_impulse: bool = True,
) -> SpeechOutput:
    """Full conversation pipeline: context -> AI -> emotion -> persist -> broadcast.

    Args:
        perception: The input stimulus. Carries source, person_id, parts, etc.
        context: Pre-built context (if None, gathered from the perception).
        broadcast: Whether to broadcast the response via WebSocket.
        persist: Whether to save the exchange in memory.
        emit_event: Whether to emit a ``chat.message`` module event after.
        emotion_impulse: Whether the reply's ``[EMOTION]`` tag moves the mood.
            False for a silent work step: the tag still travels in the frame,
            but a chantier step is not a lived exchange — its affect comes
            from the verdict (fierté, blocage), not from every intermediate
            sentence the model writes to itself.

    L'ordre des étapes est porteur — voir chaque étape. En deux mots : la
    question est écrite APRÈS le contexte (le tampon court terme la
    montrerait deux fois) et AVANT l'appel IA (la partie longue et fragile) ;
    un tour échoué est persisté avec une réponse ``is_internal`` mais ne
    produit ni impulsion, ni événement, ni annonce ``_turn.completed``.
    """
    request_id = set_new_request_id()
    source = perception.source
    person_id = perception.person_id
    # text property concatenates all text Parts. Preprocessors have
    # already serialized images/audio/files into text descriptions.
    message = perception.text

    # Bind the turn's person for the whole async context, so tool handlers
    # ("who am I talking to?") don't need the model to repeat an id it never
    # sees. Inherited by every coroutine awaited below.
    set_current_person_id(person_id)

    # What the transport itself proves about this turn. Absent metadata means
    # "no proof", which is the safe reading for any adapter that hasn't been
    # taught to say otherwise.
    authenticated = bool(perception.metadata.get("authenticated", False))
    is_public = bool(perception.metadata.get("is_public", False))

    await _identifier_passivement(person_id, message, source, authenticated)
    # Hydrate person mood from DB if evicted from RAM since last interaction
    await emotion_engine.ensure_person_loaded(person_id)
    timeout_seconds = _timeout_pour_le_log()

    ai_failed = False
    user_message_id: int | None = None
    tool_calls: list[str] = []
    try:
        # 1. Assemble context (memory, emotion, modules, self-concept, ...)
        context = await _contexte_du_tour(
            context, perception, message, authenticated, is_public,
        )
        # 1b. Write the question down, before attempting to answer it.
        if persist:
            user_message_id = await _ecrire_la_question(perception, message)
        # 2. Prompt -> AI call -> emotion extraction.
        response_text, emotion_data, tool_calls = await _interroger_le_modele(
            context, message,
        )
    except Exception as exc:
        ai_failed = True
        emotion_data = None
        response_text = _texte_de_repli(exc, person_id, source, timeout_seconds)

    # 3. Process emotion (only on success, never in professional mode).
    declared = await _ressentir(
        context, person_id, emotion_data, ai_failed, emotion_impulse,
    )

    # 4. Persist the reply — including a failed turn's fallback.
    assistant_message_id: int | None = None
    if persist:
        assistant_message_id = await _ecrire_la_reponse(
            response_text, person_id, source, ai_failed, user_message_id,
        )

    # 5. Announce the turn — event, `_turn.completed`, the dream consumed.
    if not ai_failed:
        await _annoncer_le_tour(
            perception, context, response_text, emotion_data, emit_event,
        )

    # 6. What this turn's frame carries.
    vue = await _vue_emotionnelle(person_id, declared)
    logger.info(
        "[%s/%s] %s -> %s (emotion=%s intensity=%.2f)",
        source, person_id,
        message[:60], response_text[:80],
        vue["emotion_name"], vue["emotion_intensity"],
    )
    output = SpeechOutput(
        text=response_text,
        emotion_data=emotion_data,
        tool_calls=tool_calls,
        request_id=request_id,
        ai_failed=ai_failed,
        message_id=assistant_message_id,
        user_message_id=user_message_id,
        client_msg_id=_client_msg_id(perception),
        reply_ref=_reply_ref(perception),
        **vue,
    )

    # 7. Broadcast (inner state follows). An internal trigger that failed is
    #    NOT broadcast at all: nobody asked a question, so an error fallback
    #    greeting/murmur would be pure noise — silence is the valid outcome.
    if broadcast and not (ai_failed and perception.intent is Intent.INTERNAL_TRIGGER):
        await _diffuser(output, source, person_id)

    return output


# -- Steps of a turn ----------------------------------------------------------


async def _identifier_passivement(
    person_id: str, message: str, source: str, authenticated: bool,
) -> None:
    """Passive identification: read the turn for "moi c'est Thomas" and file
    a claim. This never binds anything on its own — it only gives Mika
    something to notice and decide on. Failures are non-fatal by design:
    not knowing who someone is must never cost them their answer."""
    try:
        await identity_resolver.ingest_message(
            person_id, message, channel=source, authenticated=authenticated,
        )
    except Exception as exc:
        degradations.record("turn: passive identification", exc)


def _timeout_pour_le_log() -> float:
    """Lu pour le message de log seulement : la borne elle-même est posée par
    le routeur (voir ``_interroger_le_modele``)."""
    try:
        from old.backend.configs.service import config_service
        return float(config_service.get("ai.call_timeout_seconds"))
    except Exception:
        return 0.0


async def _contexte_du_tour(
    context: ConversationContext | None, perception: Perception, message: str,
    authenticated: bool, is_public: bool,
) -> ConversationContext:
    """Le contexte du tour — assemblé ici, ou reçu d'un appelant qui a le sien.

    Second statement of the mood-hint rule, and deliberately not a
    duplicate: a caller assembling its own context (the conscience does)
    cannot be made to declare the intent, and this is the only point that
    sees both. Without it, an action brief Mika wrote to herself is read as
    the recipient's tone — "besoin de vider son sac" about a text nobody
    sent.
    """
    if context is None:
        context = await gather_context(
            message, perception.person_id, channel=perception.source,
            authenticated=authenticated, is_public=is_public,
            intent=perception.intent,
        )
    if perception.intent is not Intent.REQUEST_RESPONSE and context.user_mood_hint:
        context = dataclasses.replace(context, user_mood_hint="")
    return context


async def _ecrire_la_question(perception: Perception, message: str) -> int | None:
    """Write the question down — deliberately *after* gather_context and
    *before* the AI call.

    After, because add_message also appends to the short-term buffer that
    gather_context just read — persisting first would hand the model the
    current message twice, once as history and once as the prompt. Before,
    because the AI call is the long fragile part: a restart during it used
    to erase the question itself, leaving someone with a bubble marked
    delivered and no trace on the server that they had spoken at all.

    A turn replayed after a restart already has its question in the
    database — that row is precisely how it was found (see
    pipeline/turns.py::resume_interrupted_turns). Writing it again produced
    a second row with the same text: duplicated in the person's fiche,
    duplicated for the consolidator, and displayed twice in the browser,
    since the merge only adopts bubbles that have no id yet and the original
    already had one. The rehydrated short-term buffer still holds that
    question, so the replayed turn shows it to the model once as history and
    once as the prompt. That is the cheaper of the two artefacts: dropping it
    from the buffer would leave the answer standing alone, without the
    question, for every turn that follows.
    """
    replayed_id = perception.metadata.get("original_message_id")
    if isinstance(replayed_id, int):
        return replayed_id
    internal = perception.intent is Intent.INTERNAL_TRIGGER
    # Une écriture qui échoue (base verrouillée) n'est pas une panne d'IA :
    # servir « j'ai eu un petit bug » sans avoir appelé le modèle privait la
    # personne d'une réponse que rien n'empêchait. On répond, on compte
    # l'échec, et la ligne manquante est la seule chose perdue.
    try:
        return await persist_user_message(
            message=message,
            source=perception.source,
            person_id=perception.person_id,
            attachments_meta=_serialize_attachments_meta(perception),
            # The "user" side of an internal trigger is scaffolding Mika
            # wrote to herself, not something anyone said.
            is_internal=internal,
            # Un brief interne n'est jamais rejoué : rien à retenir de son
            # transport.
            transport_meta=None if internal else _transport_meta(perception),
        )
    except Exception as exc:
        degradations.record("turn: persistance de la question", exc)
        logger.warning(
            "Question non persistée (person=%s, source=%s): %s — "
            "le tour continue sans ligne",
            perception.person_id, perception.source, exc,
        )
        return None


async def _interroger_le_modele(
    context: ConversationContext, message: str,
) -> tuple[str, EmotionData | None, list[str]]:
    """Prompt -> AI call -> emotion extraction ; lève ``_ReponseVide`` sur
    un texte vide.

    UNE seule borne temporelle, celle du routeur (``_metered_call``,
    ``ai.call_timeout_seconds``). Il y en avait deux, égales, l'une autour
    de l'autre : l'externe démarrait avant la construction du prompt et
    l'attente du créneau, donc tombait toujours la première — la coroutine
    interne recevait un ``CancelledError``, jamais un ``TimeoutError``, et
    le routeur ne comptait pas les jetons déjà payés d'une boucle d'outils
    morte à l'itération six. Le ``TimeoutError`` du routeur remonte ici tel
    quel.
    """
    response_text, emotion_data, tool_calls = await call_ai_and_parse(
        context, message,
    )
    if not (response_text or "").strip():
        raise _ReponseVide(
            f"{len(tool_calls)} outil(s) appelé(s), aucun texte produit"
        )
    return response_text, emotion_data, tool_calls


def _texte_de_repli(
    exc: BaseException, person_id: str, source: str, timeout_seconds: float,
) -> str:
    """Le texte servi à la place d'une réponse, selon ce qui a échoué.

    Une seule chaîne de cas, dans l'ordre historique des ``except`` : le
    dépassement, le rôle non configuré, le quota, la réponse vide, puis
    tout le reste — qui seul est un vrai bug, journalisé avec sa trace.
    """
    if isinstance(exc, asyncio.TimeoutError):
        logger.warning(
            "AI call timed out after %ds (person=%s, source=%s)",
            timeout_seconds, person_id, source,
        )
        return "Hmm, je reflechis plus lentement que prevu... Laisse-moi un instant."
    if isinstance(exc, UnconfiguredRoleError):
        # Configuration error, not a runtime bug: no model is mapped to the
        # role. One concise line — a traceback adds nothing actionable here.
        logger.warning(
            "IA non configurée (person=%s, source=%s): %s", person_id, source, exc,
        )
        # Nommer le rôle : « pas de modèle associé » sans dire lequel a
        # laissé plus d'une install fraîche chercher du côté de
        # ``conversation`` alors que c'est ``conversation_tools`` qui manquait.
        role_manquant = getattr(exc, "role", None)
        precision = (
            f" au role '{role_manquant.value}'"
            if getattr(role_manquant, "value", None) else ""
        )
        return (
            "Je ne suis pas encore configurée pour repondre... "
            f"Mon IA n'a pas de modele associe{precision} "
            "(Configuration > IA · Roles)."
        )
    if isinstance(exc, QuotaExceeded):
        # Hit a daily/monthly LLM quota. Return a truthful short message
        # instead of the generic "bug" fallback so the user knows why.
        logger.warning(
            "AI quota exceeded (person=%s, source=%s): %s", person_id, source, exc,
        )
        return (
            "Desolee, j'ai atteint la limite d'usage IA pour le moment. "
            "Reessaie un peu plus tard."
        )
    if isinstance(exc, _ReponseVide):
        logger.warning(
            "Réponse vide du modèle (person=%s, source=%s): %s — "
            "vérifie ai.<provider>.thinking et le plafond de sortie",
            person_id, source, exc,
        )
        return "Attends... j'ai perdu le fil, je n'ai rien reussi a formuler. Tu redis ?"
    logger.error(
        "AI error while processing message (person=%s, source=%s)",
        person_id, source, exc_info=exc,
    )
    # A light global-mood perturbation reflects Mika's own frustration
    # at her technical failure — not a relational emotion toward the user.
    emotion_engine.process_emotion(
        EmotionData(Emotion.ANXIOUS, 0.1), "conscience_mika",
    )
    return "Oups, j'ai eu un petit bug... Tu peux reessayer ?"


async def _ressentir(
    context, person_id: str, emotion_data: EmotionData | None,
    ai_failed: bool, emotion_impulse: bool,
) -> EmotionData | None:
    """Apply the tag as an impulse and snapshot the mood ; returns what this
    turn is entitled to claim as its emotion (``declared``).

    Only on success — a crashed AI is not the user's fault and should not
    color Mika's mood toward them — and never when a project with
    emotion_policy=OFF is active: work-mode replies must not color
    relational state. Deliberately non-fatal: a bookkeeping error here must
    not turn a real, already-received answer into the fallback.

    ``declared`` is the tag, when there is one and when nothing forbids it.
    A failure declared nothing (the fallback is not a sentence Mika wrote),
    and professional mode already suppresses the impulse — letting the tag
    colour the frame would put back through the window what
    emotion_policy=OFF throws out the door.
    """
    suppresses_emotion = bool(getattr(context, "project_suppresses_emotion", False))
    declared = emotion_data if not ai_failed and not suppresses_emotion else None
    if ai_failed or suppresses_emotion or not emotion_impulse:
        return declared
    try:
        # No tag means *no impulse*. NEUTRAL is not "nothing", it is the
        # origin of PAD space, so a default one pulled whatever the person
        # had just provoked back toward zero: a turn she had no tag for was
        # lived as a soothing.
        if declared is not None:
            # ``declared`` : c'est la balise du modèle, pas une impulsion
            # programmée — pour un acte sans destinataire (``conscience_mika``)
            # elle passe par la diffusion ordinaire, pas par le pas dosé de
            # la vie intérieure (voir ``_feel_for_herself``).
            emotion_engine.process_emotion(declared, person_id, declared=True)
        # Snapshot runs either way, so the drift between turns keeps being
        # archived even when a turn declares nothing.
        await emotion_engine.save_snapshot(person_id, declared=declared)
    except Exception:
        logger.exception(
            "Emotion post-processing failed (person=%s) — the reply itself "
            "is unaffected", person_id,
        )
    return declared


async def _ecrire_la_reponse(
    response_text: str, person_id: str, source: str, ai_failed: bool,
    user_message_id: int | None,
) -> int | None:
    """Persist the reply — including a failed turn's fallback.

    A failure used to drop the whole exchange, on the grounds that a
    fallback is not a real answer. True of the *answer*; false of the
    question — which is why the question is written at step 1b. Only the
    *reply* is demoted: marked internal, so the extractor never turns
    "j'ai eu un petit bug" into a souvenir and a restart doesn't rehydrate
    it as something Mika said. Everything else a failure withholds still
    is: no emotional impulse, no chat.message event, no turn signal.
    """
    try:
        return await persist_assistant_message(
            response=response_text,
            person_id=person_id,
            is_internal=ai_failed,
            # Closes the question: answered, well or badly. A fallback still
            # counts, or every boot would replay the same failing turn.
            replying_to=user_message_id,
        )
    except Exception as exc:
        # Même règle qu'à l'écriture de la question : une réponse déjà reçue
        # du modèle ne devient pas une panne parce que la base n'a pas pu la
        # garder. Elle part à l'écran ; la mémoire longue en perd la trace
        # et le registre le dit.
        degradations.record("turn: persistance de la reponse", exc)
        logger.warning(
            "Réponse non persistée (person=%s, source=%s): %s",
            person_id, source, exc,
        )
        return None


async def _annoncer_le_tour(
    perception: Perception, context, response_text: str,
    emotion_data: EmotionData | None, emit_event: bool,
) -> None:
    """Ce qu'un tour RÉUSSI dit au reste du moteur — jamais un tour échoué.

    5.  The ``chat.message`` module event.
    5b. ``_turn.completed``: everything that merely wants to *know* a turn
        happened — the drives relieving EXPRESSION, the conscience filing a
        "did I say that right?" rumination — subscribes to this instead of
        being called from here. Note what is NOT announced: the emotional
        impulse and the identity ingest are pipeline *steps*, not listeners —
        their effects are read within the same turn. See pipeline/signals.py.
    5c. The dream consumed, now that the turn actually happened. Marking it
        during gather_context spent it before the AI call: a timeout on the
        first message of the morning burned last night's dream forever while
        the fallback never mentioned it. A duplicate in one prompt (two
        overlapping turns) is cheap against losing the dream outright.
    """
    if emit_event:
        await emit_communication_event(perception.source, perception.person_id)

    await publish_turn_completed(
        person_id=perception.person_id,
        source=perception.source,
        intent=perception.intent.name,
        text=response_text,
        emotion_name=emotion_data.emotion.value if emotion_data else "",
        emotion_intensity=emotion_data.intensity if emotion_data else 0.0,
        project_suppresses_emotion=bool(
            getattr(context, "project_suppresses_emotion", False)
        ),
        # Quel projet la détection a reconnu dans ce tour. Le lanceur en a
        # besoin pour savoir qu'un humain est repassé sur cet engagement ;
        # ce qu'il en fait est sa politique, pas la nôtre.
        project_id=getattr(context, "project_id", None),
    )

    pending_dream = getattr(context, "pending_dream_recall", None)
    if pending_dream is not None:
        try:
            from old.backend.memory import read

            await read.mark_dream_recalled(pending_dream)
        except Exception as exc:
            degradations.record("turn: marquage du reve", exc)


async def _vue_emotionnelle(person_id: str, declared: EmotionData | None) -> dict:
    """Les quatre champs émotionnels de la trame ``speech``.

    The tag wins when there is one: it is what she chose while writing,
    where the oscillator only says where the relation stands — and it only
    absorbs a share of an impulse, so reading it here reported a state
    closer to the one before the turn than to what the reply declared.
    """
    try:
        view = await emotion_engine.turn_emotion_view(person_id, declared)
        return {
            "emotion_name": view.emotion,
            "emotion_intensity": view.intensity,
            "emotion_state": view.state,
            "emotion_blend": [
                {"emotion": name, "weight": round(w, 2)} for name, w in view.blend
            ],
        }
    except Exception as exc:
        degradations.record("turn: vue emotionnelle", exc)
        msg_emotion = emotion_engine.compute_message_emotion(person_id)
        return {
            "emotion_name": msg_emotion.emotion.value,
            "emotion_intensity": msg_emotion.intensity,
            "emotion_state": emotion_engine.get_state_dict(person_id),
            "emotion_blend": [
                {"emotion": e.value, "weight": round(w, 2)}
                for e, w in msg_emotion.blend
            ],
        }


async def _diffuser(output: SpeechOutput, source: str, person_id: str) -> None:
    """Broadcast to WebSocket (inner state follows), behind a short
    "thinking" delay so responses don't pop back instantly. Skipped for
    internal triggers (Mika already decided deliberately) and for AI errors
    (fallback messages should come back fast).

    Le délai cosmétique dormait dans l'unique worker de la file : deux
    secondes pendant lesquelles le tour suivant — de n'importe qui —
    attendait. Il vit dans une chaîne de diffusion détachée qui garde
    l'ordre des réponses ; le worker rend la main dès que le tour est
    calculé et persisté.
    """
    thinking_delay = 0.0
    if not output.ai_failed:
        try:
            from old.backend.drives.engine import drive_engine
            energy = drive_engine.energy_level()
        except Exception:
            energy = 0.5
        thinking_delay = _compute_thinking_delay(
            response_text=output.text, energy=energy, source=source,
        )
    if thinking_delay > 0 or _broadcast_chain.pending():
        if thinking_delay > 0:
            logger.debug(
                "Thinking delay: %.2fs (words=%d)",
                thinking_delay, len(output.text.split()),
            )
        _broadcast_chain.schedule(thinking_delay, output, source, person_id)
    else:
        await broadcast_to_websocket(output, source, person_id=person_id)


class _BroadcastChain:
    """Diffusions différées, dans l'ordre, hors du worker de la file.

    Chaque diffusion attend la précédente avant son propre délai : deux
    réponses ne peuvent pas se doubler (la deuxième calculée vite pendant
    que la première « réfléchit » partirait avant elle, et la voix lirait
    les répliques à l'envers). Une diffusion qui lève ne casse ni la chaîne
    ni le tour : le tour est déjà persisté, le client le récupère par
    curseur. ``flush`` est appelé à l'arrêt pour ne pas perdre les deux
    dernières secondes d'une conversation.
    """

    def __init__(self) -> None:
        self._tail: asyncio.Task | None = None
        self._tasks: set[asyncio.Task] = set()

    @staticmethod
    def _sur_cette_boucle(task: asyncio.Task) -> bool:
        """Une tâche d'une autre boucle (tests : une boucle par test) n'est
        ni un prédécesseur à attendre ni quelque chose à vider — l'attendre
        lèverait « attached to a different loop » et perdrait la diffusion."""
        try:
            return task.get_loop() is asyncio.get_running_loop()
        except RuntimeError:
            return False

    def pending(self) -> bool:
        return (
            self._tail is not None
            and not self._tail.done()
            and self._sur_cette_boucle(self._tail)
        )

    def schedule(self, delay: float, output, source: str, person_id: str | None) -> None:
        previous = self._tail if self.pending() else None
        task = asyncio.create_task(
            self._run(previous, delay, output, source, person_id)
        )
        self._tail = task
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    @staticmethod
    async def _run(previous, delay: float, output, source: str, person_id) -> None:
        if previous is not None:
            # ``wait`` ne relève jamais l'issue du prédécesseur (échec ou
            # annulation) : seule NOTRE annulation peut sortir d'ici, et elle
            # doit sortir — un ``except BaseException`` autour d'un ``shield``
            # aurait avalé l'annulation de l'arrêt et diffusé quand même.
            await asyncio.wait([previous])
        if delay > 0:
            await asyncio.sleep(delay)
        try:
            await broadcast_to_websocket(output, source, person_id=person_id)
        except Exception as exc:
            degradations.record("turn: diffusion differee", exc)
            logger.exception("Diffusion différée en échec (person=%s)", person_id)

    async def flush(self, timeout: float = 5.0) -> None:
        """Attend les diffusions en attente — borné, jamais bloquant à l'arrêt."""
        pending = [
            t for t in self._tasks if not t.done() and self._sur_cette_boucle(t)
        ]
        if not pending:
            return
        try:
            await asyncio.wait_for(
                asyncio.gather(*pending, return_exceptions=True), timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "%d diffusion(s) différée(s) abandonnée(s) à l'arrêt", len(pending),
            )
            for t in pending:
                t.cancel()


_broadcast_chain = _BroadcastChain()


async def flush_delayed_broadcasts(timeout: float = 5.0) -> None:
    """Point d'appel de l'arrêt (config/asgi.py), après le drain de la file."""
    await _broadcast_chain.flush(timeout)


def _client_msg_id(perception: Perception) -> str | None:
    """The browser-generated id of the message that triggered this turn.

    Opaque to the pipeline — it is minted by the client and only ever
    handed back, so it is length-capped and coerced to str rather than
    validated: it indexes nothing server-side, and the one thing it must
    not do is grow a payload without bound.
    """
    raw = perception.metadata.get("client_msg_id")
    if not isinstance(raw, str) or not raw:
        return None
    return raw[:64]


def _reply_ref(perception: Perception) -> str | None:
    """Le salon d'où ce tour est venu, tel que le canal l'a déclaré.

    Même traitement que ``client_msg_id`` : une valeur opaque au pipeline,
    rendue au canal qui l'a émise, donc bornée et coercée plutôt que
    validée.
    """
    raw = perception.metadata.get("reply_ref")
    if raw is None or raw == "":
        return None
    return str(raw)[:64]


def _transport_meta(perception: Perception) -> dict:
    """Ce que le transport a prouvé pour ce tour, tel que la reprise le rejouera.

    Persisté sur la ligne de la question (``Message.transport_meta``) : un
    tour interrompu par un redémarrage était rebâti avec des drapeaux vides,
    donc ``is_public=False`` — un message de groupe Telegram repartait en
    confiance ACCOUNT, le fichier de la personne injecté, la réponse postée
    dans le groupe. Les clés sont exactement celles que ce module lit.
    """
    meta = {
        "authenticated": bool(perception.metadata.get("authenticated", False)),
        "is_public": bool(perception.metadata.get("is_public", False)),
    }
    reply_ref = _reply_ref(perception)
    if reply_ref:
        meta["reply_ref"] = reply_ref
    return meta


# Ce qui, des métadonnées d'une pièce jointe, est persisté puis expédié dans
# chaque trame ``history``. Une liste fermée, et pas « tout sauf deux clés » :
# ``Part.metadata`` recopie le dict brut de l'émetteur, et rien en aval ne
# mesurait — une seule clé de 10 Mo faisait une ligne de 10 Mo et une trame
# de 10 Mo, à chaque ouverture du fil. Les clés sont celles que les
# préprocesseurs posent (``vision`` / ``audio`` / ``files``).
_ATTACHMENT_META_KEYS = (
    "name", "preprocessor", "extracted", "extract_method", "truncated",
    "duration_seconds", "error",
)
_ATTACHMENT_META_STR_MAX = 255


def _bounded_meta_value(value):
    """Un scalaire JSON borné, ou ``None`` pour ce qui n'en est pas un."""
    if isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:_ATTACHMENT_META_STR_MAX]
    return None


def _serialize_attachments_meta(perception: Perception) -> list[dict]:
    """Extract a JSON-friendly descriptor for each attached, non-text part.

    Binary content is not stored here — the router has already saved
    raw media to disk/DB via pipeline.media. This is purely structural
    metadata (kind, mime_type, name, ...) that lives alongside the
    persisted user Message so later retrieval knows what was attached.

    The subtlety is that by the time this runs there are **no non-text
    parts left**. Preprocessing happens in the router, before the
    processor is ever called, and it does not annotate a part — it
    *replaces* it: an image Part becomes ``Part(kind="text",
    content="[image: un chat roux dort sur un canapé]")``. So a filter on
    ``kind != "text"`` matched nothing and every upload was persisted with
    an empty ``attachments_meta``, which is the field the history frame
    ships as ``attachments``. A reloaded thread had no idea a file had
    ever been sent, and the documented promise that "the structured parts
    are preserved" was never once true for a web upload.

    What survives the substitution is ``metadata["original_kind"]``, which
    every preprocessor sets (including on its failure placeholder). That
    is what identifies a part as an attachment here.
    """
    meta: list[dict] = []
    for p in perception.parts:
        original_kind = p.metadata.get("original_kind")
        if p.kind == "text" and not original_kind:
            continue
        entry = {
            "kind": original_kind or p.kind,
            "mime_type": _bounded_meta_value(
                p.metadata.get("original_mime_type") or p.mime_type
            ),
        }
        for key in _ATTACHMENT_META_KEYS:
            if key in p.metadata:
                value = _bounded_meta_value(p.metadata[key])
                if value is not None:
                    entry[key] = value
        meta.append(entry)
    return meta
