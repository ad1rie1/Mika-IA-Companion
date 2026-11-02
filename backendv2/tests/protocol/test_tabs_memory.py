"""Elle › Mémoire, chaque onglet dans sa forme (``app/handmade/tabs/memory.py``, ADR 0177), à travers le vrai serveur :
ce que chaque page met en avant, à sa place — la confiance d'une croyance, l'échéance d'une promesse, la date d'un
moment, ce qu'elle a lu d'une pièce, où en est la relecture — ; et ce qu'elle dit, vide."""

from __future__ import annotations

from mika.contracts import attachments, memory
from mika.contracts import runtime as rt
from mika.kernel.clock import DAY, HOUR
from mika.kernel.events import Content
from tests.fixtures.mika import connect
from tests.protocol.test_console_diagnostics import stop
from tests.protocol.test_console_workflows import append
from tests.protocol.test_drawn_pages import drawn
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée


def _life(client, live):
    """Une vie à l'arrêt (pas de relecture qui écrive pendant la lecture), où Alice est connue."""
    bootstrap(client)
    stop(client, live.kernel)
    client.portal.call(connect, live.kernel, "alice", "Alice")
    return live.kernel, live.kernel.mind.clock.now()


def _between(page: str, start: str, end: str = "") -> str:
    part = page.split(start, 1)[1]
    return part.split(end, 1)[0] if end else part


def test_a_belief_shows_its_trust_and_origin_and_a_replaced_one_fades(world):  # noqa: F811
    client, live, _ = world
    kernel, _ = _life(client, live)
    old = append(client, kernel, [memory.BELIEVED.draft(text=Content.of("Alice préfère le thé."), about=("alice",),
                                                        origin=memory.INFERRED, confidence=0.4)], "memory").seqs[0]
    append(client, kernel, [memory.BELIEVED.draft(text=Content.of("Alice préfère le café serré."), about=("alice",),
                                                  origin=memory.TOLD, source="alice", confidence=0.9, replaces=old)],
           "memory")
    page = drawn(client, "/inspecteur/memoire/croyances")
    new = _between(page, "Alice préfère le café serré.", "</li>")
    before = page.split("Alice préfère le café serré.")[0].rsplit("<li class=", 1)[1]
    # sa confiance d'abord, en chiffre et en jauge ; son origine et qui la lui a dite ; ce qu'elle remplace
    assert 'class="belief-trust-value now-num">0,90<' in before and "now-bar confidence" in before
    assert 'belief-origin o-told">on le lui a dit<' in new and "par Alice" in new
    assert f"/inspecteur/evenement/{old}" in _between(new, 'class="belief-replaces"', "</span>")
    replaced = page.split("Alice préfère le thé.")[0].rsplit("<li class=", 1)[1]
    assert "faded" in replaced and "0,40" in replaced
    assert "o-inferred" in _between(page, "Alice préfère le thé.", "</li>")
    # le numéro et l'importance, que la page ne montre pas, restent dans le détail
    assert "Informations complémentaires" in new and "importance" in new


def test_promises_that_bind_her_come_first_with_their_deadline_then_kept_and_dropped(world):  # noqa: F811
    client, live, _ = world
    kernel, now = _life(client, live)
    made = append(client, kernel, [
        memory.PROMISE_NOTICED.draft(text=Content.of("Envoyer la recette à Alice."), to="alice", due=now - 2 * HOUR),
        memory.PROMISE_NOTICED.draft(text=Content.of("Relire le dossier d'Alice."), to="alice", due=now + DAY),
        memory.PROMISE_NOTICED.draft(text=Content.of("Trouver un titre."), to="alice"),
        memory.PROMISE_NOTICED.draft(text=Content.of("Rappeler le libraire."), to="alice"),
    ], "memory").seqs
    append(client, kernel, [memory.PROMISE_RESOLVED.draft(promise=made[2], status=memory.HONORED),
                            memory.PROMISE_RESOLVED.draft(promise=made[3], status=memory.DROPPED)], "memory")
    page = drawn(client, "/inspecteur/memoire/promesses")
    engaged = _between(page, 'id="promises-open"', 'class="promises-done"')
    assert "Envoyer la recette" in engaged and "Relire le dossier" in engaged and "Trouver un titre" not in engaged
    late = engaged.split("Envoyer la recette")[0].rsplit("<li class=", 1)[1]
    assert "late" in late and "en retard" in late  # échue : elle le dit, à gauche
    assert "en retard" not in engaged.split("Relire le dossier")[0].rsplit("<li class=", 1)[1]
    assert "Trouver un titre" in _between(page, 'id="promises-kept"', "</section>")
    assert "Rappeler le libraire" in _between(page, 'id="promises-dropped"', "</section>")
    pending = drawn(client, "/inspecteur/memoire/promesses?status=pending")
    assert 'id="promises-open"' in pending and 'id="promises-kept"' not in pending


