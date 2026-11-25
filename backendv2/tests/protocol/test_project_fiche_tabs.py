"""La fiche d'un projet calquée sur l'écran Projets (ADR 0297), et la page d'ensemble (ADR 0281), à travers le vrai
serveur, sur la chaîne d'exemple de l'aperçu (``app/domains/projects/demo.py`` : un produit, un projet qui le lit, des
tickets à chaque étape où la main est au propriétaire, un point d'arrêt dit prêt, une liste à sa charge, un plan sans
réponse).

- sa barre : Vue d'ensemble, Objectifs, Tickets, Code, Documentation, Activité, Dépendances, Listes (seulement s'il a
  une liste), Administration ; plus de « Plus » ; les adresses d'avant (ses fichiers, ses décisions, son carnet, ses
  accès) mènent à la section de l'onglet qui les porte ;
- son cadre : le contenu de l'onglet sur toute la largeur, sans liste des projets — un onglet en liste et détail pose
  sa propre liste (``test_project_fiche_zones.py`` garde Objectifs, Tickets et Listes) ;
- sa Vue d'ensemble, sans panneau : ce qui attend quelqu'un, chaque ligne menant là où elle se règle, ses objectifs et
  leurs jalons en barres, son code, ses tickets par étape, ses missions ; elle ne porte aucun formulaire d'un autre
  onglet ;
- Dépendances, Administration et Code montrent ce que leurs lots avaient posé ;
- l'inventaire : aucune action de la fiche n'a disparu, et chacune est là où il le dit ;
- la page d'ensemble : « À faire » pour tous les projets, ce qui attend dans chacun, les liens entre projets.
"""

from __future__ import annotations

import html
import re

from mika.app.domains.projects.demo import chain
from mika.contracts import projects as c
from mika.kernel.events import Content
from mika.kernel.forms import Upload
from mika.runtime.operations import perform
from tests.protocol.test_console_workflows import append
from tests.protocol.test_drawn_pages import drawn
from tests.protocol.test_tabs_projects import _create, _life
from tests.protocol.test_web import world  # noqa: F401 — fixture partagée

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
FICHE = "/admin/fiche/project/{}"


def _chain(client, live) -> tuple[object, int, int]:
    """La chaîne d'exemple : le produit (n° ``pid``) et le projet qui le lit (n° ``rid``)."""
    kernel = _life(client, live)
    pid = _create(client, kernel, "Outils réseau", "Créer un module RDP\nÉcrire sa documentation")
    rid = _create(client, kernel, "Faire connaître Outils réseau", "Écrire la page d'accueil")
    client.portal.call(lambda: chain(kernel, str(pid), str(rid)))
    return kernel, pid, rid


def _tab(client, pid: int, name: str, more: str = "") -> str:
    page = drawn(client, FICHE.format(pid) + f"?onglet={name}{more}")
    assert "Cette vue a échoué" not in page and "Action non déclarée" not in page, name
    return page


def _do(client, kernel, pid: int, action: str, nonce: str, **values: str) -> None:
    posted = {"_champs": list(values), **{k: [v] for k, v in values.items()}}
    got = client.portal.call(lambda: perform(kernel, f"projects.{action}", posted, by="user_1", subject=str(pid),
                                             nonce=nonce))
    assert got.ok, got


def _bar(page: str) -> list[str]:
    """Les onglets de la barre de la fiche, dans l'ordre, sans leurs comptes."""
    nav = re.search(r'<nav class="tabs[^"]*".*?</nav>', page, re.S)
    assert nav, "pas de barre d'onglets"
    return [re.sub(r"\s*\d+$", "", " ".join(re.sub(r"<[^>]+>", " ", a).split()))
            for a in re.findall(r"<a\b.*?</a>", nav.group(0), re.S)]


def _actions(page: str) -> set[str]:
    """Les actions dont la page porte un formulaire."""
    return set(re.findall(r'action="/admin/action/(projects\.[a-z_]+)"', page))


#: la barre de la fiche, dans l'ordre et sous les noms de l'écran Projets (ADR 0297)
BAR = ["Vue d'ensemble", "Objectifs", "Tickets", "Code", "Documentation", "Activité", "Dépendances"]


