"""Les sections du rappel : le rendu en mots de ce que le rappel a trouvé, section par section.

L'enrichisseur ``recall`` (``recall.py``) cherche et trie ; ce module dit ce qu'il a trouvé : ses souvenirs et ce
qu'elle sait (``memories``, ``shared_memories``), les gens qu'on nomme (``acquainted``), les échanges passés, ses
promesses, la vie de la personne en face (``life``), ce qui vient (``ahead``), ce qu'elle a déjà dit d'elle
(``self_said``). L'ordre où elle les lit est déclaré ailleurs (``READING``, ``app/composition.py``, ADR 0151).

Ce que l'enrichisseur ou les outils lisent aussi (``when_words``, ``knowledge_label``, ``_today``…) reste dans
``recall.py`` : ce module l'importe de là, jamais l'inverse.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mika.contracts import memory as c
from mika.contracts import social as social_c
from mika.faculties.memory import timespan
from mika.faculties.memory.faculty import MEMORY, MemoryState, params
from mika.faculties.memory.likelihood import cautious, likely_words, nature_of
from mika.faculties.memory.recall import (
    OWNER,
    Moment,
    Recall,
    Recalled,
    _today,
    followed_lately,
    knowledge_label,
    names_of,
    when_words,
)
from mika.faculties.memory.salience import Item, age_words
from mika.kernel.clock import DAY
from mika.kernel.faculty import Zone
from mika.kernel.frame import Frame
from mika.kernel.prompt import Fragment, SectionBody
from mika.vocab.episodes import CONVERSATIONAL, Kind
from mika.vocab.people import clean_tokens, read_source
from mika.vocab.phrasebook import family, phrase

#: une croyance apprise il y a plus longtemps dit depuis quand (« ma sœur vient ce week-end » n'est plus vrai)
DATED_AFTER_US = 7 * DAY


# ── Les sections ──────────────────────────────────────────────────────────


def read_in(item: Item) -> str:
    """« lu dans « Le Monde » » : une croyance qu'elle tient d'une lecture (ADR 0085) — une source publique, anodine,
    qui se nomme partout."""
    source = next((read_source(k) for t in item.testimonies if t.origin == c.READ for k in t.told_by
                   if read_source(k)), "")
    return phrase("memory.recall.read_in", source=source) if source else ""


def _lines(recalled: list[Recalled], now: int, *, beliefs: bool, names: Mapping[str, str] | None = None) -> list[str]:
    lines = []
    for r in recalled:
        if beliefs:
            # ce qu'elle devine se dit comme tel ; ce qu'on lui a dit se lit déjà dans le texte
            how = [family("memory.recall.origin").get(r.item.origin or "", "")]
            how.append(knowledge_label(r.item, names or {}))
            how.append(read_in(r.item))
            since = r.item.as_of or r.item.born_at
            if now - since >= DATED_AFTER_US:
                # « ma sœur vient ce week-end », relu trois semaines plus tard, n'est plus vrai : elle sait depuis quand
                # (depuis quand c'est vrai, quand on le lui a dit — ADR 0081)
                how.append(phrase("memory.recall.learned", age=age_words(since, now)))
            told = ", ".join(h for h in how if h)
            lines.append(f"- {clean_tokens(r.label)}" + (f" ({told})" if told else ""))
        else:
            lines.append(f"- {age_words(r.item.born_at, now)} : {clean_tokens(r.label)}")
    return lines


def _body(recall: Recall, frame: Frame, *, witness: bool) -> SectionBody | None:
    memories = [r for r in recall.memories if r.verdict.witness == witness]
    beliefs = [r for r in recall.beliefs if r.verdict.witness == witness]
    hidden = recall.unsaid if not witness else []
    if not memories and not beliefs and not hidden:
        return None
    parts: list[Fragment] = []
    names = names_of(frame, {r.item.holder for r in beliefs if r.item.holder})
    for bucket, belief, heading in ((memories, False, phrase("memory.recall.souvenirs")),
                                    (beliefs, True, phrase("memory.recall.beliefs"))):
        if bucket:
            parts.append(Fragment(heading, heading=True))
            # ce qui lui revient se redit même quand le fil le montre encore (ADR 0263 ne vaut que pour ce qu'elle a
            # dit d'elle et ce qui vous lie) : ce qu'elle a sous les yeux est ce que son usage renforce
            parts.extend(Fragment(line, tuple(f"memory:{i}" for i in (r.evidence or (r.item.id,)))) for r, line in zip(
                bucket, _lines(bucket, frame.now, beliefs=belief, names=names), strict=True))
    if hidden:
        # sonde réelle du 2026-10-02 : sans cette ligne, interrogée là-dessus, elle mentait (« il ne m'a rien dit »)
        parts.append(Fragment(phrase("memory.recall.unsaid"), heading=True))
        parts.extend(Fragment(line) for line in [*hidden, phrase("memory.recall.unsaid_advice")])
    shown = memories + beliefs  # ce qu'on lui a confié porte son étiquette (``memory.tag``), ligne par ligne
    return SectionBody("\n".join(f.text for f in parts), level=max((r.verdict.level for r in shown), default=0),
                       provenance=tuple(f"memory:{i}" for r in shown for i in (r.evidence or (r.item.id,))), witness=witness,
                       tied=any(r.verdict.tied for r in shown),
                       fragments=tuple(parts))


@MEMORY.section("acquainted", zone=Zone.VOLATILE, episodes=[Kind.REPLY], trim_rank=40,
                title=phrase("memory.acquainted.title"))
def _acquainted(s: MemoryState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """« LES GENS QU'ON NOMME » : un prénom qu'elle connaît dans son cercle — elle le connaît, peut-être pas la même
    personne ; si ça compte, elle demande de qui on parle, sans rien dire de ce qu'elle en sait."""
    recall: Recall | None = enrich.get("recall")
    if not recall or not recall.acquainted:
        return None
    lines = []
    for name, many, relation in recall.acquainted:
        if many > 1:
            lines.append(phrase("memory.acquainted.several", name=name))
        elif relation in (OWNER, social_c.CLOSE):
            lines.append(phrase("memory.acquainted.close", name=name))
        else:
            lines.append(phrase("memory.acquainted.friend", name=name))
    lines.append(phrase("memory.acquainted.advice"))
    return SectionBody("\n".join(lines))


