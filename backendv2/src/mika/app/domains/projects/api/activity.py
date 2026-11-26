"""Ce qui s'est passé dans un projet, pour qui est connecté (ADR 0290) : son fil d'activité, ses exécutions et ce que
chacune a fait pas à pas, son carnet, et de quoi dessiner le diagramme de ses objectifs.

**Tout vient du journal**, relu à la demande — rien n'est gardé à côté :

- **le fil** mêle, dans l'ordre, ses exécutions (``projects.run_reported``), les commits qu'elles ont laissés, ce qui
  est arrivé à ses pull requests (l'hôte relu, les vérifications, une fusion demandée, ce qu'une personne y a écrit),
  à ses tickets, et **les gestes des personnes** (un objectif ajouté, un plan validé, une consigne, une pause…). Un
  geste est ce qu'une personne a fait, quel que soit l'objet ; le reste se range par objet. Il se filtre par sorte et
  par objectif, se pagine par curseur, et se compte par jour sur trente jours ;
- **une exécution** : son épisode (``episode.started``, ``episode.ended``), son compte rendu, et ses appels d'outils
  lus dans sa trace (``runtime.traces``, jetable : gardée quatorze jours) — le nom de l'outil en mots, ce qu'il
  visait en une ligne, jamais ce qu'il a rendu ; un outil dont le résultat vient d'ailleurs le marque ;
- **le diagramme** ne porte que de vraies dates : quand un objectif a été posé, sa première exécution, sa clôture ;
  pour un jalon, quand il a été posé, dit prêt, atteint, et — déduit de ses exécutions — quand elle s'y est mise et
  combien d'exécutions il a prises. Le moteur n'estime aucune durée.

**Qui lit.** Le détail du projet (``reach.opened_project``), au niveau de ce que le projet écrit (``written``) : un
compte rendu, une note de carnet, un pas d'une exécution portent ce niveau. Le titre d'un ticket ne se dit que si elle
peut le lire (``tracker.veiled``). Le contrat, route par route : ``docs/protocole-moi.md``, § 11.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import timedelta
from typing import Any

from starlette.routing import Route

from mika.app.domains.projects.api.projects import PAGE, PAGE_MAX, PATH, TEXT_VEILED
from mika.app.domains.projects.api.reach import (
    BY_HER,
    BY_YOU,
    TEXT_SHOWN,
    YOU_WORDS,
    Reach,
    Scene,
    author_fields,
    opened_project,
    reach,
    reads_files,
    store_of,
    texts_of,
)
from mika.app.me.api import Call, Denied, MeApiBase, missing
from mika.app.me.common import millis, snippet
from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.contracts import self_ as self_c
from mika.faculties.projects import diagram as diagram_rows
from mika.faculties.projects import faculty as f
from mika.faculties.projects import feed, tracker
from mika.faculties.projects.faculty import (
    Project,
    written,
)
from mika.faculties.projects.inspect import OBJ_FR, VERDICT_FR
from mika.faculties.projects.inspect_milestones import CHECK_WORDS
from mika.faculties.projects.inspect_milestones import STATE_FR as MILESTONE_FR
from mika.kernel.clock import DAY
from mika.vocab.episodes import outcome_words, project_target

#: ce que le fil lit du journal, par lots, et combien de lots au plus pour remplir une page ou compter trente jours
SCAN, SCAN_BATCHES, COUNT_BATCHES = 200, 10, 25
#: les jours comptés
DAYS = 30
#: les épisodes relus pour le diagramme (les passages d'une mission qu'il rend : ``diagram.PASSES_SHOWN``)
EPISODES_READ = 1000
NO_AIMS = ("Ce projet ne t'ouvre pas ses fichiers : tu lis ce qu'elle a fait, en mots, pas les chemins ni les "
           "commandes.")
#: un texte écrit à un niveau qu'elle n'entend pas ici (ADR 0292) ne se sert pas : la ligne dit ``TEXT_VEILED``
_VEILED_REF = "\x00veiled"
NO_WORK = "Ce que ce projet écrit est d'un niveau que tu n'entends pas ici : son activité ne t'est pas lue."

# ── Les sortes du fil : celles de la faculté (``feed``), que lit aussi la console ─

RUN, COMMIT, PULL, TICKET, GESTURE, KINDS = feed.RUN, feed.COMMIT, feed.PULL, feed.TICKET, feed.GESTURE, feed.KINDS
KIND_WORDS, SORT_WORDS, READS = feed.KIND_WORDS, feed.SORT_WORDS, feed.READS
_ALL = feed.ALL


def _work(call: Call) -> tuple[Scene, Reach]:
    """Le projet, pour qui lit ce qu'il écrit : son détail, au niveau de ce que le projet écrit."""
    sc, r = opened_project(call)
    if written(r.p) > r.reader.level:
        raise Denied(403, NO_WORK)
    return sc, r


