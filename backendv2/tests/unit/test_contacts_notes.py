"""Ce qu'elle sait d'un contact (ADR 0298, lot 6), dans l'annuaire : les faits d'un portrait et leur oubli.

- **un portrait remplace** les faits de la même vue (contact, source, compte), pas ceux d'une autre ; un portrait
  illisible (ou sans rien de sûr) laisse ceux d'avant ; chaque passage est noté ;
- **ce qui est visible** : les faits d'une vue ne se lisent que pour qui voit cette vue ;
- **oublier un fait** : il part, son empreinte reste (jamais son texte), et le même fait — reformulé — ne se garde
  plus ; un autre fait, si ;
- **ils suivent le contact** : réuni à un autre, ils le suivent ; oublié (lui, son identifiant, la personne reliée) ou
  son compte retiré, ils partent.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from mika.adapters.contacts import ContactsStore
from mika.adapters.contacts.models import NoteForgottenRow
from mika.ports.contacts import (
    EMAIL,
    MAIL,
    PHONE_APP,
    PHONE_SOURCE,
    TEAMS,
    TEAMS_ID,
    Note,
    Observation,
    Portrait,
    note_print,
    note_words,
    relearned,
)
from tests.fixtures import backend

NOW = 1_790_000_000_000_000
HOUR = 3_600_000_000


@pytest.fixture
def store(tmp_path):
    found = ContactsStore(backend.target(tmp_path, "contacts"), now=lambda: NOW)
    yield found
    found.close()


def gilles(store: ContactsStore) -> int:
    store.observe_now([Observation(TEAMS_ID, "8:orgid:gilles", TEAMS, "equipe", "Gilles Rousseau", 4, NOW - HOUR, NOW),
                       Observation(TEAMS_ID, "8:orgid:gilles", TEAMS, "autre", "Gilles Rousseau", 2, NOW - HOUR, NOW)])
    return store.contact_of(TEAMS_ID, "8:orgid:gilles")


def note(text: str, cid: int, source: str = TEAMS, account: str = "equipe", confidence: float = 0.8) -> Note:
    return Note(0, cid, source, account, text, "role", confidence, "m1", "en tête-à-tête", NOW - HOUR, NOW, "run#1")


def portrait(cid: int, account: str = "equipe", *, ok: bool = True, at: int = NOW) -> Portrait:
    return Portrait(cid, TEAMS, account, at, NOW - HOUR, 4, ok=ok, call_id="run#1")


def texts(store: ContactsStore, cid: int, **kw) -> list[str]:
    return [n.text for n in store.notes(cid, **kw)]


def test_a_portrait_replaces_the_facts_of_its_own_place_only(store):
    cid = gilles(store)
    assert store.portrayed(portrait(cid), [note("Il est responsable réseau chez Nordis.", cid),
                                           note("Il suit la migration des centrales.", cid, confidence=0.6)]) == 2
    assert store.portrayed(portrait(cid, "autre"), [note("Il attend le devis avant vendredi.", cid,
                                                         account="autre")]) == 1
    assert texts(store, cid) == ["Il est responsable réseau chez Nordis.", "Il attend le devis avant vendredi.",
                                 "Il suit la migration des centrales."]  # les plus sûrs d'abord
    first = store.notes(cid)[0]
    assert (first.kind, first.confidence, first.ref, first.place, first.call_id) == (
        "role", 0.8, "m1", "en tête-à-tête", "run#1")
    # le portrait suivant de la même vue remplace ses faits, pas ceux de l'autre compte
    assert store.portrayed(portrait(cid, at=NOW + HOUR), [note("Il pilote le déploiement des PDV.", cid)]) == 1
    assert sorted(texts(store, cid)) == ["Il attend le devis avant vendredi.", "Il pilote le déploiement des PDV."]
    # illisible : rien ne change, mais le passage est noté
    assert store.portrayed(portrait(cid, at=NOW + 2 * HOUR, ok=False), None) == 0
    assert sorted(texts(store, cid)) == ["Il attend le devis avant vendredi.", "Il pilote le déploiement des PDV."]
    done = store.portraits(contacts={cid})
    assert [(p.account, p.ok, p.at) for p in done] == [("equipe", False, NOW + 2 * HOUR), ("equipe", True, NOW + HOUR),
                                                       ("autre", True, NOW), ("equipe", True, NOW)]
    assert len(store.portraits(since=NOW + HOUR)) == 2 and store.portraits(contacts=set()) == []
    # un contact qui n'existe plus : rien n'est gardé
    assert store.portrayed(portrait(999), [note("x", 999)]) == 0 and store.portraits(contacts={999}) == []


def test_facts_are_read_only_where_their_place_is_visible(store):
    cid = gilles(store)
    store.portrayed(portrait(cid), [note("Il est responsable réseau.", cid)])
    store.portrayed(portrait(cid, "autre"), [note("Il attend le devis.", cid, account="autre")])
    assert texts(store, cid, visible={(TEAMS, "equipe")}) == ["Il est responsable réseau."]
    assert texts(store, cid, visible={(MAIL, "equipe")}) == [] and texts(store, cid, visible=set()) == []
    assert len(texts(store, cid)) == 2  # une opératrice : tous


def test_a_forgotten_fact_leaves_a_print_never_its_text_and_is_not_relearned(store):
    cid = gilles(store)
    store.portrayed(portrait(cid), [note("Il est responsable réseau chez Nordis.", cid),
                                    note("Il suit la migration des centrales.", cid)])
    gone = next(n for n in store.notes(cid) if "réseau" in n.text)
    assert store.forget_note(gone.id).text == gone.text and store.note(gone.id) is None
    assert store.forget_note(gone.id) is None
    with store._session() as s:
        (kept,) = s.scalars(select(NoteForgottenRow)).all()
    assert kept.contact == cid and "réseau" not in kept.prints and "Nordis" not in kept.prints
    assert kept.prints == note_print(gone.text)
    # le même fait, reformulé, ne se garde plus ; un autre, si
    store.portrayed(portrait(cid, at=NOW + HOUR), [note("Responsable du réseau chez Nordis, il le gère.", cid),
                                                   note("Il prépare la recette du VPN.", cid)])
    assert texts(store, cid) == ["Il prépare la recette du VPN."]


def test_the_relearned_rule_compares_words_by_their_prints():
    prints = [note_print("Il est responsable réseau chez Nordis.")]
    assert relearned("Responsable réseau chez Nordis", prints)
    assert not relearned("Il attend le devis avant vendredi.", prints)
    assert not relearned("Il a dit oui.", prints)  # aucun mot qui compte : rien à comparer
    assert note_words("Il gère le réseau, à Nesle !") == {"gere", "reseau", "nesle"}


def test_facts_follow_a_merge_and_leave_with_their_contact_or_their_account(store):
    cid = gilles(store)
    store.observe_now([Observation(EMAIL, "gilles@nordis.fr", MAIL, "pro", "Gilles R.", 3, NOW - HOUR, NOW),
                       Observation(PHONE_APP, "whatsapp:ab12", PHONE_SOURCE, "user_1", "Gilles", 2, NOW - HOUR, NOW)])
    other = store.contact_of(EMAIL, "gilles@nordis.fr")
    phone = store.contact_of(PHONE_APP, "whatsapp:ab12")
    store.portrayed(portrait(cid), [note("Il est responsable réseau.", cid)])
    store.portrayed(Portrait(other, MAIL, "pro", NOW), [note("Il envoie les devis.", other, MAIL, "pro")])
    store.portrayed(Portrait(phone, PHONE_SOURCE, "user_1", NOW), [note("Il joue au foot le jeudi.", phone,
                                                                        PHONE_SOURCE, "user_1")])
    other_note = store.notes(other)[0]
    store.forget_note(other_note.id)  # son empreinte suit aussi la réunion
    store.portrayed(Portrait(other, MAIL, "pro", NOW + 1), [note("Il envoie les devis.", other, MAIL, "pro"),
                                                            note("Il signe les bons.", other, MAIL, "pro")])
    assert store.merge(cid, other)
    assert sorted(texts(store, cid)) == ["Il est responsable réseau.", "Il signe les bons."]
    assert {p.contact for p in store.portraits()} == {cid, phone}
    store.portrayed(Portrait(cid, MAIL, "pro", NOW + 2), [note("Il envoie les devis.", cid, MAIL, "pro")])
    assert texts(store, cid, visible={(MAIL, "pro")}) == []  # oublié avant la réunion : toujours pas réappris
    # un compte retiré : ce qu'il avait appris part avec lui
    store.drop_source(TEAMS, "equipe")
    assert texts(store, cid, visible={(TEAMS, "equipe")}) == []
    assert all(p.account != "equipe" for p in store.portraits())
    # la personne d'un téléphone oubliée : ce que son téléphone avait appris part
    store.forget_now("user_1")
    assert store.notes(phone) == [] and store.portraits(contacts={phone}) == []
    # le contact oublié : ses faits, ses empreintes et ses portraits partent
    store.forget_now(f"contact:{cid}")
    assert store.notes(cid) == [] and store.portraits(contacts={cid}) == []
    with store._session() as s:
        assert s.scalars(select(NoteForgottenRow).where(NoteForgottenRow.contact == cid)).all() == []


def test_forgetting_someone_takes_away_the_facts_of_others_that_name_them(store):
    """Relecture I11 : « Il travaille avec Paul Durand sur le budget » restait sur la fiche de Gilles après l'oubli de
    Paul (sa fiche, ou la personne qui lui parle), et ``contacts_lookup`` le redisait. Un fait qui nomme une personne
    oubliée part avec elle ; un fait qui ne la nomme pas reste ; un nom d'un seul mot ne se reconnaît qu'avec sa
    majuscule."""
    cid = gilles(store)
    store.observe_now([Observation(EMAIL, "paul.durand@gmail.com", MAIL, "pro", "Paul Durand", 1, NOW, NOW),
                       Observation(EMAIL, "max@gmail.com", MAIL, "pro", "Max", 1, NOW, NOW)])
    paul, max_ = store.contact_of(EMAIL, "paul.durand@gmail.com"), store.contact_of(EMAIL, "max@gmail.com")
    store.portrayed(portrait(cid), [note("Il travaille avec Paul Durand sur le budget.", cid),
                                    note("Il prend au max deux jours de congé.", cid),
                                    note("Il attend la validation de Max.", cid),
                                    note("Il suit la migration VPN.", cid)])
    assert store.naming(["Il voit PAUL DURAND demain.", "Il suit le VPN.", "au max", "Avec Max."], but=cid) == [
        True, False, False, True]
    assert store.naming(["Gilles Rousseau écrit."], but=cid) == [False]  # son propre nom n'est pas un tiers
    asyncio.run(store.forget(f"contact:{paul}"))
    assert texts(store, cid) == ["Il prend au max deux jours de congé.", "Il attend la validation de Max.",
                                 "Il suit la migration VPN."]
    store.link(max_, "user_9")
    asyncio.run(store.forget("user_9"))  # la personne qui lui parle, et sa fiche reliée
    assert texts(store, cid) == ["Il prend au max deux jours de congé.", "Il suit la migration VPN."]
