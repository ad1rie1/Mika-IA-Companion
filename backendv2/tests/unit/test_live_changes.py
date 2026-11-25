"""Le direct (ADR 0308) : ce qui change part, regroupé, à chaque personne connectée — et seulement ce qu'elle voit.

Sur le vrai noyau composé (``tests/fixtures/mika.py``), un courrier simulé et un vrai cache de Teams ; les connexions
sont celles du concentrateur du chat, qui gardent ce qu'on leur envoie. Une personne (``user_1``) a la boîte « pro »
et le compte Teams « principal », une autre (``user_2``) la boîte « perso », une troisième (``user_3``) rien.
"""

from __future__ import annotations

import asyncio
import json
import threading
from types import SimpleNamespace

from mika.adapters.contacts import ContactsStore
from mika.adapters.teams import TeamsAccount, TeamsConfig, TeamsStore
from mika.adapters.web.accounts import Account
from mika.adapters.web.hub import Hub
from mika.app.domains.teams.desk import PRESENCE_EVERY_S, TeamsDesk
from mika.app.me.api import Call, me_of
from mika.app.me.changes import LiveChanges, Reader, Touch, touches_from, touches_of
from mika.contracts import identity as identity_c
from mika.contracts import location as location_c
from mika.contracts import phone as phone_c
from mika.contracts import projects as projects_c
from mika.contracts import runtime as rt
from mika.faculties.projects.faculty import ACCESS_SET, AMENDED, ARCHIVED, LINKS_SET, NOTED, RESTORED
from mika.kernel.events import Content, Origin
from mika.plugins.email import EmailParams
from mika.plugins.teams import TeamsParams
from mika.ports.changes import (
    CONTACTS,
    MAIL,
    MAIL_DRAFTS,
    OUTBOX,
    PROJECTS,
    TEAMS,
    TEAMS_REPLIES,
    TOPICS,
    Change,
)
from mika.ports.contacts import EMAIL, Observation
from mika.ports.contacts import MAIL as MAIL_SOURCE
from mika.vocab.episodes import Kind, task_target
from tests.fixtures.courrier import mailbox
from tests.fixtures.mika import boot, build, reply

REF = "pro:<projet@example.test>"
#: le regroupement des tests : court, pour qu'ils ne durent pas
WINDOW = 0.02


def go(coro):
    return asyncio.run(coro)


class Screens:
    """Les écrans connectés : ce que chacun a reçu, par adresse."""

    def __init__(self, hub: Hub) -> None:
        self.hub = hub
        self.got: dict[str, list[dict]] = {}

    def open(self, handle: str, *, authenticated: bool = True, channel: str = "web") -> list[dict]:
        got = self.got.setdefault(handle, [])

        async def send(frame: dict) -> None:
            got.append(frame)

        account = int(handle.split("_")[1]) if authenticated else None
        self.hub.attach(send, handle=handle, authenticated=authenticated, account=account, display_name=handle,
                        channel=channel)
        return got

    def forget(self) -> None:
        for got in self.got.values():
            got.clear()

    def changes(self, handle: str) -> list[list[dict]]:
        return [f["changes"] for f in self.got.get(handle, []) if f["type"] == "changed"]


async def world(tmp_path, *people: str):
    kernel, _, _, _ = build(tmp_path, reply("D'accord."))
    await boot(kernel)
    kernel.ports["mail"] = mailbox(3)
    teams = TeamsStore(lambda: TeamsConfig(accounts={"principal": TeamsAccount(label="Teams d'Adrien"),
                                                     "lea": TeamsAccount(label="Teams de Léa")}),
                       tmp_path / "teams.db")
    kernel.ports["teams"] = teams
    kernel.ports["contacts"] = ContactsStore(tmp_path / "contacts.db")
    await kernel.set_params("email", EmailParams(owners={"pro": "personne:user_1", "perso": "personne:user_2"}))
    await kernel.set_params("teams", TeamsParams(owners={"principal": "personne:user_1", "lea": "personne:user_2"}))
    hub = Hub(port=None)  # type: ignore[arg-type] — on ne fait qu'envoyer
    screens = Screens(hub)
    for handle in people:
        screens.open(handle)
    live = LiveChanges(kernel, hub, window_s=WINDOW)
    live.start()
    kernel.mind.subscribe(live.listen)
    return kernel, live, screens


async def settle() -> None:
    await asyncio.sleep(WINDOW * 5)


# ── à qui ──


