"""Prompt construction — system prompt assembly and conversation formatting.

Extracted from ai/client.py. This is orchestration logic, not AI infra.

The layer list below used to be thirteen keyword parameters and twelve
copies of ``if x: system += "\\n\\n--- TITRE ---\\n" + x + "\\n--- FIN ---"``,
fed by a caller that transcribed a thirteen-field dataclass into thirteen
identically-named arguments. Adding one prompt block meant editing four
places (the dataclass, the gather, the transcription, the builder) and the
docstring that claimed to describe the order had already drifted away from
the code — it still listed modules → emotion → memory while dream, journal
and project had been inserted in between.

Now the order *is* the table. `_LAYERS` is the documentation, and it is the
thing that runs.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from old.backend.ai.chat import ChatPrompt, VolatileBlock, history_msg_max_chars
from old.backend.config.personality import personality
from old.backend.emotion.types import Emotion
from old.backend.pipeline.context import ConversationContext
from old.backend.utils.degradation import degradations

logger = logging.getLogger(__name__)

# La forme exacte que `retriever._souvenir_line` produit : `f" [{emotion}]"`.
# Ancré sur l'espace qui précède, donc un entête de section en début de ligne
# (`[Ce que tu sais]`) et les libellés de confiance (`[certain]`) ne matchent
# jamais.
_EMOTION_TAG_RE = re.compile(
    r"\s\[(?:" + "|".join(e.value for e in Emotion) + r")\]"
)


def _strip_emotion_tags(text: str) -> str:
    """Retire les marqueurs `[angry]` du rendu mémoire.

    Le retriever ne peut pas les omettre lui-même : `memory_context` est
    calculé dans `gather_context` avant la détection de projet, donc il ne
    connaît structurellement pas la politique du tour.
    """
    return _EMOTION_TAG_RE.sub("", text)

# Mention posée dans le créneau du résumé quand la compaction est inactive et
# que le fil dépasse quand même le budget L3 : une coupe visible plutôt que
# silencieuse (docs/evolution-contexte.md §5). Le SQL et l'index épisodique
# gardent le verbatim ; seul le contexte immédiat est élagué.
_TRUNCATION_NOTICE = (
    "[Début de conversation non affiché ici : {n} message(s) plus anciens "
    "restent en mémoire mais sortent du budget de contexte immédiat.]"
)


# Quand le fil déborde du budget L3, on ne le ramène pas juste sous la borne :
# on le ramène à cette FRACTION de la borne. Élaguer message par message, au
# fil de l'eau, changeait ``messages[0]`` à chaque tour dès que la borne était
# atteinte — et le préfixe caché chez Claude (système + historique jusqu'au
# tour précédent) ne matchait plus jamais : ~48 k tokens réécrits à 1,25× à
# chaque tour au lieu de relus à 0,1×. Avec l'hystérésis, une coupe ouvre de
# la place pour des dizaines de tours pendant lesquels le préfixe est stable.
# Même parti que le compacteur (``memory/compaction.py``).
_L3_TRIM_LOW_RATIO = 0.5


def _l3_trim_low_ratio() -> float:
    from old.backend.configs.runtime import cfg_float

    return cfg_float(
        "ai.context.l3_trim_low_ratio", _L3_TRIM_LOW_RATIO, mini=0.1, maxi=1.0,
    )


def _trim_history_to_l3(
    history: list[dict], max_chars: int, low_ratio: float | None = None,
) -> tuple[list[dict], int]:
    """Garde le bloc le plus récent de l'historique, avec hystérésis.

    Pur et testable. Le poids d'un message est sa taille de *rendu* (clippée
    à ``HISTORY_MSG_MAX_CHARS``), pour que la borne corresponde à ce qui part
    réellement sur le réseau. Tant que le fil entier tient dans ``max_chars``,
    il est rendu intact. Quand il déborde, il est ramené au bloc le plus
    récent tenant dans ``max_chars × low_ratio`` — jamais juste sous la
    borne, sinon la coupe se répète à chaque tour et le préfixe caché ne
    matche plus (voir ``_L3_TRIM_LOW_RATIO``). Le fil est contigu : jamais
    de trou au milieu. Le tour le plus récent est toujours gardé, même s'il
    dépasse à lui seul.

    Retourne ``(kept, dropped_count)``.
    """
    if max_chars <= 0:
        return list(history), 0
    # Lu une fois par appel, pas une fois par message : les deux plafonds
    # doivent parler du même chiffre, et le budget d'un tour ne peut pas
    # changer au milieu du fil qu'il découpe.
    plafond_message = history_msg_max_chars()
    weights = [min(len(m.get("content") or ""), plafond_message) for m in history]
    if sum(weights) <= max_chars:
        return list(history), 0
    ratio = _l3_trim_low_ratio() if low_ratio is None else low_ratio
    cible = max(1, int(max_chars * ratio))
    kept_rev: list[dict] = []
    used = 0
    for m, weight in zip(reversed(history), reversed(weights)):
        if kept_rev and used + weight > cible:
            break
        kept_rev.append(m)
        used += weight
    kept_rev.reverse()
    return kept_rev, len(history) - len(kept_rev)


@dataclass(frozen=True)
class _Layer:
    """One optional block of the system prompt.

    ``field`` names the ``ConversationContext`` attribute holding the text;
    an empty value means the block is skipped entirely. ``header`` of
    ``None`` appends the value raw (memory context brings its own markup).
    """

    field: str
    header: str | None = None
    footer: str = "--- FIN ---"
    # Suppressed when an active project runs in professional mode.
    muted_by_project: bool = False
    # Nettoyé des marqueurs `[emotion]` dans ce même mode — le bloc porte
    # autre chose que de l'affect et ne peut donc pas être coupé en entier.
    strip_emotion_tags: bool = False


# Order matters for the model's attention. Personality, self-concept,
# identity and person-context are the "slow" layers — stable across a
# session — so they lead. Circadian and fatigue shift by the hour. Modules,
# project, emotion and memory are recomputed every turn and come last, where
# recency biases recall.
#
# The footers are deliberately inconsistent (`--- FIN ---` for most,
# `--- FIN PROJET ---` and friends for three others). That is reproduced
# verbatim rather than tidied: this refactor is byte-for-byte output-
# preserving, and unifying them is a change to what the model reads, which
# belongs in its own commit with its own reasoning.
_LAYERS: tuple[_Layer, ...] = (
    _Layer("self_concept", "--- QUI TU ES DEVENUE ---"),
    # Identity sits immediately before what she knows about them, because it
    # qualifies that block: "here is Thomas's history" reads very differently
    # after "someone *claims* to be Thomas". The context layer already
    # withholds private material when certainty is too low; this says why.
    _Layer("identity_context", "--- QUI TU AS EN FACE ---"),
    _Layer("person_context", "--- CE QUE TU SAIS DE CETTE PERSONNE ---"),
    # Le mode professionnel coupe TOUS les canaux affectifs, pas seulement
    # l'état émotionnel : lire le ton de l'interlocuteur, s'autoriser à être
    # « moins parfaite », ruminer et proposer de raconter un rêve sont autant
    # de contradictions à trois lignes d'une directive « ton factuel et posé
    # uniquement ». Le rythme et le fil d'hier restent : ce sont des faits,
    # pas de l'affect.
    _Layer(
        "user_mood_hint", "--- CE QUE TU PERCOIS DE SON ETAT ---",
        muted_by_project=True,
    ),
    _Layer("circadian_context", "--- TON RYTHME ---"),
    _Layer("fatigue_fog", "--- ETAT COGNITIF ---", muted_by_project=True),
    _Layer(
        "rumination_context", "--- CE QUI TE TROTTE DANS LA TETE ---",
        muted_by_project=True,
    ),
    # Ses chantiers (conscience.Travail) — juste après les pensées, dont ils
    # sont la forme agie : une rumination qui insiste devient un chantier, et
    # les deux blocs racontent ensemble ce qui l'occupe. Coupé en mode
    # professionnel comme les ruminations : « je lisais un truc sur les
    # modèles de diffusion » n'a pas sa place à trois lignes d'une directive
    # « ton factuel et posé uniquement ».
    _Layer(
        "travaux_context", "--- CE QUE TU AS EN TRAIN ---",
        muted_by_project=True,
    ),
    _Layer(
        "dream_context", "--- CE QUE TU AS REVE CETTE NUIT ---",
        muted_by_project=True,
    ),
    _Layer("journal_context", "--- TON FIL D'HIER ---"),
    _Layer("module_context", "--- CONTEXTE MODULES ---", "--- FIN CONTEXTE MODULES ---"),
    # Last of the "slow" zone but before the emotional state: when a project
    # is active its tone directive must dominate the emotional expression,
    # not the other way around.
    _Layer("project_context", "--- PROJET EN COURS ---", "--- FIN PROJET ---"),
    # Suppressed in professional mode, so the prompt cannot say "tu te sens
    # excited" three lines after the project said "langage neutre". Drives
    # ride along in the same string and go quiet with it.
    _Layer(
        "emotion_context", "--- TON ETAT EMOTIONNEL ACTUEL ---",
        "--- FIN ETAT EMOTIONNEL ---", muted_by_project=True,
    ),
    # Retrieved memories arrive pre-formatted by the retriever — including a
    # `[angry]` per souvenir, rendered *after* the project directive, in the
    # recency zone that weighs most.
    _Layer("memory_context", None, strip_emotion_tags=True),
    # La pensée pré-verbale de la passe de préparation ferme le prompt : la
    # récence est la position qui pèse le plus, et c'est la seule couche qui
    # dit quelque chose sur CE tour précis plutôt que sur l'état ambiant.
    _Layer("note_de_focus", "--- CE QUI TE VIENT A L'ESPRIT ---"),
)


# Boundary of the cacheable prefix, as a count of leading ``_LAYERS`` entries.
# Personality + the first two layers (self-concept, identity) are the "slow"
# zone: personality is static per process, the self-narrative regenerates
# ~daily, identity moves only when a claim appears or resolves. Everything
# from ``person_context`` onward is recomputed every turn (live PAD affect,
# "Il est 14h", ruminations, module state, retrieved memories) and would
# invalidate a provider-side prompt cache on every single call if it lived
# in the prefix.
_STABLE_LAYER_COUNT = 2


def _render_layer(layer: _Layer, value: str) -> str:
    if layer.header is None:
        return value
    return f"{layer.header}\n{value}\n{layer.footer}"


def _assemble(context: ConversationContext) -> tuple[str, list[VolatileBlock]]:
    """``(stable, blocs volatils)`` — le rendu ET sa décomposition, une passe.

    La borne globale du tour (``ai.budget.fit_turn``) doit pouvoir couper une
    couche *nommée* sans laisser un « --- CE QUE TU SAIS DE CETTE PERSONNE ---
    » sans sa fin : elle a besoin des blocs, pas seulement de leur
    concaténation. Les reconstruire ailleurs aurait fait deux tables d'ordre à
    tenir d'accord, ce que `_LAYERS` existe précisément pour éviter.
    """
    suppress_emotion = context.project_suppresses_emotion

    # Personality bases itself on whether a project is active and what its
    # emotion policy says: in professional mode it drops the variability
    # block and the mandatory [EMOTION:...] tag instruction. A project turn
    # therefore rewrites the stable prefix — accepted: professional mode is
    # a mode, not a per-turn fluctuation.
    stable = personality.to_system_prompt(
        project_active=bool(context.project_context),
        project_suppresses_emotion=suppress_emotion,
    )

    blocks: list[VolatileBlock] = []
    for index, layer in enumerate(_LAYERS):
        # Strict getattr, no default: a typo in a layer's field name would
        # otherwise read as "this block is empty" and drop it from every
        # prompt, forever, without a single error. The table trades four
        # edit sites for one, and this is the price of that trade.
        value = getattr(context, layer.field)
        if not value:
            continue
        if layer.muted_by_project and suppress_emotion:
            continue
        if layer.strip_emotion_tags and suppress_emotion:
            value = _strip_emotion_tags(value)
        if index < _STABLE_LAYER_COUNT:
            stable += "\n\n" + _render_layer(layer, value)
        else:
            blocks.append(VolatileBlock(
                field=layer.field, value=value,
                header=layer.header, footer=layer.footer,
            ))

    return stable, blocks


def _render_volatile(blocks: list[VolatileBlock]) -> str:
    """Concaténation rendue des blocs volatils.

    Même forme que la recomposition d'après coupe dans ``ai.budget.fit_turn``
    — un bloc vidé disparaît avec son en-tête. Un test pin l'accord des deux.
    """
    return "\n\n".join(b.render() for b in blocks if b.value)


def build_prompt_parts(context: ConversationContext) -> tuple[str, str]:
    """Return ``(stable, volatile)`` — the system prompt split on volatility.

    ``stable + "\\n\\n" + volatile`` is byte-identical to what
    :func:`build_system_prompt` returns; a test pins that equivalence so the
    split can never drift from the legacy rendering.
    """
    stable, blocks = _assemble(context)
    return stable, _render_volatile(blocks)


def build_system_prompt(context: ConversationContext) -> str:
    """Assemble the full system prompt from personality + contextual layers.

    Takes the context object rather than unpacking it: the caller held a
    ``ConversationContext`` whose fields matched these parameters one for
    one, so the unpacking was pure transcription — and the kind that stays
    silently wrong when a field is added and one of the four places is
    missed.
    """
    stable, volatile = build_prompt_parts(context)
    if volatile:
        return f"{stable}\n\n{volatile}"
    return stable


def build_chat_prompt(context: ConversationContext, message: str) -> ChatPrompt:
    """Build the structured prompt for a conversation turn.

    The provider decides the rendering: chat-native providers cache the
    stable prefix and send the history as real messages; legacy providers
    get the exact old two-string shape via ``ChatPrompt.legacy_pair()``.

    L'historique est borné ici par le budget L3 du modèle (la même valeur que
    le watermark de compaction) : sans rôle ``COMPACTION`` mappé, c'est la
    SEULE chose qui empêche un fil long de partir entier dans le prompt
    (jusqu'à ``memory.short_term_limit`` messages, défaut 500). On borne la
    *copie* de rendu, jamais le buffer — la compaction et la réhydratation en
    restent maîtresses.

    Le tour entier est ensuite ramené dans la fenêtre : chaque bloc porte son
    plafond, leur SOMME n'était mesurée nulle part, et un dépassement fait
    tronquer le provider **par la tête** — le préfixe stable, c'est-à-dire la
    personnalité. Les déclarations d'outils y comptent (~6 500 tokens pour les
    neuf modules embarqués) : elles partent sur le fil sans apparaître dans
    aucun des deux prompts, donc sans ce terme le budget promettait une place
    déjà occupée.
    """
    stable, blocks = _assemble(context)
    history = list(context.history or [])
    summary = context.conversation_summary
    tools_chars = 0
    # Le rôle qui SERVIRA ce tour : outillé dès qu'il y a des outils (le cas
    # nominal — les modules SYSTEM en garantissent). Le budget se calculait
    # sur ``CONVERSATION`` quel que soit le tour : deux modèles à fenêtres
    # différentes sur les deux rôles bornaient le tour contre la mauvaise
    # fenêtre (troncature par la tête dans un sens, place gaspillée dans
    # l'autre). ``_resolve`` replie ``conversation_tools`` sur
    # ``conversation`` quand seul le second est mappé, donc le budget suit.
    role_effectif = None

    try:
        from old.backend.ai.budget import conversation_l3_chars, tool_weight, tools_prompt_chars
        from old.backend.ai.router import AIRole

        role_effectif = AIRole.CONVERSATION_TOOLS if context.tools else AIRole.CONVERSATION
        tools_chars = tools_prompt_chars(context.tools)
        if tools_chars:
            # Le relevé porte la valeur jusqu'aux appelants sans outils sous la
            # main — la compaction, qui décide *quand* replier le fil, appelle
            # `conversation_l3_chars()` sans argument. Sans ce dépôt les deux
            # viseraient deux tailles : le compactor laisserait grossir jusqu'à
            # 7 864 caractères pendant que le rendu en enverrait 4 000. Un tour
            # sans outils (conscience, `include_tools=False`) ne dit rien du
            # poids d'un tour outillé et n'écrase donc pas le relevé. Noté sous
            # les deux rôles : le compactor lit la clé ``conversation``.
            tool_weight.note(AIRole.CONVERSATION.value, tools_chars)
            tool_weight.note(role_effectif.value, tools_chars)
        history, dropped = _trim_history_to_l3(
            history, conversation_l3_chars(tools_chars, role=role_effectif),
        )
    except Exception as exc:
        degradations.record("prompt: borne historique L3", exc)
        dropped = 0

    # Coupe visible seulement dans le cas réellement perdant : rien pour
    # couvrir le début élagué. Avec un résumé de compaction, l'élagage est le
    # fonctionnement normal (le résumé couvre déjà les anciens), pas une
    # dégradation à signaler.
    if dropped and not summary:
        # La mention DANS le prompt est la garantie « pas de coupe silencieuse »
        # (le modèle la voit lui-même) ; le log est pour l'opérateur. Pas
        # `degradations.record` : ce n'est pas une exception avalée mais un
        # état attendu (compaction non mappée + fil long), et le registre est
        # réservé aux except (invariant AST de utils/degradation).
        summary = _TRUNCATION_NOTICE.format(n=dropped)
        logger.debug(
            "Historique élagué au budget L3 : %d message(s) hors contexte "
            "immédiat (compaction inactive) — mention posée dans le prompt.",
            dropped,
        )

    prompt = ChatPrompt(
        system_stable=stable,
        system_volatile=_render_volatile(blocks),
        history=history,
        message=message,
        conversation_summary=summary,
        volatile_blocks=blocks,
    )

    try:
        from old.backend.ai.budget import (
            budget_for,
            build_budget,
            default_window_tokens,
            fit_turn,
        )
        from old.backend.ai.router import AIRole

        budget = budget_for(
            role_effectif or AIRole.CONVERSATION, tools_chars=tools_chars,
        )
        if budget is None:
            # Même repli que le budget L3 : « fenêtre non déclarée » ne peut
            # pas vouloir dire « pas de borne », sinon le seul cas où la
            # troncature par la tête est certaine est aussi le seul où rien ne
            # la retient. La coupe vise la place PHYSIQUE (`window_room`), pas
            # `usable_tokens` — derrière un modèle 200k dont la fenêtre n'est
            # simplement pas déclarée, viser la cible viderait le prompt à
            # chaque tour.
            budget = build_budget(default_window_tokens(), tools_chars=tools_chars)
        prompt, _fit = fit_turn(prompt, budget)
    except Exception as exc:
        degradations.record("prompt: borne globale du tour", exc)

    return prompt


def format_conversation(
    message: str,
    conversation_history: list[dict] | None = None,
) -> str:
    """Format conversation history + current message into a single prompt string.

    Un tour porte un ``speaker`` quand il a ete dit par quelqu'un d'autre que
    l'interlocuteur du tour courant (pose par
    ``context._label_history_speakers``). Le tampon court terme est partage
    par tout le monde — c'est la premisse « quelqu'un dans une piece entend ce
    qui s'y dit » — mais rendre chaque ligne « User: » rendait la phrase
    d'Alice indiscernable de celle que Thomas vient d'ecrire : le modele
    l'attribuait a son interlocuteur et pouvait y repondre. Le nom n'est paye
    en tokens qu'au changement de locuteur.
    """
    full_prompt = ""
    if conversation_history:
        for msg in conversation_history:
            role = msg["role"]
            content = msg["content"]
            if role == "user":
                speaker = msg.get("speaker") or ""
                label = f"User ({speaker})" if speaker else "User"
                full_prompt += f"{label}: {content}\n\n"
            elif role == "assistant":
                full_prompt += f"Assistant: {content}\n\n"
    full_prompt += f"User: {message}"
    return full_prompt
