"""Réunir ses contacts (ADR 0304) : d'office quand c'est sûr, un juge pour le reste — sur le vrai annuaire, le vrai
cache de Teams et un faux modèle (aucun appel réel).

- **un identifiant Teams se compare sous sa forme canonique** : « worker/8:orgid:<uuid> » et « 8:orgid:<uuid> » sont
  le même auteur dans le cache de Teams et la même fiche dans l'annuaire ;
- **qui le juge voit** (``likenesses``) : les paires des suggestions, et celles qui ont un mot rare de leurs noms en
  commun quelle que soit sa forme — jamais un mot que beaucoup portent, ni le même prénom seul, ni deux fiches
  séparées par une opératrice, reliées à deux personnes, ou un nom raconté face à quelqu'un qui lui parle ;
- **ce qu'il en fait** : sûr de la même personne, il les réunit (gardé, défaisable) ; sûr de deux, elles ne sont plus
  proposées (sans empêcher une preuve de les réunir plus tard) ; sinon elles t'attendent avec son avis. Un avis ne vaut
  que sur ce qu'il a vu : une fiche qui change se rejuge ;
- **sa réponse** est relue strictement : illisible, rien ne change et le groupe n'est pas redemandé tant que ses
  fiches ne changent pas ; une panne n'est pas comptée ; des plafonds par passage et par jour ;
- **ce qu'il voit d'une fiche** : ses noms, son organisation, ses adresses, la sorte de son compte Teams (jamais son
  identifiant), les conversations où elle écrit ; l'oubli emporte ses avis et ses réunions.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from mika.adapters.contacts import ContactsStore
from mika.adapters.teams import TeamsAccount, TeamsConfig, TeamsStore
from mika.adapters.teams.store import same_person
from mika.contracts import identity as identity_c
from mika.contracts import self_ as self_c
from mika.inspector.text import render
from mika.kernel.inspect import InspectContext
from mika.plugins.contacts import CONTACTS, ContactsParams, ContactsState
from mika.plugins.contacts.inspect import _matches
from mika.plugins.contacts.matching import (
    EVERY,
    GROUP_MAX,
    MATCH_SCHEMA,
    ROLE,
    Matching,
    Verdict,
    groups,
    parse,
    verdicts,
)
from mika.ports.contacts import (
    APART,
    EMAIL,
    MAIL,
    PHONE,
    SAME,
    TEAMS,
    TEAMS_ID,
    TOLD,
    TOLD_NAME,
    JudgeCall,
    Judgement,
    Likeness,
    Observation,
    normalized,
    pair_basis,
)
from mika.ports.llm import LLMResponse
from mika.ports.teams import InboxBatch, InboxConversation, InboxMessage
from tests.fixtures import backend

NOW = 1_790_000_000_000_000
DAY = 86_400_000_000
ADRIEN = "user_1"
KEVIN = "8:orgid:5de5780c-0012-4111-a4a0-658addef044b"
ROMAIN = "8:orgid:63be7eb2-bf06-4b41-8de7-2070747d4dad"
VISITOR = "8:teamsvisitor:8d5727cf5a004b6cbdae2c6915030b6e"
MEETING = "19:meeting_auchan@thread.v2"


class Frame:
    def __init__(self, world: World) -> None:
        self.now, self.root = world.now, None
        self.env = SimpleNamespace(params_of=lambda name, root: world.params if name == CONTACTS.name else None)

    def get(self, key):
        if key == self_c.PERSONA:
            return SimpleNamespace(name="Mika")
        if getattr(key, "family", None) is identity_c.IDENTITY:
            return SimpleNamespace(name={ADRIEN: "Adrien"}.get(key.arg, ""))
        return None

    def local(self, t: int | None = None) -> datetime:
        return datetime.fromtimestamp((self.now if t is None else t) / 1_000_000, tz=UTC)


def cards(request) -> dict[str, list[int]]:
    """Les numéros des fiches du prompt, par nom."""
    out: dict[str, list[int]] = {}
    for n, name in re.findall(r"\[(\d+)\] « (.+?) »", request.messages[0].content):
        out.setdefault(name, []).append(int(n))
    return out


class Model:
    """Le faux juge : ce qu'il répond (un texte, une fonction de la requête, ``None`` : une panne)."""

    def __init__(self) -> None:
        self.answer: object = None
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
    def __init__(self, tmp) -> None:
        self.now = NOW
        self.params = ContactsParams()
        self.contacts = ContactsStore(backend.target(tmp, "contacts"), now=lambda: self.now)
        self.teams = TeamsStore(lambda: TeamsConfig(accounts={"equipe": TeamsAccount(owner="personne:" + ADRIEN)}),
                                tmp / "teams.db", now=lambda: self.now)
        self.model = Model()
        self.process = Matching()

    def run(self) -> None:
        ctx = SimpleNamespace(state=ContactsState(), ports={"contacts": self.contacts, "teams": self.teams},
                              frame=Frame(self), now=self.now, llm=self.model, run_id="run", ask=self.model.ask)
        asyncio.run(self.process.run(ctx))

    # ── ce que l'annuaire a rangé ──
    def teams_seen(self, author: str, name: str, *, count: int = 3, email: str = "") -> int:
        seen = [Observation(TEAMS_ID, author, TEAMS, "equipe", name, count, self.now - DAY, self.now)]
        if email:
            seen.append(Observation(EMAIL, email, TEAMS, "equipe", name, 0, self.now, self.now,
                                    joins=(TEAMS_ID, author), proof=True))
        self.contacts.observe_now(seen)
        return self.contacts.contact_of(TEAMS_ID, author)

    def mail_seen(self, address: str, name: str) -> int:
        self.contacts.observe_now([Observation(EMAIL, address, MAIL, "perso", name, 2, self.now - DAY, self.now)])
        return self.contacts.contact_of(EMAIL, address)

    def told(self, key: str, name: str, by: str = ADRIEN) -> int:
        self.contacts.observe_now([Observation(TOLD_NAME, key, TOLD, by, name, 1, self.now, self.now)])
        return self.contacts.contact_of(TOLD_NAME, key)

    def pairs(self) -> set[frozenset[str]]:
        return {frozenset((x.a.name, x.b.name)) for x in self.contacts.suggestions()}


