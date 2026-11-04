"""Les bornes de l'API par personne (ADR 0187) : un essai compté avant d'attendre, rendu s'il réussit ; des essais qui
font joindre un serveur, bornés par compte ; une création redite avec la même clé, faite une seule fois ; des réglages
relus puis réécrits d'un seul tenant (deux personnes qui enregistrent en même temps ne s'effacent pas) ; et les mots
d'une ligne, dits à qui n'est pas une de ses propriétaires."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from types import SimpleNamespace as NS

import pytest

from mika.adapters.mail.config import MailAccount, MailConfig
from mika.adapters.web.app import LoginThrottle
from mika.app.moi import Call, Denied
from mika.app.moi import mail as mail_moi
from mika.app.moi import mcp as mcp_moi
from mika.app.moi import settings as settings_moi
from mika.vocab.access import OWNER, PERSON, SOURCE_WORDS_OTHER, who_words


def call(api: object, key: str = "") -> Call:
    me = NS(account=NS(id=7), handle="user_7")
    request = NS(headers={"idempotency-key": key} if key else {})
    return Call(request, me, None, {}, api)  # type: ignore[arg-type]


def test_a_try_counted_ahead_is_given_back_when_it_succeeds():
    throttle = LoginThrottle(2, 60.0, monotonic=lambda: 100.0)
    throttle.fail("k")
    throttle.forgive("k")  # réussi : il ne compte plus
    assert not throttle.blocked("k") and len(throttle) == 0
    throttle.fail("k")
    throttle.fail("k")
    assert throttle.blocked("k")
    throttle.forgive("ailleurs")  # rien à rendre : rien ne bouge
    assert throttle.blocked("k")


def test_tries_that_reach_a_server_are_bounded_per_account():
    api = NS(probes=LoginThrottle(3, 60.0, monotonic=lambda: 5.0))
    for _ in range(3):
        call(api).probe()
    with pytest.raises(Denied) as refused:
        call(api).probe()
    assert refused.value.status == 429


def test_a_creation_said_twice_with_the_same_key_is_made_once():
    api = NS(created=OrderedDict(), creating={})
    made: list[int] = []

    async def make() -> dict:
        await asyncio.sleep(0)  # deux envois qui se croisent
        made.append(1)
        return {"ok": True, "box": f"b{len(made)}"}

    async def twice() -> list[dict]:
        return list(await asyncio.gather(call(api, "k1").once(make), call(api, "k1").once(make)))

    first, second = asyncio.run(twice())
    assert made == [1] and first == {"ok": True, "box": "b1"} and second == {**first, "deduped": True}
    other = asyncio.run(call(api, "k2").once(make))
    assert other["box"] == "b2" and "deduped" not in other
    assert asyncio.run(call(api).once(make))["box"] == "b3"  # sans clé : rien n'est gardé


def test_a_line_naming_her_owners_says_so_to_someone_else():
    def name(key: str) -> str:
        return key

    assert who_words((OWNER,), name) == "Toi"
    assert who_words((OWNER,), name, sources=SOURCE_WORDS_OTHER) == "Ses propriétaires"


def test_one_persons_creations_never_wait_for_another_ones():
    api = NS(created=OrderedDict(), creating={})
    gate = asyncio.Event()

    async def slow() -> dict:
        await gate.wait()  # ses serveurs répondent lentement
        return {"ok": True, "box": "lente"}

    async def fast() -> dict:
        return {"ok": True, "box": "rapide"}

    async def both() -> dict:
        held = asyncio.ensure_future(call(api, "a").once(slow))
        await asyncio.sleep(0)
        other = call(api, "b")
        other.me = NS(account=NS(id=8), handle="user_8")  # une autre personne
        done = await asyncio.wait_for(other.once(fast), timeout=1)
        gate.set()
        await held
        return done

    assert asyncio.run(both())["box"] == "rapide"


def test_password_tries_launched_together_are_bounded():
    checked: list[str] = []

    async def verify(username: str, password: str) -> None:
        checked.append(password)
        await asyncio.sleep(0.01)  # scrypt : la vérification attend
        return None

    api = NS(password_tries=LoginThrottle(5, 60.0, monotonic=lambda: 1.0), accounts=NS(verify=verify))

    def wrong(i: int) -> Call:
        me = NS(account=NS(id=7, username="lea"), handle="user_7")
        request = NS(headers={}, query_params={})
        return Call(request, me, None, {"current": f"faux-{i}", "password": "un-autre-long"}, api)  # type: ignore[arg-type]

    async def together() -> list:
        return list(await asyncio.gather(*(settings_moi.account_password(wrong(i)) for i in range(12)),
                                         return_exceptions=True))

    got = asyncio.run(together())
    assert len(checked) == 5  # cinq vérifiées, les autres refusées avant d'attendre
    assert sorted(e.status for e in got if isinstance(e, Denied)) == [400] * 5 + [429] * 7


def test_a_service_line_naming_her_owners_says_so_to_someone_else():
    line = NS(who=(OWNER,), when=(), read="seule", act="carte", keep="prive", tools=())
    for owner, words in ((True, "Toi"), (False, "Ses propriétaires")):
        asking = NS(frame=NS(get=lambda ref: None), me=NS(owner=owner, name="Léa", person="user_7"))
        assert mcp_moi._line_json(line, asking)["who"] == words


class SlowBoxes:
    """Des réglages en mémoire dont l'écriture attend, comme une base : deux enregistrements peuvent s'y croiser."""

    def __init__(self, cfg: MailConfig | None = None) -> None:
        self.cfg = cfg or MailConfig()
        self.writing = asyncio.Lock()

    def email(self) -> MailConfig:
        return self.cfg

    async def save_email(self, cfg: MailConfig) -> MailConfig:
        await asyncio.sleep(0)
        self.cfg = cfg
        return cfg


BOX = {"label": "Rando", "address": "rando@example.test", "imap_host": "imap.example.test",
       "user": "rando@example.test", "password": "secret-imap", "smtp_host": "smtp.example.test",
       "smtp_user": "rando@example.test", "smtp_password": "secret-smtp"}


def someone(api: object, i: int, data: dict) -> Call:
    me = NS(account=NS(id=i), handle=f"user_{i}", person=f"p{i}", operator=False, owner=False, name=f"P{i}")
    return Call(NS(headers={}, query_params={}), me, None, data, api)  # type: ignore[arg-type]


@pytest.fixture
def quiet(monkeypatch):
    """Ses serveurs se cherchent lentement (l'autre enregistrement avance pendant ce temps) ; rien à journaliser."""
    async def slow_dns(host: str) -> bool:
        for _ in range(3):
            await asyncio.sleep(0)
        return False

    async def nothing(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(settings_moi, "local_host", slow_dns)
    monkeypatch.setattr(settings_moi, "audit", nothing)
    monkeypatch.setattr(settings_moi, "_traces", lambda call: set())
    monkeypatch.setattr(mail_moi, "owned", lambda call, key, *more: None)


def test_two_people_plugging_a_box_at_once_both_keep_it(quiet):
    api = NS(settings=SlowBoxes(), reconfigure=None, created=OrderedDict(), creating={})

    async def together() -> list[dict]:
        return list(await asyncio.gather(
            settings_moi.box_save(someone(api, 7, {"values": {**BOX, "label": "Léa"}})),
            settings_moi.box_save(someone(api, 8, {"values": {**BOX, "label": "Bob"}}))))

    made = asyncio.run(together())
    kept = api.settings.cfg.accounts
    assert sorted(kept) == sorted(m["box"] for m in made) and len(kept) == 2  # aucune n'a effacé l'autre
    assert {a.owner for a in kept.values()} == {PERSON + "p7", PERSON + "p8"}


def test_a_box_removed_while_she_changes_it_does_not_come_back(quiet):
    api = NS(settings=SlowBoxes(MailConfig(accounts={"rando": MailAccount.model_validate(
        {**BOX, "owner": PERSON + "p7"})})), reconfigure=None, created=OrderedDict(), creating={})
    moved = {"box": "rando", "values": {"imap_host": "imap.ailleurs.example.test", "password": "secret-neuf"}}

    async def together() -> list:
        return list(await asyncio.gather(settings_moi.box_save(someone(api, 7, moved)),
                                         settings_moi.box_remove(someone(api, 7, {"box": "rando"})),
                                         return_exceptions=True))

    changed, removed = asyncio.run(together())
    assert removed["message"] == "Boîte retirée."
    assert isinstance(changed, Denied) and changed.status == 404  # relue sous le verrou : elle n'est plus là
    assert api.settings.cfg.accounts == {}  # et rien ne l'a réécrite


def test_a_box_changed_elsewhere_meanwhile_is_not_overwritten(quiet):
    api = NS(settings=SlowBoxes(MailConfig(accounts={"rando": MailAccount.model_validate(
        {**BOX, "owner": PERSON + "p7"})})), reconfigure=None, created=OrderedDict(), creating={})
    moved = {"box": "rando", "values": {"imap_host": "imap.ailleurs.example.test", "password": "secret-neuf"}}

    async def renamed_meanwhile() -> None:
        await asyncio.sleep(0)  # pendant qu'elle cherche le serveur : la console renomme la boîte
        async with api.settings.writing:
            before = api.settings.cfg.accounts["rando"]
            await api.settings.save_email(MailConfig(accounts={"rando": before.model_copy(update={"label": "Pro"})}))

    async def together() -> list:
        return list(await asyncio.gather(settings_moi.box_save(someone(api, 7, moved)), renamed_meanwhile(),
                                         return_exceptions=True))

    changed, _ = asyncio.run(together())
    assert isinstance(changed, Denied) and changed.status == 409  # « rouvre-la » : rien d'écrasé sans le voir
    kept = api.settings.cfg.accounts["rando"]
    assert kept.label == "Pro" and kept.imap_host == "imap.example.test"
