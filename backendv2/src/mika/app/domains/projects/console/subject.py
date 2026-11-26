"""La fiche d'un projet, calquée sur l'écran Projets du client web (ADR 0297 ; avant : 0121, 0133, 0176, 0177, 0281).

**Son cadre.** Sous la barre du haut de la console : son en-tête (``ProjectFiche.head`` : son nom, son état en
pastilles, ses faits ; la console y pose ses actions), sa barre d'onglets — Vue d'ensemble, Objectifs, Tickets, Code,
Documentation, Activité, Dépendances, Listes (hors de la barre tant que le projet n'a pas de liste de suivi :
``ProjectFiche.hidden``), Administration —, puis le contenu de l'onglet sur toute la largeur. La liste des projets
n'y est pas : on y revient par le fil d'Ariane, comme l'écran par « ‹ Projets ». **Les trois zones** — une liste, le
contenu en volets, un panneau — valent pour un onglet en liste et détail, et la liste est la sienne (ses objectifs,
ses tickets) : ``goals.py``, ``diagram.py``, ``tickets.py`` (leurs aides :
``zones.py``). Sa feuille : ``projets_fiche.css`` et ``projets_zones.css`` (``pj-…``), le dessin de l'écran
porté sur les jetons de la console.

**Ce qu'elle lit.** Ce qu'un projet montre d'un coup d'œil vient de ``faculties/projects/glance.py`` — la source que
lit aussi l'API par personne : ses objectifs et leurs jalons en barres, ses pull requests ouvertes, ses tickets par
étape, ses dépendances, ses missions. Ce qui attend quelqu'un, son plan, ses dernières exécutions, sa prochaine
exécution, son dépôt et ses chiffres se lisent dans les blocs de sa vue (``Got``), ses faits dans son en-tête ; les
textes dans le magasin de contenus (``parts.texts``). Ce qu'elle lit par les fonctions de la faculté, à côté de sa
vue, est déclaré dans ``tests/protocol/test_drawn_fiches.py`` (ADR 0218) : le projet lui-même (``project_at``),
``glance``, et pour « Accès » ses lignes (``access_of``) et le nom de qui elles nomment (``who_named``).

**Ses onglets.**

- Vue d'ensemble (``overview``, ``vue.html``) : une grille de cartes sur toute la largeur, sans liste ni panneau —
  où il en est et ce qui attend quelqu'un en tête, puis ses objectifs, son code (son dépôt, ses pull requests et
  leurs vérifications), son prochain passage (son rythme, ses missions), puis ses tickets par étape, ses
  dépendances, ses dernières exécutions ; son plan en carte seulement quand il attend sa réponse (sinon il se lit
  dans Objectifs). Chaque carte mène à son onglet.
- Objectifs, Tickets, Listes : refaits sur l'écran (``goals.goals``, ``diagram.diagram_view``,
  ``tickets.tickets_page``, ``tickets.lists_page``) — ils posent eux-mêmes leurs zones.
- Administration (``administration``, ``admin.html``) : ce que seul le portail règle, en sous-onglets, dans le gabarit
  du paramétrage — ses réglages (``projects.modifier``), ses outils et services (``projects.outils``), ses lignes
  d'accès (l'onglet ``acces``, réuni : ``projects.acces``), ses tickets et ses issues (``projects.tickets_regler``),
  et « Sous le capot » (ses identifiants, ce qui retient son exécution, ses plafonds et ses pannes).
- Code, Documentation, Activité, Dépendances : refaits sur l'écran (``code.code_page``,
  ``docs.docs_page``, ``activity.activity_page``, ``links.links_page``), leurs sous-onglets en
  adresses (``?vue=``). Les adresses d'avant mènent à ce qui les a remplacées sans exécuter leur vue
  (``ProjectFiche.moved``) : ``?onglet=fichiers`` à Code, ``decisions`` à Documentation › Décisions, ``carnet`` à
  Activité › Carnet ; ``acces`` (réuni : ``ProjectFiche.joined``) à Administration › Accès.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from markupsafe import Markup

from mika.app.domains.projects.console.activity import activity_page
from mika.app.domains.projects.console.code import code_page
from mika.app.domains.projects.console.diagram import diagram_view
from mika.app.domains.projects.console.docs import doc_html, docs_page, page_url
from mika.app.domains.projects.console.git import git_page
from mika.app.domains.projects.console.goals import goals
from mika.app.domains.projects.console.links import links_page
from mika.app.domains.projects.console.tickets import lists_page, tickets_page
from mika.app.domains.projects.console.zones import (
    CHECKS_SHORT,
    CHECKS_TONES,
    DONE,
    FAIL,
    KIND,
    MARK_TONES,
    WAIT,
    WORK,
    YOU,
    Scene,
    tab_url,
)
from mika.app.handmade import blocks as drawn_blocks
from mika.app.handmade.access import (
    POLICY_CHOICES,
    canal_choices,
    canal_instances,
    people_with_accounts,
    who_choices,
)
from mika.app.handmade.subjects.parts import texts
from mika.app.handmade.tabs import (
    Got,
    lines,
    paged,
    pairs,
    text,
)
from mika.contracts import projects as c
from mika.faculties.projects import docs, glance
from mika.faculties.projects.access import STEER_WORDS, who_named
from mika.faculties.projects.faculty import access_of, project_at
from mika.faculties.projects.inspect import (
    ENGINE_TITLE,
    LIVING,
    NEXT_RUN_LABEL,
    TICKETS_SETTING_TITLE,
    window_words,
)
from mika.faculties.projects.inspect_code import PULLS, REMOTE, VIEW
from mika.faculties.projects.inspect_common import FORGOTTEN
from mika.faculties.projects.inspect_todo import TITLE as TODO_TITLE
from mika.faculties.projects.inspect_tracker import JOURNEY_WORDS
from mika.faculties.projects.inspect_words import CHECKS_FR, OBJ_FR, PULL_FR
from mika.inspector import render
from mika.inspector.pages.episode_drawn import EPISODE_STYLES
from mika.inspector.pages.subjects import subject_url
from mika.inspector.ui import UI, Overview, env
from mika.kernel.inspect import Head, Pager, plural, relative_fr
from mika.plugins.forge.access import app_tool_names
from mika.ports.workshop import PULL_OPEN
from mika.vocab.access import MOMENTS, PERSON, when_words

MOMENT_CHOICES = tuple((k, label[:1].upper() + label[1:]) for k, label in MOMENTS)
#: les titres de ses onglets (ceux de leur vue dans la faculté) : la console passe les blocs d'un onglet réuni
#: (``ProjectFiche.joined``) dans une section à ce titre
CODE_TITLE, ADMIN_TITLE, ACCESS_TITLE = "Code", "Administration", "Accès"
#: les couleurs d'état de l'écran, les mêmes partout (``projets_fiche.css``), viennent de ``zones``
#: le ton d'une étiquette de son en-tête → une couleur d'état : actif, elle y travaille ; en pause, il t'attend
TONES = {"ok": WORK, "info": WORK, "warn": YOU, "danger": FAIL, "muted": WAIT, "": WAIT}
#: le ton d'une exécution (son verdict) → sa couleur : fait, elle continue, elle attend quelqu'un, bloqué
RUN_TONES = {"ok": DONE, "info": WORK, "muted": YOU, "danger": FAIL, "": WORK}
#: la sorte d'une attente (le premier mot de son étiquette) → son icône
WAITING_ICONS = (("accord", "shield"), ("ticket", "ticket"), ("plan", "list"), ("point", "flag"), ("relecture", "pr"))
#: son flux, en mots (ceux du réglage « Son dépôt distant »)
FLOW_WORDS = {c.FLOW_DIRECT: "direct", c.FLOW_PR: "par pull request"}
#: ce qu'une carte de la vue d'ensemble montre au plus : ses objectifs, ce qui attend avant « et n de plus », ses
#: dernières exécutions ; et un texte d'une ligne
GOALS_SHOWN, WAITING_SHOWN, RUNS_SHOWN, LINE_SHOWN = 4, 3, 2, 240
#: les faits de son en-tête dits sous son nom, sur tous ses onglets (son mode, pour qui) ; les suivants sont dits une
#: fois ailleurs : sa dernière exécution sur « Où il en est », sa plage sur « Prochain passage » (sa vue d'ensemble),
#: sa dernière tentative dans Administration › Sous le capot
HEAD_FACTS = 2


def _form(forms: Any, action: str) -> Any:
    """Le formulaire que la console a préparé pour une action de l'onglet (son jeton, son retour)."""
    return next((v for k, v in dict(forms or {}).items() if k.split("|", 1)[0] == action), None)


