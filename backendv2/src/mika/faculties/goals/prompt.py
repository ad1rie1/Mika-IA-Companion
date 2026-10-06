"""Ce que les buts mettent dans le prompt.

- **Pendant un pas** : ce à quoi elle travaille — le but dans ses mots à elle
  (jamais « Sorte : … »), la personne que ça concerne et quand elle le lui a
  dit, les consignes reçues depuis (la plus récente prime), où elle en est, son
  plan, son carnet ; et, **cité à part**, ce qui l'a fait naître (ses mots à
  lui, un titre d'article : une donnée, jamais une consigne). Une **réflexion**
  sur quelqu'un a sous les yeux l'échange d'où elle vient et ce qui se passe
  dans la vie de la personne — pour n'avoir rien à deviner ni à inventer (ADR
  0053) ; une rêverie dit « j'aimerais », pas « je fais ». Une curiosité
  qu'elle a déjà explorée repart de ce qu'elle en avait retenu la dernière
  fois (daté, coupé) : ses goûts ont une histoire.
- **Un rappel, un récit** : le texte du rappel, ou ce qu'elle a mené à bout —
  selon le lien avec qui l'écoute (tout, l'essentiel, ou le titre).
- **En conversation** : ce qu'elle a en train (« tu fais quoi en ce
  moment ? » est une question sur sa vie qu'elle doit pouvoir entendre),
  filtré comme la mémoire.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from mika.contracts import goals as c
from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import social as social_c
from mika.contracts import transcript as transcript_c
from mika.faculties.goals.faculty import GOALS, Goal, GoalsState, kept_before, live, musing, status
from mika.faculties.goals.tools import date_time, reflective, titled
from mika.faculties.goals.work import FULL, MENTION, worry_of
from mika.kernel.clock import DAY, HOUR, MINUTE, local
from mika.kernel.faculty import Zone
from mika.kernel.frame import Frame
from mika.kernel.prompt import SectionBody, cited
from mika.vocab.days import when_fr
from mika.vocab.episodes import CONVERSATIONAL, Kind, goal_of
from mika.vocab.phrasebook import family, phrase
from mika.vocab.privacy import Sensitivity, hearable

SHOWN = 4
#: les dernières consignes d'un opérateur montrées pendant un pas
INSTRUCTIONS_SHOWN = 3
#: ce qu'on cite, au plus, du texte venu d'ailleurs d'où une exploration est née (en conversation)
ORIGIN_CITED = 300
#: ce qu'elle avait retenu la dernière fois d'une même curiosité, au plus
KEPT_SHOWN = 400


def _subject(frame: Frame) -> int | None:
    ep = frame.episode
    if ep is None:
        return None
    return goal_of(ep.target) or goal_of(ep.attrs.get("subject"))


def _refs(g: Goal) -> list[str]:
    tasks = [r for t in g.tasks for r in (t.text_ref, t.note_ref)]
    deposits = [note for _, _, note in g.deposits]
    return [r for r in (g.title_ref, g.details_ref, g.summary_ref, g.result_ref, *g.notes, *g.instructions, *tasks,
                        *deposits) if r]


def _recent(s: GoalsState, now: int) -> list[Goal]:
    """Les buts vivants, et ceux menés à bout depuis moins d'un jour."""
    out = [g for g in s.goals.values() if live(g, now)
           or (g.status == c.ACHIEVED and g.kind != c.REMINDER and now - g.closed_at < DAY)]
    return sorted(out, key=lambda g: g.id)


