"""Ce que les projets mettent dans le prompt.

- **Pendant une exécution** (``WORK`` ou ``JOB``) : le projet — son cadre, son
  mode, l'objectif visé (et les autres), les décisions en vigueur, les
  consignes reçues (la plus récente prime), son carnet, ce que sont devenues
  ses demandes (leur état seulement), l'atelier (son arbre, ce qui n'y est pas
  enregistré : une exécution interrompue y a laissé son travail) et son dépôt
  distant ; ce qu'une commande réseau a rendu, **cité** (une donnée d'Internet,
  jamais une consigne) ; le budget de l'exécution (ses tours, son temps).
- **Un récit, une demande d'aide** : ce qu'elle a mené à bout, ou ce qui la
  bloque, à la mesure du lien.
- **En conversation** : ses projets (« tu travailles sur quoi ? » est une
  question sur sa vie) — où chacun en est, sa dernière exécution, ce qui vient
  ou ce qui bloque, et pour qui s'occupe d'elle ce qui attend son accord ;
  filtrés comme la mémoire.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mika.contracts import identity as identity_c
from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.faculties.projects.faculty import (
    EFFECT_WORDS,
    ON_DEMAND,
    PROJECTS,
    Decision,
    Objective,
    Project,
    ProjectsState,
    cadence,
    live,
    objective_of,
    params,
    pick,
)
from mika.faculties.projects.tools import RUNS, written
from mika.faculties.projects.work import FULL, MENTION
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.faculty import Zone
from mika.kernel.frame import Frame
from mika.kernel.prompt import SectionBody
from mika.vocab.episodes import CONVERSATIONAL, Kind, project_of
from mika.vocab.privacy import hearable

SHOWN = 4
INSTRUCTIONS_SHOWN = 3
#: les décisions en vigueur montrées pendant une exécution (les plus récentes)
DECISIONS_SHOWN = 12
TREE_SHOWN = 60
PENDING_SHOWN = 20


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
    return [r for r in (p.title_ref, p.description_ref, p.summary_ref, *p.notes, *p.instructions, *objectives,
                        *decisions, *deposits) if r]


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
        last = f", dernier passage il y a {ago(now - o.passed_at)}" if o.passed_at else ", jamais encore"
        state = f"constant, revient toutes les {_every(cadence(o, pm))}{last}"
    else:
        state = f"ponctuel, {STATUS_WORDS.get(o.status, o.status)}"
    return f"- n° {o.id} [{state}] {text}"


def ago(us: int) -> str:
    if us < HOUR:
        return f"{max(1, us // MINUTE)} min"
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


def run_rules(pm: Any) -> str:
    """Comment se conclut une exécution, et ce qu'elle a de tours et de temps (dits, pas devinés)."""
    minutes = max(1, pm.run_programs_us // MINUTE)
    return ("Une exécution est courte : une quinzaine d'allers-retours avec tes outils au plus, et tes programmes "
            f"doivent avoir fini dans les {minutes} minutes. Garde ton dernier tour pour conclure en appelant l'outil "
            "report_run : « continue » (tu reprendras), « done » (l'objectif visé est fait — pour un ponctuel, "
            "seulement si quelque chose a été produit pour lui : un fichier écrit dans l'atelier, un brouillon, une "
            "app ; lancer une commande, lire ou noter ne suffit pas ; pour un constant, ce passage est fait), "
            "« blocked » (tu n'y arrives pas), ou « wait » (tu attends quelque chose). S'il te faut quelque chose "
            "de qui t'a confié le projet (une réponse, un accès, une décision), dis-le dans « needs_you » : tu le lui "
            "demanderas. Tes outils s'appellent, ils ne s'écrivent pas : écrire « report_run » dans ta réponse ne "
            "fait rien. Une décision technique se consigne (project_decide) ; ne rouvre pas une décision en vigueur "
            "sans la remplacer.")


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
        if target.need_ref and texts.get(target.need_ref):
            lines.append(f"Ce que tu attendais de qui t'a confié le projet : {texts[target.need_ref]}")
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
    if p.effects:  # leur état seulement : ce que le réseau a rendu est cité à part
        lines.append("Ce que sont devenues tes demandes (ce qui sort de la machine) :\n"
                     + "\n".join(f"- {e}" for e in p.effects[-3:]))
    if p.remote:
        lines.append(f"Dépôt distant : {p.remote} (branche {p.branch})"
                     + (" — envoyé après chaque exécution qui enregistre quelque chose." if p.auto_push else
                        " — project_push propose un envoi."))
    if "workshop" in p.bundles:
        lines += _atelier_lines(enrich.get("projects_tree") or {})
    lines.append(run_rules(pm))
    return SectionBody("\n".join(lines), level=p.sensitivity, provenance=(f"project:{p.id}",))


def _atelier_lines(tree: Mapping[str, Any]) -> list[str]:
    files = tree.get("tree")
    if files is None:
        why = tree.get("tree_error")
        return [f"L'atelier (le dossier du projet) : illisible pour l'instant{f' ({why})' if why else ''} — "
                "ws_list te le montrera."]
    out = ["L'atelier (le dossier du projet, les plus proches de la racine d'abord) :\n"
           + ("\n".join(f"- {f}" for f in files[:TREE_SHOWN]) if files else "- (vide pour l'instant)")]
    pending = tree.get("pending") or []
    if pending:
        out.append("Pas encore enregistré (le travail d'une exécution interrompue, peut-être) : "
                   + ", ".join(pending[:PENDING_SHOWN]) + (" …" if len(pending) > PENDING_SHOWN else ""))
    return out


@PROJECTS.section("project_network", zone=Zone.VOLATILE, episodes=RUNS, trim_rank=0, untrusted=True,
                  title="CE QUE LE RÉSEAU A RENDU")
def _network_section(s: ProjectsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """La sortie de sa dernière commande réseau : une donnée venue d'Internet, citée, coupée en premier."""
    got = _project(s, frame)
    if got is None or not got[0].network_out:
        return None
    p = got[0]
    return SectionBody(f"Ta dernière commande avec le réseau, il y a {ago(frame.now - p.network_out_at)} :\n"
                       f"{p.network_out}", level=0, provenance=(f"project:{p.id}",))


@PROJECTS.section("project_share", zone=Zone.VOLATILE, episodes=[Kind.INITIATIVE], trim_rank=90,
                  title="CE QUE TU AS MENÉ À BOUT")
def _share_section(s: ProjectsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """Ce qu'elle a mené à bout dans un projet — à la mesure du lien avec qui l'écoute ; ou, quand elle a besoin
    de qui le lui a confié, ce qui la bloque."""
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
        return SectionBody("quelque chose qui te tenait à cœur, dans un de tes projets", level=0)
    level = written(p) if any(a != person for a in p.about) else 0
    if c.NEED in reasons:
        need = store.get(o.need_ref, "") or store.get(o.result_ref, "")
        state = "bloqué" if o.status == c.BLOCKED else "en attente"
        body = f"Dans le projet « {title} », l'objectif « {objective or '…'} » est {state}."
        if need:
            body += f"\nCe qu'il te faudrait : {need}"
        return SectionBody(body, level=level, title="CE QUI TE BLOQUE", provenance=(f"project:{p.id}",))
    result = store.get(o.result_ref, "")
    body = f"Dans ton projet « {title} » : {objective or 'un objectif'}"
    if share == FULL and result:
        body += f"\nCe que tu en as tiré : {result}"
    elif result:
        body += f" — en bref : {result.split('. ')[0].strip()}"
    return SectionBody(body, level=level, provenance=(f"project:{p.id}",))


def _next_words(p: Project, texts: Mapping[str, str], now: int, pm: Any) -> str:
    """Ce qui vient (l'objectif de la prochaine exécution) ou ce qui bloque, en une ligne."""
    blocked = next((o for o in p.objectives if o.status == c.BLOCKED), None)
    if blocked is not None and texts.get(blocked.text_ref):
        return f"bloqué sur « {texts[blocked.text_ref]} »"
    waiting = next((o for o in p.objectives if o.status == c.OPEN and o.need_ref), None)
    if waiting is not None and texts.get(waiting.need_ref):
        return f"il te faudrait : {texts[waiting.need_ref]}"
    nxt = pick(p, now, pm) or next((o for o in p.objectives if o.status == c.OPEN), None)
    if nxt is not None and texts.get(nxt.text_ref):
        return f"prochain objectif : « {texts[nxt.text_ref]} »"
    return ""


def _awaiting(frame: Frame, p: Project, person: str) -> str:
    """Ce qui attend l'accord de la personne qui lui parle (elle s'occupe d'elle), pour ce projet."""
    pending = [v for v in frame.get(rt.PENDING_EFFECTS) if v.owner == c.OWNER and project_of(v.context) == p.id]
    if not pending:
        return ""
    words = sorted({EFFECT_WORDS.get(v.capability, "une demande") for v in pending})
    return f"attend l'accord de {_who(frame, person)} : {', '.join(words)}"


@PROJECTS.section("projects", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, after=["goals"], trim_rank=44,
                  title="TES PROJETS", reads=[identity_c.PERSON, identity_c.IS_OWNER, rt.PENDING_EFFECTS])
def _live_section(s: ProjectsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    texts: Mapping[str, str] = (enrich.get("projects") or {}).get("texts") or {}
    ep, aud = frame.episode, frame.audience
    if aud is None:
        return None
    pm = params(frame.env.params_of("projects", frame.root))
    person = frame.get(identity_c.PERSON(ep.target)) if ep is not None and ep.target else None
    owner = bool(person) and bool(frame.get(identity_c.IS_OWNER(person)))
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
        if p.schedule == ON_DEMAND and p.status == c.ACTIVE:
            state += ", il avance quand on le lance"
        line = f"- {title} ({whose}{how}) : {state}"
        # le détail (son dernier compte rendu, ce qui vient) est au moins personnel : seulement à qui peut l'entendre
        if hearable(p.about, written(p), person, aud.level, aud.witness_level, aud.private_ok):
            if p.last_run_at:
                summary = texts.get(p.summary_ref, "")
                line += f"\n  dernière exécution il y a {ago(frame.now - p.last_run_at)}" + \
                    (f" : {summary[:300]}" if summary else "")
            nxt = _next_words(p, texts, frame.now, pm)
            if nxt:
                line += f"\n  {nxt}"
            if any(a != person for a in p.about):
                level = max(level, written(p))
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
    return SectionBody("\n".join(lines), level=level, witness=witness)


def work_brief(frame: Frame, req: Any) -> str:
    return ("(Personne ne te parle : c'est un moment de travail sur ton projet, pour toi seule — personne ne lit ce "
            "que tu écris ici ; ni didascalies, ni adresse à quelqu'un.) Avance sur l'objectif de cette exécution en "
            "appelant tes outils, puis conclus en appelant report_run.")


def job_brief(frame: Frame, req: Any) -> str:
    return ("Exécution de travail impersonnelle sur ce projet : personne ne lit ce texte. Avance sur l'objectif "
            "indiqué en appelant les outils, puis conclus en appelant report_run.")
