"""Regarder les images de Teams (ADR 0258) : une à la fois, la plus ancienne d'abord, comme une photo reçue dans le
chat (le port ``preprocess``, ADR 0106). Ce qu'elle y voit rejoint le texte de son message (« [image : …] », dans
l'adaptateur) ; un message qui attendait ses images peut alors être remarqué (``IMAGE_SEEN`` : le tri relit). Un échec
passager (un modèle injoignable) est retenté plus tard, quelques fois ; sans lecture possible, l'image reste gardée,
sans rien dire d'elle.
"""

from __future__ import annotations

from typing import Any

from mika.kernel.clock import MINUTE
from mika.kernel.faculty import CatchUp
from mika.kernel.frame import Frame
from mika.plugins.teams import IMAGE_SEEN, IMAGES, TEAMS, TeamsState
from mika.ports.preprocess import Upload
from mika.ports.teams import DEFAULT_ACCOUNT

#: au plus tant d'images regardées par passage (le reste au passage suivant, aussitôt)
PER_RUN = 4
#: ce qu'elle en garde, au plus (caractères) : toute sa description (``STUDY_TOKENS`` la borne bien avant), qu'on lit
#: sous l'image ; le texte du message n'en reprend que le début
SEEN_MAX_CHARS = 4000
#: un échec passager : on réessaie après ce délai
RETRY_US = 2 * MINUTE


@TEAMS.process("teams.images", wake_on=[IMAGES], catch_up=CatchUp.ONCE, max_quantum_s=600, deadline_s=600)
class Look:
    def __init__(self) -> None:
        #: les images arrivées au début du dernier passage (``None`` : pas encore passé)
        self.handled: int | None = None
        #: le dernier passage a regardé tout ce qu'il pouvait : il en reste peut-être
        self.more = False
        #: après un échec passager, pas avant
        self.retry_at = 0

    def next_due(self, s: TeamsState, frame: Frame, last_run: int | None) -> int | None:
        if self.retry_at:
            return max(frame.now, self.retry_at)
        return frame.now if self.more or self.handled is None or s.images != self.handled else None

    async def run(self, ctx: Any) -> None:
        arrived = ctx.state.images
        self.more = await self._run(ctx)
        self.handled = arrived

    async def _run(self, ctx: Any) -> bool:
        """Un passage ; vrai s'il en reste peut-être."""
        port = ctx.ports.get("teams")
        if port is None:
            return False
        reader = ctx.ports.get("preprocess")
        self.retry_at = 0
        for _ in range(PER_RUN):
            image = port.image_to_read()
            if image is None:
                return False
            if reader is None:  # rien pour regarder : gardée, sans rien dire d'elle
                ref = port.image_read(image.id, seen="", sensitive=False, read=True)
            else:
                studied = await reader.study(Upload(f"teams-{image.image}", image.mime, image.data),
                                             max_chars=SEEN_MAX_CHARS)
                if not studied.read and studied.transient:
                    port.image_read(image.id, seen="", sensitive=False, read=False)
                    self.retry_at = ctx.frame.now + RETRY_US
                    return False
                ref = port.image_read(image.id, seen=studied.text if studied.read else "",
                                      sensitive=studied.sensitive, read=True)
            message = port.message(ref) if ref else None
            await ctx.emit(IMAGE_SEEN.draft(account=message.account if message is not None else DEFAULT_ACCOUNT,
                                            dedupe_key=f"teams-image:{image.id}"))
        return True
