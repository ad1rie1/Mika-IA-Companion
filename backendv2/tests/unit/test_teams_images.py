"""Les images de Teams dans le magasin et leur lecture (ADR 0258), sur un magasin à part (sans ordonnanceur qui les
regarderait à notre place) : un message qui attend ses images n'est remarqué qu'une fois qu'elles sont lues (3 min au
plus) ; ce que Mika y a vu remplace « [image] » à son rang et survit à une retouche ; un échec passager est retenté,
puis l'image reste gardée sans rien dire ; l'oubli efface les images ; la lecture regarde chaque image et fait relire
le tri.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from mika.adapters.teams import TeamsConfig, TeamsStore
from mika.adapters.teams import store as store_mod
from mika.adapters.teams.store import described
from mika.app.teams import batch_of
from mika.kernel.clock import MINUTE
from mika.plugins.teams import images as images_mod
from mika.ports.preprocess import Studied
from mika.ports.teams import IMAGE_KEPT, IMAGE_KNOWN, IMAGE_NO_MESSAGE, ImageIn
from mika.sim.clock import SimClock
from tests.unit.test_teams import DM, START

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture
def store(tmp_path):
    clock = SimClock(START)
    s = TeamsStore(lambda: TeamsConfig(), tmp_path / "teams.db", now=clock.now)
    s.clock = clock
    yield s
    s.close()


def push(store, *messages) -> None:
    now = store.clock.now()
    lot = {"conversations": [{"id": DM, "kind": "dm"}], "messages": [
        {"id": mid, "conv": DM, "author": "Alice", "author_id": "8:orgid:a", "time": now // 1000, "text": text,
         "images": images} for mid, text, images in messages]}
    store.store_batch("principal", batch_of(lot, now // 1000)[0], now)


def keep(store, mid: str, image: str = "0-img", *, data: bytes = JPEG, mime: str = "image/jpeg", position: int = 0):
    return store.keep_image("principal", ImageIn(DM, mid, image, position, mime, data), store.clock.now())


def noticed(store) -> list[str]:
    return [m.text for m in asyncio.run(store.fetch_new(10))]


def read_next(store, seen: str) -> None:
    found = store.image_to_read()
    store.image_read(found.id, seen=seen, sensitive=False, read=True)


def test_a_message_waits_for_its_images_then_is_noticed_described(store):
    push(store, ("1759000000710", "une photo [image]", 1), ("1759000000711", "et du texte", 0))
    assert noticed(store) == ["et du texte"], "annoncée, pas arrivée : il attend"
    assert keep(store, "1759000000710") == IMAGE_KEPT
    assert keep(store, "1759000000710") == IMAGE_KNOWN
    assert keep(store, "1759000000799") == IMAGE_NO_MESSAGE
    assert noticed(store) == ["et du texte"], "arrivée, pas regardée : il attend encore"
    read_next(store, "un chat roux sur un clavier")
    assert noticed(store) == ["une photo [image : un chat roux sur un clavier]", "et du texte"]


def test_an_image_that_never_comes_holds_its_message_three_minutes_at_most(store):
    push(store, ("1759000000712", "perdue [image]", 1))
    assert noticed(store) == []
    store.clock.advance_to(store.clock.now() + store_mod.IMAGE_HOLD + MINUTE)
    assert noticed(store) == ["perdue [image]"]


def test_what_she_saw_survives_an_edit_and_the_images_go_with_the_message(store):
    push(store, ("1759000000720", "[image] puis [image]", 2))
    keep(store, "1759000000720", "0-img-un", position=0)
    keep(store, "1759000000720", "0-img-deux", data=PNG, mime="image/png", position=1)
    read_next(store, "un tableau blanc")
    read_next(store, "un graphe]\nen barres")
    [m] = store.thread("principal", DM, 5)
    assert m.text == "[image : un tableau blanc] puis [image : un graphe) en barres]"
    push(store, ("1759000000720", "[image] puis [image] (retouché)", 2))
    [m] = store.thread("principal", DM, 5)
    assert m.text == "[image : un tableau blanc] puis [image : un graphe) en barres] (retouché)"
    assert [(i.position, i.mime) for i in store.images_of([m.ref])] == [(0, "image/jpeg"), (1, "image/png")]
    assert store.image_bytes(m.ref, "0-img-deux") == ("image/png", PNG)
    asyncio.run(store.forget("teams:8:orgid:a"))
    assert store.images_of([m.ref]) == [] and store.image_bytes(m.ref, "0-img-deux") is None


def test_a_passing_failure_is_retried_then_the_image_is_kept_unread(store):
    push(store, ("1759000000730", "[image]", 1))
    keep(store, "1759000000730")
    found = store.image_to_read()
    for _ in range(store_mod.IMAGE_TRIES - 1):
        store.image_read(found.id, seen="", sensitive=False, read=False)
        assert store.image_to_read() is not None, "encore à regarder"
    store.image_read(found.id, seen="", sensitive=False, read=False)
    assert store.image_to_read() is None, "tenue pour lue après trois essais"
    assert noticed(store) == ["[image]"], "et son message ne l'attend plus"


def test_an_account_keeps_a_bounded_place_for_its_images(store, monkeypatch):
    monkeypatch.setattr(store_mod, "IMAGES_PER_ACCOUNT_BYTES", len(JPEG) * 2)
    push(store, ("1759000000750", "[image] [image] [image]", 3))
    for n in range(3):
        keep(store, "1759000000750", f"0-img-{n}", position=n)
        store.clock.advance_to(store.clock.now() + MINUTE)
    [m] = store.thread("principal", DM, 1)
    assert [i.image for i in store.images_of([m.ref])] == ["0-img-1", "0-img-2"], "la plus ancienne est partie"


class Reader:
    def __init__(self, *results: Studied) -> None:
        self.results = list(results)
        self.seen: list[str] = []

    async def study(self, upload, *, max_chars: int) -> Studied:
        self.seen.append(upload.mime)
        return self.results.pop(0)


def test_the_reading_process_looks_at_each_image_and_lets_the_triage_read_again(store):
    push(store, ("1759000000740", "[image]", 1), ("1759000000741", "[image]", 1))
    keep(store, "1759000000740")
    keep(store, "1759000000741", data=PNG, mime="image/png")
    emitted: list = []

    async def emit(draft) -> None:
        emitted.append(draft)

    reader = Reader(Studied("un plan de salle", True), Studied("", False, transient=True))
    ctx = SimpleNamespace(ports={"teams": store, "preprocess": reader}, frame=SimpleNamespace(now=1_000_000),
                          emit=emit, state=SimpleNamespace(images=2))
    look = images_mod.Look()
    asyncio.run(look.run(ctx))
    assert reader.seen == ["image/jpeg", "image/png"]
    assert len(emitted) == 1, "une image lue ; l'autre, un échec passager, attend son tour"
    assert look.retry_at > ctx.frame.now
    assert [m.text for m in store.thread("principal", DM, 5)] == ["[image : un plan de salle]", "[image]"]


def test_described_replaces_each_mark_by_its_rank():
    assert described("a [image] b [image]", {1: "deux"}) == "a [image] b [image : deux]"
    assert described("rien", {0: "une image sans marque"}) == "rien [image : une image sans marque]"
    assert described("[image : vieux]", {0: "neuf"}) == "[image : neuf]"
    assert described("[image]", {}) == "[image]"