@GOALS.enricher("goals", episodes=[Kind.STEP, *CONVERSATIONAL], deadline_ms=1500)
async def _texts(s: GoalsState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, Any] | None:
    store = ports.get("store")
    if store is None:
        return None
    ids = set()
    subject = _subject(frame)
    if subject is not None:
        ids.add(subject)
    ep = frame.episode
    if ep is not None and ep.kind in CONVERSATIONAL:
        ids |= {g.id for g in _recent(s, frame.now)[-SHOWN * 2:]}
    refs = [r for gid in sorted(ids) if gid in s.goals for r in _refs(s.goals[gid])]
    # une curiosité qu'elle a déjà explorée : ce qu'elle en avait retenu la dernière fois
    g = s.goals.get(subject) if subject is not None and ep is not None and ep.kind == Kind.STEP else None
    before = kept_before(s, g) if g is not None else None
    if before is not None:
        refs.append(before[1])
    return {"texts": store.content(refs) if refs else {}}


def _who(frame: Frame, key: str | None) -> str:
    name = frame.get(identity_c.IDENTITY(key)).name if key else ""
    return f"« {name} »" if name else phrase("expression.person.someone")


def _progress(g: Goal) -> str:
    if not g.max_steps:
        return ""
    left = g.max_steps - g.steps
    if g.steps <= 1:
        return phrase("goals.step.progress.starting")
    if left <= 1:
        return phrase("goals.step.progress.ending")
    return phrase("goals.step.progress.session", step=g.steps, total=g.max_steps)


#: les tâches montrées pendant un pas (les faites d'abord repliées : seules les dernières se disent)
PLAN_SHOWN = 20


def _plan(g: Goal, texts: Mapping[str, str]) -> str:
    """Son plan de travail : ce qui reste d'abord (les tâches demandées par l'opérateur avant les siennes),
    puis les dernières faites ; les outils goal_task_add / goal_task_update le tiennent à jour."""
    if not g.tasks:
        return ""
    open_ = [t for t in g.tasks if t.status != c.TASK_DONE]
    open_.sort(key=lambda t: (t.author != "operator", t.status != c.DOING, t.id))
    done = [t for t in g.tasks if t.status == c.TASK_DONE][-5:]
    marks = family("goals.task")
    asked = phrase("goals.step.asked")
    rows = []
    for t in [*open_, *done][:PLAN_SHOWN]:
        note = texts.get(t.note_ref, "") if t.note_ref else ""
        rows.append(f"- {t.id}. [{marks.get(t.status, t.status)}]{asked if t.author == 'operator' else ''} "
                    f"{texts.get(t.text_ref, phrase('goals.step.task_forgotten'))}" + (f" — {note}" if note else ""))
    return phrase("goals.step.plan") + "\n" + "\n".join(rows)


def when_words(at: int, now: int, frame: Frame) -> str:
    """Quand, en mots du calendrier (« ce matin », « hier soir », « il y a 3 jours »)."""
    tz = frame.env.tz_of(frame.root)
    then, today = local(at, tz), local(now, tz)
    days = (today.date() - then.date()).days
    part = "morning" if then.hour < 12 else "afternoon" if then.hour < 18 else "evening"
    if days <= 0:
        return phrase(f"expression.when.today.{part}")
    if days == 1:
        return phrase(f"expression.when.yesterday.{part}")
    return phrase("expression.when.days_ago", days=days)


def _last_time(before: tuple[int, str, int] | None, frame: Frame, texts: Mapping[str, str]) -> str:
    """Ce qu'elle avait retenu la dernière fois qu'elle a exploré la même curiosité : elle repart de là, pas d'une
    page blanche (vide : jamais, ou oublié avec la personne qu'il concernait)."""
    text = texts.get(before[1], "") if before is not None else ""
    if before is None or not text:
        return ""
    return phrase("goals.step.last_time", when=when_words(before[0], frame.now, frame),
                  kept=_clip(text, KEPT_SHOWN))


