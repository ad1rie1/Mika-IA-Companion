"""La faculté ``social`` : sa tranche, ses paramètres, ses réducteurs, ses faits."""

from __future__ import annotations

import statistics
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict

from mika.contracts import affect as affect_c
from mika.contracts import agency as agency_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import presence as presence_c
from mika.contracts import runtime as rt
from mika.contracts import social as c
from mika.kernel.builtin import BOOT
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.faculty import Faculty
from mika.kernel.forms import Knob
from mika.kernel.state import FrozenDict
from mika.vocab import affect as A
from mika.vocab.affect import Emotion
from mika.vocab.episodes import Kind
from mika.vocab.people import fold, is_identifiable
from mika.vocab.temperament import Temperament, lerp

KEEP_DAYS = 64
#: les liens retenus par personne (les plus récents), et les personnes dont on retient les liens
TIES_KEPT = 32
TIED_PERSONS_KEPT = 512
#: Les dernières conversations dont on retient qui les a ouvertes.
STARTS_KEPT = 20
#: Les initiatives en cours dont on retient la raison (des épisodes qui n'ont jamais parlé s'y oublient).
OPENINGS_KEPT = 16
#: Qui a ouvert une conversation.
HER, THEM = "her", "them"
#: Les connexions vivantes retenues (au-delà, les plus anciennes s'oublient) ; les départs retenus (les plus récents).
LINKS_KEPT = 512
LEFT_KEPT = 512
_RANK = {level: i for i, level in enumerate(c.CLOSENESS_LEVELS)}


class SocialParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # le rythme d'une relation : l'écart médian entre les jours où la personne écrit
    rhythm_window_days: Annotated[int, Knob(
        label="Fenêtre du rythme (jours)", group="Rythme d'une relation", lo=7, hi=365,
        help="Seuls les jours de contact de cette fenêtre servent à mesurer l'écart habituel entre deux jours où "
             "la personne écrit (64 jours de contact distincts au plus sont gardés).")] = 90
    rhythm_min_days: Annotated[float, Knob(
        label="Rythme mesuré minimal (jours)", group="Rythme d'une relation", lo=0.5, hi=14, step=0.5,
        help="Le rythme mesuré n'est jamais plus court : une personne qui écrit tous les jours ne manque pas "
             "au bout de quelques heures.")] = 1.0
    rhythm_max_days: Annotated[float, Knob(
        label="Rythme mesuré maximal (jours)", group="Rythme d'une relation", lo=7, hi=180, step=1,
        help="Le rythme mesuré n'est jamais plus long : au-delà, même une relation espacée finit par lui "
             "manquer.")] = 30.0
    rhythm_min_gaps: Annotated[int, Knob(
        label="Écarts pour mesurer un rythme", group="Rythme d'une relation", lo=1, hi=20,
        help="Combien d'écarts entre jours de contact il faut dans la fenêtre pour mesurer un rythme ; en deçà, "
             "le rythme supposé selon la proximité s'applique.")] = 2
    fallback_close_days: Annotated[float, Knob(
        label="Rythme supposé : proche (jours)", group="Rythme d'une relation", lo=0.5, hi=30, step=0.5,
        help="L'écart habituel prêté à une personne proche tant que son rythme n'est pas mesurable.")] = 3.0
    fallback_friend_days: Annotated[float, Knob(
        label="Rythme supposé : amie (jours)", group="Rythme d'une relation", lo=1, hi=60, step=0.5,
        help="L'écart habituel prêté à une amie tant que son rythme n'est pas mesurable.")] = 7.0
    fallback_other_days: Annotated[float, Knob(
        label="Rythme supposé : les autres (jours)", group="Rythme d'une relation", lo=1, hi=90, step=0.5,
        help="Celui prêté à une connaissance ou une inconnue. Il ne change que la lecture (fiche, silence ÷ "
             "rythme) : elle ne relance que ses amies et ses proches.")] = 14.0
    # la proximité naît de l'histoire vécue (jours distincts, messages reçus) et
    # de ce qu'elle a installé (le regard d'``affect`` : jamais amie d'une rancune)
    # s'être parlé deux jours différents…
    acquaintance_days: Annotated[int, Knob(
        label="Connaissance : jours de contact", group="Proximité vécue", lo=1, hi=30,
        help="S'être parlé tant de jours différents fait d'une inconnue une connaissance (ou assez de messages, "
             "ci-dessous).")] = 2
    # … ou longuement : dix minutes d'insultes ne font pas une connaissance
    acquaintance_messages: Annotated[int, Knob(
        label="Connaissance : messages reçus", group="Proximité vécue", lo=1, hi=500,
        help="… ou avoir reçu tant de messages d'elle, même en un seul jour.")] = 20
    friend_days: Annotated[int, Knob(
        label="Amie : jours de contact", group="Proximité vécue", lo=1, hi=60,
        help="Jours de contact distincts pour devenir amie (avec assez de messages, et sans rancune).")] = 3
    friend_messages: Annotated[int, Knob(
        label="Amie : messages reçus", group="Proximité vécue", lo=1, hi=1000,
        help="Messages reçus pour devenir amie (avec assez de jours de contact, et sans rancune).")] = 15
    close_days: Annotated[int, Knob(
        label="Proche : jours de contact", group="Proximité vécue", lo=1, hi=120,
        help="Jours de contact distincts pour devenir proche (avec assez de messages, sans rancune, de la "
             "chaleur installée ou de l'attachement — moins d'attachement pour une longue histoire —, et un mois "
             "d'histoire vécue au moins).")] = 7
    close_messages: Annotated[int, Knob(
        label="Proche : messages reçus", group="Proximité vécue", lo=1, hi=2000,
        help="Messages reçus pour devenir proche.")] = 50
    #: proche : de la chaleur installée, un attachement — jamais la seule assiduité (ADR 0058)
    close_regard: Annotated[float, Knob(
        label="Proche : chaleur installée", group="Proximité vécue", lo=0, hi=1, step=0.01,
        help="Le regard installé (affect : 0 au repos, 1 chaleur pleine) qu'il faut pour devenir proche — "
             "ou l'attachement ci-dessous. Des soirées chaleureuses ordinaires l'installent (de l'ordre de 0,25 en "
             "un mois) ; des échanges sans chaleur, non.")] = 0.1
    close_bond: Annotated[float, Knob(
        label="Proche : attachement", group="Proximité vécue", lo=0, hi=1, step=0.01,
        help="L'attachement (affect : nourri par ses déclarations chaleureuses ou tendres, lent, demi-vie de deux "
             "mois) qui suffit, à lui seul, pour être proche : une mauvaise passe qui assombrit le regard du moment "
             "n'éloigne pas quelqu'un à qui elle tient. Le mois d'histoire reste exigé.")] = 0.15
    #: la personne qui l'a installée : au moins ce niveau d'office (jamais « proche » : ça se vit)
    owner_floor: Annotated[str, Knob(
        label="Propriétaire : au moins", group="Proximité vécue",
        choices=((c.STRANGER, "comme tout le monde"), (c.ACQUAINTANCE, "connaissance"), (c.FRIEND, "amitié")),
        help="Sa propriétaire reconnue a d'office au moins ce niveau de proximité — dès l'amitié, son message de "
             "nuit la réveille (corps). Jamais « proche » d'office : ça se vit. Une proximité fixée par un "
             "opérateur l'emporte ; une rancune lourde lève ce plancher, comme elle défait une amitié.")] = c.FRIEND
    close_long_days: Annotated[int, Knob(
        label="Proche : longue histoire (jours)", group="Proximité vécue", lo=1, hi=365,
        help="Au-delà de tant de jours de contact, un attachement plus modeste (ci-dessous) suffit pour être "
             "proche : le temps approfondit ce qui est là, il ne le crée pas — l'assiduité seule, sans chaleur ni "
             "attachement, ne fait pas une intimité.")] = 60
    close_long_bond: Annotated[float, Knob(
        label="Proche : attachement d'une longue histoire", group="Proximité vécue", lo=0, hi=1, step=0.01,
        help="L'attachement (affect) qui suffit, avec une longue histoire, pour être proche. Une politesse sans "
             "chaleur, des mois durant, reste une amitié ; même réglé à zéro, il faut un attachement.")] = 0.08
    close_history_days: Annotated[int, Knob(
        label="Proche : histoire d'au moins (jours)", group="Proximité vécue", lo=1, hi=365,
        help="Entre leur premier et leur dernier jour de contact, il faut au moins tant de jours pour être "
             "proche : on ne le devient pas en une semaine, si intense soit-elle — ni pendant une absence (le "
             "temps vécu ensemble, pas le calendrier).")] = 30
    closeness_window_days: Annotated[int, Knob(
        label="Proximité : fenêtre glissante (jours)", group="Proximité vécue", lo=14, hi=730,
        help="La proximité se lit sur les jours de contact de cette fenêtre ; l'histoire plus ancienne ne la "
             "fait pas tomber plus d'un cran sous ce qu'elle a été — sauf une histoire courte que son silence a "
             "dépassée (ci-dessous).")] = 120
    closeness_silence_factor: Annotated[float, Knob(
        label="Proximité : long silence (× rythme)", group="Proximité vécue", lo=2, hi=50, step=0.5,
        help="Un silence d'au moins tant de fois son rythme (et d'au moins le minimum ci-dessous) fait "
             "descendre la proximité d'un cran — l'histoire la retient un cran sous ce qu'elle a été.")] = 8.0
    lasting_days: Annotated[int, Knob(
        label="Une longue amitié : jours de contact", group="Proximité vécue", lo=7, hi=365,
        help="Une proche d'au moins tant de jours de contact garde, quel que soit le silence, un plancher : amie. "
             "Une histoire plus courte, quand son silence a duré plus que toute leur histoire, redevient une "
             "connaissance — comme une amitié de trois semaines suivie de mois sans nouvelles.")] = 45
    closeness_silence_min_days: Annotated[int, Knob(
        label="Proximité : long silence d'au moins (jours)", group="Proximité vécue", lo=3, hi=365,
        help="En deçà, aucun silence ne fait descendre la proximité, quel que soit le rythme.")] = 21
    # reprendre contact : un silence d'une fois et demie son rythme
    recontact_factor: Annotated[float, Knob(
        label="Manque : silence ÷ rythme", group="Reprendre contact", lo=1, hi=10, step=0.1,
        help="Une amie ou un proche lui manque quand son silence dépasse tant de fois son rythme habituel : elle "
             "a envie de reprendre des nouvelles, et le manque nourrit ses pensées.")] = 1.5
    recontact_evidence: Annotated[float, Knob(
        label="Preuve d'une relance", group="Reprendre contact", lo=0, hi=12, step=0.5,
        help="Preuve d'initiative (log-odds) d'un manque. Au-dessus du seuil d'initiative (9 par défaut), une "
             "relance part seule ; plafonnée à 12 par l'arbitrage.")] = 10.5
    # longtemps après : une amie partie sans plus répondre, elle reprend de ses nouvelles une fois (ADR 0058)
    rekindle_after_us: Annotated[int, Knob(
        label="Longtemps après : un silence d'au moins", group="Reprendre des nouvelles, longtemps après",
        lo=14 * DAY, hi=365 * DAY,
        help="Une amie (ou quelqu'un qui l'a été) qui ne répond plus : passé ce silence, des deux côtés, elle peut "
             "prendre de ses nouvelles une fois, doucement — même après deux messages restés sans réponse. Pas "
             "de nouvelle tentative tant que la personne n'a pas écrit.")] = 90 * DAY
    rekindle_rhythms: Annotated[float, Knob(
        label="Longtemps après : au moins tant de fois son rythme", group="Reprendre des nouvelles, longtemps après",
        lo=2, hi=50, step=0.5,
        help="… et au moins ce multiple du rythme de la relation (une amie mensuelle n'est pas « longtemps » "
             "silencieuse au bout de trois mois).")] = 6.0
    rekindle_announced_us: Annotated[int, Knob(
        label="Après une date qu'elle avait annoncée", group="Reprendre des nouvelles, longtemps après",
        lo=HOUR, hi=14 * DAY,
        help="Si la personne lui avait annoncé un moment (un départ, un retour, un examen) qui est passé pendant son "
             "silence, elle peut en prendre des nouvelles dès ce délai après — sans attendre des mois.")] = DAY
    rekindle_min_us: Annotated[int, Knob(
        label="Après une date annoncée : pas avant", group="Reprendre des nouvelles, longtemps après",
        lo=3 * DAY, hi=90 * DAY,
        help="… mais jamais moins de ce silence depuis leur dernier échange : ce n'est pas une relance.")] \
        = 14 * DAY
    rekindle_evidence: Annotated[float, Knob(
        label="Preuve de cette prise de nouvelles", group="Reprendre des nouvelles, longtemps après",
        lo=0, hi=12, step=0.5,
        help="Preuve d'initiative (log-odds). Au-dessus du seuil (9), elle le fait dans la journée ; plafonnée à "
             "12 par l'arbitrage.")] = 10.0
    # se connaître : qui a un lien avec qui (ADR 0058)
    tie_room_max: Annotated[int, Knob(
        label="Se connaître : une conversation d'au plus", group="Qui se connaît", lo=2, hi=50,
        help="Deux personnes qui étaient ensemble dans une conversation d'au plus tant de personnes se connaissent "
             "(un lien) ; au-delà, un grand salon ne fait pas des proches qui se connaissent. Une personne qui en "
             "nomme une autre lui crée aussi un lien — jamais celle qui prononce seulement un nom.")] = 6
    # chercher du réconfort : une humeur nettement sombre
    comfort_evidence: Annotated[float, Knob(
        label="Preuve d'une recherche de réconfort", group="Réconfort", lo=0, hi=12, step=0.5,
        help="Preuve d'initiative (log-odds) pour écrire, quand elle va mal, à la personne auprès de qui elle se "
             "sent le mieux ; plafonnée à 12 par l'arbitrage.")] = 10.0
    distress_valence: Annotated[float, Knob(
        label="Détresse : valence au plus", group="Réconfort", lo=-1, hi=0, step=0.05,
        help="Elle cherche du réconfort quand la valence de son humeur ressentie tombe à ce niveau ou "
             "plus bas (et que l'intensité suit).")] = -0.35
    distress_intensity: Annotated[float, Knob(
        label="Détresse : intensité au moins", group="Réconfort", lo=0, hi=1, step=0.05,
        help="L'intensité ressentie qu'il faut, avec la valence ci-dessus, pour parler de détresse.")] = 0.5
    comfort_spacing_us: Annotated[int, Knob(
        label="Espacement du réconfort", group="Réconfort", lo=30 * MINUTE, hi=3 * DAY,
        help="Pas deux recherches de réconfort plus rapprochées, ni vers quelqu'un à qui elle a écrit "
             "depuis moins longtemps : on va vers une personne, pas vers toutes à la suite.")] = 6 * HOUR
    # l'envie de discuter : une amie ou un proche joignable, plus silencieuse que d'habitude
    chat_after_us: Annotated[int, Knob(
        label="Envie de discuter : silence minimal", group="Envie de discuter", lo=30 * MINUTE, hi=3 * DAY,
        help="Il faut au moins ce silence (dans un sens comme dans l'autre) avec une amie ou un proche pour "
             "avoir envie de lui écrire sans raison particulière.")] = 4 * HOUR
    chat_ratio: Annotated[float, Knob(
        label="Envie de discuter : silence ÷ rythme", group="Envie de discuter", lo=0, hi=10, step=0.1,
        help="… et un silence d'au moins tant de fois son rythme habituel (au-delà du seuil de manque, c'est "
             "une relance).")] = 1.0
    chat_friend: Annotated[float, Knob(
        label="Envie de discuter : preuve (amie)", group="Envie de discuter", lo=0, hi=3.5, step=0.1,
        help="Preuve d'initiative (log-odds) de l'envie de discuter avec une amie : peu de chose seule, assez "
             "quand le besoin de compagnie s'y ajoute. Plafonnée à 3,5 chaleur comprise.")] = 1.5
    chat_close: Annotated[float, Knob(
        label="Envie de discuter : preuve (proche)", group="Envie de discuter", lo=0, hi=3.5, step=0.1,
        help="La même preuve envers un proche. Plafonnée à 3,5 chaleur comprise.")] = 2.5
    chat_warmth: Annotated[float, Knob(
        label="Envie de discuter : poids de la chaleur", group="Envie de discuter", lo=0, hi=3.5, step=0.1,
        help="S'ajoute à la preuve, multiplié par la chaleur installée envers la personne (0 à 1).")] = 1.0
    # ses heures pour écrire d'elle-même à quelqu'un d'absent (heure locale, minutes)
    day_start_min: Annotated[int, Knob(
        label="Écrire d'elle-même : à partir de", group="Heures d'initiative", lo=0, hi=24 * 60,
        help="Heure locale (10 h = 10:00) à partir de laquelle elle relance, cherche du réconfort ou écrit "
             "pour discuter. Les salutations n'en dépendent pas.")] = 10 * 60
    day_end_min: Annotated[int, Knob(
        label="Écrire d'elle-même : jusqu'à", group="Heures d'initiative", lo=0, hi=24 * 60,
        help="Heure locale après laquelle elle ne le fait plus. Avant le début, la plage passe minuit (un "
             "tempérament nocturne : de 18 h à 1 h).")] = 20 * 60 + 30
    # une rancune (hostilité installée) : ni initiative vers elle, ni amitié naissante
    grudge: Annotated[float, Knob(
        label="Seuil de rancune", group="Retenue", lo=0.05, hi=1, step=0.05,
        help="À partir de cette hostilité installée (affect), aucune initiative ordinaire vers la personne — pas "
             "même une salutation. Plus bas : la moindre contrariété coupe les ponts.")] = 0.2
    grudge_inform_shift: Annotated[float, Knob(
        label="Prévenir malgré une rancune", group="Retenue", lo=-6, hi=0, step=0.5,
        help="Une rancune n'arrête ni ce qui est dû (un rappel promis part à l'heure, tel quel) ni ce qui prévient "
             "(un mail important, un projet confié qui n'avance plus sans la personne) : elle ne fait que décaler "
             "l'annonce d'autant (log-odds) — elle prévient, sans se presser.")] = -2.0
    # saluer : une arrivée, pas une reconnexion
    away_us: Annotated[int, Knob(
        label="Une arrivée après une absence d'au moins", group="Saluer", lo=5 * MINUTE, hi=12 * HOUR,
        help="Une connexion n'est une arrivée (qu'elle salue) qu'après une absence d'au moins cette durée : un "
             "onglet rechargé, une connexion coupée quelques minutes, un redémarrage d'elle (qui était là y est "
             "compté parti à l'instant où elle revient) ne font pas revenir quelqu'un qui n'était pas parti.")] \
        = HOUR
    grudge_demote: Annotated[float, Knob(
        label="Rancune qui défait une amitié installée", group="Retenue", lo=0.05, hi=1, step=0.05,
        help="Une amitié installée (ci-dessous) n'est rétrogradée pour rancune qu'à partir de cette hostilité : "
             "une dispute n'efface pas un mois d'amitié. Une amitié naissante, elle, ne passe pas le seuil de "
             "rancune ordinaire.")] = 0.35
    friendship_settled_days: Annotated[int, Knob(
        label="Une amitié est installée après (jours de contact)", group="Retenue", lo=1, hi=120,
        help="Au-delà de tant de jours de contact distincts, l'amitié est installée : seule une rancune plus "
             "lourde la défait.")] = 7
    # qui ouvre leurs conversations : quand c'est presque toujours elle, elle le remarque
    conversation_gap_us: Annotated[int, Knob(
        label="Une nouvelle conversation après", group="Réciprocité", lo=10 * MINUTE, hi=2 * DAY,
        help="Un silence d'au moins tant sépare deux conversations : qui écrit après lui ouvre la suivante "
             "(une réponse à sa relance n'en ouvre pas).")] = 2 * HOUR
    reciprocity_min_starts: Annotated[int, Knob(
        label="Réciprocité : conversations comptées au moins", group="Réciprocité", lo=2, hi=20,
        help="En deçà de tant de conversations ouvertes (par l'une ou l'autre), elle ne juge pas qui écrit en "
             "premier.")] = 5
    one_sided_share: Annotated[float, Knob(
        label="C'est presque toujours elle : part au moins", group="Réciprocité", lo=0.5, hi=1, step=0.05,
        help="Quand elle a ouvert au moins cette part de leurs dernières conversations, elle le remarque : ses "
             "envies de relancer ou de discuter s'espacent, et une pensée lui reste.")] = 0.7
    one_sided_shift: Annotated[float, Knob(
        label="Relances quand c'est toujours elle", group="Réciprocité", lo=-10, hi=0, step=0.5,
        help="Ses relances, envies de discuter et pensées qui insistent vers cette personne deviennent moins "
             "probables d'autant (log-odds).")] = -2.0
    one_sided_spacing_us: Annotated[int, Knob(
        label="Le remarquer au plus une fois par", group="Réciprocité", lo=DAY, hi=60 * DAY,
        help="Elle ne s'en fait pas la remarque plus souvent.")] = 7 * DAY
    # profils : relus quand assez de nouveau est su, au plus une fois par jour
    profile_min_items: Annotated[int, Knob(
        label="Fiche : éléments nouveaux", group="Fiches", lo=1, hi=50,
        help="Sa fiche d'une personne n'est relue (appel au modèle) qu'après tant de souvenirs ou croyances "
             "nouveaux la concernant.")] = 3
    profile_interval_us: Annotated[int, Knob(
        label="Fiche : intervalle minimal", group="Fiches", lo=HOUR, hi=30 * DAY,
        help="Pas deux relectures de la même fiche plus rapprochées.")] = DAY
    profile_max_items: Annotated[int, Knob(
        label="Fiche : éléments relus", group="Fiches", lo=5, hi=200,
        help="Combien de ses souvenirs et croyances sur la personne (les plus importants) le modèle relit — "
             "seulement ce que la personne a dit elle-même, ou ce qu'elles ont vécu ensemble.")] = 30
    profile_per_run: Annotated[int, Knob(
        label="Fiches par passage", group="Fiches", lo=1, hi=10,
        help="Combien de fiches au plus une passe relit (les plus en retard d'abord) : les appels restent "
             "rares.")] = 2
    profile_retry_us: Annotated[int, Knob(
        label="Fiche : délai entre passes", group="Fiches", lo=MINUTE, hi=DAY,
        help="Délai avant la passe suivante quand d'autres fiches attendent ou qu'un appel a échoué : pas de "
             "rafale d'appels au modèle.")] = 30 * MINUTE


