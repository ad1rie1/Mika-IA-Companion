import json
import logging

import anthropic
from django.conf import settings

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """\
Tu es un systeme d'analyse de memoire. Analyse ces messages de conversation \
et extrais les informations importantes.

Pour chaque information trouvee, determine:
1. TYPE: "souvenir" (evenement passe, action, activite) ou "connaissance" (fait durable, preference, verite sur une personne/chose)
2. STOCKER: true/false — cette information vaut-elle le coup d'etre retenue?
   (ignore les banalites, salutations, questions generiques, et messages sans substance)
3. CONTENU: resume concis et autonome de l'information (comprehensible sans contexte)
4. THEMES: liste de themes/categories pertinents (ex: ["sport", "velo", "loisir"])
5. ENTITES: liste de personnes/objets/lieux impliques avec leur type

Regles:
- "Il aime le cafe" → connaissance (fait durable)
- "Il a bu un cafe ce matin" → souvenir (evenement)
- "Salut ca va?" → NE PAS STOCKER
- "Je m'appelle Thomas" → connaissance
- "J'ai fait du velo hier" → souvenir
- Chaque extraction doit etre AUTONOME (comprehensible seule, sans les messages)

Retourne UNIQUEMENT du JSON valide, sans texte autour:
{
  "extractions": [
    {
      "type": "souvenir",
      "store": true,
      "content": "L'utilisateur a fait du velo avec Thierry le 7 fevrier",
      "themes": ["sport", "velo", "loisir"],
      "entities": [{"name": "Thierry", "type": "person"}]
    }
  ]
}

Si aucune information ne vaut le coup d'etre stockee, retourne:
{"extractions": []}
"""

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
    """Uses Claude Haiku to analyze messages and extract structured memories."""

    def __init__(self):
        self.client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        self.model = settings.HAIKU_MODEL

    async def analyze_messages(self, messages: list[dict]) -> list[dict]:
        """Analyze a batch of messages and extract souvenirs + connaissances.

        Args:
            messages: list of {"role": "user"|"assistant", "content": "..."}

        Returns:
            list of extraction dicts with keys:
            type, store, content, themes, entities
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
                system=EXTRACTION_PROMPT,
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
