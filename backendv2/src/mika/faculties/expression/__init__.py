"""``expression`` : comment ce qu'elle ressent sort d'elle.

- l'analyse de la balise ``[EMOTION:nom:intensité]`` qu'elle écrit en fin de
  réponse (retirée du texte, gardée en annotation de l'énoncé), et le fait
  qu'elle ait posé une question (on en attend la réponse) ;
- la consigne de style (parler comme on parle, une échelle d'intensité, ce
  qu'est le bloc d'état interne : sa tête à elle, jamais citée) ;
- le murmure : parfois, avant d'écrire à quelqu'un qui la regarde, une
  pensée à mi-voix — et parfois elle se ravise ;
- la livraison : un énoncé commité part vers les transports par la file de
  sortie, avec l'émotion à montrer et la voix à prendre.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from mika.contracts import affect as affect_c
from mika.contracts import agency as agency_c
from mika.contracts import attention as attention_c
from mika.contracts import body as body_c
from mika.contracts import expression as c
from mika.contracts import identity as identity_c
from mika.contracts import needs as needs_c
from mika.contracts import others as others_c
from mika.contracts import presence as presence_c
from mika.contracts import runtime as rt
from mika.contracts import self_ as self_c
from mika.contracts import social as social_c
from mika.contracts import transcript as transcript_c
from mika.kernel.clock import HOUR, MINUTE
from mika.kernel.codec import h64
from mika.kernel.episode import Prelude
from mika.kernel.faculty import Faculty, Zone
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.prompt import CONTEXT_FOOTER, CONTEXT_HEADER, LAST, unlabel
from mika.kernel.state import FrozenDict
from mika.ports.delivery import Delivery, EmotionView
from mika.vocab import affect as A
from mika.vocab import flows, reading, voice
from mika.vocab.affect import Declared, Emotion, parse_tag
from mika.vocab.days import when_fr
from mika.vocab.episodes import CONVERSATIONAL, Kind, Tag
from mika.vocab.people import is_internal
from mika.vocab.phrasebook import family, phrase
from mika.vocab.words import STOPWORDS, elided, fold, stems


class ExpressionParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    murmur_chance: Annotated[float, Knob(
        label="Murmure : une fois sur", group="Le murmure", lo=0, hi=1, step=0.05,
        help="La probabilité qu'une initiative vers quelqu'un qui la regarde soit précédée d'une pensée à mi-voix "
             "(tirée du hasard de l'épisode) : souvent, pas toujours.")] = 0.35
    murmur_charged_chance: Annotated[float, Knob(
        label="Murmure quand ça la travaille", group="Le murmure", lo=0, hi=1, step=0.05,
        help="La même probabilité quand c'est une humeur qui déborde, une inquiétude ou une peine qui la "
             "pousse : on se parle plus à soi-même quand quelque chose pèse.")] = 0.6
    murmur_adrift: Annotated[float, Knob(
        label="Murmure sans suite", group="Le murmure", lo=0, hi=1, step=0.05,
        help="Parmi les murmures, la part où elle se ravise : elle y pense, puis n'écrit pas (l'initiative ne "
             "suit pas).")] = 0.2
    murmur_spacing_us: Annotated[int, Knob(
        label="Murmures espacés d'au moins", group="Le murmure", lo=5 * MINUTE, hi=12 * HOUR,
        help="Pas deux murmures plus rapprochés : une voix intérieure qui commente tout lasse.")] = HOUR
    opening_gap_us: Annotated[int, Knob(
        label="Une conversation commence après un silence de", group="Ce qu'elle se répète", lo=30 * MINUTE,
        hi=48 * HOUR,
        help="Son premier message après un tel silence (qu'elle vienne d'elle-même ou qu'elle réponde) est une entrée "
             "en matière : comparée aux précédentes avec la même personne, pour qu'elle ne commence pas chaque "
             "retrouvaille par la même formule.")] = 3 * HOUR


@dataclass(frozen=True, slots=True)
class ExpressionState:
    #: les murmures récents : corrélation de l'épisode → l'adresse de la personne à qui elle allait écrire (le
    #: murmure se montre sur ses écrans à elle, jamais à tout le monde)
    murmurs: FrozenDict[str, str] = field(default_factory=FrozenDict)


EXPRESSION = Faculty("expression", state=ExpressionState, init=lambda p: ExpressionState(), params=ExpressionParams,
                     state_version=2)

#: au plus tant de murmures retenus (le temps que leur livraison parte)
MURMURS_KEPT = 8


def params(p: ExpressionParams | None) -> ExpressionParams:
    return p if p is not None else ExpressionParams()


#: sa marque d'un mensonge, où qu'elle l'écrive, fermée ou non (une marque coupée en fin de réponse ne doit pas
#: partir : ce qu'elle y écrit peut dire ce qu'elle cache)
LIE_MARK = re.compile(r"\[\s*(?:MENSONGE|MENTI|LIE)\b\s*:?([^\]]*)(?:\]|$)", re.IGNORECASE)
_SENTENCE = re.compile(r"[^.!?…]+[.!?…]*")
#: une ligne qui ouvre ses balises de fin (« [EMOTION: … », « [EN_FACE: … », « [MENSONGE: … »)
_TRAILER = re.compile(r"^[ \t]*\[\s*(?:EMOTION|EN_FACE|MENSONGE|MENTI|LIE)\b", re.IGNORECASE | re.MULTILINE)
_BRACKETS = re.compile(r"\[[^\]\n]*\]?")


def closing(text: str) -> str:
    """Ce qu'elle dit, puis ses balises de fin : passé la première ligne de balises qui suit sa parole, seules les
    balises comptent. Un texte écrit après n'est pas à dire (2026-10-14 : « Correction de balise : [EN_FACE: …] »
    arrivait à la personne). Une balise en tête de réponse ne coupe rien."""
    m = next((m for m in _TRAILER.finditer(text) if text[:m.start()].strip()), None)
    if m is None:
        return text
    return text[:m.start()] + " ".join(_BRACKETS.findall(text[m.start():]))


def lied(text: str, mark: str) -> tuple[int, int] | None:
    """Le passage faux de ce qu'elle a dit (``début``, ``fin``) : la phrase qui partage le plus de mots avec sa
    marque, pourvu qu'elle en porte au moins la moitié ; toute la réponse quand la marque ne cite rien
    (« [mensonge] »). ``None`` quand la marque cite une phrase que cette réponse ne contient pas — celle d'un message
    précédent, qu'elle croit après coup avoir inventée (ADR 0108) : ce n'est pas un mensonge de cette réponse, rien
    n'est désigné. La marque elle-même n'est jamais gardée."""
    wanted = stems(mark)
    if not wanted:
        return 0, len(text)
    best, span = 0, None
    for m in _SENTENCE.finditer(text):
        shared = len(stems(m.group()) & wanted)
        if shared > best and m.group().strip():
            best, span = shared, (m.start() + len(m.group()) - len(m.group().lstrip()), m.end())
    return span if 2 * best >= len(wanted) else None


def parse(text: str, speaker: str = "") -> tuple[str, dict[str, str]]:
    """Le texte sans balise, ce qu'elle a déclaré, ce qu'elle a lu de la personne (sa balise ``[EN_FACE: …]``,
    retirée, ADR 0093), si elle a posé une question, et si elle a menti (sa marque ``[MENSONGE: …]``, retirée : seul
    le passage faux est désigné). ``speaker`` : son nom (celui de sa persona) — un « Nom : » recopié en tête de
    réponse se retire."""
    text = closing(text or "")
    marks = [m.group(1) or "" for m in LIE_MARK.finditer(text)]
    unread, their = reading.read(LIE_MARK.sub("", text))
    tag = parse_tag(unread, speaker)
    annotations: dict[str, str] = {}
    if their is not None:
        annotations[c.READING_ANNOTATION] = their.encode()
    span = lied(tag.text, " ".join(marks)) if marks and tag.text.strip() else None
    if span is not None:
        annotations[c.LIE_ANNOTATION] = f"{span[0]}:{span[1]}"
    if tag.declared is not None:
        annotations[c.EMOTION_ANNOTATION] = tag.declared.encode()
    elif tag.unknown:
        annotations[c.UNKNOWN_EMOTION_ANNOTATION] = tag.unknown[:40]
    if "?" in tag.text:
        annotations[c.QUESTION_ANNOTATION] = "1"
    return tag.text, annotations


def reannotate(draft: str, annotations: Mapping[str, str], text: str) -> dict[str, str]:
    """Les annotations de sa réponse récrite par l'autrice (``text``, ADR 0114) : ce qu'elle ressent, ce qu'elle a lu
    de la personne et le fait d'avoir menti restent ceux du premier jet (``draft``) ; ce qui décrit la forme du texte se
    recalcule sur le message envoyé — une question qu'il pose (le premier jet finissait sur une question, le message
    envoyé non), et le passage faux, retrouvé dans le texte récrit (le texte entier quand il ne s'y retrouve pas : elle
    a menti quand même)."""
    out = {k: v for k, v in annotations.items() if k not in (c.QUESTION_ANNOTATION, c.LIE_ANNOTATION)}
    if "?" in text:
        out[c.QUESTION_ANNOTATION] = "1"
    lie = annotations.get(c.LIE_ANNOTATION)
    if lie is not None:
        start, _, end = lie.partition(":")
        passage = draft[int(start):int(end)] if start.isdigit() and end.isdigit() else ""
        span = (lied(text, passage) if passage.strip() else None) or (0, len(text))
        out[c.LIE_ANNOTATION] = f"{span[0]}:{span[1]}"
    return out


def style() -> str:
    """La consigne de style (``expression.style`` dans sa voix) : parler comme on parle, une échelle d'intensité, ce
    qu'est le bloc d'état interne — sa tête à elle, jamais citée."""
    return phrase("expression.style", names=", ".join(e.value for e in Emotion), header=CONTEXT_HEADER,
                  footer=CONTEXT_FOOTER)


@EXPRESSION.section("style", zone=Zone.STABLE, episodes=CONVERSATIONAL, tags=[Tag.AFFECTIVE], trim_rank=100)
def _style(s: ExpressionState, frame: Frame, enrich: Any) -> str:
    return style()


def pro_style() -> str:
    """La consigne du mode pro (``expression.pro`` dans sa voix, ADR 0116), à la place de sa consigne de style (coupée
    avec ses sections affectives) : un travail, fait avec ses outils, rendu à l'écran en Markdown, sans jetons de voix
    ni balises — et ce qu'est le bloc d'état interne."""
    return phrase("expression.pro", header=CONTEXT_HEADER, footer=CONTEXT_FOOTER)


# ── Ce qu'elle se répète ──────────────────────────────────────────────────

#: ses derniers messages relus pour s'entendre se répéter
HABIT_WINDOW = 6
#: un message à partir duquel on parle longtemps (en caractères, à peu près quatre phrases)
LONG_MESSAGE = 320
_TOKEN = re.compile(r"\w+(?:'\w+)?")
GREETINGS = frozenset({"salut", "coucou", "hey", "bonjour", "bonsoir", "yo", "hello", "re", "hi", "yoo",
                       "heey", "heyy", "coucouu"})


def _tokens(text: str) -> list[tuple[str, str]]:
    """Les mots d'un message : tels qu'elle les a écrits (en minuscules), et leur clé sans accents."""
    return [(w, fold(w)) for w in _TOKEN.findall(A.strip_prosody(text).lower().replace("’", "'"))]


def _words(text: str) -> list[str]:
    return [key for _w, key in _tokens(text)]


def _opener(text: str) -> tuple[str, str]:
    """Les deux premiers mots d'un message : tels qu'elle les a écrits, et leur clé."""
    raw = " ".join(A.strip_prosody(text).split()[:2])
    return raw.strip(" ,;:!?."), " ".join(_words(raw)[:2])


def repeats(said: Sequence[tuple[int, str]], now: int, opened: Sequence[str] = ()) -> list[str]:
    """Ce qu'on entendrait se répéter dans ses derniers messages : une même ouverture (deux des trois derniers, ou
    trois des six derniers) et une même formule de quatre mots ou plus dans au moins trois messages. Une
    personne s'entend se répéter ; la consigne de style seule n'y suffit pas (sonde réelle du 2026-10-02 :
    « Adrien… Je t'entends dire que… » en tête de quatre réponses sur cinq)."""
    kept = [(at, t) for at, t in said if t and t.strip() and A.SILENCE_TOKEN not in t][-HABIT_WINDOW:]
    msgs = [t for _at, t in kept]
    out: list[str] = []
    # redire bonjour à quelqu'un qu'on vient de saluer (sa salutation, puis sa réponse au « salut » qui suit)
    if kept and now - kept[-1][0] < HOUR and (_words(kept[-1][1])[:1] or [""])[0] in GREETINGS:
        out.append(phrase("expression.habits.greeted"))
    openers = [_opener(t) for t in msgs]
    keys = [k for _raw, k in openers if len(k.split()) == 2]
    seen_opener = ""
    for raw, key in reversed(openers):
        if key and (keys[-3:].count(key) >= 2 or keys.count(key) >= 3):
            out.append(phrase("expression.habits.opener", opener=raw))
            seen_opener = key
            break
    grams: dict[tuple[str, ...], int] = {}
    shown: dict[tuple[str, ...], str] = {}
    for t in msgs:
        ws = _tokens(t)
        for i in range(len(ws) - 3):
            shown.setdefault(tuple(k for _w, k in ws[i:i + 4]), " ".join(w for w, _k in ws[i:i + 4]))
        for g in {tuple(k for _w, k in ws[i:i + 4]) for i in range(len(ws) - 3)}:
            grams[g] = grams.get(g, 0) + 1
    common = sorted((g for g, n in grams.items() if n >= 3 and sum(w not in STOPWORDS for w in g) >= 1),
                    key=lambda g: (-grams[g], g))
    for g in common:
        if seen_opener and " ".join(g).startswith(seen_opener):
            continue
        out.append(phrase("expression.habits.formula", formula=shown[g]))
        break
    # d'une conversation à l'autre : ses premiers mots quand vous vous retrouvez, qu'elle vienne ou qu'on vienne à elle
    # (sonde finale : « Yooo, Adrien ! » en tête de six initiatives, une par soir — le fil des six derniers messages
    # ne les voyait jamais deux fois ; et « Heeey Adrien ! » chaque soir où c'est lui qui écrit le premier)
    starts = [_opener(t) for t in opened if t and t.strip()][-3:]
    start_keys = [k for _raw, k in starts if len(k.split()) == 2]
    twice = next((k for k in reversed(start_keys) if start_keys.count(k) >= 2 and k != seen_opener), None)
    if twice is not None:
        raw = next(r for r, k in reversed(starts) if k == twice)
        out.append(phrase("expression.habits.reunion", opener=raw))
    # trois messages d'affilée qui posent des questions : un interrogatoire, pas une conversation (2026-10-14, avec
    # Sonnet : « un seul ou plusieurs ? », « tu les as essayés, ou… ? », « tu comptes y aller, ou… ? »)
    if len(msgs) >= 3 and all("?" in A.strip_prosody(t) for t in msgs[-3:]):
        out.append(phrase("expression.habits.questions"))
    # trois longs messages d'affilée : un monologue, pas une conversation (sonde : quatre à six phrases à chaque fois)
    if len(msgs) >= 3 and all(len(A.strip_prosody(t)) >= LONG_MESSAGE for t in msgs[-3:]):
        out.append(phrase("expression.habits.long"))
    return out


#: une phrase qui parle d'elle (« je », « j'ai », « moi », « mon »…)
_SELF = re.compile(r"\b(?:je|j['’]|moi|mon|ma|mes)\b", re.IGNORECASE)
_SENTENCES = re.compile(r"(?<=[.!?…])\s+")
#: au plus tant de ce qu'elle a dit d'elle, cité
SAID_OF_HERSELF_MAX = 200


#: au plus tant de ses messages de cette conversation relus pour ce qu'elle y a dit d'elle
SAID_OF_HERSELF_MESSAGES = 3


def said_of_herself(said: Sequence[tuple[int, str]], now: int) -> str | None:
    """Ce que ses derniers messages de cette conversation (la dernière heure, trois au plus, le plus récent d'abord)
    disaient d'elle — ses affirmations, pas ses questions : la personne les a lus. Le prompt lui rappelle à chaque tour
    ce qu'elle fait ; à « et toi ? », elle le redisait presque mot pour mot (2026-10-14 : « je dessine… une
    aquarelle », puis « je suis toujours à mon aquarelle » — rejoué six fois sur six ; citée, zéro sur huit). Au banc
    de conversation, elle redisait aussi ce qu'elle avait raconté trois messages plus tôt (« je traînais dans ma
    chambre sans but »)."""
    quotes: list[str] = []
    for at, text in reversed(said):
        if now - at > HOUR or len(quotes) >= SAID_OF_HERSELF_MESSAGES:
            break
        if not text or A.SILENCE_TOKEN in text:
            continue
        mine = [t.strip() for t in _SENTENCES.split(A.strip_prosody(text))
                if _SELF.search(t) and not t.strip().endswith("?")]
        if mine:
            quote = " ".join(mine[:2])
            quotes.append(quote if len(quote) <= SAID_OF_HERSELF_MAX
                          else quote[:SAID_OF_HERSELF_MAX - 1].rstrip() + "…")
    return " » ; « ".join(quotes) or None


@EXPRESSION.enricher("own_words", episodes=CONVERSATIONAL, deadline_ms=300)
async def _own_words(s: ExpressionState, frame: Frame, ports: Mapping[str, Any]) -> tuple[tuple[int, str], ...] | None:
    """Ses derniers messages à cette personne (ou dans ce salon), du plus ancien au plus récent."""
    store, ep = ports.get("store"), frame.episode
    if store is None or ep is None or not ep.target:
        return None
    t = transcript_c.thread_table()
    rows = store.query_mind(select(t.c.at, t.c.text).where(t.c.role == "assistant", *_where(t, ep))
                            .order_by(t.c.id.desc()).limit(HABIT_WINDOW))
    return tuple((int(r[0]), str(r[1] or "")) for r in reversed(rows))


def _where(t: Any, ep: Any) -> tuple[Any, ...]:
    """Le fil de cet épisode : son salon, ou le fil privé avec sa cible."""
    room = ep.attrs.get("room")
    return (t.c.room == room,) if room else (t.c.person == ep.target, t.c.room.is_(None))


#: au plus tant de messages du fil relus pour y retrouver ses entrées en matière (trois conversations, largement)
OPENINGS_SCAN = 500


@dataclass(frozen=True, slots=True)
class Openings:
    #: ses dernières entrées en matière (au plus trois), du plus ancien au plus récent
    said: tuple[str, ...] = ()
    #: la conversation en cours a commencé après un silence et elle n'y a encore rien dit : sa réponse l'ouvre
    opens: bool = False


@EXPRESSION.enricher("own_openings", episodes=CONVERSATIONAL, deadline_ms=300)
async def _own_openings(s: ExpressionState, frame: Frame, ports: Mapping[str, Any]) -> Openings | None:
    """Ses trois dernières entrées en matière avec cette personne (ou dans ce salon) : son premier message après un
    silence, qu'elle soit venue d'elle-même ou qu'elle réponde — comment elle commence quand vous vous retrouvez,
    d'une conversation à l'autre. Et si la conversation en cours attend encore son premier mot à elle."""
    store, ep = ports.get("store"), frame.episode
    if store is None or ep is None or not ep.target:
        return None
    gap = params(frame.env.params_of("expression", frame.root)).opening_gap_us
    t = transcript_c.thread_table()
    window = store.query_mind(select(t.c.id, t.c.at, t.c.role).where(*_where(t, ep))
                              .order_by(t.c.id.desc()).limit(OPENINGS_SCAN))
    # chaque silence d'au moins ``gap`` ouvre une conversation (numérotée dans l'ordre), le tout début du fil aussi
    # quand on l'a relu en entier ; sinon, ce qui précède le premier silence relu a commencé avant la fenêtre et ne
    # compte pas. De chaque conversation, son premier message à elle — aucun dans la dernière : elle n'y a encore
    # rien dit. Compté ici plutôt qu'en SQL (des fenêtres et une table dérivée sans nom : SQLite les prend, MariaDB
    # veut un nom à chaque table dérivée)
    whole = len(window) < OPENINGS_SCAN
    conv, prev = 0, None
    first: dict[int, int] = {}
    for mid, at, role in reversed(window):
        if (prev is None and whole) or (prev is not None and int(at) - prev >= gap):
            conv += 1
        prev = int(at)
        if conv > 0 and role == "assistant":
            first.setdefault(conv, int(mid))
    # les dernières conversations, de la plus récente à la plus ancienne : la dernière toujours, les autres si elle
    # y a parlé
    convs = [n for n in range(conv, 0, -1) if n in first or n == conv][:4]
    wanted = [first[n] for n in convs if n in first]
    texts = {int(i): str(x) for i, x in store.query_mind(select(t.c.id, t.c.text).where(t.c.id.in_(wanted)))} \
        if wanted else {}
    rows = [texts.get(first[n]) if n in first else None for n in convs]
    said = tuple(x for x in reversed(rows) if x is not None)[-3:]
    return Openings(said=said, opens=bool(rows) and rows[0] is None)


@EXPRESSION.enricher("last_heard", episodes=[Kind.REPLY], deadline_ms=300)
async def _last_heard(s: ExpressionState, frame: Frame, ports: Mapping[str, Any]) -> str | None:
    """Le message auquel elle répond."""
    store, ep = ports.get("store"), frame.episode
    reply_to = ep.attrs.get("reply_to") if ep is not None else None
    if store is None or reply_to is None:
        return None
    t = transcript_c.thread_table()
    rows = store.query_mind(select(t.c.text).where(t.c.id == reply_to))
    return str(rows[0][0] or "") if rows else None


#: une question qu'elle vient de poser attend encore sa réponse pendant ce temps
QUESTION_PENDING_US = 15 * MINUTE
_QUESTION = re.compile(r"[^.!?…\n]*\?")


def pending_question(said: Sequence[tuple[int, str]], heard: str, now: int) -> str | None:
    """La question qu'elle vient de poser, quand la personne n'a répondu qu'un bonjour (« re », « salut ») : elle
    ne la repose pas. Sonde réelle du 2026-10-03 : « comment s'est passé ton anniversaire hier ? », puis, à « re »,
    « comment s'est passé hier ? » — deux fois dans la semaine."""
    words = _words(heard)
    if not said or not words or len(words) > 3 or not all(w in GREETINGS for w in words):
        return None
    at, text = said[-1]
    if now - at > QUESTION_PENDING_US:
        return None
    asked = [q.strip() for q in _QUESTION.findall(A.strip_prosody(text)) if len(q.strip()) > 3]
    if not asked:
        return None
    q = asked[-1]
    return q if len(q) <= 90 else "…" + q[-89:]


# ── Sa réponse relue ──────────────────────────────────────────────────────
#
# Banc de conversation du 2026-10-14 (Sonnet, jugé par Opus) : malgré la consigne de style et « TA RÉPONSE », une
# réplique sur deux finissait par « ceci, ou cela ? », s'ouvrait par le même « Ah, » que les précédentes, ou redisait
# une phrase déjà dite. Ces tics se voient sur le brouillon même : relu, il est réécrit une fois (``pipeline``).

#: une question à options (« t'as trouvé quelque chose, ou t'es rentré bredouille ? ») — pas « … ou pas ? »
_OPTIONS = re.compile(r"\bou\b(?!\s+(?:pas|non|quoi|bien|alors)\b)", re.IGNORECASE)
#: on la corrige ou on la taquine (« nan celui qui défonce tout », « non c'est ma cousine », « merci maman ») …
_CORRECTED = re.compile(r"^\s*(?:non|nan|nope|mais non|pas du tout)\b|\bmaman\b|\btu te trompes\b|\bt'as tout faux\b"
                        r"|\bc'est pas (?:ça|ca)\b", re.IGNORECASE)
#: … et elle ouvre sur une excuse ou une justification (« ah pardon, j'avais tout faux ») : un réflexe d'assistante.
#: Banc de recherche du 2026-10-15 : une réponse sur quatre, dans ces cas-là, et aucune consigne ne l'enlève tout à
#: fait ; relue, elle rebondit (« ah ok, donc la lumière c'est surtout pour le style »). « désolée pour ton
#: grand-père » n'est pas une excuse : ni « désolée » seul, ni une excuse sans qu'on l'ait corrigée ne sont repris.
_SORRY = re.compile(r"\b(?:pardon|excuse-moi|je m'excuse|autant pour moi|au temps pour moi|j'(?:ai|avais) tout faux"
                    r"|je me suis (?:trompée|plantée))\b", re.IGNORECASE)
#: une excuse se lit dans ses premiers mots
_SORRY_WITHIN = 80
#: au moins tant de mots en commun avec l'un de ses derniers messages : une redite ; avec son portrait : une copie
_AGAIN, _COPIED = 5, 6
#: à un message de tant de caractères au plus, une réponse de plus de ``_LONG_ANSWER`` (ou en plusieurs paragraphes)
#: est hors de mesure
_SHORT_HEARD, _LONG_ANSWER = 60, 280


def _plain(text: str) -> str:
    """Sa parole sans balise ni jeton de voix."""
    return " ".join(A.strip_prosody(_BRACKETS.sub(" ", text or "")).split())


#: une ligne vide : en chat, ce qui suit part dans une autre bulle (les clients découpent, ADR 0112)
_BUBBLES = re.compile(r"\n\s*\n")


def _bubbles(text: str) -> str:
    """Sa parole sans balise ni jeton de voix, ses bulles gardées (séparées par une ligne vide)."""
    return "\n\n".join(p for p in (_plain(b) for b in _BUBBLES.split(text or "")) if p)


def review(draft: str, mine: Sequence[str], heard: str = "", portrait: str = "") -> str | None:
    """Ce qu'elle remarquerait en se relisant, avant d'envoyer : une question à options, plusieurs questions, une
    question encore après deux messages qui en posaient, la même ouverture que deux de ses trois derniers messages, ses premiers mots qui redisent ceux de la personne, une
    suite de mots déjà dite dans un de ses derniers messages, ou recopiée de son portrait (``portrait`` : sa persona
    telle que le modèle l'a lue — un exemple de sa voix repris mot pour mot, banc du 2026-10-14). ``None`` : rien à
    reprendre."""
    text = _plain(draft)
    if not text:
        return None
    found: list[str] = []
    questions = [q.strip() for q in _QUESTION.findall(text) if len(q.strip()) > 3]
    choice = next((q for q in questions if _OPTIONS.search(q)), None)
    if choice is not None:
        found.append(phrase("expression.review.choice", question=choice))
    if len(questions) >= 2:
        found.append(phrase("expression.review.questions"))
    before = [_plain(m) for m in mine if _plain(m)][-3:]
    # une question à chaque message, la troisième d'affilée : un interrogatoire. Aucune consigne ne le retient
    # (ablation du 2026-10-15 : 88 à 100 % de ses réponses finissent sur une question, quoi qu'on retire ou ajoute)
    if questions and len(before) >= 2 and all(_QUESTION.search(m) for m in before[-2:]):
        found.append(phrase("expression.review.asked"))
    first = (_words(text)[:1] or [""])[0]
    if first and first not in GREETINGS and sum((_words(m)[:1] or [""])[0] == first for m in before) >= 2:
        found.append(phrase("expression.review.opener", word=text.split()[0].rstrip(",;:!?.…")))
    opening = next(iter(_SENTENCE.findall(text)), "")
    said = stems(heard)
    ws = _words(text)
    # reprendre un mot (« Bleu marine, ça va avec tout ») est naturel ; redire sa phrase (« Un manteau bleu marine un
    # peu cher, tu l'aimes bien »), ou ses mots tels quels, ne l'est pas
    hw = _words(heard)
    echoed = {tuple(hw[i:i + _AGAIN]) for i in range(len(hw) - _AGAIN + 1)} & \
        {tuple(ws[i:i + _AGAIN]) for i in range(len(ws) - _AGAIN + 1)}
    if (said and len(stems(opening) & said) >= max(3, (3 * len(stems(opening)) + 4) // 5)) or any(
            sum(w not in STOPWORDS for w in g) >= 2 for g in echoed):
        found.append(phrase("expression.review.echo"))
    # un second bonjour, un second au revoir : son dernier message les a déjà dits
    last = before[-1] if before else ""
    if first in GREETINGS and last and (_words(last)[:1] or [""])[0] in GREETINGS:
        found.append(phrase("expression.review.greeted"))
    if last and LEAVING.search(fold(text.lower())) and LEAVING.search(fold(last.lower())):
        found.append(phrase("expression.review.farewell"))
    pw = _words(portrait)
    copied = {tuple(pw[i:i + _COPIED]) for i in range(len(pw) - _COPIED + 1)} & \
        {tuple(ws[i:i + _COPIED]) for i in range(len(ws) - _COPIED + 1)}
    if any(sum(w not in STOPWORDS for w in g) >= 2 for g in copied):
        found.append(phrase("expression.review.portrait"))
    if _CORRECTED.search(heard or "") and _SORRY.search(text[:_SORRY_WITHIN]):
        found.append(phrase("expression.review.sorry"))
    heard_plain = " ".join(A.strip_prosody(heard).split())
    # une ligne vide n'allonge rien : en chat, c'est une autre bulle
    if heard_plain and len(heard_plain) <= _SHORT_HEARD and len(text) > _LONG_ANSWER:
        found.append(phrase("expression.review.long"))
    grams = {tuple(ws[i:i + _AGAIN]) for i in range(len(ws) - _AGAIN + 1)}
    for m in before:
        mw = _words(m)
        again = next((g for i in range(len(mw) - _AGAIN + 1) if (g := tuple(mw[i:i + _AGAIN])) in grams
                      and sum(w not in STOPWORDS for w in g) >= 2), None)
        if again is not None:
            found.append(phrase("expression.review.again", words=" ".join(again)))
            break
    if not found:
        return None
    return phrase("expression.review.note", draft=text[:600], found=" ; ".join(found))


# ── Sa réponse écrite par une autrice (ADR 0114) ──────────────────────────
#
# Ablation du 2026-10-15 : rejouer un appel mal jugé en retirant ou réécrivant un bloc de son prompt ne change presque
# rien — faire de ce qu'on lui dit une vérité générale, reformuler, finir par une question, c'est le modèle qui joue
# l'amie qui écoute. Banc du 2026-10-16 : tour par tour, même Opus reste une assistante qui joue un rôle et s'occupe de
# l'autre ; le même modèle, qui écrit un fil SMS entier en autrice, fait parler deux personnes. La seconde passe
# (``pipeline``, rôle ``polish``) est donc une autrice : elle lit son portrait, le fil et ce que le premier jet voulait
# dire, et écrit la suite du fil — ses messages à elle, puis la réponse probable de l'autre (l'écrire la garde
# autrice) ; seuls les siens partent. Ses balises, ses outils et ce qu'elle sait restent ceux du premier jet.

#: les derniers messages du fil que lit l'autrice
_POLISH_THREAD = 16


def _thread_lines(role: str, content: str, name: str) -> list[str]:
    """Un message du fil en lignes de SMS : une par bulle pour elle, une pour l'autre."""
    if role != "assistant":
        said = _plain(content)
        return [phrase("expression.polish.them", text=said)] if said else []
    return [phrase("expression.polish.her", name=name, text=b) for b in _bubbles(content).split("\n\n") if b]


def _thread(history: Sequence[Any], name: str) -> list[str]:
    """Les derniers messages du fil (``_POLISH_THREAD``) en lignes de SMS, chacun précédé de son repère de temps
    quand du temps a passé (« [le lendemain, mardi 14h13] ») : sans eux, trois jours de fil se lisaient comme une
    seule conversation, et au « coucou » du matin elle pouvait reprendre la blague de la veille. Le repère seul qui
    précède un de ses messages (``ChatPrompt.chat_messages``) passe sur ce message."""
    entries: list[list[str]] = []
    pending = ""
    for m in history:
        mark, rest = ("", m.content) if m.role == "assistant" else unlabel(m.content)
        mark = mark or pending
        lines = _thread_lines(m.role, rest, name)
        if not lines:
            pending = mark
            continue
        pending = ""
        entries.append([phrase("expression.polish.mark", mark=mark), *lines] if mark else lines)
    return [line for entry in entries[-_POLISH_THREAD:] for line in entry]


def authored(text: str, name: str) -> str:
    """Ses messages dans la suite écrite par l'autrice : les lignes « {name} : … » (ou sans nom) jusqu'à la première
    de l'autre, une bulle chacune (séparées par une ligne vide) ; « » si l'autrice ne lui fait rien dire."""
    out: list[str] = []
    # deux messages sur une ligne (« … Mika : … », « … L'autre : … ») : chacun sur la sienne
    them = phrase("expression.polish.them", text="").strip()
    split = re.compile(rf"\s+(?=(?:{re.escape(name)}|{re.escape(them.rstrip(':').strip())})\s*:)")
    for line in (part for raw in (text or "").splitlines() for part in split.split(raw)):
        line = line.strip().strip("«»\"").strip()
        if not line:
            continue
        who = _SPEAKER.match(line)
        label = who.group(1).strip() if who else ""
        if label and fold(label.split("(")[0].strip().lower()) == fold(name.lower()):  # « Mika (brouillon) »
            said = who.group(2).strip()
        elif label[:1].isupper():
            break  # l'autre (« L'autre : … », un prénom) : la suite n'est plus à elle
        else:
            said = line  # « bon : t'as raison » est une bulle à elle, pas un nom
        if said:
            out.append(said)
    return "\n\n".join(out)


def _other_titles() -> tuple[str, ...]:
    """Les sections de son état qui disent qui est l'autre : qui écrit, le ton entre eux, sa fiche."""
    return phrase("identity.who.title"), phrase("social.register.title"), phrase("social.about.title")


def _section(state: str, title: str) -> str:
    """Le corps d'une section « --- TITRE --- » de son état interne (« » : absente)."""
    m = re.search(rf"--- {re.escape(title)} ---\n(.*?)(?=\n--- |\Z)", state or "", re.S)
    return m.group(1).strip() if m else ""


#: « Nom : … » en tête d'une ligne de SMS (un nom court, éventuellement en gras)
_SPEAKER = re.compile(r"^\**([^:*\n]{1,24}?)\**\s*:\s*(.*)$")


def polish(draft: str, messages: Sequence[Any], heard: str = "",
           persona: Any = None, author: Any = None) -> tuple[str, str, Callable[[str], str]] | None:
    """La seconde passe sur sa réponse : (consigne, message, ce qu'on garde de la suite écrite) d'un appel où une
    autrice écrit la suite du fil à partir de son premier jet, ou ``None`` sans premier jet. ``persona`` : sa persona
    rendue pour la conversation (``text``, ``name``, ``reference`` : un fil de référence pour le registre) ;
    ``author`` : l'autrice du chat (``vocab.flows.Author``, ADR 0124) — ses codes s'ajoutent au cadre, son exemple
    prend la place du fil de référence."""
    text = _bubbles(draft)
    if not text:
        return None
    name = getattr(persona, "name", "") or phrase("expression.polish.unnamed")
    turns = [m for m in messages if getattr(m, "role", "") in ("user", "assistant") and (m.content or "").strip()]
    state = turns[-1].content if turns and turns[-1].role == "user" else ""
    history = turns[:-1] if state else turns
    lines = _thread(history, name)
    # le moment du message en cours par rapport au dernier (pour ce qu'elle lance d'elle-même : de maintenant), en
    # tête de ce qui suit son état interne
    now = unlabel(state.split(CONTEXT_FOOTER, 1)[-1].lstrip())[0]
    if now:
        lines.append(phrase("expression.polish.mark", mark=now))
    # ce que la personne vient d'écrire — jamais le cadrage d'un épisode (« personne ne vient de t'écrire… »)
    if _plain(heard):
        lines.append(phrase("expression.polish.them", text=_plain(heard)))
    system = phrase("expression.polish.system", name=name, portrait=(getattr(persona, "text", "") or "").strip())
    # qui est l'autre, d'après ce qu'elle a vécu avec lui (sa fiche, déjà filtrée pour cette audience) : l'autrice
    # écrit aussi ses réponses à venir (banc du 2026-10-16 : avec sa fiche, il plaisante comme lui)
    other = [body for title in _other_titles() if (body := _section(state, title))]
    if other:
        system += "\n\n" + phrase("expression.polish.other", name=name, about="\n".join(other))
    codes = (getattr(author, "codes", "") or "").strip()
    if codes:
        system += "\n\n" + phrase("expression.polish.codes", codes=codes)
    reference = (getattr(author, "example", "") or "").strip() or (getattr(persona, "reference", "") or "").strip()
    if reference:
        system += "\n\n" + phrase("expression.polish.reference", thread=reference, name=name)
    message = phrase("expression.polish.message", thread="\n".join(lines), name=name,
                     draft=" / ".join(text.split("\n\n")))
    return system, message, lambda written: authored(written, name)


def polish_draft(flow: str, draft: str, about: str, author: Any) -> tuple[str, str] | None:
    """La passe d'une autrice sur un brouillon d'outil (ADR 0124) : (consigne, message) d'un appel qui le récrit dans
    le genre de son flux (un courriel, un message Teams ou un SMS écrits à la place de la personne) et selon ses codes,
    sans rien y ajouter ; ``None`` pour une forme qui ne se récrit pas ainsi (le chat a sa seconde passe) ou un
    brouillon vide. ``about`` : ce à quoi il répond."""
    form = flows.form_of(flow)
    text = (draft or "").strip()
    if form not in flows.DRAFTS or not text:
        return None
    parts = [phrase("expression.author.system", genre=phrase(f"expression.author.genre.{form}"))]
    codes = (getattr(author, "codes", "") or "").strip()
    if codes:
        parts.append(phrase("expression.author.codes", codes=codes))
    example = (getattr(author, "example", "") or "").strip()
    if example:
        parts.append(phrase("expression.author.example", example=example))
    message = phrase("expression.author.message", about=(about or "").strip() or phrase("expression.author.opening"),
                     draft=text)
    return "\n\n".join(parts), message


#: un message de quelques mots : une réponse à la même mesure
SHORT_MESSAGE = 40
#: les curseurs de son tempérament qui s'entendent dans une réponse, du plus visible au moins visible ; au plus
#: ``_MARKED_SHOWN`` d'entre eux, marqués (``_MARKED`` du milieu ou plus), sont rappelés dans « TA RÉPONSE »
_VOICED = ("expressiveness", "sociability", "optimism", "negativity", "energy", "reactivity", "impulsivity",
           "shyness", "empathy", "trust", "curiosity", "contagion", "mask", "grudge", "anxiety", "introspection")
_MARKED, _MARKED_SHOWN = 0.3, 3


def marked_traits(temperament: Any) -> list[str]:
    """Ses traits les plus marqués, tels qu'ils doivent s'entendre dans une réponse (banc de conversation du
    2026-10-15 : réfléchie, solaire et kuudere parlaient pareil — un juge reconnaissait le profil une fois sur
    trois, le hasard ; le texte de sa persona l'emportait sur ses curseurs)."""
    if temperament is None:
        return []
    marked = []
    for rank, slider in enumerate(_VOICED):
        value = getattr(temperament, slider, None)
        if isinstance(value, (int, float)) and abs(float(value) - 0.5) >= _MARKED - 1e-9:
            marked.append((-abs(float(value) - 0.5), rank, slider, "high" if value > 0.5 else "low"))
    out: list[str] = []
    # les plus marqués d'abord ; chacun dit ce qu'il change à la façon d'écrire dans un chat (« tu montres peu : des
    # phrases courtes… »), pas seulement ce qu'il est (« ton attention passe par les actes ») — V5 du banc : la
    # phrase du trait seule ne changeait rien à sa parole
    for _dist, _rank, slider, side in sorted(marked)[:_MARKED_SHOWN]:
        note = (getattr(temperament, "notes", None) or {}).get(slider, "")
        out.append(f"{phrase(f'expression.answer.traits.{slider}.{side}')} {note}".strip())
    return out


#: un merci, un au revoir (mots repliés) : la réponse d'une amie, pas d'un guichet
THANKS = frozenset({"merci", "mercii", "thanks", "thx"})
LEAVING = re.compile(r"\b(?:bonne (?:nuit|soiree|journee|aprem)|a (?:plus tard|demain|toute)|bye|ciao|"
                     r"je (?:file|te laisse|vais y aller)|j'y vais)\b|\ba plus\W*$|\ba\+")


@EXPRESSION.section("answer", zone=Zone.VOLATILE, episodes=[Kind.REPLY], tags=[LAST], trim_rank=90,
                    title=phrase("expression.answer.title"), reads=[self_c.PERSONA])
def _answer(s: ExpressionState, frame: Frame, enrich: Mapping[str, Any]) -> str:
    """« TA RÉPONSE » : le dernier mot avant son message — réagir en personne, une question au plus et ouverte, pas
    de conseil qu'on ne demande pas, pas sa phrase reformulée ; court à qui écrit court. Banc de conversation du
    2026-10-14 (Sonnet, jugé par Opus) : avec ces règles seulement dans la consigne de style, en tête du prompt, une
    réplique sur deux finissait par « ceci, ou cela ? » et les conseils de coach revenaient."""
    heard = " ".join(A.strip_prosody(enrich.get("last_heard") or "").split())
    folded = fold(heard.lower())
    out = [phrase("expression.answer.react")]
    doc = frame.get(self_c.PERSONA)
    traits = marked_traits(getattr(doc, "temperament", None))
    if traits:
        out.append(phrase("expression.answer.character", traits=" ; ".join(traits)))
    out.append(phrase("expression.answer.subject"))
    if heard and len(heard) <= SHORT_MESSAGE:
        out.append(phrase("expression.answer.short"))
    if THANKS & set(_words(heard)):
        out.append(phrase("expression.answer.thanked"))
    if LEAVING.search(folded):
        out.append(phrase("expression.answer.leaving"))
    return " ".join(out)


@EXPRESSION.section("habits", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, trim_rank=55,
                    title=phrase("expression.habits.title"))
def _habits(s: ExpressionState, frame: Frame, enrich: Mapping[str, Any]) -> str | None:
    ep = frame.episode
    # ses entrées en matière, seulement quand ce tour en est une : elle vient d'elle-même, ou elle répond au premier
    # message après un silence (au milieu d'une conversation lancée, la section ne grossit pas)
    openings = enrich.get("own_openings") or Openings()
    opening = ep is not None and (ep.kind == Kind.INITIATIVE or (ep.kind == Kind.REPLY and openings.opens))
    opened = openings.said if opening else ()
    said = enrich.get("own_words") or ()
    found = repeats(said, frame.now, opened)
    told = said_of_herself(said, frame.now)
    if told:
        found = [*found, phrase("expression.habits.told", said=told)]
    asked = pending_question(said, enrich.get("last_heard") or "", frame.now) \
        if ep is not None and ep.kind == Kind.REPLY else None
    if not found and not asked:
        return None
    # une remarque pour elle seule : la sonde finale l'a vue s'en excuser à voix haute (« je vais varier mon
    # langage, promis ! »)
    out = []
    if found:
        out.append(phrase("expression.habits.reread", found=" ; ".join(found)))
    if asked:
        out.append(phrase("expression.habits.asked", question=asked))
    out.append(phrase("expression.habits.private"))
    return " ".join(out)


def _client_msg_id(store: Any, reply_to: int | None) -> str | None:
    if store is None or reply_to is None:
        return None
    t = transcript_c.thread_table()
    rows = store.query_mind(select(t.c.client_msg_id).where(t.c.id == reply_to))
    return rows[0][0] if rows else None


def _state_dict(face: affect_c.Face) -> dict[str, Any]:
    return {
        "person": {"emotion": face.person[0].value, "intensity": face.person[1]},
        "global": {"emotion": face.mood[0].value, "intensity": face.mood[1]},
        "message": {
            "emotion": face.emotion.value, "intensity": face.intensity,
            "blend": [{"emotion": e.value, "weight": round(w, 2)} for e, w in face.blend],
        },
    }


def emotion_view(frame: Frame, target: str | None, declared: Declared | None, *, toward: bool = False
                 ) -> EmotionView:
    """Ce que la trame montre : la balise déclarée si elle existe (c'est ce
    qu'elle a voulu dire) — ses deux premières facettes quand elle en a dit
    plusieurs (son ambivalence, jugée par le modèle, ADR 0093) —, sinon le
    visage (posture et humeur mêlées). Une réplique à quelqu'un (``toward`` : sa balise est déjà dans sa posture
    envers lui) montre son visage tel qu'elle le laisse voir à cette personne — son expressivité, son masque, sa
    défense, refermée ou non (ADR 0100) : ce que l'écran garde ensuite pendant qu'elle parle."""
    person = frame.get(identity_c.PERSON(target)) if target else "__global__"
    face = frame.get(affect_c.FACE(person))
    blend = tuple((e.value, round(w, 2)) for e, w in face.blend)
    if declared is not None and toward and target and declared.emotion is not Emotion.NEUTRAL:
        return EmotionView(face.emotion.value, face.intensity, blend, _state_dict(face), True)
    if declared is not None:
        name = declared.emotion.value
        if declared.facets:
            blend = tuple((e, round(x, 2)) for e, x in declared.facets[:2])
        elif not blend or blend[0][0] != name:
            blend = ((name, round(declared.intensity, 2)), *blend)[:2]
        return EmotionView(name, round(declared.intensity, 2), blend, _state_dict(face), True)
    return EmotionView(face.emotion.value, face.intensity, blend, _state_dict(face), False)


# ── Le murmure ────────────────────────────────────────────────────────────

#: ce qui pèse : une humeur qui déborde, une inquiétude, une peine — on se parle plus à soi-même
CHARGED = frozenset({affect_c.MOOD_OVERFLOW, others_c.CHECK_IN, social_c.COMFORT, attention_c.THOUGHT})
def why() -> Mapping[str, str]:
    """Pourquoi elle écrit, dit en clair, par raison d'initiative (``expression.murmur.why`` dans sa voix) — jamais
    le motif lui-même (ce qu'on lui a confié, un nom d'autrui, une citation) : le murmure se montre à l'écran de la
    personne, qui n'a pas à lire ce qui la travaille."""
    return family("expression.murmur.why")


def _draw(*parts: Any) -> float:
    """Un tirage uniforme dans [0, 1), dérivé de l'épisode (rejouable)."""
    return h64("murmure", *parts) / 2.0 ** 64


def _matter_why(frame: Frame, target: str, name: str) -> str | None:
    """Ce dont elle a envie de lui parler, quand ce sont ses envies qui la poussent
    (la sorte de chose, jamais son contenu)."""
    m = frame.get(needs_c.MATTER(target))
    if not isinstance(m, needs_c.Matter):
        return None
    if m.kind == needs_c.THOUGHT_MATTER:
        return phrase("expression.murmur.matter.read") if m.external else \
            phrase("expression.murmur.matter.thought")
    if m.kind == needs_c.DONE_MATTER:
        return phrase("expression.murmur.matter.done", when=when_fr(m.at, frame.now, frame.env.tz_of(frame.root)))
    if m.kind == needs_c.WORKING_MATTER:
        return phrase("expression.murmur.matter.working")
    if m.kind == needs_c.MOMENT_MATTER:
        return phrase("expression.murmur.matter.moment")
    if m.kind == needs_c.DREAM_MATTER:
        return phrase("expression.murmur.matter.dream")
    return phrase("expression.murmur.matter.told", que_name=elided(name, "que"))


def why_fr(frame: Frame, req: Any, target: str, name: str) -> str:
    """La raison la plus forte de l'initiative, dite en clair."""
    selected = getattr(req, "selected", None)
    parts = sorted(getattr(selected, "parts", ()) or (), key=lambda p: (-p[2], p[1]))
    said = why()
    for _source, reason, _evidence in parts:
        if reason in (needs_c.NEED_SOCIAL, needs_c.NEED_EXPRESSION, social_c.CHAT):
            matter = _matter_why(frame, target, name)
            if matter is not None:
                return matter
        if reason in said:
            return said[reason]
    return phrase("expression.murmur.anything")


def _mood(frame: Frame) -> str:
    m = frame.get(affect_c.MOOD)
    if m.felt_intensity < 0.1:
        return phrase("expression.murmur.as_usual")
    return f"{A.intensity_word(m.felt_intensity)} {A.FR.get(m.felt, '')}".strip()


@EXPRESSION.prelude(kinds=[Kind.INITIATIVE])
def murmur(frame: Frame, req: Any) -> Prelude | None:
    """Avant d'écrire d'elle-même à quelqu'un qui la regarde (un écran ouvert),
    elle se murmure parfois ce qui la traverse — une fois sur trois environ,
    plus souvent quand quelque chose pèse ; parfois elle se ravise. Réveillée,
    pas pour une salutation, pas plus d'une fois par heure. Le murmure se montre
    à la personne visée (persona voix intérieure), jamais en message, et ne dit
    jamais le motif lui-même."""
    reasons = set(str(getattr(req, "reason", "")).split(","))
    target = getattr(req, "target", None)
    if not target or is_internal(target) or social_c.GREETING in reasons:
        return None
    if target not in frame.get(presence_c.PRESENT):
        return None  # personne pour l'entendre (une messagerie : un murmure ne s'écrit pas)
    if frame.get(body_c.SLEEP) is not body_c.SleepPhase.AWAKE:
        return None
    p = params(frame.env.params_of("expression", frame.root))
    if frame.now - frame.get(agency_c.AGENCY).murmured_at < p.murmur_spacing_us:
        return None
    trigger = str(getattr(req, "trigger", ""))
    chance = p.murmur_charged_chance if CHARGED & reasons else p.murmur_chance
    if _draw(trigger, target, frame.seq) >= chance:
        return None
    # on ne se ravise pas de tenir parole (un rappel promis), ni de prévenir de ce qui ne peut pas attendre (un mail
    # important, un projet confié qui bloque) : elle peut y penser à mi-voix, jamais « pas maintenant » (ADR 0044)
    firm = bool((agency_c.OWED | agency_c.INFORMS) & reasons)
    adrift = not firm and _draw("sans suite", trigger, target, frame.seq) < p.murmur_adrift
    known = frame.get(identity_c.IDENTITY(target)).name
    name = f"« {known} »" if known else phrase("expression.person.unnamed")
    reason = why_fr(frame, req, target, name)
    now = frame.local()
    scene = phrase("expression.murmur.scene", hour=now.hour, minute=f"{now.minute:02d}", mood=_mood(frame))
    if adrift:
        intent = phrase("expression.murmur.intent_adrift", name=name, why=reason)
        ask = phrase("expression.murmur.ask_adrift")
    else:
        intent = phrase("expression.murmur.intent", name=name, why=reason)
        ask = phrase("expression.murmur.ask")
    tail = phrase("expression.murmur.tail", ask=ask)
    tag = c.MURMUR_ADRIFT if adrift else c.MURMUR
    return Prelude(Kind.MURMUR, f"{scene} {intent} {tail}", reason=f"{tag}:{target}", instead=adrift)


@EXPRESSION.reducer(rt.EPISODE_STARTED)
def _murmuring(s: ExpressionState, e, cx) -> ExpressionState:
    """Un murmure commence : on retient à qui elle allait écrire (sa livraison ira
    là, et seulement là)."""
    d = e.data
    if d.kind != Kind.MURMUR:
        return s
    tag, _, target = d.reason.partition(":")
    if tag not in (c.MURMUR, c.MURMUR_ADRIFT) or not target:
        return s
    murmurs = s.murmurs.set(e.correlation, target)
    if len(murmurs) > MURMURS_KEPT:  # les identifiants d'épisode sont chronologiques
        murmurs = FrozenDict(sorted(murmurs.items())[-MURMURS_KEPT:])
    return replace(s, murmurs=murmurs)


@EXPRESSION.effect(rt.UTTERANCE)
async def _deliver(ev: Any, ports: Mapping[str, Any]) -> None:
    d = ev.data
    if d.kind not in CONVERSATIONAL and d.kind != Kind.MURMUR:
        return
    port = ports.get("delivery")
    text = d.text.text
    if port is None or text is None:
        return
    frame: Frame = ports["frame"]()
    target = d.target
    if d.kind == Kind.MURMUR:
        # une pensée à mi-voix : sur les écrans de la personne à qui elle allait écrire, voix intérieure — jamais
        # à tout le monde (sans destinataire connu, elle ne part pas)
        target = frame.state("expression").murmurs.get(ev.correlation)
        if not target:
            return
    declared = Declared.decode(d.annotation(c.EMOTION_ANNOTATION))
    persona = voice.SPEAKING if d.target and d.kind in CONVERSATIONAL else voice.INNER
    await port.deliver(Delivery(
        key=ev.id, target=target, channel=d.channel, room=d.room, text=text, persona=persona,
        emotion=emotion_view(frame, target, declared, toward=d.kind in CONVERSATIONAL),
        message_id=ev.seq, reply_to=d.reply_to,
        client_msg_id=_client_msg_id(ports.get("store"), d.reply_to),
        source="reply" if d.kind == Kind.REPLY else "conscience",
        sleep_phase=frame.get(body_c.SLEEP).value, local_hour=frame.local().hour,
        answers=tuple(d.answers) if persona == voice.SPEAKING else (),
        # ce qui part avec la parole (des références opaques ici) ; jamais avec une pensée à voix haute
        attachments=tuple(d.attachments) if persona == voice.SPEAKING else (),
        mode=d.mode if persona == voice.SPEAKING else "",
    ))