def test_the_fiche_follows_the_projects_screen(world):  # noqa: F811
    client, live, _ = world
    _, pid, rid = _chain(client, live)
    page = _tab(client, pid, "apercu")
    # le produit n'a pas de liste de suivi : « Listes » n'est pas dans sa barre ; le projet qui le lit en a une
    assert _bar(page) == [*BAR, "Administration"]
    assert _bar(_tab(client, rid, "apercu")) == [*BAR, "Listes", "Administration"]
    assert "tabs-more" not in page and "Où il en est</a>" not in page and ">Cadre</a>" not in page
    # ses onglets comptent ce qu'ils montrent : ses objectifs ouverts (ponctuels et missions, ce que montre
    # « Ouverts » ; l'écran ne compte que les ponctuels), ses tickets ouverts
    nav = page.split('<nav class="tabs"', 1)[1].split("</nav>", 1)[0]
    opened = re.search(r'>Ouverts<span class="pj-cnt">(\d+)<', _tab(client, pid, "objectifs")).group(1)
    assert f'Objectifs<span class="tab-n now-num">{opened}</span>' in nav and 'Tickets<span class="tab-n now-num">4</span>' in nav
    # la fiche s'ouvre sur sa vue d'ensemble, sur toute la largeur : ni liste des projets ni panneau « Infos » — on
    # revient aux projets par le fil d'Ariane, comme l'écran par « ‹ Projets »
    opened = drawn(client, FICHE.format(pid))
    assert 'data-tab="project/apercu"' in opened and 'class="pj-cadre"' in opened
    assert 'class="pj-list"' not in opened and 'class="pj-side"' not in opened and 'class="pj-row' not in opened
    assert ">Projets</a>" in opened.split('<nav class="crumbs"', 1)[1].split("</nav>", 1)[0]
    assert "style=" not in opened.split('class="pj-cadre"', 1)[1]  # la CSP : ni largeur ni couleur en ligne
    # un onglet en liste et détail pose ses trois zones, avec sa liste à lui ; les autres prennent la largeur
    assert 'aria-label="Ses tickets"' in _tab(client, pid, "tickets")
    assert 'aria-label="Ses objectifs"' in _tab(client, pid, "objectifs")
    assert 'class="pj-list"' not in _tab(client, pid, "liens") + _tab(client, pid, "comportement")
    assert 'aria-label="Ses pages"' in _tab(client, pid, "documentation")  # Documentation › Pages : sa liste à elle
    # hors de la barre, l'adresse de ses listes marche toujours, et l'onglet ouvert y reprend sa place
    assert _bar(_tab(client, pid, "suivi")) == [*BAR, "Listes", "Administration"]
    # les adresses d'avant mènent à ce qui les a remplacées (ADR 0297) : une section, ou un sous-onglet en adresse
    for old, host, view in (("fichiers", "git", ""), ("decisions", "documentation", "decisions"),
                            ("carnet", "executions", "carnet"), ("acces", "comportement", "")):
        moved = client.get(FICHE.format(pid) + f"?onglet={old}&statut=toutes", follow_redirects=False)
        assert moved.status_code == 303, old
        assert f"onglet={host}" in moved.headers["location"] and "statut=toutes" in moved.headers["location"]
        assert moved.headers["location"].endswith(f"#{old}") and (not view or f"vue={view}" in moved.headers["location"])
        assert f'id="{old}"' in _tab(client, pid, host, f"&vue={view}" if view else "")
    assert client.get(FICHE.format(pid) + "?onglet=objectifs", follow_redirects=False).status_code == 200


