"""Tout garder en local (ADR 0249) : l'historique des boîtes qui le veulent (``AccountInfo.keep_all``) se télécharge
petit à petit, les plus récents d'abord, qu'elle dorme ou non. C'est le monde, pas sa vie : rien ne s'écrit au
journal, et rien de ce qui se télécharge ainsi n'est trié ni remarqué — son tri ne lit que ce qui arrive dans les
dossiers relevés (``email.poll``)."""

from __future__ import annotations

from typing import Any

from mika.kernel.clock import MINUTE
from mika.kernel.faculty import CatchUp
from mika.kernel.frame import Frame
from mika.plugins.email import EMAIL, EmailState

#: au plus, ce qu'un passage télécharge d'une boîte (l'adaptateur borne aussi sa durée : quelques secondes)
KEEP_BATCH = 100
#: tant qu'il reste de l'historique : un passage par minute ; sinon, on revérifie à ce rythme (une case cochée, un
#: dossier nouveau, un dossier relu après un changement sur le serveur)
KEEP_EVERY = MINUTE
KEEP_IDLE = 10 * MINUTE


@EMAIL.process("email.keep", catch_up=CatchUp.ONCE, max_quantum_s=900, priority=85)
class Keep:
    def __init__(self) -> None:
        #: le dernier passage a encore trouvé de l'historique à télécharger
        self.busy = False
        #: la fin du dernier passage : la cadence se compte d'elle, pas de son début (un passage long qui se redirait
        #: dû aussitôt, sans rien écrire, serait retenu par l'ordonnanceur, de plus en plus longtemps)
        self.done_at: int | None = None

    def next_due(self, s: EmailState, frame: Frame, last_run: int | None) -> int | None:
        since = max(self.done_at or 0, last_run or 0)
        return max(frame.now, since + (KEEP_EVERY if self.busy else KEEP_IDLE))

    async def run(self, ctx: Any) -> None:
        port = ctx.ports.get("mail")
        read = 0
        if port is not None and port.configured():
            for info in port.accounts():
                if info.keep_all and info.ready:
                    read += await port.keep_history(info.key, KEEP_BATCH)
        self.busy, self.done_at = read > 0, ctx.now
