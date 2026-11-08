"""L'accueil (``app/handmade/home.py``), à travers le vrai serveur : ce qui attend l'opératrice (une ligne par page
où décider), comment elle va, qui est là, la journée en chiffres et ses derniers épisodes ; il se relit seul. Et le
cadre qu'il partage avec toute la console (``base.html``) : la pastille de son état, le menu du compte."""

from __future__ import annotations

import html
import re
from types import SimpleNamespace

from mika.app.handmade import home
from mika.inspector.names import Names
from mika.inspector.pages import approvals as approvals_pages
from mika.inspector.pages import home as home_tabs
from mika.inspector.pages import system as system_pages
from mika.inspector.ui import UI
from mika.kernel.clock import MINUTE
from mika.kernel.forms import plural
from mika.kernel.inspect import Note, Ref, Stat, Stats, Swatch, Text, Vital
from mika.runtime import health
from tests.fixtures.console_html import ConsoleHTML
from tests.protocol.test_now_page import chat
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée


def test_only_an_operator_opens_the_home(world):  # noqa: F811
    client, _, _ = world
    for url in home.BASES:
        page = client.get(url, follow_redirects=False)
        assert page.status_code == 303 and page.headers["location"].endswith("/inspecteur/connexion"), url
    assert client.get(home.FRAGMENT).status_code == 401


def test_the_home_says_what_waits_how_she_is_and_what_she_did(world):  # noqa: F811
    client, _, _ = world
    bootstrap(client)
    chat(client, "salut, tu vas bien ?")
    page = client.get("/inspecteur/")
    assert page.status_code == 200
    ConsoleHTML(page.text).check()
    text = html.unescape(page.text)
    assert "<h1>Vue d'ensemble</h1>" in text and re.search(r'<a class="nav-item on" href="/inspecteur/"', text)
    assert " style=" not in text and not re.search(r"<script(?![^>]*\bsrc=)", text)
    assert "À regarder maintenant" in text and ", en ce moment</h2>" in text and "Qui est là" in text
    assert '<a href="/inspecteur/fiche/person/user_1">adrien</a>' in text  # en ligne, sur sa carte
    assert "réponses" in text and "Derniers épisodes" in text and "Comprendre le résultat" in text
    assert client.get("/inspecteur/accueil").status_code == 200
    fragment = client.get(home.FRAGMENT)
    assert fragment.status_code == 200 and "<h1" not in fragment.text and "data-now-stamp" in fragment.text


def test_her_state_and_her_needs_say_what_they_are(world):  # noqa: F811
    """« Mika, en ce moment » : son état est une valeur sous « État », pas une clé sans valeur ; ses besoins ont un
    titre et disent ce que mesure leur pourcentage (audit du 2026-11-05, C1-11)."""
    client, _, _ = world
    bootstrap(client)
    text = html.unescape(client.get("/inspecteur/").text)
    assert re.search(r"<dt>État</dt><dd>(éveillée|endormie)\b", text)
    assert "<dt>Éveillée</dt>" not in text and "<dt>Endormie</dt>" not in text
    needs = text.index('id="home-needs-title">Ses besoins</h3>')
    assert needs < text.index('<ul class="home-needs" aria-labelledby="home-needs-title">')
    assert "leur tension : elle monte vers 100 %" in text[needs:]


def test_the_attention_card_has_no_link_that_repeats_one_of_its_lines(world):  # noqa: F811
    """« Tout ce qui attend ta décision » doublait la ligne « À valider › Tout ce qui attend » (C1-10)."""
    client, _, _ = world
    bootstrap(client)
    text = html.unescape(client.get("/inspecteur/").text)
    card = text[text.index('<section class="now-card home-attention"'):]
    card = card[:card.index("</section>")]
    assert "Tout ce qui attend ta décision" not in card and 'class="now-more"' not in card


def priorities_of(page: str) -> list[tuple[str, str, str, str]]:
    """Les lignes de « À regarder maintenant » : ``(adresse, valeur, libellé, indice)``."""
    text = html.unescape(page)
    out = []
    for item in re.findall(r'<li class="st-\w+">(.*?)</li>', text.split('<ul class="home-priorities">', 1)[-1], re.S):
        href = re.search(r'<a href="([^"]+)"', item)
        value = re.search(r'<span class="home-priority-value now-num">(.*?)</span>', item, re.S)
        label = re.search(r"<strong>(.*?)</strong>(?:<span>(.*?)</span>)?", item, re.S)
        out.append((href.group(1) if href else "", value.group(1).strip(), label.group(1), label.group(2) or ""))
    return out


