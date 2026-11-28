"""Ce qu'elle sait d'un contact, à partir de ce qu'elle lit (ADR 0298, lot 6) : le processus ``contacts.portrait``, sur
le vrai cache de Teams, le vrai courrier et le vrai annuaire, un journal du téléphone jouet et un faux modèle (aucun
appel réel).

- **seulement qui échange vraiment** : des messages dans les deux sens, dans la fenêtre — un expéditeur qui ne fait
  qu'écrire, une adresse générique, un échange d'il y a quarante jours n'en sont pas ; l'historique chargé ne fait
  relire que la fin, sauf « Relire tout l'historique » ;
- **quand** : un premier portrait après quelques messages, un nouveau après ``refresh_after`` de plus ; des plafonds
  par jour (contacts, appels) et par passage ;
- **le prompt** vient de sa voix (``contacts.portrait``), ses messages cités, jamais un fait oublié ;
- **la réponse** est relue strictement : illisible, rien n'est gardé et la vue attend du nouveau ; un appel en panne
  n'est pas compté ; un fait oublié, redit, ne se garde pas ;
- **une fiche qui s'enrichit** (ADR 0303) : le portrait suivant reçoit ce qu'elle en savait et la complète — un fait
  récrit garde ce qui le fondait, un fait précisé prend le message nouveau, un fait retiré part, un fait qu'il ne cite
  pas reste ; un fait dont le message n'est plus, ou oublié pendant l'appel, ne revient pas ; sa façon d'être et ce
  qu'il y a entre elle et la personne du compte y ont leur sorte.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from mika.adapters.contacts import ContactsStore
from mika.adapters.mail import ImapSmtpMail, MailAccount, MailConfig
from mika.adapters.teams import TeamsAccount, TeamsConfig, TeamsStore
from mika.contracts import identity as identity_c
from mika.contracts import self_ as self_c
from mika.plugins.contacts import CONTACTS, ContactsParams, ContactsState, _phoned
from mika.plugins.contacts.ingest import Ingest
from mika.plugins.contacts.portrait import (
    EVERY,
    PORTRAIT_SCHEMA,
    START_DELAY,
    WAKE_GAP,
    Candidate,
    Line,
    Portraits,
    fair,
    left,
    parse,
    phone_exchange,
    thread_people,
)
from mika.ports.contacts import EMAIL, MAIL, NOTES_MAX, PHONE_SOURCE, TEAMS, TEAMS_ID, Observation
from mika.ports.llm import LLMResponse
from mika.ports.mail import AccountInfo, Mail
from mika.ports.teams import InboxBatch, InboxConversation, InboxMessage
from mika.sim.outside import FakeMail
from mika.vocab.phrasebook import phrase
from tests.fixtures import backend
from tests.unit.test_contacts_phone import Journal, sender

NOW = 1_790_000_000_000_000
MS = NOW // 1000
HOUR_MS = 3_600_000
DAY_MS = 24 * HOUR_MS
HOUR = 3_600_000_000
ADRIEN = "user_1"
DM, OLD_DM, GROUP = "19:gilles_adrien@unq.gbl.spaces", "19:paul_adrien@unq.gbl.spaces", "19:projet@thread.v2"
GILLES, LEA, PAUL = "8:orgid:gilles", "8:orgid:lea", "8:orgid:paul"
DUO = "abcdefabcdefabcd"
FACT = {"texte": "Il pilote la migration des centrales vers le VPN.", "sorte": "role", "confiance": 0.9,
        "message": 1}


class Frame:
    def __init__(self, world: World) -> None:
        self.world, self.now, self.root = world, world.now, None
        self.env = SimpleNamespace(params_of=lambda name, root: world.params if name == CONTACTS.name else None)

    def get(self, key):
        if key == identity_c.OWNERS:
            return (ADRIEN,)
        if key == self_c.PERSONA:
            return SimpleNamespace(name="Mika")
        return None

    def local(self, t: int | None = None) -> datetime:
        return datetime.fromtimestamp((self.now if t is None else t) / 1_000_000, tz=UTC)


class Model:
    """Le faux modèle : ce qu'il répond (un texte, ``None`` : une panne), et ce qu'on lui a demandé."""

    def __init__(self) -> None:
        self.answer: object = json.dumps({"faits": [FACT]})
        self.asked: list = []

    def serving(self, role: str) -> str:
        return "faux"

    def held(self, role: str, priority: int = 1) -> str:
        return ""

    async def ask(self, request):
        self.asked.append(request)
        answer = self.answer(request) if callable(self.answer) else self.answer
        return None if answer is None else LLMResponse(str(answer))


class World:
    """Le compte Teams « equipe » et la boîte « pro » sont à Adrien, son téléphone aussi."""

    def __init__(self, tmp) -> None:
        self.now = NOW
        self.params = ContactsParams()
        self.teams = TeamsStore(lambda: TeamsConfig(accounts={"equipe": TeamsAccount(owner="personne:" + ADRIEN)}),
                                tmp / "teams.db", now=lambda: self.now)
        self.mail = ImapSmtpMail(lambda: MailConfig(accounts={"pro": MailAccount(address="adrien@nordis.fr")}),
                                 tmp / "mail.db")
        self.mail._cache.save_folder("pro", "Envoyés", role="sent")
        self.contacts = ContactsStore(backend.target(tmp, "contacts"), now=lambda: self.now)
        self.journal = Journal()
        self.state = ContactsState()
        self.model = Model()
        self.uid = 0
        self.ingest = Ingest()
        self.portraits = Portraits()

    def ctx(self) -> SimpleNamespace:
        ports = {"teams": self.teams, "mail": self.mail, "contacts": self.contacts, "store": self.journal}
        return SimpleNamespace(state=self.state, ports=ports, frame=Frame(self), now=self.now, llm=self.model,
                               run_id="run", ask=self.model.ask)

    # ── ce qu'elle lit ──
    def teams_says(self, *messages: InboxMessage, history: bool = False) -> None:
        self.teams.store_batch("equipe", InboxBatch(
            "8:orgid:adrien", "Adrien", (InboxConversation(DM, "", "dm"), InboxConversation(GROUP, "Projet", "group"),
                                         InboxConversation(OLD_DM, "", "dm")),
            messages, history=history), self.now)

    def mail_in(self, sender_: str, address: str, subject: str, at: int, body: str) -> None:
        self.uid += 1
        self.mail._cache.store(Mail(f"<m{self.uid}@x>", sender_, address, subject, at, body, to="adrien@nordis.fr",
                                    account="pro", folder="INBOX"), self.uid)

    def mail_out(self, to: str, at: int) -> None:
        self.uid += 1
        self.mail._cache.store(Mail(f"<m{self.uid}@x>", "Adrien <adrien@nordis.fr>", "adrien@nordis.fr", "Re",
                                    at, "ok", to=to, account="pro", folder="Envoyés"), self.uid)

    def phone(self, *seqs: int) -> None:
        for seq in seqs:
            data = json.loads(self.journal.events[seq].data)
            self.state = _phoned(self.state, SimpleNamespace(seq=seq, at=data["sent_at"], data=SimpleNamespace(
                own=data["own"], sender=data["sender"], recipient=data["recipient"], source=data["source"],
                thread=data["thread"], sent_at=data["sent_at"])), None)

    def run(self) -> list:
        """Un passage de la collecte, puis du portrait ; ce que le modèle a reçu à ce passage."""
        before = len(self.model.asked)
        asyncio.run(self.ingest.run(self.ctx()))
        asyncio.run(self.portraits.run(self.ctx()))
        return self.model.asked[before:]

    def close(self) -> None:
        self.teams.close()
        self.mail._cache.close()
        self.contacts.close()


@pytest.fixture
def world(tmp_path):
    found = World(tmp_path)
    yield found
    found.close()


def gilles_writes(n: int, start: int = 0, at: int = MS - HOUR_MS) -> tuple[InboxMessage, ...]:
    return tuple(InboxMessage(f"g{start + i}", DM, "Gilles Rousseau", GILLES, at + i, f"Message {start + i} de Gilles")
                 for i in range(n))


def seed(world: World) -> None:
    """Gilles (Teams) et Bob (courrier) échangent avec Adrien, Maman sur son WhatsApp ; Léa ne fait qu'écrire dans un
    groupe, Carla au courrier, Paul par SMS ; une lettre d'information répond toute seule ; Paul (Teams) échangeait
    il y a quarante jours. L'historique de Gilles, chargé, a quarante jours."""
    old = MS - 40 * DAY_MS
    world.teams_says(*gilles_writes(4), InboxMessage("a1", DM, "Adrien", "8:orgid:adrien", MS - HOUR_MS + 50,
                                                     "Je regarde", own=True),
                     *(InboxMessage(f"l{i}", GROUP, "Léa Martin", LEA, MS - 2 * HOUR_MS + i, "Qui a la clé ?")
                       for i in range(4)))
    world.teams_says(InboxMessage("h0", DM, "Gilles Rousseau", GILLES, old, "Un vieux message de Gilles"),
                     *(InboxMessage(f"p{i}", OLD_DM, "Paul Henry", PAUL, old + i, f"Paul, il y a longtemps {i}")
                       for i in range(4)),
                     InboxMessage("a0", OLD_DM, "Adrien", "8:orgid:adrien", old + 9, "Merci Paul", own=True),
                     history=True)
    for i in range(3):
        world.mail_in("Bob Martin <bob@gmail.com>", "bob@gmail.com", f"Le devis {i}", NOW - (i + 2) * HOUR,
                      f"Voici le devis numéro {i}.")
        world.mail_in("Carla <carla@gmail.com>", "carla@gmail.com", "Promo", NOW - (i + 2) * HOUR, "Achetez")
        world.mail_in("Nordis <noreply@nordis.fr>", "noreply@nordis.fr", "Info", NOW - (i + 2) * HOUR, "Lettre")
    world.mail_out("Bob <bob@gmail.com>, noreply@nordis.fr", NOW - HOUR)
    j = world.journal
    maman = sender(ADRIEN, "whatsapp", "k-maman", "Maman")
    seqs = [j.received(ADRIEN, "whatsapp", "k-maman", "Maman", at=NOW - (i + 2) * HOUR) for i in range(3)]
    seqs.append(j.received(ADRIEN, "whatsapp", "", "", own=True, at=NOW - HOUR))
    seqs += [j.received(ADRIEN, "messages", "k-paul", "Paul", thread="f00d", at=NOW - (i + 2) * HOUR)
             for i in range(3)]
    world.phone(*seqs)
    assert maman.startswith("phone:")