@dataclass(frozen=True, slots=True)
class Contact:
    days: tuple[int, ...] = ()  # jours locaux (ordinaux) où la personne a écrit
    inbound: int = 0
    first_in: int = 0
    last_in: int = 0
    last_out: int = 0
    unanswered: int = 0  # ses initiatives depuis le dernier message de la personne
    #: messages reçus chacun de ces jours (en parallèle de ``days``)
    counts: tuple[int, ...] = ()
    #: jours de contact distincts depuis le début (``days`` n'en garde que les derniers), et le premier
    total_days: int = 0
    first_day: int = 0
    #: le dernier échange (dans un sens ou dans l'autre) ; le début de la conversation en cours ;
    #: et le dernier message de la personne avant elle
    last_activity: int = 0
    since: int = 0
    previous: int = 0
    #: qui a ouvert leurs dernières conversations : ``(jour, HER | THEM)``
    starts: tuple[tuple[int, str], ...] = ()


@dataclass(frozen=True, slots=True)
class Profile:
    summary_ref: str
    tone: str = ""  # en clair, profil d'avant la version 2
    interests: tuple[str, ...] = ()
    sensitive: tuple[str, ...] = ()
    revised_at: int = 0
    upto: int = 0
    mentions_at: int = 0  # combien d'éléments de mémoire la concernaient à la relecture
    #: les contenus, gardés à part (vides : aucun, ou profil d'avant la version 2)
    tone_ref: str = ""
    interests_ref: str = ""
    sensitive_ref: str = ""


