"""La fiche d'un projet, rangée par ce qu'on y fait (ADR 0121, 0133, 0176, 0177, 0281) : « Où il en est » (avec
« Missions et objectifs », l'onglet réuni), Liens, Exécutions, Cadre (avec « Accès », l'onglet réuni), Décisions
techniques, Fichiers et Carnet dessinés ici ; Tickets et Suivi bloc par bloc ; Dépôt dans ``project_git``.

- Où il en est suit la vue d'un objet de la maquette (ADR 0176) : un seul bandeau (sa pause, ou ce qui le retient),
  puis deux sous-onglets. « En bref » : ce qui t'attend en tête (ADR 0281 : la table que sa vue tire de
  ``faculties/projects/todo.py`` — chaque attente, depuis quand, à qui la main, le lien de son geste), une bande de
  chiffres (ses dernières exécutions en barres), ses missions (ses objectifs constants : leur cadence, ce qui les
  déclenche, leur dernier passage, ce qui les a éveillées) et ses objectifs en cours (leurs jalons en jauge, leur
  branche et leur pull request, leur relecture), une ligne chacun, son plan avec sa réponse quand il en a un (en
  tête s'il attend), puis des tuiles qui mènent à leurs onglets — ce qui vient ensuite, ses dernières exécutions, ses
  décisions en vigueur, son cadre, son dépôt. Les données sont celles de la vue « Où il en est » de la faculté
  (``Got``) : ses blocs servent la console en MCP et le repli.
- Missions et objectifs (le second sous-onglet : l'onglet ``objectifs``, réuni par ``ProjectFiche.joined`` — son
  ancienne adresse y mène) : ses chiffres, puis ses missions et ses objectifs ponctuels, chacun sous son titre, une
  entrée par objectif — son numéro, ce qu'il vise en clair, sa sorte et son état, son rythme, qui l'a posé, son
  dernier compte rendu (long, il tient en quatre lignes que « lire la suite » déplie) et ce qu'elle en a tiré ; ses
  boutons sur sa ligne, pas sous un détail (deux en vue, « Modifier l'objectif », le reste sous « ⋯ ») ; ses jalons
  et ce que tu y fais. Son filtre (ouverts et bloqués, faits, retirés, tous) est un bouton à choix dans l'en-tête de
  la liste. « Ajouter un objectif » est une colonne à côté de la liste, sur un grand écran.
- Exécutions : jour par jour, comme Projets › Exécutions et sur les mêmes pièces (``run`` de ``tabs/projects.py``,
  ``by_day``, ``handmade/projets/_runs.html``) — ses chiffres en tuiles, puis chaque exécution : l'objectif visé, son
  issue, le verdict et sa preuve, le compte rendu cité, le commit, la durée, et les onglets de son épisode (prompt,
  outils, appels, décision) ; sans le projet, c'est lui. La légende de la faculté (ce que montre chaque onglet de
  l'épisode) passe dans l'en-tête de la liste : un onglet dessiné ne reçoit plus la description de l'onglet. Sans
  exécution, la page le dit une fois, sans chiffres ni pagination ; la pagination (le curseur ``avant``) reste celle
  de la console.
- Décisions techniques : une entrée par décision, comme une décision d'architecture — la question tranchée et son
  statut, ce qui est choisi, pourquoi (cité), le contexte et les options repliés, qui l'a posée et quand, ce qu'elle
  remplace ; ses boutons sur sa ligne (la retirer ou la remettre en vigueur, « Remplacer cette décision »).
  « Consigner une décision » est une colonne à côté, comme « Ajouter un objectif ». Son titre les dit techniques :
  « Décisions », sur la fiche d'un but, ce sont les pesées de l'arbitre, comme la colonne « décision » de ses
  Exécutions ; la clé de l'onglet reste ``decisions``.
- Fichiers : bloc par bloc (``blocks.page``), comme les autres onglets d'un moyen de communication et ceux d'un but,
  son arborescence en table d'exploitation (des colonnes) : la navigation « Dossier », le fichier ouvert, la table du
  dossier, et « Déposer un fichier » avec le formulaire que la console a préparé.
- Cadre : le gabarit du paramétrage (ADR 0176), en sous-onglets. « Ses réglages » : le formulaire « Modifier le
  projet » que la console a préparé, par groupes (Le projet, Son mode, Son rythme, Sa liberté), une ligne par réglage,
  « Enregistrer » collé en bas, sans cadre dans la carte ; les cartes « Son mode », « Son rythme » et « Sa liberté »
  de sa vue ne se redisent pas : ce que veut dire un mode est l'aide de son réglage (``MODE_HELP``), ses plafonds
  (par défaut, espacement, par heure) celle de « Exécutions par jour au plus », sa prochaine exécution une ligne
  au-dessus ; un projet archivé n'a pas de formulaire : ces cartes s'y lisent, en lecture. « Outils et services » :
  la table des lots, « Choisir ses outils » (``projects.outils``) à côté. « Accès » : ses lignes d'accès (l'onglet
  ``acces``, réuni). « Tickets et issues » : qui valide le plan d'un ticket, la borne d'un petit ticket, la
  publication en issues, en faits, et le formulaire qui les règle (``projects.tickets_regler``).
- Liens (ADR 0257, 0271) : « Ce qu'il lit » — chaque projet lu, ce que le lien donne maintenant, ce que la vue de son
  atelier montre —, « Choisir ce qu'il lit » (``projects.liens``) à côté, ce qu'il leur a demandé, ce qu'on lui a
  demandé, et « Qui le lit ».
- Ses onglets disent combien ils en comptent (tickets, suivi, liens, exécutions) ; les plus rares (Décisions
  techniques, Fichiers, Carnet) sont rangés sous « Plus ».
- Accès : qui peut le voir, le piloter, se servir de ses apps, et quand — un tableau de lignes lues de haut en bas,
  comme les règles d'un pare-feu, puis la ligne par défaut, obligatoire. Les outils qu'une ligne peut cocher sont ceux
  des apps du projet, lus dans la Forge (une app vit dans un projet, ADR 0104), et ce qu'elle en fait se choisit dans
  les mots des familles (``vocab.access.POLICIES``) ; chaque bouton envoie tout le tableau (``projects.acces``).
- Carnet : en sous-onglets — Consignes, Ses notes, Ce qu'on en a fait, Ce qui sort —, chacun avec sa pagination (le
  curseur de sa liste : ``avant``, ``avant_notes``, ``avant_ops``, ``avant_effets`` ; celui qu'on feuillette s'ouvre).
  Une demande qui attend ton accord le dit, garde sa commande exacte et mène à la file « À valider » (le lien que
  porte sa ligne, ``decide_where``), sans formulaire de décision.

« Où il en est » lit tout dans sa vue : ce qui t'attend, ses missions et ses objectifs en une ligne, l'avancement de
ses objectifs tel que la faculté l'écrit (``objectives_progress``). Ce que ses onglets comptent, et le nombre de ses
décisions en vigueur (sa vue n'en montre que les dernières), vient de l'``inspect`` de la faculté (``tab_counts``). Ce
que la fiche lit encore par les fonctions de la faculté, à côté de sa vue (ADR 0218, déclaré dans
``tests/protocol/test_drawn_fiches.py``) : le projet lui-même (``project_at``) ; pour « Accès », ses lignes
(``access_of``) et le nom de qui elles nomment (``who_named``), qu'un formulaire édite et que sa vue ne porte pas.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from markupsafe import Markup

from mika.app.handmade import blocks as drawn_blocks
from mika.app.handmade.access import (
    POLICY_CHOICES,
    canal_choices,
    canal_instances,
    people_with_accounts,
    who_choices,
)
from mika.app.handmade.subjects.project_git import git_page
from mika.app.handmade.tabs import Got, Line, anchored, blank, lines, paged, pairs, raw_lines, subpanes, text
from mika.app.handmade.tabs.decisions import by_day
from mika.app.handmade.tabs.projects import run
from mika.contracts import projects as c
from mika.faculties.projects.access import STEER_WORDS, who_named
from mika.faculties.projects.faculty import access_of, project_at
from mika.faculties.projects.inspect import (
    ASKS_TITLE,
    DECIDE_LABEL,
    EFFECTS_CURSOR,
    LINKS_TITLE,
    MISSIONS_TITLE,
    NEXT_RUN_LABEL,
    NOTES_CURSOR,
    OBJECTIVE_PARAM,
    ONCE_TITLE,
    OPERATIONS_CURSOR,
    PULL_LINK_TITLE,
    PULL_TITLE,
    READERS_TITLE,
    READS_TITLE,
    RECEIVED_TITLE,
    TICKETS_SETTING_TITLE,
    tab_counts,
)
from mika.faculties.projects.inspect_milestones import ROUTINE_TITLE
from mika.faculties.projects.inspect_milestones import TITLE as MILESTONES_TITLE
from mika.faculties.projects.inspect_reviews import TITLE as REVIEW_TITLE
from mika.faculties.projects.inspect_todo import TITLE as TODO_TITLE
from mika.inspector import render
from mika.inspector.pages.subjects import subject_url
from mika.inspector.ui import UI, Overview, env
from mika.kernel.inspect import Pager
from mika.plugins.forge.access import app_tool_names
from mika.vocab.access import MOMENTS, PERSON, when_words

KIND = "project"
MOMENT_CHOICES = tuple((k, label[:1].upper() + label[1:]) for k, label in MOMENTS)
#: les titres de ses onglets réunis (``ProjectFiche.joined``) : la console passe leurs blocs dans une section à ce
#: titre — celui de leur vue dans la faculté
OVERVIEW_TITLE, OBJECTIVES_TITLE, BEHAVIOUR_TITLE, ACCESS_TITLE = "Où il en est", "Missions et objectifs", "Cadre", "Accès"


def _form(forms: Any, action: str) -> Any:
    """Le formulaire que la console a préparé pour une action de l'onglet (son jeton, son retour)."""
    return next((v for k, v in dict(forms or {}).items() if k.split("|", 1)[0] == action), None)