def places(requests) -> set[tuple[str, str]]:
    return {tuple(r.call_id.rsplit(":", 2)[-2:]) for r in requests}


def test_only_who_really_exchanges_with_an_account_is_portrayed_from_their_latest_messages(world):
    seed(world)
    asked = world.run()
    c = world.contacts
    gilles, bob = c.contact_of(TEAMS_ID, GILLES), c.contact_of(EMAIL, "bob@gmail.com")
    maman = next(x.id for x in c.page(size=50).items if x.name == "Maman")
    by_contact = {int(r.call_id.split("#", 1)[1].split(":", 1)[0]): r for r in asked}
    assert set(by_contact) == {gilles, bob, maman}  # ni Léa, ni Carla, ni la lettre d'information, ni Paul
    assert places(asked) == {(TEAMS, "equipe"), (MAIL, "pro"), (PHONE_SOURCE, ADRIEN)}
    teams = by_contact[gilles]
    assert teams.role == "portrait" and teams.lane == "background" and teams.output_schema == PORTRAIT_SCHEMA
    assert teams.system_stable == phrase("contacts.portrait.system", name="Mika")
    asked_text = teams.messages[0].content
    assert asked_text.startswith(phrase("contacts.portrait.ask", who="Gilles Rousseau", where="Teams", count=4,
                                        messages="")[:40])
    assert "> Message 3 de Gilles" in asked_text and asked_text.index("Message 3") < asked_text.index("Message 0")
    assert "Un vieux message" not in asked_text  # l'historique chargé : seulement la fin, dans la fenêtre
    assert phrase("contacts.portrait.place.dm") in asked_text and "Je regarde" not in asked_text
    mail = by_contact[bob].messages[0].content
    assert "Voici le devis numéro 0." in mail and "objet « Le devis 0 »" in mail and "Achetez" not in mail
    # ses faits, gardés sous la vue d'où ils viennent : le message qui les fonde (le plus récent), où il était
    (note,) = c.notes(gilles)
    assert (note.source, note.account, note.text, note.kind, note.confidence) == (
        TEAMS, "equipe", FACT["texte"], "role", 0.9)
    assert note.said_at == (MS - HOUR_MS + 3) * 1000 and note.ref  # « g3 », sous la référence que Teams lui donne
    assert note.place == phrase("contacts.portrait.place.dm") and note.call_id == f"run#{gilles}:teams:equipe"
    (phone_note,) = c.notes(maman)
    assert phone_note.ref.startswith("p") and "#" not in phone_note.ref
    assert c.notes(gilles, visible={(MAIL, "pro")}) == []
    assert c.cursor("portrait.eligible") == 3 and c.cursor("portrait.run") == NOW


