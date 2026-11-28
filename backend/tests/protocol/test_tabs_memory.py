"""Elle › Mémoire, chaque onglet dans sa forme (``app/handmade/tabs/memory.py``, ADR 0177), à travers le vrai serveur :
ce que chaque page met en avant, à sa place — la confiance d'une croyance, l'échéance d'une promesse, la date d'un
moment, ce qu'elle a lu d'une pièce, où en est la relecture — ; et ce qu'elle dit, vide."""

from __future__ import annotations

import re
from dataclasses import replace

from mika.contracts import attachments, memory
from mika.contracts import runtime as rt
from mika.faculties.attachments import inspect as received_view
from mika.faculties.memory import inspect as memory_view
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
    page = drawn(client, "/admin/memoire/croyances")
    new = _between(page, "Alice préfère le café serré.", "</li>")
    before = page.split("Alice préfère le café serré.")[0].rsplit("<li class=", 1)[1]
    # sa confiance d'abord, en chiffre et en jauge ; son origine et qui la lui a dite ; ce qu'elle remplace
    assert 'class="belief-trust-value now-num">90\u202f%<' in before and "now-bar confidence" in before
    assert 'belief-origin o-told">on le lui a dit<' in new and "par Alice" in new
    assert f"/admin/evenement/{old}" in _between(new, 'class="belief-replaces"', "</span>")
    replaced = page.split("Alice préfère le thé.")[0].rsplit("<li class=", 1)[1]
    assert "faded" in replaced and "40\u202f%" in replaced
    assert "o-inferred" in _between(page, "Alice préfère le thé.", "</li>")
    # le numéro et l'importance, que la page ne montre pas, restent dans le détail
    assert "Informations complémentaires" in new and "importance" in new


def _card(page: str, text: str) -> str:
    """L'entrée d'une liste qui porte ce texte, de son ``<li`` à sa fin."""
    return next(li for li in page.split("<li class=")[1:] if text in li).split("</li>", 1)[0]


def test_what_she_held_before_fades_and_an_ended_situation_says_so_in_words(world):  # noqa: F811
    """Une situation finie dit « finie » une fois, jamais sa clé (« ended ») ; un élément d'avant s'estompe, quel
    qu'il soit (``FORMER_STATUSES`` : remplacé, fondu dans un autre, joint à un autre), et se retrouve par son
    statut."""
    client, live, _ = world
    kernel, now = _life(client, live)
    situation = append(client, kernel, [
        memory.EVENT_NOTED.draft(text=Content.of("Le déménagement d'Alice."), when=now - 3 * DAY, about=("alice",),
                                 ongoing=True),
        memory.EVENT_NOTED.draft(text=Content.of("Le stage d'Alice."), when=now - 2 * DAY, about=("alice",),
                                 ongoing=True)], "memory").seqs[0]
    append(client, kernel, [memory.SITUATION_ENDED.draft(event=situation)], "memory")
    card = _card(drawn(client, "/admin/memoire/moments"), "Le déménagement d'Alice.")
    assert card.count(">finie<") == 1 and "ended" not in card and "faded" not in card.split(">", 1)[0]
    ended = drawn(client, "/admin/memoire/moments?status=ended")
    assert "Le déménagement d'Alice." in ended and "Le stage d'Alice." not in ended and "inconnu" not in ended

    kept, joined = append(client, kernel, [
        memory.BELIEVED.draft(text=Content.of("Alice aime la randonnée."), about=("alice",), origin=memory.TOLD,
                              source="alice", confidence=0.8),
        memory.BELIEVED.draft(text=Content.of("Alice adore marcher en montagne."), about=("alice",),
                              origin=memory.TOLD, source="alice", confidence=0.7)], "memory").seqs
    append(client, kernel, [memory.JOINED.draft(night="2026-11-12", pairs=((kept, joined),), mute=True)], "memory")
    beliefs = drawn(client, "/admin/memoire/croyances")
    assert "faded" in _card(beliefs, "Alice adore marcher").split(">", 1)[0]
    assert "faded" not in _card(beliefs, "Alice aime la randonnée").split(">", 1)[0]
    found = drawn(client, "/admin/memoire/croyances?status=joined")
    assert "Alice adore marcher" in found and "Alice aime la randonnée" not in found and "inconnu" not in found
    assert "jointe à une autre" in _card(found, "Alice adore marcher")

    first, merged = append(client, kernel, [
        memory.REMEMBERED.draft(text=Content.of("Alice a gagné son tournoi d'échecs."), about=("alice",)),
        memory.REMEMBERED.draft(text=Content.of("Alice a gagné son tournoi d'échecs !"), about=("alice",))],
        "memory").seqs
    append(client, kernel, [memory.NIGHT_SORTED.draft(night="2026-11-12", merges=((first, merged),))], "memory")
    memories = drawn(client, "/admin/memoire/souvenirs")
    cards = [li for li in memories.split("<li class=")[1:] if "tournoi d'échecs" in li]
    assert len(cards) == 2 and sum("faded" in li.split(">", 1)[0] for li in cards) == 1
    assert "fondu dans un autre" in next(li for li in cards if "faded" in li.split(">", 1)[0])