def _what(g: Goal, frame: Frame, texts: Mapping[str, str],
          before: tuple[int, str, int] | None = None) -> list[str]:
    """Ce à quoi elle travaille, en mots à elle : d'où ça vient et ce qu'elle peut en faire — et, pour une curiosité
    qu'elle a déjà explorée, ce qu'elle en avait retenu."""
    title = titled(g, texts)[0] or phrase("goals.step.no_title")
    lines = [phrase("goals.step.goal", title=title)]
    person = g.owner or (g.about[0] if g.about else None)
    name = frame.get(identity_c.IDENTITY(person)).name if person else ""
    when = f" {when_words(g.origin_at, frame.now, frame)}" if g.origin_at else ""
    quoted = phrase("goals.step.quoted") if _origin(g, texts) else ""
    if g.kind != c.EXPLORATION:
        return lines
    if musing(g) and g.origin == c.FROM_TALK:
        who = f"« {name} »" if name else phrase("goals.step.someone")
        lines.append(phrase("goals.step.talk_musing", who=who, when=when, quoted=quoted))
        lines.append(phrase("goals.step.daydream_rule"))
    elif musing(g):
        lines.append(phrase("goals.step.interest_musing"))
        lines.append(phrase("goals.step.daydream_rule"))
    elif reflective(g) and name:
        lines.append(phrase("goals.step.confided", name=name, when=when, quoted=quoted))
        closeness = family("goals.step.closeness").get(frame.get(social_c.CLOSENESS(person)))
        if closeness:
            lines.append(phrase("goals.step.closeness_line", name=name, closeness=closeness))
        lines.append(phrase("goals.step.reflect_on", name=name))
        lines.append(phrase("goals.step.reflection_rule"))
    elif reflective(g):
        lines.append(phrase("goals.step.came", when=when, quoted=quoted))
        lines.append(phrase("goals.step.reflection_rule"))
    elif g.origin == c.FROM_SIGNAL:
        lines.append(phrase("goals.step.noticed", when=when))
    elif g.origin == c.FROM_INTEREST:
        lines.append(phrase("goals.step.interest"))
    last = _last_time(before, frame, texts)
    if last:
        lines.append(last)
    return lines


@GOALS.section("step", zone=Zone.VOLATILE, episodes=[Kind.STEP], trim_rank=90, title=phrase("goals.step.title"),
               reads=[identity_c.IDENTITY, social_c.CLOSENESS])