@MEMORY.section("memories", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, trim_rank=30,
                title=phrase("memory.recall.title"))
def _memories(s: MemoryState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    recall = enrich.get("recall")
    return _body(recall, frame, witness=False) if recall else None


@MEMORY.section("shared_memories", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, trim_rank=31,
                title=phrase("memory.recall.shared_title"))
def _shared(s: MemoryState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    recall = enrich.get("recall")
    return _body(recall, frame, witness=True) if recall else None


@MEMORY.section("past_exchanges", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, trim_rank=20,
                title=phrase("memory.exchanges.title"))
def _exchanges(s: MemoryState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    recall: Recall | None = enrich.get("recall")
    if not recall or not recall.exchanges:
        return None
    # ce qui est déjà dans le fil ne se répète pas — sauf le moment que sa question désigne : au bout d'une semaine de
    # fil, qui a dit quoi lundi matin s'y perd (sonde réelle du 2026-10-03 : elle lui a prêté son propre rêve)
    exchanges = recall.exchanges
    p = params(frame.env.params_of("memory", frame.root))
    exchanges = exchanges[: p.max_chunks]
    if not exchanges:
        return None
    names = names_of(frame, {e.person for e in exchanges if e.person})
    lines = []
    for e in exchanges:
        who = names.get(e.person) or recall.name or phrase("memory.exchanges.someone")
        lines.append(phrase("memory.exchanges.line", age=age_words(e.at, frame.now), who=who, said=e.user_text[:240],
                            reply=e.reply_text[:240]))
    return SectionBody("\n".join(lines), provenance=tuple(f"chunk:{e.id}" for e in exchanges),
                       fragments=tuple(Fragment(line, (f"chunk:{e.id}",),
                                                (e.question, e.id) if e.question and not e.dated else ())
                                       for e, line in zip(exchanges, lines, strict=True)))


@MEMORY.section("promises", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, trim_rank=60,
                title=phrase("memory.promises.title"))
def _promises(s: MemoryState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    recall: Recall | None = enrich.get("recall")
    if not recall or not recall.promised:
        return None
    lines = []
    today = frame.local().date()
    for pid, text, due, implicit, all_day in recall.promised:
        when = ""
        if due and not implicit:
            # un jour sans heure n'est passé qu'une fois la journée finie : le soir même, c'est encore « pour
            # aujourd'hui »
            past = frame.local(due).date() < today if all_day else due < frame.now
            when = phrase("memory.promises.was_for", when=when_words(due, frame)) if past else \
                phrase("memory.promises.for", when=when_words(due, frame))
        now = phrase("memory.promises.now") if pid in recall.due_now else ""
        lines.append(phrase("memory.promises.line", when=when, now=now, id=pid, text=text))
    return SectionBody("\n".join(lines), provenance=tuple(f"memory:{pid}" for pid, *_ in recall.promised))


@MEMORY.section("life", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, trim_rank=55,
                title=phrase("memory.life.title"))
def _life(s: MemoryState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    recall: Recall | None = enrich.get("recall")
    if not recall or not recall.moments:
        return None
    aud = frame.audience
    lines = []
    heavy = any(c.heavy_date(m.event) and _today(m.event, frame) for m in recall.moments)
    if recall.hard and aud is not None and aud.private_ok and not heavy:
        # en privé seulement : un salon n'a pas à deviner ce qui pèse (ADR 0054) ; le jour d'une date lourde, sa
        # ligne le dit
        lines.append(phrase("memory.life.hard"))
    for m in recall.moments:
        lines.append(_moment_line(m, frame, recall.close))
    return SectionBody("\n".join(lines), level=max((m.verdict.level for m in recall.moments), default=0),
                       provenance=tuple(f"memory:{m.event.id}" for m in recall.moments),
                       tied=any(m.verdict.tied for m in recall.moments))


def moment_when(ev: c.LifeEvent, frame: Frame) -> str:
    """Quand, comme on le dit : une période (« en novembre », ADR 0084), sinon le jour (« jeudi », « demain »)."""
    if ev.vague:
        return timespan.period_words(ev.when, ev.ends, ev.precision, frame.now, frame.env.tz_of(frame.root))
    return when_words(ev.when, frame, all_day=ev.all_day)


@MEMORY.section("ahead", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, trim_rank=50,
                title=phrase("memory.ahead.title"))
def _ahead(s: MemoryState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """« CE QUI VIENT » : le monde et ce qu'elle vivra à travers quelqu'un, avec leur vraisemblance en mots."""
    recall: Recall | None = enrich.get("recall")
    if not recall or not recall.ahead:
        return None
    lines = []
    for m in recall.ahead:
        # ses attentes de cette sorte se sont souvent trompées : un cran plus prudente (ADR 0086)
        careful = cautious(s.calibration.get(nature_of(m.event)), params(frame.env.params_of("memory", frame.root)))
        likely = likely_words(m.event.likelihood, careful=careful)
        lines.append(phrase("memory.ahead.line", when=moment_when(m.event, frame), label=m.label) +
                     (phrase("memory.ahead.likely", likely=likely) if likely else ""))
    return SectionBody("\n".join(lines), level=max((m.verdict.level for m in recall.ahead), default=0),
                       provenance=tuple(f"memory:{m.event.id}" for m in recall.ahead),
                       tied=any(m.verdict.tied for m in recall.ahead))


def _moment_line(m: Moment, frame: Frame, close: bool) -> str:
    """Un moment, dit comme un fait : à venir, ou déjà évoqué ; ce qui se fête, souhaité ou pas encore ; le jour où
    revient une date lourde ; passé, et s'il comptait pour une amie ; une situation qui dure, ou qu'on vient de lui
    dire finie ; ce dont vous venez de reparler. Ce qu'elle en fait (demander, souhaiter, se taire), son caractère et
    la conversation le disent — rien ici ne le lui dicte."""
    ev = m.event
    if ev.ongoing and ev.ended_at:
        return phrase("memory.life.ended", label=m.label)
    if ev.ongoing:
        since = when_words(ev.when, frame)
        head = phrase("memory.life.ongoing", label=m.label) if since == phrase("memory.when.today") else \
            phrase("memory.life.ongoing_since", since=since, label=m.label)
        if ev.recurs:
            head += phrase("memory.life.again")  # une situation finie qui recommence (ADR 0079)
        if followed_lately(ev, frame.now):
            return head + phrase("memory.life.talked_again")
        if close:
            return head + phrase("memory.life.ongoing_close")
        return head + phrase("memory.life.ongoing_ask")
    if ev.vague:
        # « en novembre » : ni « jeudi », ni « comment ça s'est passé » tant que la période dure (ADR 0084)
        when = moment_when(ev, frame)
        if ev.ends >= frame.now:
            return f"- {when} : {m.label}" + (phrase("memory.life.already_said") if m.mentioned else "")
        return f"- {when} : {m.label}" + (phrase("memory.life.past_close") if close and ev.importance >=
                                           c.IMPORTANT_MOMENT else phrase("memory.life.past"))
    when = when_words(ev.when, frame, all_day=ev.all_day)
    if ev.outcome in (c.CANCELLED, c.MOVED):
        # elle sait comment il a tourné (ADR 0086) : ni « alors, ça s'est passé comment ? », ni « bonne chance »
        outcome = phrase("memory.life.outcome.cancelled") if ev.outcome == c.CANCELLED else \
            phrase("memory.life.outcome.moved")
        return f"- {when} : {m.label}" + outcome
    if ev.festive:
        return _festive_line(m, frame, when)
    if ev.outcome == c.HAPPENED and not ev.followed_at:
        return f"- {when} : {m.label}" + phrase("memory.life.outcome.happened")
    if ev.followed_at:
        return f"- {when} : {m.label}" + (phrase("memory.life.talked_again") if ev.when > frame.now
                                           else phrase("memory.life.past_talked"))
    if ev.yearly and _today(ev, frame):
        if c.heavy_date(ev):
            return phrase("memory.life.heavy_today", label=m.label)
        return phrase("memory.life.yearly_today", label=m.label)
    if ev.when > frame.now:
        return f"- {when} : {m.label}" + (phrase("memory.life.already_said") if m.mentioned else "")
    if close and ev.importance >= c.IMPORTANT_MOMENT:
        return f"- {when} : {m.label}" + phrase("memory.life.past_close")
    return f"- {when} : {m.label}" + phrase("memory.life.past")


def _festive_line(m: Moment, frame: Frame, when: str) -> str:
    """Ce qui se fête : souhaité ou pas encore, le jour même ou passé."""
    ev = m.event
    if ev.followed_at:
        return f"- {when} : {m.label}" + phrase("memory.life.festive_wished")
    if frame.local(ev.when).date() == frame.local().date():
        return phrase("memory.life.festive_today", label=m.label)
    if ev.when > frame.now:
        return f"- {when} : {m.label}" + (phrase("memory.life.already_said") if m.mentioned else "")
    return f"- {when} : {m.label}" + phrase("memory.life.festive_missed")


@MEMORY.section("self_said", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, trim_rank=35,
                title=phrase("memory.self_said.title"))
def _self_said_section(s: MemoryState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """Ses goûts, ses avis, sa vie, tels qu'elle les a déjà dits : on lui parle d'elle, elle ne se contredit pas
    (elle peut changer d'avis — alors elle le dit)."""
    recall: Recall | None = enrich.get("recall")
    if not recall or not recall.self_said:
        return None
    lines = [phrase("memory.self_said.line", age=age_words(it.born_at, frame.now), text=it.text)
             for it in recall.self_said]
    # ce que le fil montre encore ne se redit pas (ADR 0263) : le dernier message où elle l'a dit, tant qu'il est
    # frais — une redite complète ses sources, et c'est la plus récente que le fil garde ; la fenêtre glissée, ou
    # vingt jours plus tard, la ligne revient
    return SectionBody("\n".join(lines), provenance=tuple(f"memory:{it.id}" for it in recall.self_said),
                       fragments=tuple(Fragment(line, (f"memory:{it.id}",),
                                                c.shown_by_thread(it.sources, it.touched_at, frame.now, last=True))
                                       for it, line in zip(recall.self_said, lines, strict=True)))