def _select(page: str, name: str) -> str:
    """Le sélecteur d'un filtre, de son ``<select`` à sa fin."""
    return page.split(f'<select name="{name}">', 1)[1].split("</select>", 1)[0]


def test_a_filter_has_one_empty_choice_that_says_what_it_does(world):  # noqa: F811
    """Un sélecteur de filtre n'a qu'une option vide : aucune de plus quand ses choix en ont une (« toutes ») ;
    « Tous » sans défaut ; « Par défaut (…) » quand le filtre en a un."""
    client, live, _ = world
    _life(client, live)
    pieces = _select(drawn(client, "/admin/memoire/recues"), "sorte")
    assert pieces.count('<option value=""') == 1 and '<option value="" selected>toutes</option>' in pieces
    beliefs = drawn(client, "/admin/memoire/croyances")
    assert _select(beliefs, "status").count('<option value=""') == 1
    assert '<option value="">Tous</option>' in _select(beliefs, "status")
    assert 'placeholder="un nom"' in beliefs and "par défaut" not in _select(beliefs, "status").casefold()
    projects = _select(drawn(client, "/admin/projets/tous"), "etat")
    assert projects.count('<option value=""') == 1 and '<option value="">Par défaut (actifs et en pause)</option>' \
        in projects and '<option value="vivants" selected>' in projects


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
    page = drawn(client, "/admin/memoire/promesses")
    engaged = _between(page, 'id="promises-open"', 'class="promises-done"')
    assert "Envoyer la recette" in engaged and "Relire le dossier" in engaged and "Trouver un titre" not in engaged
    late = engaged.split("Envoyer la recette")[0].rsplit("<li class=", 1)[1]
    assert "late" in late and "en retard" in late  # échue : elle le dit, à gauche
    assert "en retard" not in engaged.split("Relire le dossier")[0].rsplit("<li class=", 1)[1]
    assert "Trouver un titre" in _between(page, 'id="promises-kept"', "</section>")
    assert "Rappeler le libraire" in _between(page, 'id="promises-dropped"', "</section>")
    pending = drawn(client, "/admin/memoire/promesses?status=pending")
    assert 'id="promises-open"' in pending and 'id="promises-kept"' not in pending


def test_a_label_renamed_in_the_view_files_nothing_elsewhere(world, monkeypatch):  # noqa: F811
    """L'onglet lit l'état d'un élément dans la clé de son étiquette (``Badge.key``), jamais dans ses mots : un libellé
    renommé dans la vue — « tenue », les mots d'une origine, la sorte d'une pièce — ne range pas une promesse tenue
    parmi celles qui l'engagent, ne fait pas perdre à une origine sa sorte, ni à une pièce son icône."""
    monkeypatch.setitem(memory_view.LISTINGS, memory.PROMISE, replace(memory_view.PROMISES, statuses=(
        ("pending", "en cours"), (memory.HONORED, "tenue parole"), (memory.DROPPED, "abandonnée"))))
    monkeypatch.setattr(memory_view, "ORIGIN_FR", {**memory_view.ORIGIN_FR, memory.TOLD: "on le lui a confié"})
    monkeypatch.setitem(received_view.KIND_LABELS, attachments.IMAGE, "image fixe")
    client, live, _ = world
    kernel, _ = _life(client, live)
    made = append(client, kernel, [memory.PROMISE_NOTICED.draft(text=Content.of("Trouver un titre."), to="alice"),
                                   memory.PROMISE_NOTICED.draft(text=Content.of("Relire le dossier."), to="alice")],
                  "memory").seqs
    append(client, kernel, [memory.PROMISE_RESOLVED.draft(promise=made[0], status=memory.HONORED)], "memory")
    page = drawn(client, "/admin/memoire/promesses")
    assert "Trouver un titre" in _between(page, 'id="promises-kept"', "</section>")
    assert "Trouver un titre" not in _between(page, 'id="promises-open"', 'class="promises-done"')
    assert "Relire le dossier" in _between(page, 'id="promises-open"', 'class="promises-done"')

    append(client, kernel, [memory.BELIEVED.draft(text=Content.of("Alice joue du violoncelle."), about=("alice",),
                                                  origin=memory.TOLD, source="alice", confidence=0.8)], "memory")
    beliefs = drawn(client, "/admin/memoire/croyances")
    belief = _card(beliefs, "Alice joue du violoncelle.")
    assert 'belief-origin o-told"' in belief and "par Alice" in belief and "o-other" not in belief
    table = re.search(r'<a href="([^"]+)"[^>]*>Tableau</a>', beliefs)
    assert table and "on le lui a confié (Alice)" in drawn(client, "/admin/memoire/croyances" + table[1])

    message = append(client, kernel, [rt.PERCEPTION_RECEIVED.draft(handle="alice", channel="web", addressed=True,
                                                                   text=Content.of("Tiens."))]).seqs[0]
    append(client, kernel, [attachments.KEPT.draft(
        file="c" * 32, message=message, handle="alice", name=Content.of("plan.png"), mime="image/png", size=1_000,
        kind=attachments.IMAGE, read=True, about=("alice",), seen=Content.of("Un plan."))], "attachments")
    piece = _card(drawn(client, "/admin/memoire/recues"), "plan.png")
    assert piece.startswith('"memories-item piece k-image') and 'title="image fixe"' in piece


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
    page = drawn(client, "/admin/memoire/moments")
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
    past = _between(drawn(client, "/admin/memoire/moments"), 'id="moments-past"')
    concert = next(li for li in past.split("<li class=") if "Le concert d'Alice" in li)
    assert "annulé" in concert


