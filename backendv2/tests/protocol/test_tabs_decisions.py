"""Activité › Décisions, chaque onglet dans sa forme (``app/handmade/tabs/decisions.py``, ADR 0177), à travers le vrai
serveur : une ligne de l'arbitre se lit partout pareil (ce qui pousse face à ce qui retient, ce qui l'en empêche, ce
qui en sort) ; ses initiatives, ses choix, ses épisodes et ses échéances, chacun à sa place — et ce qu'ils disent,
vides. La table de l'arbitre est fixée (``Arbiter.rows``) : la vraie dépend de l'heure (la nuit, tout est bloqué)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from mika.app.handmade.tabs import decisions
from mika.contracts import runtime as rt
from mika.kernel.arbitration import Row, sigmoid
from mika.kernel.builtin import SELECTED, RowRecord
from mika.kernel.events import Content, VoiceProvenance
from mika.kernel.registry import ArbitrationPolicy
from mika.runtime.health import PROCESS_FAILURES_MAX
from mika.vocab.episodes import Kind
from tests.fixtures.mika import connect
from tests.protocol.test_console_diagnostics import stop
from tests.protocol.test_console_workflows import append
from tests.protocol.test_drawn_pages import drawn
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée

POLICY = ArbitrationPolicy(thresholds={Kind.INITIATIVE: 9.0, Kind.STEP: 8.0},
                           max_rates={Kind.INITIATIVE: 0.1, Kind.STEP: 1 / 120})


def _row(kind, target, parts, *, vetoes=(), shifts=(), threshold=9.0):
    score = sum(v for _, _, v in parts) + sum(v for _, v in shifts) - threshold
    hazard = 0.0 if vetoes else POLICY.max_rates[kind] * sigmoid(score)
    return Row(kind, target, tuple(parts), sum(v for _, v in shifts), tuple(vetoes), score, hazard,
               threshold=threshold, shifts=tuple(shifts))


#: une ligne qui l'emporte (Béa), une sous le seuil (Adrien), une bloquée par un veto, une sans cible
ROWS = [
    _row(Kind.INITIATIVE, "user_2", [("attention", "mail_to_tell", 12.0)]),
    _row(Kind.INITIATIVE, "user_1", [("attention", "mail_to_tell", 8.0), ("social", "presence", 0.0)],
         shifts=[("runtime", -1.0)]),
    _row(Kind.STEP, "goal:4", [("goals", "advance", 11.0)], vetoes=[("body", "asleep")], threshold=8.0),
    _row(Kind.INITIATIVE, "any", [("social", "presence", 1.0)]),
]


def _life(client, live, monkeypatch=None):
    """Une vie à l'arrêt où Adrien (le compte) et Béa sont connus ; la table de l'arbitre fixée."""
    bootstrap(client)
    stop(client, live.kernel)
    client.portal.call(connect, live.kernel, "user_1", "adrien")
    client.portal.call(connect, live.kernel, "user_2", "Béa")
    if monkeypatch is not None:
        monkeypatch.setattr(live.kernel.registry, "arbitration", POLICY)
        monkeypatch.setattr(live.kernel.arbiter, "rows", lambda frame, record=True: list(ROWS))
    return live.kernel, live.kernel.mind.clock.now()


def _entry(page: str, marker: str) -> str:
    """L'entrée de la liste (``<li …>`` … ``</li>`` de premier niveau) qui contient ``marker``."""
    start = page.rfind('<li class="arb-line', 0, page.index(marker))
    return page[start:page.index('</details>', page.index(marker)) + len('</details>')]


def test_the_arbiter_table_says_what_pushes_what_holds_back_and_what_comes_out(world, monkeypatch):  # noqa: F811
    client, live, _ = world
    _life(client, live, monkeypatch)
    page = drawn(client, "/inspecteur/decisions/maintenant")
    # d'abord la phrase : elle agirait, sur la ligne la plus probable (Béa : 12 points, 3 au-dessus du seuil)
    outlook = page.split('class="now-card arb-outlook"')[1].split("</section>")[0]
    assert "Elle agirait d’elle-même en moyenne dans" in outlook and "initiative envers Béa" in outlook
    assert "Comment elle décide" in outlook and "seuil <span class=\"now-num\">9,00</span>" in outlook
    lines = page.split('class="arb-lines"')[1]
    # la plus probable d'abord, puis celles sous le seuil, puis celles qu'un veto bloque
    assert lines.index("s-likely") < lines.index("s-under") < lines.index("s-blocked")
    likely = _entry(page, "Ce qui pousse l’emporte de 3,00")
    assert "Béa" in likely and "l'emporte" in likely
    under = _entry(page, "Il lui manque 2,00 pour l’emporter")
    assert "adrien" in under
    # ce qui pousse face à ce qui retient : la preuve, le réglage qui la freine, le seuil — et une raison sans poids
    pushes, holds = under.split('class="arb-side push"')[1].split('class="arb-side hold"')
    assert "+8,00" in pushes and "−1,00" in holds and "le seuil de cette sorte d'épisode" in holds and "−9,00" in holds
    assert "Là, mais sans poids" in under
    assert 'score <span class="now-num">−2,00</span>' in under
    # la barre : le vert (8 points) et le rouge (10) de part et d'autre de l'équilibre, au milieu
    widths = [float(w) for w in re.findall(r'<rect class="push" x="[\d.]+" y="1" width="([\d.]+)"', under)]
    assert widths and abs(widths[0] - 100 * 8 / 18) < 1
    assert '<line class="mid" x1="50" x2="50"' in under
    # bloquée : ce qui l'en empêche, et ce qui se passerait sans ce veto
    blocked = _entry(page, "sans cela, ce qui pousse l’emporterait de 3,00")
    assert "Ce qui l’en empêche" in blocked and "le but n° 4" in blocked and 'class="arb-tug vetoed"' in blocked
    # le calcul pas à pas, replié : chaque étape et son cumul, puis le score
    assert "Le calcul pas à pas" in under and "−2,00" in under.split('class="arb-steps"')[1]