def test_a_mail_change_goes_only_to_who_sees_the_box(tmp_path):
    async def scenario():
        kernel, live, screens = await world(tmp_path, "user_1", "user_2", "user_3")
        live.touch(Change(MAIL, ("pro",)))
        await settle()
        return screens

    screens = go(scenario())
    assert screens.changes("user_1") == [[{"topic": "mail", "boxes": ["pro"]}]]
    assert screens.changes("user_2") == [] and screens.changes("user_3") == []


def test_what_cannot_be_named_goes_to_who_has_something_there(tmp_path):
    """Une écriture qui ne sait pas sa boîte (l'oubli d'un correspondant) : sans clé, à qui a une boîte — pas à qui
    n'en a aucune."""
    async def scenario():
        kernel, live, screens = await world(tmp_path, "user_1", "user_2", "user_3")
        live.touch(Change(MAIL))
        await settle()
        return screens

    screens = go(scenario())
    assert screens.changes("user_1") == screens.changes("user_2") == [[{"topic": "mail"}]]
    assert screens.changes("user_3") == []


def test_a_teams_conversation_is_named_only_to_who_holds_its_account(tmp_path):
    async def scenario():
        kernel, live, screens = await world(tmp_path, "user_1", "user_2")
        live.touch(Change(TEAMS, ("principal",), ("19:a",)))
        live.touch(Change(TEAMS, ("lea",), ("lea~19:b",)))
        await settle()
        return screens

    screens = go(scenario())
    assert screens.changes("user_1") == [[{"topic": "teams", "conversations": ["19:a"]}]]
    assert screens.changes("user_2") == [[{"topic": "teams", "conversations": ["lea~19:b"]}]]


def test_an_unauthenticated_screen_hears_nothing_and_nobody_connected_costs_nothing(tmp_path):
    async def scenario():
        kernel, live, screens = await world(tmp_path)
        live.touch(Change(MAIL))
        await settle()
        alone = await live.send([Touch(MAIL, "boxes")])
        screens.open("anon_1", authenticated=False)
        live.touch(Change(MAIL))
        await settle()
        return alone, screens

    alone, screens = go(scenario())
    assert alone == 0 and screens.got["anon_1"] == []


# ── regroupé, depuis n'importe quel fil ──


def test_a_burst_goes_out_as_one_frame_per_person(tmp_path):
    async def scenario():
        kernel, live, screens = await world(tmp_path, "user_1", "user_2")
        for _ in range(50):
            live.touch(Change(MAIL, ("pro",)))
        live.touch(Change(MAIL, ("perso",)))
        live.touch(Change(MAIL_DRAFTS, ("pro",)))
        await settle()
        return screens

    screens = go(scenario())
    assert screens.changes("user_1") == [[{"topic": "mail", "boxes": ["pro"]}, {"topic": "mail.drafts", "boxes": ["pro"]}]]
    assert screens.changes("user_2") == [[{"topic": "mail", "boxes": ["perso"]}]]


def test_a_touch_from_another_thread_reaches_the_screens(tmp_path):
    """La relève IMAP tourne dans un fil : ce qu'elle range arrive quand même, sur la boucle."""
    async def scenario():
        kernel, live, screens = await world(tmp_path, "user_1")
        writer = threading.Thread(target=live.touch, args=(Change(MAIL, ("pro",)),))
        writer.start()
        writer.join()
        await settle()
        return screens

    assert go(scenario()).changes("user_1") == [[{"topic": "mail", "boxes": ["pro"]}]]


# ── du journal ──


def propose(kernel, box: str = "pro", ref: str = REF):
    return kernel.mind.append([rt.EFFECT_PROPOSED.draft(
        capability="email.send", owner="email", summary=Content.of("Répondre à Léa"), context="email",
        args_json=json.dumps({"draft": "d1", "account": box, "mail": ref}))], emitter="runtime", correlation="moi",
        origin=Origin.EXTERNAL)


def test_a_draft_she_proposes_names_its_box_its_mail_and_the_badges(tmp_path):
    async def scenario():
        kernel, live, screens = await world(tmp_path, "user_1", "user_2")
        await propose(kernel)
        await settle()
        return screens

    screens = go(scenario())
    assert screens.changes("user_1") == [[{"topic": "me"}, {"topic": "mail", "boxes": ["pro"]},
                                          {"topic": "mail.drafts", "boxes": ["pro"]},
                                          {"topic": "mail.work", "refs": [REF]}]]
    assert screens.changes("user_2") == []


