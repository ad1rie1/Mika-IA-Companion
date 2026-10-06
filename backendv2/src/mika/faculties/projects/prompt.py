"""Ce que les projets mettent dans le prompt.

- **Pendant une exécution** (``WORK`` ou ``JOB``) : le projet — son cadre, son
  mode, l'objectif visé (et les autres), les décisions en vigueur, les
  consignes reçues (la plus récente prime), son carnet, ce que sont devenues
  ses demandes (leur état seulement), l'atelier (son arbre, ce qui n'y est pas
  enregistré : une exécution interrompue y a laissé son travail) et son dépôt
  distant ; ce qu'une commande réseau a rendu, **cité** (une donnée d'Internet,
  jamais une consigne) ; ce que la personne à qui elle a demandé un coup de
  main lui a écrit en privé depuis, **cité** ; le budget de l'exécution (ses
  tours, son temps).
- **Un récit, une demande d'aide** : ce qu'elle a mené à bout (tout ce qui
  l'a été depuis le récit précédent), ou ce qui la bloque, à la mesure du lien.
- **En conversation** : ses projets (« tu travailles sur quoi ? » est une
  question sur sa vie) — où chacun en est, sa dernière exécution, ce qui vient
  ou ce qui bloque, et pour qui s'occupe d'elle ce qui attend son accord et
  l'outil pour les piloter ensemble (``project_steer``, en réponse) ;
  filtrés comme la mémoire.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mika.contracts import identity as identity_c
from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.contracts import transcript as transcript_c
from mika.faculties.projects.faculty import (
    ON_DEMAND,
    PROJECTS,
    Decision,
    Objective,
    Project,
    ProjectsState,
    answered,
    cadence,
    effect_words,
    live,
    objective_of,
    params,
    pick,
)
from mika.faculties.projects.tools import RUNS, steers, written
from mika.faculties.projects.work import FULL, MENTION, untold
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.faculty import Zone
from mika.kernel.frame import Frame
from mika.kernel.prompt import SectionBody
from mika.vocab.episodes import CONVERSATIONAL, Kind, project_of
from mika.vocab.phrasebook import family, phrase
from mika.vocab.privacy import hearable

SHOWN = 4
INSTRUCTIONS_SHOWN = 3
#: les décisions en vigueur montrées pendant une exécution (les plus récentes)
DECISIONS_SHOWN = 12
TREE_SHOWN = 60
PENDING_SHOWN = 20
#: les objectifs qu'un récit nomme (les plus récents) ; ceux d'avant sont comptés
TOLD_SHOWN = 8


def _project(s: ProjectsState, frame: Frame) -> tuple[Project, Objective | None] | None:
    ep = frame.episode
    if ep is None:
        return None
    pid = project_of(ep.target)
    got = objective_of(ep.attrs.get("subject"))
    if pid is None and got is not None:
        pid = got[0]
    p = s.projects.get(pid) if pid is not None else None
    if p is None:
        return None
    o = next((x for x in p.objectives if got is not None and got[0] == p.id and x.id == got[1]), None)
    return p, o


def _refs(p: Project) -> list[str]:
    objectives = [r for o in p.objectives for r in (o.text_ref, o.note_ref, o.result_ref, o.need_ref)]
    decisions = [r for d in p.decisions for r in (d.title_ref, d.choice_ref, d.reason_ref, d.context_ref)]
    deposits = [note for _, _, note in p.deposits]
    refusals = [note for _, note in p.refusals]
    return [r for r in (p.title_ref, p.description_ref, p.summary_ref, *p.notes, *p.instructions, *objectives,
                        *decisions, *deposits, *refusals) if r]


def _talk_refs(p: Project) -> list[str]:
    """Ce qu'une conversation peut dire d'un projet : son titre, son dernier compte rendu, ce qui vient."""
    opened = [o for o in p.objectives if o.status in (c.OPEN, c.BLOCKED)][:3]
    return [r for r in (p.title_ref, p.summary_ref, *(o.text_ref for o in opened), *(o.need_ref for o in opened))
            if r]


@PROJECTS.enricher("projects", episodes=[*RUNS, *CONVERSATIONAL], deadline_ms=1500)
async def _texts(s: ProjectsState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, Any] | None:
    store = ports.get("store")
    if store is None:
        return None
    ep = frame.episode
    chosen: list[Project] = []
    got = _project(s, frame)
    if got is not None:
        chosen.append(got[0])
    if ep is not None and ep.kind in CONVERSATIONAL:
        chosen += [p for p in _recent(s)[-SHOWN * 2:] if p not in chosen]
    refs = [r for p in chosen for r in (_refs(p) if got is not None and p is got[0] else _talk_refs(p))]
    return {"texts": store.content(refs) if refs else {}}


@PROJECTS.enricher("projects_tree", episodes=RUNS, deadline_ms=3000)
async def _tree(s: ProjectsState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, Any] | None:
    """L'arbre de l'atelier et ce qui n'y est pas enregistré — à part : un atelier illisible (un lien cassé, un
    git qui ne répond pas) ne doit jamais rendre l'exécution aveugle à son projet."""
    got = _project(s, frame)
    atelier = ports.get("workshop")
    if got is None or atelier is None or not atelier.exists(got[0].id):
        return None
    pid = got[0].id
    out: dict[str, Any] = {}
    try:
        out["tree"] = await atelier.tree(pid)
    except (OSError, ValueError) as exc:
        out["tree_error"] = str(exc)[:200]
    try:
        out["pending"] = await atelier.pending(pid)
    except (OSError, ValueError):
        out["pending"] = []
    return out


