"""Corriger sa mémoire depuis les cartes de la Mémoire (ADR 0230 ; audit du 2026-11-05 : C2-01, décision C2-Q1), à
travers le vrai serveur.

Avant, les cartes de Souvenirs, Croyances, Promesses et La vie des autres ne portaient que « Voir l'origine → » et
« Le détail » : une croyance fausse, une promesse tenue que la relecture n'avait pas vue, un moment annulé ne se
corrigeaient qu'en oubliant toute la personne. Chaque carte porte maintenant les gestes qui ont un sens pour son
élément — une promesse en cours se marque tenue ou s'abandonne, une situation qui dure se finit, un moment daté sans
issue reçoit la sienne, un souvenir ou une croyance actif se dément (sous « ⋯ ») —, postés depuis la page, confirmés,
audités ; une carte d'un statut d'avant n'en offre aucun, et un formulaire rejoué sur un élément déjà corrigé ne
réécrit rien. Les actions mêmes (ce qu'elles écrivent, ce qu'elles ne font pas ressentir) sont gardées par
``tests/unit/test_memory_corrections.py``.
"""

from __future__ import annotations

import re

from mika.contracts import memory
from mika.contracts import runtime as rt
from mika.kernel.clock import DAY
from mika.kernel.events import Content
from tests.fixtures.mika import connect
from tests.protocol.test_console_diagnostics import stop
from tests.protocol.test_console_files import _events
from tests.protocol.test_console_workflows import append
from tests.protocol.test_drawn_fiches import form_of
from tests.protocol.test_drawn_pages import drawn
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée

OPERATOR = "user_1"
PROMISES, BELIEFS, MEMORIES, MOMENTS = ("/inspecteur/memoire/promesses", "/inspecteur/memoire/croyances",
                                        "/inspecteur/memoire/souvenirs", "/inspecteur/memoire/moments")
AUDITED = "/inspecteur/systeme/operations"
#: chaque geste de correction et sa clé d'action
GESTURES = ("memory.tenir", "memory.abandonner", "memory.finir", "memory.issue", "memory.dementir")


def _life(client, live):
    """Une vie à l'arrêt (pas de relecture qui écrive pendant la lecture), où Alice est connue."""
    bootstrap(client)
    stop(client, live.kernel)
    client.portal.call(connect, live.kernel, "alice", "Alice")
    return live.kernel, live.kernel.mind.clock.now()


def _noted(client, kernel, *drafts) -> list[int]:
    """Des éléments notés comme la relecture les note : leur numéro, celui de l'événement qui les a notés."""
    return list(append(client, kernel, list(drafts), "memory").seqs)


def _card(page: str, text: str) -> str:
    """La carte d'une liste qui porte ce texte, de son ``<li`` à sa fin (ses formulaires compris)."""
    found = [li for li in page.split('<li class="memories-item')[1:] if text in li]
    assert len(found) == 1, text
    return found[0]


def _gestures(card: str) -> set[str]:
    """Les actions de correction dont la carte porte un formulaire."""
    return set(re.findall(r'action="/inspecteur/action/(memory\.[a-z]+)"', card))


def _post(client, action: str, form: dict[str, list[str]]):
    sent = client.post(f"/inspecteur/action/{action}", data=form, follow_redirects=False)
    assert sent.status_code == 303, sent.text
    return sent


def _corrections(client, live) -> list:
    """Ce que les gestes ont écrit à la mémoire (leurs événements, hors de l'audit)."""
    return _events(client, live, memory.PROMISE_RESOLVED, memory.SITUATION_ENDED, memory.RESOLVED, memory.RETRACTED)