def _journal(call: Call, types: Iterable[Any], limit: int, *, where: tuple[str, Any] | None = None,
             before: int | None = None, correlations: Any = None) -> list[Any]:
    """Les derniers événements de ces types, décodés, du plus récent au plus ancien."""
    mind = call.kernel.mind
    names = [getattr(t, "name", t) for t in types]
    return [mind.decode(x) for x in mind.store.latest(names, limit, where=where, before=before,
                                                      correlations=correlations)]


class _Reader:
    """Ce qu'une page du fil relit une fois : les tickets nommés (et si elle peut les lire), qui a agi."""

    def __init__(self, sc: Scene, r: Reach) -> None:
        self.sc, self.r, self.level = sc, r, written(r.p)
        self._tickets: dict[str, Any] = {}

    def heard(self, content: Any) -> str:
        """La référence d'un texte, si elle l'entend. **Chaque texte servi se compare à son niveau, par le sien**
        (ADR 0292) — celui que son contenu porte au journal, pas celui que le détail du projet a aujourd'hui : le
        compte rendu d'un objectif né d'un ticket plus confidentiel garde son niveau quand ce ticket, fermé, est
        sorti de l'état."""
        return heard(self.r, content)

    def ticket(self, key: str) -> Any:
        if key not in self._tickets:
            self._tickets[key] = tracker.entry(store_of(self.sc.call), self.r.p.id, c.TICKETS, key)
        return self._tickets[key]

    def veiled(self, item: Any) -> bool:
        """Le titre de ce ticket lui est-il voilé (``tracker.veiled``) ?"""
        return bool(tracker.veiled(self.r.reader, item))

    def who(self, author: str, by: str) -> dict[str, Any]:
        """Qui a fait ceci : elle ; la personne connectée ; une autre personne, nommée seulement si elle a le droit
        de le savoir ; un autre projet, jamais nommé ici ; quelqu'un chez l'hôte. La règle est celle de toute l'API
        des projets (``reach.author_fields``) : il n'y en a qu'une. Le fil d'activité y ajoute seulement ce qu'il
        tient pour d'elle — ce qui n'est signé de personne (ni une personne, ni un projet, ni l'hôte)."""
        hers = author in (c.BY_SELF, "self") or (not by and author not in feed.PEOPLE)
        if hers and author != c.BY_HOST and not c.asking_project(author):
            author = c.BY_SELF
        return author_fields(self.sc, {}, author, by, self.level)


def heard(r: Reach, content: Any) -> str:
    """La référence d'un contenu du journal si la personne entend son niveau ; ``_VEILED_REF`` s'il est au-dessus ;
    vide s'il n'y en a pas."""
    ref = getattr(content, "ref", None) if content is not None else None
    if not ref:
        return ""
    return ref if int(getattr(content, "level", 0) or 0) <= r.reader.level else _VEILED_REF


def _said(texts: Mapping[str, str], ref: str) -> str:
    """Le texte d'une référence rendue par ``heard`` : ses mots, ou ce qui dit qu'il ne s'entend pas d'ici."""
    return TEXT_VEILED if ref == _VEILED_REF else texts.get(ref, "") if ref else ""


def _entries(look: _Reader, e: Any) -> list[dict[str, Any]]:
    """Ce qu'un événement du journal donne au fil (``feed.entries``), à l'instant du client (ms)."""
    return [{**x, "at": millis(x["at"])} for x in feed.entries(look, e)]