def _tab(key: str, tab: str = "", anchor: str = "") -> str:
    return subject_url(KIND, key, tab) + (f"#{anchor}" if anchor else "")


def _part(got: Got, title: str) -> Got | None:
    """Un onglet réuni sous un autre (``Overview.joined``) : les blocs de sa section, lus comme ceux d'un onglet —
    la console les passe dans une ``Section`` à son titre. Sans section à ce titre (l'onglet seul), rien."""
    section = next((b for b in got.items if b.get("t") == "section" and b.get("title") == title), None)
    if section is None:
        return None
    part = copy.copy(got)
    part.items = list(section.get("items", []))
    return part


def _line(said: str, limit: int = LINE_SHOWN) -> str:
    """Un texte en une ligne, coupé au mot."""
    said = " ".join(said.split())
    return said if len(said) <= limit else said[:limit].rsplit(" ", 1)[0] + "…"


# ── Le cadre : le contenu d'un onglet, sur toute la largeur ──────────────────────────────────────────────────────


def framed(body: Any) -> Any:
    """Le contenu d'un onglet dans le cadre de la fiche (ADR 0297), sur toute la largeur — sans la liste des projets :
    on y revient par le fil d'Ariane. Ce qu'un onglet laisse à la console (un couple, un triplet) reste tel quel ;
    rien à dessiner : rien."""
    if body is None:
        return None
    if isinstance(body, tuple):
        return (framed(body[0]), *body[1:])
    return Markup(env.get_template("handmade/projets/cadre.html").render(body=body))