#: les tuiles de « Où il en est » : (titre du bloc de la faculté, l'onglet où il mène)
TILE_TABS = {"executions": "executions", "decisions": "decisions", "cadre": "comportement",
             "prochaine": "comportement", "depot": "git"}
#: ses deux sous-onglets : l'essentiel, puis ses missions et ses objectifs — l'onglet réuni (``ProjectFiche.joined``),
#: dont l'ancre est le nom (son ancienne adresse y mène)
BRIEF_PANE, OBJECTIVES_PANE = "bref", "objectifs"


def _tab(key: str, tab: str) -> str:
    return subject_url(KIND, key, tab)


def _part(got: Got, title: str) -> Got | None:
    """Un onglet réuni sous un autre (``Overview.joined``) : les blocs de sa section, lus comme ceux d'un onglet —
    la console les passe dans une ``Section`` à son titre. Sans section à ce titre (l'onglet seul), rien."""
    section = next((b for b in got.items if b.get("t") == "section" and b.get("title") == title), None)
    if section is None:
        return None
    part = copy.copy(got)
    part.items = list(section.get("items", []))
    return part


def _waiting(got: Got) -> dict[str, Any] | None:
    """« Ce qui t'attend » (ADR 0281), tel que sa vue le dit : une ligne par attente — sa sorte, de quoi il s'agit,
    depuis quand, qui elle attend, et le lien de son geste."""
    t = got.table(TODO_TITLE)
    if t is None:
        return None
    # combien attendent : une ligne peut en résumer plusieurs (les éléments d'une liste) — le titre de la table le
    # dit alors ; sinon c'est le nombre de ses lignes, que la console a ôté du titre
    counted = re.search(r"\((\d+)\)$", str(t.get("title") or ""))
    return {"empty": t.get("empty", ""), "caption": t.get("caption", ""),
            "count": int(counted.group(1)) if counted else int(t.get("count") or 0),
            "items": [{"kind": x.get("quoi"), "text": x.text("de quoi il s'agit"), "since": x.get("depuis"),
                       "who": x.get("attend"), "go": x.get("le geste"), "project": x.get("projet")}
                      for x in lines(t)]}