def test_what_she_would_do_towards_someone_starts_with_a_choice_then_a_verdict(world, monkeypatch):  # noqa: F811
    client, live, _ = world
    _life(client, live, monkeypatch)
    empty = drawn(client, "/inspecteur/decisions/envers")
    pick = empty.split('class="now-card arb-pick"')[1]
    assert "Envers qui ?" in pick and "Choisis une personne" in pick
    assert re.search(r'class="hm-chip" href="/inspecteur/decisions/envers\?personne=user_1">adrien<', pick)
    nobody = drawn(client, "/inspecteur/decisions/envers?personne=Personne-de-ce-nom")
    assert "Personne ne correspond à « Personne-de-ce-nom »" in nobody and "arb-pick" in nobody
    page = drawn(client, "/inspecteur/decisions/envers?personne=adrien")
    verdict = page.split('class="now-card arb-verdict')[1].split("</section>")[0]
    assert "Envers adrien" in verdict and "Elle pourrait prendre la parole envers adrien" in verdict
    # ce qui pousse le plus (la preuve à +8), pas la première de la ligne (une raison sans poids)
    assert "Ce qui pousse le plus" in verdict and "(+8,00)" in verdict and "0,00" not in verdict
    mine = page.split("Ses lignes envers adrien")[1].split('class="arb-shared"')[0]
    assert "Il lui manque 2,00" in mine and "Béa" not in mine
    shared = page.split('class="arb-shared"')[1]
    assert "Ce qui vise n’importe qui de présent" in shared and "n'importe qui de présent" not in mine


def test_her_initiatives_show_her_budget_in_slots_and_whether_she_was_answered(world):  # noqa: F811
    client, live, _ = world
    kernel, _ = _life(client, live)
    voice = VoiceProvenance(call_id="test", persona_hash="fictive", role="initiative", model="fake")
    append(client, kernel, [rt.UTTERANCE.draft(kind=Kind.INITIATIVE, target="user_2", channel="web", voice=voice,
                                               text=Content.of("Coucou Béa, tu as pu te reposer ?"))])
    append(client, kernel, [rt.UTTERANCE.draft(kind=Kind.INITIATIVE, target="user_1", channel="web", voice=voice,
                                               text=Content.of("Tu as avancé sur l'écran titre ?"))])
    append(client, kernel, [rt.PERCEPTION_RECEIVED.draft(handle="user_1", channel="web",
                                                         text=Content.of("oui, presque fini !"))])
    page = drawn(client, "/inspecteur/decisions/initiatives")
    done, cap = (int(x) for x in re.search(r'class="now-num">(\d+) / (\d+)<', page).groups())
    assert page.count('class="ini-slot"') + page.count('class="ini-slot on"') == cap
    assert page.count('class="ini-slot on"') == done
    said = page.split('class="ini-said"')[1].split("</ol>")[0]
    answered = said.split("Tu as avancé sur l'écran titre ?")[0].rsplit("<li", 1)[1]
    waiting = said.split("Coucou Béa")[0].rsplit("<li", 1)[1]
    assert 't-ok' in answered and "répondue" in answered and "t-warn" in waiting
    assert "1 répondue" in page and "1 sans réponse" in page
    assert "Ses règles" in page and "Comptées ces 24 heures" in page