def test_a_box_shared_for_reading_shows_its_mail_but_not_the_answers_being_prepared(tmp_path):
    """Partagée en lecture (ADR 0188) : ses mails se lisent, ses réponses en préparation et ses pastilles restent à
    son propriétaire."""
    async def scenario():
        kernel, live, screens = await world(tmp_path, "user_1", "user_2")
        await kernel.set_params("email", EmailParams(owners={"pro": "personne:user_1", "perso": "personne:user_2"},
                                                     shares={"pro": {"personne:user_2": "lire"}}))
        await settle()
        screens.forget()
        await propose(kernel)
        await settle()
        return screens

    screens = go(scenario())
    assert screens.changes("user_2") == [[{"topic": "mail", "boxes": ["pro"]}]]
    assert {c["topic"] for c in screens.changes("user_1")[0]} == {"me", "mail", "mail.drafts", "mail.work"}


def test_her_work_on_a_mail_is_said_when_it_starts_and_at_each_step(tmp_path):
    async def scenario():
        kernel, live, screens = await world(tmp_path, "user_1", "user_2")
        await kernel.mind.append([rt.EPISODE_STARTED.draft(kind=Kind.TASK, target=task_target("email", REF))],
                                 emitter="runtime", correlation="ep-1", origin=Origin.EXTERNAL)
        await settle()
        live.step("ep-1")  # un outil part (l'étape ne vit qu'en mémoire)
        live.step("ep-inconnu")
        await settle()
        return screens

    screens = go(scenario())
    assert screens.changes("user_1") == [[{"topic": "mail.work", "refs": [REF]}]] * 2
    assert screens.changes("user_2") == []


def test_the_phone_and_the_position_go_to_their_person_only(tmp_path):
    async def scenario():
        kernel, live, screens = await world(tmp_path, "user_1", "user_2")
        await kernel.mind.append([phone_c.RECEIVED.draft(recipient="user_2", handle="user_2", source="whatsapp",
                                                         thread="t1", text=Content.of("Tu viens ?"))],
                                 emitter="phone", correlation="tel", origin=Origin.EXTERNAL)
        await kernel.mind.append([location_c.LOCATED.draft(handle="user_1", person="user_1",
                                                           coords=Content.of("45.764043,4.835659"),
                                                           fixed_at=kernel.mind.clock.now())],
                                 emitter="location", correlation="ici", origin=Origin.EXTERNAL)
        await settle()
        return screens

    screens = go(scenario())
    flat = {k: [c for frame in screens.changes(k) for c in frame] for k in ("user_1", "user_2")}
    assert flat["user_2"] == [{"topic": "phone", "conversations": ["whatsapp|t1"]}]
    assert flat["user_1"] == [{"topic": "phone.position"}]


def test_a_settings_change_goes_to_everyone_without_naming_anything(tmp_path):
    """Les propriétaires et les partages d'une boîte changent ce que chacune voit : à toutes, sans clé — ses contacts
    compris (qui les voit suit la boîte, ``contacts.reach``)."""
    async def scenario():
        kernel, live, screens = await world(tmp_path, "user_1", "user_3")
        await kernel.set_params("email", EmailParams(owners={"pro": "personne:user_3"}))
        await settle()
        return screens

    screens = go(scenario())
    said = [{"topic": "me"}, {"topic": "mail"}, {"topic": "mail.drafts"}, {"topic": "contacts"},
            {"topic": "settings"}]
    assert screens.changes("user_1") == screens.changes("user_3") == [said]


# ── la traduction des bases tenues à côté ──


def test_what_the_bases_say_becomes_the_topics_of_the_contract():
    assert touches_from(Change(OUTBOX, ("principal",), ("19:a",))) == [
        Touch(TEAMS, "accounts", keys=("19:a",), owners=("principal",)),
        Touch(TEAMS_REPLIES, "accounts", "preparer", owners=("principal",))]
    assert touches_from(Change(CONTACTS, places=(("teams", "principal"),))) == [
        Touch(CONTACTS, "directory", owners=("teams|principal",))]
    assert touches_from(Change("inconnu")) == []