def _alarm(key: str, notes: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Le seul bandeau de la page : ce qui l'arrête (sa pause, un objectif qui manque). Ce qui attend ton accord n'y
    est plus : « Ce qui t'attend » le dit, en tête, avec le reste (ADR 0281)."""
    alarm = next((n for n in notes if n.get("tone") in ("warn", "danger")), None)
    if alarm is None:
        return None
    paused = alarm["text"].startswith("En pause")
    return {"tone": alarm["tone"], "text": alarm["text"], "button": "Voir les exécutions" if paused else "",
            "href": _tab(key, "executions") if paused else ""}


def _plan(got: Got) -> dict[str, Any] | None:
    """Son plan (une section de la faculté) : où il en est, la demande et le plan en mots, sa réponse en boutons."""
    section = got.first("section", "Le plan")
    if section is None:
        return None
    items = section.get("items", [])
    facts = pairs(next((x for x in items if x.get("t") == "fields"), None))
    return {"state": facts.get("son plan"), "by": facts.get("demandé par"), "version": facts.get("version"),
            "waits": (facts.get("son plan") or {}).get("tone") == "warn",  # il attend sa réponse : il passe en tête
            "texts": [x for x in items if x.get("t") == "prose"],
            "bar": next((x for x in items if x.get("t") == "toolbar"), None)}


def _said_cell(line: Line, label: str) -> str:
    c = line.get(label)
    return "" if blank(c) else text(c)


def _missions(got: Got) -> list[dict[str, Any]]:
    """Ses missions (ses objectifs constants), une ligne chacune : sa cadence, ce qui la déclenche, son dernier
    passage, ce qui l'a éveillée."""
    return [{"n": x.text("n°"), "text": x.text("mission"), "state": x.get("état"), "tone": x.tone,
             "facts": [(k, v) for k, v in (("revient", _said_cell(x, "revient")),
                                           ("déclenchée par", _said_cell(x, "déclenchée par")),
                                           ("dernier passage", _said_cell(x, "dernier passage"))) if v],
             "stirred": _said_cell(x, "ce qui l'a éveillée")} for x in lines(got.table(MISSIONS_TITLE))]


def _once(got: Got) -> list[dict[str, Any]]:
    """Ses objectifs ponctuels en cours, une ligne chacun : ses jalons, sa branche et sa pull request, sa relecture,
    son dernier passage."""
    out = []
    for x in lines(got.table(ONCE_TITLE)):
        marks = _said_cell(x, "jalons")
        done, _, rest = marks.partition(" · ")
        reached, _, total = done.partition("/")
        out.append({"n": x.text("n°"), "text": x.text("objectif"), "state": x.get("état"), "tone": x.tone,
                    "marks": done, "waits": rest,
                    "w": round(100 * int(reached) / int(total)) if reached.isdigit() and total.isdigit() and int(total)
                    else None,
                    "facts": [(k, v) for k, v in (("branche", _said_cell(x, "branche et pull request")),
                                                  ("relecture", _said_cell(x, "relecture")),
                                                  ("dernier passage", _said_cell(x, "dernier passage"))) if v]})
    return out


def overview(got: Got, key: str) -> Markup | None:
    """Projet › Où il en est (ADR 0281) : son bandeau, puis deux sous-onglets — « En bref » : ce qui t'attend en
    tête, sa bande de chiffres, ses missions et ses objectifs en cours en une ligne chacun, ce qui vient ensuite, son
    plan, des tuiles qui mènent à leurs onglets ; « Missions et objectifs » : l'onglet réuni, chaque objectif avec
    ses boutons. Seul (l'onglet ``apercu`` sans celui qu'il réunit), il n'a que « En bref »."""
    whole = got
    got = _part(whole, OVERVIEW_TITLE) or whole
    band = got.stats("Où il en est")
    if band is None:
        return None
    p = project_at(got.ui.kernel.mind.frame().state("projects"), key)
    notes = [b for b in got.items if b.get("t") == "note"]  # ce que la faculté dit de son état (pas ceux des tuiles)
    banner = _alarm(key, notes)
    said = banner["text"] if banner else ""
    runs = got.timeline("Dernières exécutions")
    entries = (runs or {}).get("entries", [])
    figures = []
    for item in band["items"]:
        figure = {**item, "bars": []}
        if item["label"] == "Exécutions":  # ses dernières exécutions en barres, la plus ancienne d'abord
            figure["bars"] = [e.get("tone") or "ok" for e in reversed(entries)]
        if item["label"] == "Objectifs":  # ses objectifs sont le second sous-onglet de cette page
            figure["href"] = f"#{OBJECTIVES_PANE}"
        figures.append(figure)
    decisions = got.table("Décisions en vigueur")
    frame_text = next((b for b in got.walk() if b.get("title") == "Le cadre"), None)
    failures = next((f for f in band["items"] if f["label"] == "Pannes d'affilée"), None)
    joined = _part(whole, OBJECTIVES_TITLE)
    detail = objectives(joined) if joined is not None else None
    waiting = _waiting(got)
    counts = tab_counts(p) if p is not None else {}
    return whole.draw(
        "handmade/projets/ensemble.html", banner=banner,
        notes=[n for n in notes if n["text"] != said], figures=figures, plan=_plan(got), waiting=waiting,
        missions=_missions(got), once=_once(got), objectives_pane=detail,
        panes=[{"id": BRIEF_PANE, "label": "En bref", "count": waiting["count"] if waiting else 0,
                "warn": bool(waiting and waiting["items"])},
               {"id": OBJECTIVES_PANE, "label": OBJECTIVES_TITLE, "count": counts.get("objectifs", 0), "warn": False}]
        if detail is not None else [],
        runs=entries, failing=text((failures or {}).get("value")) if failures and failures.get("tone") else "",
        decisions=[{"n": x.text("n°"), "question": x["la question"], "choice": x.get("ce qui est choisi")}
                   for x in lines(decisions)],
        in_force=counts.get("decisions", 0),
        cadre=frame_text, next_run=pairs(got.fields("Prochaine exécution")), depot=pairs(got.fields("Son dépôt")),
        links={**{name: _tab(key, tab) for name, tab in TILE_TABS.items()},
               "objectifs": f"#{OBJECTIVES_PANE}" if detail is not None else _tab(key, "objectifs")})


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


def _milestones(line: Line) -> list[dict[str, Any]]:
    """Les jalons d'un objectif (ADR 0273), tels que son détail les porte : leur numéro et leur état, leur texte,
    comment ils se vérifient, et ce qui en est gardé — comment elle l'a rempli, sa preuve, son commit."""
    table = next((d for d in line.detail if d.get("t") == "table" and d.get("title") == MILESTONES_TITLE), None)
    out = []
    for x in lines(table):
        said, commit = x.get("comment, et sa preuve"), x.get("commit")
        out.append({"label": f"Jalon n° {x.text('n°')} · {x.text('état')}", "text": x.text("jalon"),
                    "check": x.text("vérifié par"), "said": "" if blank(said) else text(said),
                    "commit": "" if blank(commit) else text(commit)})
    return out


def _objective(line: Line) -> dict[str, Any]:
    """Un objectif : ce qu'il vise, sa sorte et son état, ses faits en une ligne, son dernier compte rendu et ce
    qu'elle en a tiré ; ses boutons sur sa ligne (``_buttons``) ; ses jalons et ce que tu y fais, ou la liste de
    passage d'un constant (ADR 0273)."""
    prose = {d.get("title") or "": d.get("text") or "" for d in reversed(line.detail) if d.get("t") == "prose"}
    routine = prose.pop(ROUTINE_TITLE, "")
    # sa branche et sa pull request, et sa page chez l'hôte (ADR 0274)
    pull = {"text": prose.pop(PULL_TITLE, ""), "href": prose.pop(PULL_LINK_TITLE, "")}
    review = prose.pop(REVIEW_TITLE, "")  # son dernier verdict de relecture et ses constats (ADR 0276)
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
            "result": next(iter(prose.values()), ""), "routine": routine, "milestones": _milestones(line),
            "pull": pull if pull["text"] else None, "review": review,
            # ses panneaux de plus, après « Modifier l'objectif » : trancher un point d'arrêt, ajouter un jalon
            "panels": [d for d in line.detail if d.get("t") == "disclosure"][1:], **_buttons(line)}


