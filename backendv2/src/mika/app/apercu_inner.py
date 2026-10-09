"""Souvenirs, pensées et reprises fictifs pour relire la console sur une vie temporaire."""

from mika.contracts import attention as a
from mika.contracts import memory as m
from mika.contracts import runtime as rt
from mika.kernel.clock import DAY, HOUR
from mika.kernel.events import Content, Origin


async def inner(kernel) -> None:
    # Appelé après activity() : l'ordonnanceur est arrêté, aucune extraction n'est exécutée.
    now = kernel.mind.clock.now()

    async def emit(owner, drafts):
        return await kernel.mind.append(drafts, emitter=owner, origin=Origin.GENESIS,
                                        correlation="apercu-vie-interieure")

    source = await emit("runtime", [rt.PERCEPTION_RECEIVED.draft(handle="user_1", channel="web", addressed=False,
        text=Content.of("Pour le stream, je préfère un programme court. On garde un temps pour les questions à la fin. "
                        "Le projet de jeu reste confidentiel pour le moment."))])
    refs = source.seqs
    await emit("memory", [
        m.REMEMBERED.draft(text=Content.of("Adrien veut un stream facile à suivre : quelques sujets bien préparés, "
            "puis un vrai moment pour répondre au chat.\n\nIl préfère laisser respirer le programme."),
            about=("user_1",), told_by=("user_1",), sources=refs, sensitivity=1, emotion="curious"),
        m.REMEMBERED.draft(text=Content.of("Le nouveau jeu d’Adrien n’est pas encore annoncé. Je garde les détails entre nous."),
            about=("user_1",), told_by=("user_1",), sources=refs, sensitivity=3, secret=True),
        m.REMEMBERED.draft(text=Content.of("Béa était fatiguée lors de notre dernier échange. On s’est quittées en se disant à demain."),
            about=("user_2",), told_by=("user_2",), sensitivity=2, emotion="sad"),
    ])
    belief = await emit("memory", [m.BELIEVED.draft(text=Content.of("Adrien préfère des streams longs et très détaillés."),
        about=("user_1",), origin=m.INFERRED, confidence=0.4, sources=refs)])
    await emit("memory", [m.BELIEVED.draft(text=Content.of("Adrien préfère un programme de stream court, avec des questions à la fin."),
        about=("user_1",), origin=m.TOLD, source="user_1", confidence=0.9, sources=refs, replaces=belief.seqs[0])])
    promises = await emit("memory", [
        m.PROMISE_NOTICED.draft(text=Content.of("Relire le programme du stream avec Adrien."), to="user_1", due=now + DAY, sources=refs),
        m.PROMISE_NOTICED.draft(text=Content.of("Préparer une première liste de sujets pour Adrien."), to="user_1", sources=refs),
        m.PROMISE_NOTICED.draft(text=Content.of("Retrouver les anciennes maquettes pour Béa."), to="user_2"),
    ])
    await emit("memory", [m.PROMISE_RESOLVED.draft(promise=promises.seqs[1], status=m.HONORED),
        m.PROMISE_RESOLVED.draft(promise=promises.seqs[2], status=m.DROPPED),
        m.EVENT_NOTED.draft(text=Content.of("Le prochain stream d’Adrien."), when=now + 2 * DAY,
                           about=("user_1",), sources=refs),
        m.EXTRACTION_DEFERRED.draft(key=refs[0], messages=refs, about=("user_1",), status="review", attempts=3,
            failure_code="provider_error", detail=Content.of("Le modèle de relecture n’a pas répondu. "
                "Le message source est conservé ; ce passage pourra être relu quand le fournisseur sera disponible.")),
    ])
    await emit("attention", [
        a.THOUGHT_BORN.draft(text=Content.of("J’aimerais trouver une ouverture simple pour le stream d’Adrien. "
            "Un exemple concret aiderait le chat à entrer dans le sujet."), emotion="curious", intensity=0.7,
            origin=a.EXCHANGE, about=("user_1",), source=refs[0]),
        a.THOUGHT_BORN.draft(text=Content.of("Béa avait l’air fatiguée. Je me demande si elle a pu se reposer."),
            emotion="thinking", intensity=0.45, origin=a.CONCERN, about=("user_2",)),
        a.THOUGHT_BORN.draft(text=Content.of("Cette idée de titre me préoccupait, mais elle a perdu de son importance."),
            emotion="neutral", intensity=0.001, origin=a.EXCHANGE, about=("user_1",)),
        a.EXPECTATION_MET.draft(kind=a.PROMISE, person="user_1", since=now - HOUR, ref=promises.seqs[1]),
    ])
