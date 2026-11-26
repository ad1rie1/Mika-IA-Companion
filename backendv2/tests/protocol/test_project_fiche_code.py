"""La fiche d'un projet › Code, calquée sur l'écran Projets (ADR 0288, 0297) : ses sous-onglets en adresses, chacun
dans ses zones ; le contenu d'un fichier, d'un diff ou de l'hôte en texte brut ; un Markdown rendu sans lien ni image ;
la fusion d'une pull request par l'action ``projects.fusionner``, au commit de tête que la page a lu, et ses refus ;
modifier une pull request et y répondre ; accepter le ticket qu'une issue propose ; les lectures de l'hôte gardées.

Le dépôt est celui des tests de l'API par personne (``test_moi_project_code.Repo`` : un vrai atelier, sa branche de
travail, sa pull request n° 12 que l'hôte en mémoire dit ouverte) : les deux écrans lisent les mêmes règles."""

from __future__ import annotations

import html
import json
import re

import pytest

from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.faculties.projects import inspect_code, inspect_merge, merge, tracker
from mika.faculties.projects.faculty import PULL_REQUEST_CAPABILITY
from mika.faculties.projects.merge import MERGE_ASKED
from mika.faculties.projects.pulls import CHECKS_SEEN
from mika.kernel.events import Content
from mika.ports.workshop import (
    CHECKS_FAILED,
    CHECKS_NONE,
    CHECKS_PENDING,
    CheckRun,
    Checks,
    Issue,
    Issues,
    Remark,
)
from tests.protocol.test_drawn_fiches import form_of
from tests.protocol.test_drawn_pages import drawn
from tests.protocol.test_moi_mail import append, journal
from tests.protocol.test_moi_project_code import LURE, PAGE, Repo
from tests.protocol.test_moi_projects import _project
from tests.protocol.test_web import world  # noqa: F401 — fixture partagée
from tests.unit.test_project_pulls import needs_bwrap

pytestmark = needs_bwrap
FICHE = "/admin/fiche/project/{}?onglet=git"
TRAP = "# Piège\n\n[ouvre-moi](https://piege.example/x) ![image](https://piege.example/i.png)\n\n<script>alert(1)</script>\n"


@pytest.fixture
def repo(world) -> Repo:  # noqa: F811
    client, live, _ = world
    return Repo(client, live)


def _page(r: Repo, more: str = "") -> str:
    return drawn(r.client, FICHE.format(r.pid) + more)


def _raw(r: Repo, more: str = "") -> str:
    return r.client.get(FICHE.format(r.pid) + more).text


def _post(r: Repo, form: dict[str, list[str]], action: str, **values: str):
    data = {**form, "_champs": [*form.get("_champs", []), *values], **{k: [v] for k, v in values.items()}}
    return r.client.post(f"/admin/action/{action}", data=data, follow_redirects=False)


def _zone(page: str, start: str, end: str = "</aside>") -> str:
    return page.split(start, 1)[1].split(end, 1)[0]


