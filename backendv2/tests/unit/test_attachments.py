"""Ce qu'on lui envoie dans une conversation (ADR 0106), par ses intentions.

- une photo, un document, un vocal joints à un message sont **gardés** (leurs octets hors du journal) et **lus de
  près** en fond (une photo décrite en détail, son texte visible, ce qu'elle a d'intime) ;
- la même pièce renvoyée par la même adresse est une seule pièce, portée par deux messages ; une lecture qui échoue
  pour un temps se redemande, puis la pièce est gardée sans lecture ; des octets absents ne laissent rien ;
- **un lien n'est pas une source** : la relecture désigne les pièces d'où vient un élément (un repère, un nom), en
  plus de ses messages, plusieurs au besoin ; sans désignation, seulement la seule pièce des messages cités ; une
  clé inventée ne relie rien ; elle relie (et délie) elle-même, en mots ;
- elle retrouve et rouvre une pièce devant son expéditeur, dans un salon public où elle a été postée, pour elle-même
  — pas devant quelqu'un d'autre ; ce qui y est relié passe par le verdict de sa mémoire ; une photo se regarde de
  nouveau pour une question ;
- la place est bornée par personne (toutes ses adresses) ; l'oubli d'une personne efface octets, lignes, liens et
  vecteurs.
"""

from __future__ import annotations

import asyncio
import hashlib

from sqlalchemy import select

from mika.adapters.preprocess import verdict_line
from mika.adapters.shares import MemoryShares
from mika.adapters.vectors import HashEmbedder, SqliteVectorIndex
from mika.app.mindport import KernelPort
from mika.contracts import attachments as c
from mika.contracts import memory as mc
from mika.contracts.runtime import AttachmentMeta
from mika.faculties.attachments.faculty import (
    MIB,
    MISSING,
    AttachmentsParams,
    AttachmentsState,
    carried_table,
    due_expiries,
    file_id,
    files_table,
    links_table,
)
from mika.faculties.memory.extraction import Extraction, Line, Piece, XCroyance, XSouvenir, pieces_of, pieces_words
from mika.kernel.events import Content, Origin
from mika.kernel.state import FrozenDict
from mika.ports.preprocess import Studied
from mika.sim.clock import run_virtual
from mika.vocab.privacy import INTERNAL, Sensitivity
from tests.fixtures.mika import build, boot, connect, said
from tests.unit.test_knowledge_coherence import Store, drafts
from tests.unit.test_knowledge_coherence import alice_says as _alice_line
from tests.unit.test_shares import call, journal, quiet

PHOTO = b"\xff\xd8\xff\xe0" + b"un chat roux" * 40
TICKET = b"\x89PNG\r\n\x1a\n" + b"ticket de caisse" * 30
SEEN = "Un chat roux couché sur un canapé bleu, une couverture à carreaux. Aucun texte visible."


class Reader:
    """Le prétraitement, scripté : ce qu'une lecture de près rend, et ce qu'un regard répond."""

    def __init__(self, studied: Studied | list[Studied] | None = None, looked: str | None = None) -> None:
        self.studied = studied if isinstance(studied, list) else [studied or Studied(SEEN, True)]
        self.looked = looked
        self.studies: list[str] = []
        self.looks: list[tuple[str, str]] = []

    async def perceive(self, uploads):  # pragma: no cover - le bord n'est pas en jeu ici
        return []

    async def study(self, upload, *, max_chars):
        self.studies.append(upload.name)
        return self.studied[min(len(self.studies), len(self.studied)) - 1]

    async def look(self, upload, question):
        self.looks.append((upload.name, question))
        return self.looked