def test_each_gesture_posted_from_its_card_does_what_it_says_and_is_audited(world):  # noqa: F811
    client, live, _ = world
    kernel, now = _life(client, live)
    recipe, book = _noted(client, kernel,
                          memory.PROMISE_NOTICED.draft(text=Content.of("Envoyer la recette à Alice."), to="alice",
                                                       due=now + DAY),
                          memory.PROMISE_NOTICED.draft(text=Content.of("Prêter le livre à Alice."), to="alice"))
    internship, dinner = _noted(client, kernel,
                                memory.EVENT_NOTED.draft(text=Content.of("Le stage d'Alice."), when=now - 2 * DAY,
                                                         about=("alice",), ongoing=True),
                                memory.EVENT_NOTED.draft(text=Content.of("Le dîner chez Alice."), when=now - DAY,
                                                         about=("alice",)))
    cat, photo = _noted(client, kernel,
                        memory.BELIEVED.draft(text=Content.of("Alice a un chat qui s'appelle Moustache."),
                                              about=("alice",), origin=memory.TOLD, source="alice", confidence=0.8),
                        memory.REMEMBERED.draft(text=Content.of("Alice m'a montré une photo de son chat."),
                                                about=("alice",)))

    # une promesse en cours : « Marquer tenue » et « Abandonner », confirmés, l'élément dans un champ caché
    page = drawn(client, PROMISES)
    card = _card(page, "Envoyer la recette")
    assert _gestures(card) == {"memory.tenir", "memory.abandonner"}
    assert ">Marquer tenue</button>" in card and ">Abandonner</button>" in card
    assert 'data-confirm="Marquer cette promesse tenue' in card
    kept = form_of(page, "memory.tenir", having=str(recipe))
    assert kept["promise"] == [str(recipe)] and kept["_sujet"] == [str(recipe)] and kept["_fixes"] == ["promise"]
    done = _post(client, "memory.tenir", kept)
    assert done.headers["location"].startswith(PROMISES)
    assert "Promesse marquée tenue." in drawn(client, done.headers["location"])
    _post(client, "memory.abandonner", form_of(drawn(client, PROMISES), "memory.abandonner", having=str(book)))
    after = drawn(client, PROMISES)
    # la promesse passe parmi les tenues, l'autre parmi les abandonnées ; plus rien à corriger
    assert "Envoyer la recette" in after.split('id="promises-kept"', 1)[1].split("</section>", 1)[0]
    assert "Prêter le livre" in after.split('id="promises-dropped"', 1)[1].split("</section>", 1)[0]
    assert 'id="promises-open"' not in after
    assert not _gestures(_card(after, "Envoyer la recette")) and not _gestures(_card(after, "Prêter le livre"))

    # une situation qui dure : « C'est fini » ; un moment daté sans issue : « Comment ça a tourné », son choix
    page = drawn(client, MOMENTS)
    assert _gestures(_card(page, "Le stage d'Alice.")) == {"memory.finir"}
    dated = _card(page, "Le dîner chez Alice.")
    assert _gestures(dated) == {"memory.issue"}
    assert '<summary class="btn quiet">Comment ça a tourné</summary>' in dated and ">Noter</button>" in dated
    assert '<option value="cancelled">annulé</option>' in dated
    _post(client, "memory.finir", form_of(page, "memory.finir", having=str(internship)))
    settle = form_of(page, "memory.issue", having=str(dinner))
    assert settle["event"] == [str(dinner)] and settle["_champs"] == ["outcome"]
    _post(client, "memory.issue", {**settle, "outcome": ["cancelled"]})
    after = drawn(client, MOMENTS)
    ended, called_off = _card(after, "Le stage d'Alice."), _card(after, "Le dîner chez Alice.")
    assert ">finie<" in ended and ">annulé<" in called_off
    assert not _gestures(ended) and not _gestures(called_off)

    # une croyance, un souvenir : « Ce n'est pas vrai », discret (sous « ⋯ ») ; démentis, ils s'estompent et le
    # disent, leur texte gardé
    for url, text, item, said in ((BELIEFS, "Alice a un chat", cat, "démentie"),
                                  (MEMORIES, "Alice m'a montré une photo", photo, "démenti")):
        page = drawn(client, url)
        card = _card(page, text)
        assert _gestures(card) == {"memory.dementir"}
        overflow = card.split('<details class="action-overflow">', 1)[1]
        assert 'aria-label="Autres gestes"' in overflow and 'class="btn danger"' in overflow \
            and ">Ce n'est pas vrai</button>" in overflow
        _post(client, "memory.dementir", form_of(page, "memory.dementir", having=str(item)))
        card = _card(drawn(client, url), text)
        assert card.startswith(" belief faded") or card.startswith(" faded")
        assert f">{said}<" in card and not _gestures(card)

    # ce que chaque geste a écrit, et rien d'autre ; Système › Gestes audités montre chacun, fait
    written = [(type(e.data).__name__, e.data) for e in _corrections(client, live)]
    assert [(name, getattr(d, "promise", None) or getattr(d, "event", None) or getattr(d, "item", None))
            for name, d in written] == [("PromiseResolved", recipe), ("PromiseResolved", book),
                                        ("SituationEnded", internship), ("Resolved", dinner),
                                        ("Retracted", cat), ("Retracted", photo)]
    audit = [(a.data.action, a.data.by, a.data.subject, a.data.outcome) for a in _events(client, live, rt.OPERATED)]
    assert audit == [("memory.tenir", OPERATOR, str(recipe), "done"), ("memory.abandonner", OPERATOR, str(book), "done"),
                     ("memory.finir", OPERATOR, str(internship), "done"),
                     ("memory.issue", OPERATOR, str(dinner), "done"),
                     ("memory.dementir", OPERATOR, str(cat), "done"), ("memory.dementir", OPERATOR, str(photo), "done")]
    gestures = drawn(client, AUDITED)
    for title in ("Marquer tenue", "Abandonner", "C'est fini", "Comment ça a tourné", "Ce n'est pas vrai"):
        assert title in gestures, title


