"""La fiche d'un projet : sa vue d'ensemble, ses onglets Objectifs, Décisions et « Accès » dessinés (ADR 0121, 0133,
0177).

- La vue d'ensemble suit la vue d'un objet de la maquette (ADR 0176) : un seul bandeau (ce qui attend ton accord —
  « Les décider » ouvre la file des validations —, sinon sa pause ou ce qui le retient), une bande de chiffres (la
  dernière exécution en barres), puis des tuiles qui mènent à leurs onglets — objectifs, exécutions, décisions en
  vigueur, son cadre, sa prochaine exécution, son dépôt —, et son plan avec sa réponse quand il en a un. Les données
  sont celles de l'onglet « Vue d'ensemble » de la faculté (``Got``) : ses blocs servent la console en MCP et le repli.
- Objectifs : ses chiffres, puis une entrée par objectif — son numéro, ce qu'il vise en clair, sa sorte et son état,
  son rythme, qui l'a posé, son dernier compte rendu (long, il tient en quatre lignes que « lire la suite » déplie)
  et ce qu'elle en a tiré ; ses boutons sur sa ligne, pas sous un détail (deux en vue, « Modifier l'objectif », le
  reste sous « ⋯ »). « Ajouter un objectif » est une colonne à côté de la liste, sur un grand écran.
- Décisions : une entrée par décision, comme une décision d'architecture — la question tranchée et son statut, ce
  qui est choisi, pourquoi (cité), le contexte et les options repliés, qui l'a posée et quand, ce qu'elle remplace ;
  ses boutons sur sa ligne (la retirer ou la remettre en vigueur, « Remplacer cette décision »). « Consigner une
  décision » est une colonne à côté, comme « Ajouter un objectif ».
- Ses onglets disent combien ils en comptent (objectifs, exécutions, décisions) ; les plus rares (Accès, Carnet) sont
  rangés sous « Plus ».
- Accès : qui peut le voir, le piloter, se servir de ses apps, et quand — un tableau de lignes lues de haut en bas,
  comme les règles d'un pare-feu, puis la ligne par défaut, obligatoire. Les outils qu'une ligne peut cocher sont ceux
  des apps du projet, lus dans la Forge (une app vit dans un projet, ADR 0104) ; chaque bouton envoie tout le tableau
  (``projects.acces``).
"""

from __future__ import annotations

from typing import Any

from markupsafe import Markup

from mika.app.handmade.access import canal_choices, canal_instances, people_with_accounts, who_choices
from mika.app.handmade.project_git import git_page
from mika.app.handmade.tabs import Got, Line, blank, lines, pairs, text
from mika.contracts import projects as c
from mika.faculties.projects.access import STEER_WORDS, who_named
from mika.faculties.projects.actions import pending_of
from mika.faculties.projects.faculty import access_of, in_force, project_at
from mika.inspector import render
from mika.inspector.pages.subjects import fiche_url
from mika.inspector.ui import PREFIX, UI, Overview, env
from mika.kernel.inspect import Pager
from mika.plugins.forge import app_tool_names
from mika.vocab.access import MOMENTS, PERSON, when_words

KIND = "project"
#: ce qu'une ligne fait, dans un sélecteur du tableau
POLICY_CHOICES = (("seule", "Seule"), ("carte", "Demande à la personne"), ("toi", "Ton accord"), ("non", "Non"))
MOMENT_CHOICES = tuple((k, label[:1].upper() + label[1:]) for k, label in MOMENTS)


def _form(forms: Any, action: str) -> Any:
    """Le formulaire que la console a préparé pour une action de l'onglet (son jeton, son retour)."""
    return next((v for k, v in dict(forms or {}).items() if k.split("|", 1)[0] == action), None)


#: les tuiles de la vue d'ensemble : (titre du bloc de la faculté, l'onglet où il mène)
TILE_TABS = {"objectifs": "objectifs", "executions": "executions", "decisions": "decisions",
             "cadre": "comportement", "prochaine": "comportement", "depot": "git"}


def _tab(key: str, tab: str) -> str:
    return fiche_url(KIND, key, tab)


