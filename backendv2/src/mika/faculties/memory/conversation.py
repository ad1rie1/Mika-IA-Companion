"""Ce que le modèle voit d'une conversation qu'il relit (la consolidation, côté modèle).

**Une conversation par appel** : un fil privé avec une personne, ou un salon
(un groupe, tout le monde y lit tout). Chaque personne y porte un **jeton**
unique (« Alice [P1] ») : deux Alice ne se confondent jamais, et le modèle
désigne les gens de la conversation par leur jeton.

Le message rendu (``render``) : la date et le calendrier, qui parle, ce qui
est déjà su, puis les messages, avec leurs pièces jointes. Comment un nom que
le modèle écrit redevient une personne : ``speakers.py`` ; la consigne, l'outil
et ce qu'on attend en retour : ``extraction.py``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from mika.ports.preprocess import inert
from mika.vocab import affect as A
from mika.vocab.circadian import day_fr
from mika.vocab.people import fold
from mika.vocab.phrasebook import family, phrase


@dataclass(frozen=True, slots=True)
class Speaker:
    token: str  # « P1 »
    person: str  # la clé de personne
    name: str

    @property
    def label(self) -> str:
        return f"{self.name} [{self.token}]"


@dataclass(frozen=True, slots=True)
class Piece:
    """Une pièce jointe d'un message, telle que la relecture la voit (ADR 0106) : son repère (« #12.1 » : la première
    pièce du message #12), son nom, sa sorte, la clé de ses octets."""

    token: str
    name: str
    kind: str
    file: str


@dataclass(frozen=True, slots=True)
class Line:
    seq: int
    at: int
    speaker: str  # le libellé affiché (« Alice [P1] »), ou son nom à elle
    text: str
    person: str | None = None  # la clé de personne de qui parle (``None`` : elle)
    aside: bool = False  # dans un salon, pas adressé à elle
    lie: bool = False  # une de ses répliques qu'elle a marquée mensonge : elle ne dit pas le vrai
    #: une de ses répliques qui racontait sans nom ce qu'elle sait de quelqu'un (ADR 0091) : son texte ne se relit pas
    veiled: bool = False
    #: un échange avec un service dont rien ne se garde (ADR 0128) — sa réplique, et la demande qu'elle suivait : son
    #: texte ne se relit pas
    unkept: bool = False
    #: ce que vaut ce qu'elle a lu pour cet échange (ADR 0128) : ce qu'on en tire ne se dit pas en dessous
    floor: int = 0
    #: les pièces jointes que porte le message (ADR 0106)
    pieces: tuple[Piece, ...] = ()
    #: une de ses répliques : ce qu'elle a déclaré ressentir en l'écrivant (sa balise, ses facettes) — la relecture en
    #: part pour juger ce qu'elle-même ressent de ce qui s'est dit (ADR 0107)
    felt: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True, slots=True)
class Conversation:
    """Un fil privé (``room`` vide, une personne) ou un salon — ou une conversation reçue ailleurs, qu'on lui montre
    (ADR 0120) : ``relayed`` est alors la personne qui l'a reçue, et ``heading`` dit à la relecture ce que c'est."""

    key: str
    speakers: tuple[Speaker, ...]
    lines: tuple[Line, ...]
    room: str | None = None
    relayed: str = ""
    heading: str = ""

    @property
    def persons(self) -> tuple[str, ...]:
        return tuple(sorted({s.person for s in self.speakers}))

    @property
    def seqs(self) -> tuple[int, ...]:
        return tuple(ln.seq for ln in self.lines)

    def author(self, seq: int) -> str | None:
        return next((ln.person for ln in self.lines if ln.seq == seq), None)


#: Le calendrier montré à la relecture : la semaine d'avant les messages, et les deux semaines qui viennent (au plus
#: tant de jours, des plus récents) — « lundi » se lit « lundi 13 octobre », pas au jugé (ADR 0099).
CALENDAR_BEFORE, CALENDAR_AFTER, CALENDAR_MAX = 7, 14, 35


def calendar(first: date, today: date) -> str:
    """« lundi 5 octobre, mardi 6 octobre, … » : chaque jour, de la semaine qui précède le premier message aux deux
    semaines qui viennent — pour qu'un jour nommé se situe sans calcul (« on se voit lundi », écrit un vendredi)."""
    start = min(first, today) - timedelta(days=CALENDAR_BEFORE)
    end = today + timedelta(days=CALENDAR_AFTER)
    start = max(start, end - timedelta(days=CALENDAR_MAX - 1))
    return ", ".join(day_fr(start + timedelta(days=i)) for i in range((end - start).days + 1))