@dataclass(frozen=True, slots=True)
class SocialState:
    greeted: FrozenDict[str, int] = field(default_factory=FrozenDict)
    contacts: FrozenDict[str, Contact] = field(default_factory=FrozenDict)
    profiles: FrozenDict[str, Profile] = field(default_factory=FrozenDict)
    declared: FrozenDict[str, str] = field(default_factory=FrozenDict)  # proximité déclarée par un opérateur
    mentions: FrozenDict[str, int] = field(default_factory=FrozenDict)  # éléments de mémoire la concernant
    comforted_at: int = 0  # la dernière fois qu'elle est allée chercher du réconfort
    #: ses initiatives en cours : corrélation → raisons (une salutation n'ouvre pas une conversation à elle seule)
    openings: FrozenDict[str, str] = field(default_factory=FrozenDict)
    #: quand elle a remarqué, pour la dernière fois, que c'est toujours elle qui écrit à cette personne
    noticed: FrozenDict[str, int] = field(default_factory=FrozenDict)
    #: les connexions vivantes qu'elle a vues passer (connexion → adresse) : la présence, elle, ne survit pas à un
    #: redémarrage ; il faut savoir qui était là quand elle s'est arrêtée
    links: FrozenDict[str, str] = field(default_factory=FrozenDict)
    #: quand chaque adresse a quitté ses écrans pour la dernière fois (sa dernière connexion fermée) ; à un
    #: redémarrage, qui était là y est compté parti à l'instant où elle revient — ce n'est pas lui qui est parti
    left: FrozenDict[str, int] = field(default_factory=FrozenDict)
    #: qui a un lien avec qui : personne → {personne avec qui elle a un lien → la dernière fois que ça s'est vu}.
    #: Ils étaient ensemble dans une petite conversation, ou la seconde a nommé la première (ADR 0058)
    ties: FrozenDict[str, FrozenDict[str, int]] = field(default_factory=FrozenDict)
    #: quand elle a repris des nouvelles de quelqu'un, longtemps après (une fois par silence)
    rekindled: FrozenDict[str, int] = field(default_factory=FrozenDict)
    #: le dernier cran de chaque lien qu'elle a ressenti ou tenu pour acquis, et quand : personne → (niveau, instant)
    felt_levels: FrozenDict[str, tuple[str, int]] = field(default_factory=FrozenDict)
    #: quand elle a relevé ses liens pour la première fois (0 : jamais — le premier passage les relève sans les vivre)
    bonds_since: int = 0


def derive(t: Temperament, overrides: Any = None) -> SocialParams:
    """L'optimisme recule le seuil de la détresse : une optimiste tient plus
    longtemps avant d'aller chercher du réconfort (au milieu : −0,35, la valeur
    d'avant). Les surcharges sont posées par ``runtime/params.py``."""
    values: dict[str, Any] = {"distress_valence": round(lerp(-0.2, -0.5, t.optimism), 3)}
    values.update(dict(overrides or {}))
    return SocialParams(**values)


#: v2 : messages par jour, histoire totale, conversations ouvertes, contenus des profils à part.
#: ``ignored_shift`` est retiré : ne pas harceler quelqu'un qui ne répond pas est la retenue d'``agency``
#: (ADR 0033) ; d'anciens réglages qui le portent se relisent sans lui.
#: v3 : qui était là, et quand chacun est parti (une reconnexion, un redémarrage d'elle ne sont pas des arrivées).
#: v4 : qui a un lien avec qui, et les prises de nouvelles longtemps après (ADR 0058).
#: v5 : une ouverture qui ne regarde que la personne (``agency.FOR_THEM`` : s'inquiéter d'elle, lui souhaiter, lui
#: demander comment ça s'est passé) n'est plus comptée comme « elle a écrit la première » — ``starts`` se recalcule.
#: v6 : le dernier cran ressenti de chaque lien (``bond_shifted``, ``bond_noted``).
SOCIAL = Faculty("social", state=SocialState, init=lambda p: SocialState(), params=SocialParams, derive=derive,
                 state_version=6, retired_params=("ignored_shift",))
SOCIAL.declare(*c.ALL)


def params(p: SocialParams | None) -> SocialParams:
    return p if p is not None else SocialParams()


# ── Réducteurs ────────────────────────────────────────────────────────────


@SOCIAL.reducer(rt.EPISODE_STARTED, reads=[identity_c.PERSON])
def _started(s: SocialState, e, cx) -> SocialState:
    d = e.data
    reasons = d.reason.split(",")
    if d.kind != Kind.INITIATIVE or not d.target:
        return s
    openings = s.openings.set(e.correlation, d.reason)
    if len(openings) > OPENINGS_KEPT:  # les identifiants d'épisode sont chronologiques
        openings = FrozenDict(sorted(openings.items())[-OPENINGS_KEPT:])
    s = replace(s, openings=openings)
    if c.COMFORT in reasons:
        s = replace(s, comforted_at=e.at)  # on va vers une personne, pas vers toutes à la suite
    if c.GREETING in reasons:
        s = replace(s, greeted=s.greeted.set(cx.facts.get(identity_c.PERSON(d.target)), e.at))
    return s


def _active(ct: Contact, at: int, gap: int) -> tuple[Contact, bool]:
    """Un échange de plus : après un long silence, il ouvre une nouvelle
    conversation, et l'on retient quand la personne avait écrit pour la
    dernière fois avant elle. Rend aussi si cet échange en ouvre une."""
    opens = not ct.last_activity or at - ct.last_activity >= gap
    if not opens:
        return replace(ct, last_activity=max(ct.last_activity, at)), False
    return replace(ct, last_activity=max(ct.last_activity, at), previous=ct.last_in, since=at), True


def _opened(ct: Contact, day: int, who: str) -> Contact:
    if (day, who) in ct.starts:
        return ct  # un jour compte une fois, de chaque côté
    return replace(ct, starts=(*ct.starts, (day, who))[-STARTS_KEPT:])


#: Des raisons sans preuve, qui ne portent qu'une garde (la personne est là, elle peut se raviser) : ce ne sont pas
#: des raisons de lui écrire.
_CARRIERS = frozenset({c.PRESENT_PERSON, agency_c.SECOND_THOUGHTS})


def _for_them(reasons: Any) -> bool:
    """Une initiative qui ne regarde que la personne (``agency.FOR_THEM``) : s'inquiéter d'elle, l'encourager, lui
    souhaiter son anniversaire, lui demander comment ça s'est passé. On ne tient pas ses comptes quand on prend soin
    de quelqu'un : elle n'entre pas dans « qui écrit la première »."""
    motives = set(reasons) - _CARRIERS - {""}
    return bool(motives) and motives <= agency_c.FOR_THEM


@SOCIAL.reducer(rt.PERCEPTION_RECEIVED, reads=[identity_c.PERSON])
def _received(s: SocialState, e, cx) -> SocialState:
    d = e.data
    if not d.addressed or not is_identifiable(d.handle):
        return s  # entendu dans un groupe sans lui être adressé : ce n'est pas un contact
    p = params(cx.params)
    person = cx.facts.get(identity_c.PERSON(d.handle))
    ct = s.contacts.get(person) or Contact()
    day = cx.local(e.at).date().toordinal()
    if ct.days and ct.days[-1] == day:
        days, counts, total = ct.days, (*ct.counts[:-1], (ct.counts[-1] if ct.counts else 0) + 1), ct.total_days
    else:
        days, counts = (*ct.days, day)[-KEEP_DAYS:], (*ct.counts, 1)[-KEEP_DAYS:]
        total = max(ct.total_days, len(ct.days)) + 1
    answering = ct.unanswered > 0
    ct, opens = _active(ct, e.at, p.conversation_gap_us)
    if opens and not answering:
        ct = _opened(ct, day, THEM)  # elle (ou il) a écrit la première, sans répondre à une relance
    ct = replace(ct, days=days, counts=counts, total_days=total, first_day=ct.first_day or day,
                 inbound=ct.inbound + 1, first_in=ct.first_in or e.at, last_in=e.at, unanswered=0)
    return replace(s, contacts=s.contacts.set(person, ct))


