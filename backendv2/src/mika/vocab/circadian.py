"""Le rythme circadien : des phases locales, une teinte, une vigilance.

Fonctions pures d'un profil et d'une heure locale. Les phases changent à des
instants **déterministes** (les débuts de phase, en heure locale, heure d'été
comprise) : les physiques qui en dépendent (le repos de l'humeur) sont
constantes par morceaux entre ces instants, jamais échantillonnées à la
cadence d'une boucle.

La **vigilance de l'heure** (le processus C) culmine en début de soirée, avec
un creux après le déjeuner et son plus bas au petit matin. Ce n'est pas la
fatigue : elle vient de la pression de sommeil (``body``) — on est fatigué
près de l'heure où l'on s'endort, pas « parce qu'il est 22 h ».
"""

from __future__ import annotations

import enum
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from types import MappingProxyType
from zoneinfo import ZoneInfo

from mika.kernel.clock import local, next_local
from mika.vocab.affect import Emotion, Vec3, to_pad


class Phase(enum.StrEnum):
    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"
    NIGHT = "night"


PHASE_FR: Mapping[Phase, str] = MappingProxyType({
    Phase.MORNING: "matin",
    Phase.AFTERNOON: "après-midi",
    Phase.EVENING: "soir",
    Phase.NIGHT: "nuit",
})

#: « c'est le matin »…
MOMENT_FR: Mapping[Phase, str] = MappingProxyType({
    Phase.MORNING: "le matin",
    Phase.AFTERNOON: "l'après-midi",
    Phase.EVENING: "le soir",
    Phase.NIGHT: "la nuit",
})

#: Une tendance, dite comme une tendance (jamais une consigne).
_TENDENCY_FR: Mapping[Phase, str] = MappingProxyType({
    Phase.MORNING: "Le matin, tu es d'ordinaire plutôt d'attaque.",
    Phase.AFTERNOON: "L'après-midi, tu es souvent en forme, facilement enjouée.",
    Phase.EVENING: "Le soir, d'habitude, tu te poses et ton ton se fait plus doux.",
    Phase.NIGHT: "La nuit, tu es souvent plus rêveuse.",
})


def _default_starts() -> tuple[tuple[Phase, int], ...]:
    return ((Phase.MORNING, 6 * 60), (Phase.AFTERNOON, 12 * 60), (Phase.EVENING, 18 * 60), (Phase.NIGHT, 23 * 60))


def _default_tints() -> Mapping[Phase, Emotion]:
    return MappingProxyType({
        Phase.MORNING: Emotion.HOPEFUL,
        Phase.AFTERNOON: Emotion.PLAYFUL,
        Phase.EVENING: Emotion.RELIEVED,
        Phase.NIGHT: Emotion.DREAMY,
    })


@dataclass(frozen=True, slots=True)
class Profile:
    """Un rythme : débuts de phase (minutes locales), teinte de chaque phase,
    vigilance de l'heure (un cosinus sur 24 h culminant en début de soirée,
    moins un creux après le déjeuner)."""

    starts: tuple[tuple[Phase, int], ...] = field(default_factory=_default_starts)
    tints: Mapping[Phase, Emotion] = field(default_factory=_default_tints)
    tint_strength: float = 0.35
    energy_peak_hour: float = 18.0
    energy_amplitude: float = 0.36
    energy_baseline: float = 0.62
    energy_dip_hour: float = 14.0
    energy_dip: float = 0.08

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.starts, key=lambda s: s[1]))
        if {p for p, _ in ordered} != set(Phase) or len(ordered) != len(Phase):
            raise ValueError("un profil déclare exactement un début par phase")
        object.__setattr__(self, "starts", ordered)
        object.__setattr__(self, "tints", MappingProxyType(dict(self.tints)))

    def start_of(self, phase: Phase) -> int:
        return next(m for p, m in self.starts if p is phase)

    def shifted(self, minutes: int) -> Profile:
        """Le même rythme décalé (chronotype) : phases et pic d'énergie."""
        return Profile(
            starts=tuple((p, (m + minutes) % (24 * 60)) for p, m in self.starts),
            tints=self.tints,
            tint_strength=self.tint_strength,
            energy_peak_hour=(self.energy_peak_hour + minutes / 60.0) % 24.0,
            energy_amplitude=self.energy_amplitude,
            energy_baseline=self.energy_baseline,
            energy_dip_hour=(self.energy_dip_hour + minutes / 60.0) % 24.0,
            energy_dip=self.energy_dip,
        )