def test_the_overview_says_what_awaits_and_where_it_stands_in_cards(world):  # noqa: F811
    client, live, _ = world
    _, pid, rid = _chain(client, live)
    page = _tab(client, pid, "apercu")
    waiting = page.split('class="pj-card pj-atoi"', 1)[1].split("</section>", 1)[0]
    assert '<b class="now-num">4</b>' in waiting and "choses attendent quelqu'un" in waiting
    # ce qui attend, dans l'ordre où s'en occuper : les tickets dont la main est à toi, puis le point d'arrêt ; les
    # trois premières en vue, le reste replié sur place
    said = re.findall(r'<b class="pj-wait-text"[^>]*>(.*?)</b>', waiting, re.S)
    assert [s.split(" — ")[0] for s in said] == [
        "#2 Exporter la liste des hôtes en CSV", "#3 Quel port par défaut pour RDP ?",
        "#4 Journaliser les connexions refusées", "Objectif n° 1, jalon n° 2"]
    assert "proposé : à accepter ou à écarter" in said[0] and "elle te pose une question" in said[1]
    assert "son plan attend ta validation" in said[2] and "elle le dit prêt" in said[3]
    assert "et 1 de plus" in waiting and waiting.index("et 1 de plus") < waiting.index("Objectif n° 1, jalon n° 2")
    # chaque ligne mène là où elle se règle : l'onglet ouvert sur l'objet
    go = re.findall(r'<a class="pj-mini" href="([^"]+)".*?<span class="pj-go">(.*?)<svg', waiting, re.S)
    assert {text.strip(): href.split("?", 1)[1] for href, text in go} == {
        "Accepter ou écarter": "onglet=tickets&element=%232", "Répondre": "onglet=tickets&element=%233",
        "Valider ou refuser son plan": "onglet=tickets&element=%234", "Valider ou refuser": "onglet=objectifs"}
    for href, _ in go:  # et ce lien ouvre bien l'objet, avec son geste
        assert client.get(href).status_code == 200
    opened = _tab(client, pid, "tickets", "&element=%234")
    assert "Journaliser les connexions refusées" in opened and "projects.ticket_trancher" in _actions(opened)
    # ses objectifs : leurs jalons en une barre, un segment par jalon — le point d'arrêt dit prêt est « à toi »
    goals = page.split('aria-label="Objectifs"', 1)[1].split("</section>", 1)[0]
    rdp = goals.split("Créer un module RDP", 1)[1].split("</a>", 1)[0]
    assert "0 sur 2 terminés" in goals and "0 / 2 jalons" in rdp
    assert re.findall(r"<i(?: class=\"(\w+)\")?></i>", rdp) == ["", "you"]
    # ses tickets par étape : une barre empilée en SVG, et sa légende
    tickets = page.split('aria-label="Tickets"', 1)[1].split("</section>", 1)[0]
    assert "4 ouverts" in tickets and '<svg viewBox="0 0 4 10"' in tickets
    assert re.findall(r"<li[^>]*><i class=\"e\d\"></i>([^<]+)<b>(\d+)</b>", tickets) == [
        ("Non lu", "2"), ("En analyse", "1"), ("Validation", "1"), ("Pull request", "0"), ("Fusion", "0"),
        ("Traité", "0")]
    # son prochain passage et ses missions ; ses dépendances ; ses dernières exécutions
    coming = page.split('aria-label="Prochain passage"', 1)[1].split("</section>", 1)[0]
    assert "Garder les tests verts" in coming and "toutes les 24 h" in coming and ">Régler</a>" in coming
    deps = page.split('aria-label="Dépendances"', 1)[1].split("</section>", 1)[0]
    assert "Dépendent de lui" in deps and "Faire connaître Outils réseau" in deps and "aucun projet" in deps
    assert "Aucune exécution encore." in page.split('aria-label="Dernières exécutions"', 1)[1].split("</section>")[0]
    # plus de panneau « Infos » : son rythme est sur « Prochain passage », son dépôt et ses vérifications sur
    # « Code », et son plan — qui n'attend rien — en une ligne sur « Objectifs », qui y mène
    assert 'class="pj-side"' not in page and 'class="pj-card pj-plan' not in page
    assert "Son plan : " in goals and "onglet=objectifs&plan=1" in goals
    assert "les jours" in coming or "à toute heure" in coming or 'class="pj-consigne"' in coming
    # la vue d'ensemble mène aux onglets : aucun de leurs formulaires n'y est
    assert _actions(page.split('class="pj-vue"', 1)[1]) == set()
    # le projet qui le lit : son plan attend, en carte, en tête ; sa mission dit ce qui la déclenche ; sa liste est
    # à ta charge
    reader = _tab(client, rid, "apercu")
    plan = reader.split('class="pj-card pj-plan you"', 1)[1].split("</section>", 1)[0]
    assert reader.index('class="pj-card pj-plan you"') < reader.index('class="pj-grid"')
    assert {"projects.plan_valider", "projects.plan_reviser"} <= _actions(plan)
    waits = reader.split('class="pj-card pj-atoi"', 1)[1].split("</section>", 1)[0]
    assert "Son plan attend une réponse" in waits and "Lire son plan et répondre" in waits
    assert '<b class="now-num">6</b>' in waits and "2 autres éléments" in waits  # six attentes, en cinq lignes
    assert "Acme Réseaux (liste « entreprises »)" in waits and "Ouvrir la liste" in waits
    coming = reader.split('aria-label="Prochain passage"', 1)[1].split("</section>", 1)[0]
    assert "Garder le site cohérent avec le produit" in coming and "tous les 2 jours" in coming
    assert f"la base du projet n° {pid} qui avance" in coming  # ce qui la déclenche, en plus de sa cadence
    assert "Il dépend de" in reader and "Outils réseau</a>" in reader.split('aria-label="Dépendances"', 1)[1]
    # un projet qui avance seul le dit sur sa carte, en vert
    kernel = live.kernel
    alone = _create(client, kernel, "Seul", "Écrire")
    quiet = _tab(client, alone, "apercu")
    assert 'class="pj-card pj-atoi rien"' in quiet and "rien n'attend personne : il avance seul" in quiet