@pytest.fixture
def world(tmp_path):
    found = World(tmp_path)
    yield found
    found.contacts.close()
    found.teams.close()


def person(cards_: list[int], sure: bool, why: str = "") -> dict:
    return {"fiches": cards_, "sure": sure, "raison": why}


# ── un identifiant Teams, une forme ──


def test_a_teams_identifier_is_the_same_whatever_form_it_arrives_in(world):
    assert normalized(TEAMS_ID, "Worker/8:orgid:5DE5780C-0012-4111-A4A0-658ADDEF044B ") == KEVIN
    assert normalized(TEAMS_ID, "https://x/v1/users/ME/contacts/8:orgid:5de5780c-0012-4111-a4a0-658addef044b") == KEVIN
    assert normalized(TEAMS_ID, VISITOR.upper()) == VISITOR  # un invité n'a pas d'autre forme
    first = world.teams_seen(KEVIN, "Kévin MASSOL-EXT", count=310)
    again = world.teams_seen("worker/" + KEVIN, "Kévin MASSOL-EXT", count=3)
    assert again == first and world.contacts.contact_of(TEAMS_ID, "worker/" + KEVIN) == first
    sheet = world.contacts.sheet(first)
    assert [(i.kind, i.value) for i in sheet.identifiers] == [(TEAMS_ID, KEVIN)]
    assert sheet.identifiers[0].sightings[0].count == 313
    assert world.contacts.suggestions() == []