@SOCIAL.reducer(rt.UTTERANCE, reads=[identity_c.PERSON])
def _uttered(s: SocialState, e, cx) -> SocialState:
    d = e.data
    reasons = s.openings.get(e.correlation, "").split(",")
    if e.correlation in s.openings:
        s = replace(s, openings=s.openings.delete(e.correlation))
    if not d.visible or not d.target or not is_identifiable(d.target):
        return s
    p = params(cx.params)
    person = cx.facts.get(identity_c.PERSON(d.target))
    ct = s.contacts.get(person) or Contact()
    # saluer, tenir parole : ni ouvrir une conversation, ni attendre une réponse (ce n'était pas une question)
    speaking_up = d.kind == Kind.INITIATIVE and not agency_c.NOT_SPEAKING_UP & set(reasons)
    initiative = d.kind == Kind.INITIATIVE
    ct, opens = _active(ct, e.at, p.conversation_gap_us)
    if speaking_up and opens and not _for_them(reasons):
        # c'est elle qui écrit la première — sauf pour prendre soin de la personne, qui ne se compte pas
        ct = _opened(ct, cx.local(e.at).date().toordinal(), HER)
    ct = replace(ct, last_out=e.at, unanswered=ct.unanswered + (1 if speaking_up else 0))
    if initiative and c.REKINDLE in reasons:
        s = replace(s, rekindled=s.rekindled.set(person, e.at))  # une fois par silence
    return replace(s, contacts=s.contacts.set(person, ct))


def _kept_left(left: FrozenDict[str, int]) -> FrozenDict[str, int]:
    if len(left) <= LEFT_KEPT:
        return left
    return FrozenDict(sorted(left.items(), key=lambda kv: (kv[1], kv[0]))[-LEFT_KEPT:])


@SOCIAL.reducer(presence_c.CONNECTED)
def _connected(s: SocialState, e, cx) -> SocialState:
    links = s.links.set(e.data.connection, e.data.handle)
    if len(links) > LINKS_KEPT:  # des connexions jamais fermées (un transport qui ne le dit pas) : on les oublie
        links = FrozenDict(sorted(links.items())[-LINKS_KEPT:])
    return replace(s, links=links)


@SOCIAL.reducer(presence_c.DISCONNECTED)
def _disconnected(s: SocialState, e, cx) -> SocialState:
    """Une connexion se ferme : quand c'était la dernière de l'adresse, elle est partie à cet instant."""
    handle = s.links.get(e.data.connection)
    if handle is None:
        return s
    links = s.links.delete(e.data.connection)
    if handle in links.values():
        return replace(s, links=links)  # encore là par un autre écran
    return replace(s, links=links, left=_kept_left(s.left.set(handle, e.at)))


@SOCIAL.reducer(BOOT)
def _rebooted(s: SocialState, e, cx) -> SocialState:
    """Elle redémarre : les connexions d'avant sont tombées avec elle (sans un mot, si elle s'est arrêtée
    brutalement). Qui était là ne l'a pas quittée : il est compté parti à l'instant où elle revient, si bien que
    son écran qui se reconnecte n'est pas une arrivée."""
    if not s.links:
        return s
    left = s.left
    for handle in sorted(set(s.links.values())):
        left = left.set(handle, e.at)
    return replace(s, links=FrozenDict(), left=_kept_left(left))


@SOCIAL.reducer(memory_c.REMEMBERED, memory_c.BELIEVED)
def _mentioned(s: SocialState, e, cx) -> SocialState:
    mentions = s.mentions
    for person in e.data.about:
        mentions = mentions.set(person, mentions.get(person, 0) + 1)
    return replace(s, mentions=mentions)


#: une personne nommée avec hostilité (« Bruno m'a trahie ») n'est pas pour autant de son entourage
_HOSTILE = frozenset({Emotion.ANGRY, Emotion.DISGUSTED, Emotion.FRUSTRATED, Emotion.JEALOUS})


def _tie(ties: FrozenDict[str, FrozenDict[str, int]], person: str, other: str,
         at: int) -> FrozenDict[str, FrozenDict[str, int]]:
    mine = (ties.get(person) or FrozenDict()).set(other, at)
    if len(mine) > TIES_KEPT:
        mine = FrozenDict(sorted(mine.items(), key=lambda kv: (kv[1], kv[0]))[-TIES_KEPT:])
    ties = ties.set(person, mine)
    if len(ties) > TIED_PERSONS_KEPT:  # les liens vus le moins récemment s'oublient
        ties = FrozenDict(sorted(ties.items(), key=lambda kv: (max(kv[1].values()), kv[0]))[-TIED_PERSONS_KEPT:])
    return ties


@SOCIAL.reducer(memory_c.REMEMBERED, memory_c.BELIEVED, memory_c.EVENT_NOTED, memory_c.REINFORCED,
                reads=[identity_c.PERSON])
def _knit(s: SocialState, e, cx) -> SocialState:
    """Qui a un lien avec qui, d'après ce qu'elle retient (ADR 0058) : deux personnes qui étaient ensemble dans
    une petite conversation (``heard_by``) se connaissent ; une personne qui en nomme une autre en lui racontant sa
    vie (``told_by`` → ``about``) la compte dans son entourage — l'autre a un lien avec elle. L'inverse, jamais :
    prononcer le nom de quelqu'un ne crée aucun lien avec lui. Nommée avec colère ou dégoût, non plus."""
    d = e.data
    p = params(cx.params)

    def persons(keys: Any) -> set[str]:
        return {cx.facts.get(identity_c.PERSON(k)) or k for k in keys
                if is_identifiable(k) and not k.startswith("name:")}

    pairs: set[tuple[str, str]] = set()
    hostile = A.emotion_of(getattr(d, "emotion", None)) in _HOSTILE
    if not hostile:
        about = persons(d.about)
        pairs |= {(named, teller) for teller in persons(d.told_by) for named in about if named != teller}
    heard = persons(d.heard_by)
    if 2 <= len(heard) <= p.tie_room_max:
        pairs |= {(a, b) for a in heard for b in heard if a != b}
    if not pairs:
        return s
    ties = s.ties
    for person, other in sorted(pairs):
        ties = _tie(ties, person, other, e.at)
    return replace(s, ties=ties)


@SOCIAL.reducer(c.PROFILE_REVISED)
def _profiled(s: SocialState, e, cx) -> SocialState:
    d = e.data
    profile = Profile(summary_ref=d.summary.ref or "", tone=d.legacy_tone, interests=tuple(d.legacy_interests),
                      sensitive=tuple(d.legacy_sensitive), revised_at=e.at, upto=d.upto,
                      mentions_at=s.mentions.get(d.person, 0), tone_ref=d.tone.ref or "" if d.tone else "",
                      interests_ref=d.interests.ref or "" if d.interests else "",
                      sensitive_ref=d.sensitive.ref or "" if d.sensitive else "")
    return replace(s, profiles=s.profiles.set(d.person, profile))


@SOCIAL.reducer(c.CLOSENESS_SET)
def _declared(s: SocialState, e, cx) -> SocialState:
    d = e.data
    if d.closeness not in c.CLOSENESS_LEVELS:
        return replace(s, declared=s.declared.delete(d.person))
    return replace(s, declared=s.declared.set(d.person, d.closeness))


@SOCIAL.reducer(c.ONE_SIDED)
def _noticed(s: SocialState, e, cx) -> SocialState:
    about = e.data.about
    return replace(s, noticed=s.noticed.set(about[0], e.at)) if about else s


def _felt(s: SocialState, person: str, level: str, at: int) -> SocialState:
    s = replace(s, bonds_since=s.bonds_since or at)
    if not person or level not in c.CLOSENESS_LEVELS:
        return s
    return replace(s, felt_levels=s.felt_levels.set(person, (level, at)))


@SOCIAL.reducer(c.BOND_SHIFTED)
def _shifted(s: SocialState, e, cx) -> SocialState:
    """Un lien qui a changé de cran, remarqué : c'est ce cran qu'elle ressent désormais."""
    return _felt(s, e.data.person, e.data.after, e.at)


@SOCIAL.reducer(c.BOND_NOTED)
def _bond_noted(s: SocialState, e, cx) -> SocialState:
    """Un cran tenu pour acquis sans le vivre (la mise en service, une proximité fixée, le plancher d'une
    propriétaire) : c'est de lui que se mesurera le prochain changement."""
    return _felt(s, e.data.person, e.data.level, e.at)


