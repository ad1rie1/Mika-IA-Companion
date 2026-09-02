"""Le monde des chantiers — sorti du moteur, sans changer un octet de sa surface.

``engine.py`` portait huit responsabilités et dépassait les trois mille lignes ;
tout ce qui fait vivre un ``Travail`` — le lire, le semer, l'ouvrir, lui faire
faire un pas, appliquer son verdict, le dire à voix haute, le refermer au
redémarrage — vit désormais ici.

**Des fonctions de module, pas une classe.** Les tests construisent le moteur
par ``__new__`` et patchent SES méthodes (``patch.object(type(e),
"_appeler_le_modele")``) : un collaborateur qui capturerait ces callables à la
construction les rendrait impatchables, et un collaborateur instancié dans
``__init__`` n'existerait pas sur un moteur ``__new__``. Le moteur garde donc
des délégués d'une ligne — chaque nom de méthode survit — et ``faire_un_pas``
orchestre *à travers* cette surface (``moteur._appeler_le_modele``,
``moteur._appliquer_verdict``…), si bien qu'un patch posé sur le moteur
continue de porter.

Les constantes de repli des clés ``conscience.travail.*`` déménagent avec
leurs sites d'appel : la garde AST de ``test_config_rapatriement`` résout un
repli ``ast.Name`` en attribut du module *appelant*, et un site qui lirait sa
constante dans un autre module lui serait invisible.
"""

from __future__ import annotations

import logging

from asgiref.sync import sync_to_async
from django.db.models import F

from configs.runtime import cfg_float, cfg_int
from conscience.conduite import (
    PULSIONS_FECONDES,
    Conduite,
    ConduiteTuning,
    Graine,
    TravailEnCours,
    decider_diffusion,
    est_essouffle,
    facturer_envie,
    recolter_graines,
)
from conscience.verdict import (
    CONSIGNE_VERDICT,
    EtatVerdict,
    VerdictTuning,
)
from conscience.trousse import preparer
from conscience import estime
from drives.engine import drive_engine
from emotion.engine import emotion_engine
from utils.degradation import degradations, degraded

logger = logging.getLogger(__name__)

#: Pas maximum d'un chantier avant qu'il soit clos d'office. Un travail sans
#: terme n'est pas un travail.
_TRAVAIL_PAS_MAX = 5
#: Sujets retenus parmi ceux que les modules proposent. Petit : c'est une
#: curiosité, pas un inventaire — et chacun concourt aux trois places.
_GRAINES_MODULES_MAX = 3
#: Mémoire des amorces semées : une graine dont un chantier est né dans cette
#: fenêtre ne rouvre rien, **quel que soit le sort du chantier**. La
#: déduplication ne se lisait que sur les chantiers vivants, or une graine
#: survit à son chantier — une Observation reste « en attente » trente
#: minutes, une Rumination à 0.5 vit des heures — si bien qu'un chantier fini
#: ou bloqué au cycle N+1 rouvrait la même amorce au cycle N+2 : un appel
#: LLM à boucle d'outils par itération, et à chaque FINI un souvenir, une
#: fierté et +0.05 d'estime (le plafond en neuf tours) ; à chaque BLOQUÉ une
#: frustration, une rumination « je bloque sur… » de plus et −0.04 d'estime.
_SEMIS_MEMOIRE_S = 24 * 3600
#: Intensité de la fierté ressentie quand un chantier aboutit — la même que
#: celle que sa diffusion déclare (`peut_etre_dire_le_travail`, proud 0.4) :
#: une seule vérité émotionnelle pour un même événement.
_FIERTE_TRAVAIL_ABOUTI = 0.4
#: L'échec fait mal — c'était l'asymétrie centrale du dossier psychologique :
#: seul le FINI produisait un affect, un chantier bloqué ou abandonné était
#: émotionnellement muet. L'appraisal de l'obstruction d'un but est LA source
#: humaine de la frustration (Lazarus/Scherer), et c'est cette douleur-là qui
#: rend l'échec racontable. Constantes et non clés de configuration : ces
#: intensités sont de la même famille que les ancres PAD — la physique du
#: personnage, pas un réglage d'exploitation.
_FRUSTRATION_TRAVAIL_BLOQUE = 0.35
#: L'abandon est plus doux que le blocage : l'envie s'est éteinte d'elle-même,
#: on ne se cogne pas à un mur — on remarque qu'on a lâché. Une mélancolie
#: légère, pas une frustration.
_MELANCOLIE_TRAVAIL_ABANDONNE = 0.25
#: Le soulagement d'une attente exaucée — la personne qu'un chantier
#: attendait a répondu. C'est l'embryon du modèle d'attentes : une
#: prédiction que le système tenait déjà, qui se réalise, et qui enfin SE
#: RESSENT au lieu de n'être qu'un UPDATE de drapeau.
_SOULAGEMENT_REPONSE_ATTENDUE = 0.3


# ── Réglages, résolus ici — `conduite.py` et `verdict.py` restent purs ────


