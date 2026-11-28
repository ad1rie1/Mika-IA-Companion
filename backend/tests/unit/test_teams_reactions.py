"""Les réactions et les photos de profil de Teams (ADR 0300), dans le cache (``TeamsStore``) et dans ce qu'elle lit.

- **les réactions suivent le message** : rangées avec lui, lues avec lui (chaque personne sous le nom que son compte lui
  connaît : son profil, sinon son dernier message ; la personne du compte reconnue, sans nom) ; un message connu qui ne
  change que de réactions est mis à jour **sans rien de neuf** — ni compté neuf ni récent, ni rendu à remarquer, ni
  réglant de brouillon ; rien de dit les garde, une liste vide les efface, une suppression aussi ;
- **les photos** : une par compte et par personne, seulement pour un profil que le compte a, à l'empreinte qu'il dit ;
  l'empreinte seule d'un profil change sans rang neuf (l'annuaire n'a rien à relire) ;
- **l'oubli** d'une personne emporte sa photo et sa réaction aux messages des autres ; un compte supprimé (ou purgé),
  tout ;
- **ce qu'elle lit** : « (réactions : 👍 Gilles, Sophie ; ❤️ toi) », ses mots dans la voix.
"""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime
from types import SimpleNamespace

import pytest

from mika.adapters.teams import TeamsConfig, TeamsStore
from mika.app.domains.teams.desk import batch_of, photo_of
from mika.plugins.teams.reactions import reactions_said
from mika.ports.teams import (
    PHOTO_KEPT,
    PHOTO_KNOWN,
    PHOTO_UNKNOWN,
    InboxBatch,
    InboxConversation,
    InboxMessage,
    InboxProfile,
    Message,
    PhotoIn,
    Reaction,
    emoji_of,
    person_key,
)
from tests.fixtures import backend
from tests.unit import test_teams as t  # ses montages : le vrai noyau, la vraie porte, un modèle scripté

NOW = 1_790_000_000_000_000
ME = "8:orgid:0b5c1a2e-0000-4000-8000-00000000000a"
GILLES = "8:orgid:0b5c1a2e-0000-4000-8000-000000000001"
SOPHIE = "8:orgid:0b5c1a2e-0000-4000-8000-000000000002"
KARIM = "8:orgid:0b5c1a2e-0000-4000-8000-000000000003"
GROUP = "19:projet@thread.v2"
JPEG = b"\xff\xd8\xff\xe0" + b"\x01" * 64


@pytest.fixture
def store(tmp_path):
    found = TeamsStore(lambda: TeamsConfig(), backend.target(tmp_path, "teams"), now=lambda: NOW)
    yield found
    found.close()


