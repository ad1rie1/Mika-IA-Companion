"""Partager ce qui est à soi (ADR 0188) : la règle du propriétaire s'étend à qui l'on partage, au niveau donné.

- une boîte (un compte Teams) partagée sert aussi avec la personne, reconnue, en tête-à-tête, si son partage atteint ce
  que l'outil demande : lire, préparer, s'en servir ;
- jamais dans un salon, jamais à une autre personne, jamais quand rien n'est partagé ;
- ses outils lui sont offerts dès qu'on lui partage quelque chose, réduits à ce qu'on lui partage ;
- la règle est dite une fois (``vocab.ownership``) : le courrier et Teams répondent pareil, ce qu'une personne a se lit
  au même endroit.
"""

from __future__ import annotations

from itertools import product
from types import SimpleNamespace as NS

import pytest

from mika.contracts import identity as identity_c
from mika.kernel.frame import Audience, EpisodeRef, Frame
from mika.plugins.email import EmailParams, boxes_here, owns_a_box
from mika.plugins.teams import TeamsParams, accounts_here, owns_an_account
from mika.vocab.access import SELF, SHARE_PREPARE, SHARE_READ, SHARE_USE, reaches
from mika.vocab.episodes import Kind
from mika.vocab.ownership import (
    OWNED,
    SHARED,
    best_handle,
    facing,
    held,
    must_approve,
    owns_one,
    reach,
    shared_with,
)
from mika.vocab.privacy import ChannelTrust

BOXES = ("perso", "pro")
NADIA = Audience(persons=("user_2",), channel="web", public=False, trust=ChannelTrust.AUTHENTICATED.value,
                 owner=False, person="user_2")
LEA = Audience(persons=("user_3",), channel="web", public=False, trust=ChannelTrust.AUTHENTICATED.value,
               owner=False, person="user_3")
ROOM = Audience(persons=("user_1", "user_2"), channel="web", public=True, trust=ChannelTrust.AUTHENTICATED.value,
                owner=True, person="user_2")


class OwnersFrame(Frame):
    """Un cadre dont les propriétaires sont ``owners`` (le fait ``identity.owners``), et rien d'autre."""

    __slots__ = ("owners",)

    def get(self, ref):  # noqa: ANN001, ANN201 — le seul fait que lit la règle ici
        return self.owners if ref is identity_c.OWNERS else None


def owners_frame(audience: Audience, params, owners: tuple[str, ...] = ("user_1",)) -> Frame:
    """Un cadre sur ces paramètres ; ses propriétaires : ``owners`` (``user_1`` d'office)."""
    env = NS(params_of=lambda owner, root: params, tools={}, access_tables=None, closeness=None)
    frame = OwnersFrame(None, 0, env, audience, EpisodeRef("e", Kind.REPLY, target="user_2"))
    frame.owners = owners
    return frame


def mail_frame(audience: Audience, shares: dict) -> Frame:
    return owners_frame(audience, EmailParams(shares=shares))


def teams_frame(audience: Audience, shares: dict) -> Frame:
    return owners_frame(audience, TeamsParams(shares=shares))


def test_the_levels_are_ordered():
    assert reaches(SHARE_USE, SHARE_READ) and reaches(SHARE_PREPARE, SHARE_READ) and reaches(SHARE_READ, SHARE_READ)
    assert not reaches(SHARE_READ, SHARE_PREPARE) and not reaches(SHARE_PREPARE, SHARE_USE)
    assert not reaches("", SHARE_READ) and not reaches(SHARE_USE, "")


def test_a_shared_box_serves_her_at_her_level():
    read = {"perso": {"personne:user_2": SHARE_READ}}
    assert boxes_here(mail_frame(NADIA, read), BOXES, SHARE_READ) == ("perso",)
    assert boxes_here(mail_frame(NADIA, read), BOXES, SHARE_PREPARE) == ()  # lire ne prépare pas
    assert boxes_here(mail_frame(NADIA, read), BOXES) == ()  # par défaut, s'en servir : lire ne range rien
    prepare = {"perso": {"personne:user_2": SHARE_PREPARE}}
    assert boxes_here(mail_frame(NADIA, prepare), BOXES, SHARE_PREPARE) == ("perso",)
    assert boxes_here(mail_frame(NADIA, prepare), BOXES, SHARE_USE) == ()
    use = {"perso": {"personne:user_2": SHARE_USE}}
    assert boxes_here(mail_frame(NADIA, use), BOXES, SHARE_USE) == ("perso",)
    assert boxes_here(mail_frame(LEA, use), BOXES, SHARE_READ) == ()  # pas à une autre personne
    assert boxes_here(mail_frame(ROOM, use), BOXES, SHARE_READ) == ()  # jamais à plusieurs
    assert boxes_here(mail_frame(NADIA, {}), BOXES, SHARE_READ) == ()  # rien de partagé : rien