def _filled(call: Call, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Les lignes, leur texte lu : un compte rendu est le titre de son exécution ; ailleurs il suit le titre."""
    texts = texts_of(call, [x["text_ref"] for x in entries if x["text_ref"] != _VEILED_REF])
    for x in entries:
        ref = x.pop("text_ref")
        x["veiled"] = ref == _VEILED_REF  # un texte d'un niveau qu'elle n'entend pas : la ligne le dit, sans lui
        text = snippet(_said(texts, ref), 300)
        if x["kind"] == RUN:
            x["title"] = text
        elif text:
            x["sub"] = text
    return entries


def _about(call: Call, p: Project) -> tuple[int, int, frozenset[int]]:
    """Ce qu'une lecture du fil ne garde que : un objectif (``objective``), ou un ticket (``ticket`` : son numéro) —
    ce qui lui arrive, et ce qui arrive aux objectifs nés de lui (leurs exécutions, leurs commits, leur pull
    request)."""
    ticket = call.number("ticket", 0, 0)
    return call.number("objective", 0, 0), ticket, \
        frozenset(o.id for o in p.objectives if ticket and o.ticket == ticket)


def _kept(x: Mapping[str, Any], objective: int, ticket: int, born: frozenset[int]) -> bool:
    return feed.kept(x, objective, ticket, born)


async def activity(call: Call) -> dict[str, Any]:
    """``GET …/projets/<id>/activite[?kind=&objective=&ticket=&before=&size=]`` : son fil d'activité, du plus récent
    au plus ancien. ``before`` : le curseur rendu par la page d'avant (``next`` ; 0 : il n'y a plus rien)."""
    sc, r = _work(call)
    kind = call.arg("kind", limit=12)
    if kind and kind not in KINDS:
        raise Denied(400, "« kind » : run, commit, pull, ticket ou gesture.", {"kind": ", ".join(KINDS)})
    objective, ticket, born = _about(call, r.p)
    size = call.number("size", PAGE, 1, PAGE_MAX)
    cursor: int | None = call.number("before", 0, 0) or None
    look, out, more = _Reader(sc, r), [], True
    for _ in range(SCAN_BATCHES):
        batch = _journal(call, READS.get(kind, _ALL), SCAN, where=("project", r.p.id), before=cursor)
        for e in batch:
            if len(out) >= size:
                break
            cursor = e.seq
            out += [x for x in _entries(look, e) if (not kind or x["kind"] == kind)
                    and _kept(x, objective, ticket, born)]
        else:
            if len(batch) < SCAN:
                more = False
                break
            continue
        break
    return {"kinds": [{"code": k, "label": KIND_WORDS[k]} for k in KINDS], "size": size,
            "next": cursor or 0 if more and out else 0, "items": _filled(call, out)}


def _count(call: Call, types: Iterable[Any], project: int, counted: Any) -> bool:
    """Passe à ``counted`` chaque événement de ces types pour ce projet, du plus récent au plus ancien, par lots ;
    vrai s'il y en a trop pour tout lire (``COUNT_BATCHES`` lots) : le compte est alors incomplet."""
    cursor: int | None = None
    for _ in range(COUNT_BATCHES):
        batch = _journal(call, types, SCAN, where=("project", project), before=cursor)
        for e in batch:
            cursor = e.seq
            counted(e)
        if len(batch) < SCAN:
            return False
    return True


async def activity_totals(call: Call) -> dict[str, Any]:
    """``GET …/projets/<id>/activite/totaux[?objective=&ticket=]`` : les totaux du fil — par sorte, pour ce filtre,
    sur toute son histoire (pas seulement trente jours) —, de son carnet et de ses exécutions : de quoi poser un
    compte sur chaque pastille et chaque sous-onglet. ``cut`` : trop d'événements, le compte est incomplet."""
    sc, r = _work(call)
    objective, ticket, born = _about(call, r.p)
    look = _Reader(sc, r)
    totals = dict.fromkeys(KINDS, 0)
    notes = [0]

    def feed(e: Any) -> None:
        for x in _entries(look, e):
            if _kept(x, objective, ticket, born):
                totals[x["kind"]] += 1

    def noted(e: Any) -> None:
        if ticket:
            notes[0] += e.data.objective in born
        else:
            notes[0] += not objective or e.data.objective == objective

    cut = _count(call, _ALL, r.p.id, feed)
    notes_cut = _count(call, [f.NOTED], r.p.id, noted)
    return {"kinds": [{"code": k, "label": KIND_WORDS[k], "count": totals[k]} for k in KINDS], "totals": totals,
            "total": sum(totals.values()), "cut": cut, "notes": notes[0], "notes_cut": notes_cut, "runs": r.p.runs}