def test_the_lives_of_others_read_as_an_agenda(world):  # noqa: F811
    client, live, _ = world
    kernel, now = _life(client, live)
    noted = append(client, kernel, [
        memory.EVENT_NOTED.draft(text=Content.of("Le chat d'Alice est malade."), when=now - 3 * DAY, about=("alice",),
                                 ongoing=True),
        memory.EVENT_NOTED.draft(text=Content.of("Le vernissage d'Alice."), when=now + 9 * DAY, about=("alice",)),
        memory.EVENT_NOTED.draft(text=Content.of("L'examen d'Alice."), when=now + 2 * DAY, about=("alice",)),
        memory.EVENT_NOTED.draft(text=Content.of("L'entretien d'Alice."), when=now - DAY, about=("alice",)),
        memory.EVENT_NOTED.draft(text=Content.of("L'anniversaire d'Alice."), when=now + 20 * DAY, about=("alice",),
                                 yearly=True, festive=True),
    ], "memory").seqs
    append(client, kernel, [memory.RESOLVED.draft(event=noted[3], outcome=memory.HAPPENED, by="alice")], "memory")
    page = drawn(client, "/inspecteur/memoire/moments")
    assert page.index('id="moments-current"') < page.index('id="moments-ahead"') < page.index('id="moments-past"')
    assert "Le chat d'Alice" in _between(page, 'id="moments-current"', 'id="moments-ahead"')
    ahead = _between(page, 'id="moments-ahead"', 'id="moments-past"')
    # ce qui vient, le plus proche d'abord ; ce qui revient chaque année et se fête le dit
    assert ahead.index("L'examen") < ahead.index("Le vernissage") < ahead.index("L'anniversaire")
    assert "revient chaque année" in ahead and "se fête" in ahead
    past = _between(page, 'id="moments-past"')
    assert "L'entretien d'Alice" in past and "a eu lieu" in past
    day = kernel.mind.frame().local(now + 2 * DAY)
    exam = ahead.split("L'examen")[0].rsplit("<li class=", 1)[1]
    assert f'moment-day-n now-num">{day.day}<' in exam


def test_a_moment_long_past_still_says_how_it_turned_out(world):  # noqa: F811
    """Un moment passé depuis longtemps sort de la mémoire de travail de la faculté (sa tranche) au moment suivant
    qu'elle note ; l'archive le garde, issue comprise : la vue le dit, et l'onglet aussi."""
    client, live, _ = world
    kernel, now = _life(client, live)
    old = append(client, kernel, [memory.EVENT_NOTED.draft(text=Content.of("Le concert d'Alice."), when=now - 20 * DAY,
                                                           about=("alice",))], "memory").seqs[0]
    append(client, kernel, [memory.RESOLVED.draft(event=old, outcome=memory.CANCELLED, by="alice")], "memory")
    append(client, kernel, [memory.EVENT_NOTED.draft(text=Content.of("Le déménagement d'Alice."), when=now + DAY,
                                                     about=("alice",))], "memory")
    assert old not in kernel.mind.frame().state("memory").events  # hors de la tranche : seule l'archive le sait
    past = _between(drawn(client, "/inspecteur/memoire/moments"), 'id="moments-past"')
    concert = next(li for li in past.split("<li class=") if "Le concert d'Alice" in li)
    assert "annulé" in concert


def test_received_pieces_show_what_she_read_and_their_place(world):  # noqa: F811
    """Les pièces et la place de chacun sur une même page, en sous-onglets (ADR 0182) ; l'ancienne adresse de la
    place y mène, ouverte sur elle."""
    client, live, _ = world
    kernel, now = _life(client, live)
    message = append(client, kernel, [rt.PERCEPTION_RECEIVED.draft(handle="alice", channel="web", addressed=True,
                                                                   text=Content.of("Regarde !"))]).seqs[0]
    known = append(client, kernel, [memory.REMEMBERED.draft(text=Content.of("Alice expose ses dessins."),
                                                             about=("alice",), sources=(message,))], "memory").seqs[0]
    append(client, kernel, [
        attachments.KEPT.draft(file="a" * 32, message=message, handle="alice", name=Content.of("affiche.png"),
                               mime="image/png", size=480_000, kind=attachments.IMAGE, read=True, about=("alice",),
                               seen=Content.of("Une affiche violette pour une exposition.")),
        attachments.KEPT.draft(file="b" * 32, message=message, index=2, handle="alice", name=Content.of("vocal.ogg"),
                               mime="audio/ogg", size=80_000, kind=attachments.AUDIO, about=("alice",)),
    ], "attachments")
    append(client, kernel, [attachments.LINKED.draft(file="a" * 32, item=known)], "attachments")
    page = drawn(client, "/inspecteur/memoire/recues")
    poster = _between(page, "affiche.png", "</li>")
    assert "Une affiche violette pour une exposition." in _between(poster, "piece-seen", "</div></div>")
    assert "relié à 1 élément" in poster and "onglet=liens" in poster and "/inspecteur/telecharger/piece/" in poster
    voice = _between(page, "vocal.ogg", "</li>")
    assert "gardée, pas lue" in voice and "Rien n’a pu en être lu" in voice
    assert 'class="memories-item piece k-image' in page and 'class="memories-item piece k-audio' in page
    assert 'class="hm-subtabs" data-subtabs' in page and 'href="#pieces-list"' in page and 'href="#pieces-place"' in page
    place = _between(page, 'id="pieces-place"')
    row = _between(place, 'class="place-row', "</li>")
    assert "Alice" in row and "now-bar place" in row and "2 pièces" in row and "onglet=pieces" in row
    assert "Place de chacun" in page and "2,00 Go" in page
    moved = client.get("/inspecteur/memoire/place", follow_redirects=False)
    assert moved.status_code == 301 and moved.headers["location"] == "/inspecteur/memoire/recues#pieces-place"


