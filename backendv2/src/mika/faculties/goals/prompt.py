"""Ce que les buts mettent dans le prompt.

- **Pendant un pas** : ce à quoi elle travaille — le but, son cadre (un
  projet confié), les consignes reçues depuis (la plus récente prime), où
  elle en est, son carnet, ce que sont devenues ses demandes, l'atelier.
- **Un rappel, un récit** : le texte du rappel, ou ce qu'elle a mené à bout —
  selon le lien avec qui l'écoute (tout, l'essentiel, ou le titre).
- **En conversation** : ce qu'elle a en train (« tu fais quoi en ce
  moment ? » est une question sur sa vie qu'elle doit pouvoir entendre),
  filtré comme la mémoire.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from mika.contracts import goals as c
from mika.contracts import identity as identity_c
from mika.faculties.goals.faculty import GOALS, Goal, GoalsState, live, status
from mika.faculties.goals.work import FULL, MENTION
from mika.kernel.clock import DAY, local
from mika.kernel.faculty import Zone
from mika.kernel.frame import Frame
from mika.kernel.prompt import SectionBody, readable
from mika.vocab.episodes import CONVERSATIONAL, Kind, goal_of
from mika.vocab.privacy import hearable

SHOWN = 4
#: les dernières consignes d'un opérateur montrées pendant un pas
INSTRUCTIONS_SHOWN = 3


def _subject(frame: Frame) -> int | None:
    ep = frame.episode
    if ep is None:
        return None
    return goal_of(ep.target) or goal_of(ep.attrs.get("subject"))


def _refs(g: Goal) -> list[str]:
    return [r for r in (g.title_ref, g.details_ref, g.summary_ref, g.result_ref, *g.notes, *g.instructions) if r]


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
    out: dict[str, Any] = {"texts": store.content(refs) if refs else {}}
    atelier = ports.get("workshop")
    g = s.goals.get(subject) if subject is not None else None
    if ep is not None and ep.kind == Kind.STEP and g is not None and "workshop" in g.bundles and atelier is not None:
        out["tree"] = await atelier.tree(g.id) if atelier.exists(g.id) else []
    return out


def _who(frame: Frame, key: str | None) -> str:
    name = frame.get(identity_c.IDENTITY(key)).name if key else ""
    return f"« {name} »" if name else "quelqu'un"


def _progress(g: Goal) -> str:
    if not g.max_steps:
        return ""
    left = g.max_steps - g.steps
    if g.steps <= 1:
        return "tu commences à peine"
    if left <= 1:
        return "tu arrives au bout de ce que tu t'étais donné"
    return f"pas {g.steps} sur {g.max_steps}"


STEP_RULES = ("Conclus ce pas par report_step : « continue » (tu reprendras), « done » (seulement si tu as réellement "
              "fait quelque chose — un outil qui a produit un résultat), « blocked » (tu n'y arrives pas), ou "
              "« wait » (tu attends quelque chose).")


@GOALS.section("step", zone=Zone.VOLATILE, episodes=[Kind.STEP], trim_rank=90, title="CE À QUOI TU TRAVAILLES")
def _step(s: GoalsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    gid = _subject(frame)
    g = s.goals.get(gid) if gid is not None else None
    if g is None:
        return None
    data = enrich.get("goals") or {}
    texts: Mapping[str, str] = data.get("texts") or {}
    kind = {c.EXPLORATION: "une exploration que tu as entreprise de toi-même",
            c.PROJECT: f"un projet que {_who(frame, g.address or g.owner)} t'a confié"}.get(g.kind, g.kind)
    lines = [f"Sorte : {kind}.", f"But : {texts.get(g.title_ref, '(titre oublié)')}"]
    if g.details_ref and texts.get(g.details_ref):
        lines.append(f"Cadre (confié, tu ne le changes pas) : {texts[g.details_ref]}")
    if g.kind == c.PROJECT and g.due is not None:
        lines.append(f"À rendre pour le {local(g.due, frame.env.tz_of(frame.root)):%d/%m à %H:%M}.")
    instructions = [texts[r] for r in g.instructions if texts.get(r)]
    if instructions:
        lines.append("Consignes reçues depuis (à suivre ; la plus récente prime) :\n"
                     + "\n".join(f"- {i}" for i in instructions[-INSTRUCTIONS_SHOWN:]))
    progress = _progress(g)
    if g.summary_ref and texts.get(g.summary_ref):
        lines.append(f"Où tu en es{f' ({progress})' if progress else ''} : {texts[g.summary_ref]}")
    elif progress:
        lines.append(f"Où tu en es : {progress}.")
    notes = [texts[r] for r in g.notes if texts.get(r)]
    if notes:
        lines.append("Ton carnet :\n" + "\n".join(f"- {n}" for n in notes[-3:]))
    if g.effects:
        lines.append("Tes demandes (ce qui sort de la machine) :\n" + "\n".join(f"- {e}" for e in g.effects[-3:]))
    if "workshop" in g.bundles:
        tree = data.get("tree")
        lines.append("L'atelier (ton dossier) :\n" + ("\n".join(f"- {f}" for f in tree[:40]) if tree
                                                        else "- (vide pour l'instant)"))
    lines.append(STEP_RULES)
    return SectionBody("\n".join(lines), level=g.sensitivity, provenance=(f"goal:{g.id}",))


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
    title = texts.get(g.title_ref)
    ep = frame.episode
    person = frame.get(identity_c.PERSON(ep.target)) if ep is not None and ep.target else None
    got = _levels(g, person, frame)
    args = ep.attrs.get("args") if ep is not None else None
    share = str(args.get("share", MENTION)) if args else MENTION
    if g.kind == c.REMINDER:
        if not title or got is None:
            return None
        when = f" (prévu pour {local(g.due, frame.env.tz_of(frame.root)):%H:%M})" if g.due else ""
        return SectionBody(f"{title}{when}", level=got[0], witness=got[1], title="LE RAPPEL",
                           provenance=(f"goal:{g.id}",))
    if got is None or share == MENTION or not title:
        # une simple mention : le titre seulement s'il peut s'entendre, sinon rien de précis
        shown = title if title and got is not None and g.sensitivity <= 1 else "quelque chose qui te tenait à cœur"
        return SectionBody(shown, level=0, title="CE QUE TU AS MENÉ À BOUT")
    result = texts.get(g.result_ref, "")
    if share == FULL:
        body = f"{title}\nCe que tu en as tiré : {result}" if result else title
    else:
        first = result.split(". ")[0].strip() if result else ""
        body = title + (f" — en bref : {first}" if first else "")
    return SectionBody(body, level=got[0], witness=got[1], title="CE QUE TU AS MENÉ À BOUT",
                       provenance=(f"goal:{g.id}",))


@GOALS.section("goals", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, after=["thoughts"], trim_rank=45,
               title="CE QUE TU AS EN TRAIN", reads=[identity_c.PERSON])
def _live_section(s: GoalsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    texts: Mapping[str, str] = (enrich.get("goals") or {}).get("texts") or {}
    ep, aud = frame.episode, frame.audience
    if aud is None:
        return None
    person = frame.get(identity_c.PERSON(ep.target)) if ep is not None and ep.target else None
    lines, level, witness = [], 0, False
    tz = frame.env.tz_of(frame.root)
    for g in _recent(s, frame.now)[-SHOWN * 2:]:
        title = texts.get(g.title_ref)
        if not title or not hearable(g.about, g.sensitivity, person, aud.level, aud.witness_level, aud.private_ok):
            continue
        if g.status == c.ACHIEVED:
            lines.append(f"- tu as mené à bout : {title}")
        elif status(g, frame.now) == c.PAUSED:
            lines.append(f"- mis en pause pour l'instant : {title}")
        elif g.kind == c.REMINDER:
            when = f"{local(g.due, tz):%d/%m à %H:%M}" if g.due else "bientôt"
            lines.append(f"- un rappel promis à {_who(frame, g.address)} pour le {when} : {title}")
        elif g.kind == c.PROJECT:
            lines.append(f"- un projet pour {_who(frame, g.address or g.owner)} : {title} ({_progress(g) or 'en cours'})")
        else:
            waiting = ""
            if g.status == c.WAITING:
                waiting = (f" — tu attends la réponse de {_who(frame, g.wait_for)}" if g.wait_for
                           else " — tu attends avant d'y revenir")
            lines.append(f"- tu explores : {title} ({_progress(g) or 'en cours'}){waiting}")
        if any(a != person for a in g.about):  # ce qui ne concerne que l'interlocuteur ne compte pas ici
            level = max(level, g.sensitivity)
            witness = witness or person in g.about
        if len(lines) >= SHOWN:
            break
    if not lines:
        return None
    return SectionBody("\n".join(lines), level=level, witness=witness)


def step_brief(frame: Frame, req: Any) -> str:
    return ("(Personne ne te parle : c'est un moment de travail, pour toi seule — personne ne lit ce que tu écris "
            "ici.) Avance d'un pas sur ce but avec tes outils, puis conclus par report_step.")


# ── Outil : relire ce qu'elle a en train (même filtre que la section) ──


class NoArgs(BaseModel):
    pass


@GOALS.tool("goals_list", description="Relire ce que tu as en train : tes projets, tes explorations, tes rappels.",
            args=NoArgs, bundle="goals", episodes=CONVERSATIONAL)
async def goals_list(args: NoArgs, ctx: Any) -> str:
    enrich = {"goals": await _texts(ctx.state, ctx.frame, ctx.ports) or {}}
    return readable(_live_section(ctx.state, ctx.frame, enrich), ctx.frame.audience) or "Tu n'as rien en train."