def test_dependencies_administration_and_code_show_what_their_lots_had_put(world):  # noqa: F811
    client, live, _ = world
    kernel, pid, rid = _chain(client, live)
    # ── Dépendances : ce qu'il lit et ce que le lien donne, ce qu'il a demandé ; chez le projet lu, ce qu'on lui a
    # demandé
    links = _tab(client, rid, "liens")
    assert 'data-tab="project/liens"' in links and "Il dépend de" in links and "Outils réseau" in links
    assert "Ce que le lien lui donne" in links and "Ses demandes" in links and "Dépendent de lui" in links
    assert "projects.liens" in _actions(links)
    asked = _tab(client, pid, "liens", "&vue=demandes")
    assert "Exporter la liste des hôtes en CSV" in asked and "de « Faire connaître Outils réseau »" in asked
    assert "Faire connaître Outils réseau" in _tab(client, pid, "liens")  # qui le lit
    # ── Administration : ses réglages, ses outils, ses accès, ses tickets, sous le capot — chacun dans son
    # sous-onglet, avec son formulaire ; les ancres d'avant valent toujours
    frame = _tab(client, pid, "comportement")
    assert 'data-tab="project/comportement"' in frame
    nav = frame.split('aria-label="Ce qui se règle"', 1)[1].split("</nav>", 1)[0]
    assert re.findall(r'<a href="#([a-z-]+)">', nav) == [
        "cadre-reglages", "cadre-outils", "acces", "cadre-tickets", "admin-capot"]
    assert re.findall(r"<b>([^<]+)</b>", nav) == ["Ses réglages", "Outils et services", "Accès", "Tickets et issues",
                                                 "Sous le capot", "Listes de suivi"]
    assert f'href="{FICHE.format(pid)}?onglet=suivi"' in nav  # il n'a pas de liste : de quoi en créer une
    assert "Listes de suivi" not in _tab(client, rid, "comportement").split('aria-label="Ce qui se règle"', 1)[1].split(
        "</nav>", 1)[0]
    assert {"projects.modifier", "projects.outils", "projects.acces", "projects.tickets_regler"} <= _actions(frame)
    tickets = frame.split('id="cadre-tickets"', 1)[1].split('id="admin-capot"', 1)[0]
    assert "validation du plan d'un ticket" in tickets and "toujours par toi" in tickets
    assert "3 fichiers et 40 lignes au plus" in tickets and "sans dépôt distant" in tickets
    assert "Relecture indépendante" in frame.split('id="cadre-reglages"', 1)[1].split('id="cadre-outils"', 1)[0]
    assert 'class="access-form"' in frame.split('id="acces"', 1)[1].split('id="cadre-tickets"', 1)[0]
    engine = frame.split('id="admin-capot"', 1)[1]
    assert all(said in engine for said in ("Pour le moteur", "Ses exécutions", "Son atelier", "numéro",
                                           "ce qui retient son exécution", "pannes d'affilée", "commit de sa base"))
    assert _actions(engine) == set()  # rien ne s'y règle
    # l'onglet Tickets n'a plus ce réglage : il y mène
    listed = _tab(client, pid, "tickets")
    assert "projects.tickets_regler" not in _actions(listed) and "les régler dans Administration" in listed
    # ── Code : ses sous-onglets de l'écran, des adresses (le détail : test_project_fiche_code.py) ; l'atelier face
    # au distant est la sous-vue « distant », et ne redit pas ses branches (Code › Branches)
    append(client, kernel, [c.RUN_REPORTED.draft(project=pid, objective=1, verdict=c.CONTINUE, commit="a" * 40,
                                                 branch="mika/objectif-1",
                                                 summary=Content.of("Le squelette est posé.", level=0))], "projects")
    git = _tab(client, pid, "git")
    bar = git.split('aria-label="Son code"', 1)[1].split("</nav>", 1)[0]
    assert re.findall(r'<a href="[^"]*"[^>]*>([^<]+)', bar) == ["Fichiers", "Commits", "Pull requests", "Branches",
                                                         "Issues", "CI"]
    assert 'id="fichiers"' in git and "vue=distant" in git
    remote = _tab(client, pid, "git", "&vue=distant")
    assert 'data-tab="project/git"' in remote and 'id="git-branches"' not in remote and 'id="git-reglages"' in remote
    # ── Documentation, Activité, Dépendances : leurs sous-onglets, des adresses (le détail :
    # test_project_fiche_docs.py, test_project_fiche_activity.py)
    for tab, label, names in (("documentation", "Sa documentation", ["Pages", "Images", "Décisions"]),
                              ("executions", "Son activité", ["Fil", "Exécutions", "Carnet"]),
                              ("liens", "Ses dépendances", ["Schéma", "Demandes"])):
        nav = _tab(client, pid, tab).split(f'aria-label="{label}"', 1)[1].split("</nav>", 1)[0]
        assert [re.sub(r"<[^>]+>.*", "", a) for a in re.findall(r"<a href=\"[^\"]*\"[^>]*>(.*?)</a>", nav)] == names
    decided = _tab(client, pid, "documentation", "&vue=decisions")
    assert re.findall(r"vue=decisions(?:&amp;|&)statut=(\w+)", decided.split('aria-label="Lesquelles"', 1)[1].split(
        "</nav>", 1)[0]) == [c.SUPERSEDED, c.WITHDRAWN, "toutes"]
    # la vue d'ensemble dit ce qui vient de se passer
    recent = _tab(client, pid, "apercu").split('aria-label="Dernières exécutions"', 1)[1].split("</section>", 1)[0]
    assert "Le squelette est posé." in recent and "continuer — objectif n° 1" in recent