def test_files_are_read_at_a_branch_and_say_what_they_cannot_show(repo):
    r = repo
    call = r.client.portal.call
    call(r.ws.write, r.pid, "docs/piege.md", TRAP)
    call(r.ws.commit, r.pid, "docs : une page piégée")
    page = _page(r)
    assert 'data-tab="project/git"' in page and 'id="fichiers"' in page and "style=" not in _zone(page, 'class="pj-code"', "</main>")
    bar = _zone(page, 'aria-label="Son code"', "</nav>")
    assert re.findall(r'aria-current="page">([^<]+)', bar) == ["Fichiers"]
    assert f"{PAGE[8:]}" in page and "vue=distant" in page  # son dépôt distant, qui mène à l'atelier face au distant
    # rien n'est choisi : le README de la base, rendu — la page d'accueil du dépôt
    assert "la page d'accueil du dépôt" in page and "<h3>Outils réseau</h3>" in page
    tree = _zone(page, 'aria-label="L\'arborescence"', "</nav>")
    assert re.findall(r"<span>([^<]+)</span>", tree)[:3] == ["outils", "README.md", "logo.png"]  # à la base
    # un fichier, à la branche de travail : en chasse fixe, ses lignes numérotées ; son dossier s'ouvre
    shown = _raw(r, f"&ref={r.branch}&chemin=outils/scan.py")
    rows = re.findall(r'<div class="r"><span class="ln">(\d+)</span><span class="cd">([^<]*)</span></div>', shown)
    assert rows[:2] == [("1", "PORT = 22"), ("2", "DELAI = 2")] and len(rows) == 6
    assert 'class="pj-node d1" href=' in shown and "journal.py" in shown  # le dossier ouvert, à cette branche
    assert ">Python<" in shown and "Dernier commit" in shown and "journal : écrire chaque refus" in shown
    # un binaire le dit ; un chemin caché aussi, sans rien lire
    assert "Un fichier binaire : son contenu ne s'affiche pas." in _page(r, f"&ref={r.branch}&chemin=logo.png")
    assert inspect_code.HIDDEN in _page(r, "&chemin=.env")
    # un Markdown du dépôt : rendu sans lien qui s'ouvre, sans image chargée, sans script ; ou sa source
    trap = _raw(r, f"&ref={r.branch}&chemin=docs/piege.md")
    rendered = _zone(trap, 'class="pj-md pj-readme"', "</div>")
    assert "piege.example" not in rendered and "<img" not in rendered and "<script" not in rendered
    assert 'class="pj-md-a">ouvre-moi</span>' in rendered and "&lt;script&gt;" in rendered
    source = _raw(r, f"&ref={r.branch}&chemin=docs/piege.md&md=source")
    assert "(https://piege.example/x)" in html.unescape(source) and 'class="pj-md pj-readme"' not in source
    # « Déposer un fichier » s'ouvre dans le contenu, son formulaire envoie un fichier
    deposit = _raw(r, "&deposer=1")
    assert 'action="/admin/action/projects.deposer"' in deposit and 'enctype="multipart/form-data"' in deposit


def test_commits_come_by_day_and_a_commit_shows_its_diff_unified_or_side_by_side(repo):
    r = repo
    page = _page(r, "&vue=commits")
    days = re.findall(r'<p class="pj-day">([^<]+)</p>', page)
    assert days and "journal : écrire chaque refus" in page and "squelette : paquet et premiers tests" in page
    shown = _raw(r, f"&vue=commits&sha={r.head}")
    assert "outils/scan.py" in shown and "outils/journal.py" in html.unescape(shown)
    added = re.findall(r'<div class="r add"><span class="ln"></span><span class="ln">(\d+)</span>'
                       r'<span class="sg">\+</span><span class="cd">([^<]*)</span></div>', shown)
    assert ("2", "DELAI = 2") in added and ("3", "    return [PORT]") not in added
    assert 'class="r hunk"' in shown and "Le commit" in shown and "Ce qui est lié" in shown
    side = _raw(r, f"&vue=commits&sha={r.head}&diff=cote")
    assert 'class="pj-diff cote"' in side and 'class="ln rien"' in side
    assert 'aria-current="true">' in _zone(side, 'aria-label="La forme du diff"', "</nav>")
    # le filtre par branche, en liens
    only = _page(r, f"&vue=commits&ref={r.branch}")
    assert f"ref={r.branch.replace('/', '%2F')}" in only


