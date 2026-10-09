"""États fictifs pour relire l'activité et les erreurs, dans le magasin temporaire de l'aperçu."""

from mika.contracts import runtime as rt
from mika.kernel.events import Content, Origin
from mika.vocab.episodes import Kind

#: « pas avant » : aussi loin qu'un instant peut l'être
_NEVER = 2**62


def _hold(scheduler) -> None:
    for spec in scheduler.specs:
        scheduler.not_before[spec.name] = _NEVER


async def activity(kernel) -> list[str]:
    # La photographie doit rester stable pendant l'export ; aucun épisode de travail n'est lancé. Les processus
    # sont retenus, l'ordonnanceur reste en marche : arrêté, la santé montrerait une panne fabriquée par l'aperçu.
    _hold(kernel.scheduler)
    await kernel.scheduler.cancel_all()
    _hold(kernel.scheduler)  # un passage fini entre-temps a pu lever sa retenue
    for slug, kind, outcome, detail in (
        ("supports", Kind.STEP, "done", "Les supports du prochain stream sont prêts à relire."),
        ("connexion", Kind.TASK, "failed", "Le service de transcription n’a pas répondu. La tâche peut être reprise."),
        ("priorite", Kind.STEP, "preempted", "Le travail a cédé la place à une conversation."),
    ):
        corr = f"apercu-activite-{slug}"
        await kernel.mind.append([
            rt.EPISODE_STARTED.draft(kind=kind, reason=detail),
            rt.EPISODE_ENDED.draft(kind=kind, outcome=outcome, detail=detail),
        ], emitter="runtime", origin=Origin.GENESIS, correlation=corr)
    corr = "apercu-activite-en-cours"
    question = await kernel.mind.append([
        rt.PERCEPTION_RECEIVED.draft(handle="user_1", channel="web", authenticated=True,
            text=Content.of("Tu peux me résumer ce qui reste à préparer pour le prochain stream ?")),
    ], emitter="runtime", origin=Origin.EXTERNAL, correlation=corr)
    await kernel.mind.append([
        rt.EPISODE_STARTED.draft(kind=Kind.REPLY, target="user_1", reply_to=question.seqs[0],
                                 reason="Préparer une réponse sur le programme du stream"),
    ], emitter="runtime", origin=Origin.GENESIS, correlation=corr)
    urls = [f"/inspecteur/episode/{corr}", f"/inspecteur/evenement/{question.seqs[0]}"]
    cases = (("failed", "TimeoutError()"), ("interrupted", "Action interrompue pendant un redémarrage."),
             ("stale", "La réponse a dépassé son délai d’envoi."))
    for (key, seq), (status, error) in zip(kernel.mind.store.query_mind(
            "SELECT o.key, o.seq FROM outbox o JOIN events e ON e.seq=o.seq "
            "WHERE e.type=? ORDER BY o.seq DESC LIMIT 3", (rt.UTTERANCE.name,)), cases, strict=False):
        urls.append(f"/inspecteur/evenement/{seq}")
        await kernel.mind.store.mark_outbox(key, status, error)
    return urls
