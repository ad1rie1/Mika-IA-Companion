"""Modality preprocessors — turn non-text Parts into text Parts.

The router calls `run_preprocessors(perception)` before the AI step so
the LLM always sees a text prompt. Each preprocessor is responsible for
one modality: vision (image → LLM caption), audio (voice → Whisper
transcript), files (documents → extracted text). All degrade to a safe
placeholder when their engine is unavailable or fails.

Design notes:
  - Preprocessors MUTATE `perception.parts` in place: the non-text part
    is replaced with a `Part(kind="text", content="[description]")` and
    the original part's metadata is preserved via `metadata["original_kind"]`.
  - A preprocessor that fails must never raise into the router: it
    should log, leave the part untouched, and return. The AI will get
    an explicit "[image non disponible]" marker so it can apologize.
"""
from __future__ import annotations

import asyncio
import logging

from pipeline.perception import Part, Perception

logger = logging.getLogger(__name__)


# Échéance globale de l'étape. Elle s'exécute dans le routeur, donc AVANT
# le `wait_for(ai.call_timeout_seconds)` du processeur : rien ne la bornait,
# et le tour occupe pendant tout ce temps l'unique worker de la file (le
# backlog monte vers MAX_PENDING pendant que personne n'est servi). Le pire
# cas valait la somme des échéances unitaires — 5 pièces jointes × 45 s de
# transcription = 225 s. Une borne qui plafonne un lot entier n'a pas à se
# régler indépendamment des échéances unitaires qu'elle couvre, elle reste
# donc une constante comme VISION_TIMEOUT_SECONDS et TRANSCRIBE_TIMEOUT_SECONDS.
PREPROCESS_TIMEOUT_SECONDS = 60


async def run_preprocessors(perception: Perception) -> None:
    """Run modality-specific preprocessors on a perception.

    Walks the parts list; for each non-text Part, calls the matching
    preprocessor and replaces the Part with the resulting text Part.
    Mutates `perception.parts` in place.

    Les parts non-texte sont traitées *en parallèle*, l'ensemble borné par
    `PREPROCESS_TIMEOUT_SECONDS` : ce sont des appels réseau (vision →
    provider multimodal, audio → Whisper) qui n'empruntent pas l'exécuteur
    ORM, les sérialiser ne protégeait rien et faisait payer au tour la somme
    des attentes. Ce qui n'a pas abouti à l'échéance retombe sur le
    placeholder d'erreur, comme un préprocesseur en échec.
    """
    from pipeline.preprocessors import audio, files, vision

    dispatch: dict[str, callable] = {
        "image": vision.process,
        "video": vision.process,  # frames reduce to images for now
        "audio": audio.process,
        "file": files.process,
    }

    # Indexé par position : l'ordre des parts porte du sens (une légende
    # précède ce qu'elle légende), il doit survivre au traitement parallèle.
    pending: dict[int, asyncio.Task] = {}
    for index, part in enumerate(perception.parts):
        if part.kind == "text":
            continue

        handler = dispatch.get(part.kind)
        if handler is None:
            logger.debug("No preprocessor for kind=%s, keeping raw part", part.kind)
            continue

        pending[index] = asyncio.ensure_future(handler(part))

    if not pending:
        return

    try:
        await asyncio.wait_for(
            asyncio.gather(*pending.values(), return_exceptions=True),
            timeout=PREPROCESS_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Prétraitement abandonné après %ss (%d part(s) en vol)",
            PREPROCESS_TIMEOUT_SECONDS, len(pending),
        )

    new_parts = list(perception.parts)
    for index, task in pending.items():
        new_parts[index] = _resolve_part(task, perception.parts[index])

    perception.parts = new_parts


def _error_part(part: Part) -> Part:
    """Le marqueur explicite qui remplace une part non traitée — l'IA le
    voit et peut s'en excuser, plutôt que de ne rien recevoir."""
    return Part(
        kind="text",
        content=f"[{part.kind} non disponible]",
        metadata={"original_kind": part.kind, "error": True},
    )


def _resolve_part(task: asyncio.Task, part: Part) -> Part:
    """Le résultat d'un préprocesseur, ou le placeholder d'erreur.

    Échec, abandon à l'échéance et — cas théorique d'une coroutine qui
    avale son annulation — tâche encore en vol donnent le même repli :
    une part non-texte ne doit jamais atteindre le prompt.
    """
    if not task.done():
        task.cancel()
        logger.warning("Preprocessor %s still in flight after deadline", part.kind)
        return _error_part(part)

    if task.cancelled():
        logger.warning("Preprocessor %s abandoned at deadline", part.kind)
        return _error_part(part)

    error = task.exception()
    if error is not None:
        logger.error("Preprocessor %s failed", part.kind, exc_info=error)
        return _error_part(part)

    return task.result()
