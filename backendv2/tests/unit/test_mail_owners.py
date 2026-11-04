"""À qui est une boîte (ADR 0185) : une boîte sert à son propriétaire.

- les tiennes (sans propriétaire nommé) : toi en privé, elle quand elle travaille — jamais une autre personne, ni un
  salon, ni une inconnue ;
- les siennes : elle seule, au travail — ni toi, ni une autre personne ;
- celles d'une personne : avec elle, reconnue, en tête-à-tête ; ses outils de courrier lui sont offerts, réduits à
  ses boîtes : elle n'y voit ni tes mails, ni tes dossiers, ni tes brouillons, ni tes envois ;
- une tâche de rédaction voit la boîte de son mail ;
- elle n'annonce un mail important que d'une de tes boîtes ;
- dans les réglages, une boîte est à toi (vide), à elle, ou à une personne — rien d'autre.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace as NS

import pytest
from pydantic import ValidationError

from mika.adapters.mail.config import MailAccount
from mika.kernel.frame import Audience, EpisodeRef, Frame
from mika.plugins.email import EmailParams, EmailState, Seen, announceable, boxes_here, owns_a_box
from mika.plugins.email.boxes import Boxes
from mika.plugins.email.tools import _port, email_accounts
from mika.ports.mail import AccountInfo, Draft, Mail, MailQuery
from mika.sim.outside import FakeMail
from mika.vocab.episodes import Kind, task_target
from mika.vocab.privacy import ChannelTrust

OWNERS = {"elle_box": "elle", "nadia_box": "personne:user_2"}
BOXES = ("perso", "elle_box", "nadia_box")
YOU = Audience(persons=("user_1",), channel="web", public=False, trust=ChannelTrust.AUTHENTICATED.value, owner=True,
               person="user_1")
NADIA = Audience(persons=("user_2",), channel="web", public=False, trust=ChannelTrust.AUTHENTICATED.value,
                 owner=False, person="user_2")
ROOM = Audience(persons=("user_1", "user_2"), channel="web", public=True, trust=ChannelTrust.AUTHENTICATED.value,
                owner=True, person="user_1")
WORKING = Audience(persons=(), channel="internal", public=False, trust=ChannelTrust.INTERNAL.value, owner=True)


def frame(audience: Audience, kind: str = Kind.REPLY, target: str = "user_1", owners=OWNERS) -> Frame:
    env = NS(params_of=lambda owner, root: EmailParams(owners=owners), tools={}, access_tables=None, closeness=None)
    return Frame(None, 0, env, audience, EpisodeRef("e", kind, target=target))


def test_a_box_serves_its_owner():
    assert boxes_here(frame(YOU), BOXES) == ("perso",)  # toi : les tiennes, pas les siennes, pas celles de Nadia
    assert boxes_here(frame(NADIA), BOXES) == ("nadia_box",)  # Nadia, reconnue en privé : la sienne seulement
    assert boxes_here(frame(WORKING, Kind.STEP, "goal:1"), BOXES) == ("perso", "elle_box")  # elle seule : les tiennes, les siennes
    assert boxes_here(frame(ROOM), BOXES) == ()  # à plusieurs : aucune
    # une tâche de rédaction : la boîte de son mail, même celle de Nadia (on la lui a demandée)
    task = task_target("email", "nadia_box:<m1@exemple.fr>")
    assert "nadia_box" in boxes_here(frame(WORKING, Kind.TASK, task), BOXES)
    # sans propriétaire nommé, tout est à toi : rien ne change d'avant
    assert boxes_here(frame(YOU, owners={}), BOXES) == BOXES


def test_her_tools_are_offered_to_whoever_owns_a_box():
    assert owns_a_box(NADIA, Kind.REPLY, frame(NADIA))
    assert not owns_a_box(NADIA, Kind.REPLY, frame(NADIA, owners={"elle_box": "elle"}))  # rien à elle
    assert not owns_a_box(YOU, Kind.REPLY, frame(YOU))  # toi : ta famille d'outils décide, comme avant
    assert not owns_a_box(ROOM, Kind.REPLY, frame(ROOM))  # jamais à plusieurs
    assert not owns_a_box(NADIA, Kind.REPLY, None)  # une console qui juge sans ce qu'elle vit : personne
    from mika.plugins.email import EMAIL, owns_a_box_to_prepare, owns_a_box_to_use
    # chacun selon ce qu'il demande (ADR 0188) : préparer une réponse, ranger, sinon lire
    wanted = {"email_draft": owns_a_box_to_prepare, "email_tidy": owns_a_box_to_use}
    assert all(t.owned is wanted.get(t.name, owns_a_box) for t in EMAIL.tools if t.owner_only)


def _mail(n: int, account: str) -> Mail:
    return Mail(f"<m{n}@exemple.fr>", "Alice <alice@exemple.fr>", "alice@exemple.fr", f"Objet {n}", 1_000 + n,
                "Bonjour.", to="x@exemple.fr", account=account)


def test_her_tools_see_only_the_boxes_of_whoever_is_there():
    fake = FakeMail(boxes=[AccountInfo(k, k.capitalize(), f"{k}@exemple.fr", ready=True, can_send=True)
                           for k in BOXES])
    for n, box in enumerate(BOXES, start=1):
        fake.deliver(_mail(n, box))
    view = Boxes(fake, ("nadia_box",))
    assert [a.key for a in view.accounts()] == ["nadia_box"] and view.account("perso") is None
    assert [m.account for m in view.messages_page(MailQuery()).items] == ["nadia_box"]
    assert not view.messages_page(MailQuery(account="perso")).items  # nommer une autre boîte ne l'ouvre pas
    assert asyncio.run(view.get("perso:<m1@exemple.fr>")) is None
    assert asyncio.run(view.get("nadia_box:<m3@exemple.fr>")) is not None
    with pytest.raises(ValueError):
        view.save_draft(Draft(id="", account="perso", to="a@b.fr", subject="s", body="b"))
    # par l'outil : Nadia ne voit que sa boîte ; toi, les tiennes ; personne en salon
    ctx = NS(ports={"mail": fake}, frame=frame(NADIA))
    said = asyncio.run(email_accounts(None, ctx))
    assert "nadia_box" in said and "perso" not in said and "elle_box" not in said
    port, refused = _port(NS(ports={"mail": fake}, frame=frame(ROOM)))
    assert port is None and refused is not None and not refused.ok


def test_she_announces_only_mail_from_your_boxes():
    def seen(account: str) -> Seen:
        return Seen(1, "Alice", "alice@exemple.fr", 0.95, False, 0, "", account=account)
    from mika.kernel.state import FrozenDict
    s = EmailState(mails=FrozenDict({"perso:<1>": seen("perso"), "nadia_box:<2>": seen("nadia_box"),
                                     "elle_box:<3>": seen("elle_box")}))
    assert announceable(s, 10, EmailParams(owners=OWNERS)) == ("perso:<1>",)


class _Facts:
    """Ce qu'un cadre sait : ses paramètres, quelques faits (une adresse de Nadia, présente)."""

    def __init__(self, owners, facts):
        self.env = NS(params_of=lambda owner, root: EmailParams(owners=owners), tools={}, access_tables=None,
                      closeness=None)
        self.root, self.facts = None, facts

    def get(self, key):
        return self.facts.get(key, ())


def test_a_send_from_a_persons_box_is_hers_to_approve():
    from mika.contracts import identity as identity_c
    from mika.contracts import presence as presence_c
    from mika.plugins.email import approver_name, approver_of
    facts = {identity_c.HANDLES("user_2"): ("web:nadia", "mobile:nadia"), presence_c.PRESENT: ("mobile:nadia",)}
    seen = _Facts(OWNERS, facts)
    assert approver_of(seen, "nadia_box") == "mobile:nadia"  # sa carte, là où elle est
    assert approver_of(seen, "perso") == "" and approver_of(seen, "elle_box") == ""  # la console, comme avant
    assert approver_name(seen, "nadia_box") == "la personne à qui est cette boîte"  # son prénom, s'il est connu


def test_a_box_is_yours_hers_or_a_persons():
    assert MailAccount(owner="").owner == "" and MailAccount(owner="elle").owner == "elle"
    assert MailAccount(owner=" personne:user_2 ").owner == "personne:user_2"
    assert MailAccount(owner="elle").info("x").owner == "elle"
    for bad in ("nadia", "personne:", "tous"):
        with pytest.raises(ValidationError):
            MailAccount(owner=bad)