def test_a_contact_change_goes_to_who_sees_its_source(tmp_path):
    """Un contact vu dans la boîte « pro » est un contact de qui a cette boîte (``visible_sources``) : pas d'une autre."""
    async def scenario():
        kernel, live, screens = await world(tmp_path, "user_1", "user_2")
        store = kernel.ports["contacts"]
        store.on_change(live.touch)
        store.observe_now([Observation(EMAIL, "lea@x.fr", MAIL_SOURCE, "pro", "Léa Martin", 1, 1, 1)])
        await settle()
        return screens

    screens = go(scenario())
    assert screens.changes("user_1") == [[{"topic": "contacts"}]] and screens.changes("user_2") == []


def test_a_project_she_does_not_see_is_never_named(tmp_path):
    """Ce qu'elle voit d'un projet est ``projects.reaches`` : sans projet à elle, un projet nommé ne lui dit rien."""
    async def scenario():
        kernel, live, screens = await world(tmp_path, "user_1")
        return await live.send([Touch(PROJECTS, "project", keys=("7",)), Touch(PROJECTS, "project")])

    assert go(scenario()) == 0


def test_a_topic_said_without_keys_takes_over_what_was_named(tmp_path):
    async def scenario():
        kernel, _, _ = await world(tmp_path)
        me = me_of(kernel.mind.frame(), Account(1, "", "", False, True))
        return Reader(Call(None, me, kernel, {}, None), "web").changes(
            [Touch(MAIL, "boxes", keys=("pro",)), Touch(MAIL, "boxes"), Touch(MAIL, "boxes", keys=("perso",))])

    assert go(scenario()) == [{"topic": "mail"}]


# ── qui voit quoi change : à toutes ──


def event(kind, seq: int = 1, **data):
    """Un événement tel qu'un lot commité le donne à la traduction (son type, son numéro, sa charge)."""
    return SimpleNamespace(type=kind, seq=seq, data=SimpleNamespace(**data))


def test_what_changes_who_sees_a_project_goes_to_everyone_without_a_key():
    """Ses accès, ce qu'il lit des autres, son propriétaire ou son niveau, archivé ou rendu : le filtre lit l'état
    d'après — celle qui vient de perdre l'accès ne recevrait rien, et garderait le projet à l'écran."""
    for kind in (ACCESS_SET, LINKS_SET, AMENDED, ARCHIVED, RESTORED):
        assert touches_of([event(kind, project=7)], None, None) == [Touch(PROJECTS, "all"), Touch("me", "all")], kind
    # le reste de sa vie se nomme, à qui le voit
    assert touches_of([event(NOTED, project=7)], None, None) == [Touch(PROJECTS, "project", keys=("7",)),
                                                                Touch("me", "project", owners=("7",))]


def test_an_address_linked_to_a_person_tells_every_domain_to_everyone():
    """À qui est une adresse (``me.person``) change ce qui est à elle partout : ses boîtes « personne:… », son
    téléphone, ses voyages, ses contacts, ses projets."""
    said = touches_of([event(identity_c.LINKED, handle="user_2", person="lea")], None, None)
    assert said == [Touch(topic, "all") for topic in TOPICS]


def test_a_translation_that_fails_does_not_take_the_others_with_it():
    """Un événement qu'on ne sait pas traduire (une panne de sa traduction) : les autres du lot partent quand même."""
    broken = SimpleNamespace(type=projects_c.PROJECT_CREATED, seq=0, data=None)  # ``seq`` nul, sans charge
    said = touches_of([event(identity_c.LINKED, handle="user_2", person="lea"),
                       SimpleNamespace(type=phone_c.RECEIVED, seq=3, data=None), broken], None, None)
    assert said[:len(TOPICS)] == [Touch(topic, "all") for topic in TOPICS]


def test_a_rule_that_fails_sees_nothing_and_spares_the_others(tmp_path):
    """L'annuaire qui lève : rien de ce qu'il gardait ne part (on ne sait pas qui le voit), le courrier part quand
    même."""
    async def scenario():
        kernel, live, screens = await world(tmp_path, "user_1")
        tried: list[int] = []

        def broken():
            tried.append(1)
            raise RuntimeError("l'annuaire ne répond pas")

        kernel.ports["contacts"].sources = broken
        live.touch(Change(CONTACTS, places=(("mail", "pro"),)))
        live.touch(Change(CONTACTS, places=(("teams", "principal"),)))
        live.touch(Change(MAIL, ("pro",)))
        await settle()
        return screens, tried

    screens, tried = go(scenario())
    assert screens.changes("user_1") == [[{"topic": "mail", "boxes": ["pro"]}]]
    assert tried == [1]  # la règle en panne ne se relit pas pour chaque touche de la trame


