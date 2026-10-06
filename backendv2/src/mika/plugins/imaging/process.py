"""Le processus qui dessine (ADR 0063).

Un dessin demandé (``imaging.requested``) le réveille ; il prend le plus ancien en attente, le fait générer par la
passerelle des images (port ``imaging``, ADR 0061 — ses fournisseurs, ses replis, ses créneaux), dépose les octets
dans le port ``shares`` (sujets : la personne), le regarde (rôle ``caption``) pour qu'elle puisse en parler, puis
journalise ``imaging.drawn`` ; ou ``imaging.failed``, avec la raison, quand il n'a pas pu se faire. Un passage
coupé (un redémarrage) laisse le dessin « en cours » : le passage suivant le reprend.

Un passage dure ce que dure l'image (jusqu'à une dizaine de minutes sur le serveur local) : les processus tournent
chacun dans leur tâche, celui-ci ne retient personne.
"""

from __future__ import annotations

import base64
import hashlib
from typing import Any

from mika.contracts import imaging as c
from mika.contracts import self_ as self_c
from mika.kernel.events import Content
from mika.kernel.faculty import CatchUp
from mika.kernel.frame import Frame
from mika.plugins.imaging.faculty import IMAGING, ImagingState, Job, params_of
from mika.ports.imaging import DRAW, ImageRequest
from mika.ports.llm import Image, LLMRequest, Message
from mika.ports.preprocess import inert
from mika.ports.shares import MAX_SHARE_BYTES
from mika.vocab.phrasebook import family, phrase
from mika.vocab.privacy import Sensitivity

#: une génération coupée au-delà (attente d'un créneau comprise) : la passerelle a ses propres délais, plus courts
DEADLINE_S = 2400.0
EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


def next_job(s: ImagingState) -> Job | None:
    waiting = [j for j in s.jobs.values() if j.status == c.WAITING]
    return min(waiting, key=lambda j: (j.at, j.job)) if waiting else None


def file_of(job: str) -> str:
    """L'identifiant des octets d'un dessin (32 caractères hexadécimaux, déterministe : un passage repris réécrit le
    même fichier)."""
    return hashlib.blake2b(f"dessin:{job}".encode(), digest_size=16).hexdigest()


def look_request(mime: str, data: bytes, call_id: str, name: str) -> LLMRequest:
    """La description d'un dessin qu'elle vient de faire (``name`` : son nom, celui de sa persona)."""
    image = Image(mime, base64.b64encode(data).decode())
    return LLMRequest(role="caption", call_id=call_id, system_stable=phrase("imaging.look.system", name=name),
                      messages=(Message("user", phrase("imaging.look.ask"), images=(image,)),), max_tokens=200,
                      lane="background", priority=3)


def failed_draft(j: Job, outcome: str, reason: str = "") -> Any:
    # pourquoi, en mots (le code de l'issue, s'il est inconnu)
    text = family("imaging.failed").get(outcome, outcome) + \
        (phrase("imaging.failed_detail", detail=inert(reason, 300)) if reason else "")
    return c.FAILED.draft(job=j.job, target=j.target, person=j.person, outcome=outcome,
                          reason=Content.of(text, level=int(Sensitivity.PERSONAL)),
                          dedupe_key=f"dessin-rate:{j.job}")


@IMAGING.process("imaging.draw", wake_on=[c.REQUESTED], lane="background", catch_up=CatchUp.ONCE,
                 max_quantum_s=DEADLINE_S, deadline_s=DEADLINE_S, priority=40)
class Draw:
    def next_due(self, s: ImagingState, frame: Frame, last_run: int | None) -> int | None:
        return frame.now if next_job(s) is not None else None

    async def run(self, ctx: Any) -> None:
        j = next_job(ctx.state)
        if j is None:
            return
        port, shares, store = ctx.ports.get("imaging"), ctx.ports.get("shares"), ctx.ports.get("store")
        if port is None or not port.configured or shares is None:
            await ctx.emit(failed_draft(j, c.UNCONFIGURED))
            return
        prompt = (store.content([j.prompt_ref]) if store is not None and j.prompt_ref else {}).get(j.prompt_ref)
        if not prompt:  # le prompt a été oublié (la personne aussi) : rien à dessiner, rien à dire
            await ctx.emit(failed_draft(j, c.FAILED_))
            return
        start = ctx.now
        result = await port.generate(ImageRequest(
            role=DRAW, call_id=j.job, prompt=prompt, aspect=j.aspect, quality=j.quality, adult=j.adult,
            refusal_fallback=j.owner, lane="conversation", priority=1, meta={"episode": j.job}))
        if not result.ok:
            await ctx.emit(failed_draft(j, result.outcome, result.reason))
            return
        picture = result.images[0]
        if len(picture.data) > MAX_SHARE_BYTES:
            await ctx.emit(failed_draft(j, c.TOO_BIG))
            return
        file = file_of(j.job)
        await shares.put(file, picture.data, subjects=tuple(dict.fromkeys(k for k in (j.target, j.person) if k)))
        caption = None
        if params_of(ctx.frame).look:
            seen = await ctx.ask(look_request(picture.mime, picture.data, f"{j.job}:look",
                                              self_c.name_of(ctx.frame.get(self_c.PERSONA))))
            text = inert(seen.text, 600) if seen is not None and seen.text else ""
            caption = Content.of(text, level=int(Sensitivity.PERSONAL)) if text else None
        level = int(Sensitivity.PERSONAL)
        await ctx.emit(c.DRAWN.draft(
            file=file, target=j.target, person=j.person, about=tuple(k for k in (j.person,) if k and k != j.target),
            name=Content.of(f"dessin-{j.job[:6]}.{EXTENSIONS.get(picture.mime, 'png')}", level=level),
            mime=picture.mime, size=len(picture.data), digest=hashlib.sha256(picture.data).hexdigest(), job=j.job,
            caption=caption, backend=result.backend, model=result.model, pixels=result.size,
            seconds=round((ctx.now - start) / 1_000_000, 1), cost_usd=result.cost_usd,
            dedupe_key=f"dessin-pret:{j.job}"))