def test_the_teams_cache_files_an_author_under_one_key(world):
    world.teams.store_batch("equipe", InboxBatch("8:orgid:adrien", "Adrien", (InboxConversation(MEETING, "", "dm"),), (
        InboxMessage("m1", MEETING, "Kévin MASSOL-EXT", KEVIN, NOW // 1000 - 5000, "Bonjour"),
        InboxMessage("m2", MEETING, "Kévin MASSOL-EXT", "worker/" + KEVIN.upper(), NOW // 1000 - 4000, "Ça va ?"),
    )), NOW)
    assert len(world.teams.authored(["worker/" + KEVIN])) == 2 and len(world.teams.authored([KEVIN])) == 2
    assert len([p for p in world.teams.people_since((0, 0), 100).people]) == 1
    assert same_person("worker/" + KEVIN, KEVIN.upper()) and not same_person("", "")


# ── qui le juge voit ──


def test_a_rare_word_brings_two_cards_to_the_judge_whatever_its_form(world):
    told = world.told("name:p:kevin massol", "Kévin Massol")
    teams = world.teams_seen(KEVIN, "Kévin MASSOL-EXT")
    becuwe = world.teams_seen("8:orgid:becuwe", "Kévin BECUWE")
    for i, surname in enumerate(("AUCLERT", "CHAN", "TURKI", "YAHIA", "PICARD", "DHOUIBI", "GAOUAR", "MISSIE",
                                 "OLSCHANEZKY", "BORILLA", "CORRIERE")):
        world.teams_seen(f"8:orgid:ext{i}", f"Paul {surname}-EXT")
    found = {(x.a, x.b): x for x in world.contacts.likenesses()}
    assert found[(min(told, teams), max(told, teams))].rule == "words"
    # le même prénom seul ne rapproche pas ; « ext », que tous les prestataires portent, non plus
    assert (min(teams, becuwe), max(teams, becuwe)) not in found and (told, becuwe) not in found
    assert not any(x.rule == "words" and "EXT" in world.contacts.sheet(x.a).name
                   and "EXT" in world.contacts.sheet(x.b).name for x in found.values())
    # sans avis du juge, un mot rare seul ne t'est pas proposé (seul le nom l'est)
    assert world.pairs() == set()


def test_the_judge_never_sees_what_you_separated_nor_two_people_who_talk_to_her(world):
    a, b = world.teams_seen("8:orgid:p1", "Pascal Martin"), world.mail_seen("pascal@beta.fr", "Pascal Martin")
    c, d = world.teams_seen("8:orgid:j1", "Julie Roy"), world.mail_seen("julie@roy.fr", "Julie Roy")
    lea, told = world.teams_seen("8:orgid:lea", "Léa Morel"), world.told("name:p:lea morel", "Léa Morel")
    world.contacts.dismiss(a, b)
    world.contacts.link(c, "user_2")
    world.contacts.link(d, "user_3")
    world.contacts.link(lea, ADRIEN)
    assert {(x.a, x.b) for x in world.contacts.likenesses()} == set()
    assert world.contacts.unite(a, b) == 0 and world.contacts.unite(c, d) == 0 and world.contacts.unite(lea, told) == 0
    assert world.contacts.joined() == []


# ── ce qu'il en fait ──


def romain(world) -> tuple[int, int]:
    """Romain chez Auchan (son compte et son adresse), et un invité de réunion qui a tapé ce nom."""
    org = world.teams_seen(ROMAIN, "Romain CATANZARITI", count=20, email="rcatanzariti@auchan.fr")
    guest = world.teams_seen(VISITOR, "Romain Catanzariti", count=1)
    world.teams.store_batch("equipe", InboxBatch("8:orgid:adrien", "Adrien", (
        InboxConversation(MEETING, "Point ESL Auchan", "meeting"),), (
        InboxMessage("v1", MEETING, "Romain Catanzariti", VISITOR, NOW // 1000 - 3000, "Je vous entends ?"),)), NOW)
    return org, guest


def test_what_the_judge_is_sure_of_is_united_at_once_and_kept(world):
    org, guest = romain(world)
    assert world.pairs() == {frozenset(("Romain CATANZARITI", "Romain Catanzariti"))}
    world.model.answer = lambda r: json.dumps({"personnes": [person(sorted(n for ns in cards(r).values() for n in ns),
                                                                     True, "Même nom, invité d'une réunion Auchan.")],
                                               "differentes": []})
    world.run()
    (request,) = world.model.asked
    assert request.role == ROLE and request.output_schema == MATCH_SCHEMA and "Mika" in request.system_stable
    text = request.messages[0].content
    assert "un invité anonyme d'une réunion" in text and "un compte de son organisation" in text
    assert "rcatanzariti@auchan.fr" in text and "auchan.fr" in text and "« Point ESL Auchan »" in text
    assert VISITOR not in text and ROMAIN not in text  # un identifiant Teams ne dit rien au juge
    left = {world.contacts.contact_of(TEAMS_ID, ROMAIN), world.contacts.contact_of(TEAMS_ID, VISITOR)}
    assert len(left) == 1 and left <= {org, guest}
    (joined,) = world.contacts.joined()
    assert joined.reason == "Même nom, invité d'une réunion Auchan." and joined.call_id == request.call_id
    assert {joined.kept, joined.gone} == {"Romain CATANZARITI", "Romain Catanzariti"}
    assert world.pairs() == set() and len(world.contacts.judge_calls()) == 1
    world.now += 2 * EVERY
    world.run()
    assert len(world.model.asked) == 1  # rien de neuf : rien à rejuger
    # l'oubli emporte la fiche gardée, ses avis et ses réunions
    asyncio.run(world.contacts.forget(f"contact:{left.pop()}"))
    assert world.contacts.joined() == [] and world.contacts.judgements() == []


def test_what_the_judge_doubts_waits_for_you_with_its_words(world):
    told = world.told("name:p:kevin massol", "Kévin Massol")
    teams = world.teams_seen(KEVIN, "Kévin MASSOL-EXT")
    world.model.answer = lambda r: json.dumps({"personnes": [person([1, 2], False, "Le même nom de famille ; rien "
                                                                                   "d'autre ne le recoupe.")],
                                               "differentes": []})
    world.run()
    (x,) = world.contacts.suggestions()
    assert {x.a.id, x.b.id} == {told, teams} and x.reason == "words" and x.verdict == SAME
    assert x.why == "Le même nom de famille ; rien d'autre ne le recoupe."
    assert world.contacts.joined() == []
    # sa fiche change (une adresse de plus) : l'avis ne vaut plus, la paire se rejuge au passage suivant
    world.contacts.observe_now([Observation(EMAIL, "kevin.massol-ext@mousquetaires.com", TEAMS, "equipe",
                                            "Kévin MASSOL-EXT", 0, NOW, NOW, joins=(TEAMS_ID, KEVIN), proof=True)])
    assert world.contacts.suggestions() == []
    world.now += 2 * EVERY
    world.run()
    assert len(world.model.asked) == 2 and "kevin.massol-ext@mousquetaires.com" in world.model.asked[1].messages[0].content


def test_two_people_the_judge_knows_apart_are_no_longer_proposed_but_a_proof_still_unites_them(world):
    a, b = world.teams_seen("8:orgid:p1", "Pascal Martin"), world.mail_seen("pascal@beta.fr", "Pascal Martin")
    assert world.pairs() == {frozenset(("Pascal Martin",))}
    world.model.answer = json.dumps({"personnes": [person([1], True), person([2], True)],
                                     "differentes": [{"fiches": [2, 1], "raison": "Deux entreprises."}]})
    world.run()
    assert world.contacts.suggestions() == []
    (j,) = world.contacts.judgements()
    assert (j.verdict, j.sure, j.reason) == (APART, True, "Deux entreprises.")
    # ce n'est pas une opératrice qui les a séparées : une preuve les réunit encore
    assert world.contacts.unite(a, b) in (a, b)


def test_an_unreadable_answer_changes_nothing_and_a_failure_is_not_counted(world):
    world.teams_seen("8:orgid:p1", "Pascal Martin"), world.mail_seen("pascal@beta.fr", "Pascal Martin")
    world.model.answer = None  # une panne
    world.run()
    assert len(world.model.asked) == 1 and world.contacts.judge_calls() == [] and world.contacts.judgements() == []
    world.model.answer = "je ne sais pas"
    world.now += 2 * EVERY
    world.run()
    (call,) = world.contacts.judge_calls()
    assert not call.ok and [j.verdict for j in world.contacts.judgements()] == [""]
    assert world.pairs() == {frozenset(("Pascal Martin",))}  # elle t'attend, sans avis
    world.now += 2 * EVERY
    world.run()
    assert len(world.model.asked) == 2  # pas redemandée tant que ses fiches ne changent pas


def test_the_judge_keeps_to_its_caps_and_can_be_turned_off(world):
    for surname in ("Martin", "Roy", "Morel"):
        world.teams_seen(f"8:orgid:{surname}", f"Paul {surname}")
        world.mail_seen(f"paul@{surname.lower()}.fr", f"Paul {surname}")
    world.model.answer = json.dumps({"personnes": [person([1, 2], False)], "differentes": []})
    world.params = ContactsParams(match_per_run=2, match_calls_per_day=2)
    world.run()
    assert len(world.model.asked) == 2
    world.now += 2 * EVERY
    world.run()
    assert len(world.model.asked) == 2  # le jour est plein
    world.now += DAY
    world.run()
    assert len(world.model.asked) == 3
    world.params = ContactsParams(matching=False)
    assert world.process.next_due(None, Frame(world), None) is None


# ── sa réponse ──


def test_the_answer_is_read_strictly():
    assert parse("pas de JSON", 3) is None and parse('{"personnes": "non"}', 3) is None
    assert parse('{"personnes": [{"fiches": [9], "sure": true}]}', 3) is None  # aucune fiche qui tienne
    got = parse('Voici : {"personnes": [{"fiches": [1, 2, 2, true], "sure": true, "raison": "  même   compte "},'
                ' {"fiches": [2, 3], "sure": "oui"}], "differentes": [{"fiches": [3, 1]}, {"fiches": [1]}]}', 3)
    assert isinstance(got, Verdict) and len(got.people) == 2
    assert got.people[0].cards == (1, 2) and got.people[0].sure and got.people[0].reason == "même compte"
    assert got.people[1].cards == (3,) and not got.people[1].sure  # « oui » n'est pas vrai ; 2 était déjà placée
    assert got.apart == ((1, 3, ""),)
    # la même personne et deux à la fois : il n'en est pas sûr
    torn = parse('{"personnes": [{"fiches": [1, 2], "sure": true}], "differentes": [{"fiches": [1, 2]}]}', 2)
    assert not torn.people[0].sure and torn.apart == ()
    long = parse(json.dumps({"personnes": [{"fiches": [1], "sure": True, "raison": "x" * 900}]}), 1)
    assert len(long.people[0].reason) == 300


def test_each_pair_of_a_group_gets_its_verdict():
    order, bases = [7, 3, 5], {7: "a", 3: "b", 5: "c"}
    got = {(j.a, j.b): j for j in verdicts(order, parse(json.dumps(
        {"personnes": [person([1, 2], True, "oui")], "differentes": []}), 3), bases, NOW, "c1")}
    assert (got[(3, 7)].verdict, got[(3, 7)].sure, got[(3, 7)].reason) == (SAME, True, "oui")
    assert (got[(5, 7)].verdict, got[(5, 7)].sure) == (APART, False) and got[(3, 5)].verdict == APART
    assert got[(3, 7)].basis == pair_basis("a", "b")
    assert {j.verdict for j in verdicts(order, None, bases, NOW, "c1")} == {""}


def test_a_verdict_only_holds_for_what_the_judge_saw(world):
    a, b = world.teams_seen("8:orgid:p1", "Pascal Martin"), world.mail_seen("pascal@beta.fr", "Pascal Martin")
    bases = world.contacts.bases([a, b])
    world.contacts.judged(JudgeCall(NOW, "c1", 2), [Judgement(a, b, APART, True, "non", pair_basis(bases[a], bases[b]),
                                                              NOW, "c1")])
    assert world.contacts.suggestions() == []
    world.contacts.observe_now([Observation(PHONE, "06 12 34 56 78", TEAMS, "equipe", "Pascal Martin", 0, NOW, NOW,
                                            joins=(TEAMS_ID, "8:orgid:p1"))])
    assert world.pairs() == {frozenset(("Pascal Martin",))}  # un identifiant de plus : l'avis ne vaut plus


def test_the_console_view_says_what_waits_what_was_united_and_what_is_apart(world):
    romain(world)
    world.teams_seen("8:orgid:p1", "Pascal Martin"), world.mail_seen("pascal@beta.fr", "Pascal Martin")
    world.teams_seen("8:orgid:j1", "Julie Roy"), world.mail_seen("julie@roy.fr", "Julie Roy")

    def answer(r):
        names = cards(r)
        if "Romain CATANZARITI" in names:
            return json.dumps({"personnes": [person([1, 2], True, "Le même, invité d'Auchan.")], "differentes": []})
        if "Pascal Martin" in names:
            return json.dumps({"personnes": [person([1], True), person([2], True)],
                               "differentes": [{"fiches": [1, 2], "raison": "Deux entreprises."}]})
        return json.dumps({"personnes": [person([1, 2], False, "Rien ne le recoupe.")], "differentes": []})

    world.model.answer = answer
    world.run()
    blocks = _matches(ContactsState(), Frame(world), InspectContext(store=None, ports={"contacts": world.contacts}))
    text = render(blocks, str, NOW)
    assert "à valider : 1" in text and "réunies d'office : 1" in text and "dites deux personnes : 1" in text
    assert "appels du juge en 24 h : 3 / 40" in text
    assert "la même personne, sans en être sûr" in text and "Rien ne le recoupe." in text
    assert "Le même, invité d'Auchan." in text and "Deux entreprises." in text



def test_a_group_always_holds_the_pair_that_opened_it():
    likes = [Likeness(i, 100, "same_name", 200 - i) for i in range(2, 12)] + [Likeness(1, 100, "words", 12)]
    due = [Likeness(1, 100, "words", 12)]
    (group,) = groups(due, likes)
    assert group[0] == 100 and 1 in group and len(group) == GROUP_MAX
    assert groups([], likes) == []  # rien à juger : aucun appel


# ── ce que la relecture a montré ──


def test_a_told_name_never_reaches_someone_who_talks_to_her_through_another_card(world):
    linked = world.mail_seen("lea@morel.fr", "Léa Morel")
    world.contacts.link(linked, "user_2")
    told = world.told("name:p:lea morel", "Léa Morel")
    middle = world.teams_seen("8:orgid:lea", "Léa Morel")  # la plus récente : elle ouvre le groupe des trois
    world.model.answer = lambda r: json.dumps({"personnes": [person([1, 2, 3], True, "Le même nom partout.")],
                                               "differentes": []})
    world.run()
    assert len(cards(world.model.asked[0]).get("Léa Morel", [])) == 3
    # quel que soit l'ordre des réunions, le nom raconté ne finit jamais sur une fiche reliée à quelqu'un qui lui parle
    holder = world.contacts.sheet(world.contacts.contact_of(TOLD_NAME, "name:p:lea morel"))
    assert holder.person == "" and holder.id != world.contacts.contact_of(EMAIL, "lea@morel.fr")
    assert world.contacts.sheet(world.contacts.contact_of(EMAIL, "lea@morel.fr")).person == "user_2"
    assert {told, middle, linked} >= {holder.id}


def test_forgetting_someone_takes_the_judges_words_that_name_them(world):
    kevin = world.told("name:p:kevin massol", "Kévin Massol")
    a, b = world.teams_seen("8:orgid:p1", "Pascal Martin"), world.mail_seen("pascal@beta.fr", "Pascal Martin")
    bases = world.contacts.bases([a, b])
    world.contacts.judged(JudgeCall(NOW, "c1", 3), [
        Judgement(a, b, SAME, False, "Comme Kévin Massol, le même nom.", pair_basis(bases[a], bases[b]), NOW, "c1")])
    asyncio.run(world.contacts.forget(f"contact:{kevin}"))
    assert world.contacts.judgements() == []


def test_detaching_what_the_judge_united_takes_its_trace(world):
    org, _guest = romain(world)
    world.model.answer = lambda r: json.dumps({"personnes": [person([1, 2], True, "Le même.")], "differentes": []})
    world.run()
    (joined,) = world.contacts.joined()
    sheet = world.contacts.sheet(joined.keep)
    visitor = next(i for i in sheet.identifiers if i.value == VISITOR)
    world.contacts.detach(visitor.id)
    assert world.contacts.joined() == []


def test_a_card_that_changed_during_the_call_is_not_united(world):
    org, guest = romain(world)

    def answer(r):  # pendant l'appel, une preuve change la fiche de l'invité
        world.contacts.observe_now([Observation(PHONE, "06 11 22 33 44", TEAMS, "equipe", "Romain Catanzariti", 0, NOW,
                                                NOW, joins=(TEAMS_ID, VISITOR))])
        return json.dumps({"personnes": [person([1, 2], True, "Le même.")], "differentes": []})

    world.model.answer = answer
    world.run()
    assert world.contacts.joined() == [] and world.contacts.contact_of(TEAMS_ID, VISITOR) == guest
    world.now += 2 * EVERY
    world.model.answer = json.dumps({"personnes": [person([1, 2], False, "Peut-être.")], "differentes": []})
    world.run()
    assert len(world.model.asked) == 2  # son avis s'est refait sur ce qu'elle est devenue


def test_a_card_she_cannot_show_waits_without_a_call(world):
    world.told("name:p:lea morel", "Léa Morel")
    world.teams_seen("8:orgid:lea", "Léa Morel")
    world.contacts.reset_source(TOLD)  # plus rien de vu du nom raconté, le temps d'une relecture
    world.model.answer = json.dumps({"personnes": [person([1, 2], True)], "differentes": []})
    world.run()
    world.now += 2 * EVERY
    world.run()
    assert world.model.asked == [] and world.contacts.judge_calls() == []
    assert [j.verdict for j in world.contacts.judgements()] == [""]


def test_a_teams_person_is_forgotten_under_the_same_subject_whatever_the_form():
    from mika.contracts.teams import person_handle

    assert person_handle("worker/" + KEVIN.upper()) == person_handle(KEVIN) == "teams:" + KEVIN
    assert person_handle("  ") == ""
