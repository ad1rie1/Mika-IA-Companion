"""Contrat d'``agency`` : le budget d'initiatives, la période réfractaire —
et ce qui n'est pas « prendre la parole ».

Une initiative ne compte qu'une fois **dite** (un énoncé visible) : un
silence, une panne, une initiative supplantée ne consomment rien. Une
abstention laisse une courte hésitation ; un murmure « sans suite » (elle
s'apprêtait à écrire à quelqu'un, puis s'est ravisée) arrête l'initiative
qu'il précédait.

Toutes les raisons d'aller vers quelqu'un ne se valent pas : certaines sont
**dues** (tenir parole), d'autres **préviennent** (ce qui ne peut pas
attendre), d'autres **saluent** qui arrive, d'autres ne regardent **que la
personne** (prendre soin d'elle). C'est déclaré ici, une fois, et lu par
chaque retenue (le budget, ne pas harceler, la rancune, l'heure où la
personne répond, qui écrit la première) — jamais redit dans une faculté.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from mika.contracts import attention as attention_c
from mika.contracts import email as email_c
from mika.contracts import forge as forge_c
from mika.contracts import goals as goals_c
from mika.contracts import imaging as imaging_c
from mika.contracts import mcp as mcp_c
from mika.contracts import memory as memory_c
from mika.contracts import needs as needs_c
from mika.contracts import others as others_c
from mika.contracts import projects as projects_c
from mika.contracts import social as social_c
from mika.contracts import wakeup as wakeup_c
from mika.kernel.episode import Outcome
from mika.kernel.facts import FactFamily, FactKey

OWNER = "agency"

DAILY_CAP = "daily_cap"
REFRACTORY = "refractory"
#: Veto : des initiatives restées sans réponse vers cette personne — plus rien tant qu'elle n'a pas écrit (une
#: seule relance douce, après un long délai, vers une amie ou une proche).
UNANSWERED = "unanswered"
#: Veto : son dernier message à cette personne attend encore sa réponse (quelques heures de retenue).
AWAITING_REPLY = "awaiting_reply"
#: on s'est dit au revoir (« bonne nuit », « je file ») : pas d'initiative ordinaire tout de suite après, même
#: si la personne reste connectée
FAREWELL = "farewell"
#: Veto : elle allait lui écrire et s'est ravisée (un murmure sans suite) — pas tout de suite, donc.
CHANGED_MIND = "changed_mind"
#: Veto : ses dernières envies de lui écrire ont fini en silence (ou en panne), d'affilée — elle laisse passer de
#: plus en plus de temps avant d'y revenir.
HESITATING = "hesitating"
#: Veto : la personne est en train de lui écrire (``presence.COMPOSING``) — elle attend son message, et y répondra.
COMPOSING = "composing"
#: Veto : la personne n'est pas là et ce n'est pas une heure où elle écrit d'habitude (``others.HOURS`` : apprises,
#: sinon une nuit supposée) — on n'écrit pas à quelqu'un qui dort ; ce qui est dû ou prévient passe outre.
NOT_REACHABLE = "not_reachable"
#: Raison (sans preuve) des candidats qui portent la garde « elle s'est ravisée » vers une adresse présente.
SECOND_THOUGHTS = "second_thoughts"

#: Ce qui est **dû** : tenir parole — dire à l'heure dite le rappel qu'on lui a demandé, faire au moment dit ce
#: qu'elle avait promis (« je te demanderai jeudi soir comment ça s'est passé », ``memory.KEEP_PROMISE``). Ce
#: n'est pas « prendre la parole » : ni le plafond du jour, ni la période réfractaire, ni la retenue envers qui
#: ne répond pas, ni l'heure où la personne répond d'habitude ne s'y appliquent ; une rancune non plus — elle
#: colore le ton, elle ne reprend pas la promesse. Un dessin promis aussi : le montrer quand il est prêt, ou dire
#: qu'il n'a pas pu se faire (``imaging``, ADR 0063). Rendre compte de ce qu'un réveil par API lui a fait faire, à
#: qui il le dit (``wakeup``, ADR 0068). Dire ce qu'un service ou une app a rendu après un accord (ADR 0064, 0133).
OWED = frozenset({goals_c.REMIND, memory_c.KEEP_PROMISE, imaging_c.DELIVER, imaging_c.COULD_NOT,
                  mcp_c.ANSWERED_REASON, forge_c.ANSWERED_REASON, wakeup_c.DONE})
#: Ce qui **prévient** : ce qui ne peut pas attendre et regarde la personne au premier chef — un mail important
#: arrivé pour sa propriétaire, un projet qu'elle lui a confié qui n'avance plus sans elle, ce qu'une de ses apps
#: vient de trouver pour la personne que son projet concerne (ADR 0105). Prévenir n'est pas
#: relancer : la retenue « ne pas harceler » ne s'y applique pas, une rancune le décale au plus (on prévient
#: quelqu'un même fâchée contre lui), et être ignorée n'y change rien — ni l'allongement de la période
#: réfractaire par les initiatives restées sans réponse, ni l'envie moindre envers qui n'a pas répondu, ni s'être
#: ravisée de lui écrire pour autre chose. C'est déjà borné par sa source (une fois par mail, une fois par
#: objectif bloqué) ; le plafond du jour et la période réfractaire **de base** s'y appliquent toujours (ne pas
#: annoncer trois mails en trois messages d'affilée).
INFORMS = frozenset({email_c.MENTION, projects_c.NEED, forge_c.APP_NEWS, forge_c.APP_ALERT})
#: … sauf ce qui prévient sans presser : ce qu'une app a trouvé pour la personne attend qu'elle ait répondu à ce
#: qu'elle lui a déjà écrit d'elle-même. Sans cela, une veille d'actualité (trois relevés par jour) lui écrivait des
#: nouvelles sans fin à qui ne répondait plus (2026-10-19, sur le portable). Un mail important, un projet bloqué,
#: ce qu'une app a trouvé et qu'elle a jugé urgent (``forge.APP_ALERT``) ne l'attendent pas.
WAITS_FOR_AN_ANSWER = frozenset({forge_c.APP_NEWS})
#: **Saluer** qui arrive : pas « prendre la parole » non plus (ni plafond, ni période réfractaire, ni retenue
#: envers qui ne répond pas) — mais une rancune l'empêche (ADR 0013 : pas même une salutation).
GREETS = frozenset({social_c.GREETING})
#: Ce qui n'est pas prendre la parole pour qu'on lui réponde : saluer qui arrive, tenir parole. Ni compté au
#: budget, ni suivi d'une période réfractaire, ni attendu en retour (ce n'était pas une question) — seul (``spoke_up``).
NOT_SPEAKING_UP = GREETS | OWED
#: Ce qui ne regarde **que la personne** : prendre de ses nouvelles parce qu'on s'inquiète, lui demander comment
#: s'est passé ce qu'elle avait de prévu, l'encourager ou lui souhaiter (``others.WELL_WISHES``), revenir sur ce qui
#: pèse entre vous, lui rendre ce qu'on a fait de ce qui la concernait. C'est prendre la parole (le budget, la
#: période réfractaire s'y appliquent), mais pas « écrire toujours la première » : on ne tient pas ses comptes quand
#: on prend soin de quelqu'un — ``social`` ne le compte pas dans la réciprocité. Avec ce qui prévient (``INFORMS``),
#: ça n'attend pas que son dernier message ait trouvé sa réponse (``agency``).
FOR_THEM = others_c.WELL_WISHES | frozenset({others_c.CHECK_IN, others_c.FOLLOW_UP, attention_c.THOUGHT,
                                             goals_c.SHARE, projects_c.SHARE})


def spoke_up(reasons: Iterable[str], *, waiting: bool = False) -> bool:
    """Ce qu'une initiative **dite** a été : saluer qui arrive ou tenir parole, seuls, ce n'est pas prendre la
    parole ; mais une salutation (ou une parole tenue) qui emporte une nouvelle, un récit, une demande, des nouvelles
    prises (``INFORMS | FOR_THEM``), si — sans quoi le message qui disait tout à l'arrivée de quelqu'un ne comptait
    pour rien (sonde du 2026-10-13), et n'attendait pas de réponse (2026-10-19). Saluer quelqu'un qui a laissé sans
    réponse ce qu'elle lui avait écrit d'elle-même (``waiting``), c'est le relancer."""
    got = set(reasons)
    if not NOT_SPEAKING_UP & got or (INFORMS | FOR_THEM) & got:
        return True
    return waiting and bool(GREETS & got) and not OWED & got