def test_a_failing_check_and_the_badge_of_its_page_make_one_line(world, monkeypatch):  # noqa: F811
    """Une même panne, une seule ligne (C1-02) : le contrôle de la file de sortie mène à sa page (« Système › File de
    sortie »), comme le badge de cette page, et la plus précise reste ; la santé générale, qui compte les contrôles
    qui ne vont pas, ne fait pas une ligne de plus. Avant : « Santé · File de sortie » vers la santé générale, puis
    « Système › File de sortie — à regarder »."""
    client, _, _ = world
    bootstrap(client)
    checks = tuple(health.Check(name, health.OK, "ok") for name in
                   ("journal", "slices", "loops", "projections", "processes", "llm", "lanes", "config", "ports"))
    report = health.Health("ready", (*checks, health.Check("outbox", health.DEGRADED, "2 abandonnés en 24 h")))
    monkeypatch.setattr(health, "report", lambda kernel: report)
    monkeypatch.setattr(system_pages, "_outbox_problems", lambda ui: 3)
    health_or_outbox = ("/inspecteur/systeme/sante", "/inspecteur/systeme/sorties")
    rows = priorities_of(client.get("/inspecteur/").text)
    assert [r for r in rows if r[0] in health_or_outbox] == [
        ("/inspecteur/systeme/sorties", "!", "Système › File de sortie", "2 abandonnés en 24 h")]
    # un contrôle qui n'a pas de page à lui mène à la santé générale, et dit lequel
    report = health.Health("ready", (*checks[:3], health.Check("projections", health.DEGRADED, "2 en retard"),
                                     *checks[4:]))
    monkeypatch.setattr(system_pages, "_outbox_problems", lambda ui: 0)
    rows = priorities_of(client.get("/inspecteur/").text)
    assert [r for r in rows if r[0] in health_or_outbox] == [
        ("/inspecteur/systeme/sante", "!", "Système › Santé générale", "Projections : 2 en retard")]


def test_the_total_of_the_queue_says_what_it_counts(world, monkeypatch):  # noqa: F811
    """« À valider › Tout ce qui attend » ne dit plus « à regarder » : ses onglets disent ce qu'il compte, et ce
    qu'aucun ne garde passe en « autres demandes » (C1-10)."""
    client, _, _ = world
    bootstrap(client)
    counts = {"": 6, "courriers": 3, "identites": 1}
    monkeypatch.setattr(approvals_pages, "_count", lambda ui, tab: counts.get(getattr(tab, "slug", ""), 0))
    rows = priorities_of(client.get("/inspecteur/").text)
    assert ("/inspecteur/approbations/en_attente", "6", "À valider › Tout ce qui attend",
            "courriers à envoyer : 3 · identités à confirmer : 1 · autres demandes : 2") in rows
    assert not [r for r in rows if r[0].startswith("/inspecteur/approbations/") and "en_attente" not in r[0]]
    assert UI._made_of([("Réponses Teams", 2)], 2) == "réponses Teams : 2"


def test_an_episode_toward_no_one_says_nothing_of_whom():
    """Une séance de travail ne s'adresse à personne : sa ligne ne dit plus « vers personne en particulier » (« — »,
    que la liste de l'accueil tait) ; « n'importe qui de présent » reste dit (C1-10)."""
    ui = SimpleNamespace(names=Names(SimpleNamespace()))

    def ended(target):
        return SimpleNamespace(at=1, correlation="c1", data=SimpleNamespace(
            kind="work", target=target, outcome="done", detail="", guard=""))

    assert home_tabs.episode_row(ui, ended(None)).cells[2] == Text("—", "muted")
    assert home_tabs.episode_row(ui, ended("none")).cells[2] == Text("—", "muted")
    assert home_tabs.episode_row(ui, ended("any")).cells[2] == Text("n'importe qui de présent", "muted")