def test_her_mail_tools_are_offered_once_something_is_shared():
    assert owns_a_box(NADIA, Kind.REPLY, mail_frame(NADIA, {"pro": {"personne:user_2": SHARE_READ}}))
    assert not owns_a_box(LEA, Kind.REPLY, mail_frame(LEA, {"pro": {"personne:user_2": SHARE_READ}}))
    assert not owns_a_box(ROOM, Kind.REPLY, mail_frame(ROOM, {"pro": {"personne:user_2": SHARE_READ}}))


def test_a_shared_teams_account_follows_the_same_rule():
    shares = {"principal": {"personne:user_2": SHARE_PREPARE}}
    assert accounts_here(teams_frame(NADIA, shares), ("principal",), None, SHARE_PREPARE) == ("principal",)
    assert accounts_here(teams_frame(NADIA, shares), ("principal",), None, SHARE_USE) == ()
    assert accounts_here(teams_frame(ROOM, shares), ("principal",), None, SHARE_READ) == ()
    assert owns_an_account(NADIA, Kind.REPLY, teams_frame(NADIA, shares))
    assert not owns_an_account(LEA, Kind.REPLY, teams_frame(LEA, shares))


YOU = Audience(persons=("user_1",), channel="web", public=False, trust=ChannelTrust.AUTHENTICATED.value, owner=True,
               person="user_1")


def owned_frame(audience: Audience, shares: dict, owners: dict) -> Frame:
    return owners_frame(audience, EmailParams(shares=shares, owners=owners))


def test_her_tools_are_offered_at_the_level_they_need():
    from mika.plugins.email import owns_a_box_to_prepare, owns_a_box_to_use
    read = mail_frame(NADIA, {"pro": {"personne:user_2": SHARE_READ}})
    assert owns_a_box(NADIA, Kind.REPLY, read)  # lire : ses outils qui lisent
    assert not owns_a_box_to_prepare(NADIA, Kind.REPLY, read) and not owns_a_box_to_use(NADIA, Kind.REPLY, read)
    prepare = mail_frame(NADIA, {"pro": {"personne:user_2": SHARE_PREPARE}})
    assert owns_a_box_to_prepare(NADIA, Kind.REPLY, prepare) and not owns_a_box_to_use(NADIA, Kind.REPLY, prepare)
    use = mail_frame(NADIA, {"pro": {"personne:user_2": SHARE_USE}})
    assert owns_a_box_to_use(NADIA, Kind.REPLY, use)


def test_a_box_shared_with_one_of_her_owners_serves_her_too():
    shared = owned_frame(YOU, {"nadia_box": {"personne:user_1": SHARE_READ}}, {"nadia_box": "personne:user_2"})
    assert "nadia_box" in boxes_here(shared, ("nadia_box",), SHARE_READ)  # une propriétaire, en tête-à-tête
    assert "nadia_box" not in boxes_here(shared, ("nadia_box",), SHARE_PREPARE)


def test_what_she_prepares_for_a_prepare_share_waits_for_the_owner():
    from mika.plugins.email import OWNED, SHARED, owner_must_approve, reach_of
    prepare = owned_frame(NADIA, {"pro": {"personne:user_2": SHARE_PREPARE}}, {})
    assert owner_must_approve(prepare, "pro")  # quoi que dise la règle du canal de la boîte
    assert reach_of(prepare, "pro", SHARE_PREPARE) == SHARED
    use = owned_frame(NADIA, {"pro": {"personne:user_2": SHARE_USE}}, {})
    assert not owner_must_approve(use, "pro")  # s'en servir : comme le propriétaire, la règle du canal décide
    own = owned_frame(NADIA, {}, {"nadia_box": "personne:user_2"})
    assert not owner_must_approve(own, "nadia_box") and reach_of(own, "nadia_box") == OWNED
    assert not owner_must_approve(owned_frame(NADIA, {}, {}), "pro")  # rien de partagé : rien à imposer


