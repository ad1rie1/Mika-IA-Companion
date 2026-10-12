"""La faculté ``self`` : sa tranche d'état et ce qu'elle déclare. Ses contributions vivent chacune dans son module
(``narrative``, ``esteem``, ``model``, ``interests``, ``absence``, ``persona``, ``greeting``, ``night``,
``inspect``)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mika.contracts import body as body_c
from mika.contracts import self_ as c
from mika.faculties.self import days
from mika.faculties.self.knobs import SelfParams, derive
from mika.faculties.self.records import Deed, Dream, Effort, Interest, Journal, Knock, Lead, Mark
from mika.kernel.faculty import Faculty
from mika.kernel.frame import Frame
from mika.kernel.state import FrozenDict


@dataclass(frozen=True, slots=True)
class SelfState:
    persona: c.PersonaDoc = field(default_factory=c.PersonaDoc)
    revisions: int = 0
    esteem: float = 0.5  # à ``esteem_at``
    esteem_at: int = 0
    souvenirs: int = 0
    narrative_ref: str = ""
    #: les personnes que le récit peut nommer (reportées au récit suivant, qui le relit)
    narrative_about: tuple[str, ...] = ()
    narrated_at: int = 0
    narrated_souvenirs: int = 0
    #: les souvenirs relus pour l'écrire ; l'un a changé (il se réécrit) ; l'un est devenu secret (il se tait d'ici
    #: là) — ADR 0082
    narrative_sources: tuple[int, ...] = ()
    narrative_stale: bool = False
    narrative_masked: bool = False
    journals: FrozenDict[str, Journal] = field(default_factory=FrozenDict)  # par journée vécue
    dreams: tuple[Dream, ...] = ()  # les plus récents
    #: les derniers coups portés à son estime
    knocks: tuple[Knock, ...] = ()
    #: ce que ses réussites lui ont rendu, sur la journée vécue ``gains_day``
    gains_day: str = ""
    gains: float = 0.0
    #: ce que les mots de chacun ont fait à son estime, sur la journée vécue ``social_day``
    social_day: str = ""
    social: FrozenDict[str, float] = field(default_factory=FrozenDict)
    #: « goal:12 », « objective:3:7 » → ce que ça lui a demandé jusqu'ici
    efforts: FrozenDict[str, Effort] = field(default_factory=FrozenDict)
    #: ce qu'elle a fait de son côté (le journal le raconte)
    deeds: tuple[Deed, ...] = ()
    #: sa nuit : quand elle s'est endormie, ce que la digestion a apaisé depuis son dernier réveil, le réveil
    #: déjà raconté
    asleep_at: int = 0
    eased: int = 0
    woke_at: int = 0
    woke_night: str = ""
    #: sa dernière parole visible (une nuit coupée par une conversation fait réécrire son journal)
    spoke_at: int = 0
    #: qui s'est excusé, et quelle journée vécue (une fois par jour et par personne)
    apologies: FrozenDict[str, str] = field(default_factory=FrozenDict)
    #: ses réussites et ses ratés récents — tenir parole, mener au bout, voir venir (ADR 0088)
    record: tuple[Mark, ...] = ()
    #: ses centres d'intérêt vivants, par clé (la ligne de sa persona, « lived:<nuit> »), et ses pistes ; la dernière
    #: nuit où elle y a réfléchi, jusqu'à quelle piste, et la dernière naissance (ADR 0089)
    interests: FrozenDict[str, Interest] = field(default_factory=FrozenDict)
    leads: tuple[Lead, ...] = ()
    reflected_night: str = ""
    reflected_upto: int = 0
    last_birth_at: int = 0
    #: ce qui la fait changer, compté (ADR 0090) : ce qu'elle a dit d'elle qui la définit, ses changements d'avis,
    #: ce qu'elle a vécu à travers les autres — et où en étaient ces comptes, ce qu'elle savait d'elle et ses intérêts
    #: (clé, niveau), à son dernier récit
    self_beliefs: int = 0
    changes: int = 0
    lived: int = 0
    narrated_self_beliefs: int = 0
    narrated_changes: int = 0
    narrated_lived: int = 0
    narrated_knows: tuple[str, ...] = ()
    narrated_interests: tuple[tuple[str, str], ...] = ()


#: v5 : une rêverie n'est ni une réussite (estime) ni « se lancer » (journal), une réussite ne compte son effort
#: que s'il est prouvé, des excuses adoucissent (ADR 0047)
#: v6 : un rêve et un journal gardent leur filiation — devant qui leurs sources permettent de les redire (ADR 0078)
#: v7 : le récit, un rêve, un journal suivent leurs sources : devenue secrète, il se tait (ADR 0082)
#: v8 : ses réussites et ses ratés (``record``) : ce qu'elle sait d'elle (ADR 0088)
#: v9 : ses centres d'intérêt vivent, ses pistes, sa réflexion de la nuit (ADR 0089)
#: v10 : le récit se réécrit quand elle a changé, sur tout ce qu'elle sait d'elle (ADR 0090)
#: v11 : une réflexion menée au bout n'est pas un exploit : ni estime, ni « elle mène ses buts au bout » (ADR 0096)
#: v12 : une source devenue une confidence (un sujet délicat, ``memory.delicate``) fait taire le récit, le rêve, le
#: journal intime qui la reprenaient, comme une source devenue secrète (ADR 0099)
SELF = Faculty("self", state=SelfState, init=lambda p: SelfState(), params=SelfParams, derive=derive, state_version=12,
               retired_params=("achieved_knock",))
SELF.declare(c.PERSONA_REVISED, c.NARRATED, c.JOURNALED, c.DREAMT, c.WOKE_WITH, c.TOUCHED, c.INTEREST_BORN,
             c.REFLECTED)


def day_of(cx: Any, at: int) -> str:
    """La journée vécue d'un instant, selon son rythme (lu chez ``body``), dans un réducteur."""
    return days.lived_day(at, cx.tz, days.day_starts(cx.facts.get(body_c.RHYTHM))).isoformat()


def lived_day_of(frame: Frame, at: int) -> str:
    """La même, depuis un cadre (un interprète, un processus)."""
    return days.lived_day(at, frame.env.tz_of(frame.root), days.day_starts(frame.get(body_c.RHYTHM))).isoformat()