def test_a_pull_request_reads_in_panes_and_merges_at_the_head_the_page_read(repo):
    r = repo
    r.host.talks[12] = (Remark(id=1, issue=12, author="bea", body=f"<b>Bien</b> — {LURE}", at=1),)
    page = _raw(r, "&vue=pulls&pr=12")
    drawn(r.client, FICHE.format(r.pid) + "&vue=pulls&pr=12")
    said = html.unescape(page)
    assert "Pull request n° 12" in said and "prête à fusionner" in said and "Journaliser les connexions refusées" in said
    assert re.findall(r'<a href="#(pr-\w+)">', _zone(page, 'aria-label="Ce qu\'on en lit"', "</nav>")) == [
        "pr-resume", "pr-commits", "pr-fichiers", "pr-echanges"]
    # ce qui vient de l'hôte : son texte et ses échanges, en texte brut, présentés comme venus d'ailleurs
    assert "&lt;b&gt;Bien&lt;/b&gt;" in page and "<b>Bien</b>" not in page and "Venu d'ailleurs" in page
    assert "ruff check" in page and "pytest · 3.12" in said  # ses vérifications, une à une
    # la fusion : une confirmation qui dit ce qui part et nomme le commit de tête lu
    confirm = _zone(page, 'class="action-panel pj-confirm"', "</details>")
    assert f"<code>{r.head[:12]}</code>" in confirm and "Si sa branche bouge d'ici là, rien ne part." in confirm
    form = form_of(page, inspect_merge.ACTION)
    assert form["head"] == [r.head] and form["objective"] == [str(r.oid)] and "data-confirm" not in confirm
    # la tête a bougé depuis : rien ne part, et la page de l'action le dit
    moved = _post(r, {**form, "head": [r.base]}, inspect_merge.ACTION)
    assert journal(r.live, MERGE_ASKED) == [] and "a bougé depuis ce que tu as lu" in html.unescape(
        moved.text if moved.status_code == 200 else r.client.get(moved.headers["location"]).text)
    # l'hôte dit ses vérifications en cours : rien ne part non plus (la règle de l'action, relue chez lui)
    r.host.checked[r.head] = Checks(sha=r.head, state=CHECKS_PENDING)
    form = form_of(_raw(r, "&vue=pulls&pr=12"), inspect_merge.ACTION)  # la page relue : un nouveau jeton de geste
    pending = _post(r, form, inspect_merge.ACTION)
    assert journal(r.live, MERGE_ASKED) == [] and inspect_merge.BLOCK_WORDS[merge.RUNNING] in html.unescape(
        pending.text if pending.status_code == 200 else r.client.get(pending.headers["location"]).text)
    r.host.checked[r.head] = Checks(sha=r.head, state="passed")
    form = form_of(_raw(r, "&vue=pulls&pr=12"), inspect_merge.ACTION)
    done = _post(r, form, inspect_merge.ACTION)
    assert done.status_code == 303 and "vue=pulls" in done.headers["location"]
    [asked] = journal(r.live, MERGE_ASKED)
    assert (asked.data.number, asked.data.sha) == (12, r.head)
    after = html.unescape(_raw(r, "&vue=pulls&pr=12"))
    assert inspect_merge.BLOCK_WORDS[merge.ASKED] in after or "Sa fusion est demandée" in after
    assert 'action="/admin/action/projects.fusionner"' not in _raw(r, "&vue=pulls&pr=12")


def test_checks_still_running_hold_the_merge_on_the_page(repo):
    r = repo
    append(r.client, r.live, [CHECKS_SEEN.draft(project=r.pid, objective=r.oid, sha=r.head, state=CHECKS_PENDING,
                                                **r.about)], "projects")
    page = html.unescape(_raw(r, "&vue=pulls&pr=12"))
    assert inspect_merge.BLOCK_WORDS[merge.RUNNING] in page and "disabled" in page
    assert 'action="/admin/action/projects.fusionner"' not in page


def test_the_page_says_what_the_host_it_read_would_make_the_merge_refuse(repo):
    """ADR 0297 (C2 l'avait vu) : le journal disait la CI passée, l'hôte la disait en cours — la page offrait
    « Fusionner » et l'action le refusait. La page applique à sa propre lecture de l'hôte la règle de l'action
    (``merge.checks_block``) : elle dit ce que le moteur dirait, sans offrir le geste."""
    r = repo
    ready = _raw(r, "&vue=pulls&pr=12")
    assert 'action="/admin/action/projects.fusionner"' in ready  # prête : l'hôte lu dit sa CI passée
    r.host.checked[r.head] = Checks(sha=r.head, state=CHECKS_PENDING, runs=(CheckRun("pytest", CHECKS_PENDING, 1, 0),))
    page = html.unescape(_raw(r, "&vue=pulls&pr=12&frais=1"))
    assert inspect_merge.BLOCK_WORDS[merge.RUNNING] in page and "disabled" in page
    assert 'action="/admin/action/projects.fusionner"' not in page


def test_a_pull_request_is_edited_and_answered_from_its_page(repo):
    r = repo
    page = _raw(r, "&vue=pulls&pr=12")
    edit = _zone(page, 'id="pr-modifier"', "</section>")
    assert 'name="title"' in edit and 'name="body"' in edit and "Branche " in html.unescape(edit)
    form = form_of(page, "projects.pull_modifier")
    assert _post(r, form, "projects.pull_modifier", title="Un meilleur titre", body="").status_code == 303
    reply = form_of(page, "projects.pull_commenter")
    assert _post(r, reply, "projects.pull_commenter", text="Merci, je regarde.").status_code == 303
    written = journal(r.live, merge.PULL_WRITE_ASKED)
    assert len(written) == 2 and {e.data.number for e in written} == {12}


