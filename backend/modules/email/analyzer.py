import json
import logging
from dataclasses import dataclass, field

from django.conf import settings
from claude_agent_sdk import query, AssistantMessage, TextBlock
from claude_agent_sdk.types import ClaudeAgentOptions

from modules.email.prompts import EMAIL_TRIAGE_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


@dataclass
class EmailAnalysis:
    should_notify: bool = False
    notification_text: str = ""
    notification_emotion: str = "neutral"
    memories: list[dict] = field(default_factory=list)
    should_reply: bool = False
    reply_text: str = ""
    priority: str = "low"


class EmailAnalyzer:
    """Uses Claude to analyze incoming emails and decide actions."""

    def __init__(self):
        self.model = settings.CLAUDE_MODEL_LIGHT
        self._system_prompt: str | None = None

    def _get_system_prompt(self) -> str:
        if self._system_prompt is None:
            from config.personality import personality

            self._system_prompt = EMAIL_TRIAGE_SYSTEM_PROMPT.format(
                name=personality.name,
                description=personality.description,
                tone=personality.tone,
            )
        return self._system_prompt

    async def analyze_email(
        self, from_addr: str, subject: str, body: str
    ) -> EmailAnalysis:
        """Analyze a single email and return triage decision."""
        email_text = (
            f"De: {from_addr}\n"
            f"Objet: {subject}\n"
            f"Contenu:\n{body}"
        )

        try:
            options = ClaudeAgentOptions(
                system_prompt=self._get_system_prompt(),
                model=self.model,
                max_turns=1,
            )
            raw_text = ""
            async for msg in query(prompt=email_text, options=options):
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            raw_text += block.text
            raw = raw_text.strip()
            data = json.loads(raw)
            return EmailAnalysis(
                should_notify=data.get("should_notify", False),
                notification_text=data.get("notification_text", ""),
                notification_emotion=data.get("notification_emotion", "neutral"),
                memories=data.get("memories", []),
                should_reply=data.get("should_reply", False),
                reply_text=data.get("reply_text", ""),
                priority=data.get("priority", "low"),
            )
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning("Failed to parse email analysis: %s", exc)
            return EmailAnalysis()
        except Exception:
            logger.exception("Email analysis API error")
            return EmailAnalysis()