def test_her_choices_show_the_wheel_of_lines_and_the_chosen_one(world):  # noqa: F811
    client, live, _ = world
    kernel, _ = _life(client, live)
    empty = drawn(client, "/inspecteur/decisions/selections")
    assert "Elle n'a encore rien décidé d'elle-même" in empty
    rows = (
        RowRecord(kind=Kind.INITIATIVE, target="user_1", parts=(("attention", "mail_to_tell", 8.0),), shift=0.0,
                  vetoes=(), score=-1.0, hazard=0.0003, threshold=9.0),
        RowRecord(kind=Kind.INITIATIVE, target="user_2", parts=(("social", "presence", 1.5),), shift=0.0,
                  vetoes=(("agency", "awaiting_reply"),), score=-7.5, hazard=0.0, threshold=9.0),
        RowRecord(kind=Kind.MURMUR, target="none", parts=(("attention", "thought", 2.0),), shift=0.0, vetoes=(),
                  score=-2.0, hazard=0.0001),
    )
    append(client, kernel, [SELECTED.draft(rows=rows, fired=("INITIATIVE:user_1",), draw=0.3, candidates=3,
                                           bound=0.001, total=0.0004)], "kernel")
    page = drawn(client, "/inspecteur/decisions/selections")
    item = page.split('class="sel-item"')[1]
    assert "Elle a choisi :" in item.split('class="sel-draw"')[0] and "adrien" in item.split('class="sel-draw"')[0]
    assert "l’occurrence est acceptée" in item or "l'occurrence est acceptée" in item  # les mots de la console
    # la roue : la ligne choisie d'abord, à proportion de son taux (3 sur 4), puis l'autre ; la bloquée, nommée
    wheel = re.findall(r'<rect class="(on|off)" x="[\d.]+" y="1" width="([\d.]+)"', item)
    assert [c for c, _ in wheel] == ["on", "off"] and abs(float(wheel[0][1]) - 75) < 1
    assert "75 %" in item and "bloquée :" in item.split('class="sel-blocked"')[1]
    assert "Les 3 lignes au moment du choix" in item and item.count('class="arb-line ') == 3


def test_episodes_read_day_by_day_after_her_last_hours(world):  # noqa: F811
    client, live, _ = world
    kernel, _ = _life(client, live)
    for kind, outcome, detail in ((Kind.STEP, "done", "Les supports sont prêts."),
                                  (Kind.TASK, "failed", "Le service n’a pas répondu.")):
        append(client, kernel, [rt.EPISODE_ENDED.draft(kind=kind, outcome=outcome, detail=detail)])
    page = drawn(client, "/inspecteur/decisions/episodes")
    activity = page.split('class="now-card eps-activity"')[1].split("</section>")[0]
    assert "Ces dernières 24 heures" in activity and "échec" in activity and "Ses quatorze jours" in activity
    assert activity.count("<rect") == 14  # une barre par jour
    feed = page.split('class="eps-day-name">Aujourd\'hui</h3>')[1]
    failed = feed.split("Le service n’a pas répondu.")[0].rsplit("<li", 1)[1]
    assert 'class="failed"' in failed and "Tâche silencieuse" in failed
    assert feed.index("Le service n’a pas répondu.") < feed.index("Les supports sont prêts.")  # le plus récent d'abord
    assert "Comprendre le résultat" in feed and 'href="/inspecteur/episode/' in feed
    none = drawn(client, "/inspecteur/decisions/episodes?issue=cancelled")
    assert "Aucun épisode ne correspond" in none


def test_deadlines_are_ranged_by_horizon_and_what_fails_comes_first(world):  # noqa: F811
    client, live, _ = world
    kernel, _ = _life(client, live)
    sched = kernel.scheduler
    name = sched.specs[0].name
    sched.consecutive[name] = PROCESS_FAILURES_MAX
    page = drawn(client, "/inspecteur/decisions/echeances")
    assert re.search(r'class="now-num">\d+</span> processus', page) and "aucun ne tourne en ce moment" in page
    failing = page.split('class="now-card due-failing"')[1].split("</section>")[0]
    assert "Échouent d’affilée" in failing and f"{PROCESS_FAILURES_MAX} d'affilée" in failing
    groups = re.findall(r'class="due-group-head">([^<]+)<', page)
    order = ["Dans l'heure", "Plus tard aujourd'hui", "Plus tard", "Rien de prévu"]
    assert groups and [g.strip() for g in groups] == [o for o in order if o in [g.strip() for g in groups]]
    if "Rien de prévu" in page and len(groups) > 1:  # ce qui n'a rien de prévu se replie quand il y a autre chose
        assert '<details class="due-group h-never">' in page


def test_the_arbiter_pages_read_the_view_never_the_arbiter_nor_the_journal():
    """Table de l'arbitre, Que ferait-elle ?, Ses choix : leurs barres se tirent des lignes de la vue (leur calcul pas
    à pas, leurs colonnes repliées) ; le dessin ne touche ni à l'arbitre ni au journal."""
    tree = ast.parse(Path(decisions.__file__).read_text(encoding="utf-8"))
    touched = sorted({node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
                      and node.attr in ("arbiter", "older", "registry")})
    assert touched == []