def conduite_tuning() -> ConduiteTuning:
    """Les seuils de la conduite, lus dans la configuration."""
    d = ConduiteTuning()
    f = lambda cle, repli: cfg_float(f"conscience.{cle}", repli)  # noqa: E731
    i = lambda cle, repli: cfg_int(f"conscience.{cle}", repli)    # noqa: E731
    return ConduiteTuning(
        graine_obs_pertinence=f(
            "travail.graine_obs_pertinence", d.graine_obs_pertinence),
        graine_pensee_intensite=f(
            "travail.graine_pensee_intensite", d.graine_pensee_intensite),
        graine_pulsion_tension=f(
            "travail.graine_pulsion_tension", d.graine_pulsion_tension),
        graines_max=i("travail.graines_max", d.graines_max),
        envie_demi_vie_s=f("travail.envie_demi_vie_s", d.envie_demi_vie_s),
        envie_plancher_abandon=f(
            "travail.envie_plancher_abandon", d.envie_plancher_abandon),
        envie_poursuite_min=f(
            "travail.envie_poursuite_min", d.envie_poursuite_min),
        ouverture_envie_min=f(
            "travail.ouverture_envie_min", d.ouverture_envie_min),
        travaux_actifs_max=i(
            "travail.travaux_actifs_max", d.travaux_actifs_max),
        pas_intervalle_min_s=f(
            "travail.pas_intervalle_min_s", d.pas_intervalle_min_s),
        diffusion_notable_min=f(
            "travail.diffusion_notable_min", d.diffusion_notable_min),
        diffusion_intervalle_min_s=f(
            "travail.diffusion_intervalle_min_s",
            d.diffusion_intervalle_min_s),
    )


def verdict_tuning() -> VerdictTuning:
    """Les deux bornes de délai. Les quatre bornes de recopie ne sont pas
    déclarées : ce sont des gardes d'un lecteur face à une sortie hostile,
    même famille que la taille maximale d'un source forgé."""
    d = VerdictTuning()
    return VerdictTuning(
        delai_defaut_s=cfg_float(
            "conscience.verdict.delai_defaut_s", d.delai_defaut_s),
        delai_max_s=cfg_float(
            "conscience.verdict.delai_max_s", d.delai_max_s),
    )


# ── Lecture et récolte ────────────────────────────────────────────────────


def _apaiser_les_pensees(references, *, resoudre: bool = False) -> int:
    """Une pensée dont le chantier se ferme cesse d'insister.

    Résolue s'il a abouti — elle a fait la chose ; divisée par deux sinon
    (bloqué, abandonné, clos au redémarrage) — elle a essayé, et l'échec a
    déjà sa propre pensée (« je bloque sur… »). Ne rien faire laissait la
    rumination entière, au-dessus de la porte des graines, prête à rouvrir le
    même chantier dès que la déduplication cessait de la voir.

    Synchrone, à appeler DANS le callable de l'écrivain qui change le statut :
    les deux sont un seul fait. Tolère des références qui ne sont pas des pk.
    """
    from conscience.models import Rumination

    pks = [int(r) for r in references if str(r).isdigit()]
    if not pks:
        return 0
    actives = Rumination.objects.filter(pk__in=pks, status="active")
    if resoudre:
        return actives.update(status="resolved")
    return actives.update(intensity=F("intensity") * 0.5)


async def travaux_en_cours(maintenant) -> tuple[list, set]:
    """Les chantiers vivants, et les amorces déjà semées.

    Le second élément est la clé de déduplication `(origine, reference)` :
    sans elle, une `Observation` reste « en attente » trente minutes et
    rouvrirait le même chantier à chaque cycle — trois places saturées en
    quatre-vingt-dix secondes. Elle couvre **tout chantier né dans les
    dernières `_SEMIS_MEMOIRE_S`**, pas seulement les vivants : une graine
    survit à son chantier, et un chantier fini ou bloqué rouvrait la même
    amorce au cycle suivant (voir la constante).

    L'abandon des essoufflés et le relâchement des attentes échues se font
    **dans le même callable synchrone** que la lecture.
    `sync_to_async(thread_sensitive=True)` sérialise sur un seul thread
    d'exécuteur : lire, boucler en RAM puis réécrire laisserait un autre
    écrivain s'intercaler entre les deux — le piège exact documenté sur
    `_decay_ruminations`.
    """
    from conscience.models import Travail
    from datetime import timedelta

    t = conduite_tuning()

    def _passe() -> tuple[list, set]:
        vivants: list[TravailEnCours] = []
        semees: set[tuple[str, str]] = set()
        a_abandonner: list = []
        a_reveiller: list = []
        # Les amorces de TOUS les chantiers récents, vivants ou non : c'est
        # le sort d'une graine, pas celui d'un chantier, qui décide si elle
        # peut resservir. Lue avant la boucle, qui n'y ajoute plus que les
        # vivants (une ligne vivante plus vieille que la fenêtre reste semée).
        semees.update(
            (origine, str(reference))
            for origine, reference in Travail.objects.filter(
                created_at__gte=maintenant - timedelta(seconds=_SEMIS_MEMOIRE_S),
            ).values_list("origine", "reference")
        )
        for row in Travail.objects.filter(statut=Travail.Statut.EN_COURS):
            # Une attente échue cesse d'en être une — ICI, parce que c'est
            # la seule relecture périodique des chantiers. Une échéance
            # absente (ligne d'avant la migration, verdict tronqué) se
            # relève aussi : un drapeau sans échéance est le cul-de-sac
            # exact que `reprendre_le` existe pour fermer.
            if row.en_attente_de_reponse and (
                row.reprendre_le is None or row.reprendre_le <= maintenant
            ):
                row.en_attente_de_reponse = False
                row.reprendre_le = None
                row.attend_qui = ""
                a_reveiller.append(row)
            vue = TravailEnCours(
                identifiant=row.pk,
                titre=row.titre,
                envie=row.envie,
                ancre_envie=row.ancre,
                dernier_pas_le=row.dernier_pas_le,
                pas_effectues=row.pas_effectues,
                pas_max=row.pas_max,
                en_attente_de_reponse=row.en_attente_de_reponse,
                themes=tuple(row.themes or ()),
            )
            if est_essouffle(vue, maintenant, t):
                row.statut = Travail.Statut.ABANDONNEE
                a_abandonner.append(row)
                continue
            vivants.append(vue)
            semees.add((row.origine, str(row.reference)))
        if a_abandonner:
            Travail.objects.bulk_update(a_abandonner, ["statut"])
            # L'abandon est un statut terminal comme les autres : la pensée
            # qui l'avait ouvert cesse d'insister, sinon elle rouvre le même
            # chantier dès que la mémoire des semis l'oublie.
            _apaiser_les_pensees(
                row.reference for row in a_abandonner
                if row.origine == Travail.Origine.PENSEE
            )
        if a_reveiller:
            Travail.objects.bulk_update(
                a_reveiller,
                ["en_attente_de_reponse", "reprendre_le", "attend_qui"],
            )
        return vivants, semees, len(a_abandonner)

    with degraded("conscience: reveil nominatif des attentes"):
        await _reveiller_attentes_nominatives(maintenant)

    try:
        vivants, semees, abandonnes = await sync_to_async(
            _passe, thread_sensitive=True,
        )()
    except Exception as exc:
        degradations.record("conscience: lecture des travaux", exc)
        return [], set()

    if abandonnes:
        # Remarquer qu'on a lâché quelque chose teinte — légèrement. Une
        # impulsion pour le lot, pas une par chantier : c'est le constat qui
        # pèse, pas l'inventaire. L'abandon n'ouvre PAS de rumination —
        # l'envie s'est éteinte d'elle-même, c'est sa définition ; seule la
        # couleur du moment reste.
        with degraded("conscience: melancolie d'un abandon"):
            from emotion.types import Emotion, EmotionData

            emotion_engine.process_emotion(
                EmotionData(
                    Emotion.MELANCHOLIC, _MELANCOLIE_TRAVAIL_ABANDONNE,
                ),
                "conscience_mika",
            )
    return vivants, semees