#: ses objectifs par sorte (ADR 0281) : (la sorte telle que sa ligne la dit, le titre du groupe, ce qu'il en dit)
OBJECTIVE_GROUPS = (("constant", "Ses missions", "Elles reviennent : selon leur cadence, ou quand quelque chose les "
                                                 "déclenche."),
                    ("ponctuel", "Ses objectifs", "Chacun se fait une fois, jalon après jalon, avec sa preuve."))


def objectives(got: Got) -> Markup | None:
    """Projet › Missions et objectifs : ses chiffres, ses missions (ses constants) puis ses objectifs ponctuels, une
    entrée chacun, et « Ajouter un objectif » à côté ; le filtre de sa vue (ouverts et bloqués, faits, retirés, tous)
    en bouton à choix, appliqué d'un clic — réuni sous « Où il en est », la console ne le pose plus pour lui."""
    t = got.table("Ses objectifs")
    if t is None:
        return None
    items = [_objective(x) for x in lines(t)]
    groups = [{"title": title, "help": said, "items": [o for o in items if text(o["kind"]) == kind]}
              for kind, title, said in OBJECTIVE_GROUPS]
    chosen = got.query.get(OBJECTIVE_PARAM.name) or OBJECTIVE_PARAM.default
    seg = [{"text": label[:1].upper() + label[1:], "on": value == chosen,
            "href": f"?onglet=objectifs&{OBJECTIVE_PARAM.name}={value}"} for value, label in OBJECTIVE_PARAM.choices]
    return got.draw("handmade/projets/fiche_objectifs.html", t=t, band=got.stats(), notes=got.notes(),
                    items=items, groups=[g for g in groups if g["items"]], seg=seg,
                    add=got.first("section", "Ajouter un objectif"))


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
    """Projet › Décisions techniques : une entrée par décision, et « Consigner une décision » à côté."""
    t = got.table("Ses décisions")
    if t is None:
        return None
    return got.draw("handmade/projets/fiche_decisions.html", t=t, notes=got.notes(),
                    items=[_decision(x) for x in lines(t)], add=got.first("section", "Consigner une décision"))


