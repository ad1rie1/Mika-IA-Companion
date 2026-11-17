"""Elle › Pensées, chaque onglet dans sa forme (``app/handmade/tabs/thoughts.py``, ADR 0177), à travers le vrai
serveur : ses pensées la plus forte d'abord, de la couleur de leur émotion ; ce qu'elle remarque, la pertinence
annoncée et celle qu'elle retient sur une même barre ; ses attentes, le temps qui court vers leur échéance ; et
l'historique de chacune dans son sous-onglet, ouvert quand on le feuillette."""

from __future__ import annotations

import html
import re
from dataclasses import replace

from mika.app.handmade.tabs import thoughts
from mika.app.handmade.tabs.thoughts import born_of
from mika.contracts import attention, self_
from mika.contracts import email as email_c
from mika.faculties.attention import inspect as attention_view
from mika.faculties.self import inspect as self_view
from mika.kernel.clock import HOUR, MINUTE
from mika.kernel.events import Content, Origin, VoiceProvenance
from tests.fixtures.mika import connect
from tests.protocol.test_console_diagnostics import stop
from tests.protocol.test_console_workflows import append
from tests.protocol.test_drawn_pages import drawn
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée


def _life(client, live):
    """Une vie à l'arrêt (rien ne remarque ni ne constate pendant la lecture), où Alice est connue."""
    bootstrap(client)
    stop(client, live.kernel)
    client.portal.call(connect, live.kernel, "alice", "Alice")
    return live.kernel, live.kernel.mind.clock.now()


def _panes(page: str) -> str:
    return page.split('class="hm-subpanes"', 1)[1]


def _between(page: str, start: str, end: str = "") -> str:
    part = page.split(start, 1)[1]
    return part.split(end, 1)[0] if end else part