#: L'inventaire (ADR 0281) : chaque action de la fiche d'un projet, et l'onglet qui porte son formulaire — « tête » :
#: la barre de titre, sur tous ses onglets ; une action ajoutée à la faculté doit y prendre sa place.
INVENTORY = {
    "projects.lancer": "tête", "projects.pause": "tête", "projects.reprendre": "tête", "projects.consigne": "tête",
    "projects.archiver": "tête", "projects.restaurer": "tête",
    "projects.plan_valider": "apercu", "projects.plan_reviser": "apercu",
    "projects.lancer_objectif": "objectifs", "projects.objectif_statut": "objectifs",
    "projects.objectif_modifier": "objectifs", "projects.objectif_ajouter": "objectifs",
    "projects.jalon_ajouter": "objectifs", "projects.jalon_trancher": "objectifs",
    "projects.jalon_modifier": "objectifs", "projects.jalon_retirer": "objectifs",
    "projects.ticket_ouvrir": "tickets", "projects.ticket_trancher": "tickets", "projects.element_noter": "tickets",
    "projects.ticket_modifier": "tickets", "projects.ticket_publier": "tickets", "projects.note_publier": "tickets",
    "projects.element_ajouter": "suivi", "projects.element_statut": "suivi", "projects.element_confier": "suivi",
    "projects.liste_regler": "suivi",
    "projects.liens": "liens",
    "projects.depot_distant": "git", "projects.pousser": "git", "projects.recuperer": "git",
    "projects.modifier": "comportement", "projects.outils": "comportement", "projects.acces": "comportement",
    "projects.tickets_regler": "comportement",
    "projects.decision_ajouter": "documentation", "projects.decision_statut": "documentation",
    "projects.decision_modifier": "documentation",
    "projects.deposer": "git",
    "projects.fusionner": "git",
    "projects.pull_modifier": "git", "projects.pull_commenter": "git",
    # ADR 0289, 0297 : sa documentation s'écrit aussi dans la console, par les mêmes actions
    "projects.doc_ecrire": "documentation", "projects.doc_deplacer": "documentation",
    "projects.doc_supprimer": "documentation", "projects.doc_image": "documentation",
    "projects.doc_image_retirer": "documentation",
}
#: ce que seul un état particulier montre, et que ce test ne monte pas : une issue chez l'hôte (publier une note),
#: un atelier qui a quelque chose à pousser, une pull request ouverte chez l'hôte (la fusionner, la modifier, y
#: répondre : test_project_fiche_code.py)
NOT_STAGED = {"projects.note_publier", "projects.pousser", "projects.fusionner", "projects.pull_modifier",
              "projects.pull_commenter"}