def runs(got: Got) -> Markup | None:
    """Projet › Exécutions : ses chiffres en tuiles, puis ses exécutions jour par jour, comme Projets › Exécutions
    (``run``, ``by_day``) ; sans exécution, la page le dit une fois, sans chiffres."""
    t = got.table("Ses exécutions")
    if t is None:
        return None
    items = [run(got, x, r) for x, r in zip(lines(t), raw_lines(got, t), strict=False)]
    return got.draw("handmade/projets/fiche_executions.html", t=t, band=got.stats() if items else None,
                    notes=got.notes(), days=by_day(got, items))


#: ce que « Son rythme » dit des plafonds, repris dans l'aide de « Exécutions par jour au plus » : (son libellé
#: dans la vue, ses mots dans l'aide)
CAP_FACTS = (("exécutions par jour", "en vigueur"), ("espacement", "espacement"),
             ("par heure, tous projets", "par heure, tous projets"))
#: le réglage qui reçoit ces faits en aide
CAP_FIELD = "runs_per_day"
#: les blocs de faits de la vue que le formulaire remplace ; un projet archivé (sans formulaire) les montre en lecture
SETTINGS_FACTS = ("Son mode", "Son rythme", "Sa liberté")


def _groups(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Les champs d'un formulaire par groupe (« Le projet », « Son mode »…), dans l'ordre où ils viennent."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for f in fields:
        groups.setdefault(str(f.get("group") or ""), []).append(f)
    return [{"title": title, "fields": fs} for title, fs in groups.items()]


def _edited(form: dict[str, Any], rhythm: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Le formulaire « Modifier le projet » par groupes ; l'aide de son plafond d'exécutions dit ce qui vaut
    aujourd'hui (le plafond par défaut, l'espacement, le plafond horaire de tous les projets), lu dans sa vue."""
    cap = " ; ".join(f"{words} : {text(rhythm[label])}" for label, words in CAP_FACTS if label in rhythm)
    fields = [{**f, "help": f"{f.get('help') or ''} {cap[:1].upper()}{cap[1:]}.".strip()}
              if f.get("path") == CAP_FIELD and cap else f for f in form.get("fields", [])]
    return {**form, "groups": _groups(fields)}


#: les sous-onglets de « Cadre » : (ancre, libellé) — « Accès » garde le nom de son onglet réuni, où mène son
#: ancienne adresse
FRAME_PANES = (("cadre-reglages", "Ses réglages"), ("cadre-outils", "Outils et services"), ("acces", "Accès"),
               ("cadre-tickets", "Tickets et issues"))


def behaviour(got: Got, key: str) -> Markup | None:
    """Projet › Cadre (ADR 0281), dans le gabarit du paramétrage et en sous-onglets. « Ses réglages » : le formulaire
    « Modifier le projet » (préparé par la console) par groupes, une ligne par réglage et « Enregistrer » collé en
    bas ; ce que sa vue dit en cartes (son mode, son rythme, sa liberté) passe en aide de leur réglage, sa prochaine
    exécution en une ligne au-dessus ; sans formulaire (un projet archivé), ces faits en lecture. « Outils et
    services » : la table des lots, et « Choisir ses outils » à côté. « Accès » : ses lignes d'accès (l'onglet réuni,
    ``ProjectFiche.joined``). « Tickets et issues » : qui valide le plan d'un ticket, la borne d'un petit ticket, la
    publication en issues, en faits, et le formulaire qui les règle."""
    rhythm, tools = got.fields("Son rythme"), got.first("section", "Ses outils")
    if rhythm is None or tools is None:
        return None
    facts = pairs(rhythm)
    form = _form(got.forms, "projects.modifier")
    tickets = got.first("section", TICKETS_SETTING_TITLE)
    rights = access(got.ui, key, got.forms) if _part(got, ACCESS_TITLE) is not None else None
    shown = {"cadre-reglages": True, "cadre-outils": True, "acces": rights is not None,
             "cadre-tickets": tickets is not None}
    return got.draw(
        "handmade/projets/fiche_comportement.html",
        notes=[n for n in got.every("note") if n not in list(got.walk((tickets or {}).get("items", [])))
               and not n.get("title")],
        next_run=facts.get(NEXT_RUN_LABEL),
        edit=_edited(form, facts) if form is not None else None,
        settings=[] if form is not None else [b for title in SETTINGS_FACTS if (b := got.fields(title))],
        tools=tools, lots=_one_page(got.table("Ce qu'elle a en main")), choose=_form(got.forms, "projects.outils"),
        access=rights, tickets=tickets,
        ticket_facts=next((x for x in (tickets or {}).get("items", []) if x.get("t") == "fields"), None),
        ticket_form=_form(got.forms, "projects.tickets_regler"),
        panes=[{"id": i, "label": label} for i, label in FRAME_PANES if shown[i]])


def links_page(got: Got) -> Markup | None:
    """Projet › Liens (ADR 0257, 0271, 0281) : ce qu'il lit — chaque projet lu, ce que le lien donne maintenant, ce
    que la vue de son atelier montre, comment une demande y naîtrait — et « Choisir ce qu'il lit » à côté ; ce qu'il
    leur a demandé ; ce qu'on lui a demandé ; qui le lit."""
    links = got.first("section", LINKS_TITLE)
    if links is None:
        return None
    return got.draw("handmade/projets/fiche_liens.html", notes=got.notes(), links=links,
                    reads=_one_page(got.table(READS_TITLE)), readers=_one_page(got.table(READERS_TITLE)),
                    link=_form(got.forms, "projects.liens"), asks=_one_page(got.table(ASKS_TITLE)),
                    received=_one_page(got.table(RECEIVED_TITLE)))