async def _reveiller_attentes_nominatives(maintenant) -> int:
    """Un message de la personne attendue relève l'attente avant l'échéance.

    « J'attends la réponse d'Adrien » et « je reprends dans une heure »
    étaient la même attente aveugle : seul le temps réveillait. Le nom écrit
    par le verdict se résout ICI, au réveil, par la couche identité
    (``handles_for_entity_names``) — jamais par égalité de nom à l'écriture,
    la personne pouvant se lier entre les deux. Le nom brut est aussi essayé
    comme ``person_id`` exact : le modèle a parfois un handle sous les yeux,
    et l'égalité de *transport* n'est pas l'égalité de nom que la couche
    identité remplace.

    Coût : une requête bornée par cycle éveillé ; la résolution et le test
    de messages ne se paient que s'il existe des attentes nominatives. La
    relève est un UPDATE conditionnel (``filter(en_attente_de_reponse=True)``)
    — pas de lecture-modification-écriture à faire écraser par un autre
    écrivain. Le brief interne d'un acte est exclu (``is_internal``) : son
    propre pas ne doit pas compter comme la réponse attendue.
    """
    from conscience.models import Travail

    def _en_attente() -> list[dict]:
        return list(
            Travail.objects.filter(
                statut=Travail.Statut.EN_COURS,
                en_attente_de_reponse=True,
            )
            .exclude(attend_qui="")
            .values("pk", "attend_qui", "dernier_pas_le")[:10]
        )

    attentes = await sync_to_async(_en_attente)()
    if not attentes:
        return 0

    from identity.resolver import identity_resolver

    try:
        handle_map = await identity_resolver.handles_for_entity_names(
            sorted({a["attend_qui"] for a in attentes})
        )
    except Exception as exc:
        degradations.record("conscience: resolution d'une attente", exc)
        handle_map = {}

    releves = 0
    for attente in attentes:
        depuis = attente["dernier_pas_le"]
        if depuis is None:
            continue
        pids = {
            h["person_id"]
            for h in handle_map.get(attente["attend_qui"], [])
        }
        pids.add(attente["attend_qui"])

        def _repondu(pids=tuple(pids), depuis=depuis) -> bool:
            from memory.models import Message

            return (
                Message.objects.filter(
                    person_id__in=list(pids), role="user",
                    created_at__gt=depuis,
                )
                .exclude(is_internal=True)
                .exists()
            )

        try:
            if not await sync_to_async(_repondu)():
                continue
            fait = await sync_to_async(
                lambda pk=attente["pk"]: Travail.objects.filter(
                    pk=pk, en_attente_de_reponse=True,
                ).update(
                    en_attente_de_reponse=False,
                    reprendre_le=None,
                    attend_qui="",
                ),
                thread_sensitive=True,
            )()
            if fait:
                releves += 1
                logger.info(
                    "Attente relevée : %s a répondu (travail #%s)",
                    attente["attend_qui"], attente["pk"],
                )
        except Exception as exc:
            degradations.record("conscience: relance d'une attente", exc)

    if releves:
        # « Enfin, il a répondu. » Une impulsion pour la passe : c'est le
        # soulagement qui compte, pas l'inventaire des attentes.
        with degraded("conscience: soulagement d'une reponse attendue"):
            from emotion.types import Emotion, EmotionData

            emotion_engine.process_emotion(
                EmotionData(Emotion.RELIEVED, _SOULAGEMENT_REPONSE_ATTENDUE),
                "conscience_mika",
            )
    return releves