def _words(part: str, gap: str = " ") -> str:
    """Ce qu'un morceau de page donne à lire : ses balises remplacées par ``gap`` (rien : deux mots qu'aucune espace
    ne sépare restent collés, « d'Alice »), ses entités rendues, ses espaces resserrés."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", gap, part)).split())


def test_thoughts_come_strongest_first_in_the_colour_of_their_emotion(world):  # noqa: F811
    client, live, _ = world
    kernel, _ = _life(client, live)
    append(client, kernel, [
        attention.THOUGHT_BORN.draft(text=Content.of("Un détail du concert me revient."), emotion="curious",
                                     intensity=0.3, origin=attention.EXCHANGE, about=("alice",)),
        attention.THOUGHT_BORN.draft(text=Content.of("Alice avait l'air triste."), emotion="sad", intensity=0.8,
                                     origin=attention.CONCERN, about=("alice",)),
    ], "attention")
    page = drawn(client, "/admin/pensees/pensees")
    assert 'class="person-tiles-list"' in page.split('class="hm-subtabs"')[0]  # la bande de chiffres, au-dessus
    now = _between(page, 'id="thoughts-now"', 'id="thoughts-history"')
    assert now.index("Alice avait l'air triste.") < now.index("Un détail du concert")  # la plus forte d'abord
    sad = now.split("Alice avait l'air triste.")[0].rsplit('<li class=', 1)[1]
    assert sad.startswith('"thought-item sw-sad') and "née d’une inquiétude" in sad
    curious = now.split("Un détail du concert")[0].rsplit('<li class=', 1)[1]
    assert "sw-curious" in curious and "née d’un échange" in curious
    assert "now-bar thought" in _between(now, "Alice avait l'air triste.", "</li>")
    history = _between(page, 'id="thoughts-history"', 'id="thoughts-rules"')
    assert "Alice avait l'air triste." in history and "vivante" in history
    assert 'id="thoughts-rules"' in page and "demi-vie d'une pensée" in page
    # la bande dit ce qu'elle mesure ; ses seuils sont dans « Comment elles vivent », les initiatives sur Attentes
    band = _words(page.split('class="hm-subtabs"')[0])
    assert "Y a repensé" in band and "dès" not in band and "au plus toutes les" not in band
    assert "Initiatives sans réponse" not in band
    rules = _words(_between(page, 'id="thoughts-rules"'))
    assert re.search(r"y repenser au plus toutes les \d+ min, une pensée d'au moins \d+ %", rules), rules


def test_what_she_notices_shows_announced_and_kept_pertinence_on_one_bar(world):  # noqa: F811
    client, live, _ = world
    kernel, _ = _life(client, live)

    def mail(n, summary, pertinence):
        return email_c.NOTICED.draft(source="email", kind=email_c.MAIL, summary=Content.of(summary),
                                     pertinence=pertinence, bundle="email", mail=f"perso:<{n}@x>", sender="Léa",
                                     address="lea@example.net", importance=0.5, dedupe_key=f"test-{n}")

    async def signal():
        return await kernel.mind.append([mail(1, "Léa attend ton avis.", 0.8), mail(2, "Une facture est là.", 0.5)],
                                        emitter="email", origin=Origin.EXTERNAL, correlation="test-remarque")
    signals = client.portal.call(signal).seqs
    append(client, kernel, [attention.NOTICED.draft(signal=signals[0], source="email", kind=email_c.MAIL, weight=0.5,
                                                    emotion="curious", intensity=0.3)], "attention")
    page = drawn(client, "/admin/pensees/remarque")
    now = _between(page, 'id="noticed-now"', 'id="noticed-history"')
    # ce qui attend d'être remarqué, d'abord ; puis ce qu'elle a remarqué
    assert now.index("Une facture est là.") < now.index("Remarqué ces dernières minutes")
    row = _between(now, '<li class="noticed-row habituated">', "</li>")
    # annoncée 80 %, retenue 40 % (poids 50 %) : les deux sur la même barre, l'habituation dite, en %
    assert 'class="announced" x1="0" x2="80.0"' in row and 'class="fill" x1="0" x2="40.0"' in row
    assert "poids <span class=\"now-num\">50\u202f%</span>" in row and "sw-curious" in row
    # la source et la sorte en mots, le lien vers le signal gardé ; l'émotion qu'il lui a laissée
    assert "Courrier · un mail" in _words(row) and f"/admin/evenement/{signals[0]}" in row
    assert "<span>émotion laissée</span>" in now and "dosée" not in page
    past = _between(page, 'id="noticed-history"', 'id="noticed-rules"')
    assert "Courrier · un mail" in _words(past) and ">email<" not in past and "sw-curious" in past
    assert "Courrier · un mail" in _words(_between(now, 'class="noticed-queue"', "</ul>"))
    assert 'href="#noticed-now" class="warn"' in page  # quelque chose attend : le sous-onglet le signale


def test_expectations_show_time_running_to_their_deadline_then_the_closed_ones(world):  # noqa: F811
    client, live, _ = world
    kernel, now = _life(client, live)
    append(client, kernel, [attention.EXPECTATION_MET.draft(kind=attention.REPLY, person="alice",
                                                           since=now - 2 * HOUR)], "attention")
    from_alice = append(client, kernel, [attention.EXPECTATION_MISSED.draft(kind=attention.REPLY, person="alice",
                                                                           since=now - 30 * MINUTE)], "attention")
    page = drawn(client, "/admin/pensees/attentes")
    waits = _between(page, 'id="waits-now"', 'id="waits-closed"')
    late = _between(waits, '<li class="wait-item', "</li>")
    # manquée mais encore à temps : la jauge du temps qui court vers l'échéance de la réponse tardive
    assert "danger" in late.split(">")[0] and "La réponse d'Alice" in _words(late, "") and "now-bar wait" in late
    closed = _between(page, 'id="waits-closed"')
    assert "La réponse d'Alice" in _words(closed, "") and "de Alice" not in _words(page, "")
    # la bande : le délai en messagerie, les initiatives sans réponse (ici seulement)
    band = _words(page.split('class="hm-subtabs"')[0])
    assert "min en messagerie" in band and "par message" not in band and "Initiatives sans réponse" in band
    assert closed.index('<li class="missed">') < closed.index('<li class="met">')  # la plus récente d'abord
    assert f"/admin/evenement/{from_alice.seqs[0]}" in closed and "déçue" in closed and "comblée" in closed
    older = _panes(drawn(client, "/admin/pensees/attentes?avant=999999"))
    assert older.index('id="waits-closed"') < older.index('id="waits-now"')


def test_a_label_renamed_in_the_view_files_nothing_elsewhere(world, monkeypatch):  # noqa: F811
    """Les onglets de Pensées lisent l'état d'un élément à la clé de son étiquette (``Badge.key``), jamais à ses mots :
    renommés dans la vue, « vivante » ne fait pas passer une pensée pour éteinte, « comblée » ne range pas une attente
    parmi les déçues, « journal » ne fait pas d'un journal un rêve, ni « oui » d'un rêve souvenu un rêve oublié."""
    monkeypatch.setattr(attention_view, "ALIVE", replace(attention_view.ALIVE, text="encore là"))
    monkeypatch.setattr(attention_view, "MET", replace(attention_view.MET, text="venue"))
    monkeypatch.setattr(self_view, "JOURNAL_ENTRY", replace(self_view.JOURNAL_ENTRY, text="carnet"))
    monkeypatch.setattr(self_view, "KEPT_ON_WAKING", replace(self_view.KEPT_ON_WAKING, text="il lui en reste"))
    client, live, _ = world
    kernel, now = _life(client, live)
    append(client, kernel, [attention.THOUGHT_BORN.draft(text=Content.of("Le concert de samedi."), emotion="curious",
                                                         intensity=0.6, origin=attention.EXCHANGE, about=("alice",))],
           "attention")
    history = _between(drawn(client, "/admin/pensees/pensees"), 'id="thoughts-history"', 'id="thoughts-rules"')
    alive = history.split("Le concert de samedi.")[0].rsplit("<li class=", 1)[1]
    assert "encore là" in history and " out" not in alive.split(">", 1)[0]  # toujours vivante

    append(client, kernel, [attention.EXPECTATION_MET.draft(kind=attention.REPLY, person="alice",
                                                           since=now - 2 * HOUR)], "attention")
    closed = _between(drawn(client, "/admin/pensees/attentes"), 'id="waits-closed"')
    assert '<li class="met">' in closed and '<li class="missed">' not in closed and "venue" in closed

    voice = VoiceProvenance(call_id="nuit", persona_hash="fictive", role="journal", model="fake")
    dreamt = append(client, kernel, [
        self_.DREAMT.draft(night="2027-10-18", voice=voice, kind=self_.PLEASANT, vividness=0.8,
                           text=Content.of("Un toit où chaque note allumait une fenêtre.")),
        self_.JOURNALED.draft(day="2027-10-18", voice=voice, text=Content.of("Une soirée au bureau.")),
    ], "self").seqs
    append(client, kernel, [self_.WOKE_WITH.draft(night="2027-10-18", woke_at=now, dream=dreamt[0],
                                                  kind=self_.PLEASANT, remembered=True)], "self")
    nights = drawn(client, "/admin/pensees/nuits").split('class="nights-list"')[1]
    journal = nights.split("Une soirée au bureau.")[0].rsplit("<li class=", 1)[1]
    dream = nights.split("Un toit où chaque note")[0].rsplit("<li class=", 1)[1]
    assert journal.startswith('"journal"') and "carnet" in journal
    assert dream.startswith('"dream"') and '<span class="nights-awake on">souvenu au réveil</span>' in dream


def test_the_texts_of_her_nights_say_their_day_in_words(world):  # noqa: F811
    """Journal et rêves montre ses textes sous le titre que leur donne la faculté, leur jour en mots : l'onglet n'y
    cherche plus de date."""
    client, live, _ = world
    kernel, _ = _life(client, live)
    voice = VoiceProvenance(call_id="nuit", persona_hash="fictive", role="journal", model="fake")
    append(client, kernel, [self_.JOURNALED.draft(day="2027-10-18", voice=voice, text=Content.of("Une soirée."),
                                                  shareable=Content.of("Une soirée calme."))], "self")
    page = drawn(client, "/admin/pensees/nuits")
    journal = _between(page, 'class="now-card nights-journal"', "</article>")
    assert '<h2 id="nights-journal-title">Journal du lun. 18 oct., en entier</h2>' in journal
    today = _words(_between(page, 'aria-labelledby="nights-today-title">', "</section>"))
    assert today.startswith("Sa journée en cours, telle qu'elle pourra la raconter (")
    assert not re.search(r"\d{4}-\d{2}-\d{2}", today)
    assert "2027-10-18" not in page.split('class="nights-list"')[0]


def test_new_thoughts_tabs_say_they_are_empty(world):  # noqa: F811
    client, live, _ = world
    _life(client, live)
    for tab, says in (("pensees", "rien ne lui trotte dans la tête."),
                      ("remarque", "rien de remarqué ces dernières minutes."),
                      ("attentes", "elle n'attend rien de personne.")):
        page = drawn(client, f"/admin/pensees/{tab}")
        assert f'data-tab="pensees/{tab}"' in page and says in page, tab


def test_where_a_thought_comes_from_reads_as_a_sentence():
    assert born_of("un échange") == "née d’un échange" and born_of("une inquiétude") == "née d’une inquiétude"
    assert born_of("elle a menti à quelqu'un") == "née parce qu’elle a menti à quelqu'un"
    assert born_of("personne ne lui écrit") == "née parce que personne ne lui écrit" and born_of("—") == ""


def test_a_signal_says_its_source_and_its_kind_in_words():
    """Une source connue par son nom (sa cellule garde son lien), une source à préfixe en mots, une source ou une
    sorte inconnues telles quelles ; la particule devant qui la lui doit, élidée."""
    link = {"t": "link", "text": "email", "href": "/admin/evenement/12"}
    assert thoughts._source(link) == {"t": "link", "text": "Courrier", "href": "/admin/evenement/12"}
    assert thoughts.source_name("rss") == "Flux RSS" and thoughts.source_name("world") == "Son monde et son corps"
    assert thoughts.source_name("rss:lemonde") == "le flux « lemonde »"
    assert thoughts.source_name("forge:jardin") == "son app « jardin »"
    # ce que lui signale un appareil (``POST /api/perceptions``) : « appareil:<appareil> », de la sorte « signal »
    assert thoughts.source_name("appareil:sonnette") == "l'appareil « sonnette »"
    assert thoughts.source_name("bidule") == "bidule" and thoughts.source_name("bidule:x") == "bidule:x"
    assert thoughts._kind("mail") == "un mail" and thoughts._kind("teams_sent") == "un message Teams envoyé à sa place"
    assert thoughts._kind("bond_shifted") == "un lien qui change" and thoughts._kind("arrosage") == "arrosage"
    assert thoughts._kind("signal") == "un signal"
    assert thoughts.of_whom({"t": "link", "text": "Alice"}) == "d'" and thoughts.of_whom({"t": "text", "text": "Béa"}) \
        == "de " and thoughts.of_whom(None) == ""