def test_teams_follows_the_same_levels():
    from mika.plugins.teams import owner_must_approve, owns_an_account_to_prepare
    read = teams_frame(NADIA, {"principal": {"personne:user_2": SHARE_READ}})
    assert owns_an_account(NADIA, Kind.REPLY, read) and not owns_an_account_to_prepare(NADIA, Kind.REPLY, read)
    prepare = teams_frame(NADIA, {"principal": {"personne:user_2": SHARE_PREPARE}})
    assert owner_must_approve(prepare, "principal")
    assert not owner_must_approve(teams_frame(NADIA, {"principal": {"personne:user_2": SHARE_USE}}), "principal")




def test_a_box_of_yours_never_waits_for_another_owner():
    from mika.plugins.email import owner_must_approve
    from mika.plugins.teams import owner_must_approve as teams_must_approve
    bea = Audience(persons=("user_3",), channel="web", public=False, trust=ChannelTrust.AUTHENTICATED.value,
                   owner=True, person="user_3")
    shared = {"atelier": {"personne:user_3": SHARE_READ}}  # un partage resté d'avant : elle en est propriétaire
    assert not owner_must_approve(owners_frame(bea, EmailParams(shares=shared), ("user_1", "user_3")), "atelier")
    assert not teams_must_approve(owners_frame(bea, TeamsParams(shares=shared), ("user_1", "user_3")), "atelier")
    assert owner_must_approve(owners_frame(bea, EmailParams(shares=shared), ("user_1",)), "atelier")  # pas à elle


# ── La règle, dite une fois ───────────────────────────────────────────────

NADIA_KEY, YOU_KEY = "personne:user_2", "personne:user_1"
ALONE = Audience(persons=(), channel="internal", public=False, trust=ChannelTrust.INTERNAL.value, owner=False)


def test_who_is_facing_as_an_owner_and_as_someone_shared_with():
    assert facing(NADIA, Kind.REPLY) == shared_with(NADIA, Kind.REPLY) == NADIA_KEY
    assert facing(YOU, Kind.REPLY) == "" and shared_with(YOU, Kind.REPLY) == YOU_KEY  # toi : on peut te partager
    assert facing(ROOM, Kind.REPLY) == "" and shared_with(ROOM, Kind.REPLY) == ""  # jamais à plusieurs
    assert facing(None, "") == "" and shared_with(ALONE, Kind.WORK) == ""


@pytest.mark.parametrize(("owner", "given", "audience", "family", "task", "need", "expected"), [
    ("", {}, YOU, True, False, SHARE_USE, OWNED),  # les tiennes, là où sa famille le permet
    ("", {}, YOU, False, False, SHARE_USE, ""),
    (SELF, {}, ALONE, True, False, SHARE_USE, OWNED),  # les siennes : quand elle travaille
    (SELF, {}, YOU, True, False, SHARE_USE, ""),
    (SELF, {}, ALONE, False, False, SHARE_USE, ""),
    (NADIA_KEY, {}, NADIA, False, False, SHARE_USE, OWNED),  # celle d'une personne : avec elle
    (NADIA_KEY, {}, LEA, True, False, SHARE_USE, ""),
    (NADIA_KEY, {}, ROOM, True, False, SHARE_USE, ""),
    (NADIA_KEY, {}, ALONE, True, False, SHARE_USE, ""),
    (NADIA_KEY, {}, ALONE, True, True, SHARE_USE, OWNED),  # une tâche de rédaction : celle de son mail
    (NADIA_KEY, {}, ALONE, False, True, SHARE_USE, ""),
    (NADIA_KEY, {}, YOU, True, True, SHARE_USE, ""),  # une tâche ne vaut que quand elle travaille
    (NADIA_KEY, {YOU_KEY: SHARE_READ}, YOU, False, False, SHARE_READ, SHARED),  # partagée : à son niveau
    (NADIA_KEY, {YOU_KEY: SHARE_READ}, YOU, False, False, SHARE_PREPARE, ""),
    (NADIA_KEY, {YOU_KEY: SHARE_USE}, ROOM, True, False, SHARE_READ, ""),
])
def test_how_an_account_serves_here(owner, given, audience, family, task, need, expected):
    assert reach(owner, given, audience, Kind.WORK if audience is ALONE else Kind.REPLY, need, family=family,
                 task=task) == expected