DEFAULT = Profile()


def phase_of(dt: datetime, profile: Profile = DEFAULT) -> Phase:
    """La phase d'une heure locale : la dernière dont le début est passé
    (avant le premier début de la journée, c'est la dernière de la veille)."""
    minute = dt.hour * 60 + dt.minute
    current = profile.starts[-1][0]
    for phase, start in profile.starts:
        if minute >= start:
            current = phase
    return current


def phase_at(t: int, tz: ZoneInfo, profile: Profile = DEFAULT) -> Phase:
    return phase_of(local(t, tz), profile)


def boundaries(t0: int, t1: int, tz: ZoneInfo, profile: Profile = DEFAULT) -> list[int]:
    """Les instants de ``]t0, t1]`` où la phase change, dans l'ordre."""
    out: list[int] = []
    cursor = t0
    while True:
        nxt = min(next_local(cursor, m // 60, m % 60, tz) for _, m in profile.starts)
        if nxt > t1:
            return out
        out.append(nxt)
        cursor = nxt


def tint(phase: Phase, profile: Profile = DEFAULT) -> Vec3:
    return to_pad(profile.tints[phase], profile.tint_strength)


def energy(dt: datetime, profile: Profile = DEFAULT) -> float:
    """La vigilance de l'heure, dans [0, 1] : un cosinus culminant à
    ``energy_peak_hour``, moins un creux (une gaussienne d'une heure et demie)
    autour de ``energy_dip_hour``. Sans la fatigue (``body``)."""
    hour = dt.hour + dt.minute / 60.0 + dt.second / 3600.0
    value = profile.energy_baseline + profile.energy_amplitude / 2.0 * math.cos(
        2 * math.pi * (hour - profile.energy_peak_hour) / 24.0
    )
    gap = (hour - profile.energy_dip_hour + 12.0) % 24.0 - 12.0
    value -= profile.energy_dip * math.exp(-((gap / 1.5) ** 2))
    return max(0.0, min(1.0, value))


def energy_word(value: float) -> str:
    if value >= 0.75:
        return "très haute"
    if value >= 0.55:
        return "bonne"
    if value >= 0.35:
        return "moyenne"
    if value >= 0.2:
        return "basse"
    return "très basse"


DAYS_FR = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
MONTHS_FR = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
             "novembre", "décembre")


def date_fr(dt: date) -> str:
    """« lundi 28 septembre 2026 »."""
    return f"{day_fr(dt)} {dt.year}"


def day_fr(dt: date) -> str:
    """« lundi 28 septembre » (sans l'année, comme on le dit)."""
    return f"{DAYS_FR[dt.weekday()]} {'1er' if dt.day == 1 else dt.day} {MONTHS_FR[dt.month - 1]}"


def energy_feel(value: float) -> str:
    """Ce que son énergie lui fait, en mots (jamais un nombre) ; vide quand il
    n'y a rien à en dire."""
    if value >= 0.7:
        return "tu as la pêche"
    if value >= 0.5:
        return "tu es en forme"
    if value >= 0.35:
        return ""
    if value >= 0.2:
        return "tu es fatiguée"
    return "tu es épuisée"


def describe(dt: datetime, profile: Profile = DEFAULT, level: float | None = None) -> str:
    """« Nous sommes lundi 28 septembre 2026, il est 23h23 — c'est la nuit, et
    tu es épuisée. La nuit, tu es souvent plus rêveuse. » Ni pourcentage ni
    jargon : la date, l'heure, le moment, ce qu'elle ressent, une tendance."""
    phase = phase_of(dt, profile)
    feel = energy_feel(energy(dt, profile) if level is None else level)
    moment = f"c'est {MOMENT_FR[phase]}" + (f", et {feel}" if feel else "")
    return f"Nous sommes {date_fr(dt)}, il est {dt.hour}h{dt.minute:02d} — {moment}. {_TENDENCY_FR[phase]}"
