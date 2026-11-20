"""La fiche d'un projet : sa vue d'ensemble, ses onglets Objectifs, Exécutions, Décisions techniques, Fichiers,
Comportement et outils, « Accès » et Carnet dessinés (ADR 0121, 0133, 0176, 0177) ; Dépôt git dans ``project_git``.

- La vue d'ensemble suit la vue d'un objet de la maquette (ADR 0176) : un seul bandeau (ce qui attend ton accord —
  « Les décider » ouvre la file des validations —, sinon sa pause ou ce qui le retient), une bande de chiffres (la
  dernière exécution en barres), puis des tuiles qui mènent à leurs onglets — objectifs, exécutions, décisions en
  vigueur, son cadre, sa prochaine exécution, son dépôt —, et son plan avec sa réponse quand il en a un. Les données
  sont celles de l'onglet « Vue d'ensemble » de la faculté (``Got``) : ses blocs servent la console en MCP et le repli.
- Objectifs : ses chiffres, puis une entrée par objectif — son numéro, ce qu'il vise en clair, sa sorte et son état,
  son rythme, qui l'a posé, son dernier compte rendu (long, il tient en quatre lignes que « lire la suite » déplie)
  et ce qu'elle en a tiré ; ses boutons sur sa ligne, pas sous un détail (deux en vue, « Modifier l'objectif », le
  reste sous « ⋯ »). « Ajouter un objectif » est une colonne à côté de la liste, sur un grand écran.
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
- Comportement et outils : le gabarit du paramétrage (ADR 0176). Le formulaire « Modifier le projet » que la console a
  préparé, par groupes (Le projet, Son mode, Son rythme, Sa liberté), une ligne par réglage, « Enregistrer » collé en
  bas, sans cadre dans la carte. Les cartes « Son mode », « Son rythme » et « Sa liberté » de sa vue ne se redisent
  pas : ce que veut dire un mode est l'aide de son réglage (``MODE_HELP``), ses plafonds (par défaut, espacement, par
  heure) celle de « Exécutions par jour au plus », sa prochaine exécution une ligne au-dessus. Un projet archivé n'a
  pas de formulaire : ces cartes s'y lisent, en lecture. Puis ses outils : la table des lots, « Choisir ses outils »
  (``projects.outils``) à côté. Puis ses liens de lecture (ADR 0257) : « Ce qu'il lit » — chaque projet lu et ce que le
  lien donne maintenant —, « Choisir ce qu'il lit » (``projects.liens``) à côté, et « Qui le lit ».
- Ses onglets disent combien ils en comptent (objectifs, exécutions, décisions) ; les plus rares (Accès, Carnet) sont
  rangés sous « Plus ».
- Accès : qui peut le voir, le piloter, se servir de ses apps, et quand — un tableau de lignes lues de haut en bas,
  comme les règles d'un pare-feu, puis la ligne par défaut, obligatoire. Les outils qu'une ligne peut cocher sont ceux
  des apps du projet, lus dans la Forge (une app vit dans un projet, ADR 0104), et ce qu'elle en fait se choisit dans
  les mots des familles (``vocab.access.POLICIES``) ; chaque bouton envoie tout le tableau (``projects.acces``).
- Carnet : en sous-onglets — Consignes, Ses notes, Ce qu'on en a fait, Ce qui sort —, chacun avec sa pagination (le
  curseur de sa liste : ``avant``, ``avant_notes``, ``avant_ops``, ``avant_effets`` ; celui qu'on feuillette s'ouvre).
  Une demande qui attend ton accord le dit, garde sa commande exacte et mène à la file « À valider » (le lien que
  porte sa ligne, ``decide_where``), sans formulaire de décision.

La vue d'ensemble lit tout dans sa vue : le bandeau compte les liens vers la file que porte sa section « À décider »
(un par demande) et mène au premier ; la bande dit l'avancement de ses objectifs tel que la faculté l'écrit
(``objectives_progress``). Ce que ses onglets comptent, et le nombre de ses décisions en vigueur (sa vue n'en montre que
les dernières), vient de l'``inspect`` de la faculté (``tab_counts``). Ce que la fiche lit encore par les fonctions de la
faculté, à côté de sa vue (ADR 0218, déclaré dans ``tests/protocol/test_drawn_fiches.py``) : le projet lui-même
(``project_at``) ; pour « Accès », ses lignes (``access_of``) et le nom de qui elles nomment (``who_named``), qu'un
formulaire édite et que sa vue ne porte pas.
"""