def recolter(ctx, semees: set) -> list:
    """Les amorces que l'état courant contient, moins celles déjà semées.

    La déduplication passe **avant** `choisir_conduite` et non après : une
    amorce déjà transformée en chantier n'est plus une amorce, et la
    laisser concourir ferait choisir OUVRIR sur un objet qui existe déjà.
    """
    try:
        pulsion = drive_engine.pulsion_saillante()
        pulsions = (
            [(pulsion.value, drive_engine.states[pulsion].tension)]
            if pulsion else []
        )
        graines = recolter_graines(
            observations=ctx.pending_observations,
            pensees=ctx.rumination_lignes,
            pulsions=pulsions,
            tuning=conduite_tuning(),
        )
        graines = list(graines) + graines_des_modules(pulsion, pulsions)
        return [
            g for g in graines
            if (g.origine, str(g.reference)) not in semees
        ]
    except Exception as exc:
        degradations.record("conscience: recolte des graines", exc)
        return []


def graines_des_modules(pulsion, pulsions: list) -> list:
    """Ce que le monde propose, quand une pulsion féconde a de quoi s'en saisir.

    C'est la moitié manquante de H1. `recolter_graines` savait déjà tirer
    une amorce d'une pulsion, mais son intitulé ne pouvait être qu'une
    formule générique — « aller voir quelque chose de nouveau » — parce que
    rien ne lui disait ce qu'il y avait à voir. Une envie sans objet ne
    peut ouvrir aucun chantier ; elle ne peut que se redire.

    Les modules répondent **de mémoire** (`propose_sujets`), donc ceci
    coûte zéro requête, et n'est demandé que lorsque la pulsion franchit
    déjà sa porte : pas d'appétit, pas de sollicitation.

    `reference` porte le nom du module et le sujet, ce qui suffit à la
    déduplication : le même titre RSS ne rouvre pas de chantier tant que le
    premier vit.

    Les deux pulsions **fécondes** sollicitent (`PULSIONS_FECONDES`), pas
    la seule curiosité : l'expression veut produire quelque chose, et la
    forge — qui propose « réparer mon application » — est exactement une
    offre pour elle. SOCIAL et REST restent muets, comme dans la récolte.
    """
    if pulsion is None or getattr(pulsion, "value", "") not in PULSIONS_FECONDES:
        return []
    tension = pulsions[0][1] if pulsions else 0.0
    if tension < conduite_tuning().graine_pulsion_tension:
        return []

    try:
        from modules.manager import module_manager

        sujets = module_manager.collect_sujets()
    except Exception as exc:
        degradations.record("conscience: sujets proposes par les modules", exc)
        return []

    plafond = cfg_int(
        "conscience.travail.graines_modules_max", _GRAINES_MODULES_MAX, mini=0,
    )
    return [
        Graine(
            origine="pulsion",
            reference=f"{nom}:{sujet[:60]}",
            intitule=sujet,
            poids=tension,
            # Le module qui propose un sujet est celui dont le chantier
            # aura besoin pour le traiter : figé ici, il survit à la
            # retombée de la pulsion après le premier pas.
            modules=(nom,),
        )
        for nom, sujet in sujets[:plafond]
    ]


# ── Ouverture ─────────────────────────────────────────────────────────────


async def ouvrir_travail(graine) -> bool:
    """Poser un chantier en base, et consommer la graine. Aucun pas ici.

    Une observation devenue chantier est **traitée** (`acted`) dans le même
    callable synchrone que la création : elle a reçu une réponse — le
    chantier — et ne doit plus ni peser dans l'urgence du cycle suivant, ni
    se faire promouvoir en rumination à sa péremption, ni resservir de graine
    quand la mémoire des semis l'aura oubliée. Une pensée, elle, n'est pas
    consommée à l'ouverture (elle n'a pas encore été faite) : c'est le
    verdict terminal qui l'apaise (`_apaiser_les_pensees`). Une référence qui
    n'est pas un pk (les doubles des tests, une pulsion) ne touche rien.
    """
    from conscience.models import Observation, Travail
    from django.utils import timezone as tz

    reference = str(graine.reference)[:100]
    titre = graine.intitule[:200]

    def _creer() -> None:
        Travail.objects.create(
            titre=titre,
            origine=graine.origine,
            reference=reference,
            themes=list(graine.themes),
            # La trousse du chantier, figée à l'ouverture : c'est elle que
            # chaque pas rechargera, indépendamment de la tension de
            # pulsion du moment (que le premier pas réussi fait retomber).
            modules=[str(m) for m in (getattr(graine, "modules", ()) or ())],
            envie=max(0.0, min(1.0, graine.poids)),
            ancre_envie=tz.now(),
            pas_max=cfg_int("conscience.travail.pas_max", _TRAVAIL_PAS_MAX,
                            mini=1),
        )
        if graine.origine == Travail.Origine.OBSERVATION and reference.isdigit():
            Observation.objects.filter(
                pk=int(reference), status=Observation.Status.PENDING,
            ).update(
                status=Observation.Status.ACTED,
                action_response=f"chantier ouvert : {titre}"[:200],
            )

    try:
        await sync_to_async(_creer, thread_sensitive=True)()
        logger.info("Travail ouvert [%s]: %s", graine.origine, graine.intitule[:80])
        return True
    except Exception as exc:
        degradations.record("conscience: ouverture d'un travail", exc)
        return False


# ── Le pas ────────────────────────────────────────────────────────────────