def _one_page(table: dict[str, Any] | None) -> dict[str, Any] | None:
    """Une liste qui tient sur une page ne dit ni « 1–4 sur 4 » ni « Page 1 sur 1 » : sa pagination reste dans la
    page (la console l'exige), masquée (``.hm-pager.single``)."""
    if table is None or paged(table):
        return table
    return {**table, "pager": None, "raw_pager": table.get("pager")}


#: les sous-onglets du Carnet : (ancre, libellé, titre du bloc de la vue, son curseur de pagination)
NOTEBOOK_PANES = (("carnet-consignes", "Consignes", "Consignes reçues", "avant"),
                  ("carnet-notes", "Ses notes", "Son carnet", NOTES_CURSOR),
                  ("carnet-faits", "Ce qu'on en a fait", "Ce qu'on en a fait", OPERATIONS_CURSOR),
                  ("carnet-sorties", "Ce qui sort", "Ce qui sort de la machine", EFFECTS_CURSOR))


def _request(line: Line) -> dict[str, Any]:
    """Ce qu'il a voulu faire sortir de la machine : quand, quoi, s'il fallait ton accord, où il en est ; la commande
    exacte et le lien vers la file quand il attend (la fiche ne décide pas sur place, ADR 0177), ce qu'il en est
    sinon."""
    told = [d for d in line.rest if d.get("t") == "code"]
    decide = next((p["value"] for d in line.rest if d.get("t") == "fields" for p in d["pairs"]
                   if p["label"] == DECIDE_LABEL and p["value"].get("t") == "link"), None)
    return {"when": line.get("quand"), "what": line.text("ce qu'il voulait faire sortir"),
            "approval": line.text("accord"), "state": line.get("état"), "waiting": line.tone == "warn",
            "decide": decide, "codes": told}