def test_reading_the_whole_history_is_a_choice_of_the_operator(world):
    seed(world)
    world.params = ContactsParams(history=True)
    asked = world.run()
    paul = world.contacts.contact_of(TEAMS_ID, PAUL)
    assert paul in {int(r.call_id.split("#", 1)[1].split(":", 1)[0]) for r in asked}  # l'échange d'il y a 40 jours
    gilles = next(r for r in asked if r.call_id.endswith("teams:equipe")
                  and int(r.call_id.split("#", 1)[1].split(":", 1)[0]) == world.contacts.contact_of(TEAMS_ID, GILLES))
    assert "Un vieux message de Gilles" in gilles.messages[0].content


def test_a_portrait_is_redone_after_enough_new_messages_and_completes_the_former(world):
    seed(world)
    world.run()
    gilles = world.contacts.contact_of(TEAMS_ID, GILLES)
    assert world.run() == []  # rien de neuf : rien
    world.now += HOUR
    world.teams_says(*gilles_writes(4, start=10, at=world.now // 1000 - 1000))
    assert world.run() == []  # quatre nouveaux messages : pas encore (cinq)
    world.teams_says(*gilles_writes(1, start=20, at=world.now // 1000 - 10))
    world.model.answer = json.dumps({"faits": [{"texte": "Il attend la recette avant vendredi.",
                                                "sorte": "expectation", "confiance": 0.7, "message": 1}]})
    asked = world.run()
    assert len(asked) == 1 and "Message 20 de Gilles" in asked[0].messages[0].content
    # le fait d'avant, que la réponse ne cite pas, reste (ADR 0303) ; le nouveau s'y ajoute
    assert {n.text for n in world.contacts.notes(gilles)} == {"Il attend la recette avant vendredi.", FACT["texte"]}


def test_a_first_portrait_waits_for_a_few_messages(world):
    world.teams_says(*gilles_writes(2), InboxMessage("a1", DM, "Adrien", "8:orgid:adrien", MS - 10, "Ok", own=True))
    assert world.run() == []  # deux messages : un premier portrait en attend trois
    world.teams_says(*gilles_writes(1, start=5))
    assert len(world.run()) == 1


def test_daily_caps_and_each_pass_bound_the_cost(world):
    seed(world)
    world.params = ContactsParams(contacts_per_day=1)
    assert len(world.run()) == 1
    world.params = ContactsParams(calls_per_day=2)
    assert len(world.run()) == 1  # deux appels en vingt-quatre heures, dont celui d'avant
    world.params = ContactsParams(per_run=1)
    assert len(world.run()) == 1
    world.now += 25 * HOUR  # le lendemain, le plafond est rendu ; mais rien de neuf pour les portraits déjà faits
    world.params = ContactsParams()
    assert world.run() == []


def test_an_unreadable_answer_keeps_nothing_and_is_not_retried_a_failed_call_is_not_counted(world):
    seed(world)
    world.model.answer = None  # une panne : le passage s'arrête, rien n'est compté
    assert len(world.run()) == 1
    assert world.contacts.portraits() == []
    world.model.answer = "Je ne sais pas trop."
    asked = world.run()
    assert len(asked) == 3
    assert all(n == [] for n in (world.contacts.notes(x.contact) for x in world.contacts.portraits()))
    assert {x.ok for x in world.contacts.portraits()} == {False}
    assert world.run() == []  # illisible : la vue attend de nouveaux messages, pas de rafale


def test_a_forgotten_fact_is_never_shown_again_nor_kept_again(world):
    seed(world)
    world.run()
    gilles = world.contacts.contact_of(TEAMS_ID, GILLES)
    (note,) = world.contacts.notes(gilles)
    world.contacts.forget_note(note.id)
    world.now += HOUR
    world.teams_says(*gilles_writes(5, start=30, at=world.now // 1000 - 1000))
    world.model.answer = json.dumps({"faits": [
        {"texte": "Il pilote la migration des centrales VPN.", "sorte": "role", "confiance": 0.9, "message": 2},
        {"texte": "Il préfère qu'on l'appelle en urgence.", "sorte": "expectation", "confiance": 0.6, "message": 1}]})
    (asked,) = world.run()
    assert note.text not in asked.messages[0].content and note.text not in asked.system_stable
    assert [n.text for n in world.contacts.notes(gilles)] == ["Il préfère qu'on l'appelle en urgence."]


def test_the_answer_is_read_strictly():
    good = {"texte": "Elle suit le budget.", "sorte": "topic", "confiance": 0.5, "message": 2}
    assert [f.text for f in parse(json.dumps({"faits": [good]}), 2)] == ["Elle suit le budget."]
    assert parse("```json\n" + json.dumps({"faits": [good]}) + "\n```", 2)[0].kind == "topic"
    assert parse(json.dumps({"faits": []}), 2) == []  # rien de sûr
    for broken in ("pas de JSON", "{pas du json}", json.dumps({"autre": []}), json.dumps({"faits": "x"}),
                   json.dumps({"faits": [{**good, "message": 9}]}),  # aucun fait ne tient
                   json.dumps({"faits": [{**good, "confiance": 2}]}), json.dumps({"faits": [{**good, "texte": ""}]}),
                   json.dumps({"faits": [{**good, "texte": "x" * 161}]}),
                   json.dumps({"faits": [{**good, "confiance": True}]})):
        assert parse(broken, 2) is None, broken
    mixed = parse(json.dumps({"faits": [good, {**good, "message": 0}, {**good, "sorte": "santé"},
                                        *({**good, "texte": f"Fait {i}."} for i in range(15))]}), 2)
    assert len(mixed) == NOTES_MAX == 12 and mixed[0].text == "Elle suit le budget."  # au plus douze, sans doublon
    assert parse(json.dumps({"faits": [{**good, "sorte": "santé", "texte": "Autre."}]}), 2)[0].kind == "other"
    # un fait d'avant repris : « avant » le désigne parmi ceux qu'elle savait, sans message nouveau
    kept = {**good, "message": 0, "avant": 2}
    assert [(f.message, f.before) for f in parse(json.dumps({"faits": [kept]}), 2, known=3)] == [(0, 2)]
    assert parse(json.dumps({"faits": [kept]}), 2, known=1) is None  # un fait d'avant qu'elle n'avait pas
    assert parse(json.dumps({"faits": [{**kept, "avant": True}]}), 2, known=3) is None
    assert parse(json.dumps({"faits": [{**good, "avant": 1}]}), 2, known=1)[0].message == 2  # précisé : le message
    # « laisse » : les faits d'avant retirés, ceux qu'elle avait seulement ; sans « laisse », rien ne part
    assert left(json.dumps({"faits": [], "laisse": [1, 3, 9, True, "2"]}), 3) == {1, 3}
    assert left(json.dumps({"faits": []}), 3) == set() and left("pas de JSON", 3) == set()
    for kind in ("manner", "bond"):  # sa façon d'être, ce qu'il y a entre elle et la personne du compte
        assert parse(json.dumps({"faits": [{**good, "sorte": kind}]}), 2)[0].kind == kind


def test_the_process_wakes_after_what_is_noticed_and_hourly_otherwise(world):
    process = Portraits()
    frame = Frame(world)
    assert process.next_due(ContactsState(heard=1), frame, None) == NOW + START_DELAY
    process.handled, process.done_at = 1, NOW
    assert process.next_due(ContactsState(heard=1), frame, NOW) == NOW + EVERY
    assert process.next_due(ContactsState(heard=2), frame, NOW) == NOW + WAKE_GAP
    world.params = ContactsParams(portraits=False)
    assert process.next_due(ContactsState(heard=2), frame, NOW) is None
    spec = next(s for s in CONTACTS.processes if s.name == "contacts.portrait")
    assert spec.priority > next(s for s in CONTACTS.processes if s.name == "contacts.ingest").priority


def test_the_sources_say_who_exchanges_the_same_way_real_and_simulated(world):
    seed(world)
    got = world.mail.exchanged(NOW - 30 * 24 * HOUR)
    assert [(x.account, x.address, x.received, x.sent) for x in got] == [
        ("pro", "bob@gmail.com", 3, 1), ("pro", "noreply@nordis.fr", 3, 1)]
    assert world.mail.exchanged(NOW - 30 * 24 * HOUR, accounts=["autre"]) == []
    assert [m.subject for m in world.mail.letters_from("Bob@gmail.com", since=NOW - 3 * HOUR)] == ["Le devis 0",
                                                                                                    "Le devis 1"]
    fake = FakeMail(boxes=[AccountInfo(key="pro", label="Pro", address="adrien@nordis.fr", ready=True)])
    fake.inbox.extend(world.mail.cached(100))
    assert [(x.address, x.received, x.sent) for x in fake.exchanged(NOW - 30 * 24 * HOUR)] == [
        ("bob@gmail.com", 3, 1), ("noreply@nordis.fr", 3, 1)]
    assert [m.subject for m in fake.letters_from("bob@gmail.com", since=NOW - 3 * HOUR)] == ["Le devis 0",
                                                                                             "Le devis 1"]
    teams = world.teams.exchanged((MS - 30 * DAY_MS) * 1000)
    assert [(a, k, n) for a, k, n, _at in teams] == [("equipe", GILLES, 4)]
    assert [m.text for m in world.teams.authored([GILLES.upper()], limit=2)] == ["Message 3 de Gilles",
                                                                                  "Message 2 de Gilles"]
    assert world.teams.authored([GILLES], since=NOW) == [] and world.teams.authored([], limit=5) == []


# ── ce que le portrait voit, qui il lit ──


def test_the_portrait_names_the_person_as_its_own_place_says_never_from_another_account(world):
    """Relecture I1 : le nom donné au modèle était le nom global de la fiche — le plus récent, toutes sources
    confondues, donc peut-être lu dans le compte d'une autre (le profil Teams vu chez Béa) ; le fait tiré se disait
    ensuite au propriétaire de la vue. Le portrait de (Teams, equipe) le nomme comme cette vue le nomme."""
    seed(world)
    world.run()
    gilles = world.contacts.contact_of(TEAMS_ID, GILLES)
    world.contacts.observe_now([Observation(TEAMS_ID, GILLES, TEAMS, "chez_bea", "Gilles Rousseau-Secret", 0,
                                            NOW + HOUR, NOW + HOUR)])
    assert world.contacts.sheet(gilles).name == "Gilles Rousseau-Secret"  # le nom global, lu ailleurs
    world.now += 2 * HOUR
    world.teams_says(*gilles_writes(5, start=40, at=world.now // 1000 - 1000))
    (asked,) = world.run()
    text = asked.messages[0].content
    assert "Gilles Rousseau" in text and "Secret" not in text


def test_a_channel_or_a_big_group_is_not_an_exchange_a_small_group_answered_is(world):
    """Relecture I9 : Adrien poste une fois dans un canal ; tous ceux qui y écrivaient devenaient « avec qui il échange
    vraiment », et les plus bavards du canal prenaient les plafonds du jour. Un canal ne compte jamais ; un groupe,
    seulement petit (huit auteurs au plus) et quand Adrien y a répondu à la personne (écrit après elle)."""
    conversations = (InboxConversation("19:canal@thread.tacv2", "Général", "channel"),
                     InboxConversation("19:foule@thread.v2", "Tout le service", "group"),
                     InboxConversation("19:trio@thread.v2", "Trio", "group"),
                     InboxConversation("19:avant@thread.v2", "Avant", "group"))
    me = "8:orgid:adrien"
    messages = [InboxMessage("c0", "19:canal@thread.tacv2", "Adrien", me, MS - 100, "Bonjour à tous", own=True)]
    messages += [InboxMessage(f"c{i}", "19:canal@thread.tacv2", "Bavard", "8:orgid:bavard", MS - 90 + i, "Hello")
                 for i in range(1, 6)]
    messages += [InboxMessage(f"f{i}", "19:foule@thread.v2", f"P{i}", f"8:orgid:p{i}", MS - 80 + i, "Moi aussi")
                 for i in range(9)]
    messages.append(InboxMessage("f9", "19:foule@thread.v2", "Adrien", me, MS - 60, "Noté", own=True))
    messages += [InboxMessage("t1", "19:trio@thread.v2", "Zoé", "8:orgid:zoe", MS - 50, "On fait quoi ?"),
                 InboxMessage("t2", "19:trio@thread.v2", "Adrien", me, MS - 40, "On avance", own=True),
                 InboxMessage("a1", "19:avant@thread.v2", "Adrien", me, MS - 30, "Je pars", own=True),
                 InboxMessage("a2", "19:avant@thread.v2", "Yann", "8:orgid:yann", MS - 20, "Bon week-end")]
    world.teams.store_batch("equipe", InboxBatch(me, "Adrien", conversations, tuple(messages)), world.now)
    got = {key for _account, key, _n, _at in world.teams.exchanged((MS - 30 * DAY_MS) * 1000)}
    assert got == {"8:orgid:zoe"}  # ni le canal, ni la foule, ni Yann (Adrien n'a rien écrit après lui)
    mention = InboxMessage("a3", "19:avant@thread.v2", "Yann", "8:orgid:yann", MS - 10, "@Adrien ?", mentions_me=True)
    world.teams.store_batch("equipe", InboxBatch(me, "Adrien", conversations, (mention,)), world.now)
    got = {key for _account, key, _n, _at in world.teams.exchanged((MS - 30 * DAY_MS) * 1000)}
    assert got == {"8:orgid:zoe", "8:orgid:yann"}  # il s'adresse à lui, là où il écrit


def test_each_place_has_its_turn_so_one_talkative_account_does_not_take_the_day():
    """Relecture I9, l'ordre : les plus riches d'abord, mais chaque vue (source, compte) à son tour."""
    def c(contact, account, count):
        return Candidate(contact, TEAMS, account, f"k{contact}", count, NOW - contact)
    due = [c(1, "bavard", 50), c(2, "bavard", 40), c(3, "bavard", 30), c(4, "calme", 3), c(5, "pro", 4)]
    assert [x.contact for x in fair(due)] == [1, 4, 5, 2, 3]
    assert fair([]) == []


def test_a_phone_group_counts_only_small_and_answered():
    """Relecture I9, le téléphone : un groupe où la personne a écrit une fois ne fait pas de chacun quelqu'un avec qui
    elle échange ; il faut un petit groupe, et qu'elle ait écrit après lui. Un tête-à-tête où elle a écrit suffit."""
    def line(at, group, thread="t"):
        return Line(f"p{at}#{thread}", at, "", "x", group)
    assert phone_exchange(NOW, NOW - DAY_MS, [line(NOW - 5, False)], 2)
    assert not phone_exchange(0, NOW - DAY_MS, [line(NOW - 5, False)], 2)  # elle n'y a jamais écrit
    assert phone_exchange(NOW, NOW - DAY_MS, [line(NOW - 5, True)], 4)
    assert not phone_exchange(NOW - 10, NOW - DAY_MS, [line(NOW - 5, True)], 4)  # elle a écrit avant lui
    assert not phone_exchange(NOW, NOW - DAY_MS, [line(NOW - 5, True)], 9)  # un grand groupe
    lines = {("adrien", "whatsapp:a"): [line(1, True, "g"), line(2, True, "g")],
             ("adrien", "whatsapp:b"): [line(3, True, "g")], ("adrien", "whatsapp:c"): [line(4, False, "d")]}
    assert thread_people(lines) == {("adrien", "whatsapp", "g"): 3, ("adrien", "whatsapp", "d"): 2}


def test_a_fact_that_names_someone_else_is_not_kept(world):
    """Relecture I11 : la consigne demandait « avec qui elle travaille » ; un fait comme « Il travaille avec Paul Henry
    sur le budget » restait sur la fiche de Gilles, et l'oubli de Paul ne l'atteignait pas. Un fait qui nomme une autre
    personne de l'annuaire ne se garde pas (la consigne le demande aussi)."""
    seed(world)
    world.model.answer = json.dumps({"faits": [
        {"texte": "Il travaille avec Paul Henry sur le budget.", "sorte": "relation", "confiance": 0.8, "message": 1},
        {"texte": "Il attend la réponse de Bob avant vendredi.", "sorte": "expectation", "confiance": 0.7,
         "message": 1},
        {"texte": "Il suit le support des centrales.", "sorte": "topic", "confiance": 0.6, "message": 1}]})
    world.run()
    gilles = world.contacts.contact_of(TEAMS_ID, GILLES)
    assert [n.text for n in world.contacts.notes(gilles)] == ["Il suit le support des centrales."]
    assert "un fait qui nomme quelqu'un d'autre n'est pas gardé" in phrase("contacts.portrait.system", name="Mika")


def test_the_next_portrait_completes_the_sheet_it_was_given(world):
    """« C'est pour ça qu'un contact a une fiche » (2026-11-22) : six faits de son travail, remplacés à chaque passage,
    ne disaient rien de Kévin après 310 messages. Le portrait suivant reçoit ce qu'elle en sait et le complète."""
    seed(world)
    world.run()
    gilles = world.contacts.contact_of(TEAMS_ID, GILLES)
    (before,) = world.contacts.notes(gilles)
    world.now += HOUR
    world.teams_says(*gilles_writes(5, start=40, at=world.now // 1000 - 1000))
    world.model.answer = json.dumps({"faits": [
        {**FACT, "message": 0, "avant": 1},  # repris tel quel
        {"texte": "Il écrit vite, sans majuscules, et glisse souvent une blague.", "sorte": "manner",
         "confiance": 0.7, "message": 2, "avant": 0},
        {"texte": "Il tutoie la personne du compte et lui demande de ses nouvelles.", "sorte": "bond",
         "confiance": 0.8, "message": 1, "avant": 0}]})
    (asked,) = world.run()
    text = asked.messages[0].content
    known = phrase("contacts.portrait.known_line", n=1, kind="role", text=FACT["texte"])
    assert known in text and text.index(known) < text.index("Message 44 de Gilles")  # sa fiche, puis ses messages
    assert text.startswith(phrase("contacts.portrait.known", who="Gilles Rousseau", facts="")[:30])
    notes = {n.kind: n for n in world.contacts.notes(gilles)}
    assert set(notes) == {"role", "manner", "bond"}
    kept = notes["role"]  # ce qui le fondait reste : son message, sa date, quand elle l'avait appris
    assert (kept.text, kept.ref, kept.said_at, kept.at) == (before.text, before.ref, before.said_at, before.at)
    assert kept.call_id == asked.call_id  # le texte est celui de ce passage
    assert notes["bond"].said_at == (world.now // 1000 - 1000 + 4) * 1000 and notes["bond"].at == world.now


def test_a_fact_made_more_precise_takes_the_new_message_and_a_fact_let_go_leaves(world):
    seed(world)
    topic = "Il suit le support des centrales."
    world.model.answer = json.dumps({"faits": [FACT, {"texte": topic, "sorte": "topic", "confiance": 0.6,
                                                      "message": 2}]})
    world.run()
    gilles = world.contacts.contact_of(TEAMS_ID, GILLES)
    role = next(n for n in world.contacts.notes(gilles) if n.text == FACT["texte"])
    world.now += HOUR
    world.teams_says(*gilles_writes(5, start=50, at=world.now // 1000 - 1000))
    number = {n.text: i for i, n in enumerate(world.contacts.notes(gilles), 1)}
    world.model.answer = json.dumps({"faits": [
        {"texte": "Il pilote la migration des centrales vers le VPN, à finir en décembre.", "sorte": "role",
         "confiance": 0.9, "message": 1, "avant": number[FACT["texte"]]}], "laisse": [number[topic]]})
    (asked,) = world.run()
    # chaque fait d'avant sous son numéro, distinct de ceux des messages
    for text, n in number.items():
        assert phrase("contacts.portrait.known_line", n=n, kind="role" if text == FACT["texte"] else "topic",
                      text=text) in asked.messages[0].content
    (now_,) = world.contacts.notes(gilles)  # précisé, il remplace l'ancien ; le sujet, laissé, part
    assert now_.text.endswith("à finir en décembre.") and now_.ref != role.ref and now_.at == world.now


def test_a_partial_answer_erases_nothing(world):
    """Relecture du 2026-11-22 : la fiche entière demandée au modèle, une réponse qui n'en rendait qu'une part (ou un
    fait mal formé, la CLI ne garantissant pas le schéma) effaçait le reste pour de bon."""
    seed(world)
    world.run()
    gilles = world.contacts.contact_of(TEAMS_ID, GILLES)
    (before,) = world.contacts.notes(gilles)
    world.now += HOUR
    world.teams_says(*gilles_writes(5, start=60, at=world.now // 1000 - 1000))
    world.model.answer = json.dumps({"faits": [
        {"texte": "Il glisse souvent une blague.", "sorte": "manner", "confiance": 0.7, "message": 1, "avant": 0},
        {**FACT, "message": 0, "avant": "1"}]})  # un numéro mal écrit : ce fait-là tombe, l'ancien reste
    world.run()
    notes = {n.text: n for n in world.contacts.notes(gilles)}
    assert set(notes) == {"Il glisse souvent une blague.", FACT["texte"]}
    assert (notes[FACT["texte"]].ref, notes[FACT["texte"]].at) == (before.ref, before.at)  # tel quel


def test_a_fact_whose_message_is_gone_is_neither_shown_nor_kept(world):
    seed(world)
    world.run()
    gilles = world.contacts.contact_of(TEAMS_ID, GILLES)
    (before,) = world.contacts.notes(gilles)
    # son message est supprimé dans Teams : le cache en efface le texte
    world.teams_says(InboxMessage("g3", DM, "Gilles Rousseau", GILLES, MS - HOUR_MS + 3, "", deleted=True))
    world.now += HOUR
    world.teams_says(*gilles_writes(5, start=70, at=world.now // 1000 - 1000))
    world.model.answer = json.dumps({"faits": [], "laisse": []})  # rien de nouveau
    (asked,) = world.run()
    assert before.text not in asked.messages[0].content
    assert world.contacts.notes(gilles) == []  # parti, comme avant que la fiche ne s'enrichisse


def test_what_is_forgotten_during_the_call_does_not_come_back(world):
    seed(world)
    world.model.answer = json.dumps({"faits": [FACT, {"texte": "Il suit le support des centrales.", "sorte": "topic",
                                                      "confiance": 0.6, "message": 2}]})
    world.run()
    gilles = world.contacts.contact_of(TEAMS_ID, GILLES)
    number = {n.text: (i, n.id) for i, n in enumerate(world.contacts.notes(gilles), 1)}
    world.now += HOUR
    world.teams_says(*gilles_writes(5, start=80, at=world.now // 1000 - 1000))

    def meanwhile(request):  # pendant l'appel, on lui fait oublier les deux faits
        for _n, note_id in number.values():
            world.contacts.forget_note(note_id)
        return json.dumps({"faits": [{"texte": "Il pilote toujours la migration des centrales vers le VPN.",
                                      "sorte": "role", "confiance": 0.9, "message": 0,
                                      "avant": number[FACT["texte"]][0]}], "laisse": []})

    world.model.answer = meanwhile
    world.run()
    assert world.contacts.notes(gilles) == []  # ni repris, ni tel quel