async def build_work_prompt(row) -> str:
    """Le prompt d'un pas de chantier.

    Délibérément **distinct** de `_build_action_prompt`, qui répond à une
    autre question : « pourquoi je prends la parole maintenant ». Ici la
    question est « où j'en suis et quel est le pas suivant ». Réutiliser
    l'autre ferait arriver dans un travail silencieux les salutations,
    l'auto-évaluation des relances ignorées et l'injonction à être brève —
    c'est-à-dire tout ce qui n'a de sens que devant quelqu'un.
    """
    parts = [
        f"Tu avances sur quelque chose que tu as décidé de faire : "
        f"« {row.titre} ».",
    ]
    if row.themes:
        parts.append("Thèmes : " + ", ".join(str(t) for t in row.themes[:6]) + ".")
    if row.pas_effectues:
        parts.append(
            f"Tu en es au pas {row.pas_effectues + 1} sur {row.pas_max}."
        )
    if row.resultat:
        # Sa mémoire du chantier. Nettoyée de la prosodie, que le
        # processeur n'applique qu'au texte destiné à une voix : sans ça,
        # les `[SIGH]` d'un pas précédent reviendraient dans le prompt du
        # suivant et finiraient dans les souvenirs.
        from emotion.types import strip_prosody
        parts.append("Ce que tu as déjà fait :\n" + strip_prosody(row.resultat)[-1200:])
    parts.append(
        "Fais UN pas, un seul — le plus utile maintenant. Tu peux te "
        "servir de tes outils. Personne ne te lit : c'est un travail, pas "
        "une conversation."
    )
    parts.append(CONSIGNE_VERDICT)
    return "\n\n".join(parts)


def preparer_trousse_travail(moteur, row):
    """La trousse d'un pas : le socle, plus ce que LE CHANTIER demande.

    ``row.modules`` — figé à l'ouverture depuis la graine — passe en
    demande explicite, le rang le plus fort après le socle. C'est ce qui
    garantit qu'un chantier garde ses mains toute sa vie : la version
    précédente ne dérivait la trousse que des pulsions *du moment*, or le
    premier pas réussi assouvit la curiosité (``on_act``, −0.5), si bien
    que le pas suivant partait sans les outils qui avaient ouvert le
    chantier. L'élargissement par pulsion reste, en plus, jamais à la
    place.
    """
    return preparer(
        sources=(),
        drives=drive_engine.states,
        demandes=tuple(str(m) for m in (row.modules or ())),
        poids=moteur._poids_module,
        disponibles=moteur._modules_enregistres(),
        tuning=moteur._trousse_tuning(),
    )


async def faire_un_pas(moteur, identifiant) -> bool:
    """Faire avancer un chantier d'un pas. Rend True si le pas a eu lieu.

    Muet par défaut : un pas ne diffuse ni ne persiste. Quatre travaux à
    cinq pas feraient vingt monologues par jour, et ceux-là passeraient
    **hors** du frein quotidien des initiatives — le compteur qui existe
    précisément pour qu'elle ne devienne pas envahissante.

    Orchestre **à travers la surface du moteur** (``moteur._appeler_le_modele``,
    ``moteur._appliquer_verdict``…) : c'est ce qui fait qu'un patch posé sur
    le moteur par un test continue de porter après l'extraction.
    """
    from conscience.models import Travail
    from django.utils import timezone as tz

    maintenant = tz.now()

    def _prendre():
        """Marquer le pas AVANT l'appel, et sous condition.

        `filter(dernier_pas_le=…)` fait de la prise un test-and-set : deux
        cycles concurrents ne peuvent pas partir sur le même chantier. Et
        le compteur monte **à la prise**, pas au succès — sinon un pas qui
        tue le process serait rejoué indéfiniment au redémarrage, ce que
        `resume_interrupted_turns` a déjà appris à ses dépens.
        """
        pris = Travail.objects.filter(
            pk=identifiant, statut=Travail.Statut.EN_COURS,
        ).update(
            pas_effectues=F("pas_effectues") + 1,
            dernier_pas_le=maintenant,
        )
        if not pris:
            return None
        return Travail.objects.filter(pk=identifiant).first()

    try:
        row = await sync_to_async(_prendre, thread_sensitive=True)()
    except Exception as exc:
        degradations.record("conscience: prise d'un pas", exc)
        return False
    if row is None:
        return False

    prompt = await moteur._build_work_prompt(row)
    trousse = moteur._preparer_trousse_travail(row)

    try:
        output, bilan, reussites = await moteur._appeler_le_modele(
            prompt,
            person_id="conscience_mika",
            modules=list(trousse.modules),
            metadata={"travail": identifiant, "titre": row.titre},
            broadcast=False,
            persist=False,
        )
    except Exception as exc:
        degradations.record("conscience: pas de travail", exc)
        return False

    if output.ai_failed:
        # Le pas n'a pas eu lieu : on rend son crédit. Sans ça, sur une
        # installation dont le rôle n'est pas mappé — et le dépôt démarre
        # non configuré exprès — cinq `UnconfiguredRoleError` consommeraient
        # les cinq pas, et elle serait frustrée d'un travail jamais tenté.
        await moteur._rendre_le_pas(identifiant)
        return False

    from conscience.verdict import depouiller_verdict

    dit, verdict = depouiller_verdict(output.text, verdict_tuning())
    await moteur._appliquer_verdict(identifiant, verdict, dit, bilan)
    await moteur._peut_etre_dire_le_travail(
        verdict, dit, row.titre, tuple(row.themes or ()),
    )
    drive_engine.on_act(had_tools=reussites > 0, word_count=len(dit.split()))
    logger.info(
        "Pas de travail #%s [%s] outils=%s : %s",
        identifiant, verdict.etat.value, bilan or "aucun", dit[:80],
    )
    return True


async def rendre_le_pas(identifiant) -> None:
    """Rendre le crédit d'un pas qui n'a pas eu lieu."""
    from conscience.models import Travail

    with degraded("conscience: restitution d'un pas"):
        await sync_to_async(
            lambda: Travail.objects.filter(pk=identifiant).update(
                pas_effectues=F("pas_effectues") - 1,
            ),
            thread_sensitive=True,
        )()


# ── Le verdict et ses suites ──────────────────────────────────────────────