def test_counts_agree_and_durations_are_read_not_in_seconds():
    """Plus de « (s) » ni de secondes brutes (C1-10) : le nom s'accorde au compte (le singulier jusqu'à 1), une
    attente se dit en minutes."""
    assert plural(0, "échec", "échecs") == "0 échec" and plural(1, "mail lu", "mails lus") == "1 mail lu"
    assert plural(2, "abandonné", "abandonnés") == "2 abandonnés" and plural(1200, "an", "ans") == "1 200 ans"
    now = 100 * MINUTE

    class Store:
        def query_mind(self, query):
            return [(7, "say", "boom"), (8, "say", "boom")]

        def get_events(self, seqs):
            return [SimpleNamespace(seq=s, at=now - (7 * MINUTE if s == 9 else MINUTE)) for s in seqs]

        def pending_outbox(self):
            return [SimpleNamespace(seq=9, effect="say", attempts=1, last_error="")]

    kernel = SimpleNamespace(mind=SimpleNamespace(store=Store(), clock=SimpleNamespace(now=lambda: now)))
    check = health._outbox(kernel)
    assert check.summary == "1 effet en attente, le plus vieux depuis 7 min ; 2 abandonnés en 24 h"
    assert check.detail[0].startswith("say (seq 9) : 1 tentative ")


def test_one_line_per_page_where_to_decide():
    """Un badge, son cadre et un contrôle de santé qui mènent à la même page font une seule ligne : la plus grave, et
    à gravité égale la plus précise ; « tout va bien » ne se dit que s'il n'y a rien."""
    processes = Ref("local", "/inspecteur/systeme/processus", "Processus")
    outbox = Ref("local", "/inspecteur/systeme/sorties", "File de sortie")
    got = home.priorities([
        Stats((Stat("Système › Processus", 1, "à regarder", "warn", processes),
               Stat("Processus en échec", 1, "Retenir (souvenirs, croyances)", "danger", processes),
               Stat("Système › File de sortie", 3, "à regarder", "warn", outbox),
               Stat("Système › Processus", "!", "1 processus en échec", "warn", processes),
               Stat("Système › File de sortie", "!", "2 abandonnés en 24 h", "warn", outbox))),
    ])
    assert [(r["value"], r["label"], r["sub"]) for r in got["rows"]] == [
        ("1", "Processus en échec", "Retenir (souvenirs, croyances)"),
        ("!", "Système › File de sortie", "2 abandonnés en 24 h")]
    assert got["calm"] is None
    calm = home.priorities([Note("Rien ne demande ton attention.", "ok", title="Tout va bien")])
    assert calm == {"rows": [], "calm": {"title": "Tout va bien", "text": "Rien ne demande ton attention."}}


def test_the_status_pill_says_her_feeling_and_names_her_energy(world):  # noqa: F811
    """La pastille d'état : son émotion en un mot, l'énergie nommée (« curieuse · énergie 53 % ») ; l'intensité de
    l'émotion reste dans le panneau des vitaux (C1-13). Le résumé relu toutes les 10 s dit la même chose."""
    client, _, _ = world
    bootstrap(client)
    felt = UI._vital("Humeur", Vital("curieuse (20 %)", ratio=0.2, swatch=Swatch("curieuse", "emotion", "curious", 0.2)))
    assert felt["short"] == "curieuse" and felt["text"] == "curieuse (20 %)"
    text = html.unescape(client.get("/inspecteur/").text)
    digest = re.search(r"data-status-digest>(.*?)</span>", text).group(1)
    assert re.fullmatch(r"(humeur au repos|[^·()]+) · énergie \d+ %", digest.replace(" ", " ")), digest
    vitals = html.unescape(client.get("/inspecteur/_vitals").text)
    assert f'data-digest="{digest}"' in vitals


def test_the_account_menu_leads_to_her_own_account(world):  # noqa: F811
    """Le menu du compte mène à sa fiche (« Mon compte » : son mot de passe, ses applications), pas seulement au
    thème et à la déconnexion (C1-15)."""
    client, _, _ = world
    bootstrap(client)
    text = html.unescape(client.get("/inspecteur/").text)
    menu = text[text.index('<div class="pop account-pop">'):]
    menu = menu[:menu.index("</details>")]
    mine = re.search(r'<a class="pop-row" href="([^"]+)">Mon compte</a>', menu)
    assert mine is not None and mine.group(1) == "/inspecteur/reglages/comptes?compte=1"
    assert menu.index("Mon compte") < menu.index('data-theme-set="auto"') < menu.index("Déconnexion")
    sheet = client.get(mine.group(1))
    assert sheet.status_code == 200 and "adrien" in sheet.text