def live(tmp_path, scenario, *, reader: Reader | None = None):
    store = MemoryShares()
    reader = reader or Reader()
    # l'index des pièces, sur le magasin que le harnais construit (posé juste après : l'index ne le lit qu'à l'ouverture)
    pieces = SqliteVectorIndex(None, HashEmbedder(), table=c.VECTORS)
    kernel, clock, llm, _deliveries = build(tmp_path, quiet,
                                            ports={c.PORT: store, "preprocess": reader, c.VECTORS: pieces})
    pieces.store = kernel.deps.store

    async def main():
        await boot(kernel)
        try:
            await connect(kernel, "user_2", "Alice")
            await connect(kernel, "user_3", "Bob")
            return await scenario(kernel, store, reader)
        finally:
            await kernel.stop()

    return run_virtual(clock, main)


async def send(kernel, handle: str, text: str, *blobs: tuple[str, str, bytes], room: str | None = None,
               public: bool = False) -> tuple[int, list[str | None]]:
    """Un message et ses pièces jointes, comme le bord les fait entrer : les octets gardés d'abord, puis le message
    qui les désigne."""
    files = await KernelPort(kernel).keep_attachments(handle, [data for _n, _m, data in blobs])
    meta = tuple(AttachmentMeta(name=name, kind="image" if mime.startswith("image/") else "file", mime=mime,
                                extracted=True, file=f) for (name, mime, _d), f in zip(blobs, files, strict=True))
    got = await kernel.perceive(said(handle, text, attachments=meta, room=room, public=public))
    await asyncio.sleep(120)  # la lecture de près, en fond
    return got.seq, files


def files_rows(kernel) -> list[tuple]:
    t = files_table()
    return kernel.mind.store.query_mind(select(t.c.id, t.c.handle, t.c.sensitivity, t.c.readable, t.c.seen)
                                        .order_by(t.c.seq))


def links_rows(kernel) -> list[tuple]:
    ln = links_table()
    return kernel.mind.store.query_mind(select(ln.c.file, ln.c.item, ln.c.by).order_by(ln.c.item))


# ── Garder et lire de près ────────────────────────────────────────────────


def test_a_photo_is_kept_read_closely_and_reopened_by_its_sender_only(tmp_path):
    async def scenario(kernel, store, reader):
        _seq, [file] = await send(kernel, "user_2", "regarde mon chat !", ("chat.jpg", "image/jpeg", PHOTO))
        mine = await call(kernel, "attachments_search", "user_2", query="la photo de son chat")
        other = await call(kernel, "attachments_search", "user_3", query="chat")
        thinking = await call(kernel, "attachments_search", "goal:1", query="chat", audience=INTERNAL)
        opened = await call(kernel, "attachment_open", "user_2", piece="chat.jpg")
        return file, dict(store.blobs), dict(store.subjects), journal(kernel, c.KEPT), mine, other, thinking, opened

    file, blobs, subjects, kept, mine, other, thinking, opened = live(tmp_path, scenario)
    assert file == file_id("user_2", PHOTO) and blobs == {file: PHOTO} and "user_2" in subjects[file]
    [e] = kept
    d = e.data
    assert (d.file, d.kind, d.read, d.stored, d.size) == (file, c.IMAGE, True, True, len(PHOTO))
    assert d.seen.text == SEEN and d.name.text == "chat.jpg" and d.sensitivity == Sensitivity.PERSONAL
    assert d.digest == hashlib.sha256(PHOTO).hexdigest()
    assert "« chat.jpg »" in mine.content and "chat roux" in mine.content and file[:8] in mine.content
    assert "chat.jpg" not in other.content  # Bob n'a aucun lien avec Alice : la photo d'Alice ne se rouvre pas
    assert "« chat.jpg »" in thinking.content  # pour elle-même, oui
    assert opened.ok and SEEN in opened.content and "> " in opened.content  # ce qu'elle y a lu est cité