def test_no_action_of_the_fiche_was_lost(world):  # noqa: F811
    client, live, _ = world
    kernel, pid, rid = _chain(client, live)
    declared = {a.key for a in kernel.registry.actions.values() if a.subject == "project" and a.owner == "projects"}
    assert declared == set(INVENTORY), "une action de la fiche d'un projet n'a pas sa place dans l'inventaire"
    _do(client, kernel, pid, "decision_ajouter", "d1", title="Quel protocole ?", choice="RDP d'abord",
        reason="C'est ce qui est demandé.")
    _do(client, kernel, pid, "depot_distant", "r1", remote="https://github.com/exemple/outils-reseau.git",
        branch="main")
    _do(client, kernel, pid, "doc_ecrire", "doc-p1", path="accueil.md", text="# Outils réseau", base="0")
    got = client.portal.call(lambda: perform(kernel, "projects.doc_image", {}, by="user_1", subject=str(pid),
                                             nonce="doc-i1", files=(Upload(name="schema.png", data=PNG),)))
    assert got.ok, got
    decided = next(d.id for d in live.kernel.mind.frame().state("projects").projects[pid].decisions)
    pages = {
        "apercu": _tab(client, pid, "apercu") + _tab(client, rid, "apercu"),  # le plan : chez le projet qui en a un
        # un geste est là où l'on voit son objet : la liste, l'objet choisi, le formulaire ouvert dans le contenu
        "objectifs": _tab(client, pid, "objectifs", "&objectif=1&jalon=1") + _tab(client, pid, "objectifs", "&ajouter=1"),
        "tickets": _tab(client, pid, "tickets", "&nouveau=1") + _tab(client, pid, "tickets", "&element=%234")
        + _tab(client, pid, "tickets", "&element=%231"),
        "suivi": _tab(client, rid, "suivi", "&liste=entreprises&element=acme") + _tab(client, rid, "suivi", "&ajouter=1")
        + _tab(client, rid, "suivi", "&regler=1"),
        "liens": _tab(client, rid, "liens"),
        "git": _tab(client, pid, "git", "&deposer=1") + _tab(client, pid, "git", "&vue=distant"),
        "comportement": _tab(client, pid, "comportement"),
        # une page lue, une page écrite, ses images, une décision et ses gestes
        "documentation": _tab(client, pid, "documentation") + _tab(client, pid, "documentation", "&nouvelle=1")
        + _tab(client, pid, "documentation", "&vue=images&image=schema.png")
        + _tab(client, pid, "documentation", f"&vue=decisions&decision={decided}")
        + _tab(client, pid, "documentation", f"&vue=decisions&decision={decided}&geste=modifier")
        + _tab(client, pid, "documentation", "&vue=decisions&nouvelle=1"),
    }
    found = {tab: _actions(page) for tab, page in pages.items()}
    head = page_head(pages["tickets"])
    for action, tab in INVENTORY.items():
        if action in NOT_STAGED or action in ("projects.reprendre", "projects.restaurer"):
            continue
        assert action in (head if tab == "tête" else found[tab]), f"{action} manque sur {tab}"
    # … et chaque onglet d'avant garde ce qu'il montrait
    assert "Ce qu'elle a en main pendant une exécution" in pages["comportement"]
    assert "Quel protocole ?" in pages["documentation"] and "Déposer un fichier" in pages["git"]
    activity = _tab(client, pid, "executions", "&vue=carnet")
    assert 'data-tab="project/executions"' in activity
    assert all(pane in activity for pane in ("Consignes", "Ses notes", "Ce qu'on en a fait", "Ce qui sort"))
    # en pause, « Reprendre » ; archivé, « Restaurer »
    _do(client, kernel, pid, "pause", "p1")
    assert "projects.reprendre" in page_head(_tab(client, pid, "apercu"))
    _do(client, kernel, pid, "archiver", "a1")
    assert "projects.restaurer" in page_head(_tab(client, pid, "apercu"))


