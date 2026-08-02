import asyncio
import json
import logging

from django.conf import settings

from ai.router import AIRole, UnconfiguredRoleError, ai_router
from utils.parsing import strip_markdown_json

EXTRACTION_TIMEOUT = 45  # seconds — prevent hanging the consolidation loop

logger = logging.getLogger(__name__)

# fmt: off
EXTRACTION_PROMPT_TEMPLATE = """\
ROLE: Tu es un module d'extraction de memoire. Tu n'es PAS {name}. Tu ne reponds PAS a la conversation. \
Tu ANALYSES la conversation ci-dessous et tu extrais les informations importantes sous forme de JSON.

CONTEXTE: {name} est: {description}. Style: {tone}. Traits: {traits}.

TROIS TYPES A EXTRAIRE:

1. SOUVENIR (evenement vecu):
   - Ecrit du point de vue SUBJECTIF de {name} (1ere personne), avec SES emotions
   - Doit sonner comme un journal intime de {name}
   - Emotion parmi: neutral, happy, sad, angry, surprised, thinking, love

2. CONNAISSANCE (fait objectif durable):
   - Ecrit de maniere OBJECTIVE (3eme personne), sans emotion
   - Fait factuel sur une personne, un objet, un lieu

3. COMMITMENT (engagement pris par {name}):
   - Detecte SEULEMENT dans les messages ou {name} s'engage a faire quelque chose
   - Phrases-cles: "je te ferai", "je te promets", "je vais te", "promis je", "d'accord je m'occupe de"
   - Enregistre l'engagement tel qu'il a ete dit, a la 1ere personne
   - "person" = a qui l'engagement est fait (optionnel si generique)
   - NE PAS confondre avec une simple intention vague ("je devrais peut-etre..." n'est PAS un commitment)

4. COMMITMENT_RESOLVED (engagement tenu ou caduc):
   - SEULEMENT si une liste "ENGAGEMENTS EN COURS" est fournie apres la conversation
   - Si la conversation montre que {name} a TENU un de ces engagements
     (elle dit l'avoir fait: "voila la playlist!", "c'est fait", "je l'ai regarde hier"),
     retourne {{"type": "commitment_resolved", "store": true, "commitment_id": <id>, "resolution": "honored"}}
   - Si la conversation montre que l'engagement n'a PLUS DE SENS
     (l'autre dit "laisse tomber", le sujet est annule), retourne "resolution": "dropped"
   - Sois CONSERVATEUR: en cas de doute, ne retourne rien pour cet engagement

REGLES:
- "Il aime le cafe" → connaissance | "Il a bu un cafe" → souvenir
- "Je te ferai la playlist ce soir" → commitment (+ souvenir de la conversation)
- "Salut ca va?" → NE PAS STOCKER (banalite)
- "Je m'appelle Thomas" → connaissance | "On a joue a Zelda!" → souvenir
- Chaque extraction doit etre AUTONOME (comprehensible seule)

IMPORTANT: Retourne UNIQUEMENT du JSON valide. Pas de texte avant ni apres. Pas de markdown. Juste le JSON.

Format:
{{
  "extractions": [
    {{
      "type": "souvenir",
      "store": true,
      "content": "On a passe un super moment a jouer a Zelda avec Thomas!",
      "emotion": "happy",
      "themes": ["gaming", "zelda"],
      "entities": [{{"name": "Thomas", "type": "person"}}]
    }},
    {{
      "type": "connaissance",
      "store": true,
      "content": "Thomas aime les jeux retro",
      "themes": ["gaming", "preference"],
      "entities": [{{"name": "Thomas", "type": "person"}}]
    }},
    {{
      "type": "commitment",
      "store": true,
      "content": "Envoyer la playlist a Thomas ce soir",
      "person": "Thomas"
    }}
  ]
}}

Si rien d'important: {{"extractions": []}}
"""
# fmt: on

VALIDITY_CHECK_PROMPT = """\
Tu es un systeme de verification de memoire. Tu n'es PAS un assistant. \
Tu reponds UNIQUEMENT en JSON valide, sans texte autour.

On te donne une connaissance existante et un nouveau contexte de conversation.

Connaissance actuelle: "{connaissance}"

Nouveau contexte:
{context}

Cette connaissance est-elle remise en question par le nouveau contexte?
- Tu dois etre CONSERVATEUR: ne change pas la connaissance sauf si le \
nouveau contexte contredit CLAIREMENT l'ancienne information.
- Une simple mention du sujet ne suffit pas a invalider.
- Il faut une contradiction explicite ou une correction directe.

Retourne UNIQUEMENT du JSON valide:
{{
  "still_valid": true,
  "new_confidence": 1.0,
  "reason": "explication courte"
}}
"""