def test_the_pieces_still_being_read_are_counted_in_words(world):  # noqa: F811
    """La note des pièces qu'elle lit encore s'accorde, sa parenthèse comprise (C2-09)."""
    client, live, _ = world
    kernel, _ = _life(client, live)  # une vie à l'arrêt : la lecture de près attend

    def receive(file: str) -> str:
        append(client, kernel, [rt.PERCEPTION_RECEIVED.draft(
            handle="alice", channel="web", addressed=True, text=Content.of("Tiens."),
            attachments=(rt.AttachmentMeta(name=f"{file[:4]}.png", kind="image", mime="image/png", file=file),))])
        return drawn(client, "/admin/memoire/recues")

    page = receive("d" * 32)
    assert "1 pièce reçue en cours de lecture (elle apparaît ici une fois lue)." in page and "pièce(s)" not in page
    page = receive("e" * 32)
    assert "2 pièces reçues en cours de lecture (elles apparaissent ici une fois lues)." in page


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
    page = drawn(client, "/admin/memoire/recues")
    poster = _between(page, "affiche.png", "</li>")
    assert "Une affiche violette pour une exposition." in _between(poster, "piece-seen", "</div></div>")
    assert "relié à 1 élément" in poster and "onglet=liens" in poster and "/admin/telecharger/piece/" in poster
    voice = _between(page, "vocal.ogg", "</li>")
    assert "gardée, pas lue" in voice and "Rien n’a pu en être lu" in voice
    assert 'class="memories-item piece k-image' in page and 'class="memories-item piece k-audio' in page
    assert 'class="hm-subtabs" data-subtabs' in page and 'href="#pieces-list"' in page and 'href="#pieces-place"' in page
    place = _between(page, 'id="pieces-place"')
    row = _between(place, 'class="place-row', "</li>")
    assert "Alice" in row and "now-bar place" in row and "2 pièces" in row and "onglet=pieces" in row
    assert "Place de chacun" in page and "2,00 Go" in page
    assert "pour 1 personne" in page and "personne(s)" not in page  # le compte s'accorde (C2-09)
    moved = client.get("/admin/memoire/place", follow_redirects=False)
    assert moved.status_code == 301 and moved.headers["location"] == "/admin/memoire/recues#pieces-place"


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
    page = drawn(client, "/admin/memoire/voir-venir")
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
    page = drawn(client, "/admin/memoire/consolidation")
    assert "Rien n’est encore relu" in _between(page, 'class="consol-lede"', "</p>")
    band = _between(page, 'class="person-tiles-list"', "</ul>")
    assert 'href="/admin/memoire/souvenirs"' in band and "À reprendre" in band
    assert '<li class="warn">' in band  # un passage à reprendre : la bande le signale
    queue = _between(page, 'id="consol-queue"', 'id="consol-runs"')
    assert "Erreur du fournisseur" in queue and "3 essais" in queue and "Reprendre cette extraction" in queue
    assert 'href="#consol-queue" class="warn"' in page
    panes = drawn(client, "/admin/memoire/consolidation?avant=1").split('class="hm-subpanes"')[1]
    assert panes.index('id="consol-runs"') < panes.index('id="consol-queue"')