def notebook(got: Got) -> Markup | None:
    """Projet › Carnet, en sous-onglets — Consignes, Ses notes, Ce qu'on en a fait, Ce qui sort —, chacun avec sa
    pagination (le curseur de sa liste, ses liens qui reviennent à son ancre) ; celui qu'on feuillette s'ouvre. Une
    demande qui attend ton accord le dit et mène à la file « À valider », sans formulaire de décision."""
    lists = {pane: got.first("table" if pane == "carnet-sorties" else "timeline", title)
             for pane, _, title, _ in NOTEBOOK_PANES}
    if any(x is None for x in lists.values()):
        return None
    for pane, x in lists.items():
        anchored(x, pane)
    browsed = next((pane for pane, _, _, cursor in NOTEBOOK_PANES if got.query.get(cursor)), "")
    requests = [_request(x) for x in lines(lists["carnet-sorties"])]
    panes = [{"id": pane, "label": label, "warn": pane == "carnet-sorties" and any(r["waiting"] for r in requests)}
             for pane, label, _, _ in NOTEBOOK_PANES]
    order = [p["id"] for p in subpanes([{"id": p["id"]} for p in panes], browsed)]
    return got.draw("handmade/projets/fiche_carnet.html", notes=got.notes(), panes=panes, order=order, lists=lists,
                    requests=requests)