def test_branches_issues_and_checks_have_their_views(repo):
    r = repo
    branches = _raw(r, "&vue=branches")
    assert 'class="pj-btable"' in branches and f"<code>{r.branch}</code>" in branches
    assert "par défaut" in branches and "Ce qu'elle a d'avance" in branches  # la branche de travail, choisie d'office
    assert "Ses fichiers" in branches and f"ref={r.branch.replace('/', '%2F')}" in branches
    # une issue d'un inconnu, ses échanges : en texte brut ; le ticket qu'elle propose s'accepte ici
    r.host.listed = Issues(items=(Issue(number=9, state="open", title="<i>Le scan</i> plante", body=LURE,
                                         author="netfan42", labels=("bug",), at=5),))
    r.host.talks[9] = (Remark(id=2, issue=9, author="netfan42", body="Toujours là ?", at=6),)
    append(r.client, r.live, [tracker.adding(_project(r.live, r.pid), c.TICKETS, "issue-9", "Le scan plante",
                                             text=LURE, proposed=True, author=c.BY_HOST, issue=9)], "projects")
    issues = _raw(r, "&vue=issues&issue=9")
    drawn(r.client, FICHE.format(r.pid) + "&vue=issues&issue=9")
    assert "&lt;i&gt;Le scan&lt;/i&gt; plante" in issues and "<i>Le scan</i>" not in issues
    assert "inconnu" in issues and "Toujours là ?" in html.unescape(issues)
    accept = form_of(issues, "projects.ticket_trancher", "accept")
    assert _post(r, accept, "projects.ticket_trancher").status_code == 303
    # CI : par commit ; l'échec dit la fin de son journal, cité tel quel
    r.host.checked[r.head] = Checks(sha=r.head, state=CHECKS_FAILED, runs=(CheckRun("pytest", CHECKS_FAILED, 1, 9),))
    checks = _raw(r, f"&vue=ci&sha={r.head}&frais=1")
    assert "La fin du journal" in checks and "FAILED tests/test_scan.py" in checks
    assert html.escape(LURE, quote=False) in checks or LURE in html.unescape(checks)


def test_the_ticket_an_issue_proposes_is_dismissed_from_the_issue(repo):
    """ADR 0297 : « Écarter », depuis l'issue d'un inconnu, est le geste du ticket lui-même, avec sa raison."""
    r = repo
    r.host.listed = Issues(items=(Issue(number=10, state="open", title="Ajouter IPv6", body="Merci", author="netfan42",
                                         at=5),))
    append(r.client, r.live, [tracker.adding(_project(r.live, r.pid), c.TICKETS, "issue-10", "Ajouter IPv6",
                                             text="Merci", proposed=True, author=c.BY_HOST, issue=10)], "projects")
    page = _raw(r, "&vue=issues&issue=10")
    drawn(r.client, FICHE.format(r.pid) + "&vue=issues&issue=10")
    dismiss = form_of(page, "projects.ticket_trancher", "dismiss")
    assert "Écarter le ticket" in html.unescape(page) and 'name="reason"' in _zone(page, "Écarter le ticket", "</form>")
    sent = _post(r, dismiss, "projects.ticket_trancher", reason="Hors du périmètre de l'outil.")
    assert sent.status_code == 303
    after = drawn(r.client, sent.headers["location"])
    assert "écarté" in after
    item = r.client.portal.call(lambda: tracker.entry(r.live.kernel.mind.store, r.pid, c.TICKETS, "issue-10")).item
    assert item.closed == c.DROPPED


def test_a_pull_request_only_proposed_reads_by_its_objective(repo):
    """ADR 0297 : une pull request seulement proposée (elle attend ton accord dans « À valider ») n'a pas de numéro :
    elle s'adresse par son objectif (``pr=o<n>``), sans « Fusionner »."""
    r = repo
    other = next(o.id for o in _project(r.live, r.pid).objectives if o.id != r.oid and o.kind == c.ONCE)

    async def propose():
        return await r.live.kernel.mind.append([rt.EFFECT_PROPOSED.draft(
            capability=PULL_REQUEST_CAPABILITY, owner="projects", approval=True, context=f"project:{r.pid}",
            args_json=json.dumps({"project": r.pid, "objective": other, "branch": f"work/objective-{other}"}),
            summary=Content.of("Ouvrir une pull request", level=0))], emitter="runtime", correlation="pr-proposee")

    r.client.portal.call(propose)
    assert _project(r.live, r.pid).objectives[[o.id for o in _project(r.live, r.pid).objectives].index(other)] \
        .pull_proposal
    listed = _raw(r, "&vue=pulls")
    row = next(x for x in listed.split('<a class="pj-row')[1:] if f"pr=o{other}\"" in x).split("</a>", 1)[0]
    assert "proposée" in row and "n° " not in row  # pas encore de numéro
    page = _raw(r, f"&vue=pulls&pr=o{other}")
    drawn(r.client, FICHE.format(r.pid) + f"&vue=pulls&pr=o{other}")
    assert "proposée" in html.unescape(page) and 'action="/admin/action/projects.fusionner"' not in page


