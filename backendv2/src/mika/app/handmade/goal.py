"""La fiche d'un but, dessinée (ADR 0121) : son en-tête, et son « Résumé » — ce qu'elle cherche et où elle en est, son
avancement, sa prochaine séance, ses garde-fous, son plan de travail (chaque tâche avec ses boutons), ses dernières
séances et la dernière consigne reçue ; le détail complet, replié. Un rappel se dit autrement : quoi, quand, à qui,
s'il a été dit. Ses autres onglets (cadre, séances, carnet, décisions, épisodes) se dessinent bloc par bloc.

Les données sont celles de la faculté ``goals`` : sa tranche, lue par ses propres fonctions (statut, budget, envie,
prochaine séance et ce qui la retient), ses textes et son journal (ses séances). Les formulaires du plan sont ceux que
la console a préparés pour l'onglet (``Forms``), retrouvés dans les blocs de la faculté.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from markupsafe import Markup

from mika.app.handmade import Look, excerpt, person_href, span, unit
from mika.app.handmade.fiche_parts import (
    STYLES,
    draw,
    fact,
    rendered,
    safely,
    shaped,
    tag,
    texts,
    tone,
    whole,
)
from mika.contracts import goals as c
from mika.faculties.goals.actions import TASK_STATUS_FR
from mika.faculties.goals.faculty import Goal, budget, desire, goal_at, musing, params, status
from mika.faculties.goals.inspect import (
    AUTHORITY_FR,
    KIND_FR,
    PRIORITY_FR,
    PRIORITY_TONE,
    STATUS_FR,
    STATUS_TONE,
    TASK_ORDER,
    TASK_TONE,
    VERDICT_FR,
    VERDICT_TONE,
)
from mika.faculties.goals.work import next_step_at, why_not_now
from mika.inspector.pages.subjects import fiche_url
from mika.inspector.ui import UI, Overview
from mika.kernel.clock import DAY

KIND = "goal"
#: ses onglets, tous dessinés : « Résumé » à sa façon, les autres bloc par bloc
TABS = ("resume", "politique", "seances", "carnet", "decisions", "episodes")
#: ses dernières séances, sur le résumé
RECENT_STEPS = 3
FORGOTTEN = "(oublié)"


def _read(ui: UI, key: str) -> tuple[Any, Any, Goal] | None:
    frame = ui.kernel.mind.frame()
    try:
        s = frame.state("goals")
    except KeyError:
        return None
    g = goal_at(s, key)
    return None if g is None else (frame, s, g)


def _kind(g: Goal) -> str:
    return "rêverie" if musing(g) else KIND_FR.get(g.kind, g.kind)


def _who(ui: UI, key: str | None) -> dict[str, str] | None:
    """Une personne du but (sa clé de relation, ou l'adresse où lui parler) : son nom et sa fiche."""
    if not key:
        return None
    person = ui.names.person_of(key)
    return {"name": ui.names.name_of(key) or person, "href": person_href(person)}


def _next(g: Goal, s: Any, frame: Any, look: Look) -> str:
    """La prochaine séance en mots : quand, ou ce qui la retient (comme la faculté la dit)."""
    why = why_not_now(g, s, frame)
    if not why:
        return "dès que possible"
    nxt = next_step_at(g, s, frame) if status(g, frame.now) in (c.ACTIVE, c.WAITING) else None
    if nxt is not None and nxt > frame.now and why.startswith("pas encore"):
        return f"{look.day(nxt)} ({why.split(' : ', 1)[-1]})"
    return why


def _progress(g: Goal, p: Any) -> dict[str, Any]:
    """L'avancement : son plan de travail s'il en a un, sinon ses séances sur son budget."""
    if g.tasks:
        done = sum(1 for t in g.tasks if t.status == c.TASK_DONE)
        blocked = sum(1 for t in g.tasks if t.status == c.TASK_BLOCKED)
        return {"done": done, "of": len(g.tasks), "unit": "tâches faites", "w": unit(done / len(g.tasks)),
                "note": f"{blocked} bloquée{'s' if blocked > 1 else ''}" if blocked else ""}
    most = budget(g, p)
    return {"done": g.steps, "of": most, "unit": "séances", "w": unit(g.steps / most if most else 0.0), "note": ""}


def _guard(n: int, limit: int, then: str) -> dict[str, Any]:
    """Un garde-fou : où il en est, sur ce qui l'arrête (« 2 / 3, au-delà : bloqué »)."""
    near = bool(n) and n >= limit - 1
    return {"n": n, "limit": limit, "then": then, "w": unit(n / limit if limit else 0.0),
            "tone": "danger" if near else "warn" if n else ""}


def _alerts(g: Goal, frame: Any, look: Look, said: Mapping[str, str]) -> list[dict[str, str]]:
    """Ce qui se dit avant tout : en pause, clos (et comment), en attente de quelqu'un."""
    if g.paused_at and g.status not in c.CLOSED_STATUSES:
        return [{"tone": "warn", "text": f"En pause depuis {span(frame.now - g.paused_at)} : ni séance, ni rappel, "
                                          "ni usure de l'envie, jusqu'à ce que tu le reprennes (« Reprendre », en "
                                          "haut)."}]
    if g.status in c.CLOSED_STATUSES:
        result = said.get(g.result_ref, FORGOTTEN) if g.result_ref else "sans résultat écrit"
        return [{"tone": STATUS_TONE.get(g.status, ""),
                 "text": f"{STATUS_FR.get(g.status, g.status).capitalize()} {look.day(g.closed_at)} — {result}."}]
    if g.status == c.WAITING:
        whom = f"la réponse de {_who_name(look, g.wait_for)}" if g.wait_for else "un délai"
        late = g.waiting_until <= frame.now
        return [{"tone": "info", "text": f"Elle attend {whom}" + (" : l'attente est échue, il reprend." if late else
                                                                  f", jusqu'à {look.day(g.waiting_until)}.")}]
    return []


def _who_name(look: Look, key: str | None) -> str:
    return look.ui.names.name_of(key or "") or (key or "quelqu'un")


def _tasks(g: Goal, said: Mapping[str, str], plan: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Son plan, une tâche par ligne (en cours, à faire, bloquée, puis faite) ; ses boutons sont ceux de la ligne de la
    faculté (changer son statut, la modifier, la retirer), avec leurs formulaires préparés."""
    actions = {str(r["cells"][0].get("text", "")): r["detail"] for r in (plan or {}).get("rows", []) if r["cells"]}
    out = []
    for t in sorted(g.tasks, key=lambda t: (TASK_ORDER.get(t.status, 9), t.id)):
        out.append({"id": t.id, "text": said.get(t.text_ref, FORGOTTEN), "note": said.get(t.note_ref, "") if t.note_ref
                    else "", "status": TASK_STATUS_FR.get(t.status, t.status), "key": t.status,
                    "tone": tone(TASK_TONE.get(t.status, "")), "mine": t.author != "operator",
                    "actions": actions.get(str(t.id), [])})
    return out


def _steps(ui: UI, g: Goal, look: Look) -> list[dict[str, Any]]:
    """Ses dernières séances, la plus récente d'abord : le verdict, ce qu'elle en a dit, l'épisode."""
    found = safely(lambda: ui.inspection.context().events([c.STEP_REPORTED], RECENT_STEPS, where=("goal", g.id)),
                   "séances d'un but", [])
    out = []
    for e in found:
        d = e.data
        verdict = str(d.verdict)
        text = getattr(d.summary, "text", None) if d.summary is not None else ""
        out.append({"when": look.ago(e.at), "verdict": VERDICT_FR.get(verdict, verdict),
                    "tone": tone(VERDICT_TONE.get(verdict, "")), "text": excerpt(text, 280) if text is not None
                    else FORGOTTEN, "proof": "prouvé" if verdict == c.DONE and d.proven else
                    "sans preuve" if verdict == c.DONE else "", "episode": e.correlation})
    return out


def _blocks(blocks: Sequence[Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    """Ce que le dessin reprend des blocs de la faculté : son plan (ses formulaires), l'ajout d'une tâche, le détail."""
    plan = next((d for d in items if d["t"] == "table" and d["title"].startswith("Plan de travail")), None)
    add = next((d for d in items if d["t"] == "action" and d.get("key") == "goals.tache_ajouter"), None)
    detail = next((d for d in items if d["t"] == "disclosure"), None)
    return {"plan": plan, "add": add, "detail": shaped(detail) if detail else None}


class GoalFiche(Overview):
    """La fiche d'un but : son en-tête, son résumé dessiné ; ses autres onglets bloc par bloc."""

    slug = ""
    title = "Résumé"
    styles = STYLES
    tabs = TABS

    def render(self, ui: UI, key: str) -> Markup | None:
        return None

    def head(self, ui: UI, key: str) -> Markup | None:
        got = _read(ui, key)
        if got is None:
            return None
        frame, s, g = got
        look = Look.of(ui, DAY)
        title = texts(ui, (g.title_ref,)).get(g.title_ref, FORGOTTEN) if g.title_ref else "(sans titre)"
        st = status(g, frame.now)
        tags = [tag(STATUS_FR.get(st, st), STATUS_TONE.get(st, ""))]
        if g.paused_at and g.status not in c.CLOSED_STATUSES:
            tags.append(tag("en pause", "warn"))
        if g.priority != c.NORMAL:
            tags.append(tag(f"priorité {PRIORITY_FR.get(g.priority, g.priority)}", PRIORITY_TONE.get(g.priority, "")))
        if g.urgent:
            tags.append(tag("urgent", "danger"))
        facts = []
        if (who := _who(ui, g.owner)) is not None:
            facts.append(fact("pour", who["name"], who["href"]))
        if g.due is not None:
            facts.append(fact("échéance", look.day(g.due)))
        if g.kind != c.REMINDER and st in (c.ACTIVE, c.WAITING) and not g.paused_at:
            facts.append(fact("prochaine séance", _next(g, s, frame, look)))
        facts.append(fact("ouvert", look.day(g.opened_at)))
        return draw("tete.html", kicker=f"But n° {g.id} · {_kind(g)} · {AUTHORITY_FR.get(g.authority, g.authority)}",
                    title=title, tags=tags, facts=facts, lede="")

    def render_tab(self, ui: UI, key: str, tab: str, blocks: Sequence[Any], query: Mapping[str, str],
                   forms: Mapping[str, Any] | None = None) -> Any:
        if tab == "resume":
            return self._summary(ui, key, blocks, query, forms)
        return whole(ui, blocks, query, forms) if tab in TABS else None

    @staticmethod
    def _summary(ui: UI, key: str, blocks: Sequence[Any], query: Mapping[str, str],
                 forms: Mapping[str, Any] | None) -> Markup | None:
        got = _read(ui, key)
        if got is None:
            return None
        frame, s, g = got
        look = Look.of(ui, DAY)
        p = params(frame.env.params_of("goals", frame.root))
        latest = g.instructions[-1] if g.instructions else ""
        said = texts(ui, (g.title_ref, g.details_ref, g.summary_ref, g.result_ref, latest,
                          *(t.text_ref for t in g.tasks), *(t.note_ref for t in g.tasks)))
        st = status(g, frame.now)
        reminder = g.kind == c.REMINDER
        alive = st in (c.ACTIVE, c.WAITING) and not g.paused_at
        exploring = g.kind == c.EXPLORATION and g.status not in c.CLOSED_STATUSES
        wish = desire(g, frame.now, p) if exploring else None
        parts = _blocks(blocks, rendered(ui, blocks, query))
        chips = [_kind(g), AUTHORITY_FR.get(g.authority, g.authority)]
        chips += [f"outils : {', '.join(g.bundles)}"] if g.bundles else []
        chips += [f"{len(g.instructions)} consigne{'s' if len(g.instructions) > 1 else ''}"] if g.instructions else []
        return draw(
            "but.html", forms=forms or {}, tables="cards", reminder=reminder, alerts=_alerts(g, frame, look, said),
            title=said.get(g.title_ref, FORGOTTEN) if g.title_ref else "(sans titre)",
            details=said.get(g.details_ref, FORGOTTEN) if g.details_ref else "",
            summary=said.get(g.summary_ref, FORGOTTEN) if g.summary_ref else "",
            last_step=look.ago(g.last_step_at) if g.last_step_at else "", chips=chips,
            status={"text": STATUS_FR.get(st, st), "tone": tone(STATUS_TONE.get(st, ""))},
            progress=_progress(g, p), next=_next(g, s, frame, look) if alive and not reminder else "",
            due=look.day(g.due) if g.due is not None else "",
            wish={"text": f"{round(100 * wish)} %", "w": unit(wish), "frozen": bool(g.paused_at)}
            if wish is not None else None,
            owner=_who(ui, g.owner), address=_who(ui, g.address),
            remind={"when": look.day(g.due) if g.due is not None else "—", "urgent": g.urgent,
                    "said": g.delivered, "attempts": g.attempts,
                    "retry": look.day(g.retry_at) if g.retry_at > frame.now else ""} if reminder else None,
            guards=[("Sans verdict d'affilée", _guard(g.silent, p.silent_before_blocked, "bloqué")),
                    ("Pannes d'affilée", _guard(g.failures, p.failures_before_failed, "en échec"))],
            unproven=g.unproven, evidence=g.evidence, tasks=_tasks(g, said, parts["plan"]),
            editable=parts["add"] is not None or any(r["detail"] for r in (parts["plan"] or {}).get("rows", [])),
            add=parts["add"], detail=parts["detail"], steps=[] if reminder else _steps(ui, g, look),
            instruction=said.get(latest, FORGOTTEN) if latest else "",
            tabs={t: fiche_url(KIND, key, t) for t in TABS})
