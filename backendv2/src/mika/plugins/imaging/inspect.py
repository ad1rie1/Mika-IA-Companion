"""La console des dessins (ADR 0063) : ce qu'on lui a demandé, où chaque dessin en est, ce qu'il a coûté."""

from __future__ import annotations

from mika.contracts import imaging as c
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    Badge,
    Block,
    Column,
    InspectContext,
    Nav,
    NavItem,
    Note,
    Ref,
    Stat,
    Stats,
    Table,
    Text,
    When,
    paginate,
)
from mika.plugins.imaging.faculty import IMAGING, ImagingState, params_of

PAGE = 25
STATUS_FR = {c.WAITING: ("en cours", "info"), c.READY: ("prêt, pas encore montré", "warn"),
             c.SHOWN: ("montré", "ok"), c.MISSED: ("raté, pas encore dit", "danger"), c.TOLD: ("raté, dit", "muted")}
QUALITY_FR = {"draft": "brouillon", "normal": "normale", "high": "haute"}


@IMAGING.inspect("dessins", title="Dessins", section="sens", order=35,
                 description="Ce qu'on lui a demandé de dessiner, où chaque dessin en est, ce qu'il a coûté.")
def _inspect(s: ImagingState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = ctx.ports.get("imaging")
    p = params_of(frame)
    blocks: list[Block] = [Nav((
        NavItem("Brancher un fournisseur", Ref("local", "/inspecteur/reglages/images-fournisseurs",
                                               "Fournisseurs d'images")),
        NavItem("Régler ses dessins", Ref("local", "/inspecteur/reglages/comportement-imaging", "Réglages")),))]
    if port is None or not getattr(port, "configured", False):
        blocks.append(Note("Aucun fournisseur d'images n'est branché : elle ne dessine pas.", tone="muted"))
    jobs = sorted(s.jobs.values(), key=lambda j: (-j.at, j.job))
    count = {st: sum(1 for j in jobs if j.status == st) for st in STATUS_FR}
    blocks.append(Stats((
        Stat("En cours", str(count[c.WAITING])), Stat("Prêts à montrer", str(count[c.READY]),
                                                      tone="warn" if count[c.READY] else ""),
        Stat("Montrés", str(count[c.SHOWN]), tone="ok"),
        Stat("Ratés", str(count[c.MISSED] + count[c.TOLD]), tone="danger" if count[c.MISSED] else ""),
        Stat("Coût", f"{sum(j.cost_usd for j in jobs):.2f} $", sub="les dessins gardés en mémoire")),
        title=f"Ses dessins (qualité par défaut : {QUALITY_FR.get(p.default_quality, p.default_quality)})"))
    page, pager = paginate(jobs, ctx.pager("page", size=PAGE))
    texts = ctx.store.content([r for j in page for r in (j.prompt_ref, j.caption_ref, j.reason_ref) if r])
    rows = []
    for j in page:
        label, tone = STATUS_FR.get(j.status, (j.status, "muted"))
        said = texts.get(j.caption_ref) or texts.get(j.reason_ref) or ""
        rows.append((When(j.at), Text(j.person or j.target, kind="mono"), Badge(label, tone),
                     f"{QUALITY_FR.get(j.quality, j.quality)} · {j.aspect}" + (" · adulte" if j.adult else ""),
                     j.backend or "—", f"{j.seconds:.0f} s" if j.seconds else "—",
                     Text(texts.get(j.prompt_ref, "(oublié)"), clamp=300), Text(said, clamp=300)))
    blocks.append(Table(
        (Column("demandé", "fit"), "pour", Column("où il en est", "fit"), "qualité", "fournisseur",
         Column("durée", "fit"), "ce qu'elle a demandé au fournisseur", "ce qu'elle y voit / pourquoi il a raté"),
        tuple(rows), title="Dessins, du plus récent au plus ancien", empty="aucun dessin pour l'instant",
        pager=pager, caption="Un dessin prêt part avec le message suivant à la personne (une initiative due, ou sa "
                             "réponse) ; il se télécharge depuis l'application de la personne."))
    return blocks
