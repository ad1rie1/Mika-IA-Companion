"""Leur part du port d'entrée (ADR 0068, 0310) : un appel d'un réveil par API, déjà admis par sa porte (``desk.py``),
journalisé puis interprété (``wake``), et l'appel déjà reçu sous la même clé d'idempotence (``wake_seen``,
``wake_key``). ``app/mindport.py::KernelPort`` mêle leurs méthodes aux siennes."""

from __future__ import annotations

from collections.abc import Sequence

from mika.app.domains.domain import PortPart
from mika.contracts import identity as identity_c
from mika.contracts import wakeup as wakeup_c
from mika.kernel.events import Content, Origin
from mika.vocab.privacy import Sensitivity


def wake_key(endpoint: str, idempotency: str) -> str:
    """La clé de dédoublonnage d'un appel de réveil : un rejeu sous la même clé d'idempotence est le même appel."""
    return f"reveil:{endpoint}:{idempotency}"


class WakeupPort:
    """Un réveil par API, reçu. Elles lisent ``self.kernel``, que pose ``KernelPort``."""

    def wake_seen(self, endpoint: str, idempotency: str) -> int | None:
        """Le ``seq`` d'un appel déjà reçu par ce réveil sous cette clé d'idempotence (``None`` : aucun)."""
        if not idempotency:
            return None
        return self.kernel.mind.store.find_dedupe(wakeup_c.CALLED.name, wake_key(endpoint, idempotency))

    async def wake(self, endpoint: str, *, label: str, text: str, instructions: str, plain: bool, project: int,
                   bundles: Sequence[str], rouse: bool, notify: str, lifetime_us: int,
                   idempotency: str = "") -> int | None:
        """Un appel d'un réveil par API (ADR 0068), déjà admis par la porte : journalisé avec le réglage du réveil à
        cet instant, puis interprété (un réveil qui passe outre son rythme la tire du sommeil). Rend son ``seq`` —
        celui du premier appel portant la même clé d'idempotence, s'il y en a eu un."""
        frame = self.kernel.mind.frame()
        about: tuple[str, ...] = ()
        if notify not in (wakeup_c.NOBODY, wakeup_c.OWNERS):
            about = (frame.get(identity_c.PERSON(notify)) or notify,)
        now = self.kernel.mind.clock.now()
        draft = wakeup_c.CALLED.draft(
            endpoint=endpoint, label=label[:300], text=Content.of(text, level=int(Sensitivity.PERSONAL)),
            instructions=Content.of(instructions) if instructions.strip() else None, plain=plain, project=project,
            bundles=tuple(bundles), rouse=rouse, notify=notify, expires_at=now + lifetime_us if lifetime_us else 0,
            about=about, dedupe_key=wake_key(endpoint, idempotency) if idempotency else None)
        correlation = f"reveil:{endpoint}"
        commit = await self.kernel.mind.append([draft], emitter=wakeup_c.OWNER, correlation=correlation,
                                               origin=Origin.EXTERNAL)
        if not commit.seqs:
            return None
        seq = commit.seqs[-1]
        if not commit.deduped:
            await self.kernel.interpret(seq, correlation)
        return seq


PORT = PortPart(methods=WakeupPort)
