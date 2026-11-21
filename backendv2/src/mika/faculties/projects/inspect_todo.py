"""« Ce qui t'attend » dans la console (ADR 0281) : les mots et les lignes de ``todo.py``.

La règle (ce qui attend une personne, dans quel ordre, quel geste) est dans ``todo.py``, sans un mot. Ici, ce que la
console en dit : la sorte de chaque attente en étiquette, de quoi il s'agit en une ligne, depuis quand, qui elle
attend, et le lien vers l'endroit où elle se règle — l'onglet de la fiche ouvert sur l'objet, la file « À valider »
ouverte sur la demande, la page de la pull request chez l'hôte. Les éléments d'une même liste de suivi, au-delà de
``ITEMS_SHOWN``, se résument en une ligne qui mène à la liste. La fiche d'un projet (« Où il en est ») et la page
d'ensemble (« Ses projets ») posent ces lignes en tête.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from mika.faculties.projects import todo
from mika.faculties.projects.faculty import (
    ISSUE_CAPABILITY,
    ISSUE_NOTE_CAPABILITY,
    ISSUE_STATE_CAPABILITY,
    NETWORKED_CAPABILITY,
    PULL_CAPABILITY,
    PULL_REQUEST_CAPABILITY,
    PUSH_CAPABILITY,
    STEER_CAPABILITY,
    Project,
    ProjectsState,
)
from mika.faculties.projects.pulls import pull_url
from mika.kernel.inspect import Badge, Column, Ref, Row, Table, Text, When, agree, plural

TITLE = "Ce qui t'attend"
EVERYWHERE_TITLE = "À faire"
FORGOTTEN = "(oublié)"
#: les éléments d'une même liste montrés un par un ; au-delà, une ligne les résume et mène à la liste
ITEMS_SHOWN = 3
#: les attentes montrées sur la page d'ensemble ; au-delà, chaque projet dit les siennes sur sa fiche
EVERYWHERE_SHOWN = 12

KIND_WORDS = {todo.APPROVAL: "ton accord", todo.PLAN: "son plan", todo.NEED: "besoin de toi",
              todo.STALLED: "en panne", todo.BLOCKED: "objectif bloqué", todo.TICKET: "ticket",
              todo.CHECKPOINT: "point d'arrêt", todo.REVIEW: "relecture refusée", todo.ITEM: "à ta charge"}
KIND_TONES = {todo.STALLED: "danger", todo.BLOCKED: "danger", todo.ITEM: "info"}
CAPABILITY_WORDS = {PUSH_CAPABILITY: "Pousser vers le dépôt distant", PULL_CAPABILITY: "Récupérer du dépôt distant",
                    NETWORKED_CAPABILITY: "Une commande avec le réseau",
                    PULL_REQUEST_CAPABILITY: "Ouvrir une pull request", ISSUE_CAPABILITY: "Publier un ticket en issue",
                    ISSUE_STATE_CAPABILITY: "Fermer ou rouvrir une issue",
                    ISSUE_NOTE_CAPABILITY: "Publier une note chez l'hôte", STEER_CAPABILITY: "Un pilotage demandé"}
#: un effet proposé pendant son travail par un autre que la faculté des projets (l'appel d'un service, d'une app)
OTHER_CAPABILITY = "Un appel proposé pendant son travail"
TICKET_WORDS = {todo.ACCEPT: "proposé : à accepter ou à écarter", todo.QUESTION: "elle te pose une question",
                todo.DISMISSAL: "elle propose de l'écarter", todo.VALIDATION: "son plan attend ta validation",
                todo.MERGE: "sa pull request est prête à fusionner", todo.STUCK: "son objectif bloque"}
GESTURES = {todo.APPROVAL: "Décider dans « À valider »", todo.PLAN: "Lire son plan et répondre",
            todo.NEED: "Lui répondre", todo.STALLED: "Voir ses pannes, puis reprendre",
            todo.BLOCKED: "Le rouvrir ou le retirer", todo.CHECKPOINT: "Valider ou refuser",
            todo.REVIEW: "Lire ses constats et trancher", todo.ITEM: "Ouvrir l'élément"}
TICKET_GESTURES = {todo.ACCEPT: "Accepter ou écarter", todo.QUESTION: "Répondre", todo.DISMISSAL: "Confirmer ou répondre",
                   todo.VALIDATION: "Valider ou refuser son plan", todo.MERGE: "Fusionner chez l'hôte",
                   todo.STUCK: "Débloquer son objectif"}
EMPTY = "rien ne t'attend ici : il avance seul"
EVERYWHERE_EMPTY = "rien ne t'attend : ses projets avancent seuls"
CAPTION = ("Dans l'ordre où s'en occuper : ce qui attend ton accord pour sortir, un plan sans réponse, une demande "
           "d'aide ou une panne, les tickets dont la main est à toi, un point d'arrêt, une relecture refusée deux "
           "fois, puis ce qui est à ta charge dans ses listes. Chaque ligne mène là où elle se règle.")


def refs(found: Iterable[todo.Waiting]) -> list[str]:
    """Les textes que ces attentes citent, à lire avec ceux de la vue."""
    return [w.ref for w in found if w.ref]


def _said(texts: Mapping[str, str], ref: str) -> str:
    if not ref:
        return ""
    got = texts.get(ref)
    return FORGOTTEN if got is None else " ".join(got.split())


def about(w: todo.Waiting, texts: Mapping[str, str]) -> str:
    """De quoi il s'agit, en une ligne."""
    said = _said(texts, w.ref)
    if w.kind == todo.APPROVAL:
        what = CAPABILITY_WORDS.get(w.what, OTHER_CAPABILITY)
        return f"{what} — {said}" if said else what
    if w.kind == todo.PLAN:
        return "Son plan attend une réponse : le valider le lance, demander une révision le lui fait reprendre."
    if w.kind == todo.NEED:
        return f"Objectif n° {w.objective} — {said or 'elle a besoin de toi'}"
    if w.kind == todo.STALLED:
        return "Arrêté après des pannes d'affilée : il ne repart pas seul."
    if w.kind == todo.BLOCKED:
        return f"Objectif n° {w.objective} bloqué" + (f" — {said}" if said else "")
    if w.kind == todo.TICKET:
        return f"#{w.number} {said or FORGOTTEN} — {TICKET_WORDS.get(w.what, '')}"
    if w.kind == todo.CHECKPOINT:
        return f"Objectif n° {w.objective}, jalon n° {w.number} — {said or FORGOTTEN} : elle le dit prêt."
    if w.kind == todo.REVIEW:
        return (f"Objectif n° {w.objective} — ses relectures l'ont refusé deux fois de suite : la main est à toi"
                + (f". Dernier constat : {said}" if said else "."))
    return f"{said or w.key} (liste « {w.what} »)"