def render(conv: Conversation, *, now: datetime, beliefs: Sequence[tuple[int, str]],
           promises: Sequence[tuple[int, str, str]], situations: Sequence[tuple[int, str, str]] = (),
           moments: Sequence[tuple[int, str, str]] = (), ended: Sequence[tuple[int, str, str]] = (),
           passed: Sequence[tuple[int, str, str]] = ()) -> str:
    """Le message d'une conversation : la date, qui parle, ce qui est déjà
    su, les promesses en cours, les situations en cours, celles finies depuis
    peu (qui peuvent revenir) et les moments à venir de ses personnes, puis
    les messages (avec la date dès qu'elle change)."""
    out = [phrase("memory.extraction.render.today", day=day_fr(now.date()), year=now.year, hour=f"{now:%H}",
                  minute=f"{now:%M}")]
    first = datetime.fromtimestamp(conv.lines[0].at / 1e6, now.tzinfo).date() if conv.lines else now.date()
    out.append(phrase("memory.extraction.render.calendar", days=calendar(first, now.date())))
    who = ", ".join(s.label for s in conv.speakers)
    if conv.heading:
        out.append(conv.heading)
    elif conv.room:
        out.append(phrase("memory.extraction.render.room", who=who))
    else:
        out.append(phrase("memory.extraction.render.private", who=who))
    if beliefs:
        out += ["", phrase("memory.extraction.render.beliefs")] + [f"[#{i}] {text}" for i, text in beliefs]
    if promises:
        out += ["", phrase("memory.extraction.render.promises")] + [
            phrase("memory.extraction.render.promise", id=i, whom=whom, text=text) for i, whom, text in promises]
    if situations:
        out += ["", phrase("memory.extraction.render.situations")] + [
            f"[#{i}] ({whom}) {text}" for i, whom, text in situations]
    if ended:
        out += ["", phrase("memory.extraction.render.ended")] + [f"[#{i}] ({whom}) {text}" for i, whom, text in ended]
    if moments:
        out += ["", phrase("memory.extraction.render.moments")] + [
            f"[#{i}] ({whom}) {text}" for i, whom, text in moments]
    if passed:
        out += ["", phrase("memory.extraction.render.passed")] + [
            f"[#{i}] ({whom}) {text}" for i, whom, text in passed]
    out += ["", phrase("memory.extraction.render.messages")]
    day: date | None = None
    for ln in conv.lines:
        moment = datetime.fromtimestamp(ln.at / 1e6, now.tzinfo)
        if moment.date() != day:
            day = moment.date()
            out.append(phrase("memory.extraction.render.day", day=day_fr(day)))
        aside = phrase("memory.extraction.render.aside") if ln.aside else ""
        lie = phrase("memory.extraction.render.lie") if ln.lie else ""
        text = (phrase("memory.extraction.render.veiled_said") if ln.veiled
                else phrase("memory.extraction.render.unkept") if ln.unkept else ln.text)
        felt = [(e, x) for e, x in ln.felt if e != A.Emotion.NEUTRAL.value] if not ln.veiled and not ln.unkept else []
        felt_said = phrase("memory.extraction.render.felt", what=facet_words(felt)) if felt else ""
        out.append(f"[#{ln.seq}] {moment:%H:%M} {ln.speaker}{aside} : {text}{lie}{felt_said}"
                   f"{'' if ln.unkept else pieces_words(ln.pieces)}")
    return "\n".join(out)


#: une facette sous cette intensité se dit « un peu » (« colère et un peu de dégoût »)
LIGHT_FACET = 0.5


def facet_words(felt: Sequence[tuple[str, float]], *, lead: bool = True) -> str:
    """Les facettes d'un ressenti en mots, jamais un nombre : « colère », « colère et un peu de dégoût »,
    « amusement, tendresse et joie » (ADR 0083). ``lead`` : la première se dit franchement, quelle que soit son
    intensité (c'est la plus forte)."""
    words = [A.NOUN[A.Emotion(e)] if (lead and i == 0) or x >= LIGHT_FACET else
             phrase("memory.recall.felt.light", what=A.partitive(A.Emotion(e))) for i, (e, x) in enumerate(felt)]
    if len(words) < 2:
        return "".join(words)
    return phrase("memory.recall.felt.and", first=", ".join(words[:-1]), last=words[-1])


def pieces_words(pieces: Sequence[Piece]) -> str:
    """Les repères des pièces d'un message, après son texte (rien sans pièce)."""
    if not pieces:
        return ""
    kinds = family("memory.extraction.render.piece_kinds")
    return phrase("memory.extraction.render.pieces", pieces=", ".join(
        phrase("memory.extraction.render.piece", ref=p.token, name=inert(p.name, 80), kind=kinds.get(p.kind, p.kind))
        for p in pieces))


PIECE_TOKEN = re.compile(r"#?\s*(\d{1,12})\s*[./]\s*(\d{1,2})")


def pieces_of(named: Sequence[str], cited: Sequence[int], lines: Mapping[int, Line]) -> tuple[str, ...]:
    """Les pièces (leurs clés) d'où vient un élément — **en plus** de ses messages : celles que la relecture désigne
    (un repère « #12.1 », ou le nom de la pièce s'il n'en désigne qu'une), parmi les pièces de la conversation ; sans
    désignation, la seule pièce des messages qu'il cite, quand ils n'en portent qu'une (avec plusieurs, rien ne se
    devine). Une clé inventée ne relie rien."""
    every = {p.token: p for ln in lines.values() for p in ln.pieces}
    by_name: dict[str, list[Piece]] = {}
    for p in every.values():
        for key in {fold(p.name), fold(p.name).rpartition(".")[0]} - {""}:
            by_name.setdefault(key, []).append(p)
    out: list[str] = []
    for raw in named:
        text = str(raw).strip().strip("[]«»\"' ")
        m = PIECE_TOKEN.fullmatch(text)
        token = f"#{m.group(1)}.{m.group(2)}" if m else ""
        if token in every:
            out.append(every[token].file)
            continue
        same = by_name.get(fold(text), [])
        if len({p.file for p in same}) == 1:
            out.append(same[0].file)
    if not out and not named:
        carried = {p.file for s in cited if s in lines for p in lines[s].pieces}
        if len(carried) == 1:
            out = list(carried)
    return tuple(dict.fromkeys(out))