async def appliquer_verdict(moteur, identifiant, verdict, dit, bilan) -> None:
    """Écrire ce que le pas a produit — **un seul callable synchrone**.

    Lire, décider en RAM puis réécrire laisserait un autre écrivain
    s'intercaler : `sync_to_async(thread_sensitive=True)` sérialise tout
    sur un thread unique, et c'est le piège documenté sur
    `_decay_ruminations`, où la digestion nocturne se faisait écraser.

    Un verdict illisible n'est pas une erreur, c'est un état : il se
    compte, et au bout de quelques-uns le chantier se bloque plutôt que de
    tourner indéfiniment sans jamais savoir où il en est.

    Un chantier qui ABOUTIT laisse un souvenir ET une fierté ressentie —
    hors du callable synchrone, parce que la création passe par le vector
    store. Sans le souvenir, elle passait ses journées à mener des choses
    au bout dont il ne restait rien ; sans l'impulsion, elle se serait
    souvenue d'avoir été fière sans l'avoir jamais été sur le moment.
    """
    from conscience.models import Rumination, Travail
    from django.utils import timezone as tz

    t = conduite_tuning()
    maintenant = tz.now()

    def _ecrire() -> dict | None:
        row = Travail.objects.filter(pk=identifiant).first()
        if row is None:
            return None

        journal = (row.resultat + "\n\n" + dit).strip() if dit else row.resultat
        row.resultat = journal[-6000:]

        if verdict.etat is EtatVerdict.FINI:
            row.statut = Travail.Statut.ABOUTIE
        elif verdict.etat is EtatVerdict.BLOQUE:
            row.statut = Travail.Statut.BLOQUEE
            row.raison_blocage = verdict.motif_blocage[:500]
        elif verdict.etat is EtatVerdict.ATTENDRE:
            # Le drapeau et son échéance sont les deux moitiés d'un même
            # geste (le motif de l'envie et son ancre) : le drapeau seul
            # était un cul-de-sac — posé ici, relevé par personne,
            # « attendre » signifiait « se faner jusqu'à l'abandon » et
            # `delai_s`, soigneusement borné par le lecteur, n'avait
            # aucun consommateur. `is not None` et non `or` : 0 s est un
            # délai légal (« tout de suite »), pas une absence.
            from datetime import timedelta
            delai = (
                verdict.delai_s if verdict.delai_s is not None else 300.0
            )
            row.en_attente_de_reponse = True
            row.reprendre_le = maintenant + timedelta(seconds=delai)
            # Qui elle attend, si le verdict le nomme : un message de cette
            # personne la réveillera avant l'échéance. Écrit tel quel — la
            # résolution vers des handles appartient au réveil, jamais à
            # l'écriture (la personne peut se lier ENTRE les deux).
            row.attend_qui = (verdict.qui or "")[:100]
        elif verdict.etat is EtatVerdict.ILLISIBLE:
            # Compté sur le journal plutôt que dans un champ : le lot ne
            # gagne pas une colonne pour un compteur qu'un seul endroit
            # lit. Trois passes sans verdict lisible et le chantier se
            # bloque — un travail qui ne sait jamais dire où il en est ne
            # peut pas se terminer.
            if row.resultat.count("[verdict illisible]") >= 2:
                row.statut = Travail.Statut.BLOQUEE
                row.raison_blocage = "aucun verdict lisible après trois pas"
            else:
                row.resultat = (row.resultat + "\n[verdict illisible]")[-6000:]

        if row.statut == Travail.Statut.EN_COURS and row.pas_effectues >= row.pas_max:
            row.statut = Travail.Statut.BLOQUEE
            row.raison_blocage = "nombre de pas épuisé"

        # Envie et ancre dans le MÊME `update_fields` : écrire la valeur
        # sans avancer l'ancre re-facturerait le même temps au tour
        # suivant, l'ancre sans la valeur effacerait la décroissance. Les
        # deux moitiés du même geste ne doivent pas pouvoir se séparer —
        # c'est ce qui est arrivé à `Connaissance`, ancrée sur un
        # `auto_now` que Django ne rafraîchit pas sous `update_fields`.
        vue = TravailEnCours(
            identifiant=row.pk, titre=row.titre, envie=row.envie,
            ancre_envie=row.ancre,
        )
        row.envie, row.ancre_envie = facturer_envie(vue, maintenant, t)
        row.save(update_fields=[
            "resultat", "statut", "raison_blocage", "en_attente_de_reponse",
            "reprendre_le", "attend_qui", "envie", "ancre_envie", "updated_at",
        ])

        # Un chantier né d'une pensée et mené au bout résout la pensée.
        # C'est la boucle du regret refermée par l'autre côté : elle
        # n'oublie pas parce que le temps passe, elle oublie parce qu'elle
        # a fait la chose. Bloqué, il l'apaise seulement (divisée par deux) :
        # ne rien faire la laissait entière, au-dessus de la porte des
        # graines — et le même chantier se rouvrait dès que la
        # déduplication cessait de le voir.
        if (
            row.origine == Travail.Origine.PENSEE
            and row.statut in (Travail.Statut.ABOUTIE, Travail.Statut.BLOQUEE)
        ):
            _apaiser_les_pensees(
                [row.reference],
                resoudre=row.statut == Travail.Statut.ABOUTIE,
            )

        if row.statut == Travail.Statut.ABOUTIE:
            return {"issue": "aboutie", "titre": row.titre}
        if row.statut == Travail.Statut.BLOQUEE:
            # Le blocage devient une pensée : « je bloque sur… ». C'est elle
            # qui portera la dérive émotionnelle (frustration → inquiétude),
            # la saignée d'humeur et la digestion nocturne — toute la
            # tuyauterie du regret existe déjà, il suffisait d'y verser
            # l'échec. Écrite dans le même callable synchrone que le statut :
            # les deux sont un seul fait.
            Rumination.objects.create(
                summary=(
                    f"Je bloque sur « {row.titre[:120]} »"
                    + (f" — {row.raison_blocage[:140]}"
                       if row.raison_blocage else "")
                ),
                themes=list(row.themes or []),
                intensity=_FRUSTRATION_TRAVAIL_BLOQUE,
                emotion="frustrated",
                status="active",
            )
            return {"issue": "bloquee", "titre": row.titre}
        return None

    issue = None
    with degraded("conscience: application d'un verdict"):
        issue = await sync_to_async(_ecrire, thread_sensitive=True)()

    if issue and issue.get("issue") == "bloquee":
        # L'échec se ressent, pas seulement l'aboutissement — c'était
        # l'asymétrie centrale du dossier psychologique : un être qui n'a
        # jamais mal à ses échecs ne peut pas en parler vrai.
        with degraded("conscience: frustration du travail bloque"):
            from emotion.types import Emotion, EmotionData

            emotion_engine.process_emotion(
                EmotionData(Emotion.FRUSTRATED, _FRUSTRATION_TRAVAIL_BLOQUE),
                "conscience_mika",
            )
        # Et il entame la valeur propre — petit coup, c'est l'accumulation
        # qui fait l'estime.
        with degraded("conscience: estime apres blocage"):
            await estime.ressentir(
                estime.COUP_TRAVAIL_BLOQUE, "travail bloqué",
            )

    if issue and issue.get("issue") == "aboutie":
        aboutie = issue
        # `verdict.resume` d'abord : c'est la phrase que le bloc demande
        # (« ce que tu viens de faire »). `dit` en repli, borné — le pas
        # entier n'est pas un souvenir, c'est un journal. `getattr` comme
        # `_pending_greeted` : les tests construisent le moteur par
        # `__new__`, donc sans pont mémoire.
        essence = (verdict.resume or dit or "").strip()[:300]
        bridge = getattr(moteur, "memory", None)
        if bridge is not None:
            with degraded("conscience: souvenir d'un travail abouti"):
                await bridge.remember_completed_work(
                    aboutie["titre"], essence,
                )
        # Ressentie, pas seulement mémorisée. Sans cette impulsion, le
        # souvenir disait « proud » pendant que le visage, la voix et
        # l'humeur du quart d'heure suivant n'en savaient rien.
        # `conscience_mika` : c'est elle qui ressent, pas une relation.
        # La résonance de tempérament s'applique naturellement — un
        # fond joyeux amplifie, un fond neutre laisse tel quel.
        with degraded("conscience: fierte du travail abouti"):
            from emotion.types import Emotion, EmotionData

            emotion_engine.process_emotion(
                EmotionData(Emotion.PROUD, _FIERTE_TRAVAIL_ABOUTI),
                "conscience_mika",
            )
        with degraded("conscience: estime apres aboutissement"):
            await estime.ressentir(
                estime.COUP_TRAVAIL_ABOUTI, "travail abouti",
            )