def test_a_conversation_received_on_the_phone_waits_in_the_queue_with_its_action(world):  # noqa: F811
    """Une relecture du téléphone empêchée attend dans la même file que les siennes (ADR 0224) : elle dit d'où elle
    vient, sa cause et son détail, et se reprend du même geste."""
    client, live, _ = world
    kernel, _ = _life(client, live)
    seq = append(client, kernel, [rt.PERCEPTION_RECEIVED.draft(handle="alice", channel="web", addressed=False,
                                                               text=Content.of("Un repère."))]).seqs[0]
    detail = Content.of('{"issues": ["croyances[1]: missing"], "output": "[{\\"croyances\\": []}]"}', level=3)
    append(client, kernel, [memory.EXTRACTION_DEFERRED.draft(key=seq, source=memory.FROM_RELAYED, messages=(seq,),
        about=("alice",), status="review", failure_code="invalid_items", detail=detail)], "memory")
    queue = _between(drawn(client, "/admin/memoire/consolidation"), 'id="consol-queue"', 'id="consol-runs"')
    assert f"conversation reçue sur le téléphone, message n° {seq}" in queue
    assert "Éléments extraits invalides" in queue and "à examiner" in queue and "Détail du passage" in queue
    assert "Reprendre cette extraction" in queue and f'name="key" value="{seq}"' in queue


def test_a_new_memory_says_each_tab_is_empty(world):  # noqa: F811
    client, live, _ = world
    _life(client, live)
    for tab, says in (("croyances", "pas encore de croyance."), ("promesses", "pas encore de promesse."),
                      ("moments", "pas encore de moment noté."), ("recues", "aucune pièce reçue."),
                      ("recues", "aucune pièce gardée."), ("envoyes", "elle n'a encore envoyé aucun fichier."),
                      ("voir-venir", "aucun moment constaté encore."),
                      ("consolidation", "pas encore de relecture."), ("consolidation", "pas encore de nuit relue.")):
        page = drawn(client, f"/admin/memoire/{tab}")
        assert f'data-tab="memoire/{tab}"' in page and says in page, tab


def test_a_night_reread_shows_what_she_kept_and_what_the_night_joined_or_confronted(world):  # noqa: F811
    client, live, _ = world
    kernel, _ = _life(client, live)
    said = ("Alice aime le jazz.", "Alice adore le jazz.", "Alice vit à Lyon.", "Alice a quitté Lyon.",
            "Alice joue du piano.", "Alice fait du piano.")
    b = append(client, kernel, [memory.BELIEVED.draft(text=Content.of(t), about=("alice",), origin=memory.TOLD,
                                                      source="alice", confidence=0.8) for t in said], "memory").seqs
    append(client, kernel, [
        memory.REREAD.draft(night="2026-11-10", upto=0, readings=0, pairs=0),  # d'avant ``produced`` : rien n'en dit
        memory.JOINED.draft(night="2026-11-10", pairs=((b[4], b[5]),)),
        memory.JOINED.draft(night="2026-11-12", pairs=((b[0], b[1]),), mute=True),
        memory.CONFRONTED.draft(night="2026-11-12", supersedes=((b[3], b[2]),)),
    ], "memory")
    done = append(client, kernel, [memory.REREAD.draft(night="2026-11-12", upto=b[0], readings=3, pairs=2,
                                                       produced=4, call_id="nuit#0", model="haiku")],
                  "memory").seqs[0]
    page = drawn(client, "/admin/memoire/consolidation")
    assert 'href="#consol-rereads">Lectures de la nuit<' in page
    rereads = _between(page, 'id="consol-rereads"', 'id="consol-state"')
    night, before = _between(rereads, "12 nov.", "</li>"), _between(rereads, "10 nov.", "</li>")
    assert 'now-num">3</span> lectures relues' in night and 'now-num">2</span> paires confrontées' in night
    assert 'now-num">4</span> éléments retenus' in night and "haiku" in night
    assert f"/admin/evenement/{done}" in night
    # en détail, ce que la même nuit a réuni (jugé la même chose par la relecture) ou confronté, vers les croyances
    detail = _between(night, "Ce que la nuit a réuni ou confronté")
    assert "jugées la même chose par la relecture, sans être les mêmes mots" in detail and "emporte sur" in detail
    assert all(f"/admin/evenement/{n}" in detail for n in b[:4])
    assert f"/admin/evenement/{b[4]}" not in detail  # la jointure d'une autre nuit reste à sa nuit
    # une nuit relue avant ``produced`` ne dit pas ce qu'elle a retenu, et sans appel, pas de modèle
    assert "retenu" not in before and "sans appel au modèle" in before
    assert f"/admin/evenement/{b[4]}" in before
    state = _between(page, 'id="consol-state"')
    assert "dernière nuit relue" in state and "2026-11-12" in state
    # une page plus ancienne de la liste ouvre son sous-onglet
    panes = drawn(client, f"/admin/memoire/consolidation?avant_lectures={done}").split(
        'class="hm-subpanes"')[1]
    assert panes.index('id="consol-rereads"') < panes.index('id="consol-queue"')