async def activity_days(call: Call) -> dict[str, Any]:
    """``GET …/projets/<id>/activite/jours`` : le compte par jour des trente derniers jours, sorte par sorte — de
    quoi dessiner un graphique —, et qui a fait quoi."""
    sc, r = _work(call)
    frame = sc.frame
    today = frame.local().date()
    since = frame.now - (DAYS + 1) * DAY
    days = [today - timedelta(days=n) for n in range(DAYS - 1, -1, -1)]
    counts = {day: dict.fromkeys(KINDS, 0) for day in days}
    by = {BY_HER: 0, BY_YOU: 0, "others": 0}
    look, cursor, cut = _Reader(sc, r), None, False
    for _ in range(COUNT_BATCHES):
        batch = _journal(call, _ALL, SCAN, where=("project", r.p.id), before=cursor)
        for e in batch:
            cursor = e.seq
            if e.at < since:
                break
            day = frame.local(e.at).date()
            for x in _entries(look, e) if day in counts else ():
                counts[day][x["kind"]] += 1
                by[x["author_kind"] if x["author_kind"] in (BY_HER, BY_YOU) else "others"] += 1
        else:
            if len(batch) == SCAN:
                continue
        break
    else:
        cut = True  # trop d'événements pour tout compter : les jours les plus anciens sont incomplets
    totals = {k: sum(row[k] for row in counts.values()) for k in KINDS}
    return {"days": [{"day": day.isoformat(), **counts[day], "total": sum(counts[day].values())} for day in days],
            "totals": totals, "total": sum(totals.values()), "cut": cut,
            "kinds": [{"code": k, "label": KIND_WORDS[k]} for k in KINDS],
            "by": [{"who": "self", "label": self_c.name_of(frame.get(self_c.PERSONA)), "count": by[BY_HER]},
                   {"who": "you", "label": YOU_WORDS, "count": by[BY_YOU]},
                   {"who": "others", "label": "d'autres", "count": by["others"]}]}


# ── Ses exécutions ────────────────────────────────────────────────────────


def _sort(p: Project, subject: str | None) -> tuple[str, int] | None:
    """Ce qu'était un épisode de ce projet — une séance de cadrage, du travail, une relecture — et l'objectif qu'il
    visait ; ``None`` : une prise de parole sur lui (``diagram.episode_sort``, que lit aussi la console)."""
    return diagram_rows.episode_sort(p, subject)


def _objective_ref(p: Project, oid: int, texts: Mapping[str, str]) -> dict[str, Any] | None:
    o = f.objective_at(p, oid) if oid else None
    if o is None:
        return None
    return {"id": o.id, "text": texts.get(o.text_ref, ""), "kind": o.kind, "ticket": o.ticket, "status": o.status,
            "status_label": OBJ_FR.get(o.status, o.status)}