def test_a_setting_saved_outside_the_journal_goes_to_everyone(tmp_path):
    """Une boîte, sa connexion Microsoft, un compte Teams, les règles d'envoi… (``Settings._put``) : les écrans relisent
    ce qu'ils en montrent ; la fin de l'attente d'un code Microsoft, chez qui lit la boîte et à son propriétaire."""
    async def scenario():
        kernel, live, screens = await world(tmp_path, "user_1", "user_2")
        live.saved("mail_oauth")
        await settle()
        first = {k: screens.changes(k) for k in ("user_1", "user_2")}
        screens.forget()
        live.saved("canaux")
        await settle()
        second = {k: screens.changes(k) for k in ("user_1", "user_2")}
        screens.forget()
        live.signed("pro")
        await settle()
        return first, second, {k: screens.changes(k) for k in ("user_1", "user_2")}

    first, second, signed = go(scenario())
    assert first["user_1"] == first["user_2"] == [[{"topic": "mail"}, {"topic": "settings"}]]
    assert second["user_1"] == second["user_2"] == [[{"topic": "settings"}]]
    assert signed == {"user_1": [[{"topic": "mail", "boxes": ["pro"]}, {"topic": "settings"}]], "user_2": []}


def test_the_presence_of_the_extension_never_erases_what_a_batch_names(tmp_path):
    """Sa présence fait relire les comptes de qui lit le compte ; un lot du même instant, qui nomme sa conversation, y
    suffit (toute trame ``teams`` relit les comptes)."""
    async def scenario():
        kernel, live, screens = await world(tmp_path, "user_1", "user_2")
        live.presence("principal")
        await settle()
        alone = {k: screens.changes(k) for k in ("user_1", "user_2")}
        screens.forget()
        live.presence("principal")
        live.touch(Change(TEAMS, ("principal",), ("19:a",)))
        await settle()
        return alone, screens.changes("user_1")

    alone, together = go(scenario())
    assert alone == {"user_1": [[{"topic": "teams"}]], "user_2": []}
    assert together == [[{"topic": "teams", "conversations": ["19:a"]}]]


# ── le rythme, la boucle, l'envoi ──


def test_a_topic_that_keeps_coming_is_paced_and_its_last_change_is_never_lost(tmp_path):
    """Une boîte qu'on range sans cesse : quelques trames d'affilée, puis une par intervalle — la dernière part quand
    même, réunie ; un autre sujet n'attend pas son tour."""
    async def scenario():
        kernel, live, screens = await world(tmp_path, "user_1")
        live.gap_s, live.burst = 0.6, 2
        for _ in range(2):
            live.touch(Change(MAIL, ("pro",)))
            await asyncio.sleep(0.08)
        live.touch(Change(MAIL))  # son tour n'est pas venu : il attend…
        await asyncio.sleep(0.08)
        live.touch(Change(MAIL_DRAFTS, ("pro",)))  # … un autre sujet, non
        await asyncio.sleep(0.15)
        early = screens.changes("user_1")
        await asyncio.sleep(0.6)
        return early, screens.changes("user_1")

    early, late = go(scenario())
    pro = [{"topic": "mail", "boxes": ["pro"]}]
    assert early == [pro, pro, [{"topic": "mail.drafts", "boxes": ["pro"]}]]
    assert late == [*early, [{"topic": "mail"}]]


def test_the_rules_run_off_the_loop_while_a_base_holds_its_lock(tmp_path):
    """L'annuaire et le cache de Teams tiennent leur verrou le temps d'un lot, dans un fil : ce que le direct en lit
    tourne ailleurs que sur la boucle, qui ne se fige pas ; la trame part une fois le lot fini."""
    async def scenario():
        kernel, live, screens = await world(tmp_path, "user_1")
        contacts, teams = kernel.ports["contacts"], kernel.ports["teams"]
        held, release = threading.Event(), threading.Event()

        def batch() -> None:  # un lot qui dure, sous les deux verrous
            with contacts._lock, teams._lock:
                held.set()
                release.wait(5)

        worker = threading.Thread(target=batch)
        worker.start()
        held.wait(5)
        loop = asyncio.get_running_loop()
        live.touch(Change(CONTACTS, places=(("mail", "pro"),)))
        live.touch(Change(TEAMS, ("principal",), ("19:a",)))
        worst, last = 0.0, loop.time()
        for _ in range(25):  # la boucle bat pendant que le lot tient ses verrous
            await asyncio.sleep(0.01)
            worst, last = max(worst, loop.time() - last), loop.time()
        during = screens.changes("user_1")
        release.set()
        worker.join()
        await settle()
        return worst, during, screens.changes("user_1")

    worst, during, after = go(scenario())
    assert worst < 0.15 and during == []
    assert after == [[{"topic": "teams", "conversations": ["19:a"]}, {"topic": "contacts"}]]