def _banner(got: Got, key: str, pending: list[Any], notes: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Le seul bandeau de la page : ce qui attend ton accord, sinon ce qui l'arrête (sa pause, un objectif qui manque)."""
    if pending:
        n = len(pending)
        return {"tone": "warn", "text": (f"{n} demande{'s' if n > 1 else ''} attend{'ent' if n > 1 else ''} ton "
                                         "accord : ce qu'elle veut faire sortir de la machine, rien ne part sans toi."),
                "button": "Les décider", "href": f"{PREFIX}/approbations/en_attente?demande={pending[0].proposal}"}
    alarm = next((n for n in notes if n.get("tone") in ("warn", "danger")), None)
    if alarm is None:
        return None
    paused = alarm["text"].startswith("En pause")
    return {"tone": alarm["tone"], "text": alarm["text"], "button": "Voir les exécutions" if paused else "",
            "href": _tab(key, "executions") if paused else ""}


def _plan(got: Got) -> dict[str, Any] | None:
    """Son plan (une section de la faculté) : où il en est, la demande et le plan en mots, sa réponse en boutons."""
    section = next((b for b in got.items if b.get("t") == "section" and b.get("title") == "Le plan"), None)
    if section is None:
        return None
    items = section.get("items", [])
    facts = pairs(next((x for x in items if x.get("t") == "fields"), None))
    return {"state": facts.get("son plan"), "by": facts.get("demandé par"), "version": facts.get("version"),
            "texts": [x for x in items if x.get("t") == "prose"],
            "bar": next((x for x in items if x.get("t") == "toolbar"), None)}


def _objectives(p: Any) -> dict[str, str]:
    """L'avancement en deux mots (la maquette : « 7/7 » en grand, « ponctuels faits · 2 constants » à côté)."""
    once = [o for o in p.objectives if o.kind == c.ONCE and o.status != c.DROPPED]
    done = sum(1 for o in once if o.status == c.DONE)
    constants = sum(1 for o in p.objectives if o.kind == c.CONSTANT and o.status == c.OPEN)
    blocked = sum(1 for o in p.objectives if o.status == c.BLOCKED)
    sub = [f"ponctuel{'s' if len(once) > 1 else ''} fait{'s' if len(once) > 1 else ''}"] if once else []
    sub += [f"{constants} constant{'s' if constants > 1 else ''}"] if constants else []
    sub += [f"{blocked} bloqué{'s' if blocked > 1 else ''}"] if blocked else []
    return {"value": f"{done}/{len(once)}" if once else str(constants), "sub": " · ".join(sub) if once else
            ("constant" if constants == 1 else "constants") if constants else "aucun", "short":
            f"{done}/{len(once)} faits" if once else ""}


def overview(got: Got, key: str) -> Markup | None:
    """Projet › Vue d'ensemble : un bandeau, une bande de chiffres, des tuiles qui mènent à leurs onglets."""
    band = got.stats("Où il en est")
    if band is None:
        return None
    frame = got.ui.kernel.mind.frame()
    p = project_at(frame.state("projects"), key)
    pending = pending_of(frame, p.id) if p is not None else []
    notes = [b for b in got.items if b.get("t") == "note"]  # ce que la faculté dit de son état (pas ceux des tuiles)
    banner = _banner(got, key, pending, notes)
    said = banner["text"] if banner else ""
    runs = got.timeline("Dernières exécutions")
    entries = (runs or {}).get("entries", [])
    progress = _objectives(p) if p is not None else None
    figures = []
    for item in band["items"]:
        figure = {**item, "bars": []}
        if item["label"] == "Exécutions":  # ses dernières exécutions en barres, la plus ancienne d'abord
            figure["bars"] = [e.get("tone") or "ok" for e in reversed(entries)]
        if item["label"] == "Objectifs" and progress is not None:
            figure.update(value={"t": "text", "text": progress["value"]}, sub=progress["sub"])
        figures.append(figure)
    objectives = got.table("Ses objectifs")
    decisions = got.table("Décisions en vigueur")
    frame_text = next((b for b in got.walk() if b.get("title") == "Le cadre"), None)
    failures = next((f for f in band["items"] if f["label"] == "Pannes d'affilée"), None)
    return got.draw(
        "handmade/projets/ensemble.html", banner=banner,
        notes=[n for n in notes if n["text"] != said], figures=figures, plan=_plan(got),
        objectives=[{"n": x.get("n°"), "text": x["objectif"], "kind": x.get("sorte"), "state": x.get("état"),
                     "last": x.get("dernier passage")} for x in lines(objectives)],
        objectives_more=bool(objectives and objectives.get("caption")),
        progress=(progress or {}).get("short", ""),
        runs=entries, failing=text((failures or {}).get("value")) if failures and failures.get("tone") else "",
        decisions=[{"n": x.text("n°"), "question": x["la question"], "choice": x.get("ce qui est choisi")}
                   for x in lines(decisions)],
        in_force=in_force(p) if p is not None else 0,
        cadre=frame_text, next_run=pairs(got.fields("Prochaine exécution")), depot=pairs(got.fields("Son dépôt")),
        links={name: _tab(key, tab) for name, tab in TILE_TABS.items()})


#: l'état d'un objectif → la classe de son entrée
OBJECTIVE_STATES = {"fait": "done", "bloqué": "blocked", "retiré": "dropped"}
#: au-delà (en caractères), un texte cité (un compte rendu, un pourquoi) tient en quatre lignes et « lire la suite » le
#: déplie : en deçà, il se lit en entier (replié plus court, il ne cacherait parfois rien, parfois presque tout, selon
#: la largeur)
LONG_TEXT = 600


def _buttons(line: Line) -> dict[str, Any]:
    """Les boutons d'une entrée, sur sa ligne, rangés comme ceux de la barre de titre : deux en vue, le reste sous
    « ⋯ », et son panneau à part (« Modifier l'objectif », « Remplacer cette décision »)."""
    bar = next((d for d in line.detail if d.get("t") == "toolbar"), None)
    buttons = [x for x in (bar or {}).get("items", []) if x.get("t") == "action"]
    return {"seen": buttons[:2], "more": buttons[2:],
            "edit": next((d for d in line.detail if d.get("t") == "disclosure"), None)}


def _objective(line: Line) -> dict[str, Any]:
    """Un objectif : ce qu'il vise, sa sorte et son état, ses faits en une ligne, son dernier compte rendu et ce
    qu'elle en a tiré ; ses boutons sur sa ligne (``_buttons``)."""
    state, report = line.get("état"), line.get("dernier compte rendu")
    rhythm, runs, by = line.text("rythme"), line.text("exécutions"), line.text("posé par")
    facts = [f for f in rhythm.split(" · ") if f]  # « il y a 2 h · revient tous les 2 jours » : deux faits
    if runs not in ("", "0") and "exécution" not in rhythm:  # le rythme d'un ponctuel les compte déjà
        facts.append(f"{runs} exécution{'s' if runs != '1' else ''}")
    if by and not blank(line.get("posé par")):
        facts.append(f"posé par {by}")
    return {"n": line.text("n°"), "text": line.text("objectif"), "kind": line.get("sorte"), "state": state,
            "cls": OBJECTIVE_STATES.get(text(state), ""), "facts": facts,
            "report": "" if blank(report) else text(report), "long": len(text(report)) > LONG_TEXT,
            "result": next((d.get("text") or "" for d in line.detail if d.get("t") == "prose"), ""),
            **_buttons(line)}


def objectives(got: Got) -> Markup | None:
    """Projet › Objectifs : ses chiffres, une entrée par objectif, et « Ajouter un objectif » à côté."""
    t = got.table("Ses objectifs")
    if t is None:
        return None
    return got.draw("handmade/projets/fiche_objectifs.html", t=t, band=got.stats(), notes=got.notes(),
                    items=[_objective(x) for x in lines(t)], add=got.first("section", "Ajouter un objectif"))


def _said(c: dict[str, Any] | None) -> str:
    return "" if blank(c) else text(c)


def _decision(line: Line) -> dict[str, Any]:
    """Une décision : la question tranchée, son statut, ce qui est choisi, pourquoi, le contexte et les options ; qui
    l'a posée et quand, ce qu'elle remplace, pendant quel objectif ; ses boutons sur sa ligne (``_buttons``)."""
    status = line.get("statut")
    told = pairs(next((d for d in line.rest if d.get("t") == "fields"), None))
    why, replaces, during = (_said(told.get(k)) for k in ("pourquoi", "remplace", "pendant l'objectif"))
    facts = [f"remplace {replaces}" if replaces else "", f"pendant l'objectif {during}" if during else ""]
    return {"n": line.text("n°"), "question": line.text("la question"), "choice": _said(line.get("ce qui est choisi")),
            "status": status, "live": text(status) == "en vigueur", "by": line.text("posée par"),
            "when": line.get("quand"), "why": why, "why_long": len(why) > LONG_TEXT,
            "context": _said(told.get("le contexte")), "options": _said(told.get("les options envisagées")),
            "facts": [f for f in facts if f], **_buttons(line)}


def decisions(got: Got) -> Markup | None:
    """Projet › Décisions : une entrée par décision, et « Consigner une décision » à côté."""
    t = got.table("Ses décisions")
    if t is None:
        return None
    return got.draw("handmade/projets/fiche_decisions.html", t=t, notes=got.notes(),
                    items=[_decision(x) for x in lines(t)], add=got.first("section", "Consigner une décision"))


class ProjectFiche(Overview):
    """La fiche d'un projet : sa vue d'ensemble, ses objectifs, ses décisions et « Accès » dessinés ici, son dépôt
    git dans ``project_git`` ; ses autres onglets restent ceux de la faculté ; Accès et Carnet sous « Plus »."""

    slug = ""
    title = "Vue d'ensemble"
    styles = ("handmade/tools.css", "handmade/projets.css", "handmade/projet-git.css")
    tabs = ("apercu", "objectifs", "decisions", "git", "acces")
    folded = ("acces", "carnet")
    folded_title = "Plus"

    def render(self, ui: UI, key: str) -> Markup | None:
        return None

    def counts(self, ui: UI, key: str) -> dict[str, int]:
        p = project_at(ui.kernel.mind.frame().state("projects"), key)
        if p is None:
            return {}
        return {"objectifs": sum(1 for o in p.objectives if o.status != c.DROPPED), "executions": p.runs,
                "decisions": in_force(p)}

    def render_tab(self, ui: UI, key: str, tab: str, blocks: Any, query: Any, forms: Any = None) -> Any:
        if tab == "apercu":
            return overview(Got(ui, list(blocks), query, forms or {}), key)
        if tab == "objectifs":
            return objectives(Got(ui, list(blocks), query, forms or {}))
        if tab == "decisions":
            return decisions(Got(ui, list(blocks), query, forms or {}))
        if tab == "git":
            return git_page(Got(ui, list(blocks), query, forms or {}), key)
        if tab != "acces":
            return None
        frame = ui.kernel.mind.frame()
        p = project_at(frame.state("projects"), key)
        if p is None:
            return None
        lines, default = access_of(p)
        people, instances = people_with_accounts(ui), canal_instances(ui)
        # les outils de ses apps (``<app>_<outil>``), ce qu'ils font ; et ceux qu'une ligne nomme encore sans qu'une
        # app les propose (une app effacée, renommée) : on les voit, on peut les décocher
        tools = app_tool_names(frame, ui.kernel.ports, p.id)
        known = list(dict.fromkeys([*(t for t, _ in tools), *(t for a in lines for t in a.tools)]))
        natures = dict(tools)
        rows = []
        for n, a in enumerate(lines, start=1):
            rows.append({
                "n": n, "who": who_choices(a.who, people, lambda person: who_named(frame, (PERSON + person,)),
                                           ui.her_name(), a.canal),
                "canal": canal_choices(a.canal, instances),
                "always": not a.when,
                "when_said": "Toujours" if not a.when else (when_words(a.when).capitalize() if len(a.when) == 1
                                                             else f"{len(a.when)} moments"),
                "moments": [{"key": k, "label": label, "on": k in a.when} for k, label in MOMENT_CHOICES],
                "see": a.see, "steer": a.steer, "files": a.files, "read": a.read, "act": a.act, "all": not a.tools,
                "said": "Tous" if not a.tools else f"{len(a.tools)} outil{'s' if len(a.tools) > 1 else ''}",
                "tools": [{"name": t, "nature": natures.get(t, ""), "on": t in a.tools} for t in known],
                "first": n == 1, "last": n == len(lines)})
        return Markup(env.get_template("handmade/projets/acces.html").render(
            rows=rows, default=default, steers=c.STEERS, policies=POLICY_CHOICES, steer_words=STEER_WORDS,
            form=_form(forms, "projects.acces"), never_set=p.access is None, has_apps=bool(tools),
            pager=render._pager(Pager(size=len(rows) + 1, total=len(rows) + 1), {}),
            behaviour_tab=fiche_url(KIND, key, "comportement")))