# ── Lectures ──────────────────────────────────────────────────────────────


def grudging(hostility: float, p: SocialParams) -> bool:
    """Une rancune : une hostilité **installée** qui atteint le seuil. Sans
    hostilité du tout, il n'y a rien à garder contre personne — même un seuil
    à zéro (une surcharge passée, un réglage extrême) ne coupe pas les ponts
    avec tout le monde."""
    return hostility > 0.0 and hostility >= p.grudge


def estranged(hostility: float, p: SocialParams, settled: bool = False) -> bool:
    """Une rancune qui empêche l'amitié : le seuil ordinaire pour une amitié
    naissante ; une rancune plus lourde pour défaire une amitié installée (une
    dispute ne suffit pas)."""
    return hostility > 0.0 and hostility >= (p.grudge_demote if settled else p.grudge)


#: les critères d'un niveau de proximité (``Criterion.key``)
DAYS, MESSAGES, HISTORY, REGARD, BOND, GRUDGE = "days", "messages", "history", "regard", "bond", "grudge"


@dataclass(frozen=True, slots=True)
class Criterion:
    """Un critère d'un niveau de proximité, tel que le calcul l'a lu : la valeur, le seuil, s'il est tenu.
    ``either`` : il suffit à la place du critère précédent (« ou »). L'hostilité (``GRUDGE``) se tient sous son
    seuil ; les autres, au seuil ou au-dessus."""

    key: str
    value: float
    threshold: float
    held: bool
    either: bool = False


@dataclass(frozen=True, slots=True)
class LevelTrace:
    """Le rang qu'atteint une histoire (``days`` jours de contact, ``messages`` messages reçus), et les critères de
    chaque niveau, par rang (une inconnue n'en a aucun) : le rang est le plus haut dont les critères tiennent."""

    rank: int
    days: int
    messages: int
    criteria: tuple[tuple[Criterion, ...], ...]


def _holds(criteria: tuple[Criterion, ...]) -> bool:
    """Tous les critères, chacun ou celui qui suffit à sa place (``either``)."""
    groups: list[bool] = []
    for cr in criteria:
        if cr.either and groups:
            groups[-1] = groups[-1] or cr.held
        else:
            groups.append(cr.held)
    return all(groups)


def _friendly(hostility: float, p: SocialParams, settled: bool) -> Criterion:
    """Sans rancune (``estranged``) : sous le seuil ordinaire, ou sous celui, plus lourd, d'une amitié installée."""
    return Criterion(GRUDGE, hostility, p.grudge_demote if settled else p.grudge, not estranged(hostility, p, settled))


def _level(days: int, messages: int, history: int, regard: float, p: SocialParams, friendly: Criterion,
           bond: float = 0.0) -> LevelTrace:
    # l'attachement suffisant : plus modeste après une longue histoire, jamais nul (il en faut un)
    bar = min(p.close_bond, p.close_long_bond) if days >= p.close_long_days else p.close_bond
    criteria = (
        (),
        (Criterion(DAYS, days, p.acquaintance_days, days >= p.acquaintance_days),
         Criterion(MESSAGES, messages, p.acquaintance_messages, messages >= p.acquaintance_messages, either=True)),
        (friendly, Criterion(DAYS, days, p.friend_days, days >= p.friend_days),
         Criterion(MESSAGES, messages, p.friend_messages, messages >= p.friend_messages)),
        (friendly, Criterion(DAYS, days, p.close_days, days >= p.close_days),
         Criterion(MESSAGES, messages, p.close_messages, messages >= p.close_messages),
         Criterion(HISTORY, history, p.close_history_days, history >= p.close_history_days),
         Criterion(REGARD, regard, p.close_regard, regard >= p.close_regard),
         Criterion(BOND, bond, bar, bond > 0.0 and bond >= bar, either=True)),
    )
    rank = max(i for i, level in enumerate(criteria) if _holds(level))
    return LevelTrace(rank, days, messages, criteria)


def _counts(ct: Contact) -> tuple[int, ...]:
    if len(ct.counts) == len(ct.days):
        return ct.counts
    base, extra = divmod(ct.inbound, len(ct.days))  # sans décompte par jour : les messages répartis également
    return tuple(base + (1 if i < extra else 0) for i in range(len(ct.days)))


def span(ct: Contact) -> int:
    """Le temps vécu ensemble, en jours : de leur premier à leur dernier jour de contact — jamais le calendrier
    (une absence ne rend pas leur histoire plus longue)."""
    return ct.days[-1] - (ct.first_day or ct.days[0]) if ct.days else 0


def known(ct: Contact | None, regard: float, p: SocialParams, hostility: float = 0.0, bond: float = 0.0) -> str:
    """Ce qu'elles ont été l'une pour l'autre, sur toute leur histoire (sans le silence ni la fenêtre)."""
    if ct is None or not ct.days:
        return c.STRANGER
    total = max(ct.total_days, len(ct.days))
    friendly = _friendly(hostility, p, total >= p.friendship_settled_days)
    return c.CLOSENESS_LEVELS[_level(total, ct.inbound, span(ct), regard, p, friendly, bond).rank]


@dataclass(frozen=True, slots=True)
class ClosenessTrace:
    """Pourquoi ce niveau : le calcul de la proximité pas à pas (``lived``, puis le fait ``CLOSENESS``). Le niveau
    est celui de la trace — le fait le rend, la console l'explique : l'un ne peut pas contredire l'autre."""

    level: str
    #: fixée par un opérateur : elle l'emporte, rien d'autre n'est calculé
    declared: bool = False
    #: sur la fenêtre glissante (ce que le calcul lit) et sur toute leur histoire (d'où vient le plancher)
    window: LevelTrace | None = None
    everything: LevelTrace | None = None
    #: le temps vécu ensemble ; les jours depuis leur dernier jour de contact ; le rythme qu'elles avaient ; le
    #: silence qui fait perdre un cran, et s'il est atteint
    history: int = 0
    silent: int = 0
    rhythm_days: float = 0.0
    silence_bar: float = 0.0
    lost: bool = False
    #: le plancher d'histoire (un rang) ; une amitié courte que son silence a dépassée (connaissance au plus)
    floor: int = 0
    short: bool = False
    #: le niveau vécu, avant le plancher de la propriétaire ; l'hostilité lue
    lived_level: str = c.STRANGER
    hostility: float = 0.0
    #: l'affect a été lu (pas pour qui n'a pas l'histoire d'une amie : il n'y changerait rien)
    affect: bool = True
    #: une propriétaire sous son plancher (``owner_floored`` a tranché)
    owner: bool = False


def lived_trace(ct: Contact | None, regard: float, p: SocialParams, hostility: float = 0.0,
                now_day: int | None = None, bond: float = 0.0) -> ClosenessTrace:
    """``lived``, pas à pas."""
    if ct is None or not ct.days:
        return ClosenessTrace(c.STRANGER, hostility=hostility)
    last = ct.days[-1]
    today = last if now_day is None else max(now_day, last)
    total = max(ct.total_days, len(ct.days))
    friendly = _friendly(hostility, p, total >= p.friendship_settled_days)
    history = span(ct)
    everything = _level(total, ct.inbound, history, regard, p, friendly, bond)
    recent = [(day, n) for day, n in zip(ct.days, _counts(ct), strict=True) if today - day < p.closeness_window_days]
    window = _level(len(recent), sum(n for _d, n in recent), history, regard, p, friendly, bond)
    rhythm_days, _measured = rhythm(ct, last, c.CLOSENESS_LEVELS[everything.rank], p)  # le rythme qu'elles avaient
    silent = today - last
    bar = max(p.closeness_silence_min_days, p.closeness_silence_factor * rhythm_days)
    lost = silent >= bar
    floor = everything.rank - 1
    short = silent > history and total < p.lasting_days
    if short:
        floor = min(floor, _RANK[c.ACQUAINTANCE])  # une amitié plus courte que son silence
    level = c.CLOSENESS_LEVELS[max(_RANK[c.STRANGER], window.rank - (1 if lost else 0), floor)]
    return ClosenessTrace(level, window=window, everything=everything, history=history, silent=silent,
                          rhythm_days=rhythm_days, silence_bar=bar, lost=lost, floor=floor, short=short,
                          lived_level=level, hostility=hostility)