#: ce qu'on cite de sa réponse : ses premiers messages privés depuis la demande, chacun coupé
ANSWER_LINES, ANSWER_CLIP = 10, 400


@PROJECTS.enricher("projects_answer", episodes=RUNS, deadline_ms=1500, reads=[identity_c.HANDLES])
async def _answer(s: ProjectsState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, Any] | None:
    """Ce que la personne à qui elle a demandé un coup de main lui a écrit depuis, en privé : ses messages à elle
    seule (pas un salon, pas le fil d'une autre), après la demande."""
    store = ports.get("store")
    got = _project(s, frame)
    o = got[1] if got is not None else None
    if store is None or o is None or not o.asked_to or not answered(o):
        return None
    handles = tuple(frame.get(identity_c.HANDLES(o.asked_to)) or (o.asked_to,))
    marks = ",".join("?" * len(handles))
    rows = store.query_mind(
        f"SELECT text FROM {transcript_c.THREAD_TABLE} WHERE person IN ({marks}) AND role='user' AND room IS NULL "
        "AND at > ? ORDER BY id LIMIT ?", (*handles, o.asked_at, ANSWER_LINES))
    lines = [_clip(str(text), ANSWER_CLIP) for (text,) in rows if str(text or "").strip()]
    return {"lines": lines} if lines else None