def test_a_card_of_a_former_status_offers_nothing(world):  # noqa: F811
    """Une croyance remplacée, un souvenir fondu dans un autre, une promesse tenue, une situation finie de la bouche de
    la personne, un moment déjà tranché, une date qui revient chaque année : rien à corriger ; leur voisin actif, si."""
    client, live, _ = world
    kernel, now = _life(client, live)
    old = _noted(client, kernel, memory.BELIEVED.draft(text=Content.of("Alice préfère le thé."), about=("alice",),
                                                       origin=memory.INFERRED, confidence=0.4))[0]
    _noted(client, kernel, memory.BELIEVED.draft(text=Content.of("Alice préfère le café serré."), about=("alice",),
                                                 origin=memory.TOLD, source="alice", confidence=0.9, replaces=old))
    first, merged = _noted(client, kernel,
                           memory.REMEMBERED.draft(text=Content.of("Alice a gagné son tournoi."), about=("alice",)),
                           memory.REMEMBERED.draft(text=Content.of("Alice a gagné son tournoi !"), about=("alice",)))
    append(client, kernel, [memory.NIGHT_SORTED.draft(night="2026-11-12", merges=((first, merged),))], "memory")
    honored = _noted(client, kernel, memory.PROMISE_NOTICED.draft(text=Content.of("Trouver un titre."), to="alice"))[0]
    append(client, kernel, [memory.PROMISE_RESOLVED.draft(promise=honored, status=memory.HONORED)], "memory")
    moved, _birthday, move = _noted(client, kernel,
                                   memory.EVENT_NOTED.draft(text=Content.of("Le concert d'Alice."), when=now - DAY,
                                                            about=("alice",)),
                                   memory.EVENT_NOTED.draft(text=Content.of("L'anniversaire d'Alice."),
                                                            when=now - 300 * DAY, about=("alice",), yearly=True),
                                   memory.EVENT_NOTED.draft(text=Content.of("Le déménagement d'Alice."),
                                                            when=now - 3 * DAY, about=("alice",), ongoing=True))
    append(client, kernel, [memory.RESOLVED.draft(event=moved, outcome=memory.MOVED, by="alice"),
                            memory.SITUATION_ENDED.draft(event=move)], "memory")

    beliefs = drawn(client, BELIEFS)
    assert not _gestures(_card(beliefs, "Alice préfère le thé."))
    assert _gestures(_card(beliefs, "Alice préfère le café serré.")) == {"memory.dementir"}
    memories = drawn(client, MEMORIES)
    cards = [li for li in memories.split('<li class="memories-item')[1:] if "Alice a gagné son tournoi" in li]
    assert sorted(len(_gestures(li)) for li in cards) == [0, 1]
    assert not _gestures(next(li for li in cards if li.startswith(" faded")))
    assert not _gestures(_card(drawn(client, PROMISES), "Trouver un titre."))
    moments = drawn(client, MOMENTS)
    for text in ("Le concert d'Alice.", "L'anniversaire d'Alice.", "Le déménagement d'Alice."):
        assert not _gestures(_card(moments, text)), text