class MemoryExtractor:
    """Uses Claude to analyze messages and extract structured memories.
    Souvenirs are written from the VTuber's subjective POV (personality + emotion).
    Connaissances are objective facts."""

    def __init__(self):
        self._system_prompt: str | None = None

    def _get_system_prompt(self) -> str:
        """Build the extraction prompt with personality context."""
        if self._system_prompt is None:
            from config.personality import personality

            self._system_prompt = EXTRACTION_PROMPT_TEMPLATE.format(
                name=personality.name,
                description=personality.description,
                tone=personality.tone,
                traits=", ".join(personality.traits),
            )
        return self._system_prompt

    async def analyze_messages(
        self,
        messages: list[dict],
        pending_commitments: list[dict] | None = None,
    ) -> list[dict]:
        """Analyze a batch of messages and extract souvenirs + connaissances.

        Args:
            messages: list of {"role": "user"|"assistant", "content": "..."}
            pending_commitments: open promises as {"id": int, "description": str}.
                When provided, the model also checks whether the conversation
                shows one being honored (→ ``commitment_resolved`` extraction).

        Returns:
            list of extraction dicts with keys:
            type, store, content, emotion (souvenirs only), themes, entities
        """
        if not messages:
            return []

        conversation_text = "\n".join(
            f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
            for m in messages
        )

        if pending_commitments:
            lines = "\n".join(
                f"- [{c['id']}] {c['description']}" for c in pending_commitments
            )
            conversation_text += (
                "\n\nENGAGEMENTS EN COURS (verifie si la conversation montre "
                "qu'ils ont ete tenus ou sont devenus caducs):\n" + lines
            )

        try:
            return await asyncio.wait_for(
                self._call_extraction(conversation_text, len(messages)),
                timeout=EXTRACTION_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Extraction timed out after %ds (role=%s)",
                EXTRACTION_TIMEOUT, AIRole.MEMORY_EXTRACTION.value,
            )
            return []
        except UnconfiguredRoleError as exc:
            logger.warning("Extraction ignorée — IA non configurée: %s", exc)
            return []
        except Exception:
            logger.exception("Extraction error (role=%s)", AIRole.MEMORY_EXTRACTION.value)
            return []

    async def _call_extraction(self, conversation_text: str, msg_total: int) -> list[dict]:
        """Inner extraction call — separated so we can wrap it with a timeout."""
        data = await self._query_model_json(conversation_text)
        if data is None:
            return []

        extractions = data.get("extractions", [])
        stored = [e for e in extractions if e.get("store", False)]
        logger.info(
            "Extractor: %d extractions (%d stored) from %d messages",
            len(extractions), len(stored), msg_total,
        )
        return stored

    async def _query_model_json(self, conversation_text: str) -> dict | None:
        """Query model and parse JSON response. Returns parsed dict or None."""
        raw = await self._query_model(conversation_text, AIRole.MEMORY_EXTRACTION)
        if raw is None:
            return None

        text = strip_markdown_json(raw)

        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning(
                "JSON parse failed (role=%s): %s | raw=%.300s",
                AIRole.MEMORY_EXTRACTION.value, exc, repr(raw),
            )
            return None

    async def _query_model(self, user_prompt: str, role: AIRole) -> str | None:
        """Send prompt to the configured provider via ai_router. Returns raw text or None."""
        try:
            raw_text = await ai_router.complete(
                role=role,
                system_prompt=self._get_system_prompt(),
                user_prompt=user_prompt,
            )
        except UnconfiguredRoleError as exc:
            logger.warning("Appel IA ignoré — IA non configurée (role=%s): %s", role.value, exc)
            return None
        except Exception:
            logger.exception("AI query failed (role=%s)", role.value)
            return None

        raw = raw_text.strip()
        if not raw:
            logger.warning("Empty response (role=%s)", role.value)
            return None
        return raw

    async def check_connaissance_validity(
        self, connaissance_content: str, recent_context: str
    ) -> tuple[bool, float | None]:
        """Check if a knowledge fact is contradicted by new context.

        Returns (still_valid, new_confidence).
        Conservative: requires explicit contradiction to invalidate.

        `new_confidence` vaut `None` quand aucun modèle n'a réellement répondu
        (rôle non mappé, réponse vide, JSON illisible, timeout) ou quand la
        réponse ne chiffre pas la confiance. Garder le fait valide reste le bon
        repli ; remettre sa confiance au maximum ne l'est pas — les appelants
        persistent cette valeur, ce qui annulerait la décroissance et les
        baisses décidées par la Conscience.
        """
        prompt = VALIDITY_CHECK_PROMPT.format(
            connaissance=connaissance_content,
            context=recent_context,
        )

        try:
            raw = await self._query_model(prompt, AIRole.VALIDITY_CHECK)
            if raw is None:
                return True, None

            text = strip_markdown_json(raw)
            data = json.loads(text)
            still_valid = data.get("still_valid", True)
            raw_confidence = data.get("new_confidence")
            reason = data.get("reason", "")
            if not still_valid:
                logger.info(
                    "Connaissance invalidated: %s (reason: %s)",
                    connaissance_content[:60],
                    reason,
                )
            if raw_confidence is None:
                return still_valid, None
            return still_valid, max(0.0, min(1.0, float(raw_confidence)))
        except UnconfiguredRoleError as exc:
            logger.warning("Validity check ignoré — IA non configurée: %s", exc)
            return True, None
        except Exception:
            logger.exception("Validity check error")
            return True, None  # Conservative: keep valid on error
