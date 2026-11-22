"""Ce que partagent les onglets refaits de la fiche d'un projet (ADR 0297) : les couleurs d'état de l'écran Projets, les
adresses de la fiche, les formulaires que la console prépare pour un objet choisi, un texte en Markdown, et la carte
d'une pull request avec son statut.

**Les trois zones.** Un onglet en liste et détail rend lui-même ``.pj-split`` > ``.pj-list`` + ``.pj-detail``, et dans
le détail ``.pj-dz`` > ``.pj-main`` + ``.pj-side`` (``projets/zones.html``, ``projets_zones.css``). Un choix d'élément
est une adresse — la page se recharge sur lui (``lire`` : sur un téléphone, le détail remplace la liste) ; un volet du
détail est un sous-onglet (``[data-subtabs]``, une section par ancre).

**Les formulaires.** Chaque geste est une action déclarée de la faculté : ``prepared`` demande à la console le
formulaire d'une action pour le projet (son jeton, son retour, ses champs), avec ce que la page fixe (l'objectif, le
jalon, le ticket visés) — comme elle prépare ceux des blocs d'un onglet (``Forms.of``).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

from markupsafe import Markup

from mika.app.handmade.subjects.parts import texts
from mika.contracts import projects as c
from mika.faculties.projects import glance, pulls
from mika.faculties.projects.faculty import project_at
from mika.faculties.projects.inspect import CHECKS_FR, PULL_FR
from mika.faculties.projects.inspect_code import PULLS, pull_key
from mika.inspector import render
from mika.inspector.document import readable_markdown
from mika.inspector.pages.subjects import subject_url
from mika.inspector.ui import UI, Forms
from mika.kernel.clock import US
from mika.kernel.inspect import ActionSlot, relative_fr, short_day_fr
from mika.ports.workshop import (
    CHECKS_FAILED,
    CHECKS_PASSED,
    CHECKS_PENDING,
    PULL_CLOSED,
    PULL_MERGED,
    PULL_OPEN,
)

KIND = "project"
#: les couleurs d'état de l'écran, les mêmes partout (``projets_fiche.css``) : à toi, elle y travaille, fait, en échec,
#: en attente
YOU, WORK, DONE, FAIL, WAIT = "you", "work", "done", "fail", "wait"
#: où en est un jalon (``glance.milestone_state``) → sa couleur dans la barre de son objectif
MARK_TONES = {glance.M_REACHED: DONE, glance.M_READY: YOU, glance.M_REFUSED: FAIL, glance.M_STARTED: WORK,
              glance.M_TODO: "", glance.M_DROPPED: ""}
#: le statut d'un objectif → sa couleur
OBJECTIVE_TONES = {c.OPEN: WORK, c.DONE: DONE, c.BLOCKED: FAIL, c.DROPPED: WAIT}
#: les vérifications d'une pull request → leur couleur, et leurs mots en court
CHECKS_TONES = {CHECKS_PASSED: DONE, CHECKS_FAILED: FAIL, CHECKS_PENDING: WORK}
CHECKS_SHORT = {CHECKS_PASSED: "CI passée", CHECKS_FAILED: "CI en échec", CHECKS_PENDING: "CI en cours"}
#: l'état d'une pull request → sa couleur, et son mot en court
PULL_TONES = {PULL_OPEN: WORK, PULL_MERGED: DONE, PULL_CLOSED: WAIT}
PULL_SHORT = {PULL_OPEN: "ouverte", PULL_MERGED: "fusionnée", PULL_CLOSED: "fermée"}


def tab_url(key: str, tab: str = "", anchor: str = "", **params: Any) -> str:
    """L'adresse d'un onglet de la fiche, avec ce qu'il ouvre (un objectif, un ticket, un volet) ; un paramètre vide
    ne s'écrit pas."""
    extra = urlencode({k: str(v) for k, v in params.items() if v not in (None, "", 0, False)})
    base = subject_url(KIND, key, tab)
    if extra:
        base += ("&" if "?" in base else "?") + extra
    return base + (f"#{anchor}" if anchor else "")


def pull_href(key: str, o: Any, anchor: str = "") -> str:
    """Où se lit la pull request d'un objectif dans la fiche : Code › Pull requests, elle choisie (ADR 0297)."""
    return tab_url(key, "git", anchor, vue=PULLS, pr=pull_key(o))