def test_the_same_photo_sent_twice_is_one_piece_carried_by_two_messages(tmp_path):
    async def scenario(kernel, store, reader):
        first, [a] = await send(kernel, "user_2", "mon chat", ("chat.jpg", "image/jpeg", PHOTO))
        second, [b] = await send(kernel, "user_2", "encore lui", ("chat-bis.jpg", "image/jpeg", PHOTO))
        m = carried_table()
        carried = kernel.mind.store.query_mind(select(m.c.message, m.c.file).order_by(m.c.message))
        return a, b, first, second, carried, journal(kernel, c.KEPT), reader.studies

    a, b, first, second, carried, kept, studies = live(tmp_path, scenario)
    assert a == b and carried == [(first, a), (second, a)]
    assert len(kept) == 1 and studies == ["chat.jpg"]  # lue une fois


def test_an_intimate_photo_is_a_confidence(tmp_path):
    reader = Reader(Studied("Une ordonnance médicale au nom d'Alice.", True, sensitive=True))

    async def scenario(kernel, store, reader):
        await send(kernel, "user_2", "mon ordonnance", ("ordo.jpg", "image/jpeg", PHOTO))
        return journal(kernel, c.KEPT)

    [e] = live(tmp_path, scenario, reader=reader)
    assert e.data.sensitivity == Sensitivity.CONFIDENCE and e.data.seen.level == Sensitivity.CONFIDENCE


def test_a_reading_that_fails_for_a_while_is_retried_then_the_piece_is_kept_unread(tmp_path):
    flaky = Studied("", False, error="délai dépassé", transient=True)
    reader = Reader([flaky, flaky, flaky])

    async def scenario(kernel, store, reader):
        await send(kernel, "user_2", "tiens", ("chat.jpg", "image/jpeg", PHOTO))
        early = journal(kernel, c.KEPT)
        await asyncio.sleep(3600)
        return early, journal(kernel, c.KEPT), list(reader.studies)

    early, kept, studies = live(tmp_path, scenario, reader=reader)
    assert early == [] and len(studies) == 3  # redemandée, de plus en plus tard, trois fois au plus
    [e] = kept
    assert not e.data.read and e.data.seen is None and e.data.stored  # gardée, son nom seul


def test_missing_bytes_leave_the_queue_without_any_text(tmp_path):
    async def scenario(kernel, store, reader):
        meta = (AttachmentMeta(name="perdu.jpg", kind="image", mime="image/jpeg", file="a" * 32),)
        await kernel.perceive(said("user_2", "et ça ?", attachments=meta))
        await asyncio.sleep(120)
        return journal(kernel, c.KEPT), journal(kernel, c.EXPIRED), kernel.mind.frame().state(c.OWNER)

    kept, expired, state = live(tmp_path, scenario)
    assert kept == [] and [e.data.reason for e in expired] == [MISSING] and not state.pending


def test_a_piece_posted_in_a_public_room_reopens_for_anyone(tmp_path):
    async def scenario(kernel, store, reader):
        await send(kernel, "user_2", "le menu de ce soir", ("menu.png", "image/png", TICKET), room="salon",
                   public=True)
        return journal(kernel, c.KEPT), await call(kernel, "attachments_search", "user_3", query="menu")

    [e], found = live(tmp_path, scenario)
    assert e.data.sensitivity == Sensitivity.ANODYNE and "« menu.png »" in found.content


def test_she_looks_again_at_a_photo_for_a_question(tmp_path):
    reader = Reader(looked="Il est écrit : TOTAL 12,50 €.")

    async def scenario(kernel, store, reader):
        _seq, [file] = await send(kernel, "user_2", "mon ticket", ("ticket.png", "image/png", TICKET))
        out = await call(kernel, "attachment_open", "user_2", piece=file[:8], question="le total ?")
        return out, reader.looks

    out, looks = live(tmp_path, scenario, reader=reader)
    assert looks == [("ticket.png", "le total ?")] and "12,50 €" in out.content


# ── Un lien n'est pas une source ──────────────────────────────────────────


def _pieces(*names: str, seq: int = 12) -> tuple[Piece, ...]:
    return tuple(Piece(f"#{seq}.{i}", n, "image", f"{i:032x}") for i, n in enumerate(names, 1))


