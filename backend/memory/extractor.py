import json
import logging

import anthropic
from django.conf import settings

logger = logging.getLogger(__name__)

# fmt: off
EXTRACTION_PROMPT_TEMPLATE = """\
Tu es le systeme de memoire interne de {name}.
{name} est: {description}.
Son style: {tone}.
Ses traits: {traits}.

Tu analyses les conversations de {name} et tu construis ses souvenirs et ses connaissances.

DEUX TYPES DE MEMOIRE:

1. SOUVENIR (evenement vecu):
   - Ecrit du point de vue SUBJECTIF de {name}, avec SES emotions et SA personnalite
   - {name} ressent les choses a sa maniere: colore le souvenir selon qui elle est
   - Inclus l'emotion ressentie par {name} (neutral, happy, sad, angry, surprised, thinking, love)
   - Exemple avec personnalite aimante: "Thomas a ete un peu sec avec moi, mais je sais qu'il a eu une dure journee, je le soutiens"
   - Exemple avec personnalite rancuniere: "Thomas m'a mal parle alors qu'il a juste eu une mauvaise journee, il va voir"
   - Le souvenir doit sonner comme un JOURNAL INTIME de {name}

2. CONNAISSANCE (fait objectif durable):
   - Ecrit de maniere OBJECTIVE, sans emotion ni personnalite
   - Une verite factuelle sur une personne, un objet, un lieu
   - Exemple: "Thomas est developpeur Python", "La cafetiere tombe souvent en panne"

REGLES:
- "Il aime le cafe" → connaissance (fait durable, objectif)
- "Il a bu un cafe ce matin" → souvenir (vecu, subjectif, emotion de {name})
- "Salut ca va?" → NE PAS STOCKER (banalite)
- "Je m'appelle Thomas" → connaissance (fait objectif)
- "On a joue a Zelda ensemble!" → souvenir (joie de {name}, subjectif)
- Chaque extraction doit etre AUTONOME (comprehensible seule)
- Les souvenirs sont ecrits a la 1ere personne du point de vue de {name}
- Les connaissances sont ecrites a la 3eme personne, factuelles

Retourne UNIQUEMENT du JSON valide, sans texte autour:
{{
  "extractions": [
    {{
      "type": "souvenir",
      "store": true,
      "content": "On a passe un super moment a jouer a Zelda avec Thomas, j'adore quand il partage ses passions avec moi!",
      "emotion": "happy",
      "themes": ["gaming", "zelda", "moment-partage"],
      "entities": [{{"name": "Thomas", "type": "person"}}]
    }},
    {{
      "type": "connaissance",
      "store": true,
      "content": "Thomas aime les jeux retro, en particulier Zelda",
      "themes": ["gaming", "preference"],
      "entities": [{{"name": "Thomas", "type": "person"}}]
    }}
  ]
}}

Si aucune information ne vaut le coup, retourne: {{"extractions": []}}
"""
# fmt: on

VALIDITY_CHECK_PROMPT = """\
Tu es un systeme de verification de memoire. On te donne une connaissance \
existante et un nouveau contexte de conversation.

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
  "still_valid": true/false,
  "new_confidence": 0.0-1.0,
  "reason": "explication courte"
}}
"""


class MemoryExtractor:
    """Uses Claude Haiku to analyze messages and extract structured memories.
    Souvenirs are written from the VTuber's subjective POV (personality + emotion).
    Connaissances are objective facts."""

    def __init__(self):
        self.client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        self.model = settings.HAIKU_MODEL
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

    async def analyze_messages(self, messages: list[dict]) -> list[dict]:
        """Analyze a batch of messages and extract souvenirs + connaissances.

        Souvenirs are colored by the VTuber's personality and emotions.
        Connaissances remain objective.

        Args:
            messages: list of {"role": "user"|"assistant", "content": "..."}

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

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=self._get_system_prompt(),
                messages=[{"role": "user", "content": conversation_text}],
            )
            raw = response.content[0].text.strip()
            data = json.loads(raw)
            extractions = data.get("extractions", [])
            # Keep only items marked for storage
            return [e for e in extractions if e.get("store", False)]
        except (json.JSONDecodeError, KeyError, IndexError) as exc:
            logger.warning("Failed to parse Haiku extraction response: %s", exc)
            return []
        except Exception:
            logger.exception("Haiku extraction API error")
            return []

    async def check_connaissance_validity(
        self, connaissance_content: str, recent_context: str
    ) -> tuple[bool, float]:
        """Check if a knowledge fact is contradicted by new context.

        Returns (still_valid, new_confidence).
        Conservative: requires explicit contradiction to invalidate.
        """
        prompt = VALIDITY_CHECK_PROMPT.format(
            connaissance=connaissance_content,
            context=recent_context,
        )

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            data = json.loads(raw)
            still_valid = data.get("still_valid", True)
            confidence = float(data.get("new_confidence", 1.0))
            reason = data.get("reason", "")
            if not still_valid:
                logger.info(
                    "Connaissance invalidated: %s (reason: %s)",
                    connaissance_content[:60],
                    reason,
                )
            return still_valid, max(0.0, min(1.0, confidence))
        except Exception:
            logger.exception("Haiku validity check error")
            return True, 1.0  # Conservative: keep valid on error