def where(p: Project, w: todo.Waiting) -> Ref:
    """Où se règle une attente : le lien de son geste."""
    words = TICKET_GESTURES.get(w.what, "Ouvrir le ticket") if w.kind == todo.TICKET else GESTURES.get(w.kind, "Ouvrir")
    g = w.gesture
    if g.where == todo.QUEUE:
        return Ref.approvals(words, "en_attente", **dict(g.params))
    if g.where == todo.HOST and (o := todo.objective_of(p, w)) is not None and (url := pull_url(p, o)):
        return Ref.url(url, words)
    return Ref("subject", f"project/{p.id}", words, (("onglet", g.tab or "apercu"), *g.params))


def _row(p: Project, w: todo.Waiting, texts: Mapping[str, str], who: Callable[[Project, todo.Waiting], Any],
         named: Any = None) -> Row:
    cells = (Badge(KIND_WORDS.get(w.kind, w.kind), KIND_TONES.get(w.kind, "warn")), Text(about(w, texts), clamp=220),
             When(w.since) if w.since else "—", who(p, w), where(p, w))
    return Row(cells if named is None else (named, *cells))


def _more(p: Project, w: todo.Waiting, n: int, named: Any = None) -> Row:
    """Les autres éléments d'une liste, en une ligne qui mène à elle."""
    cells = (Badge(KIND_WORDS[todo.ITEM], "info"),
             Text(f"… et {plural(n, 'autre élément', 'autres éléments')} de la liste « {w.what} » "
                  f"{agree(n, 'est', 'sont')} à ta charge."), "—", "—",
             Ref("subject", f"project/{p.id}", "Ouvrir la liste", (("onglet", "suivi"), ("liste", w.what))))
    return Row(cells if named is None else (named, *cells))


def rows(s: ProjectsState, found: Iterable[todo.Waiting], texts: Mapping[str, str],
         who: Callable[[Project, todo.Waiting], Any], named: Callable[[Project], Any] | None = None) -> list[Row]:
    """Une ligne par attente, dans leur ordre ; ``named`` : le projet en première colonne (la page d'ensemble)."""
    out: list[Row] = []
    seen: dict[tuple[int, str], int] = {}
    hidden: dict[tuple[int, str], tuple[int, int]] = {}
    for w in found:
        p = s.projects.get(w.project)
        if p is None:
            continue
        name = named(p) if named is not None else None
        if w.kind == todo.ITEM:
            at = (w.project, w.what)
            seen[at] = seen.get(at, 0) + 1
            if seen[at] > ITEMS_SHOWN:
                if at not in hidden:
                    hidden[at] = (len(out), 0)
                    out.append(_more(p, w, 1, name))
                where_, n = hidden[at]
                hidden[at] = (where_, n + 1)
                out[where_] = _more(p, w, n + 1, name)
                continue
        out.append(_row(p, w, texts, who, name))
    return out


COLUMNS = (Column("quoi", "fit", role="badge"), Column("de quoi il s'agit", role="title"), Column("depuis", "fit"),
           Column("attend", "fit"), Column("le geste", "fit"))


def table(s: ProjectsState, found: Iterable[todo.Waiting], texts: Mapping[str, str],
          who: Callable[[Project, todo.Waiting], Any], *, named: Callable[[Project], Any] | None = None,
          title: str = TITLE, empty: str = EMPTY, most: int = 0) -> Table:
    """La liste de ce qui attend, pour une fiche (``named`` absent) ou pour tous les projets ; ``most`` : combien de
    lignes au plus (0 : toutes) — le reste se dit en légende."""
    found = tuple(found)
    count = sum(1 for w in found if w.project in s.projects)  # les attentes, pas les lignes : une ligne en résume
    every = rows(s, found, texts, who, named)
    shown = every[:most] if most else every
    left = len(every) - len(shown)
    caption = CAPTION + (f" {plural(left, 'autre attente', 'autres attentes')} : sur la fiche de chaque projet."
                         if left else "")
    columns = COLUMNS if named is None else (Column("projet"), *COLUMNS)
    return Table(columns, tuple(shown), title=f"{title} ({count})" if count else title, empty=empty,
                 caption=caption if every else "")