def checking_in(reasons: Iterable[str], unanswered: int) -> bool:
    """Une initiative vers quelqu'un qui a laissé sans réponse ce qu'elle lui avait écrit d'elle-même
    (``unanswered``), sans rien qui presse (tenir parole, prévenir) : c'est une relance. Elle prend de ses nouvelles
    et ne lui apporte rien de nouveau ; ce qui la poussait (une nouvelle, un récit) attend qu'il ait répondu — sur le
    portable, ses relances n'étaient qu'une suite d'actualités (2026-10-19)."""
    return unanswered > 0 and not (OWED | (INFORMS - WAITS_FOR_AN_ANSWER)) & set(reasons)
#: Pourquoi elle était en train d'écrire à quelqu'un quand son message est arrivé (« j'allais justement
#: t'écrire ! ») : la réponse qui suit le sait — le premier motif de cette liste présent parmi les raisons de
#: l'initiative, dit avec les mots de ``agency.crossed.motive`` (persona/voix.yaml, ADR 0071). Une raison absente
#: de la liste est tue : la ligne dit seulement qu'elle allait lui écrire.
CROSSED_MOTIVES: tuple[str, ...] = (
    others_c.FOLLOW_UP, others_c.CHECK_IN, others_c.CELEBRATE, others_c.CHEER, attention_c.THOUGHT,
    social_c.RECONTACT, social_c.REKINDLE, social_c.COMFORT, social_c.CHAT, needs_c.NEED_SOCIAL,
)