def _run_json(r: Reach, e: Any, end: Any, report: Any, texts: Mapping[str, str], *, full: bool = False
              ) -> dict[str, Any] | None:
    p = r.p
    found = _sort(p, e.data.subject)
    if found is None:
        return None
    sort, oid = found
    d = report.data if report is not None else None
    outcome = str(end.data.outcome) if end is not None else ""
    # son compte rendu et ce qu'elle a demandé : chacun à son niveau, comparé à ce que la personne entend
    summary = _said(texts, heard(r, d.summary)) if d is not None else ""
    veiled = d is not None and _VEILED_REF in (heard(r, d.summary), heard(r, d.need))
    out = {"id": e.correlation, "at": millis(e.at), "sort": sort, "sort_label": SORT_WORDS[sort],
           "objective": _objective_ref(p, d.objective if d is not None and d.objective else oid, texts),
           "running": end is None, "outcome": outcome,
           "outcome_label": outcome_words(outcome, e.data.kind)[0] if outcome else "en cours",
           "seconds": max(1, (end.at - e.at) // 1_000_000) if end is not None else 0,
           "verdict": d.verdict if d is not None else "",
           "verdict_label": VERDICT_FR.get(d.verdict, d.verdict) if d is not None else "",
           "proven": bool(d.proven) if d is not None else False, "summary": snippet(summary, 300),
           "commit": d.commit[:40] if d is not None else "", "branch": d.branch if d is not None else "",
           "asked": bool(d is not None and d.need is not None and d.need.ref), "veiled": veiled}
    if full:
        out.update({"report": summary[:TEXT_SHOWN],
                    "need": _said(texts, heard(r, d.need))[:TEXT_SHOWN] if d is not None else ""})
    return out


def _runs(call: Call, p: Project, started: list[Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    corrs = [e.correlation for e in started]
    ended = {e.correlation: e for e in _journal(call, [rt.EPISODE_ENDED], len(corrs) + 1, correlations=corrs)} \
        if corrs else {}
    reports = {e.correlation: e for e in _journal(call, [c.RUN_REPORTED], len(corrs) + 1, correlations=corrs)} \
        if corrs else {}
    refs = [o.text_ref for o in p.objectives]
    for e in reports.values():
        refs += [e.data.summary.ref or "", (e.data.need.ref or "") if e.data.need is not None else ""]
    return ended, reports, texts_of(call, refs)


async def executions(call: Call) -> dict[str, Any]:
    """``GET …/projets/<id>/executions[?before=&size=]`` : ses exécutions, de la plus récente à la plus ancienne —
    cadrage, travail, relecture ; l'objectif ; l'issue et le verdict ; la durée."""
    sc, r = _work(call)
    size = call.number("size", PAGE, 1, PAGE_MAX)
    before = call.number("before", 0, 0) or None
    started = _journal(call, [rt.EPISODE_STARTED], size + 1, where=("target", project_target(r.p.id)), before=before)
    page = started[:size]
    ended, reports, texts = _runs(call, r.p, page)
    items = [x for e in page
             if (x := _run_json(r, e, ended.get(e.correlation), reports.get(e.correlation), texts)) is not None]
    return {"total": r.p.runs, "size": size, "next": page[-1].seq if len(started) > size else 0,
            "sorts": [{"code": k, "label": v} for k, v in SORT_WORDS.items()], "items": items}


def _steps(call: Call, sc: Scene, r: Reach, correlation: str) -> tuple[bool, list[dict[str, Any]], bool]:
    """Les pas d'une exécution, lus dans sa trace : (la trace est gardée, ses pas, il y en avait davantage). **Ce
    qu'un pas visait** (un chemin, une commande) est l'arbre du dépôt par morceaux : il ne se dit qu'avec le droit sur
    ses fichiers (``reads_files``) ; sans lui, un pas ne dit que ce qu'elle a fait, en mots. Ce qui vise un projet
    lié ne se dit que si la personne lit aussi les fichiers de ce projet-là (ADR 0292)."""
    files = reads_files(sc, r)
    opened: dict[int, bool] = {}

    def shown(args: Mapping[str, Any]) -> bool:
        other = feed.elsewhere(args, r.p.id)
        if not files or other is None:
            return files
        if other not in opened:
            p = sc.s.projects.get(other)
            opened[other] = p is not None and reads_files(sc, reach(sc, p))
        return opened[other]

    traces = call.port("traces")
    trace = traces.get(correlation) if traces is not None else None
    return feed.steps(trace, call.kernel.registry.tools, shown)


async def execution(call: Call) -> dict[str, Any]:
    """``GET …/projets/<id>/execution?id=`` : une exécution — son compte rendu, ce qu'elle a fait pas à pas, son
    commit, ce qu'elle a demandé."""
    sc, r = _work(call)
    wanted = call.arg("id", limit=120)
    started = [e for e in _journal(call, [rt.EPISODE_STARTED], 2, correlations=[wanted])
               if e.data.target == project_target(r.p.id)] if wanted else []
    if not started:
        raise missing()
    ended, reports, texts = _runs(call, r.p, started[:1])
    e = started[0]
    out = _run_json(r, e, ended.get(e.correlation), reports.get(e.correlation), texts, full=True)
    if out is None:
        raise missing()
    kept, steps, more = _steps(call, sc, r, e.correlation)
    aims = reads_files(sc, r)
    return {**out, "steps_kept": kept, "steps": steps, "steps_cut": more,
            # ce que chaque pas visait ne se dit qu'avec le droit sur ses fichiers ; sinon pourquoi, en mots
            "steps_aims": aims, "steps_aims_why": "" if aims else NO_AIMS}


# ── Son carnet ────────────────────────────────────────────────────────────


async def notebook(call: Call) -> dict[str, Any]:
    """``GET …/projets/<id>/carnet[?objective=&before=&size=]`` : ses notes, les plus récentes d'abord, chacune avec
    l'objectif qu'elle visait en l'écrivant."""
    sc, r = _work(call)
    size = call.number("size", PAGE, 1, PAGE_MAX)
    objective = call.number("objective", 0, 0)
    cursor: int | None = call.number("before", 0, 0) or None
    found: list[Any] = []
    more = True
    for _ in range(SCAN_BATCHES):
        batch = _journal(call, [f.NOTED], SCAN, where=("project", r.p.id), before=cursor)
        for e in batch:
            if len(found) >= size:
                break
            cursor = e.seq
            if not objective or e.data.objective == objective:
                found.append(e)
        else:
            if len(batch) < SCAN:
                more = False
                break
            continue
        break
    texts = texts_of(call, [*(e.data.text.ref or "" for e in found), *(o.text_ref for o in r.p.objectives)])
    counted = [0]

    def one(e: Any) -> None:
        counted[0] += not objective or e.data.objective == objective

    # son total, pour ce filtre (ADR 0293) : compté dans le journal, borné (``total_cut`` : incomplet)
    total_cut = _count(call, [f.NOTED], r.p.id, one)
    return {"size": size, "next": cursor or 0 if more and found else 0, "total": counted[0], "total_cut": total_cut,
            # une note garde le niveau où elle a été écrite : au-dessus de ce qu'elle entend, elle ne se sert pas
            "items": [{"seq": e.seq, "at": millis(e.at), "text": _said(texts, heard(r, e.data.text))[:TEXT_SHOWN],
                       "veiled": heard(r, e.data.text) == _VEILED_REF,
                       "objective": _objective_ref(r.p, e.data.objective, texts), "run": e.correlation}
                      for e in found]}


# ── Le diagramme de ses objectifs ─────────────────────────────────────────


async def diagram(call: Call) -> dict[str, Any]:
    """``GET …/projets/<id>/diagramme`` : ses objectifs et ses missions dans l'ordre du plan, leurs jalons, et leurs
    dates — de quoi dessiner l'avancement et le temps. De vraies dates seulement ; 0 : pas encore arrivé."""
    sc, r = _work(call)
    p = r.p
    started = _journal(call, [rt.EPISODE_STARTED], EPISODES_READ, where=("target", project_target(p.id)))
    found = diagram_rows.rows(p, diagram_rows.starts_of(p, started))
    texts = texts_of(call, [ref for o in found for ref in (o.text_ref, *(m.text_ref for m in o.marks))])
    rows = [{
        "id": o.id, "text": texts.get(o.text_ref, ""), "kind": o.kind, "status": o.status,
        "status_label": OBJ_FR.get(o.status, o.status), "after": o.after, "rank": o.rank, "ticket": o.ticket,
        "added_at": millis(o.added_at), "started_at": millis(o.started_at), "last_run": millis(o.last_run),
        "closed_at": millis(o.closed_at), "runs": o.runs, "reached": o.reached, "milestones_total": len(o.marks),
        "passes": [millis(s) for s in o.passes],
        "milestones": [{
            "id": m.id, "text": texts.get(m.text_ref, ""), "status": m.status,
            "status_label": MILESTONE_FR.get(m.status, m.status), "check": m.check,
            "check_label": CHECK_WORDS.get(m.check, m.check), "ready": m.ready, "added_at": millis(m.added_at),
            "started_at": millis(m.started_at), "ready_at": millis(m.ready_at), "reached_at": millis(m.reached_at),
            "runs": m.runs} for m in o.marks]} for o in found]
    dated = [x for row in rows for x in (row["added_at"], row["started_at"]) if x]
    return {"now": millis(sc.frame.now), "from": min(dated, default=0), "cut": len(started) >= EPISODES_READ,
            "objectives": rows}


def routes(api: MeApiBase) -> list[Route]:
    r = api.route
    one = PATH + "/{project:int}"
    return [r(one + "/activite", activity), r(one + "/activite/jours", activity_days),
            r(one + "/activite/totaux", activity_totals),
            r(one + "/executions", executions), r(one + "/execution", execution), r(one + "/carnet", notebook),
            r(one + "/diagramme", diagram)]
