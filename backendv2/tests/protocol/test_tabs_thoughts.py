"""Elle › Pensées, chaque onglet dans sa forme (``app/handmade/tabs/thoughts.py``, ADR 0177), à travers le vrai
serveur : ses pensées la plus forte d'abord, de la couleur de leur émotion ; ce qu'elle remarque, la pertinence
annoncée et celle qu'elle retient sur une même barre ; ses attentes, le temps qui court vers leur échéance ; et
l'historique de chacune dans son sous-onglet, ouvert quand on le feuillette."""

from __future__ import annotations

from mika.app.handmade.tabs.thoughts import born_of
from mika.contracts import attention
from mika.contracts import email as email_c
from mika.kernel.clock import HOUR, MINUTE
from mika.kernel.events import Content, Origin
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


def test_thoughts_come_strongest_first_in_the_colour_of_their_emotion(world):  # noqa: F811
    client, live, _ = world
    kernel, _ = _life(client, live)
    append(client, kernel, [
        attention.THOUGHT_BORN.draft(text=Content.of("Un détail du concert me revient."), emotion="curious",
                                     intensity=0.3, origin=attention.EXCHANGE, about=("alice",)),
        attention.THOUGHT_BORN.draft(text=Content.of("Alice avait l'air triste."), emotion="sad", intensity=0.8,
                                     origin=attention.CONCERN, about=("alice",)),
    ], "attention")
    page = drawn(client, "/inspecteur/pensees/pensees")
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
    page = drawn(client, "/inspecteur/pensees/remarque")
    now = _between(page, 'id="noticed-now"', 'id="noticed-history"')
    # ce qui attend d'être remarqué, d'abord ; puis ce qu'elle a remarqué
    assert now.index("Une facture est là.") < now.index("Remarqué ces dernières minutes")
    row = _between(now, '<li class="noticed-row habituated">', "</li>")
    # annoncée 0,80, retenue 0,40 (poids 0,50) : les deux sur la même barre, l'habituation dite
    assert 'class="announced" x1="0" x2="80.0"' in row and 'class="fill" x1="0" x2="40.0"' in row
    assert "poids <span class=\"now-num\">0,50</span>" in row and "sw-curious" in row
    assert "email" in _between(page, 'id="noticed-history"', 'id="noticed-rules"')
    assert 'href="#noticed-now" class="warn"' in page  # quelque chose attend : le sous-onglet le signale


def test_expectations_show_time_running_to_their_deadline_then_the_closed_ones(world):  # noqa: F811
    client, live, _ = world
    kernel, now = _life(client, live)
    append(client, kernel, [attention.EXPECTATION_MET.draft(kind=attention.REPLY, person="alice",
                                                           since=now - 2 * HOUR)], "attention")
    from_alice = append(client, kernel, [attention.EXPECTATION_MISSED.draft(kind=attention.REPLY, person="alice",
                                                                           since=now - 30 * MINUTE)], "attention")
    page = drawn(client, "/inspecteur/pensees/attentes")
    waits = _between(page, 'id="waits-now"', 'id="waits-closed"')
    late = _between(waits, '<li class="wait-item', "</li>")
    # manquée mais encore à temps : la jauge du temps qui court vers l'échéance de la réponse tardive
    assert "danger" in late.split(">")[0] and "Sa réponse" in late and "Alice" in late and "now-bar wait" in late
    closed = _between(page, 'id="waits-closed"')
    assert closed.index('<li class="missed">') < closed.index('<li class="met">')  # la plus récente d'abord
    assert f"/inspecteur/evenement/{from_alice.seqs[0]}" in closed and "déçue" in closed and "comblée" in closed
    older = _panes(drawn(client, "/inspecteur/pensees/attentes?avant=999999"))
    assert older.index('id="waits-closed"') < older.index('id="waits-now"')


def test_new_thoughts_tabs_say_they_are_empty(world):  # noqa: F811
    client, live, _ = world
    _life(client, live)
    for tab, says in (("pensees", "rien ne lui trotte dans la tête."),
                      ("remarque", "rien de remarqué ces dernières minutes."),
                      ("attentes", "elle n'attend rien de personne.")):
        page = drawn(client, f"/inspecteur/pensees/{tab}")
        assert f'data-tab="pensees/{tab}"' in page and says in page, tab


def test_where_a_thought_comes_from_reads_as_a_sentence():
    assert born_of("un échange") == "née d’un échange" and born_of("une inquiétude") == "née d’une inquiétude"
    assert born_of("elle a menti à quelqu'un") == "née parce qu’elle a menti à quelqu'un"
    assert born_of("personne ne lui écrit") == "née parce que personne ne lui écrit" and born_of("—") == ""