def lived(ct: Contact | None, regard: float, p: SocialParams, hostility: float = 0.0,
          now_day: int | None = None, bond: float = 0.0) -> str:
    """Ce que leur histoire a fait d'elles : on devient amies en passant du
    temps ensemble, sans rancune — pas en le disant (ni parce qu'un modèle
    l'a jugé) ; proches, avec de la chaleur installée ou de l'attachement (un
    attachement plus modeste suffit à une longue histoire : le temps approfondit,
    il ne crée pas — l'assiduité seule ne fait pas une intimité), et un mois
    d'histoire **vécue** au moins (dix soirées chaleureuses d'affilée font une
    amie à qui elle tient, pas encore une proche ; dix jours de silence n'y
    ajoutent rien).

    Ce qui compte, c'est leur histoire **récente** (une fenêtre glissante) ;
    un long silence (plusieurs fois son rythme) la fait descendre d'un cran ;
    une longue amitié (``lasting_days``) ne la laisse jamais tomber plus d'un
    cran sous ce qu'elle a été — une amitié courte que le silence a dépassée
    (il dure plus que toute leur histoire) redevient une connaissance. Une
    dispute ne défait pas une amitié : seule une rancune lourde
    (``grudge_demote``) le fait (ADR 0058). Le calcul pas à pas : ``lived_trace``."""
    return lived_trace(ct, regard, p, hostility, now_day, bond).level


#: au plus l'amitié d'office : « proche » se vit
_OWNER_FLOORS = (c.STRANGER, c.ACQUAINTANCE, c.FRIEND)


def owner_floored(level: str, p: SocialParams, hostility: float = 0.0) -> str:
    """Sa propriétaire reconnue : au moins ``owner_floor`` (une amitié d'office
    au plus), sauf rancune lourde — celle qui défait une amitié installée."""
    floor = p.owner_floor if p.owner_floor in _OWNER_FLOORS else c.STRANGER
    if estranged(hostility, p, settled=True) or _RANK.get(level, 0) >= _RANK[floor]:
        return level
    return floor


def closeness(s: SocialState, person: str, regard: float, p: SocialParams, hostility: float = 0.0,
              now_day: int | None = None, bond: float = 0.0) -> str:
    """Déclarée par un opérateur, sinon vécue."""
    declared = s.declared.get(person)
    return declared if declared is not None else lived(s.contacts.get(person), regard, p, hostility, now_day, bond)


def rhythm(ct: Contact, now_day: int, level: str, p: SocialParams) -> tuple[float, bool]:
    """L'écart habituel entre deux jours de contact : mesuré sur leur
    histoire récente, sinon un repli selon la proximité."""
    recent = [d for d in ct.days if now_day - d <= p.rhythm_window_days]
    gaps = [b - a for a, b in zip(recent, recent[1:], strict=False)]
    if len(gaps) >= p.rhythm_min_gaps:
        value = float(statistics.median(gaps))
        return max(p.rhythm_min_days, min(p.rhythm_max_days, value)), True
    fallback = {c.CLOSE: p.fallback_close_days, c.FRIEND: p.fallback_friend_days}.get(level, p.fallback_other_days)
    return fallback, False


def reciprocity(ct: Contact, p: SocialParams) -> tuple[int, int, bool]:
    """(ouvertes par elle, par la personne, presque toujours elle ?)"""
    her = sum(1 for _d, who in ct.starts if who == HER)
    them = sum(1 for _d, who in ct.starts if who == THEM)
    total = her + them
    return her, them, total >= p.reciprocity_min_starts and her / total >= p.one_sided_share


def _union(parts: list[Contact]) -> Contact:
    """Une histoire vécue sous plusieurs adresses d'une même personne, réunie : ses jours de contact (et les
    messages de chacun), ses premiers et derniers échanges, qui a ouvert leurs conversations."""
    if len(parts) == 1:
        return parts[0]
    per_day: dict[int, int] = {}
    for ct in parts:
        for day, n in zip(ct.days, _counts(ct), strict=True):
            per_day[day] = per_day.get(day, 0) + n
    days = sorted(per_day)[-KEEP_DAYS:]
    shared = sum(len(ct.days) for ct in parts) - len(per_day)  # des jours vécus sous deux adresses à la fois
    last_in = max(ct.last_in for ct in parts)
    latest = max(parts, key=lambda ct: (ct.last_activity, ct.last_in, ct.since, ct.previous))
    return Contact(
        days=tuple(days), counts=tuple(per_day[d] for d in days), inbound=sum(ct.inbound for ct in parts),
        first_in=min((ct.first_in for ct in parts if ct.first_in), default=0), last_in=last_in,
        last_out=max(ct.last_out for ct in parts),
        # ses initiatives restées sans réponse depuis le dernier message de la personne, par quelque adresse
        unanswered=sum(ct.unanswered for ct in parts if ct.last_out > last_in),
        total_days=sum(max(ct.total_days, len(ct.days)) for ct in parts) - shared,
        first_day=min((ct.first_day or ct.days[0] for ct in parts if ct.days), default=0),
        last_activity=latest.last_activity, since=latest.since, previous=latest.previous,
        starts=tuple(sorted({st for ct in parts for st in ct.starts}))[-STARTS_KEPT:],
    )


def contact_of(s: SocialState, person: str, handles: Any) -> Contact | None:
    """Leur histoire, sous toutes les adresses de la personne (``identity.HANDLES``)."""
    parts = [s.contacts[k] for k in sorted({person, *handles}) if k in s.contacts]
    return _union(parts) if parts else None


def felt_of(s: SocialState, person: str, handles: Any) -> tuple[str, int] | None:
    """Le dernier cran de ce lien qu'elle a ressenti, et quand — sous toutes les adresses de la personne (le plus
    récent : une adresse reliée apporte son histoire) ; ``None`` : jamais relevé."""
    found = [(s.felt_levels[k][1], k) for k in sorted({person, *handles}) if k in s.felt_levels]
    return s.felt_levels[max(found)[1]] if found else None


def gathered(s: SocialState, person: str, handles: Any) -> SocialState:
    """La tranche vue depuis une personne : ce qu'elle a vécu sous ses autres adresses — reliées depuis à elle, par
    un opérateur ou un recoupement — se réunit sous sa clé. Les réducteurs rangent l'histoire sous la personne que
    l'adresse désignait au moment de l'événement ; une liaison ne la déplace pas, la lecture la rassemble (délier
    rend à chaque adresse la sienne). Sans autre adresse vécue, la tranche telle quelle."""
    others = sorted(k for k in set(handles) - {person}
                    if k in s.contacts or k in s.greeted or k in s.rekindled or k in s.noticed or k in s.felt_levels)
    if not others:
        return s

    def latest(d: FrozenDict[str, int]) -> FrozenDict[str, int]:
        at = max((d[k] for k in (person, *others) if k in d), default=None)
        return d if at is None else d.set(person, at)

    ct = contact_of(s, person, others)
    contacts = s.contacts if ct is None else s.contacts.set(person, ct)
    felt = felt_of(s, person, others)
    felt_levels = s.felt_levels if felt is None else s.felt_levels.set(person, felt)
    return replace(s, contacts=contacts, greeted=latest(s.greeted), rekindled=latest(s.rekindled),
                   noticed=latest(s.noticed), felt_levels=felt_levels)


def contact_reading(s: SocialState, person: str, now: int, now_day: int, level: str,
                    p: SocialParams) -> c.ContactReading:
    ct = s.contacts.get(person) or Contact()
    days, measured = rhythm(ct, now_day, level, p)
    usual = rhythm(ct, ct.days[-1], level, p)[0] if ct.days else days
    ratio = (now - ct.last_in) / (days * DAY) if ct.last_in else 0.0
    her, them, one_sided = reciprocity(ct, p)
    return c.ContactReading(person, max(ct.total_days, len(ct.days)), ct.inbound, ct.first_in, ct.last_in,
                            ct.last_out, days, measured, ct.unanswered, max(0.0, ratio), previous=ct.previous,
                            since=ct.since, her_starts=her, their_starts=them, one_sided=one_sided, usual_days=usual)