from __future__ import annotations

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
    DECIDE_LABEL,
    EFFECTS_CURSOR,
    LINKS_TITLE,
    NEXT_RUN_LABEL,
    NOTES_CURSOR,
    OPERATIONS_CURSOR,
    READERS_TITLE,
    READS_TITLE,
    tab_counts,
)
from mika.inspector import render
from mika.inspector.pages.subjects import subject_url
from mika.inspector.ui import UI, Overview, env
from mika.kernel.inspect import Pager, agree, plural
from mika.plugins.forge.access import app_tool_names
from mika.vocab.access import MOMENTS, PERSON, when_words

KIND = "project"
MOMENT_CHOICES = tuple((k, label[:1].upper() + label[1:]) for k, label in MOMENTS)


def _form(forms: Any, action: str) -> Any:
    """Le formulaire que la console a préparé pour une action de l'onglet (son jeton, son retour)."""
    return next((v for k, v in dict(forms or {}).items() if k.split("|", 1)[0] == action), None)


#: les tuiles de la vue d'ensemble : (titre du bloc de la faculté, l'onglet où il mène)
TILE_TABS = {"objectifs": "objectifs", "executions": "executions", "decisions": "decisions",
             "cadre": "comportement", "prochaine": "comportement", "depot": "git"}


def _tab(key: str, tab: str) -> str:
    return subject_url(KIND, key, tab)


def _to_decide(got: Got) -> list[str]:
    """Où se décide chaque demande qui attend ton accord : les liens vers la file que porte la section « À décider »
    de sa vue (un par demande, ``decide_where``), dans son ordre."""
    section = got.first("section", "À décider")
    return [p["value"]["href"] for b in got.walk((section or {}).get("items", [])) if b.get("t") == "fields"
            for p in b["pairs"] if p["label"] == DECIDE_LABEL and p["value"].get("t") == "link"]