def _clip(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _recent(s: ProjectsState) -> list[Project]:
    return sorted((p for p in s.projects.values() if live(p)), key=lambda p: p.id)


def _who(frame: Frame, key: str | None) -> str:
    name = frame.get(identity_c.IDENTITY(key)).name if key else ""
    return f"« {name} »" if name else phrase("expression.person.someone")


def _objective_line(o: Objective, texts: Mapping[str, str], pm: Any, now: int) -> str:
    text = texts.get(o.text_ref, phrase("projects.objective.forgotten"))
    status = family("projects.objective.status").get(o.status, o.status)
    if o.kind == c.CONSTANT and o.status != c.OPEN:
        state = phrase("projects.objective.aside", status=status)
    elif o.kind == c.CONSTANT:
        last = phrase("projects.objective.last_pass", ago=ago(now - o.passed_at)) if o.passed_at else \
            phrase("projects.objective.never")
        state = phrase("projects.objective.constant", every=_every(cadence(o, pm)), last=last)
    else:
        state = phrase("projects.objective.once", status=status)
    return "- " + phrase("projects.objective.line", id=o.id, state=state, text=text)


def ago(us: int) -> str:
    if us < HOUR:
        return phrase("projects.duration.minutes", n=max(1, us // MINUTE))
    if us < 2 * DAY:
        return phrase("projects.duration.hours", n=us // HOUR)
    return phrase("projects.duration.days", n=us // DAY)


def _every(us: int) -> str:
    return phrase("projects.duration.days", n=us // DAY) if us >= 2 * DAY and us % DAY == 0 else \
        phrase("projects.duration.hours", n=max(1, round(us / HOUR)))


def _decision_line(d: Decision, texts: Mapping[str, str]) -> str:
    why = texts.get(d.reason_ref, "") if d.reason_ref else ""
    forgotten = phrase("projects.decision.forgotten")
    return "- " + phrase("projects.decision.line", id=d.id, title=texts.get(d.title_ref, forgotten),
                         choice=texts.get(d.choice_ref, forgotten)) + \
        (phrase("projects.decision.because", why=why) if why else "")


def run_rules(pm: Any) -> str:
    """Comment se conclut une exécution, et ce qu'elle a de tours et de temps (dits, pas devinés)."""
    return phrase("projects.run.rules", minutes=max(1, pm.run_programs_us // MINUTE))


@PROJECTS.section("project", zone=Zone.VOLATILE, episodes=RUNS, trim_rank=90, title=phrase("projects.run.title"))
def _run_section(s: ProjectsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    got = _project(s, frame)
    if got is None:
        return None
    p, target = got
    data = enrich.get("projects") or {}
    texts: Mapping[str, str] = data.get("texts") or {}
    pm = params(frame.env.params_of("projects", frame.root))
    who = phrase("projects.run.own") if p.authority == c.SELF else \
        phrase("projects.run.confided", who=_who(frame, p.address or p.owner))
    # le mode de cette exécution : celui du projet, ou celui d'un réveil par API qui le lance (ADR 0068)
    mode = c.PLAIN if frame.episode is not None and frame.episode.kind == Kind.JOB else c.PERSONA
    lines = [phrase("projects.run.head", id=p.id, title=texts.get(p.title_ref, phrase("projects.run.no_title")),
                    who=who), family("projects.run.mode")[mode]]
    if p.description_ref and texts.get(p.description_ref):
        lines.append(phrase("projects.run.own_aim", text=texts[p.description_ref]) if p.authority == c.SELF
                     else phrase("projects.run.confided_frame", text=texts[p.description_ref]))
    if target is not None:
        lines.append(phrase("projects.run.target") + "\n" + _objective_line(target, texts, pm, frame.now))
        if target.kind == c.CONSTANT:
            lines.append(phrase("projects.run.constant"))
        if target.note_ref and texts.get(target.note_ref):
            lines.append(phrase("projects.run.note", note=texts[target.note_ref]))
        if target.need_ref and texts.get(target.need_ref):
            # sa réponse est arrivée : elle l'a sous les yeux, elle n'a ni à l'attendre ni à la redemander
            reply = phrase("projects.run.reply") if (enrich.get("projects_answer") or {}).get("lines") else ""
            lines.append(phrase("projects.run.awaited", need=texts[target.need_ref], reply=reply))
    others = [o for o in p.objectives if target is None or o.id != target.id]
    if others:
        # une exécution sans objectif visé (un réveil par API, ADR 0068) les voit tous
        heading = phrase("projects.run.others") if target is not None else phrase("projects.run.all")
        lines.append(heading + "\n" + "\n".join(
            _objective_line(o, texts, pm, frame.now) for o in others if o.status != c.DROPPED))
    decisions = [d for d in p.decisions if d.status == c.IN_FORCE][-DECISIONS_SHOWN:]
    if decisions:
        lines.append(phrase("projects.run.decisions") + "\n"
                     + "\n".join(_decision_line(d, texts) for d in decisions))
    instructions = [texts[r] for r in p.instructions if texts.get(r)]
    if instructions:
        lines.append(phrase("projects.run.instructions") + "\n"
                     + "\n".join(f"- {i}" for i in instructions[-INSTRUCTIONS_SHOWN:]))
    if p.summary_ref and texts.get(p.summary_ref):
        lines.append(phrase("projects.run.summary", summary=texts[p.summary_ref]))
    notes = [texts[r] for r in p.notes if texts.get(r)]
    if notes:
        lines.append(phrase("projects.run.notebook") + "\n" + "\n".join(f"- {n}" for n in notes[-3:]))
    if p.deposits:
        lines.append(phrase("projects.run.deposits") + "\n" + "\n".join(
            "- " + phrase("projects.run.deposit", name=name, size=size)
            + (f" — {texts[note]}" if note and texts.get(note) else "")
            for name, size, note in p.deposits[-3:]))
    if p.effects:  # leur état seulement : ce que le réseau a rendu est cité à part
        refused = {f"#{n}": texts.get(ref) for n, ref in p.refusals}
        lines.append(phrase("projects.run.effects") + "\n" + "\n".join(
            f"- {e}" + (phrase("projects.run.refused_why", why=why[:200]) if (why := refused.get(e.split(' ', 1)[0]))
                        else "")
            for e in p.effects[-3:]))
    if p.remote:
        lines.append(phrase("projects.run.remote_auto", remote=p.remote, branch=p.branch) if p.auto_push else
                     phrase("projects.run.remote_manual", remote=p.remote, branch=p.branch))
    if "workshop" in p.bundles:
        lines += _atelier_lines(enrich.get("projects_tree") or {})
    lines.append(run_rules(pm))
    return SectionBody("\n".join(lines), level=p.sensitivity, provenance=(f"project:{p.id}",))


def _atelier_lines(tree: Mapping[str, Any]) -> list[str]:
    files = tree.get("tree")
    if files is None:
        why = tree.get("tree_error")
        return [phrase("projects.run.tree_unreadable_why", why=why) if why else phrase("projects.run.tree_unreadable")]
    out = [phrase("projects.run.tree") + "\n"
           + ("\n".join(f"- {f}" for f in files[:TREE_SHOWN]) if files else f"- {phrase('projects.run.tree_empty')}")]
    pending = tree.get("pending") or []
    if pending:
        out.append(phrase("projects.run.pending", files=", ".join(pending[:PENDING_SHOWN])
                          + (" …" if len(pending) > PENDING_SHOWN else "")))
    return out


#: ce que sa dernière commande réseau a rendu est ce sur quoi elle travaille : coupé en premier (venu d'Internet),
#: jamais au point de disparaître
NETWORK_FLOOR = 600


@PROJECTS.section("project_network", zone=Zone.VOLATILE, episodes=RUNS, trim_rank=0, untrusted=True,
                  floor_chars=NETWORK_FLOOR, title=phrase("projects.network.title"))
def _network_section(s: ProjectsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """La sortie de sa dernière commande réseau : une donnée venue d'Internet, citée, coupée en premier — jusqu'à
    son plancher (c'est ce sur quoi elle travaille)."""
    got = _project(s, frame)
    if got is None or not got[0].network_out:
        return None
    p = got[0]
    return SectionBody(phrase("projects.network.head", ago=ago(frame.now - p.network_out_at)) + f"\n{p.network_out}",
                       level=0, provenance=(f"project:{p.id}",))


#: sa réponse est ce qui débloque l'objectif : citée (ses mots, une donnée), coupée tôt, jamais au point de disparaître
ANSWER_FLOOR = 500


@PROJECTS.section("project_answer", zone=Zone.VOLATILE, episodes=RUNS, trim_rank=5, untrusted=True,
                  floor_chars=ANSWER_FLOOR, title=phrase("projects.answer.title"), reads=[identity_c.IDENTITY])
def _answer_section(s: ProjectsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """Ce que la personne à qui elle a demandé un coup de main lui a écrit depuis, en privé : cité, pour que
    l'exécution reparte avec la réponse sous les yeux plutôt que de deviner ou de redemander."""
    got = _project(s, frame)
    lines = (enrich.get("projects_answer") or {}).get("lines") or []
    if got is None or got[1] is None or not lines:
        return None
    p, o = got
    body = (phrase("projects.answer.head", who=_who(frame, o.asked_to), ago=ago(frame.now - o.asked_at)) + "\n"
            + "\n".join(f"- {line}" for line in lines))
    return SectionBody(body, level=written(p), provenance=(f"project:{p.id}",))


@PROJECTS.section("project_share", zone=Zone.VOLATILE, episodes=[Kind.INITIATIVE], trim_rank=90,
                  title=phrase("projects.share.title"))
def _share_section(s: ProjectsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """Ce qu'elle a mené à bout dans un projet depuis son dernier récit — à la mesure du lien avec qui l'écoute ;
    ou, quand elle a besoin de qui le lui a confié, ce qui la bloque."""
    ep = frame.episode
    got = objective_of(ep.attrs.get("subject")) if ep is not None else None
    p = s.projects.get(got[0]) if got is not None else None
    o = next((x for x in p.objectives if x.id == got[1]), None) if p is not None and got is not None else None
    if p is None or o is None:
        return None
    store = (enrich.get("projects") or {}).get("texts") or {}
    title, objective = store.get(p.title_ref), store.get(o.text_ref)
    args = ep.attrs.get("args") if ep is not None else None
    reasons = ep.attrs.get("reasons") or () if ep is not None else ()
    share = str(args.get("share", MENTION)) if args else MENTION
    aud = frame.audience
    person = frame.get(identity_c.PERSON(ep.target)) if ep is not None and ep.target else None
    if aud is None or not hearable(p.about, written(p), person, aud.level, aud.witness_level, aud.private_ok) \
            or (share == MENTION and c.NEED not in reasons) or not title:
        return SectionBody(phrase("projects.share.something"), level=0)
    level = written(p) if any(a != person for a in p.about) else 0
    if c.NEED in reasons:
        need = store.get(o.need_ref, "") or store.get(o.result_ref, "")
        state = phrase("projects.share.blocked") if o.status == c.BLOCKED else phrase("projects.share.waiting")
        body = phrase("projects.share.need_head", title=title, objective=objective or "…", state=state)
        if need:
            body += "\n" + phrase("projects.share.need", need=need)
        return SectionBody(body, level=level, title=phrase("projects.share.need_title"),
                           provenance=(f"project:{p.id}",))
    pm = params(frame.env.params_of("projects", frame.root))
    told = [x for x in untold(p, frame.now, pm) if x.id != o.id] + [o]
    if len(told) > 1:  # un point : tout ce qu'elle a mené à bout depuis le précédent, le plus récent en dernier
        lines = [phrase("projects.share.many", title=title)]
        if len(told) > TOLD_SHOWN:
            lines.append("- " + phrase("projects.share.more", count=len(told) - TOLD_SHOWN))
        for x in told[-TOLD_SHOWN:]:
            result = store.get(x.result_ref, "")
            line = f"- {store.get(x.text_ref) or phrase('projects.share.an_objective')}"
            if share == FULL and result:
                line += "\n  " + phrase("projects.share.drawn_item", result=result)
            elif result:
                line += phrase("projects.share.in_short", first=result.split(". ")[0].strip())
            lines.append(line)
        return SectionBody("\n".join(lines), level=level, provenance=(f"project:{p.id}",))
    result = store.get(o.result_ref, "")
    body = phrase("projects.share.one", title=title, objective=objective or phrase("projects.share.an_objective"))
    if share == FULL and result:
        body += "\n" + phrase("projects.share.drawn", result=result)
    elif result:
        body += phrase("projects.share.in_short", first=result.split(". ")[0].strip())
    return SectionBody(body, level=level, provenance=(f"project:{p.id}",))


def _next_words(p: Project, texts: Mapping[str, str], now: int, pm: Any) -> str:
    """Ce qui vient (l'objectif de la prochaine exécution) ou ce qui bloque, en une ligne."""
    blocked = next((o for o in p.objectives if o.status == c.BLOCKED), None)
    if blocked is not None and texts.get(blocked.text_ref):
        return phrase("projects.live.blocked", text=texts[blocked.text_ref])
    waiting = next((o for o in p.objectives if o.status == c.OPEN and o.need_ref), None)
    if waiting is not None and texts.get(waiting.need_ref):
        return phrase("projects.live.needs", need=texts[waiting.need_ref])
    nxt = pick(p, now, pm) or next((o for o in p.objectives if o.status == c.OPEN), None)
    if nxt is not None and texts.get(nxt.text_ref):
        return phrase("projects.live.next", text=texts[nxt.text_ref])
    return ""


def _awaiting(frame: Frame, p: Project, person: str) -> str:
    """Ce qui attend l'accord de la personne qui lui parle (elle s'occupe d'elle), pour ce projet."""
    pending = [v for v in frame.get(rt.PENDING_EFFECTS) if v.owner == c.OWNER and project_of(v.context) == p.id]
    if not pending:
        return ""
    words = sorted({effect_words(v.capability, phrase("projects.effect.request")) for v in pending})
    return phrase("projects.live.awaiting", who=_who(frame, person), what=", ".join(words))


@PROJECTS.section("projects", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, after=["goals"], trim_rank=44,
                  title=phrase("projects.live.title"), reads=[identity_c.PERSON, rt.PENDING_EFFECTS])
def _live_section(s: ProjectsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    texts: Mapping[str, str] = (enrich.get("projects") or {}).get("texts") or {}
    ep, aud = frame.episode, frame.audience
    if aud is None:
        return None
    pm = params(frame.env.params_of("projects", frame.root))
    person = frame.get(identity_c.PERSON(ep.target)) if ep is not None and ep.target else None
    owner = bool(person) and aud.owner  # l'adresse qui parle, là où elle parle (jamais un groupe public)
    lines, level, witness, steering = [], 0, False, False
    for p in _recent(s)[-SHOWN * 2:]:
        title = texts.get(p.title_ref)
        if not title or not hearable(p.about, p.sensitivity, person, aud.level, aud.witness_level, aud.private_ok):
            continue
        whose = phrase("projects.live.own") if p.authority == c.SELF else \
            phrase("projects.live.for", who=_who(frame, p.address or p.owner))
        how = "" if p.mode == c.PERSONA else phrase("projects.live.plain")
        done = sum(1 for o in p.objectives if o.kind == c.ONCE and o.status == c.DONE)
        total = sum(1 for o in p.objectives if o.kind == c.ONCE and o.status != c.DROPPED)
        progress = phrase("projects.live.progress", done=done, total=total) if total else \
            phrase("projects.live.maintain")
        state = phrase("projects.live.paused") if p.status == c.PAUSED else progress
        if p.schedule == ON_DEMAND and p.status == c.ACTIVE:
            state += phrase("projects.live.on_demand")
        line = "- " + phrase("projects.live.line", title=title, whose=whose, how=how, state=state)
        # le détail (son dernier compte rendu, ce qui vient) est au moins personnel : seulement à qui peut l'entendre
        if hearable(p.about, written(p), person, aud.level, aud.witness_level, aud.private_ok):
            if p.last_run_at:
                summary = texts.get(p.summary_ref, "")
                since = ago(frame.now - p.last_run_at)
                line += "\n  " + (phrase("projects.live.last_run_summary", ago=since, summary=summary[:300]) if summary
                                   else phrase("projects.live.last_run", ago=since))
            nxt = _next_words(p, texts, frame.now, pm)
            if nxt:
                line += f"\n  {nxt}"
            if any(a != person for a in p.about):
                level = max(level, written(p))
            steering = steering or (owner and steers(p, person))
        waiting = _awaiting(frame, p, person) if owner and person else ""
        if waiting:
            line += f"\n  {waiting}"
        lines.append(line)
        if any(a != person for a in p.about):
            level = max(level, p.sensitivity)
            witness = witness or person in p.about
        if len(lines) >= SHOWN:
            break
    if not lines:
        return None
    # une ligne, seulement en réponse à qui s'occupe d'elle et quand elle voit un projet qu'ils pilotent ensemble :
    # « ajoute une page contact », « mets-le en pause » se font avec l'outil — sinon le projet ne l'entend jamais
    if steering and ep is not None and ep.kind == Kind.REPLY:  # l'outil ne sert qu'en réponse
        lines.append(phrase("projects.live.steer"))
    return SectionBody("\n".join(lines), level=level, witness=witness)


def work_brief(frame: Frame, req: Any) -> str:
    return phrase("projects.run.brief")


def job_brief(frame: Frame, req: Any) -> str:
    return phrase("projects.run.job_brief")