def test_the_boxes_the_settings_say_are_read_once_per_frame_on_the_loop(tmp_path):
    """Les boîtes se lisent dans les réglages (la base du journal, que seule la boucle lit, et leurs secrets à
    ouvrir) : une fois par envoi, quel que soit le nombre de personnes connectées."""
    class Counted:
        """Le courrier, dont on compte les lectures des boîtes, et où elles se font (la boucle : le fil principal)."""

        def __init__(self, port) -> None:
            self.port, self.reads = port, []

        def accounts(self):
            self.reads.append(threading.current_thread() is threading.main_thread())
            return self.port.accounts()

        def __getattr__(self, name):
            return getattr(self.port, name)

    async def scenario():
        kernel, live, screens = await world(tmp_path, "user_1", "user_2", "user_3")
        port = kernel.ports["mail"] = Counted(kernel.ports["mail"])
        sent = await live.send([Touch(MAIL, "boxes", keys=("pro",)), Touch(MAIL, "boxes", keys=("perso",)),
                                Touch(CONTACTS, "directory", owners=("mail|pro",))])
        return port.reads, sent

    reads, sent = go(scenario())
    assert reads == [True] and sent == 2


def test_a_slow_screen_holds_back_neither_the_others_nor_what_follows(tmp_path):
    """Les trames partent en parallèle, chacune en un temps borné ; ce qui est dit à une personne pendant qu'une trame
    lui part s'y ajoute et part juste après, en une — rien ne s'empile derrière une connexion lente."""
    async def scenario():
        kernel, live, screens = await world(tmp_path, "user_2")
        live.send_timeout_s = 0.3
        stuck = asyncio.Event()
        slow: list[dict] = []

        async def send(frame: dict) -> None:
            slow.append(frame)
            if len(slow) == 1:
                await stuck.wait()  # la première ne passe pas

        live.hub.attach(send, handle="user_1", authenticated=True, account=1, display_name="user_1", channel="web")
        loop = asyncio.get_running_loop()
        began = loop.time()
        first = asyncio.ensure_future(live.send([Touch(MAIL, "boxes", keys=("pro",)),
                                                 Touch(MAIL, "boxes", keys=("perso",))]))
        await asyncio.sleep(0.05)
        quick = screens.changes("user_2")  # l'autre a déjà la sienne
        for box in ("pro", "pro"):  # pendant que la première pend : réunies en une, après elle
            await live.send([Touch(MAIL_DRAFTS, "boxes", "preparer", keys=(box,))])
        sent = await first
        return quick, sent, loop.time() - began, slow

    quick, sent, took, slow = go(scenario())
    assert quick == [[{"topic": "mail", "boxes": ["perso"]}]]
    assert took < 1.0 and sent == 2  # la sienne n'est pas partie à temps ; l'autre, et celle qui l'a suivie
    assert [f["changes"] for f in slow] == [[{"topic": "mail", "boxes": ["pro"]}],
                                           [{"topic": "mail.drafts", "boxes": ["pro"]}]]


def test_the_presence_of_the_extension_is_told_when_it_shows_not_at_each_sign_of_life():
    """Elle se manifeste sans cesse (un relevé, la connexion en direct, un accusé) : ses écrans le savent quand elle
    arrive ou revient d'un silence, quand sa connexion s'ouvre ou se ferme, et au plus une fois par
    ``PRESENCE_EVERY_S`` — l'âge qu'ils montrent ne vieillit pas sans raison."""
    now = [1_000_000_000]
    desk = TeamsDesk(None, lambda: now[0], None)
    told: list[str] = []
    desk.on_presence = told.append
    desk._heard("principal")
    now[0] += 60_000_000
    desk._heard("principal")
    assert told == ["principal"]
    now[0] += PRESENCE_EVERY_S * 1_000_000
    desk._heard("principal")
    assert told == ["principal"] * 2
    desk._heard("principal", tell=True)  # sa connexion en direct s'ouvre
    desk._live_checked["mtk_x"] = ("principal", 0.0)
    desk.live_closed("mtk_x")  # puis se ferme
    assert told == ["principal"] * 4