def access(ui: UI, key: str, forms: Any) -> Markup | None:
    """Ses lignes d'accès (ADR 0133) : un tableau de lignes lues de haut en bas — qui et par où, quand, le voir, le
    piloter, ses fichiers, ce qu'elle fait d'un outil de ses apps qui lit et d'un outil qui agit, à quels outils —,
    puis la ligne par défaut, obligatoire ; le formulaire est celui de ``projects.acces``. Les outils qu'une ligne
    peut cocher sont ceux des apps du projet, lus dans la Forge."""
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
            "see": a.see, "steer": a.steer, "files": a.files, "docs": a.docs, "read": a.read, "act": a.act,
            "all": not a.tools,
            "said": "Tous" if not a.tools else f"{len(a.tools)} outil{'s' if len(a.tools) > 1 else ''}",
            "tools": [{"name": t, "nature": natures.get(t, ""), "on": t in a.tools} for t in known],
            "first": n == 1, "last": n == len(lines)})
    return Markup(env.get_template("handmade/projets/acces.html").render(
        rows=rows, default=default, steers=c.STEERS, policies=POLICY_CHOICES, steer_words=STEER_WORDS,
        form=_form(forms, "projects.acces"), never_set=p.access is None, has_apps=bool(tools),
        pager=render._pager(Pager(size=len(rows) + 1, total=len(rows) + 1), {}),
        behaviour_tab=subject_url(KIND, key, "comportement") + "#cadre-outils"))


class ProjectFiche(Overview):
    """La fiche d'un projet, rangée par ce qu'on y fait (ADR 0281) : « Où il en est » (ce qui t'attend en tête, et
    « Missions et objectifs », l'onglet réuni), Tickets et Suivi (son registre, ADR 0268, bloc par bloc), Liens,
    Dépôt (``project_git``), Exécutions, Cadre (ses réglages, ses outils, et « Accès », l'onglet réuni, en
    sous-onglets) ; Décisions techniques, Fichiers, Documentation (ses pages et leur dernière modification, ADR 0289)
    et Carnet sous « Plus »."""

    slug = ""
    title = "Où il en est"
    styles = ("handmade/outils.css", "handmade/projets.css", "handmade/projet-git.css")
    tabs = ("apercu", "objectifs", "executions", "decisions", "tickets", "suivi", "liens", "fichiers",
            "documentation", "git", "comportement", "acces", "carnet")
    folded = ("decisions", "fichiers", "documentation", "carnet")
    folded_title = "Plus"
    #: ses objectifs se lisent sous « Où il en est », ses accès sous « Cadre » : leurs adresses y mènent
    joined = {"apercu": ("objectifs",), "comportement": ("acces",)}

    def render(self, ui: UI, key: str) -> Markup | None:
        return None

    def counts(self, ui: UI, key: str) -> dict[str, int]:
        s = ui.kernel.mind.frame().state("projects")
        p = project_at(s, key)
        return tab_counts(p, s) if p is not None else {}

    def render_tab(self, ui: UI, key: str, tab: str, blocks: Any, query: Any, forms: Any = None) -> Any:
        if tab == "apercu":
            return overview(Got(ui, list(blocks), query, forms or {}), key)
        if tab == "objectifs":
            return objectives(Got(ui, list(blocks), query, forms or {}))
        if tab == "executions":
            return runs(Got(ui, list(blocks), query, forms or {}))
        if tab == "decisions":
            return decisions(Got(ui, list(blocks), query, forms or {}))
        if tab == "documentation":  # ses pages et ses images, en colonnes : rien ne s'y édite (ADR 0289)
            return drawn_blocks.page(ui, blocks, query, tables="table", forms=forms, tab="project/documentation")
        if tab == "fichiers":  # une table d'exploitation : en colonnes, et « Déposer un fichier » préparé par la console
            return drawn_blocks.page(ui, blocks, query, tables="table", forms=forms, tab="project/fichiers")
        if tab in ("tickets", "suivi"):  # son registre (ADR 0268), en table d'exploitation, comme ses fichiers
            return drawn_blocks.page(ui, blocks, query, tables="table", forms=forms, tab=f"project/{tab}")
        if tab == "liens":
            return links_page(Got(ui, list(blocks), query, forms or {}))
        if tab == "git":
            return git_page(Got(ui, list(blocks), query, forms or {}), key)
        if tab == "comportement":
            return behaviour(Got(ui, list(blocks), query, forms or {}), key)
        if tab == "carnet":
            return notebook(Got(ui, list(blocks), query, forms or {}))
        if tab == "acces":  # seul (hors de « Cadre ») : ses lignes, telles quelles
            return access(ui, key, forms)
        return None