def test_seeing_ahead_scales_her_expectations_and_who_keeps_their_word(world):  # noqa: F811
    client, live, _ = world
    kernel, now = _life(client, live)
    noted = append(client, kernel, [
        memory.EVENT_NOTED.draft(text=Content.of("Le concert d'Alice."), when=now - DAY, about=("alice",)),
        memory.EVENT_NOTED.draft(text=Content.of("Le salon d'Alice."), when=now - DAY, about=("alice",)),
    ], "memory").seqs
    append(client, kernel, [
        memory.RESOLVED.draft(event=noted[0], outcome=memory.HAPPENED, by="alice", likelihood=0.9,
                              nature=memory.FIRST_HAND, teller="alice"),
        memory.RESOLVED.draft(event=noted[1], outcome=memory.CANCELLED, by="alice", likelihood=0.9,
                              nature=memory.FIRST_HAND, teller="alice"),
    ], "memory")
    page = drawn(client, "/inspecteur/memoire/voir-venir")
    expected = _between(page, 'id="ahead-expected"', 'id="ahead-tellers"')
    # (0,9 − 1)² et (0,9 − 0)² : 0,41 en moyenne, au-delà de pile ou face
    assert "de la bouche de la personne" in expected and "0,410" in expected and 'ahead-scale danger' in expected
    assert "pile ou face" in expected and "sur <span class=\"now-num\">2</span> moments constatés" in expected
    tellers = _between(page, 'id="ahead-tellers"')
    assert "alice" in tellers.casefold() and "ahead-split" in tellers and 'x2="50.0"' in tellers  # 1 tenu sur 2


def test_consolidation_says_where_rereading_is_and_a_page_opens_its_subtab(world):  # noqa: F811
    client, live, _ = world
    kernel, _ = _life(client, live)
    source = append(client, kernel, [rt.PERCEPTION_RECEIVED.draft(handle="alice", channel="web", addressed=False,
                                                                  text=Content.of("Un message à relire."))]).seqs[0]
    append(client, kernel, [memory.EXTRACTION_DEFERRED.draft(key=source, messages=(source,), status="review",
        attempts=3, failure_code="provider_error", detail=Content.of("Le modèle n'a pas répondu."))], "memory")
    page = drawn(client, "/inspecteur/memoire/consolidation")
    assert "Rien n’est encore relu" in _between(page, 'class="consol-lede"', "</p>")
    band = _between(page, 'class="person-tiles-list"', "</ul>")
    assert 'href="/inspecteur/memoire/souvenirs"' in band and "À reprendre" in band
    assert '<li class="warn">' in band  # un passage à reprendre : la bande le signale
    queue = _between(page, 'id="consol-queue"', 'id="consol-runs"')
    assert "Erreur du fournisseur" in queue and "3 essais" in queue and "Reprendre cette extraction" in queue
    assert 'href="#consol-queue" class="warn"' in page
    panes = drawn(client, "/inspecteur/memoire/consolidation?avant=1").split('class="hm-subpanes"')[1]
    assert panes.index('id="consol-runs"') < panes.index('id="consol-queue"')


def test_a_new_memory_says_each_tab_is_empty(world):  # noqa: F811
    client, live, _ = world
    _life(client, live)
    for tab, says in (("croyances", "pas encore de croyance."), ("promesses", "pas encore de promesse."),
                      ("moments", "pas encore de moment noté."), ("recues", "aucune pièce reçue."),
                      ("recues", "aucune pièce gardée."), ("voir-venir", "aucun moment constaté encore."),
                      ("consolidation", "pas encore de relecture.")):
        page = drawn(client, f"/inspecteur/memoire/{tab}")
        assert f'data-tab="memoire/{tab}"' in page and says in page, tab