def test_the_reread_names_its_pieces_and_never_guesses_among_several():
    one = {12: Line(12, 0, "Alice", "mon chat", "user_2", pieces=_pieces("chat.jpg"))}
    three = {12: Line(12, 0, "Alice", "mes photos", "user_2", pieces=_pieces("chat.jpg", "appart.jpg", "ticket.png"))}
    assert pieces_of(["#12.2"], [12], three) == (f"{2:032x}",)
    assert pieces_of(["12.3", "[#12.1]"], [], three) == (f"{3:032x}", f"{1:032x}")  # plusieurs, dans l'ordre
    assert pieces_of(["appart.jpg"], [12], three) == (f"{2:032x}",)  # par son nom
    assert pieces_of(["appart"], [12], three) == (f"{2:032x}",)  # sans extension
    assert pieces_of([], [12], one) == (f"{1:032x}",)  # rien de désigné : la seule pièce des messages cités
    assert pieces_of([], [12], three) == ()  # parmi plusieurs, rien ne se devine
    assert pieces_of([], [], one) == ()  # rien de cité : rien
    assert pieces_of(["#99.1", "inventee.jpg"], [12], one) == ()  # une clé inventée ne relie rien
    assert pieces_words(three[12].pieces) == \
        " [pièces : #12.1 « chat.jpg » (photo), #12.2 « appart.jpg » (photo), #12.3 « ticket.png » (photo)]"


async def test_a_souvenir_and_a_belief_keep_their_messages_and_carry_their_pieces():
    db = Store()
    line = _alice_line("voilà Moustache et mon nouvel appart")
    line = Line(line.seq, line.at, line.speaker, line.text, line.person,
                pieces=_pieces("moustache.jpg", "appart.jpg", seq=line.seq))
    ex = Extraction(
        souvenirs=[XSouvenir(texte="Alice m'a montré son nouvel appartement", personnes=["P1"],
                             messages=[line.seq], pieces=[f"#{line.seq}.2"])],
        croyances=[XCroyance(texte="Alice a un chat roux, Moustache", personnes=["P1"], messages=[line.seq],
                             source="P1", pieces=["moustache.jpg"])])
    out = {d.type.name: d.data for d in await drafts(db, ex, (line,))}
    db.conn.close()
    souvenir, belief = out[mc.REMEMBERED.name], out[mc.BELIEVED.name]
    assert souvenir.sources == (line.seq,) and souvenir.pieces == (f"{2:032x}",)
    assert belief.sources == (line.seq,) and belief.pieces == (f"{1:032x}",)


def test_links_are_projected_from_the_reread_and_an_invented_key_links_nothing(tmp_path):
    async def scenario(kernel, store, reader):
        _seq, [file] = await send(kernel, "user_2", "mon chat Moustache", ("chat.jpg", "image/jpeg", PHOTO))
        commit = await kernel.mind.append([mc.BELIEVED.draft(
            text=Content.of("Alice a un chat roux, Moustache", level=2), about=("user_2",), sensitivity=2,
            told_by=("user_2",), heard_by=("user_2",), source="user_2", pieces=(file, "b" * 32))],
            emitter="memory", correlation="relecture", origin=Origin.PROCESS)
        item = commit.events[0].seq
        await asyncio.sleep(60)
        opened = await call(kernel, "attachment_open", "user_2", piece="chat.jpg")
        found = await call(kernel, "attachments_search", "user_2", query="chat")
        return file, item, links_rows(kernel), opened, found

    file, item, links, opened, found = live(tmp_path, scenario)
    assert links == [(file, item, c.BY_REREAD)]
    assert "Ce que tu sais qui va avec" in opened.content and "Moustache" in opened.content
    assert "va avec : « Alice a un chat roux, Moustache »" in found.content