async def _closeness_de(person_id: str) -> str:
    """Le lien que la théorie de l'esprit connaît pour ce handle, ou ``""``.

    Handle → Entity par la couche identité (jamais par égalité de nom), puis
    la fiche. Ne lève jamais : un lien illisible vaut « inconnu », ce qui
    ferme le récit plutôt que de l'ouvrir.
    """
    try:
        from identity.resolver import identity_resolver

        entity = await identity_resolver.entity_for_person(person_id)
        if entity is None:
            return ""

        def _lire() -> str:
            profil = getattr(entity, "profile", None)
            return str(getattr(profil, "closeness", "") or "")

        return await sync_to_async(_lire)()
    except Exception as exc:
        degradations.record("conscience: lien d'un confident", exc)
        return ""


async def _choisir_confident(moteur, titre: str, themes=()) -> dict | None:
    """À qui raconter ce chantier fini — LA personne, ou personne.

    Trois viviers, dans l'esprit de la chaîne du destinataire :

    * les **concernés** — ``who_is_concerned`` sur le titre et les thèmes
      (le « même domaine ») : joignables par définition, différé compris ;
    * les **présents** identifiables (sockets vivants) ;
    * les **owners joignables en différé** (handles module de
      ``OWNER_PERSON_IDS``) — l'administrateur de sa vie est toujours un
      confident possible, même loin du clavier.

    Chaque candidat reçoit son niveau (`recit.niveau_de_recit` : owner,
    closeness, concernement) ; le mieux placé gagne — niveau d'abord, owner
    puis concerné en départage. Aucun appel LLM : on ne délibère pas pour
    savoir à qui on raconterait une bonne nouvelle, on le sait.

    Ne lève jamais ; ``None`` = personne d'assez lié → murmure global.
    """
    from communication.presence import presence_registry
    from conscience.recit import RANG_NIVEAU, NiveauRecit, niveau_de_recit
    from identity.trust import is_identifiable_person
    from modules.collectors import is_owner

    candidats: dict[str, dict] = {}

    def _ajouter(pid: str, channel: str, concerne: bool) -> None:
        if not pid or not is_identifiable_person(pid):
            return
        entree = candidats.setdefault(
            pid, {"person_id": pid, "channel": channel, "concerne": False},
        )
        entree["concerne"] = entree["concerne"] or concerne

    # 1. Les concernés par le sujet — la mémoire désigne le « même domaine ».
    bridge = getattr(moteur, "memory", None)
    if bridge is not None:
        sujet = " ".join([titre, *[str(t) for t in (themes or ())]]).strip()
        try:
            for c in await bridge.who_is_concerned(sujet, n=5):
                handles = c.get("handles") or []
                if handles:
                    _ajouter(handles[0]["person_id"],
                             handles[0].get("channel", ""), concerne=True)
        except Exception as exc:
            degradations.record("conscience: concernes par un travail", exc)

    # 2. Les présents, et les owners joignables en différé. Un handle module
    #    quelconque n'entre PAS (surface de spam) — sauf s'il est owner, ou
    #    déjà désigné par le concernement ci-dessus.
    try:
        for inter in presence_registry.reachable():
            if inter.kind == "consumer" or is_owner(inter.person_id):
                _ajouter(inter.person_id, inter.channel, concerne=False)
    except Exception as exc:
        degradations.record("conscience: presents pour un recit", exc)

    if not candidats:
        return None

    meilleurs: list[tuple[int, int, int, dict]] = []
    for entree in candidats.values():
        owner = is_owner(entree["person_id"])
        niveau = niveau_de_recit(
            est_owner=owner,
            closeness=await _closeness_de(entree["person_id"]),
            concerne=entree["concerne"],
        )
        if niveau is NiveauRecit.RIEN:
            continue
        entree["niveau"] = niveau
        meilleurs.append(
            (RANG_NIVEAU[niveau], int(owner), int(entree["concerne"]), entree)
        )

    if not meilleurs:
        return None
    meilleurs.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)
    return meilleurs[0][3]


