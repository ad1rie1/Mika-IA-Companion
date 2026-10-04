"""L'acte — prendre la parole d'elle-même, avec sa trousse et un destinataire.

Le quatrième étage du moteur (« 4. ACT »), sorti de ``engine.py`` sur le
modèle de ``travaux.py`` : des fonctions de module prenant le moteur, jamais
une classe collaboratrice. ``act`` orchestre à travers la surface du moteur
(``moteur._preparer_trousse``, ``moteur._select_recipient``,
``moteur._appeler_le_modele``, ``moteur._audience_presente``…) pour que les
patchs que les tests posent sur ces méthodes continuent de porter — et le
moteur garde un délégué d'une ligne sous chaque nom.

Ce qu'un acte produit (``ActeResultat``) et ce qu'il a mis sous les yeux du
modèle (``ActionBrief``) vivent ici avec lui : le moteur les importe pour le
cycle de décision et le journal.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid4

from asgiref.sync import sync_to_async

from old.backend.ai.budget import tools_prompt_chars
from old.backend.ai.cadence import en_fond
from old.backend.ai.router import AIRole, ai_router
from old.backend.configs.runtime import cfg_bool, cfg_int
from old.backend.conscience.trousse import (
    DEFAULT_TUNING as DEFAULT_TROUSSE_TUNING,
    preparer,
    resume_capacites,
)
from old.backend.conscience.types import DecisionContext
from old.backend.conscience.agenda import enregistrer_tentative
from old.backend.drives.engine import drive_engine
from old.backend.utils.degradation import degradations, degraded
from old.backend.utils.tool_trace import journal_outils
from old.backend.utils.tool_results import BilanOutils

logger = logging.getLogger(__name__)

#: Observations et actions programmées effectivement montrées au modèle.
#:
#: Ce sont les bornes qui rendent le marquage honnête possible : jusqu'ici le
#: prompt en montrait 5 et 3 pendant que l'acte en clôturait 20 et 10.
_BRIEF_OBSERVATIONS_MAX = 5

# Budget de la passe 1, alignee sur les 15 s de l'interpreteur : meme role
# (SIGNAL_INTERPRETATION), meme travail — classer un signal court — et le
# meme cadre, une boucle sans superviseur. La borne routee
# (`ai.call_timeout_seconds`, 120 s) est celle d'un tour de conversation :
# la depenser ici immobilise `_decision_lock` pour quatre cycles avant
# meme que `act` n'ait commence a composer sa reponse. Ne rien dire a
# personne est un resultat valide, donc l'expiration se replie sur le
# broadcast interne plutot que d'annuler l'acte.
_RECIPIENT_TIMEOUT_S = 15

#: Personnes présentes proposées au choix du destinataire. Petit : c'est
#: une salutation possible, pas un annuaire.
_PRESENTS_MAX = 5


@dataclass(frozen=True)
class ActionBrief:
    """Le prompt d'un acte, ET ce qu'il a réellement mis sous les yeux.

    Les deux vont ensemble : c'est tout l'objet de cette classe. Le prompt
    montrait cinq observations et trois actions programmées, et l'acte en
    clôturait vingt et dix — au seul motif que l'appel n'avait pas planté. Sept
    intentions qu'elle s'était données disparaissaient à chaque acte,
    estampillées faites, pendant que le journal annonçait « Executed 10
    scheduled action(s) ».

    Rendre le texte seul rendait cette divergence indétectable : rien, dans une
    chaîne de caractères, ne dit ce qu'elle contient.
    """

    texte: str
    observations: tuple = ()
    actions: tuple = ()
    ruminations: tuple = ()


@dataclass(frozen=True)
class ActeResultat:
    """Ce qu'un acte a produit. Remplace un booléen qui disait trop peu.

    **Piège à ne pas rouvrir** : l'appelant testait `if spoke:` sur le retour.
    Un dataclass est toujours vrai, donc rendre un objet sans corriger le test
    ferait journaliser « act » sur un acte qui a échoué — ce qui gonflerait
    `acts_today`, compterait comme un acte ignoré faute de réponse possible, et
    trois pannes suffiraient à brider la conscience pour la journée. La
    véracité se lit sur `dit`, jamais sur l'objet.
    """

    dit: str = ""
    person_id: str = ""
    outils: str = ""
    outils_reussis: int = 0
    #: Personne à qui parler ET personne pour entendre : l'acte n'a pas eu
    #: lieu, sans échec. Distinct de `ai_failed` — rien n'a été tenté.
    sans_audience: bool = False
    #: Budget d'appels de fond du provider épuisé : rien tenté, rien payé.
    #: Ni un acte ni une panne — le cooldown espace les tentatives, et le
    #: moteur journalise « failed », qui ne compte jamais comme ignoré.
    differe: bool = False
    trousse: tuple = ()
    ai_failed: bool = False
    interne: bool = False


# ── Le tour de modèle ─────────────────────────────────────────────


async def appeler_le_modele(
    prompt: str,
    *,
    person_id: str,
    modules: list[str],
    memory_context: str = "",
    metadata: dict | None = None,
    broadcast: bool = True,
    persist: bool = True,
    ressentir: bool = True,
):
    """Un tour de modèle, avec sa trousse et son carnet d'outils.

    ``ressentir=False`` pour un pas de chantier : chaque `[EMOTION]` d'un
    pas muet teintait l'humeur globale — quatre pas d'un chantier, quatre
    impulsions que personne n'a vécues. L'affect d'un travail vient de
    son verdict (fierté à l'aboutissement, frustration au blocage).

    Extrait de `act` sans changer un octet de son comportement : deux
    chemins en ont désormais besoin — la parole et le pas de travail — et
    les laisser diverger ferait deux façons de monter un contexte, dont
    une seule recevrait les correctifs. C'est exactement ce qui était
    arrivé à la recopie champ à champ du contexte, où `identity_context`
    et `journal_context` manquaient à l'appel.

    Rend `(output, bilan_outils, outils_reussis)`.
    """
    import dataclasses as _dc

    from old.backend.modules.manager import module_manager
    from old.backend.pipeline.context import gather_context
    from old.backend.pipeline.perception import Perception
    from old.backend.pipeline.processor import process_message

    # La memoire n'est demandee ici que si le rappel sur les observations
    # n'a rien donne : sinon `memory_context` ecrase le champ juste en
    # dessous, et l'embedding + la requete ChromaDB seraient payes pour rien.
    base_context = await gather_context(
        prompt, person_id,
        include_tools=False,
        include_memory=not memory_context,
    )

    if metadata is not None and "ruminations" in metadata:
        from old.backend.pipeline.context_blocks import format_ruminations

        # Retenir le même lot pour le prompt et son soulagement, même si la
        # digestion nocturne change le classement pendant l'appel.
        base_context.rumination_context = format_ruminations(metadata["ruminations"])

    tools = module_manager.get_tools_for_modules(modules) if modules else []
    if (metadata or {}).get("travail"):
        from old.backend.conscience.activities import outils
        tools = [*tools, *outils()]
    tool_names = [t.name for t in tools]

    # ``replace`` plutôt qu'une recopie champ à champ : la transcription
    # manuelle avait déjà dérivé — ``identity_context`` et
    # ``journal_context`` manquaient à l'appel, si bien qu'un tour spontané
    # adressé à une vraie personne partait sans le bloc « QUI TU AS EN
    # FACE » alors que ``person_context`` (que ce bloc qualifie) passait,
    # lui. Un champ ajouté demain suit tout seul.
    context = _dc.replace(
        base_context,
        memory_context=memory_context or base_context.memory_context,
        tools=tools,
        tool_names=tool_names,
    )

    perception = Perception.from_internal_trigger(
        prompt,
        source="conscience",
        person_id=person_id,
        metadata=metadata or {},
    )

    # Le carnet couvre l'appel entier, boucle d'outils comprise :
    # `output.tool_calls` ne rend que des NOMS, jamais une issue.
    #
    # `en_fond()` : personne n'attend cette réponse — le tour part sur
    # `conversation_tools`, le rôle d'une conversation, et seul l'appelant
    # sait qu'il n'y a pas d'interlocuteur. Le marqueur suit les `await`,
    # donc un outil qui relance le modèle depuis la boucle est couvert.
    from old.backend.conscience.activities import travail_courant
    jeton_travail = travail_courant.set((metadata or {}).get("travail"))
    try:
        with journal_outils() as carnet, en_fond():
            output = await process_message(
                perception,
                context=context,
                emit_event=False,
                broadcast=broadcast,
                persist=persist,
                emotion_impulse=ressentir,
            )
            return output, BilanOutils(carnet), carnet.reussites
    finally:
        travail_courant.reset(jeton_travail)


# ── Qui est là ────────────────────────────────────────────────────


def quelquun_est_joignable(moteur) -> bool:
    """Un navigateur connecté, ou un handle module joignable (Telegram).

    La condition minimale pour qu'un acte puisse avoir un destinataire :
    `select_recipient` ne retient que des cibles joignables. Ne lève
    jamais — fermé par défaut, comme la garde d'audience.
    """
    if moteur._audience_presente():
        return True
    try:
        from old.backend.communication.presence import presence_registry

        return any(t.is_module for t in presence_registry.reachable())
    except Exception as exc:
        degradations.record("conscience: lecture de presence", exc)
        return False


def canal_de(person_id: str | None) -> str:
    """Le canal par lequel ce destinataire est joignable (« web »,
    « telegram »), pour que la porte de divulgation lise le bon plancher.
    Vide quand on ne sait pas — la porte est alors fermée."""
    if not person_id:
        return ""
    try:
        from old.backend.communication.presence import presence_registry

        cibles = presence_registry.resolve(person_id)
        return str(cibles[0].channel) if cibles else ""
    except Exception as exc:
        degradations.record("conscience: canal du destinataire", exc)
        return ""


# ── L'acte ────────────────────────────────────────────────────────


def action_confirmee(action, bilan):
    from old.backend.modules.manager import module_manager
    if not isinstance(bilan, BilanOutils) or not bilan.permet_aboutissement(
        outils_requis=bool(action.modules or action.context_data.get("expected_tools")),
    ):
        return False
    reussis = {a["nom"] for a in bilan.preuves["appels"] if a["ok"]}
    attendus = set(action.context_data.get("expected_tools") or [])
    if attendus:
        return attendus.issubset(reussis)
    if action.modules:
        disponibles = {t.name for t in module_manager.get_tools_for_modules(action.modules)}
        return bool(reussis.intersection(disponibles))
    return True


async def action_non_confirmee(moteur, actions, bilan):
    """Une tentative outillée ambiguë ne se rejoue pas aveuglément."""
    from old.backend.conscience.models import ScheduledAction
    if isinstance(bilan, BilanOutils) and bilan.preuves["total"]:
        for action in actions:
            action.status = ScheduledAction.Status.UNCERTAIN
            action.raison_echec = "Effets à vérifier avant toute nouvelle tentative."
            action.tentatives += 1
            action.context_data = {**action.context_data, "execution": bilan.preuves}
            action.context_data.pop("reserved_until", None)
            await sync_to_async(enregistrer_tentative)(
                action, ["status", "raison_echec", "tentatives", "context_data"],
            )
    else:
        await moteur._compter_tentative(list(actions))


async def act(moteur, ctx: DecisionContext, reason: str) -> ActeResultat:
    """Generate a spontaneous response using accumulated context.

    Builds an INTERNAL_TRIGGER Perception and hands it to the pipeline
    processor directly (context is pre-assembled with relevant-module
    tools, so we bypass the router's dispatch logic here — the intent
    is already "Mika acts, no event to loop back").

    Returns True only if something was actually said: the caller commits
    the day's greeting and the decision log from that answer."""
    from old.backend.conscience.models import Observation, ScheduledAction
    from old.backend.modules.manager import module_manager

    moteur._last_action_time = time.time()
    # La gigue de CE silence-ci, tirée maintenant et gardée jusqu'au
    # prochain acte, pour que le compte à rebours affiché descende sans
    # trembler.
    moteur._tirer_gigue_cooldown()

    # Avant la trousse, le brief, le destinataire et le rappel mémoire :
    # tout ça se paie pour rien si le provider n'a plus d'appel de fond
    # dans l'heure. `_last_action_time` est déjà posé, le cooldown espace
    # les tentatives — gratuites, comme pour l'absence d'audience.
    if not ai_router.budget_de_fond_disponible(AIRole.CONVERSATION_TOOLS):
        logger.info(
            "Conscience act différé [%s]: budget d'appels de fond épuisé", reason,
        )
        return ActeResultat(person_id="conscience_mika", differe=True)

    # Determine which modules are relevant based on observation sources
    trousse = moteur._preparer_trousse(ctx)
    relevant_modules = list(trousse.modules)

    # Deux blocs, et non plus un catalogue unique. `collect_capabilities_summary()`
    # énumérait tout ce qui tourne pendant que la trousse était vide : le
    # modèle, à qui on annonce des capacités qu'on ne lui donne pas,
    # *raconte* l'action au lieu de la faire — et le journal comme les
    # souvenirs se remplissent de choses qu'elle croit avoir faites.
    brief = await moteur._build_action_prompt(
        ctx,
        vecu=moteur._composer_vecu(ctx),
        en_main=trousse.bloc_en_main(),
        a_demander=resume_capacites(
            trousse,
            module_manager.collect_capabilities(),
            disponibles=moteur._modules_enregistres(),
        ),
    )
    prompt = brief.texte

    # Decide WHOM to address (pass 1). If a concerned, reachable person is
    # chosen, the response is composed with THEIR context and delivered to
    # them; otherwise it stays Mika's internal/broadcast voice.
    interne = bool(brief.actions and brief.actions[0].context_data.get("mode") == "internal")
    target = None if interne else await moteur._select_recipient(ctx)
    person_id = target or "conscience_mika"

    # Le rappel vient APRÈS le choix du destinataire, et avec sa porte :
    # avant, il partait sans `person_id` (donc avec les confidences de
    # tous) et écrasait le contexte filtré de `gather_context` (MEM-09).
    queries = [o.summary for o in ctx.pending_observations if o.pertinence > 0.3]
    memory_context = await moteur.memory.recall_for_context(
        queries, person_id=target or "", channel=canal_de(target),
    )

    # Personne à qui s'adresser ET personne dans la pièce : un acte
    # partait quand même sur le groupe global — vide — et était PERSISTÉ
    # dans le fil partagé. Jusqu'à cinq monologues par jour que personne
    # n'entendait, payés en boucle d'outils, et que le prochain
    # interlocuteur retrouvait dans son historique. Même garde que le
    # murmure : sans public, elle ne parle pas — ce qu'elle avait à dire
    # reste en attente, vieillit, et devient une pensée (promotion en
    # rumination) plutôt qu'une phrase dans le vide. `_last_action_time`
    # est déjà posé : le cooldown espace les tentatives, gratuites.
    if not interne and target is None and not moteur._audience_presente():
        logger.info(
            "Conscience act withheld [%s]: personne à qui parler ni pour "
            "entendre — les observations restent en attente", reason,
        )
        return ActeResultat(
            person_id=person_id, trousse=tuple(relevant_modules),
            sans_audience=True,
        )

    # Réserver AVANT tout effet. Un crash laisse une action à vérifier,
    # jamais une action pending susceptible de renvoyer le même message.
    if brief.actions:
        from django.utils import timezone

        action = brief.actions[0]
        # L'opérateur peut reprendre un effet incertain, pas une tentative
        # encore en vol. La marge couvre la clôture après le timeout IA.
        delai = cfg_int("ai.call_timeout_seconds", 120, mini=1) + 60
        action.context_data = {**action.context_data,
                               "attempt_token": uuid4().hex,
                               "reserved_until": (timezone.now() + timedelta(seconds=delai)).isoformat()}
        pris = await sync_to_async(lambda: ScheduledAction.objects.filter(
            pk=action.pk, status=ScheduledAction.Status.PENDING,
        ).update(status=ScheduledAction.Status.UNCERTAIN,
                 context_data=action.context_data,
                 raison_echec="Tentative réservée ; vérifier ses effets si elle est interrompue."))()
        if not pris:
            return ActeResultat(person_id=person_id, differe=True)

    try:
        output, bilan_outils, outils_reussis = await moteur._appeler_le_modele(
            prompt,
            person_id=person_id,
            modules=relevant_modules,
            memory_context=memory_context,
            metadata={"reason": reason, "relevant_modules": relevant_modules,
                      "ruminations": list(brief.ruminations)},
            broadcast=not interne, persist=not interne, ressentir=not interne,
        )

        if output.ai_failed:
            # The AI call failed (unconfigured role, quota, timeout...):
            # nothing was actually said. Leave observations pending and
            # scheduled actions unexecuted so they retry after cooldown,
            # and don't satisfy drives with a phantom act.
            #
            # Mais la tentative se COMPTE, comme sur le chemin de
            # l'exception plus bas : c'est l'échec ordinaire (rôle non
            # mappé, quota, timeout), et il rentrait avant le compteur —
            # `tentatives` restait à zéro, le plafond ne tombait jamais,
            # et un rendez-vous prioritaire relevait le cooldown et le
            # veto de sommeil à chaque cycle de 30 s, indéfiniment.
            logger.warning(
                "Conscience act aborted [%s]: AI call failed — will retry "
                "after cooldown", reason,
            )
            if brief.actions:
                with degraded("conscience: tentative d'action programmee"):
                    await action_non_confirmee(moteur, brief.actions, bilan_outils)
            return ActeResultat(
                person_id=person_id, trousse=tuple(relevant_modules),
                ai_failed=True,
            )

        # On ne clôt QUE ce qui a été mis sous les yeux du modèle.
        #
        # Le prompt en montrait cinq et l'acte en clôturait vingt : le
        # surplus était estampillé « traité » par une réponse qui ne le
        # mentionnait même pas, et devenait du même coup inéligible à la
        # promotion en pensée, qui ne relit que les observations
        # « écartées ». Le reste demeure en attente : il vieillira, sera
        # écarté, et pourra alors devenir une rumination — ce qui est
        # exactement ce qu'on veut d'un signal pertinent qu'elle n'a pas
        # traité.
        if brief.observations:
            montrees = list(brief.observations)
            for obs in montrees:
                obs.status = "acted"
                obs.action_response = output.text[:200]
            await sync_to_async(Observation.objects.bulk_update)(
                montrees, ["status", "action_response"], batch_size=50,
            )

        # Même règle pour les rendez-vous qu'elle s'était donnés. Dix
        # étaient marqués « exécutés » au seul motif que l'appel n'avait pas
        # planté, alors que trois seulement figuraient dans le prompt : sept
        # intentions disparaissaient à chaque acte, et le journal annonçait
        # « Executed 10 scheduled action(s) ».
        if brief.actions and all(action_confirmee(a, bilan_outils) for a in brief.actions):
            from django.utils import timezone as tz
            now_tz = tz.now()
            montrees_actions = list(brief.actions)
            for action in montrees_actions:
                action.status = ScheduledAction.Status.EXECUTED
                action.raison_echec = ""
                action.reessayer_le = None
                action.executed_at = now_tz
                action.tentatives = (action.tentatives or 0) + 1
                action.resultat = output.text[:500]
                action.context_data = {**action.context_data, "execution": bilan_outils.preuves}
                action.context_data.pop("reserved_until", None)
                await sync_to_async(enregistrer_tentative)(action, [
                    "status", "executed_at", "tentatives", "resultat", "context_data",
                    "raison_echec", "reessayer_le",
                ])
            logger.info(
                "Exécuté %d action(s) programmée(s) sur %d dues",
                len(montrees_actions), len(ctx.scheduled_actions),
            )

        elif brief.actions:
            await action_non_confirmee(moteur, brief.actions, bilan_outils)

        if bilan_outils:
            logger.info("Conscience tool calls: %s", bilan_outils)

        # `had_tools` se lit désormais sur les RÉUSSITES et non sur le fait
        # qu'un nom d'outil soit passé : `output.tool_calls` est une liste
        # de chaînes que la boucle remplit avant même de savoir ce que le
        # handler a rendu. Trois outils qui plantent assouvissaient donc la
        # curiosité exactement comme trois qui aboutissent — la pulsion la
        # plus difficile à satisfaire du moteur était la plus facile à
        # tromper.
        drive_engine.on_act(
            had_tools=outils_reussis > 0,
            word_count=len(output.text.split()),
        )

        # Seules les préoccupations présentées et évoquées sont soulagées.
        themes_montres = {
            t for o in brief.observations for t in (o.themes or [])
        } | {t for r in brief.ruminations for t in (r.get("themes") or [])}
        await moteur._resolve_ruminations_after_act(
            themes={t for t in themes_montres if re.search(
                r"(?<!\w)" + re.escape(str(t)) + r"(?!\w)", output.text, re.IGNORECASE,
            )},
        )

        logger.info(
            "Conscience acted [%s] (modules=%s, outils=%s): %s",
            reason, relevant_modules, bilan_outils or "aucun",
            output.text[:80],
        )
        return ActeResultat(
            dit=output.text,
            person_id=person_id,
            interne=interne,
            outils=bilan_outils,
            outils_reussis=outils_reussis,
            trousse=tuple(relevant_modules),
        )

    except Exception:
        logger.exception("Conscience act failed")
        # Là encore, seulement ce qui a été montré : une observation que le
        # modèle n'a jamais vue n'a pas « échoué », elle n'a pas été tentée.
        montrees = list(brief.observations)
        if montrees:
            for obs in montrees:
                obs.status = "failed"
            try:
                await sync_to_async(Observation.objects.bulk_update)(
                    montrees, ["status"], batch_size=50,
                )
            except Exception:
                logger.warning(
                    "Could not mark %d observation(s) as failed",
                    len(montrees), exc_info=True,
                )
        # La réservation persiste : une exception peut survenir APRÈS un
        # effet externe. Sans preuve de non-exécution, aucun rejeu automatique.
        return ActeResultat(person_id=person_id, ai_failed=True)


# ── Le destinataire ───────────────────────────────────────────────


async def select_recipient(moteur, ctx: DecisionContext) -> str | None:
    """Pass 1 of proactive speech: pick whom to address, or no one.

    Routing is memory-grounded (``who_is_concerned``) then confirmed by Mika
    via a ``[TO:person_id]`` tag. The candidate prompt is privacy-safe — only
    names + channels, never another person's private memory content.
    Returns a reachable ``person_id`` or None (keep it internal/broadcast).

    Le signal se lit sur les observations, PUIS sur les ruminations : les
    cinq déclencheurs endogènes — inactivité, salutation, humeur, pulsion,
    rumination — ne créent aucune Observation, si bien que la sélection
    rendait ``None`` avant même de chercher. C'était le miroir exact du
    défaut B1 de la trousse : au moment précis où SOCIAL déborde (« envie
    de parler à quelqu'un »), elle était structurellement incapable de
    choisir un quelqu'un.

    Et quand la mémoire ne désigne personne, deux maillons de repli :
    les personnes **présentes** (saluer celui qui est là plutôt que
    parler dans le vide), puis celles qui **manquent** — un ami joignable
    en différé et sans nouvelles depuis des jours (`who_misses_contact`).
    Le dernier mot reste au modèle (``[TO:none]`` est une réponse
    valide), et le backoff des relances ignorées borne déjà la fréquence.
    """
    from old.backend.conscience.recipients import parse_to_tag

    signal = " ".join(
        o.summary for o in ctx.pending_observations if o.pertinence > 0.3
    ).strip()
    if not signal:
        lignes = getattr(ctx, "rumination_lignes", None) or []
        signal = " ".join(
            str(ligne.get("summary", ""))[:160]
            for ligne in lignes[:3]
            if ligne.get("summary")
        ).strip()

    candidates = (
        await moteur.memory.who_is_concerned(signal, n=5) if signal else []
    )
    if not candidates:
        candidates = candidats_presents()
    if not candidates and moteur._detresse_soutenue():
        # Quand ça va mal depuis un moment et que personne n'est là, on
        # va vers le proche auprès de qui on se sent bien — la régulation
        # émotionnelle est sociale. AVANT le manque : la détresse choisit
        # le réconfortant, pas le plus longtemps silencieux.
        candidates = await moteur.memory.who_comforts(n=1)
    if not candidates:
        # n=1 : quand on a envie de parler, on pense à QUELQU'UN — la
        # personne au plus fort manque — pas à une liste de contacts.
        candidates = await moteur.memory.who_misses_contact(n=1)
    if not candidates:
        return None

    lines: list[str] = []
    allowed: list[str] = []
    for c in candidates[:5]:
        handles = c.get("handles") or []
        if not handles:
            continue
        pid = handles[0]["person_id"]
        channel = handles[0]["channel"]
        allowed.append(pid)
        # La note donne au modèle sa raison de choisir — « sans nouvelles
        # depuis 12 jour(s) » est un motif, un nom nu n'en est pas un.
        note = str(c.get("note") or "").strip()
        suffixe = f" — {note}" if note else ""
        lines.append(f"  [{pid}] {c['name']} ({channel}){suffixe}")

    if not allowed:
        return None

    prompt = (
        "Un evenement te concerne. Voici les personnes joignables qu'il "
        "pourrait interesser :\n"
        + "\n".join(lines)
        + "\n\nVeux-tu en parler a quelqu'un ? Reponds UNIQUEMENT par "
        "[TO:person_id] avec un id de la liste, ou [TO:none] si tu preferes "
        "ne rien dire a personne pour l'instant."
    )

    budget = cfg_int(
        "conscience.recipient_timeout_seconds", _RECIPIENT_TIMEOUT_S, mini=1,
    )
    try:
        from old.backend.ai.client import ai_client
        from old.backend.ai.router import AIRole

        raw = await asyncio.wait_for(
            ai_client.complete(
                system_prompt="Tu choisis a qui t'adresser. Reponds uniquement avec un tag [TO:...].",
                user_prompt=prompt,
                role=AIRole.SIGNAL_INTERPRETATION,
            ),
            timeout=budget,
        )
    except asyncio.TimeoutError as exc:
        degradations.record("conscience: choix du destinataire expire", exc)
        logger.warning(
            "Recipient selection timed out after %ds; staying internal",
            budget,
        )
        return None
    except Exception as exc:
        degradations.record("conscience: choix du destinataire", exc)
        logger.exception("Recipient selection failed; staying internal")
        return None

    target = parse_to_tag(raw, allowed)
    logger.info(
        "Conscience recipient selection: target=%s (candidates=%s)",
        target, allowed,
    )
    return target


def candidats_presents() -> list[dict]:
    """Les personnes identifiables PRÉSENTES — un socket vivant, forme candidate.

    Même contrat de retour que ``who_is_concerned`` (nom + handles), pour
    que la passe de confirmation n'ait pas deux formes à lire. Uniquement
    les personnes identifiables : un socket ``anon_*`` reste couvert par
    le broadcast global, et la tuyauterie interne n'est pas quelqu'un.

    **Consumers seulement, jamais les handles modules.** ``reachable()``
    contient aussi les handles durables (Telegram), réinscrits à chaque
    boot par ``restore_module_presence`` : les compter « présents »
    ferait de ce maillon un court-circuit permanent du manque — le
    propriétaire Telegram serait « là » à chaque acte endogène, sans
    rythme, sans préférence, sans anti-double-texte. Être joignable en
    différé est précisément la juridiction de ``who_misses_contact``.

    Ne lève jamais — chemin d'un acte, boucle sans superviseur.
    """
    from old.backend.communication.presence import presence_registry
    from old.backend.identity.trust import is_identifiable_person

    candidats: list[dict] = []
    vus: set[str] = set()
    try:
        for inter in presence_registry.reachable():
            pid = inter.person_id
            if getattr(inter, "kind", "") != "consumer":
                continue
            if pid in vus or not is_identifiable_person(pid):
                continue
            vus.add(pid)
            candidats.append({
                "name": inter.display_name or pid,
                "score": 0.0,
                "handles": [{
                    "person_id": pid,
                    "channel": inter.channel,
                    "kind": inter.kind,
                }],
            })
            if len(candidats) >= _PRESENTS_MAX:
                break
    except Exception as exc:
        degradations.record("conscience: candidats presents", exc)
        return []
    return candidats


# ── La trousse de l'acte ──────────────────────────────────────────


def modules_enregistres() -> list[str]:
    """Qui EXISTE, et non qui tourne.

    La distinction est le correctif B2 : `tools_for` jetait sans un mot un
    nom qu'aucun module ne porte — et `Observation.source` vaut
    « frontend » ou « telegram », qui ne sont des modules ni l'un ni
    l'autre. En passant la liste des enregistrés, un nom non servi devient
    visible (`Trousse.inconnus`) au lieu de disparaître.

    Lu en mémoire (`registry.all_registered()`) et non via `list_all()`,
    qui interroge `ModuleState` en base : ceci s'exécute à chaque acte.
    """
    from old.backend.modules.manager import module_manager

    try:
        return [m.name for m in module_manager.registry.all_registered()]
    except Exception as exc:
        # Sans cette liste, `preparer` accepte tout et le correctif B2
        # s'éteint à moitié — mieux vaut la trousse dégradée que pas
        # d'acte du tout, mais ça se compte.
        degradations.record("conscience: inventaire des modules", exc)
        return []


def poids_module(nom: str) -> int:
    """Le poids en caractères de déclaration d'un module."""
    from old.backend.modules.manager import module_manager

    try:
        return tools_prompt_chars(module_manager.get_tools_for_modules([nom]))
    except Exception as exc:
        degradations.record("conscience: poids d'un module", exc)
        # Compté comme cher plutôt que gratuit : un poids inconnu qui
        # vaudrait 0 ferait entrer n'importe quoi sous le plafond.
        return DEFAULT_TROUSSE_TUNING.plafond_caracteres


def preparer_trousse(moteur, ctx: DecisionContext):
    """Quels outils accompagnent CET acte.

    Remplace `_pick_relevant_modules`, qui dérivait la trousse des seules
    `obs.source` : les déclencheurs qui font la vie du personnage —
    inactivité, salutation, débordement d'humeur, pulsions, ruminations —
    ne créent aucune Observation, si bien que le seul cas où elle agissait
    d'elle-même était aussi le seul où elle n'avait aucune main.

    Les actions programmées dues passent leurs ``modules`` en demandes
    explicites — le rang que ``souhaits`` réserve à « une intention déjà
    formée ». Ce paramètre existait depuis le premier jour de la trousse
    et n'avait AUCUN appelant : « vérifie tes emails demain matin »
    partait sans l'outil email, le prompt lui interdisait de raconter, et
    le rendez-vous était marqué honoré quand même.
    """
    demandes = [
        str(nom)
        for action in ctx.scheduled_actions
        for nom in (getattr(action, "modules", None) or ())
    ]
    trousse = preparer(
        sources=[obs.source for obs in ctx.pending_observations],
        drives=drive_engine.states,
        demandes=demandes,
        poids=moteur._poids_module,
        disponibles=moteur._modules_enregistres(),
        tuning=moteur._trousse_tuning(),
    )
    if trousse.inconnus:
        logger.warning(
            "Trousse: %d nom(s) sans module servant: %s",
            len(trousse.inconnus), list(trousse.inconnus),
        )
    return trousse


# ── Le prompt de l'acte ───────────────────────────────────────────


async def build_action_prompt(
    moteur,
    ctx: DecisionContext,
    *,
    en_main: str = "",
    a_demander: str = "",
    vecu: str = "",
) -> ActionBrief:
    """Construire le prompt de ce qui est propre a CETTE decision.

    Volontairement muet sur l'humeur, les pulsions, les ruminations et le
    contexte memoire : le `ConversationContext` monte par `act()` porte
    deja les quatre dans le prompt systeme
    (`--- TON ETAT EMOTIONNEL ACTUEL ---` contient l'humeur globale suivie
    de `drive_engine.get_context()`, `--- CE QUI TE TROTTE DANS LA TETE ---`
    les memes trois ruminations, et la memoire est ajoutee brute en fin de
    prompt). Les redire ici envoyait plusieurs centaines de tokens en
    double a chaque acte — le chemin le plus cher du moteur, repaye a
    chaque tour de la boucle d'outils.

    Ce qui reste est ce que rien d'autre ne sait : les actions programmees
    dues, les observations, la raison du declenchement, l'auto-evaluation
    et les actions futures.

    `en_main` et `a_demander` remplacent l'ancien `capabilities_summary`,
    et la separation est le correctif : un seul bloc enumerait TOUT ce qui
    tourne sous « ce que tu peux faire », pendant que la trousse etait le
    plus souvent vide. Un modele a qui on annonce des capacites qu'on ne
    lui donne pas raconte l'action au lieu de la faire — et le journal, les
    souvenirs et la fiche de la personne se remplissent de choses qu'elle
    croit avoir faites. Ce qui est en main est appelable ; ce qui est
    ailleurs se dit a voix haute, faute d'outil pour l'ouvrir.
    """
    parts = []

    # Les deux bornes sont retenues, pas seulement appliquées : l'acte ne
    # doit clore que ce qui a été mis sous les yeux du modèle.
    inclure_action = cfg_bool("conscience.brief.include_scheduled_action", True)
    observations_max = cfg_int(
        "conscience.brief.observations_max", _BRIEF_OBSERVATIONS_MAX, mini=0)
    actions_montrees = tuple(ctx.scheduled_actions[:1]) if inclure_action else ()
    observations_montrees = tuple(ctx.pending_observations[:observations_max])

    # Scheduled actions due (highest priority — these are self-assigned tasks)
    if actions_montrees:
        action_lines = []
        for act_ in actions_montrees:
            action_lines.append(f"- {act_.prompt[:200]}")
            if act_.context_data:
                action_lines.append(
                    f"  Contexte: {json.dumps(act_.context_data, ensure_ascii=False)[:200]}"
                )
        parts.append(
            "Actions que tu avais programmees et qui sont maintenant dues:\n"
            + "\n".join(action_lines)
            + "\nExecute ces actions dans ta reponse."
        )

    # What you've observed
    if observations_montrees:
        obs_lines = []
        for obs in observations_montrees:
            obs_lines.append(f"- [{obs.source}] {obs.summary} (pertinence: {obs.pertinence:.1f})")
        parts.append(
            "Ce que tu as observe recemment:\n" + "\n".join(obs_lines)
        )

    # Idle time
    idle_minutes = int(ctx.idle_seconds / 60)
    if idle_minutes > 2:
        parts.append(f"Personne ne t'a parle depuis {idle_minutes} minutes.")

    # Ce qui la pousse à parler, TOUS les motifs à la fois.
    #
    # Remplace quatre `elif` sur des sous-chaînes de `reason` : la chaîne
    # n'en gardait qu'un, alors qu'un cycle cumule couramment salutation et
    # débordement d'humeur ; et l'inactivité comme les pulsions faisaient
    # monter le score sans qu'aucune phrase ne les nomme. La lecture de
    # `reason` disparaît d'ici — c'est une chaîne de diagnostic, pas une
    # source de vérité sur l'état.
    if vecu:
        parts.append(vecu)

    # Self-awareness
    if ctx.acts_today > 0:
        parts.append(f"Tu as deja pris la parole {ctx.acts_today} fois aujourd'hui.")
    if ctx.consecutive_ignored_acts >= 2:
        parts.append(
            f"Tes {ctx.consecutive_ignored_acts} dernieres interventions "
            "n'ont recu aucune reponse. Sois plus discrete ou change d'approche."
        )

    # Ce qui est réellement appelable maintenant…
    if en_main:
        parts.append(en_main)
    # …et ce qui existe ailleurs, qu'elle ne peut que mentionner.
    if a_demander:
        parts.append(a_demander)

    # Upcoming scheduled actions (so Claude knows what's already planned)
    upcoming = await moteur._get_upcoming_actions()
    if upcoming:
        upcoming_lines = [f"- Dans {mins}min: {a.prompt[:80]}" for a, mins in upcoming]
        parts.append(
            "Tu as deja programme ces actions futures:\n"
            + "\n".join(upcoming_lines)
        )

    # Instructions
    parts.append(
        "\nExprime-toi naturellement et spontanement, "
        "en accord avec ce que tu observes et ressens. "
        "Sois breve (1-3 phrases max). "
        "Tu peux utiliser tes outils si la situation le demande."
    )

    return ActionBrief(
        texte="\n\n".join(parts),
        observations=observations_montrees,
        actions=actions_montrees,
        ruminations=tuple(
            r for r in ctx.rumination_lignes if r.get("intensity", 0) >= 0.2
        )[:3],
    )