def _blocks(part: Got, tab: str) -> Markup:
    """Les blocs d'une section, dessinés un à un (``blocks.page``) sans les renuméroter : leurs formulaires restent
    ceux que la console a préparés pour la page entière."""
    return Markup(env.get_template("handmade/shared/blocks.html").render(
        blocks=[drawn_blocks.shape_block(d) for d in part.items], tables="table", forms=part.forms, tab=tab))


# ── La Vue d'ensemble ─────────────────────────────────────────────────────────────────────────────────────────


def _waiting(got: Got) -> dict[str, Any] | None:
    """Ce qui attend quelqu'un (ADR 0281), tel que sa vue le dit : une ligne par attente — sa sorte, de quoi il
    s'agit, depuis quand, qui elle attend, et le lien de son geste."""
    t = got.table(TODO_TITLE)
    if t is None:
        return None
    # combien attendent : une ligne peut en résumer plusieurs (les éléments d'une liste) — le titre de la table le
    # dit alors ; sinon c'est le nombre de ses lignes, que la console a ôté du titre
    counted = re.search(r"\((\d+)\)$", str(t.get("title") or ""))
    return {"empty": t.get("empty", ""), "caption": t.get("caption", ""),
            "count": int(counted.group(1)) if counted else int(t.get("count") or 0),
            "items": [{"kind": x.get("quoi"), "text": x.text("de quoi il s'agit"), "since": x.get("depuis"),
                       "who": x.get("attend"), "go": x.get("le geste"), "project": x.get("projet"),
                       "icon": next((icon for word, icon in WAITING_ICONS if word in x.text("quoi")), "inbox")}
                      for x in lines(t)]}