def prepared(ui: UI, forms: Any, query: Mapping[str, str], key: str, action: str, back: str = "",
             **initial: Any) -> dict[str, Any] | None:
    """Le formulaire d'une action déclarée pour ce projet, préparé par la console comme ceux des blocs d'un onglet —
    son jeton, ses champs, ce que la page fixe (``initial`` : l'objectif, le jalon, le ticket visés ; un champ visible
    y prend sa valeur de départ). ``back`` : où l'on revient après (par défaut, la page même). ``None`` : l'action
    n'est pas offerte maintenant (un projet archivé), ou la page est rendue hors d'une requête."""
    if not isinstance(forms, Forms):
        return None
    slots = render.blocks([ActionSlot(action, tuple((k, v) for k, v in initial.items()))], ui.env(), query)
    got = forms.of(slots, key).get(slots[0]["slot"])
    if got is None:
        return None
    return {**got, "back": back} if back else got


def shown(form: Mapping[str, Any] | None, *paths: str, **fixed: str) -> dict[str, Any] | None:
    """Un formulaire préparé, réduit à ce que la page en montre : ``paths``, ses champs visibles, dans cet ordre ;
    ``fixed``, des champs dont la page pose la valeur sans les montrer (le verdict d'un bouton). Les autres gardent
    leur valeur par défaut."""
    if form is None:
        return None
    by_path = {f["path"]: f for f in form.get("fields", [])}
    return {**form, "fields": [by_path[p] for p in paths if p in by_path],
            "posed": [(k, v) for k, v in fixed.items() if k in by_path]}


def markdown(text: str) -> Markup:
    """Un texte écrit en Markdown (une description, un plan), rendu comme le chat le rend : le HTML brut du texte
    reste du texte."""
    return readable_markdown(text or "", pro=True)


def pull_card(p: Any, o: Any, now: int, href: str) -> dict[str, Any] | None:
    """La pull request d'un objectif avec son statut — où elle en est, ses vérifications, sa relecture, ses conflits,
    son adresse chez l'hôte —, ou ``None`` : il n'en a pas. ``href`` : où elle se lit dans la fiche (l'onglet Code)."""
    if not (o.pull_state or o.pull or o.pull_proposal):
        return None
    state = o.pull_state
    said = "proposée : elle attend ton accord" if o.pull_proposal and not state else \
        "des changements demandés" if state == PULL_OPEN and o.pull_changes else PULL_SHORT.get(state, state)
    return {"n": o.pull, "title": pulls.title_of(o), "href": href, "url": pulls.pull_url(p, o),
            "age": relative_fr(o.pull_at, now) if o.pull_at else "", "state": said,
            "state_said": PULL_FR.get(state, said), "tone": YOU if o.pull_proposal and not state else
            PULL_TONES.get(state, WAIT), "checks": CHECKS_SHORT.get(o.checks, "") if o.checks_sha else "",
            "checks_tone": CHECKS_TONES.get(o.checks, WAIT), "checks_said": CHECKS_FR.get(o.checks, ""),
            "review": "" if not o.review_at else "relue" if o.review_ok else "relue : des constats",
            "review_tone": DONE if o.review_ok else FAIL, "conflicts": bool(o.pull_conflicts and state == PULL_OPEN)}


@dataclass(slots=True)
class Scene:
    """Ce qu'un onglet refait lit pour se dessiner : la console, le projet dans sa tranche, l'instant, les paramètres
    de l'adresse et les formulaires de la page."""

    ui: UI
    key: str
    query: Mapping[str, str]
    forms: Any
    frame: Any = field(init=False)
    s: Any = field(init=False)
    p: Any = field(init=False)
    now: int = field(init=False)

    def __post_init__(self) -> None:
        self.frame = self.ui.kernel.mind.frame()
        self.s = self.frame.state("projects")
        self.p = project_at(self.s, self.key)
        self.now = self.frame.now

    def url(self, tab: str = "", anchor: str = "", **params: Any) -> str:
        return tab_url(self.key, tab, anchor, **params)

    def form(self, action: str, back: str = "", **initial: Any) -> dict[str, Any] | None:
        return prepared(self.ui, self.forms, self.query, self.key, f"projects.{action}", back, **initial)

    def texts(self, refs: Iterable[str]) -> dict[str, str]:
        return texts(self.ui, [r for r in refs if r])

    def ago(self, at: int) -> str:
        """« il y a 3 h » ; vide sans instant."""
        return relative_fr(at, self.now) if at else ""

    def age(self, at: int) -> str:
        """Depuis quand, en court, pour une ligne de liste : « 3 h », « 2 j »."""
        return relative_fr(at, self.now).removeprefix("il y a ") if at else ""

    def when(self, at: int) -> str:
        """L'instant, comme la console le dit (« 21/11 13:58 ») ; vide sans instant."""
        return self.ui.when(at) if at else ""

    def day(self, at: int) -> str:
        """Le jour, en court (« 3 nov. »)."""
        d = datetime.fromtimestamp(at / US, self.ui.tz)
        return short_day_fr(d.date()).split(" ", 1)[1]

    def local(self, at: int) -> datetime:
        return datetime.fromtimestamp(at / US, self.ui.tz)