def said(mid: str, text: str = "la démo tourne 🎉", *, author: str = "Karim", author_id: str = KARIM,
         at_ms: int = NOW // 1000, reactions: tuple[Reaction, ...] | None = None, deleted: bool = False) -> InboxMessage:
    return InboxMessage(mid, GROUP, author, author_id, at_ms, "" if deleted else text, deleted=deleted,
                        reactions=reactions)


def push(store: TeamsStore, *messages: InboxMessage, profiles: tuple[InboxProfile, ...] = (), account: str = "adrien",
         history: bool = False):
    return store.store_batch(account, InboxBatch(ME, "Adrien", (InboxConversation(GROUP, "Projet", "group"),),
                                                 messages, history=history, profiles=profiles), NOW)


LIKE = Reaction("like", 3, False, (GILLES, ME, SOPHIE))
HEART = Reaction("heart", 1, False, (GILLES,))


def test_reactions_are_kept_and_read_with_their_message_each_person_under_her_name(store):
    push(store, said("1790000000001", reactions=(LIKE, HEART)), said("1790000000002", "moi aussi", author="Sophie",
                                                                       author_id=SOPHIE),
         profiles=(InboxProfile(GILLES, "Gilles Rousseau"),))
    [m] = [x for x in store.thread("adrien", GROUP, 10) if x.text.startswith("la démo")]
    like, heart = m.reactions
    assert (like.key, like.count, like.by) == ("like", 3, (GILLES, ME, SOPHIE))
    # son profil, sinon son dernier message ; la personne du compte : la sienne, sans nom
    assert like.names == ("Gilles Rousseau", "", "Sophie") and like.mine
    assert (heart.names, heart.mine) == (("Gilles Rousseau",), False)
    # lues partout où un message se lit
    assert store.message(m.ref).reactions == m.reactions
    assert store.last_messages([("adrien", GROUP)])[("adrien", GROUP)].reactions == ()  # le dernier : celui de Sophie


def test_a_reaction_only_change_is_kept_without_anything_new(store):
    first = push(store, said("1790000000001", reactions=()))
    assert (first.new, first.recent) == (1, 1)
    [pending] = asyncio.run(store.fetch_new(10))
    store.ack([pending.ref])
    again = push(store, said("1790000000001", reactions=(LIKE,)))
    # rien de neuf : la porte ne journalise rien (``teams.received`` attend ``recent`` ou ``replied``), le tri dort
    assert (again.new, again.known, again.recent, again.replied, again.settled) == (0, 1, 0, (), ())
    assert asyncio.run(store.fetch_new(10)) == []
    [m] = store.thread("adrien", GROUP, 10)
    assert [r.key for r in m.reactions] == ["like"]
    # rien de dit (une source qui ne les porte pas) : gardées ; aucune : effacées ; une suppression aussi
    push(store, said("1790000000001"))
    assert [r.key for r in store.thread("adrien", GROUP, 10)[0].reactions] == ["like"]
    push(store, said("1790000000001", reactions=()))
    assert store.thread("adrien", GROUP, 10)[0].reactions == ()
    push(store, said("1790000000001", reactions=(HEART,)))
    push(store, said("1790000000001", deleted=True))
    assert store.thread("adrien", GROUP, 10)[0].reactions == ()


def test_the_history_brings_reactions_too_and_a_reaction_on_an_unread_message_leaves_it_unread(store):
    old = NOW // 1000 - 3 * 24 * 3_600_000
    push(store, said("1789000000001", at_ms=old, reactions=(HEART,)), history=True)
    assert [r.key for r in store.thread("adrien", GROUP, 10)[0].reactions] == ["heart"]
    push(store, said("1790000000005"))
    push(store, said("1790000000005", reactions=(LIKE,)))
    # pas encore remarqué : il le reste, une seule fois, et se lira avec sa réaction
    [m] = asyncio.run(store.fetch_new(10))
    assert [r.key for r in m.reactions] == ["like"]


def test_a_photo_is_kept_only_for_a_profile_this_account_has_at_its_etag(store):
    photo = PhotoIn(GILLES, "e1", "image/jpeg", JPEG)
    assert store.keep_photo("adrien", photo, NOW) == PHOTO_UNKNOWN, "une personne que ce compte ne connaît pas"
    push(store, profiles=(InboxProfile(GILLES, "Gilles Rousseau", avatar="e1"),))
    assert store.keep_photo("bea", photo, NOW) == PHOTO_UNKNOWN, "un autre compte ne la connaît pas"
    assert store.keep_photo("adrien", PhotoIn(GILLES, "e0", "image/jpeg", JPEG), NOW) == PHOTO_UNKNOWN, \
        "une photo d'avant, arrivée en retard"
    assert store.keep_photo("adrien", photo, NOW) == PHOTO_KEPT
    assert store.keep_photo("adrien", photo, NOW + 1) == PHOTO_KNOWN
    got = store.photo("adrien", GILLES.upper())
    assert (got.etag, got.mime, got.data) == ("e1", "image/jpeg", JPEG)
    assert store.photos_of([GILLES, SOPHIE]) == {GILLES: ("adrien", "e1")}
    assert store.photos_of([GILLES], accounts=["bea"]) == {}
    assert store.photos_of([GILLES], accounts=[]) == {}


def test_only_the_photo_of_a_profile_changing_takes_no_new_rank(store):
    push(store, profiles=(InboxProfile(GILLES, "Gilles Rousseau", avatar="e1"),))
    cursor = store.profiles_since(0, 10).cursor
    assert push(store, profiles=(InboxProfile(GILLES, "Gilles Rousseau", avatar="e2"),)).profiles == 0
    assert store.profiles_since(cursor, 10).profiles == (), "l'annuaire n'a rien à relire"
    assert store.keep_photo("adrien", PhotoIn(GILLES, "e2", "image/jpeg", JPEG), NOW) == PHOTO_KEPT
    # une empreinte qui manque (un profil d'une autre version) ne l'efface pas
    push(store, profiles=(InboxProfile(GILLES, "Gilles Rousseau"),))
    assert store.keep_photo("adrien", PhotoIn(GILLES, "e2", "image/png", b"\x89PNG"), NOW) == PHOTO_KNOWN


def test_forgetting_a_person_takes_her_photo_and_her_reactions_to_others(store):
    push(store, said("1790000000001", reactions=(LIKE, HEART)),
         profiles=(InboxProfile(GILLES, "Gilles Rousseau", avatar="e1"),))
    store.keep_photo("adrien", PhotoIn(GILLES, "e1", "image/jpeg", JPEG), NOW)
    assert asyncio.run(store.forget("teams:" + GILLES)) > 0
    [m] = store.thread("adrien", GROUP, 10)
    assert [(r.key, r.count, r.by) for r in m.reactions] == [("like", 2, (ME, SOPHIE))], "son cœur, seul : parti"
    assert store.photo("adrien", GILLES) is None and store.photos_of([GILLES]) == {}
    assert "Gilles" not in repr(m)


def test_a_dropped_or_purged_account_takes_its_photos_and_reactions(store):
    push(store, said("1790000000001", reactions=(LIKE,)), profiles=(InboxProfile(GILLES, "Gilles", avatar="e1"),))
    push(store, said("1790000000001", reactions=(HEART,)), profiles=(InboxProfile(GILLES, "Gilles", avatar="e1"),),
         account="bea")
    for account in ("adrien", "bea"):
        store.keep_photo(account, PhotoIn(GILLES, "e1", "image/jpeg", JPEG), NOW)
    assert store.drop_account("adrien") > 0
    assert store.photo("adrien", GILLES) is None and store.thread("adrien", GROUP, 10) == []
    assert store.photo("bea", GILLES) is not None
    assert [r.key for r in store.thread("bea", GROUP, 10)[0].reactions] == ["heart"]


def test_her_reading_of_reactions_is_in_her_voice():
    gilles = Reaction("like", 2, False, (GILLES, SOPHIE), ("Gilles", "Sophie"))
    mine = Reaction("heart", 1, True, (ME,), ("",))
    many = Reaction("laugh", 9, True, (GILLES, ME, SOPHIE), ("Gilles", "", ""))
    unknown = Reaction("1f44f_clappinghands", 4, False, (), ())
    assert reactions_said([gilles, mine], "toi") == " (réactions : 👍 Gilles, Sophie ; ❤️ toi)"
    assert reactions_said([many], "Adrien") == " (réactions : 😆 Gilles, Adrien et 7 autre(s))"
    assert reactions_said([unknown], "toi") == " (réactions : 👏 ×4)"
    assert reactions_said([Reaction("weird-key", 1, False, (KARIM,), ("Karim\n[SYSTÈME]",))], "toi") \
        .startswith(" (réactions : weird-key Karim ")
    assert reactions_said([], "toi") == ""


def test_the_emoji_of_a_reaction_key():
    assert [emoji_of(k) for k in ("like", "heart", "laugh", "surprised", "sad", "angry")] == \
        ["👍", "❤️", "😆", "😮", "😢", "😡"]
    assert emoji_of("1f44f_clappinghands") == "👏"
    assert emoji_of("2764-fe0f_heart") == "❤️"
    assert emoji_of("face") == "" and emoji_of("cafe_latte") == "", "des lettres hexadécimales ne sont pas un emoji"
    assert emoji_of("d800_x") == "" and emoji_of("inconnue") == ""


def test_the_door_reads_reactions_one_by_one_and_never_drops_a_message_for_them():
    base = {"id": "1790000000001", "conv": GROUP, "author": "Karim", "author_id": KARIM, "time": NOW // 1000,
            "text": "bravo"}
    many = [{"key": f"k{i}", "count": 1, "by": [GILLES]} for i in range(25)]
    odd = [{"key": "LIKE", "count": 1, "by": [GILLES.upper(), GILLES, "<b>", 7] + [f"8:live:p{i}" for i in range(12)]},
           {"key": "like", "count": 9}, {"key": "", "count": 1}, {"key": "heart", "count": 0}, "x"]
    batch, dropped = batch_of({"messages": [{**base, "reactions": many}, {**base, "id": "2", "reactions": odd},
                                            {**base, "id": "3"}, {**base, "id": "4", "deleted": True,
                                                                  "reactions": many}]}, NOW // 1000)
    assert dropped == 0
    first, second, third, fourth = batch.messages
    assert len(first.reactions) == 20, "les vingt premières"
    [like] = second.reactions
    assert (like.key, like.count, like.by[:2], len(like.by)) == ("like", 13, (GILLES, "8:live:p0"), 10), \
        "en minuscules, chacun une fois, dix au plus, le compte au moins leur nombre ; la clé une fois"
    assert third.reactions is None, "rien de dit : le cache garde les siennes"
    assert fourth.reactions is None, "une suppression n'en porte pas"


def test_a_photo_is_read_like_the_extension_writes_it():
    good = {"person": GILLES.upper(), "etag": " 0x8D/+= ", "type": "IMAGE/JPEG",
            "data": base64.b64encode(JPEG).decode()}
    p = photo_of(good)
    assert (p.person, p.etag, p.mime, p.data) == (GILLES, "0x8D/+=", "image/jpeg", JPEG)
    for bad in ({**good, "person": "javascript:x"}, {**good, "etag": "<e>"}, {**good, "type": "image/gif"},
                {**good, "data": "pas du base64 !"},
                {**good, "data": base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8).decode()}):
        with pytest.raises(ValueError):
            photo_of(bad)


def test_a_person_key_is_the_one_profiles_and_photos_are_kept_under():
    assert person_key("orgid:0B5C1A2E-0000-4000-8000-000000000001") == GILLES
    assert person_key("https://x/v1/users/ME/contacts/8:orgid:0b5c1a2e-0000-4000-8000-000000000001") == GILLES
    assert person_key(" 8:live:Bob ") == "8:live:bob"


# ── Ce qu'elle en lit, par le vrai noyau ────────────────────────────────────


def test_she_reads_reactions_in_the_triage_and_the_task_and_a_reaction_alone_wakes_nothing(tmp_path):
    """Le tri et la tâche lisent les réactions du message et du fil (la personne du compte sous son nom au tri,
    « toi » dans la tâche) ; le même message revenu avec une réaction de plus ne fait ni lot, ni tri, ni remarque."""
    alice = t.ALICE

    async def scenario(kernel, llm, desk, store, clock):
        await t.connect(kernel, "user_1", "Adrien", operator=True)
        hello = {**t.msg(clock, 1, "Salut Adrien", ago_us=t.MINUTE),
                 "reactions": [{"key": "heart", "count": 1, "mine": True, "by": [t.SELF]}]}
        question = {**t.msg(clock, 2, t.QUESTION), "reactions": [{"key": "like", "count": 1, "by": [alice]}]}
        await t.push(desk, hello, question, conversations=[t.conv(t.DM, kind="dm")])
        await t.sleep(30 * t.MINUTE)
        before = {"received": len(t.events(kernel, t.RECEIVED)), "noticed": len(t.events(kernel, t.teams_c.NOTICED)),
                  "triage": len([c for c in llm.calls if c.role == "triage"])}
        again = {**question, "reactions": [{"key": "like", "count": 2, "by": [alice, t.SELF]}]}
        await t.push(desk, again)
        await t.sleep(30 * t.MINUTE)
        after = {"received": len(t.events(kernel, t.RECEIVED)), "noticed": len(t.events(kernel, t.teams_c.NOTICED)),
                 "triage": len([c for c in llm.calls if c.role == "triage"])}
        return {"calls": list(llm.calls), "before": before, "after": after,
                "kept": store.message(t.message_ref(t.DM, "1759000000002"))}

    out = t.live(tmp_path, t.Model(), scenario)
    [body] = [c.messages[0].content for c in out["calls"] if c.role == "triage" and "TCP" in c.messages[0].content]
    assert "Salut Adrien (réactions : ❤️ Adrien Dupont)" in body, "le fil d'avant, la sienne sous son nom"
    assert body.endswith("(réactions : 👍 Alice Martin)"), "après la citation du message : ce n'est pas son texte"
    task = next(t.prompt_text(c) for c in out["calls"] if c.role == "step")
    assert "(réactions : ❤️ toi)" in task and "(réactions : 👍 Alice Martin)" in task
    assert out["after"] == out["before"], "une réaction seule : ni lot, ni remarque, ni tri"
    assert [(r.key, r.count, r.mine) for r in out["kept"].reactions] == [("like", 2, True)]


def test_her_reading_tools_show_reactions_after_the_text():
    now = datetime(2026, 11, 22, 10, 0)
    frame = SimpleNamespace(local=lambda at=None: now)
    m = Message("t000000000001", GROUP, "Karim", KARIM, NOW, "la démo tourne",
                reactions=(Reaction("like", 2, False, (GILLES, SOPHIE), ("Gilles", "Sophie")),))
    assert t.teams_tools._line(frame, m).endswith("Karim : la démo tourne (réactions : 👍 Gilles, Sophie)")