#: Après tant d'initiatives restées sans réponse vers quelqu'un, plus rien vers cette personne tant qu'elle n'a pas
#: écrit (ADR 0033) : elle ne peut plus lui écrire — ce qui lui reste, c'est d'y penser (``attention``). C'est la
#: valeur au milieu de la matrice (une initiative, une relance) ; la sienne, son tempérament la dit
#: (``AgencyReading.gives_up_after`` : de une à quatre).
GIVE_UP_AFTER = 2
#: … sauf, longtemps après, prendre de ses nouvelles **une fois** (``social.REKINDLE``, ADR 0058) : ça passe la
#: retenue « sans réponse » tant que la personne n'a pas plus de ``gives_up_after`` initiatives sans réponse —
#: dite, elle en a une de plus, et plus rien ne passe. Être ignorée n'en diminue pas l'envie (c'est déjà rare, et
#: unique).
ONCE_MORE = frozenset({social_c.REKINDLE})

#: Les fins d'une initiative qui ne sont pas un **essai** : elle a été devancée (la personne a écrit pendant
#: qu'elle composait), interrompue, annulée — elle n'a pas eu lieu. (Un murmure sans suite non plus : elle s'est
#: ravisée, « pas maintenant » — ``RENOUNCED`` le dit, à l'adresse visée.) Un silence choisi, une panne, si. Ce
#: qu'une faculté compte comme tentatives (dire un rappel, raconter, demander un coup de main) se compte ainsi.
UNTRIED = frozenset({Outcome.SUPERSEDED, Outcome.PREEMPTED, Outcome.CANCELLED, Outcome.INTERRUPTED})


def tried(outcome: str, started: int, renounced: int) -> bool:
    """Une initiative partie à ``started`` finit sans avoir rien dit : est-ce un essai ? Un silence choisi, une
    panne, oui ; pas une initiative devancée, interrompue ou annulée (``UNTRIED``), ni un murmure sans suite —
    ``renounced`` (le fait ``RENOUNCED`` de l'adresse visée) postérieur à son départ."""
    return outcome not in UNTRIED and not (renounced and started and renounced >= started)


@dataclass(frozen=True, slots=True)
class AgencyReading:
    initiatives_today: int
    last_initiative_at: int
    refractory_until: int
    murmured_at: int = 0
    #: la dernière hésitation (une abstention, une panne, un murmure sans suite)
    hesitated_at: int = 0
    #: la fin de la période réfractaire **de base** (sans l'allongement par les initiatives ignorées) : celle
    #: qui s'applique à ce qui prévient (``INFORMS``)
    base_until: int = 0
    #: après tant d'initiatives restées sans réponse vers quelqu'un, elle laisse tomber (sa première, puis ses
    #: relances : son tempérament le dit)
    gives_up_after: int = GIVE_UP_AFTER


AGENCY = FactKey("agency.agency", type=AgencyReading, time_varying=True)
#: Quand elle s'est ravisée pour la dernière fois d'écrire à cette adresse (0 : jamais).
RENOUNCED = FactFamily("agency.renounced", arg=str, type=int)