def _alarm(key: str, notes: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Le seul bandeau de la page : ce qui l'arrête (sa pause, un objectif qui manque). Ce qui attend ton accord n'y
    est pas : la carte de ce qui attend le dit (ADR 0281)."""
    alarm = next((n for n in notes if n.get("tone") in ("warn", "danger")), None)
    if alarm is None:
        return None
    paused = alarm["text"].startswith("En pause")
    return {"tone": alarm["tone"], "text": alarm["text"], "button": "Voir son activité" if paused else "",
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


def _goals(g: glance.Glance, said: dict[str, str], key: str) -> list[dict[str, Any]]:
    """Ses objectifs ponctuels, ceux en cours d'abord : son texte, son état, ses jalons en une barre (un segment par
    jalon, à la couleur de son état ; sans jalon, un seul, à la couleur de l'objectif)."""
    out = []
    for o in g.goals[:GOALS_SHOWN]:
        tone = DONE if o.status == c.DONE else FAIL if o.status == c.BLOCKED else WORK
        out.append({"n": o.id, "text": said.get(o.text_ref, FORGOTTEN), "state": OBJ_FR.get(o.status, o.status),
                    "tone": tone, "marks": [MARK_TONES[m] for m in o.marks] or [tone],
                    "said": f"{o.reached} / {plural(len(o.marks), 'jalon', 'jalons')}" if o.marks else "pas de jalon",
                    "href": tab_url(key, "objectifs", objectif=o.id)})
    return out


def _pulls(g: glance.Glance, now: int, key: str) -> list[dict[str, Any]]:
    """Ses pull requests ouvertes : son titre, son numéro, depuis quand, où en sont ses vérifications et sa
    relecture."""
    return [{"n": x.number, "title": x.title or f"Pull request n° {x.number}", "age": relative_fr(x.at, now),
             "state": PULL_FR.get(PULL_OPEN, "ouverte").split(",")[0], "tone": CHECKS_TONES.get(x.checks, WORK),
             "checks": CHECKS_SHORT.get(x.checks, ""), "checks_tone": CHECKS_TONES.get(x.checks, WAIT),
             "checks_said": CHECKS_FR.get(x.checks, ""),
             "review": "" if x.reviewed is None else "relue" if x.reviewed else "relue : des constats",
             "review_tone": DONE if x.reviewed else FAIL, "conflicts": x.conflicts, "objective": x.objective,
             "url": x.url, "href": tab_url(key, "git", vue=PULLS, pr=x.number)} for x in g.pulls]


def _steps(g: glance.Glance) -> dict[str, Any]:
    """Ses tickets par étape du parcours : une barre empilée (la position et la largeur de chaque part, en tickets)
    et sa légende."""
    parts, at = [], 0
    for i, (code, n) in enumerate(g.steps):
        parts.append({"i": i % 6, "label": JOURNEY_WORDS.get(code, code), "count": n, "x": at})
        at += n
    return {"total": at, "open": g.tickets_open, "parts": parts}


def _linked(ui: UI, s: Any, ids: tuple[int, ...], key: str) -> list[dict[str, Any]]:
    found = [q for q in (project_at(s, i) for i in ids) if q is not None]
    names = texts(ui, [q.title_ref for q in found])
    return [{"title": names.get(q.title_ref, FORGOTTEN), "href": _tab(key, "liens")} for q in found]


def overview(got: Got, key: str) -> Markup | None:
    """Projet › Vue d'ensemble (ADR 0297) : son bandeau, puis une grille de cartes sur toute la largeur — où il en
    est et ce qui attend quelqu'un en tête ; ses objectifs et leurs jalons en barres, son code (son dépôt distant, ses
    pull requests ouvertes avec leurs vérifications, son dernier commit), son prochain passage (son rythme, ses
    missions) ; ses tickets par étape, ses dépendances, ses dernières exécutions. Son plan : en carte quand il attend
    sa réponse, sinon en une ligne qui mène à Objectifs. Chaque carte mène à son onglet."""
    ui = got.ui
    frame = ui.kernel.mind.frame()
    s = frame.state("projects")
    p = project_at(s, key)
    if p is None or got.stats("Où il en est") is None:
        return None
    g = glance.of(p, s, frame)
    target = next((o for o in p.objectives if o.id == g.coming.objective), None)
    said = texts(ui, [p.summary_ref, p.description_ref, *(o.text_ref for o in g.goals),
                      *(m.text_ref for m in g.missions), *((target.text_ref,) if target is not None else ())])
    notes = [b for b in got.items if b.get("t") == "note"]  # ce que la faculté dit de son état
    banner = _alarm(key, notes)
    shown = banner["text"] if banner else ""
    coming = pairs(got.fields("Prochaine exécution"))
    when, _, held = text(coming.get("quand")).partition(" (")
    recent = (got.timeline("Dernières exécutions") or {}).get("entries", [])
    depot = pairs(got.fields("Son dépôt"))
    return got.draw(
        "handmade/projets/vue.html", banner=banner, notes=[n for n in notes if n["text"] != shown],
        where={"text": _line(said.get(p.summary_ref, "")) if p.summary_ref else "",
               "description": said.get(p.description_ref, "") if p.description_ref else "",
               "age": relative_fr(p.last_run_at, frame.now) if p.last_run_at else ""},
        waiting=_waiting(got), most=WAITING_SHOWN, plan=_plan(got),
        goals=_goals(g, said, key), done=g.done, total=g.total,
        pulls=_pulls(g, frame.now, key), by_pulls=p.flow == c.FLOW_PR, commit=p.last_commit[:7], branch=p.branch,
        flow=FLOW_WORDS.get(p.flow, p.flow), remote=bool(p.remote), steps=_steps(g),
        depot=depot.get("dépôt distant") if p.remote else None,
        reads=_linked(ui, s, g.reads, key), readers=_linked(ui, s, g.readers, key),
        coming={"when": when, "held": held.rstrip(")"),
                "about": said.get(target.text_ref, FORGOTTEN) if target is not None else ""},
        rhythm=f"{g.schedule} · {window_words(p)}",
        missions=[{"text": said.get(m.text_ref, FORGOTTEN), "said": " · ".join((m.cadence, *m.on)),
                   "off": m.status != c.OPEN, "href": tab_url(key, "objectifs", objectif=m.id)} for m in g.missions],
        runs=[{**e, "tone": RUN_TONES.get(e.get("tone") or "", WORK)} for e in recent[:RUNS_SHOWN]],
        links={"objectifs": _tab(key, "objectifs"), "tickets": _tab(key, "tickets"), "code": _tab(key, "git"),
               "pulls": tab_url(key, "git", vue=PULLS), "liens": _tab(key, "liens"),
               "activite": _tab(key, "executions"), "reglages": _tab(key, "comportement", "cadre-reglages"),
               "plan": tab_url(key, "objectifs", plan=1)})


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


#: les sous-onglets d'« Administration » : (ancre, libellé) — « Accès » garde le nom de son onglet réuni, où mène son
#: ancienne adresse ; les ancres d'avant (« Cadre ») valent toujours
ADMIN_PANES = (("cadre-reglages", "Ses réglages"), ("cadre-outils", "Outils et services"), ("acces", "Accès"),
               ("cadre-tickets", "Tickets et issues"), ("admin-capot", "Sous le capot"))


def administration(got: Got, key: str) -> Markup | None:
    """Projet › Administration (ADR 0297), ce que seul le portail règle, dans le gabarit du paramétrage et en
    sous-onglets. « Ses réglages » : le formulaire « Modifier le projet » (préparé par la console) par groupes, une
    ligne par réglage et « Enregistrer » collé en bas ; ce que sa vue dit en cartes (son mode, son rythme, sa
    liberté) passe en aide de leur réglage, sa prochaine exécution en une ligne au-dessus ; sans formulaire (un
    projet archivé), ces faits en lecture. « Outils et services » : la table des lots, et « Choisir ses outils » à
    côté. « Accès » : ses lignes d'accès (l'onglet réuni, ``ProjectFiche.joined``). « Tickets et issues » : qui
    valide le plan d'un ticket, la borne d'un petit ticket, la publication en issues, en faits, et le formulaire qui
    les règle. « Sous le capot » : ses identifiants, ce qui retient son exécution, ses plafonds et ses pannes, ce
    que son atelier a laissé — en lecture. Chaque sous-onglet dit en une ligne ce qui vaut (``said``)."""
    whole = got
    got = _part(whole, ADMIN_TITLE) or whole
    rhythm, tools = got.fields("Son rythme"), got.first("section", "Ses outils")
    if rhythm is None or tools is None:
        return None
    facts = pairs(rhythm)
    form = _form(whole.forms, "projects.modifier")
    tickets = got.first("section", TICKETS_SETTING_TITLE)
    engine = got.first("section", ENGINE_TITLE)
    rights = access(got.ui, key, whole.forms) if _part(whole, ACCESS_TITLE) is not None else None
    lots = _one_page(got.table("Ce qu'elle a en main"))
    ticket_facts = next((x for x in (tickets or {}).get("items", []) if x.get("t") == "fields"), None)
    p = project_at(got.ui.kernel.mind.frame().state("projects"), key)
    count = len(access_of(p)[0]) if p is not None else 0
    shown = {"cadre-reglages": True, "cadre-outils": True, "acces": rights is not None,
             "cadre-tickets": tickets is not None, "admin-capot": engine is not None}
    said = {"cadre-reglages": text(pairs(got.fields("Son mode")).get("mode")),
            "cadre-outils": plural(len(lines(lots)), "lot", "lots"),
            "acces": f"{plural(count, 'ligne', 'lignes')}, puis la ligne par défaut",
            "cadre-tickets": text(next(iter(pairs(ticket_facts).values()), None)),
            "admin-capot": "identifiants, plafonds, pannes"}
    nested = list(whole.walk((tickets or {}).get("items", []))) + list(whole.walk((engine or {}).get("items", [])))
    return whole.draw(
        "handmade/projets/admin.html",
        notes=[n for n in got.every("note") if n not in nested and not n.get("title")],
        next_run=facts.get(NEXT_RUN_LABEL),
        edit=_edited(form, facts) if form is not None else None,
        settings=[] if form is not None else [b for title in SETTINGS_FACTS if (b := got.fields(title))],
        tools=tools, lots=lots, choose=_form(whole.forms, "projects.outils"),
        access=rights, tickets=tickets, ticket_facts=ticket_facts,
        ticket_form=_form(whole.forms, "projects.tickets_regler"),
        engine=[x for x in whole.walk((engine or {}).get("items", [])) if x.get("t") == "fields"],
        engine_help=(engine or {}).get("description", ""),
        lists_href="" if p is None or p.board.lists else _tab(key, "suivi"),
        panes=[{"id": i, "label": label, "said": said[i]} for i, label in ADMIN_PANES if shown[i]])


def _one_page(table: dict[str, Any] | None) -> dict[str, Any] | None:
    """Une liste qui tient sur une page ne dit ni « 1–4 sur 4 » ni « Page 1 sur 1 » : sa pagination reste dans la
    page (la console l'exige), masquée (``.hm-pager.single``)."""
    if table is None or paged(table):
        return table
    return {**table, "pager": None, "raw_pager": table.get("pager")}


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
        pager=render.pager_ctx(Pager(size=len(rows) + 1, total=len(rows) + 1), {}),
        behaviour_tab=subject_url(KIND, key, "comportement") + "#cadre-outils"))