def test_the_host_is_read_through_a_kept_and_bounded_read(repo):
    r = repo
    calls: list[str] = []
    real = r.host.talk

    async def counted(url, number, *, pull=False):
        calls.append(f"talk {number}")
        return await real(url, number, pull=pull)

    r.host.talk = counted
    _raw(r, "&vue=pulls&pr=12")
    _raw(r, "&vue=pulls&pr=12")
    assert calls == ["talk 12"]  # gardée : la seconde page ne joint pas l'hôte
    _raw(r, "&vue=pulls&pr=12&frais=1")
    assert calls == ["talk 12", "talk 12"]  # « relire » la refait


def test_merge_is_offered_only_when_the_action_would_accept_it(repo):
    """La relecture adverse de C0 à C3 (2026-11-22) : dans le délai de grâce d'un envoi dont l'hôte ne dit encore
    aucune vérification (ADR 0292), la page disait pourquoi attendre mais bâtissait « Fusionner » quand même ; l'API
    répondait ``can: False``. La page lit la règle à son instant, comme l'API (``merge_refusal``)."""
    r = repo
    append(r.client, r.live, [CHECKS_SEEN.draft(project=r.pid, objective=r.oid, sha=r.head, state=CHECKS_NONE,
                                                **r.about)], "projects")
    page = html.unescape(_raw(r, "&vue=pulls&pr=12"))
    assert inspect_merge.BLOCK_WORDS[merge.UNCHECKED] in page and "disabled" in page
    assert 'action="/admin/action/projects.fusionner"' not in page
    pulled = r.get("/pulls")["items"][0]
    assert pulled["merge"]["can"] is False and pulled["merge"]["why"] == inspect_merge.BLOCK_WORDS[merge.UNCHECKED]


def test_a_commit_keeps_its_page_and_days_follow_the_dates(repo, monkeypatch):
    """Choisir un commit d'une page plus ancienne garde cette page (la liste ne revient pas à la première) ; la liste
    se lit par jour, du plus récent, ses en-têtes dans l'ordre des dates ; « relire » ne relit l'hôte qu'une fois."""
    r = repo
    monkeypatch.setattr(inspect_code, "PAGE", 2)
    second = _raw(r, "&vue=commits&page_commits=2")
    rows = re.findall(r'<a class="pj-cm" href="([^"]+)"', second)
    assert rows and all("page_commits=2" in html.unescape(h) for h in rows)
    chosen = _raw(r, html.unescape(rows[-1]).split("?", 1)[1].replace("onglet=git", ""))
    assert re.search(r'<a class="pj-cm" href="[^"]+" aria-current="true"', chosen)  # le commit choisi est dans la liste
    assert "page 2 sur" in html.unescape(chosen) and "Plus récents" in html.unescape(chosen)  # la barre de pages
    assert "Plus anciens" in html.unescape(_raw(r, "&vue=commits"))  # (une macro importée la cachait)
    # les jours : chacun une fois, du plus récent au plus ancien
    monkeypatch.setattr(inspect_code, "PAGE", 30)
    days = re.findall(r'<p class="pj-day">([^<]+)</p>', _raw(r, "&vue=commits"))
    assert len(days) == len(set(days))
    # « relire » : le lien de la page porte son jeton ; suivi, il relit l'hôte, rechargé, plus
    calls: list[int] = []
    real = r.host.talk

    async def counted(url, number, *, pull=False):
        calls.append(number)
        return await real(url, number, pull=pull)

    r.host.talk = counted
    page = _raw(r, "&vue=pulls&pr=12")
    fresh = html.unescape(re.search(r'href="([^"]*frais=\d+[^"]*)"', page).group(1))
    assert "pr=12" in fresh and len(calls) == 1
    again = fresh.split("?", 1)[1].replace("onglet=git", "")
    _raw(r, again)
    _raw(r, again)  # la page rechargée
    assert len(calls) == 2
