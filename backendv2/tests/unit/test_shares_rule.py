"""Partager ce qui est à soi (ADR 0188) : la règle du propriétaire s'étend à qui l'on partage, au niveau donné.

- une boîte (un compte Teams) partagée sert aussi avec la personne, reconnue, en tête-à-tête, si son partage atteint ce
  que l'outil demande : lire, préparer, s'en servir ;
- jamais dans un salon, jamais à une autre personne, jamais quand rien n'est partagé ;
- ses outils lui sont offerts dès qu'on lui partage quelque chose, réduits à ce qu'on lui partage.
"""

from __future__ import annotations

from types import SimpleNamespace as NS

from mika.contracts import identity as identity_c
from mika.kernel.frame import Audience, EpisodeRef, Frame
from mika.plugins.email import EmailParams, boxes_here, owns_a_box
from mika.plugins.teams import TeamsParams, accounts_here, owns_an_account
from mika.vocab.access import SHARE_PREPARE, SHARE_READ, SHARE_USE, reaches
from mika.vocab.episodes import Kind
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