@pytest.mark.parametrize(("audience", "owner", "level", "need"), product(
    (YOU, NADIA, LEA, ROOM), ("", SELF, NADIA_KEY, YOU_KEY), ("", SHARE_READ, SHARE_PREPARE, SHARE_USE),
    (SHARE_READ, SHARE_PREPARE, SHARE_USE)))
def test_mail_and_teams_answer_alike(audience, owner, level, need):
    """Une règle d'accès, pas deux : une boîte et un compte Teams aux mêmes réglages servent aux mêmes personnes."""
    owners, shares = ({"x": owner} if owner else {}), ({"x": {NADIA_KEY: level}} if level else {})
    mail, teams = (owners_frame(audience, P(owners=owners, shares=shares)) for P in (EmailParams, TeamsParams))
    assert boxes_here(mail, ("x",), need) == accounts_here(teams, ("x",), None, need)
    assert owns_a_box(audience, Kind.REPLY, mail, need) == owns_an_account(audience, Kind.REPLY, teams, need)


def test_who_holds_one_says_it_once():
    assert owns_one({"a": NADIA_KEY}, {}, NADIA, Kind.REPLY)
    assert not owns_one({"a": NADIA_KEY}, {}, LEA, Kind.REPLY)
    assert owns_one({}, {"a": {NADIA_KEY: SHARE_READ}}, NADIA, Kind.REPLY)
    assert not owns_one({}, {"a": {NADIA_KEY: SHARE_READ}}, NADIA, Kind.REPLY, SHARE_PREPARE)
    assert not owns_one({"a": YOU_KEY}, {}, YOU, Kind.REPLY)  # toi : ta famille d'outils, pas un compte à ton nom


def test_what_she_prepares_waits_only_on_a_prepare_share():
    given = {NADIA_KEY: SHARE_PREPARE}
    assert must_approve("", given, NADIA_KEY, ("user_1",))
    assert not must_approve("", given, NADIA_KEY, ("user_2",))  # une boîte « à toi », et elle est une propriétaire
    assert not must_approve(NADIA_KEY, given, NADIA_KEY, ())  # sa boîte : un partage n'y retire rien
    assert must_approve(YOU_KEY, given, NADIA_KEY, ("user_2",))  # la boîte d'une autre : le partage décide
    assert not must_approve("", {NADIA_KEY: SHARE_USE}, NADIA_KEY, ())  # s'en servir : la règle du canal
    assert not must_approve("", {NADIA_KEY: SHARE_READ}, "", ())  # personne pour qui elle écrit
    assert not must_approve("", {}, NADIA_KEY, ())  # rien de partagé : rien à imposer


def test_what_a_person_holds_and_at_which_level():
    keys, owners = ("commune", "sienne", "nadia", "autre"), {"sienne": SELF, "nadia": NADIA_KEY, "autre": YOU_KEY}
    shares = {"autre": {NADIA_KEY: SHARE_READ}, "commune": {NADIA_KEY: SHARE_PREPARE}}
    assert held(keys, owners, shares, NADIA_KEY, owner=False) == {"commune": SHARE_PREPARE, "nadia": OWNED,
                                                                  "autre": SHARE_READ}
    # une de ses propriétaires : ce qui n'a pas de propriétaire nommé est à elle, le partage n'y ajoute rien
    assert held(keys, owners, shares, NADIA_KEY, owner=True) == {"commune": OWNED, "nadia": OWNED,
                                                                 "autre": SHARE_READ}
    assert held(keys, owners, {}, "personne:user_3", owner=False) == {}


def test_who_decides_is_found_where_she_is():
    assert best_handle(("a", "b", "c"), {"b"}, {"c"}) == "b"  # présente d'abord
    assert best_handle(("a", "b", "c"), set(), {"c"}) == "c"  # sinon où l'on peut lui écrire
    assert best_handle(("a", "b"), set(), set()) == "a"
    assert best_handle((), {"a"}, {"a"}) == ""