def _banner(got: Got, key: str, notes: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Le seul bandeau de la page : ce qui attend ton accord, sinon ce qui l'arrête (sa pause, un objectif qui manque)."""
    if pending := _to_decide(got):
        n = len(pending)
        return {"tone": "warn", "text": (f"{plural(n, 'demande', 'demandes')} {agree(n, 'attend', 'attendent')} ton "
                                         "accord : ce qu'elle veut faire sortir de la machine, rien ne part sans toi."),
                "button": "Les décider", "href": pending[0]}
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


def overview(got: Got, key: str) -> Markup | None:
    """Projet › Vue d'ensemble : un bandeau, une bande de chiffres, des tuiles qui mènent à leurs onglets."""
    band = got.stats("Où il en est")
    if band is None:
        return None
    p = project_at(got.ui.kernel.mind.frame().state("projects"), key)
    notes = [b for b in got.items if b.get("t") == "note"]  # ce que la faculté dit de son état (pas ceux des tuiles)
    banner = _banner(got, key, notes)
    said = banner["text"] if banner else ""
    runs = got.timeline("Dernières exécutions")
    entries = (runs or {}).get("entries", [])
    figures = []
    for item in band["items"]:
        figure = {**item, "bars": []}
        if item["label"] == "Exécutions":  # ses dernières exécutions en barres, la plus ancienne d'abord
            figure["bars"] = [e.get("tone") or "ok" for e in reversed(entries)]
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
        runs=entries, failing=text((failures or {}).get("value")) if failures and failures.get("tone") else "",
        decisions=[{"n": x.text("n°"), "question": x["la question"], "choice": x.get("ce qui est choisi")}
                   for x in lines(decisions)],
        in_force=tab_counts(p)["decisions"] if p is not None else 0,
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


def behaviour(got: Got) -> Markup | None:
    """Projet › Comportement et outils, dans le gabarit du paramétrage : le formulaire « Modifier le projet »
    (préparé par la console) par groupes, une ligne par réglage et « Enregistrer » collé en bas ; ce que sa vue dit
    en cartes (son mode, son rythme, sa liberté) passe en aide de leur réglage, sa prochaine exécution en une ligne
    au-dessus ; sans formulaire (un projet archivé), ces faits en lecture. Puis ses outils : la table des lots, et
    « Choisir ses outils » à côté. Puis ses liens de lecture (ADR 0257), dans le même dessin : ce qu'il lit, « Choisir
    ce qu'il lit » à côté, et qui le lit."""
    rhythm, tools = got.fields("Son rythme"), got.first("section", "Ses outils")
    if rhythm is None or tools is None:
        return None
    facts = pairs(rhythm)
    form = _form(got.forms, "projects.modifier")
    return got.draw(
        "handmade/projets/fiche_comportement.html", notes=got.notes(), next_run=facts.get(NEXT_RUN_LABEL),
        edit=_edited(form, facts) if form is not None else None,
        settings=[] if form is not None else [b for title in SETTINGS_FACTS if (b := got.fields(title))],
        tools=tools, lots=_one_page(got.table("Ce qu'elle a en main")), choose=_form(got.forms, "projects.outils"),
        links=got.first("section", LINKS_TITLE), reads=_one_page(got.table(READS_TITLE)),
        readers=_one_page(got.table(READERS_TITLE)), link=_form(got.forms, "projects.liens"))


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


class ProjectFiche(Overview):
    """La fiche d'un projet : sa vue d'ensemble, ses objectifs, ses exécutions, ses décisions, Comportement et outils
    (le gabarit du paramétrage), « Accès » et le Carnet (en sous-onglets) dessinés ici, ses fichiers bloc par bloc
    (``blocks.page``), son dépôt git dans ``project_git`` ; Accès et Carnet sous « Plus »."""

    slug = ""
    title = "Vue d'ensemble"
    styles = ("handmade/outils.css", "handmade/projets.css", "handmade/projet-git.css")
    tabs = ("apercu", "objectifs", "executions", "decisions", "fichiers", "git", "comportement", "acces", "carnet")
    folded = ("acces", "carnet")
    folded_title = "Plus"

    def render(self, ui: UI, key: str) -> Markup | None:
        return None

    def counts(self, ui: UI, key: str) -> dict[str, int]:
        p = project_at(ui.kernel.mind.frame().state("projects"), key)
        return tab_counts(p) if p is not None else {}

    def render_tab(self, ui: UI, key: str, tab: str, blocks: Any, query: Any, forms: Any = None) -> Any:
        if tab == "apercu":
            return overview(Got(ui, list(blocks), query, forms or {}), key)
        if tab == "objectifs":
            return objectives(Got(ui, list(blocks), query, forms or {}))
        if tab == "executions":
            return runs(Got(ui, list(blocks), query, forms or {}))
        if tab == "decisions":
            return decisions(Got(ui, list(blocks), query, forms or {}))
        if tab == "fichiers":  # une table d'exploitation : en colonnes, et « Déposer un fichier » préparé par la console
            return drawn_blocks.page(ui, blocks, query, tables="table", forms=forms, tab="project/fichiers")
        if tab == "git":
            return git_page(Got(ui, list(blocks), query, forms or {}), key)
        if tab == "comportement":
            return behaviour(Got(ui, list(blocks), query, forms or {}))
        if tab == "carnet":
            return notebook(Got(ui, list(blocks), query, forms or {}))
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
            behaviour_tab=subject_url(KIND, key, "comportement")))