def page_head(page: str) -> set[str]:
    """Les actions de la barre de titre : ce que la page porte avant sa barre d'onglets."""
    return _actions(page.split('<nav class="tabs', 1)[0])


def test_the_overview_page_says_what_awaits_in_every_project_and_how_they_are_linked(world):  # noqa: F811
    client, live, _ = world
    _, pid, rid = _chain(client, live)
    page = drawn(client, "/admin/projets/tous")
    assert 'data-tab="projets/tous"' in page
    todo = page.split('class="now-card prj-todo"', 1)[1].split("</section>", 1)[0]
    assert "À faire" in todo and page.index("À faire") < page.index('class="prj-list"')  # en tête, avant la liste
    said = [html.unescape(s) for s in re.findall(r'<p class="prj-todo-text">(.*?)</p>', todo, re.S)]
    # le plan d'abord, puis les tickets, le point d'arrêt, enfin ce qui est à ta charge — chacun avec son projet
    assert said[0].startswith("Son plan attend une réponse") and said[1].startswith("#2 Exporter la liste")
    assert said[4].startswith("Objectif n° 1, jalon n° 2") and said[5] == "Acme Réseaux (liste « entreprises »)"
    assert "2 autres éléments" in said[-1]
    projects = re.findall(r'<span class="prj-todo-project">(.*?)</span>', todo, re.S)
    assert "Faire connaître Outils réseau" in projects[0] and "Outils réseau" in projects[1]
    assert f'href="{FICHE.format(pid)}?onglet=tickets&element=%232"' in todo
    assert "Voir les" in todo  # au-delà de six lignes, le reste se déplie : la page tient dans un écran
    # chaque projet dit combien de choses t'y attendent ; ses chiffres le comptent en tête
    rows = page.split('class="prj-list"', 1)[1]
    assert "t’attend : 4 choses" in rows and "t’attend : 6 choses" in rows
    assert page.index("T'attendent") < page.index("Actifs")
    # les liens entre projets : qui lit qui, ce que le lien donne, la demande en cours
    linked = page.split("Dépendances entre projets", 1)[1]
    assert "Faire connaître Outils réseau" in linked and "son titre, son état" in linked
    assert "1 demande en cours (en attente d'accord)" in linked
    assert f'href="{FICHE.format(pid)}?onglet=tickets&element=%232"' in linked