def _step(s: GoalsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    gid = _subject(frame)
    g = s.goals.get(gid) if gid is not None else None
    if g is None:
        return None
    data = enrich.get("goals") or {}
    texts: Mapping[str, str] = data.get("texts") or {}
    before = kept_before(s, g)
    lines = _what(g, frame, texts, before)
    # ce qu'elle avait retenu la dernière fois a sa propre sensibilité : la section prend la plus haute
    level = max(g.sensitivity, before[2]) if before is not None and texts.get(before[1]) else g.sensitivity
    if g.kind != c.EXPLORATION and g.details_ref and texts.get(g.details_ref):
        lines.append(phrase("goals.step.frame", details=texts[g.details_ref]))
    instructions = [texts[r] for r in g.instructions if texts.get(r)]
    if instructions:
        lines.append(phrase("goals.step.instructions") + "\n"
                     + "\n".join(f"- {i}" for i in instructions[-INSTRUCTIONS_SHOWN:]))
    progress = _progress(g)
    if g.summary_ref and texts.get(g.summary_ref):
        summary = texts[g.summary_ref]
        lines.append(phrase("goals.step.where_progress_summary", progress=progress, summary=summary) if progress
                     else phrase("goals.step.where_summary", summary=summary))
    elif progress:
        lines.append(phrase("goals.step.where_progress", progress=progress))
    if g.priority in (c.HIGH, c.URGENT):
        lines.append(phrase("goals.step.urgent") if g.priority == c.URGENT else phrase("goals.step.high"))
    plan = _plan(g, texts)
    if plan:
        lines.append(plan)
    notes = [texts[r] for r in g.notes if texts.get(r)]
    if notes:
        lines.append(phrase("goals.step.notebook") + "\n" + "\n".join(f"- {n}" for n in notes[-3:]))
    lines.append(phrase("goals.step.rules"))
    return SectionBody("\n".join(lines), level=level, provenance=(f"goal:{g.id}",))


#: ce qui a fait naître une exploration est la matière même de la séance : cité, coupé en premier, mais jamais
#: au point de disparaître (le composeur coupe ce qui vient d'ailleurs avant tout le reste, jusqu'à ce plancher)
ORIGIN_FLOOR = 400


@GOALS.section("step_origin", zone=Zone.VOLATILE, episodes=[Kind.STEP], trim_rank=0, untrusted=True,
               floor_chars=ORIGIN_FLOOR, title=phrase("goals.origin_title"))
def _step_origin(s: GoalsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """Ce qui a fait naître une exploration (ce qu'on lui a confié, un titre d'article) : cité, jamais le but."""
    gid = _subject(frame)
    g = s.goals.get(gid) if gid is not None else None
    if g is None or g.kind != c.EXPLORATION:
        return None
    text = _origin(g, (enrich.get("goals") or {}).get("texts") or {})
    return SectionBody(text, level=g.sensitivity, provenance=(f"goal:{g.id}",)) if text else None


#: l'échange d'où vient une réflexion : cherché dans les heures qui précèdent sa naissance, depuis le dernier silence
EXCHANGE_LOOKBACK = 3 * HOUR
EXCHANGE_GAP = 45 * MINUTE
EXCHANGE_LINES = 12
#: ses mots à elle, coupés plus court que ceux de l'autre (c'est l'autre qu'elle relit)
THEIR_CLIP, MINE_CLIP = 240, 140
#: l'échange se coupe en premier (il vient d'ailleurs), mais jamais au point de disparaître
EXCHANGE_FLOOR = 500
#: ce qui se passe dans sa vie : les moments notés, puis ce qu'elle a appris d'elle récemment
LIFE_SHOWN, BELIEFS_SHOWN = 4, 5
BELIEFS_SINCE = 14 * DAY


def exchange_of(store: Any, frame: Frame, person: str, until: int, public: bool) -> list[tuple[bool, str]]:
    """Le dernier échange avec cette personne avant ``until`` (depuis le dernier silence de trois quarts d'heure),
    dans le fil d'où vient la pensée (un salon, ou leur fil privé) : (c'est elle qui parle, le texte), au plus
    quelques lignes — la fin, là où c'est venu."""
    handles = tuple(frame.get(identity_c.HANDLES(person)) or (person,))
    marks = ",".join("?" * len(handles))
    rows = store.query_mind(
        f"SELECT at, role, text, room FROM {transcript_c.THREAD_TABLE} WHERE person IN ({marks}) AND at >= ? "
        "AND at <= ? ORDER BY id", (*handles, until - EXCHANGE_LOOKBACK, until))
    rows = [r[:3] for r in rows if (r[3] is not None) == public]
    start = 0
    for i in range(1, len(rows)):
        if rows[i][0] - rows[i - 1][0] > EXCHANGE_GAP:
            start = i
    return [(role == "user", _clip(str(text), THEIR_CLIP if role == "user" else MINE_CLIP))
            for _at, role, text in rows[start:][-EXCHANGE_LINES:] if str(text or "").strip()]


def life_of(store: Any, frame: Frame, person: str) -> list[tuple[str, int]]:
    """Ce qu'elle sait de ce que vit cette personne en ce moment : les moments de sa vie qu'elle a notés (une
    situation en cours, ce qui vient de se passer, ce qui approche), puis ce qu'elle a appris d'elle ces deux
    dernières semaines — (texte, sensibilité). Rien d'autre : ce qu'elle ne sait pas, une réflexion ne l'invente
    pas."""
    tz = frame.env.tz_of(frame.root)
    moments = sorted(frame.get(memory_c.LIFE_EVENTS(person)) or (), key=lambda m: (-m.when, m.id))[:LIFE_SHOWN]
    texts = store.content([m.text_ref for m in moments if m.text_ref])
    out: list[tuple[str, int]] = []
    for m in moments:
        text = texts.get(m.text_ref)
        if not text:
            continue
        if m.ongoing:
            # finie : la personne l'a dit, plus au présent
            when = phrase("goals.life.over") if m.ended_at else phrase("goals.life.now")
        else:
            when = when_fr(m.when, frame.now, tz) if m.when <= frame.now else phrase("goals.life.ahead")
        told = [t for t in m.told_by if t != person]
        heard = phrase("goals.life.heard", names=_names(frame, told)) if told else ""
        out.append((phrase("goals.life.item", text=text, when=when, heard=heard), int(m.sensitivity)))
    rows = store.query_mind(
        f"SELECT text, sensitivity, about FROM {memory_c.ITEMS_TABLE} WHERE kind=? AND status='active' AND "
        "about_self=0 AND born_at >= ? AND about LIKE ? ORDER BY born_at DESC, id DESC LIMIT ?",
        (memory_c.BELIEF, frame.now - BELIEFS_SINCE, f'%"{person}"%', BELIEFS_SHOWN * 2))
    beliefs = [(str(t), int(sv)) for t, sv, about in rows if person in _listed(about)][:BELIEFS_SHOWN]
    return out + [b for b in beliefs if b[0] not in {t for t, _ in out}]


def _listed(raw: Any) -> list[str]:
    try:
        got = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return []
    return [str(x) for x in got] if isinstance(got, list) else []


def _names(frame: Frame, people: list[str]) -> str:
    someone = phrase("expression.person.someone")
    return ", ".join(f"« {n} »" if (n := frame.get(identity_c.IDENTITY(p)).name) else someone for p in people)


def _clip(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


@GOALS.enricher("goals_context", episodes=[Kind.STEP], deadline_ms=1500,
                reads=[identity_c.HANDLES, identity_c.IDENTITY, memory_c.LIFE_EVENTS])
async def _context(s: GoalsState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, Any] | None:
    """Ce qu'une réflexion sur quelqu'un a sous les yeux : l'échange d'où elle vient, et ce qui se passe dans sa
    vie (sonde réelle du 2026-10-03 : avec « laisse tomber » pour toute matière, elle écrivait « c'est venu comme
    ça, sans contexte » et finissait par inventer)."""
    store = ports.get("store")
    gid = _subject(frame)
    g = s.goals.get(gid) if gid is not None else None
    if store is None or g is None or g.kind != c.EXPLORATION or musing(g) or not reflective(g) or not g.owner:
        return None
    public = g.sensitivity <= Sensitivity.ANODYNE  # une pensée née dans un salon est anodine (ADR 0034)
    exchange = exchange_of(store, frame, g.owner, g.origin_at, public) \
        if g.origin == c.FROM_EXCHANGE and g.origin_at else []
    return {"exchange": exchange, "life": life_of(store, frame, g.owner)}


@GOALS.section("step_exchange", zone=Zone.VOLATILE, episodes=[Kind.STEP], trim_rank=5, untrusted=True,
               floor_chars=EXCHANGE_FLOOR, title=phrase("goals.exchange.title"), reads=[identity_c.IDENTITY])
def _step_exchange(s: GoalsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """L'échange d'où vient la pensée, tel qu'il s'est passé : ce que la personne a dit, ce qu'elle a répondu."""
    gid = _subject(frame)
    g = s.goals.get(gid) if gid is not None else None
    lines = (enrich.get("goals_context") or {}).get("exchange") or []
    if g is None or not lines:
        return None
    name = frame.get(identity_c.IDENTITY(g.owner)).name if g.owner else ""
    who = name or phrase("goals.exchange.other")
    body = "\n".join(phrase("goals.exchange.theirs", who=who, text=text) if theirs else
                     phrase("goals.exchange.mine", text=text) for theirs, text in lines)
    return SectionBody(body, level=g.sensitivity, provenance=(f"goal:{g.id}",))


@GOALS.section("step_life", zone=Zone.VOLATILE, episodes=[Kind.STEP], trim_rank=60,
               title=phrase("goals.life.title"), reads=[identity_c.IDENTITY])
def _step_life(s: GoalsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """Ce qu'elle sait de ce que vit la personne à qui elle repense — pour qu'elle n'ait pas à le deviner."""
    gid = _subject(frame)
    g = s.goals.get(gid) if gid is not None else None
    items = (enrich.get("goals_context") or {}).get("life") or []
    if g is None or not items:
        return None
    name = frame.get(identity_c.IDENTITY(g.owner)).name if g.owner else ""
    head = phrase("goals.life.head", name=name) if name else phrase("goals.life.head_unnamed")
    body = head + "\n" + "\n".join(f"- {text}" for text, _ in items)
    return SectionBody(body, level=max([g.sensitivity, *(sv for _, sv in items)]), provenance=(f"goal:{g.id}",))


def _origin(g: Goal, texts: Mapping[str, str]) -> str:
    """Ce qui a fait naître une exploration (ce qu'on lui a confié, un titre d'article) — à ne montrer que cité."""
    if g.kind != c.EXPLORATION:
        return ""
    return titled(g, texts)[1] or (texts.get(g.details_ref, "") if g.details_ref else "")


def _quoted(g: Goal, texts: Mapping[str, str]) -> str:
    """En conversation, le texte venu d'ailleurs d'où une exploration est née (un titre d'article, l'objet d'un
    mail) : cité, inerte, jamais comme le but. Ce qu'on lui a confié ne se redit pas ici (son titre suffit)."""
    external = titled(g, texts)[1]
    return "\n" + cited(external, ORIGIN_CITED) if external else ""


def _levels(g: Goal, person: str | None, frame: Frame) -> tuple[int, bool] | None:
    """(niveau, témoin) d'un contenu du but devant cette audience — ou rien
    s'il ne peut pas s'y dire. Ce qui ne concerne que l'interlocuteur est à lui."""
    aud = frame.audience
    if aud is None or not hearable(g.about, g.sensitivity, person, aud.level, aud.witness_level, aud.private_ok):
        return None
    others = [a for a in g.about if a != person]
    return (g.sensitivity, person in g.about) if others else (0, False)


@GOALS.section("subject", zone=Zone.VOLATILE, episodes=[Kind.INITIATIVE], trim_rank=90)
def _subject_section(s: GoalsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """Le rappel à dire, ou ce qu'elle a mené à bout — à la mesure du lien."""
    gid = _subject(frame)
    g = s.goals.get(gid) if gid is not None else None
    if g is None:
        return None
    texts: Mapping[str, str] = (enrich.get("goals") or {}).get("texts") or {}
    title = titled(g, texts)[0] or None
    ep = frame.episode
    person = frame.get(identity_c.PERSON(ep.target)) if ep is not None and ep.target else None
    got = _levels(g, person, frame)
    args = ep.attrs.get("args") if ep is not None else None
    share = str(args.get("share", MENTION)) if args else MENTION
    if g.kind == c.REMINDER:
        if not title or got is None:
            return None
        when = phrase("goals.subject.due", time=f"{local(g.due, frame.env.tz_of(frame.root)):%H:%M}") \
            if g.due else ""
        return SectionBody(f"{title}{when}", level=got[0], witness=got[1], title=phrase("goals.subject.reminder_title"),
                           provenance=(f"goal:{g.id}",))
    # une inquiétude pour la personne à qui elle écrit : pas un exploit, ce à quoi elle a repensé pour elle
    worry = worry_of(g, person)
    heading = phrase("goals.subject.reflected_title") if worry else phrase("goals.subject.achieved_title")
    if got is None or share == MENTION or not title:
        # une simple mention : le titre seulement s'il peut s'entendre, sinon rien de précis
        shown = title if title and got is not None and g.sensitivity <= 1 else phrase("goals.subject.something")
        return SectionBody(shown, level=0, title=heading)
    result = texts.get(g.result_ref, "")
    if share == FULL:
        drawn = phrase("goals.subject.drawn_reflection", result=result) if worry else \
            phrase("goals.subject.drawn", result=result)
        body = (f"{title}\n{drawn}" if result else title) + _quoted(g, texts)
    else:
        first = result.split(". ")[0].strip() if result else ""
        body = title + (phrase("goals.subject.in_short", first=first) if first else "")
    return SectionBody(body, level=got[0], witness=got[1], title=heading, provenance=(f"goal:{g.id}",))


@GOALS.section("goals", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, after=["thoughts"], trim_rank=45,
               title=phrase("goals.live.title"), reads=[identity_c.PERSON])
def _live_section(s: GoalsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    texts: Mapping[str, str] = (enrich.get("goals") or {}).get("texts") or {}
    ep, aud = frame.episode, frame.audience
    if aud is None:
        return None
    person = frame.get(identity_c.PERSON(ep.target)) if ep is not None and ep.target else None
    initiative = ep is not None and ep.kind == Kind.INITIATIVE
    lines, level, witness, theirs = [], 0, False, False
    tz = frame.env.tz_of(frame.root)
    for g in _recent(s, frame.now)[-SHOWN * 2:]:
        title = titled(g, texts)[0]
        if not title or not hearable(g.about, g.sensitivity, person, aud.level, aud.witness_level, aud.private_ok):
            continue
        if musing(g):
            # une rêverie n'est ni une nouvelle ni une réussite : rien de neuf n'est arrivé. Elle peut le dire si on
            # lui demande ce qu'elle fait ; elle n'en fait pas la matière d'un message (sonde du 2026-10-02 : « je
            # viens de finir de rêvasser autour de… » dans presque chaque initiative)
            if initiative:
                continue
            if g.status == c.ACHIEVED:
                lines.append("- " + phrase("goals.live.mused", when=when_words(g.closed_at, frame.now, frame),
                                           title=title))
            else:
                lines.append("- " + phrase("goals.live.musing", title=title))
        elif g.status == c.ACHIEVED:
            lines.append("- " + phrase("goals.live.achieved", title=title, quoted=_quoted(g, texts)))
        elif status(g, frame.now) == c.PAUSED:
            lines.append("- " + phrase("goals.live.paused", title=title))
        elif g.kind == c.REMINDER:
            when = date_time(local(g.due, tz)) if g.due else phrase("goals.live.soon")
            lines.append("- " + phrase("goals.live.reminder", who=_who(frame, g.address), when=when, title=title))
            theirs = theirs or (person is not None and g.owner == person and not g.delivered)
        else:
            waiting = ""
            if g.status == c.WAITING:
                waiting = (phrase("goals.live.waiting_for", who=_who(frame, g.wait_for)) if g.wait_for
                           else phrase("goals.live.waiting"))
            lines.append("- " + phrase("goals.live.exploring", title=title,
                                       progress=_progress(g) or phrase("goals.live.ongoing"), waiting=waiting,
                                       quoted=_quoted(g, texts)))
        if any(a != person for a in g.about):  # ce qui ne concerne que l'interlocuteur ne compte pas ici
            level = max(level, g.sensitivity)
            witness = witness or person in g.about
        if len(lines) >= SHOWN:
            break
    if not lines:
        return None
    if theirs and ep is not None and ep.kind == Kind.REPLY:  # l'outil ne sert qu'en réponse
        lines.append(phrase("goals.live.remind_change"))
    return SectionBody("\n".join(lines), level=level, witness=witness)


def step_brief(frame: Frame, req: Any) -> str:
    return phrase("goals.step.brief")