class ProjectFiche(Overview):
    """La fiche d'un projet, calquée sur l'écran Projets (ADR 0297) : Vue d'ensemble, Objectifs, Tickets, Code,
    Documentation (Pages, Images, Décisions), Activité (Fil, Exécutions, Carnet), Dépendances (Schéma, Demandes),
    Listes (hors de la barre tant qu'il n'a pas de liste de suivi), Administration (ses réglages, ses outils, « Accès »,
    ses tickets, « Sous le capot »). Un onglet en liste et détail pose lui-même ses trois zones, Administration sa
    colonne de sous-onglets ; la Vue d'ensemble se pose dans le cadre (``framed``)."""

    slug = ""
    title = "Vue d'ensemble"
    styles = ("handmade/outils.css", "handmade/projets.css", "handmade/projet-git.css", "handmade/projets_fiche.css",
              "handmade/projets_zones.css", "handmade/projets_code.css", "handmade/projets_docs.css",
              "handmade/projets_activite.css", *EPISODE_STYLES)
    tab_scripts = ("handmade/doc_editor.js",)
    #: les onglets refaits en liste et détail : ils posent eux-mêmes leurs trois zones
    zoned = ("objectifs", "tickets", "suivi")
    tabs = ("apercu", "objectifs", "executions", "tickets", "suivi", "liens", "documentation", "git", "comportement",
            "acces")
    #: un onglet et ceux qu'il porte en sous-onglets : leurs adresses d'avant y mènent
    joined = {"comportement": ("acces",)}
    #: des onglets dont l'adresse mène à ce qui les a remplacés, sans exécuter leur vue (ADR 0297)
    moved = {"fichiers": "git", "decisions": "documentation?vue=decisions", "carnet": "executions?vue=carnet"}

    def render(self, ui: UI, key: str) -> Markup | None:
        return None

    def head(self, ui: UI, key: str) -> Markup | None:
        """Son en-tête, sur tous ses onglets : son nom, son état en pastilles, ses faits sur une ligne — ceux de
        l'en-tête que déclare sa faculté ; la console y pose ses actions."""
        got = ui.inspection.head(KIND, key, ui.when_long)
        if not isinstance(got, Head):
            return None
        cell_env = ui.env()
        return Markup(env.get_template("handmade/projets/tete.html").render(
            title=got.title, badges=[{"text": b.text, "tone": TONES.get(b.tone, WAIT)} for b in got.badges],
            facts=[{"label": k, "cell": render.cell(v, cell_env)} for k, v in got.facts[:HEAD_FACTS]]))

    def hidden(self, ui: UI, key: str) -> tuple[str, ...]:
        """« Listes » n'est dans la barre que pour un projet qui a une liste de suivi ; son adresse marche toujours
        (Administration y mène, pour en créer une)."""
        p = project_at(ui.kernel.mind.frame().state("projects"), key)
        return () if p is None or p.board.lists else ("suivi",)

    def counts(self, ui: UI, key: str) -> dict[str, int]:
        """Ce que ses onglets comptent : ses objectifs ouverts — ce que montre Objectifs quand on l'ouvre, sous
        « Ouverts » : ponctuels et missions, en cours ou bloqués —, ses tickets ouverts."""
        frame = ui.kernel.mind.frame()
        s = frame.state("projects")
        p = project_at(s, key)
        if p is None:
            return {}
        g = glance.of(p, s, frame)
        return {"objectifs": sum(1 for o in p.objectives if o.status in LIVING), "tickets": g.tickets_open}

    def render_tab(self, ui: UI, key: str, tab: str, blocks: Any, query: Any, forms: Any = None) -> Any:
        if tab == "comportement":  # sa colonne est celle de ses sous-onglets
            return administration(Got(ui, list(blocks), query, forms or {}), key)
        if tab == "git":  # ses sous-onglets, chacun dans ses zones (ADR 0297)
            return self.code(Scene(ui, key, query, forms), Got(ui, list(blocks), query, forms or {}), key)
        if tab in self.zoned:  # sa liste, son contenu, son panneau : il les pose lui-même
            return self.zones(Scene(ui, key, query, forms), tab)
        if tab in self.drawn:
            return self.drawn[tab](Scene(ui, key, query, forms))
        return framed(self.content(ui, key, tab, blocks, query, forms))

    #: les onglets refaits qui lisent tout par la faculté (ADR 0297) : leurs sous-onglets en adresses
    drawn = {"documentation": docs_page, "executions": activity_page, "liens": links_page}

    @staticmethod
    def zones(sc: Scene, tab: str) -> Markup | None:
        """Un onglet en liste et détail (ADR 0297) : Objectifs (sa liste, ou son diagramme), Tickets, Listes."""
        if tab == "objectifs":
            return diagram_view(sc) if sc.query.get("vue") == "diagramme" else goals(sc)
        return tickets_page(sc) if tab == "tickets" else lists_page(sc)

    def content(self, ui: UI, key: str, tab: str, blocks: Any, query: Any, forms: Any = None) -> Any:
        """Le contenu d'un onglet, avant son cadre : la Vue d'ensemble ; « Accès » demandé seul (hors
        d'Administration), ses lignes telles quelles."""
        if tab == "apercu":
            return overview(Got(ui, list(blocks), query, forms or {}), key)
        if tab == "acces":
            return access(ui, key, forms)
        return None

    def preview(self, ui: UI, key: str, text: str, where: str = "") -> Markup | None:
        """L'aperçu d'une page de sa documentation, rendu comme la page le sera (``docs.doc_html``) :
        l'éditeur de la console le demande (``/admin/apercu/project/<n>``)."""
        sc = Scene(ui, key, {}, None)
        if sc.p is None:
            return None
        paths = [x.path for x in docs.tree(ui.kernel.mind.store, sc.p.id)]
        html, _ = doc_html(sc.p, text, where.rpartition("/")[0], lambda path: page_url(sc, path), paths)
        return html

    @staticmethod
    def code(sc: Scene, got: Got, key: str) -> Markup | None:
        """Code, calqué sur l'écran (``code.code_page``) : Fichiers, Commits, Pull requests, Branches, Issues,
        CI ; « l'atelier face au distant » (``vue=distant``) garde ce que seul l'onglet Dépôt d'avant avait —
        pousser, récupérer, ses échanges avec le distant, ses réglages (``git``) —, sous la même barre."""
        if sc.query.get(VIEW) != REMOTE:
            return code_page(sc, got)
        depot = _part(got, CODE_TITLE) or got
        legacy = git_page(depot, key)
        return code_page(sc, got, legacy if legacy is not None else _blocks(depot, "project/git"))