def test_she_links_and_unlinks_a_piece_in_words(tmp_path):
    text = "Alice a un chat roux, Moustache"

    async def scenario(kernel, store, reader):
        _seq, [file] = await send(kernel, "user_2", "regarde", ("chat.jpg", "image/jpeg", PHOTO))
        commit = await kernel.mind.append([mc.BELIEVED.draft(
            text=Content.of(text, level=2), about=("user_2",), sensitivity=2, told_by=("user_2",),
            heard_by=("user_2",), source="user_2")], emitter="memory", correlation="relecture",
            origin=Origin.PROCESS)
        await asyncio.sleep(120)  # l'index de sa mémoire
        done = await call(kernel, "attachment_link", "user_2", piece="chat.jpg", element=text)
        tied = links_rows(kernel)
        again = await call(kernel, "attachment_link", "user_2", piece="chat.jpg", element=text)
        undone = await call(kernel, "attachment_link", "user_2", piece="chat.jpg", element=text, remove=True)
        return file, commit.events[0].seq, done, tied, again, undone, links_rows(kernel)

    file, item, done, tied, again, undone, after = live(tmp_path, scenario)
    assert done.ok and text in done.content and tied == [(file, item, c.BY_HER)]
    assert "déjà relié" in again.content and undone.ok and after == []


# ── La place, l'oubli ─────────────────────────────────────────────────────


class _Frame:
    """Ce que lit la rétention : l'instant et la personne derrière chaque adresse."""

    def __init__(self, now: int, persons: dict[str, str]) -> None:
        self.now = now
        self.persons = persons

    def get(self, key):
        return self.persons.get(key.arg, key.arg)


def test_the_place_is_counted_per_person_all_her_handles_together():
    big = 6 * MIB
    state = AttachmentsState(kept=FrozenDict({
        "user_2": (c.KeptView("a" * 32, 1, big), c.KeptView("b" * 32, 3, big)),
        "mobile_2": (c.KeptView("c" * 32, 2, big),),
        "user_3": (c.KeptView("d" * 32, 1, big),),
    }))
    frame = _Frame(10, {"user_2": "user_2", "mobile_2": "user_2", "user_3": "user_3"})
    due = due_expiries(state, frame, AttachmentsParams(per_person_mb=10))
    # Alice (deux adresses, 18 Mio pour 10) perd ses deux plus anciennes ; Bob (6 Mio) rien
    assert due == [("mobile_2", c.BUDGET, ("c" * 32,)), ("user_2", c.BUDGET, ("a" * 32,))]
    assert due_expiries(state, frame, AttachmentsParams()) == []  # 2 Gio : tout tient, pour toujours


def test_forgetting_a_person_erases_her_pieces_their_links_and_their_vectors(tmp_path):
    async def scenario(kernel, store, reader):
        _seq, [file] = await send(kernel, "user_2", "mon chat", ("chat.jpg", "image/jpeg", PHOTO))
        await kernel.mind.append([mc.BELIEVED.draft(
            text=Content.of("Alice a un chat", level=2), about=("user_2",), sensitivity=2, told_by=("user_2",),
            heard_by=("user_2",), pieces=(file,))], emitter="memory", correlation="relecture",
            origin=Origin.PROCESS)
        await asyncio.sleep(120)
        before = (dict(store.blobs), files_rows(kernel), links_rows(kernel), kernel.ports[c.VECTORS].indexed())
        await kernel.forget("user_2")
        return before, (dict(store.blobs), files_rows(kernel), links_rows(kernel), kernel.ports[c.VECTORS].indexed())

    before, after = live(tmp_path, scenario)
    assert all(before) and after == ({}, [], [], set())


# ── Lire de près : le verdict « intime » ──────────────────────────────────


def test_the_intimate_line_is_read_and_removed_from_what_she_keeps():
    text, sensitive = verdict_line("Une carte d'identité posée sur une table.\nTexte : DUPONT Alice\n**INTIME : oui**")
    assert sensitive and "INTIME" not in text and "DUPONT Alice" in text
    assert verdict_line("Un coucher de soleil.\nintime : non") == ("Un coucher de soleil.", False)
    assert verdict_line("Un coucher de soleil.") == ("Un coucher de soleil.", False)  # sans verdict : rien d'intime
