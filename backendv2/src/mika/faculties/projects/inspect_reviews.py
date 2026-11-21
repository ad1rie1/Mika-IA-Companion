"""Ce que la console dit de la relecture indépendante (ADR 0276) — le nécessaire : le réglage du projet (ses choix
et son aide, que « Créer un projet » et « Modifier le projet » reprennent), sur la ligne d'un objectif son dernier
verdict et ses constats, et dans l'aperçu d'une proposition (une pull request, un envoi) le verdict du commit qui
part. Des textes de console, lus par qui décide — pas des phrases qu'elle lit : les siennes sont dans
``persona/voix.yaml`` (``projects.review``). Rien ici ne lit l'atelier ni n'écrit : ``review.py`` porte la relecture
elle-même ; la refonte de l'interface des projets est un autre lot.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mika.contracts import projects as c
from mika.faculties.projects.faculty import (
    REVIEW_TRIES_MAX,
    Objective,
    Project,
    handed_over,
    rereads,
    review_holds,
)
from mika.kernel.inspect import Prose

#: le réglage, sur la fiche du projet
REREAD_LABEL = "Relecture indépendante"
REREAD_CHOICES = ((c.REREAD_NEVER, "jamais"),
                  (c.REREAD_OUT, "avant de sortir : une pull request, un envoi au dépôt distant"),
                  (c.REREAD_EACH, "à chaque objectif dit « fait »"))
REREAD_HELP = ("Avant que son travail sorte, une autre exécution le relit sans ce que la première en a dit : la "
               "demande, le critère, les jalons et le diff. Bon : la proposition part, et son aperçu porte le "
               "verdict. Sinon ses constats rouvrent l'objectif ; après deux refus de suite, il te revient avec les "
               "deux avis. Chaque relecture compte comme une exécution. Son modèle se règle à part (Réglages › "
               "Modèles, rôle « relire un travail »).")
REREAD_UNKNOWN = "jamais, avant de sortir, ou à chaque « fait »"
#: sur la ligne d'un objectif : le titre de son détail (la fiche dessinée le reprend par ce titre)
TITLE = "Sa relecture"
WORDS = {
    "good": "relu au commit {sha}{by} : bon",
    "refused": "relu au commit {sha}{by} : refusé ({n} refus de suite)",
    "due": "une relecture est demandée pour le commit {sha}",
    "silent": "sa relecture du commit {sha} n'a pas conclu ({n} essais) : elle ne repart pas d'elle-même",
    "handed": "deux relectures de suite l'ont refusé : la main est à toi (réponds-lui, donne une consigne, ou "
              "règle la relecture du projet)",
    "by": " par « {by} »",
    "findings": "Ses constats :",
    "first": "L'avis d'avant :",
}
#: dans l'aperçu d'une proposition : ce que la relecture a dit du commit qui part
PREVIEW = {
    "good": "Relecture indépendante : bon, au commit {sha}{by}.",
    "none": "Relecture indépendante : aucun verdict favorable pour le commit {sha}.",
    "off": "Relecture indépendante : ce projet n'en demande pas.",
}
#: pourquoi une pull request ne part pas sans elle
UNREVIEWED = "aucune relecture indépendante n'a dit bon pour ce commit (réglage du projet : relecture avant de sortir)"


def _by(o: Objective) -> str:
    return WORDS["by"].format(by=o.review_by) if o.review_by else ""


def judged(p: Project, sha: str) -> Objective | None:
    """L'objectif de ce projet qu'une relecture a dit bon pour ce commit-là."""
    return next((o for o in p.objectives if review_holds(o, sha)), None)


def review_line(p: Project, o: Objective | None, sha: str) -> str:
    """Ce que l'aperçu d'une proposition dit de la relecture du commit qui part : qui a relu, quel commit — ou
    qu'aucun verdict ne le couvre, ou que le projet n'en demande pas. ``o`` : l'objectif que la proposition porte
    (une pull request) ; sans lui, celui qu'une relecture a dit bon pour ce commit (un envoi)."""
    if not sha:
        return ""
    if p.reread == c.REREAD_NEVER:
        return PREVIEW["off"]
    good = o if o is not None and review_holds(o, sha) else judged(p, sha) if o is None else None
    if good is not None:
        return PREVIEW["good"].format(sha=sha[:12], by=_by(good))
    return PREVIEW["none"].format(sha=sha[:12])


def review_words(p: Project, o: Objective) -> str:
    """Où en est la relecture d'un objectif, en une ligne (vide : rien à en dire)."""
    said = []
    if o.reviewed:
        key = "good" if o.review_ok else "refused"
        said.append(WORDS[key].format(sha=o.reviewed[:12], by=_by(o), n=len(o.review_refused)))
    if handed_over(o):
        said.append(WORDS["handed"])
    elif o.review_due and o.review_tries >= REVIEW_TRIES_MAX:
        said.append(WORDS["silent"].format(sha=o.review_due[:12], n=o.review_tries))
    elif o.review_due and rereads(p, o):
        said.append(WORDS["due"].format(sha=o.review_due[:12]))
    return " · ".join(said)


def refs(objectives: Any) -> list[str]:
    """Les textes à lire pour dire la relecture de ces objectifs : leurs constats, et ceux des refus d'avant."""
    return [r for o in objectives for r in (o.review_ref, *o.review_refused) if r]


def detail(p: Project, o: Objective, texts: Mapping[str, str]) -> list[Any]:
    """Ce que la ligne d'un objectif dit de sa relecture : son dernier verdict et ses constats ; quand la main est
    revenue au propriétaire, l'avis d'avant aussi."""
    words = review_words(p, o)
    if not words:
        return []
    rows = [words]
    last = texts.get(o.review_ref, "") if o.review_ref else ""
    if last:
        rows += [WORDS["findings"], last]
    earlier = [texts.get(r, "") for r in o.review_refused if r != o.review_ref]
    if handed_over(o) and any(earlier):
        rows += [WORDS["first"], *(x for x in earlier if x)]
    return [Prose("\n".join(rows), title=TITLE)]


__all__ = ["REREAD_CHOICES", "REREAD_HELP", "REREAD_LABEL", "TITLE", "UNREVIEWED", "detail", "judged", "refs",
           "review_line", "review_words"]
