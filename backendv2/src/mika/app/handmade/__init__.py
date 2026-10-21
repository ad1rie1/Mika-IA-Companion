"""Ce que partagent les pages dessinées à la main de la console (ADR 0121) : « En ce moment » (``now.py``), une
personne, la vue d'ensemble de sa fiche (``person/``).

Une telle page croise les facultés là où une vue déclarée n'en montre qu'une : elle lit leurs faits au même
instant, le journal, les textes et les séries de la journée, par un ``Look`` ; chacune de ses parties se lit à part
(``read_parts``) — une lecture qui échoue tait sa carte, jamais la page. Elles partagent leurs gabarits
(``inspector/templates/handmade/``) et leurs feuilles (``inspector/static/handmade/``, classes ``now-…``) : une même
façon de dire une humeur, une jauge, une personne, un fil.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from mika.contracts import affect as affect_c
from mika.contracts import attention as attention_c
from mika.contracts import identity as identity_c
from mika.contracts import presence as presence_c
from mika.contracts import social as social_c
from mika.faculties.affect import AFFECT
from mika.faculties.social.inspect import CLOSENESS_FR
from mika.inspector.ui import PREFIX, UI
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.frame import Frame
from mika.kernel.inspect import pct_fr
from mika.runtime.boundary import Failed, call
from mika.vocab import affect as A
from mika.vocab.people import is_identifiable

#: l'adresse courte d'une personne : elle mène à sa fiche (``person/``)
PERSON_BASE = f"{PREFIX}/personne"
#: les mesures d'une série sur une journée (une toutes les dix minutes)
POINTS = 144
#: un texte cité (une pensée, un rêve, un souvenir) : au plus tant de lettres
EXCERPT = 220
FORGOTTEN = "(oublié)"
#: les issues d'un épisode qui disent un échec
FAILED = frozenset({"failed", "timeout"})

WEEKDAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
MONTHS = ("janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc.")


# ── les mots du temps ──


def ago(now: int, at: int) -> str:
    """« à l'instant », « il y a 12 min », « il y a 3 h », « il y a 2 j »."""
    gap = max(0, now - at)
    if gap < MINUTE:
        return "à l'instant"
    if gap < HOUR:
        return f"il y a {gap // MINUTE} min"
    if gap < DAY:
        return f"il y a {gap // HOUR} h"
    return f"il y a {gap // DAY} j"


