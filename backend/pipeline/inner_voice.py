"""Generation of Mika's audible inner monologue.

When Mika does something on her own — decides to write to someone, reworks
a project, reads a result — she thinks out loud: *"oh tiens, si j'envoyais
un message à Alice..."*, *"mmm... oh mais c'est génial ça, je continue !"*.

That murmur is **not** the text of the action. It is a reaction *generated
from* the intended action and whatever came back from it, by a deliberately
small model call (``AIRole.INNER_VOICE``) — it fires far more often than a
conversation turn, so it must stay cheap.

The rendering side lives in [voice.py](voice.py): the ``INNER`` persona owns
the quieter/slower/lower profile and the policy that keeps stray thoughts
off other people's phones.
"""
from __future__ import annotations

import logging

from ai.router import AIRole, ai_router

logger = logging.getLogger(__name__)

# Kept tight on purpose: a thought is a handful of words, and a long one
# stops sounding like a thought.
MAX_THOUGHT_CHARS = 160
INNER_VOICE_TIMEOUT = 12

SYSTEM_PROMPT = """\
ROLE: Tu produis UNE pensée intérieure de {name}, celle qu'elle marmonne \
tout haut pour elle-même pendant qu'elle travaille. Personne ne l'écoute.

STYLE: très court — une phrase, souvent incomplète. Le registre de quelqu'un \
qui pense à voix haute: "oh tiens...", "mmm", "attends", "ah mais oui", \
"bon", "tiens donc". Tu PEUX utiliser les jetons prosodiques [SIGH], \
[LAUGH], [BREATH], [PAUSE:400].

NE PAS:
- T'adresser à quelqu'un (pas de "tu", pas de "vous")
- Annoncer ce que tu fais comme un rapport ("Je vais maintenant...")
- Expliquer, justifier, ou conclure proprement
- Dépasser une phrase

Retourne UNIQUEMENT la pensée, sans guillemets ni préfixe.
"""

USER_PROMPT = """\
CE QU'ELLE S'APPRÊTE À FAIRE: {action}
CE QUI VIENT DE REVENIR: {result}
SON HUMEUR: {mood}

Sa pensée à voix haute, maintenant:"""


def _clean(text: str) -> str:
    """Strip the shapes a small model reaches for despite the instructions."""
    thought = (text or "").strip()
    # Quotes around the whole thing, and the occasional "Pensée:" prefix.
    if len(thought) >= 2 and thought[0] in "\"«'" and thought[-1] in "\"»'":
        thought = thought[1:-1].strip()
    for prefix in ("Pensée:", "Pensee:", "Thought:"):
        if thought.lower().startswith(prefix.lower()):
            thought = thought[len(prefix):].strip()
    # One sentence: a model that ignored "une phrase" gets truncated rather
    # than turning a murmur into a monologue.
    return thought[:MAX_THOUGHT_CHARS].strip()


async def generate_inner_thought(
    action: str,
    result: str = "",
    *,
    mood: str = "neutral",
) -> str | None:
    """Produce the murmur for an action Mika is taking, or ``None``.

    ``action`` is what she is about to do (or just did), ``result`` whatever
    came back from it. Returns ``None`` when there is nothing worth saying or
    the call failed — the caller must treat silence as a valid outcome and
    never surface an error as a thought.
    """
    import asyncio

    if not (action or "").strip():
        return None

    from config.personality import personality

    try:
        raw = await asyncio.wait_for(
            ai_router.complete(
                AIRole.INNER_VOICE,
                SYSTEM_PROMPT.format(name=personality.name),
                USER_PROMPT.format(
                    action=action.strip()[:500],
                    result=(result or "rien encore").strip()[:500],
                    mood=mood,
                ),
            ),
            timeout=INNER_VOICE_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.debug("Inner voice timed out — staying silent")
        return None
    except Exception:
        # Quota, provider error, anything: a failed thought is just silence.
        logger.debug("Inner voice generation failed — staying silent",
                     exc_info=True)
        return None

    thought = _clean(raw)
    return thought or None