async def peut_etre_dire_le_travail(
    moteur, verdict, dit: str, titre: str, themes=(),
) -> None:
    """Un chantier mené au bout mérite-t-il d'être dit ? Par défaut, non.

    Un pas est muet — sans quoi quatre travaux à cinq pas font vingt
    monologues par jour, hors du frein quotidien des initiatives. Mais un
    travail *terminé* et jamais mentionné reste invisible : elle aurait
    passé la journée à faire des choses dont personne n'entend parler.

    `decider_diffusion` porte les gardes — notabilité (auto-évaluée par le
    verdict, absente = 1.0) et un silence minimal entre deux annonces. Ces
    gardes passent AVANT le choix du confident : elles décident *si* on
    raconte, le confident décide *à qui et combien*.

    **Le récit est adressé et gradué quand un lien le permet**
    (`_choisir_confident` + `recit.composer_recit`) : l'owner reçoit tout,
    un proche ou quelqu'un du même domaine l'essentiel, un ami la mention —
    livré à SA personne (`person_id`), donc persona SPEAKING et Telegram
    possible. Personne d'assez lié → le murmure global INNER d'avant, mot
    pour mot : penser tout haut au salon reste une sortie valide.
    """
    from django.utils import timezone as tz

    if verdict.etat is not EtatVerdict.FINI or not dit:
        return

    maintenant = tz.now()
    notable = verdict.notable if verdict.notable is not None else 1.0
    decision = decider_diffusion(
        Conduite.POURSUIVRE,
        resultat_notable=notable,
        derniere_diffusion_le=moteur._derniere_diffusion_travail,
        maintenant=maintenant,
        tuning=conduite_tuning(),
    )
    if not decision.diffuser:
        logger.debug("Travail fini, non diffusé : %s", decision.motif)
        return

    confident = None
    with degraded("conscience: choix d'un confident"):
        confident = await _choisir_confident(moteur, titre, themes)

    texte = dit
    person_id = None
    if confident is not None:
        from conscience.recit import composer_recit

        compose = composer_recit(
            confident["niveau"],
            dit=dit, resume=verdict.resume, titre=titre,
        )
        if compose:
            texte = compose
            person_id = confident["person_id"]
            logger.info(
                "Travail fini raconté à %s (niveau %s)",
                person_id, confident["niveau"].value,
            )

    moteur._derniere_diffusion_travail = maintenant
    with degraded("conscience: diffusion d'un travail fini"):
        from emotion.types import Emotion, EmotionData
        from pipeline.broadcast import broadcast_to_websocket
        from pipeline.processor import SpeechOutput

        await broadcast_to_websocket(
            SpeechOutput(
                text=texte,
                emotion_data=EmotionData(Emotion.PROUD, 0.4),
                emotion_name="proud",
                emotion_intensity=0.4,
                emotion_state={},
                tool_calls=[],
            ),
            source="conscience",
            person_id=person_id,
        )


# ── Redémarrage ───────────────────────────────────────────────────────────


async def reprendre_travaux() -> None:
    """Au démarrage, refermer les pas que l'arrêt a coupés en vol.

    Un pas est marqué **à la prise**, donc un process tué au milieu laisse
    un chantier dont le compteur a monté sans qu'aucun verdict ne soit
    écrit. On ne le rejoue pas : on le laisse simplement redevenir
    éligible. Rendre le crédit ici rouvrirait la boucle de plantage que
    `resume_interrupted_turns` a appris à éviter — un pas qui tue le
    process deux fois doit finir par coûter ses pas, pas les regagner.
    """
    from conscience.models import Travail

    def _passe() -> int:
        coupes = Travail.objects.filter(
            statut=Travail.Statut.EN_COURS,
            pas_effectues__gte=F("pas_max"),
        )
        pensees = list(
            coupes.filter(origine=Travail.Origine.PENSEE)
            .values_list("reference", flat=True)
        )
        n = coupes.update(
            statut=Travail.Statut.BLOQUEE,
            raison_blocage="pas épuisés — interrompu au redémarrage",
        )
        if n and pensees:
            _apaiser_les_pensees(pensees)
        return n

    with degraded("conscience: reprise des travaux"):
        n = await sync_to_async(_passe, thread_sensitive=True)()
        if n:
            logger.info("Reprise: %d chantier(s) clos au redémarrage", n)
