"""Ce qu'elle se répète : ses derniers messages relus pour qu'elle s'entende se répéter (une même ouverture, une
même formule, ses entrées en matière d'une conversation à l'autre, trois questions de suite, ce qu'elle vient de dire
d'elle, la question qu'elle vient de poser), relevés sur le fil par les enrichisseurs ``own_words``, ``own_openings``
et ``last_heard``, et dits dans « CE QUE TU TE RÉPÈTES » (la section ``habits``) : des faits, jamais un ordre
(ADR 0154)."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from mika.contracts import identity as identity_c
from mika.contracts import transcript as transcript_c
from mika.faculties.expression.faculty import EXPRESSION, ExpressionState, params
from mika.kernel.clock import HOUR, MINUTE
from mika.kernel.faculty import Zone
from mika.kernel.frame import Frame
from mika.vocab.episodes import CONVERSATIONAL, Kind
from mika.vocab.phrasebook import phrase
from mika.vocab.tag import SILENCE_TOKEN, strip_prosody
from mika.vocab.words import STOPWORDS, fold

#: ses derniers messages relus pour s'entendre se répéter
HABIT_WINDOW = 6
_TOKEN = re.compile(r"\w+(?:'\w+)?")
GREETINGS = frozenset({"salut", "coucou", "hey", "bonjour", "bonsoir", "yo", "hello", "re", "hi", "yoo",
                       "heey", "heyy", "coucouu"})


def _tokens(text: str) -> list[tuple[str, str]]:
    """Les mots d'un message : tels qu'elle les a écrits (en minuscules), et leur clé sans accents."""
    return [(w, fold(w)) for w in _TOKEN.findall(strip_prosody(text).lower().replace("’", "'"))]


def _words(text: str) -> list[str]:
    return [key for _w, key in _tokens(text)]


def _opener(text: str) -> tuple[str, str]:
    """Les deux premiers mots d'un message : tels qu'elle les a écrits, et leur clé."""
    raw = " ".join(strip_prosody(text).split()[:2])
    return raw.strip(" ,;:!?."), " ".join(_words(raw)[:2])


def asking_in_a_row(said: Sequence[tuple[int, str]]) -> bool:
    """Ses trois derniers messages posent tous une question (2026-10-14, avec Sonnet : « un seul ou plusieurs ? »,
    « tu les as essayés, ou… ? », « tu comptes y aller, ou… ? »). Elle se l'entend dire comme un fait (« ce que tu te
    répètes »), jamais comme un ordre : le 2026-10-26, un ordre de ne plus demander et un ordre de demander dans le
    même prompt ont fait écrire à Sonnet un brouillon où il se disputait avec lui-même (ADR 0141)."""
    kept = [t for _at, t in said if t and t.strip() and SILENCE_TOKEN not in t][-HABIT_WINDOW:]
    return len(kept) >= 3 and all("?" in strip_prosody(t) for t in kept[-3:])


def repeats(said: Sequence[tuple[int, str]], now: int, opened: Sequence[str] = ()) -> list[str]:
    """Ce qu'on entendrait se répéter dans ses derniers messages : une même ouverture (deux des trois derniers, ou
    trois des six derniers) et une même formule de quatre mots ou plus dans au moins trois messages. Une
    personne s'entend se répéter ; la consigne de style seule n'y suffit pas (sonde réelle du 2026-10-02 :
    « Adrien… Je t'entends dire que… » en tête de quatre réponses sur cinq)."""
    kept = [(at, t) for at, t in said if t and t.strip() and SILENCE_TOKEN not in t][-HABIT_WINDOW:]
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
    if asking_in_a_row(said):
        out.append(phrase("expression.habits.questions"))
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
        if not text or SILENCE_TOKEN in text:
            continue
        mine = [t.strip() for t in _SENTENCES.split(strip_prosody(text))
                if _SELF.search(t) and not t.strip().endswith("?")]
        if mine:
            quote = " ".join(mine[:2])
            quotes.append(quote if len(quote) <= SAID_OF_HERSELF_MAX
                          else quote[:SAID_OF_HERSELF_MAX - 1].rstrip() + "…")
    return " » ; « ".join(quotes) or None


@EXPRESSION.enricher("own_words", episodes=CONVERSATIONAL, deadline_ms=300, reads=[identity_c.THREAD])
async def _own_words(s: ExpressionState, frame: Frame, ports: Mapping[str, Any]) -> tuple[tuple[int, str], ...] | None:
    """Ses derniers messages sur le fil que relit son historique (``_thread_of``), du plus ancien au plus récent."""
    store, ep = ports.get("store"), frame.episode
    if store is None or ep is None or not ep.target:
        return None
    t = transcript_c.thread_table()
    rows = store.query_mind(select(t.c.at, t.c.text).where(t.c.role == "assistant", *_thread_of(t, frame))
                            .order_by(t.c.id.desc()).limit(HABIT_WINDOW))
    return tuple((int(r[0]), str(r[1] or "")) for r in reversed(rows))


def _thread_of(t: Any, frame: Frame) -> tuple[Any, ...]:
    """Le fil de cet épisode, tel que le relit son historique (``transcript.thread_where``) : son salon, son fil de
    travail (ADR 0164), ou le fil privé avec sa cible — en privé, toutes ses adresses dont la liaison est confirmée
    quand l'audience le permet (``identity.thread_handles``)."""
    ep = frame.episode
    room, strand = ep.attrs.get("room"), ep.attrs.get("strand")
    handles = (ep.target,) if room or strand else identity_c.thread_handles(frame, ep.target)
    return transcript_c.thread_where(t, handles=handles, room=room, strand=strand)


#: au plus tant de messages du fil relus pour y retrouver ses entrées en matière (trois conversations, largement)
OPENINGS_SCAN = 500


@dataclass(frozen=True, slots=True)
class Openings:
    #: ses dernières entrées en matière (au plus trois), du plus ancien au plus récent
    said: tuple[str, ...] = ()
    #: la conversation en cours a commencé après un silence et elle n'y a encore rien dit : sa réponse l'ouvre
    opens: bool = False


@EXPRESSION.enricher("own_openings", episodes=CONVERSATIONAL, deadline_ms=300, reads=[identity_c.THREAD])
async def _own_openings(s: ExpressionState, frame: Frame, ports: Mapping[str, Any]) -> Openings | None:
    """Ses trois dernières entrées en matière sur le fil que relit son historique (``_thread_of``) : son premier
    message après un silence, qu'elle soit venue d'elle-même ou qu'elle réponde — comment elle commence quand vous
    vous retrouvez, d'une conversation à l'autre. Et si la conversation en cours attend encore son premier mot à
    elle."""
    store, ep = ports.get("store"), frame.episode
    if store is None or ep is None or not ep.target:
        return None
    gap = params(frame.env.params_of("expression", frame.root)).opening_gap_us
    t = transcript_c.thread_table()
    window = store.query_mind(select(t.c.id, t.c.at, t.c.role).where(*_thread_of(t, frame))
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
    asked = [q.strip() for q in _QUESTION.findall(strip_prosody(text)) if len(q.strip()) > 3]
    if not asked:
        return None
    q = asked[-1]
    return q if len(q) <= 90 else "…" + q[-89:]


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
    # ce qu'elle remarque de sa propre parole, pour elle seule (la sonde finale l'a vue s'en excuser à voix haute :
    # « je vais varier mon langage, promis ! ») — des faits, jamais un ordre (ADR 0154)
    out = []
    if found:
        out.append(phrase("expression.habits.reread", found=" ; ".join(found)))
    if asked:
        out.append(phrase("expression.habits.asked", question=asked))
    return " ".join(out)