def test_a_form_replayed_on_an_item_already_corrected_is_refused_without_writing(world):  # noqa: F811
    """Le même formulaire renvoyé ne refait rien ; un autre geste resté sur une page ouverte avant la correction (une
    autre carte, un autre onglet) est refusé et le dit, sans rien écrire à la mémoire — audité, refusé ; « a eu
    lieu » sur un moment qui n'a pas commencé est refusé sur son champ."""
    client, live, _ = world
    kernel, now = _life(client, live)
    # une autre promesse reste en cours : l'action reste offerte, c'est la promesse corrigée qui refuse
    recipe, _book = _noted(client, kernel,
                           memory.PROMISE_NOTICED.draft(text=Content.of("Envoyer la recette à Alice."), to="alice"),
                           memory.PROMISE_NOTICED.draft(text=Content.of("Prêter le livre à Alice."), to="alice"))
    cat = _noted(client, kernel, memory.BELIEVED.draft(text=Content.of("Alice a un chat."), about=("alice",),
                                                       origin=memory.TOLD, source="alice", confidence=0.8))[0]
    trip = _noted(client, kernel, memory.EVENT_NOTED.draft(text=Content.of("Le voyage d'Alice à Lisbonne."),
                                                           when=now + 5 * DAY, about=("alice",)))[0]
    stale = drawn(client, PROMISES)
    kept, dropped = form_of(stale, "memory.tenir", having=str(recipe)), \
        form_of(stale, "memory.abandonner", having=str(recipe))
    first, second = (form_of(drawn(client, BELIEFS), "memory.dementir", having=str(cat)) for _ in range(2))
    assert first["_op"] != second["_op"]

    _post(client, "memory.tenir", kept)
    again = _post(client, "memory.tenir", kept)
    assert "Ce formulaire a déjà été envoyé" in drawn(client, again.headers["location"])
    late = _post(client, "memory.abandonner", dropped)
    assert "Cette promesse n'est plus en cours" in drawn(client, late.headers["location"])
    _post(client, "memory.dementir", first)
    denied = _post(client, "memory.dementir", second)
    assert "Elle ne le tient déjà plus pour sien" in drawn(client, denied.headers["location"])
    # « a eu lieu » avant qu'il commence : refusé, le formulaire remontré avec son erreur
    early = client.post("/inspecteur/action/memory.issue", follow_redirects=False,
                        data={**form_of(drawn(client, MOMENTS), "memory.issue", having=str(trip)),
                              "outcome": ["happened"]})
    assert early.status_code == 400 and "Annulé ou reporté seulement" in early.text

    written = _corrections(client, live)
    assert [(type(e.data).__name__, getattr(e.data, "status", None)) for e in written] == \
        [("PromiseResolved", memory.HONORED), ("Retracted", None)]
    audit = [(a.data.action, a.data.outcome) for a in _events(client, live, rt.OPERATED)]
    assert audit == [("memory.tenir", "done"), ("memory.abandonner", "refused"), ("memory.dementir", "done"),
                     ("memory.dementir", "refused"), ("memory.issue", "refused")]
    assert all(g in GESTURES for g, _ in audit)