@SOCIAL.fact(c.GREETED, reads=[identity_c.HANDLES])
def _greeted(s: SocialState, cx, person: str) -> int:
    return gathered(s, person, cx.facts.get(identity_c.HANDLES(person))).greeted.get(person, 0)


def _could_be_friends(ct: Contact, p: SocialParams) -> bool:
    """Assez d'histoire pour avoir pu être une amie (jours de contact et messages) : en deçà, une connaissance au
    plus, quoi que l'affect en dise — la proximité ne dépasse jamais ce que l'histoire permet."""
    return max(ct.total_days, len(ct.days)) >= p.friend_days and ct.inbound >= p.friend_messages


def closeness_trace(s: SocialState, person: str, p: SocialParams, today: int,
                    get: Callable[[Any], Any]) -> ClosenessTrace:
    """Déclarée, sinon vécue ; le plancher d'une propriétaire — pas à pas. ``get`` lit les faits (``cx.facts.get``
    pour le fait, ``frame.get`` pour la console). Ce qui coûte (l'affect, la propriété) ne se lit que quand ça peut
    changer quelque chose : une inconnue sans histoire n'a ni chaleur ni rancune à peser."""
    declared = s.declared.get(person)
    if declared is not None:
        return ClosenessTrace(declared, declared=True)
    ct = contact_of(s, person, get(identity_c.HANDLES(person)))  # une adresse reliée apporte son histoire
    floor = p.owner_floor if p.owner_floor in _OWNER_FLOORS else c.STRANGER
    if ct is None or not ct.days or not _could_be_friends(ct, p):
        # une connaissance au plus : ni la chaleur, ni l'attachement, ni la rancune n'y changent rien
        trace = replace(lived_trace(ct, 0.0, p, 0.0, today), affect=False)
        if _RANK[trace.level] >= _RANK[floor] or not get(identity_c.IS_OWNER(person)):
            return trace
        hostility = get(affect_c.HOSTILITY(person))
        return replace(trace, level=owner_floored(trace.level, p, hostility), hostility=hostility, owner=True)
    hostility = get(affect_c.HOSTILITY(person))
    trace = lived_trace(ct, get(affect_c.REGARD(person)), p, hostility, today, get(affect_c.BOND(person)))
    if _RANK[trace.level] < _RANK[floor] and get(identity_c.IS_OWNER(person)):
        return replace(trace, level=owner_floored(trace.level, p, hostility), owner=True)
    return trace


@SOCIAL.fact(c.CLOSENESS, reads=[affect_c.REGARD, affect_c.HOSTILITY, affect_c.BOND, identity_c.IS_OWNER,
                                  identity_c.HANDLES])
def _closeness(s: SocialState, cx, person: str) -> str:
    """Déclarée, sinon vécue ; le plancher d'une propriétaire (``closeness_trace``, que la console déroule)."""
    return closeness_trace(s, person, params(cx.params), cx.local(cx.now).date().toordinal(), cx.facts.get).level


@SOCIAL.fact(c.CONTACT, reads=[c.CLOSENESS, identity_c.HANDLES])
def _contact(s: SocialState, cx, person: str) -> c.ContactReading:
    return contact_reading(gathered(s, person, cx.facts.get(identity_c.HANDLES(person))), person, cx.now, cx.local(cx.now).date().toordinal(), cx.facts.get(c.CLOSENESS(person)),
                           params(cx.params))


@SOCIAL.fact(c.CIRCLE, reads=[identity_c.OWNERS, identity_c.PERSON])
def _circle(s: SocialState, cx) -> tuple[str, ...]:
    """Celles qui sont — ou ont pu être — des amies ou des proches : un tri bon marché, sans affect ni calcul de
    proximité, pour que ce qui ne regarde que les amies ne pèse pas le prix de toutes les inconnues de passage
    (une amie a eu assez de jours de contact et de messages ; une proximité déclarée ; une propriétaire, amie
    d'office). Toute amie ou proche d'aujourd'hui en est (``CLOSENESS`` ne dépasse jamais l'histoire). Des
    personnes telles qu'elles valent maintenant : une adresse reliée depuis à quelqu'un n'y figure plus pour
    elle-même, son histoire compte pour la personne (elle ne lui manque pas pendant qu'elle écrit par une autre)."""
    p = params(cx.params)

    def person_of(key: str) -> str:
        return cx.facts.get(identity_c.PERSON(key)) or key

    out = {person_of(person) for person, level in s.declared.items() if level in (c.FRIEND, c.CLOSE)}
    lived_by: dict[str, list[Contact]] = {}
    for key, ct in sorted(s.contacts.items()):
        lived_by.setdefault(person_of(key), []).append(ct)
    out |= {person for person, parts in lived_by.items()
            if person not in s.declared and _could_be_friends(_union(parts), p)}
    if p.owner_floor == c.FRIEND:
        out |= {o for o in cx.facts.get(identity_c.OWNERS) if o not in s.declared}
    return tuple(sorted(out))


def been_friends(s: SocialState, person: str, p: SocialParams, hostility: float, owner: bool) -> bool:
    """A-t-elle été une amie (ou une proche) — sur toute leur histoire, pas seulement aujourd'hui ? Une amitié
    qu'une rancune lourde a défaite, non."""
    declared = s.declared.get(person)
    if declared is not None:
        return declared in (c.FRIEND, c.CLOSE)
    if _RANK[known(s.contacts.get(person), 0.0, p, hostility)] >= _RANK[c.FRIEND]:
        return True
    return owner and p.owner_floor == c.FRIEND and not estranged(hostility, p, settled=True)


@SOCIAL.fact(c.TIES, reads=[identity_c.PERSON])
def _ties(s: SocialState, cx, person: str) -> tuple[str, ...]:
    """Les personnes avec qui elle a un lien (ADR 0058), telles qu'elles valent maintenant : une adresse reliée
    depuis à quelqu'un, un nom qu'un opérateur a relié à une personne parlent pour elle."""
    out: set[str] = set()
    for key, others in s.ties.items():
        if key == person or (cx.facts.get(identity_c.PERSON(key)) or key) == person:
            out |= {cx.facts.get(identity_c.PERSON(o)) or o for o in others}
    out.discard(person)
    return tuple(sorted(out))


@SOCIAL.fact(c.SENSITIVE)
def _sensitive(s: SocialState, cx, person: str) -> tuple[str, ...]:
    profile = s.profiles.get(person)
    return tuple(fold(t) for t in profile.sensitive) if profile else ()


@SOCIAL.fact(c.SENSITIVE_REF)
def _sensitive_ref(s: SocialState, cx, person: str) -> str:
    profile = s.profiles.get(person)
    return profile.sensitive_ref if profile else ""


@SOCIAL.fact(c.INTERESTS_REF)
def _interests_ref(s: SocialState, cx, person: str) -> str:
    profile = s.profiles.get(person)
    return profile.interests_ref if profile else ""


@SOCIAL.fact(c.MISSED, reads=[c.CIRCLE, c.CONTACT, affect_c.HOSTILITY, identity_c.IS_OWNER, identity_c.HANDLES])
def _missed(s: SocialState, cx) -> tuple[tuple[str, float], ...]:
    """Celles qui lui manquent : des amies ou des proches — d'aujourd'hui ou d'avant, une amie partie sans plus
    donner de nouvelles manque encore (ADR 0058) — dont le silence dépasse son seuil."""
    p = params(cx.params)
    out = []
    for person in cx.facts.get(c.CIRCLE):
        if not is_identifiable(person) or person.startswith("name:"):
            continue
        view = gathered(s, person, cx.facts.get(identity_c.HANDLES(person)))
        if person not in view.contacts:
            continue
        ratio = cx.facts.get(c.CONTACT(person)).silence_ratio
        if ratio < p.recontact_factor:
            continue
        hostility = cx.facts.get(affect_c.HOSTILITY(person))
        if been_friends(view, person, p, hostility, bool(cx.facts.get(identity_c.IS_OWNER(person)))):
            out.append((person, round(ratio, 3)))
    return tuple(sorted(out, key=lambda x: (-x[1], x[0])))
