"""Ce que les projets mettent dans le prompt.

- **Pendant une exécution** (``WORK`` ou ``JOB``) : le projet — son cadre, son
  mode, l'objectif visé (et les autres), les décisions en vigueur, les
  consignes reçues (la plus récente prime), son carnet, ce que sont devenues
  ses demandes, l'atelier et son dépôt distant.
- **Un récit** (mode Mika) : ce qu'elle a mené à bout, à la mesure du lien.
- **En conversation** : ses projets (« tu travailles sur quoi ? » est une
  question sur sa vie), filtrés comme la mémoire.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from mika.contracts import identity as identity_c
from mika.contracts import projects as c
from mika.faculties.projects.faculty import (
    PROJECTS,
    Decision,
    Objective,
    Project,
    ProjectsState,
    cadence,
    live,
    objective_of,
    params,
)
from mika.faculties.projects.tools import RUNS
from mika.faculties.projects.work import FULL, MENTION
from mika.kernel.clock import DAY, HOUR
from mika.kernel.faculty import Zone
from mika.kernel.frame import Frame
from mika.kernel.prompt import SectionBody, readable
from mika.vocab.episodes import CONVERSATIONAL, Kind, project_of
from mika.vocab.privacy import hearable

SHOWN = 4
INSTRUCTIONS_SHOWN = 3
#: les décisions en vigueur montrées pendant une exécution (les plus récentes)
DECISIONS_SHOWN = 12
TREE_SHOWN = 60


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
    objectives = [r for o in p.objectives for r in (o.text_ref, o.note_ref, o.result_ref)]
    decisions = [r for d in p.decisions for r in (d.title_ref, d.choice_ref, d.reason_ref, d.context_ref)]
    deposits = [note for _, _, note in p.deposits]
    return [r for r in (p.title_ref, p.description_ref, p.summary_ref, *p.notes, *p.instructions, *objectives,
                        *decisions, *deposits) if r]


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
    refs = [r for p in chosen for r in (_refs(p) if got is not None and p is got[0] else
                                        [p.title_ref, p.summary_ref])]
    out: dict[str, Any] = {"texts": store.content(refs) if refs else {}}
    atelier = ports.get("workshop")
    if ep is not None and ep.kind in RUNS and got is not None and atelier is not None:
        out["tree"] = await atelier.tree(got[0].id) if atelier.exists(got[0].id) else []
    return out


def _recent(s: ProjectsState) -> list[Project]:
    return sorted((p for p in s.projects.values() if live(p)), key=lambda p: p.id)


def _who(frame: Frame, key: str | None) -> str:
    name = frame.get(identity_c.IDENTITY(key)).name if key else ""
    return f"« {name} »" if name else "quelqu'un"


KIND_WORDS = {c.ONCE: "ponctuel", c.CONSTANT: "constant"}
STATUS_WORDS = {c.OPEN: "ouvert", c.DONE: "fait", c.BLOCKED: "bloqué", c.DROPPED: "retiré"}


def _objective_line(o: Objective, texts: Mapping[str, str], pm: Any, now: int) -> str:
    text = texts.get(o.text_ref, "(oublié)")
    if o.kind == c.CONSTANT and o.status != c.OPEN:
        state = f"constant, {STATUS_WORDS.get(o.status, o.status)} — mis de côté"
    elif o.kind == c.CONSTANT:
        last = f", dernier passage il y a {_ago(now - o.passed_at)}" if o.passed_at else ", jamais encore"
        state = f"constant, revient toutes les {_every(cadence(o, pm))}{last}"
    else:
        state = f"ponctuel, {STATUS_WORDS.get(o.status, o.status)}"
    return f"- n° {o.id} [{state}] {text}"


def _ago(us: int) -> str:
    if us < HOUR:
        return f"{max(1, us // 60_000_000)} min"
    if us < 2 * DAY:
        return f"{us // HOUR} h"
    return f"{us // DAY} jours"


def _every(us: int) -> str:
    return f"{us // DAY} jours" if us >= 2 * DAY and us % DAY == 0 else f"{max(1, round(us / HOUR))} h"


def _decision_line(d: Decision, texts: Mapping[str, str]) -> str:
    why = texts.get(d.reason_ref, "") if d.reason_ref else ""
    return f"- D{d.id} {texts.get(d.title_ref, '(oubliée)')} : {texts.get(d.choice_ref, '(oubliée)')}" + \
        (f" (parce que : {why})" if why else "")


MODE_WORDS = {
    c.PERSONA: "C'est toi qui y travailles, avec ton humeur et tes avis : tu peux préférer une solution, le dire, "
               "le consigner dans tes décisions (project_decide) — et dire quand quelque chose ne te plaît pas.",
    c.PLAIN: "Mode impersonnel : un travail factuel et méthodique, sans avis personnel, sans émotion, sans "
             "commentaire sur toi-même. Les décisions se justifient par des faits.",
}
RUN_RULES = ("Conclus cette exécution en appelant l'outil report_run : « continue » (tu reprendras), « done » (l'objectif "
             "visé est fait — pour un ponctuel, seulement si tu as réellement produit quelque chose : écrit, "
             "modifié, lancé un programme qui réussit ; lire ou chercher ne suffit pas ; pour un constant, ce "
             "passage est fait), « blocked » (tu n'y arrives pas), ou « wait » (tu attends quelque "
             "chose). Tes outils s'appellent, ils ne s'écrivent pas : écrire « report_run » dans ta réponse ne fait "
             "rien. Une décision technique se consigne (project_decide) ; ne rouvre pas une décision en vigueur sans "
             "la remplacer.")


@PROJECTS.section("project", zone=Zone.VOLATILE, episodes=RUNS, trim_rank=90, title="CE PROJET")
def _run_section(s: ProjectsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    got = _project(s, frame)
    if got is None:
        return None
    p, target = got
    data = enrich.get("projects") or {}
    texts: Mapping[str, str] = data.get("texts") or {}
    pm = params(frame.env.params_of("projects", frame.root))
    who = "un projet à toi" if p.authority == c.SELF else f"un projet que {_who(frame, p.address or p.owner)} t'a confié"
    lines = [f"Projet n° {p.id} : {texts.get(p.title_ref, '(titre oublié)')} — {who}.", MODE_WORDS[p.mode]]
    if p.description_ref and texts.get(p.description_ref):
        lines.append(f"Ce que tu veux en faire : {texts[p.description_ref]}" if p.authority == c.SELF
                     else f"Le cadre (confié, tu ne le changes pas) : {texts[p.description_ref]}")
    if target is not None:
        lines.append("L'objectif de cette exécution :\n" + _objective_line(target, texts, pm, frame.now))
        if target.kind == c.CONSTANT:
            lines.append("C'est un objectif constant : il ne finit jamais. Fais un passage utile (une amélioration "
                         "concrète, vérifiée), puis conclus ce passage par « done ».")
        if target.note_ref and texts.get(target.note_ref):
            lines.append(f"Où tu en étais sur cet objectif : {texts[target.note_ref]}")
    others = [o for o in p.objectives if target is None or o.id != target.id]
    if others:
        lines.append("Les autres objectifs du projet :\n" + "\n".join(
            _objective_line(o, texts, pm, frame.now) for o in others if o.status != c.DROPPED))
    decisions = [d for d in p.decisions if d.status == c.IN_FORCE][-DECISIONS_SHOWN:]
    if decisions:
        lines.append("Les décisions techniques en vigueur (relis-les avant de choisir) :\n"
                     + "\n".join(_decision_line(d, texts) for d in decisions))
    instructions = [texts[r] for r in p.instructions if texts.get(r)]
    if instructions:
        lines.append("Consignes reçues (à suivre ; la plus récente prime) :\n"
                     + "\n".join(f"- {i}" for i in instructions[-INSTRUCTIONS_SHOWN:]))
    if p.summary_ref and texts.get(p.summary_ref):
        lines.append(f"Le dernier compte rendu du projet : {texts[p.summary_ref]}")
    notes = [texts[r] for r in p.notes if texts.get(r)]
    if notes:
        lines.append("Ton carnet :\n" + "\n".join(f"- {n}" for n in notes[-3:]))
    if p.deposits:
        lines.append("Déposé dans l'atelier par l'opérateur :\n" + "\n".join(
            f"- {name} ({size} o)" + (f" — {texts[note]}" if note and texts.get(note) else "")
            for name, size, note in p.deposits[-3:]))
    if p.effects:
        lines.append("Ce que sont devenues tes demandes (ce qui sort de la machine) :\n"
                     + "\n".join(f"- {e}" for e in p.effects[-3:]))
    if p.remote:
        lines.append(f"Dépôt distant : {p.remote} (branche {p.branch})"
                     + (" — envoyé après chaque exécution qui enregistre quelque chose." if p.auto_push else
                        " — project_push propose un envoi."))
    if "workshop" in p.bundles:
        tree = data.get("tree")
        lines.append("L'atelier (le dossier du projet) :\n" + ("\n".join(f"- {f}" for f in tree[:TREE_SHOWN])
                                                                if tree else "- (vide pour l'instant)"))
    lines.append(RUN_RULES)
    return SectionBody("\n".join(lines), level=p.sensitivity, provenance=(f"project:{p.id}",))


@PROJECTS.section("project_share", zone=Zone.VOLATILE, episodes=[Kind.INITIATIVE], trim_rank=90,
                  title="CE QUE TU AS MENÉ À BOUT")
def _share_section(s: ProjectsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """Ce qu'elle a mené à bout dans un projet — à la mesure du lien avec qui l'écoute."""
    ep = frame.episode
    got = objective_of(ep.attrs.get("subject")) if ep is not None else None
    p = s.projects.get(got[0]) if got is not None else None
    o = next((x for x in p.objectives if x.id == got[1]), None) if p is not None and got is not None else None
    if p is None or o is None:
        return None
    store = (enrich.get("projects") or {}).get("texts") or {}
    title, objective = store.get(p.title_ref), store.get(o.text_ref)
    args = ep.attrs.get("args") if ep is not None else None
    share = str(args.get("share", MENTION)) if args else MENTION
    aud = frame.audience
    person = frame.get(identity_c.PERSON(ep.target)) if ep is not None and ep.target else None
    if aud is None or not hearable(p.about, p.sensitivity, person, aud.level, aud.witness_level, aud.private_ok) \
            or share == MENTION or not title:
        return SectionBody("quelque chose qui te tenait à cœur, dans un de tes projets", level=0)
    result = store.get(o.result_ref, "")
    body = f"Dans ton projet « {title} » : {objective or 'un objectif'}"
    if share == FULL and result:
        body += f"\nCe que tu en as tiré : {result}"
    elif result:
        body += f" — en bref : {result.split('. ')[0].strip()}"
    return SectionBody(body, level=p.sensitivity if any(a != person for a in p.about) else 0,
                       provenance=(f"project:{p.id}",))


@PROJECTS.section("projects", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, after=["goals"], trim_rank=44,
                  title="TES PROJETS", reads=[identity_c.PERSON])
def _live_section(s: ProjectsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    texts: Mapping[str, str] = (enrich.get("projects") or {}).get("texts") or {}
    ep, aud = frame.episode, frame.audience
    if aud is None:
        return None
    person = frame.get(identity_c.PERSON(ep.target)) if ep is not None and ep.target else None
    lines, level, witness = [], 0, False
    for p in _recent(s)[-SHOWN * 2:]:
        title = texts.get(p.title_ref)
        if not title or not hearable(p.about, p.sensitivity, person, aud.level, aud.witness_level, aud.private_ok):
            continue
        whose = "à toi" if p.authority == c.SELF else f"pour {_who(frame, p.address or p.owner)}"
        how = "" if p.mode == c.PERSONA else ", en mode impersonnel"
        done = sum(1 for o in p.objectives if o.kind == c.ONCE and o.status == c.DONE)
        total = sum(1 for o in p.objectives if o.kind == c.ONCE and o.status != c.DROPPED)
        progress = f"{done} objectif(s) sur {total} atteints" if total else "des objectifs à entretenir"
        state = "en pause" if p.status == c.PAUSED else progress
        lines.append(f"- {title} ({whose}{how}) : {state}")
        if any(a != person for a in p.about):
            level = max(level, p.sensitivity)
            witness = witness or person in p.about
        if len(lines) >= SHOWN:
            break
    if not lines:
        return None
    return SectionBody("\n".join(lines), level=level, witness=witness)


def work_brief(frame: Frame, req: Any) -> str:
    return ("(Personne ne te parle : c'est un moment de travail sur ton projet, pour toi seule — personne ne lit ce "
            "que tu écris ici ; ni didascalies, ni adresse à quelqu'un.) Avance sur l'objectif de cette exécution en "
            "appelant tes outils, puis conclus en appelant report_run.")


def job_brief(frame: Frame, req: Any) -> str:
    return ("Exécution de travail impersonnelle sur ce projet : personne ne lit ce texte. Avance sur l'objectif "
            "indiqué en appelant les outils, puis conclus en appelant report_run.")


# ── Outil : relire ses projets (même filtre que la section) ──


class NoArgs(BaseModel):
    pass


@PROJECTS.tool("projects_list", description="Relire tes projets : à qui, où ils en sont.", args=NoArgs,
               bundle="projects", episodes=CONVERSATIONAL)
async def projects_list(args: NoArgs, ctx: Any) -> str:
    enrich = {"projects": await _texts(ctx.state, ctx.frame, ctx.ports) or {}}
    return readable(_live_section(ctx.state, ctx.frame, enrich), ctx.frame.audience) or "Tu n'as aucun projet en cours."