def span(us: int) -> str:
    """Une durée lisible : « 40 min », « 7 h 40 », « 2 j 3 h »."""
    us = max(0, us)
    if us < HOUR:
        return f"{max(1, us // MINUTE)} min"
    if us < DAY:
        hours, minutes = divmod(us // MINUTE, 60)
        return f"{hours} h {minutes:02d}" if minutes else f"{hours} h"
    days, rest = divmod(us, DAY)
    return f"{days} j {rest // HOUR} h" if rest >= HOUR else f"{days} j"


def said(content: Any) -> str | None:
    """Le texte d'un contenu relu au journal (``None`` : oublié)."""
    return getattr(content, "text", None)


def excerpt(text: str | None, limit: int = EXCERPT) -> str:
    if text is None:
        return FORGOTTEN
    clean = " ".join(text.split())
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip() + "…"


def emotion(name: str | None) -> A.Emotion:
    """Une émotion par son nom ; un nom qui n'est pas l'une des 29 : le neutre."""
    return A.emotion_of(name) or A.Emotion.NEUTRAL


def unit(value: float) -> float:
    """Une part bornée à [0, 1], en pourcentage d'une jauge (``w``)."""
    return round(100 * max(0.0, min(1.0, value)), 1)


def affect_params(frame: Frame) -> Any:
    got = frame.env.params_of("affect", frame.root)
    return got if got is not None else AFFECT.default_params()


def person_href(person: str) -> str:
    """La fiche d'une personne, ouverte sur sa vue d'ensemble (``person/``) ; une adresse qui n'est pas une
    personne n'en a pas."""
    return f"{PREFIX}/fiche/person/{quote(person, safe='')}" if is_identifiable(person) else ""


@dataclass(slots=True)
class Look:
    """Ce que chaque partie d'une page lit : l'instant, sa fenêtre, le journal, les textes, les séries (relues une
    fois par rendu), les noms."""

    ui: UI
    frame: Frame
    now: int
    since: int
    events: Callable[..., list[Any]]
    content: Callable[[Sequence[str]], dict[str, str]]
    sampler: Callable[..., list[tuple[int, float]]] | None
    _series: dict[str, list[tuple[int, float]]] = field(default_factory=dict)

    @classmethod
    def of(cls, ui: UI, window: int) -> Look:
        """Le regard d'un rendu : l'état du noyau à cet instant, sur ``window`` en arrière."""
        frame = ui.kernel.mind.frame()
        return cls(ui, frame, frame.now, frame.now - window, ui.inspection.context().events,
                   ui.kernel.ports["store"].content, ui.sampler)

    def series(self, key: str) -> list[tuple[int, float]]:
        if key not in self._series:
            got = call(self.sampler, key, self.since, self.now, POINTS, label=f"série {key}") \
                if self.sampler is not None else []
            self._series[key] = [] if isinstance(got, Failed) else sorted(got)
        return self._series[key]

    def texts(self, refs: Sequence[str]) -> dict[str, str]:
        refs = [r for r in refs if r]
        got = call(self.content, refs, label="textes") if refs else {}
        return {} if isinstance(got, Failed) else got

    def recent(self, types: Sequence[Any], limit: int, *, where: tuple[str, Any] | None = None) -> list[Any]:
        """Les événements de ces types depuis le début de la fenêtre, du plus ancien au plus récent."""
        got = call(lambda: self.events(list(types), limit, where=where), label="journal")
        return [] if isinstance(got, Failed) else sorted((e for e in got if e.at >= self.since), key=lambda e: e.at)

    # ── les noms ──
    def name(self, person: str) -> str:
        return self.ui.names.name_of(person) or person

    def person_of(self, handle: str) -> str:
        return self.ui.names.person_of(handle)

    @staticmethod
    def href(person: str) -> str:
        return person_href(person)

    def who(self, people: Sequence[str]) -> list[dict[str, str]]:
        return [{"name": self.name(p), "href": self.href(p)} for p in dict.fromkeys(people) if p]

    # ── l'heure ──
    def hm(self, at: int) -> str:
        return self.frame.local(at).strftime("%H:%M")

    def ago(self, at: int) -> str:
        return ago(self.now, at)

    def date(self, at: int) -> str:
        """Un jour passé, court : « mardi 14 oct. »."""
        local = self.frame.local(at)
        return f"{WEEKDAYS[local.weekday()]} {local.day} {MONTHS[local.month - 1]}"

    def day(self, at: int, *, all_day: bool = False) -> str:
        """Un jour proche, dit simplement : « aujourd'hui à 14:00 », « demain », « jeudi », « 12 oct. »."""
        local, today = self.frame.local(at), self.frame.local(self.now)
        days = (local.date() - today.date()).days
        hour = "" if all_day else f" à {local.strftime('%H:%M')}"
        if days == 0:
            return f"aujourd'hui{hour}"
        if days == 1:
            return f"demain{hour}"
        if days == -1:
            return f"hier{hour}"
        if 1 < days < 7:
            return WEEKDAYS[local.weekday()] + hour
        return f"{local.day} {MONTHS[local.month - 1]}"


def read_parts(look: Look, parts: Sequence[tuple[str, Callable[[Look], Any]]], page: str) -> dict[str, Any]:
    """Chaque partie lue à part ; une partie dont la lecture a échoué vaut ``None`` (sa carte le dit)."""
    out: dict[str, Any] = {}
    for key, part in parts:
        got = call(part, look, label=f"{page} · {key}")
        out[key] = None if isinstance(got, Failed) else got
    return out


# ── une personne en une carte ──

#: son dernier message sans réponse depuis moins de tant : une conversation en cours, pas une attente
#: (``agency.live_wait_us``, ADR 0115)
LIVE_WAIT = 15 * MINUTE


def presences(look: Look) -> dict[str, dict[str, Any]]:
    """Qui est là, par personne : depuis quand (la plus ancienne de ses connexions) et si elle écrit."""
    frame = look.frame
    online: dict[str, dict[str, Any]] = {}
    for handle in frame.get(presence_c.PRESENT) or ():
        person = look.person_of(handle)
        if not is_identifiable(person):
            continue
        seen = online.setdefault(person, {"since": 0, "composing": False})
        since = frame.get(presence_c.SINCE(handle)) or 0
        seen["since"] = min(seen["since"] or since, since)
        seen["composing"] = seen["composing"] or bool(frame.get(presence_c.COMPOSING(handle)))
    return online


def person_card(look: Look, person: str, here: dict[str, Any] | None) -> dict[str, Any]:
    """Une personne en une carte, pour elle : son nom, ce qu'elle est pour elle, ce qu'elle ressent envers elle,
    l'attachement, et ce qui se passe entre elles en mots (en ligne, une réponse attendue, un silence, une rancune).
    ``here`` : sa présence (``presences``), ou ``None``."""
    frame, now = look.frame, look.now
    closeness = frame.get(social_c.CLOSENESS(person))
    stance = frame.get(affect_c.STANCE(person))
    contact = frame.get(social_c.CONTACT(person))
    waiting = frame.get(attention_c.AWAITING(person))
    hostility = frame.get(affect_c.HOSTILITY(person))
    felt = None
    if not stance.at_rest and stance.felt_intensity >= 0.1 and stance.felt is not A.Emotion.NEUTRAL:
        felt = {"emotion": stance.felt.value, "word": A.FR[stance.felt], "how": A.intensity_word(stance.felt_intensity)}
    notes: list[dict[str, str]] = []
    if here is not None and here["composing"]:
        notes.append({"text": "écrit…", "tone": "live"})
    elif here is not None:
        notes.append({"text": f"en ligne depuis {span(now - here['since'])}" if here["since"] else "en ligne",
                      "tone": "ok"})
    if waiting.unanswered and waiting.last_out and now - waiting.last_out < LIVE_WAIT:
        notes.append({"text": "en pleine conversation", "tone": "ok"})
    elif waiting.unanswered and waiting.last_out:
        many = f" · {waiting.initiatives} messages d'elle" if waiting.initiatives > 1 else ""
        notes.append({"text": f"attend sa réponse depuis {span(now - waiting.last_out)}{many}", "tone": "warn"})
    if contact.last_in:
        notes.append({"text": f"lui a écrit {look.ago(contact.last_in)}", "tone": ""})
    if here is None and contact.silence_ratio >= 1.5:
        notes.append({"text": "silence plus long que d'habitude", "tone": "warn"})
    if hostility >= 0.3:
        notes.append({"text": "elle lui en veut", "tone": "danger"})
    if stance.withdrawn_until > now:
        notes.append({"text": f"elle s'est refermée jusqu'à {look.hm(stance.withdrawn_until)}", "tone": "danger"})
    name = look.name(person)
    return {
        "name": name, "initial": (name[:1] or "?").upper(), "href": look.href(person),
        "closeness": CLOSENESS_FR.get(closeness, closeness), "close": closeness in (social_c.FRIEND, social_c.CLOSE),
        "owner": bool(frame.get(identity_c.IS_OWNER(person))),
        "felt": felt, "bond": pct_fr(stance.bond), "bond_w": round(100 * max(0.0, min(1.0, stance.bond)), 1),
        "online": here is not None, "composing": bool(here and here["composing"]),
        "notes": notes, "last_in": contact.last_in,
    }
