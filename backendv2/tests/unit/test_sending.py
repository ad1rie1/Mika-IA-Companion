"""Ce qu'elle envoie à ta place (ADR 0132) : des règles lues de haut en bas, la première qui correspond décide ;
les réglages d'avant (« préparer d'elle-même », « jamais pour », l'accord d'un courrier, le mode de Teams) traduits
en règles qui font la même chose, gardés quand on réécrit le courrier ou Teams."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mika.adapters.store_sql import SqlStore
from mika.adapters.teams import TeamsConfig
from mika.app.settings import EMAIL_KEY, OVERRIDES_KEY, SENDING_KEY, TEAMS_KEY, SecretBox, Settings
from mika.inspector.pages.sending import NEW_RULE, moved, parse
from mika.vocab.sending import (
    DEFAULT,
    MAIL,
    TEAMS,
    Sending,
    SendRule,
    from_before,
    mail_rule,
    mail_rule_for_all,
    mail_send,
    teams_rule,
)


def test_the_first_rule_that_matches_decides_then_the_default():
    rules = (SendRule(canal=f"{MAIL}:perso", dest="paul@exemple.fr", prepare=False, send="seule"),
             SendRule(canal=MAIL, dest="@Exemple.fr ", prepare=True, send="accord"),
             SendRule(canal=TEAMS, dest="rh", prepare=False, send="brouillon"))
    # une adresse exacte, sur sa boîte seulement
    assert mail_rule(rules, DEFAULT, "perso", "Paul@exemple.fr") is rules[0]
    assert mail_rule(rules, DEFAULT, "pro", "paul@exemple.fr") is rules[1]
    # un @domaine (gardé en minuscules), jamais un domaine qui n'en est qu'un morceau
    assert mail_rule(rules, DEFAULT, "pro", "anne@exemple.fr") is rules[1]
    assert mail_rule(rules, DEFAULT, "pro", "anne@sous.exemple.fr") is DEFAULT
    # une règle de Teams ne vaut pas pour le courrier, et l'inverse
    assert teams_rule(rules, DEFAULT, "19:abc", "Équipe RH", "Marie") is rules[2]
    assert teams_rule(rules, DEFAULT, "19:abc", "Projet", "Marie") is DEFAULT


def test_a_mail_goes_alone_only_if_every_recipient_allows_it():
    rules = (SendRule(canal=MAIL, dest="@maison.fr", send="seule"),)
    assert mail_send(mail_rule_for_all(rules, DEFAULT, "perso", ["a@maison.fr", "b@maison.fr"])) == "seule"
    assert mail_send(mail_rule_for_all(rules, DEFAULT, "perso", ["a@maison.fr", "x@ailleurs.fr"])) == "accord"
    assert mail_rule_for_all(rules, DEFAULT, "perso", []) is DEFAULT


def test_a_mail_has_no_draft_and_a_channel_is_one_she_knows():
    assert SendRule(canal=f"{MAIL}:perso", send="brouillon").send == "accord"
    assert SendRule(canal=TEAMS, send="brouillon").send == "brouillon"
    assert mail_send(SendRule(send="brouillon")) == "accord"  # la règle par défaut, pour un courrier
    for bad in ("sms", "courrier:", "courrier:Perso Pro"):
        with pytest.raises(ValidationError):
            SendRule(canal=bad)


def test_the_settings_of_before_become_rules_that_do_the_same():
    accounts = {"perso": {"autodraft": True, "autodraft_skip": ["@shop.fr", " "]}, "pro": {"autodraft": False}}
    got = from_before(accounts, approval=False, teams={"mode": "validation", "autodraft": True, "skip": ["rh"]})
    assert got.rules == (
        SendRule(canal="courrier:perso", dest="@shop.fr", prepare=False, send="seule"),
        SendRule(canal="courrier:perso", prepare=True, send="seule"),
        SendRule(canal="courrier:pro", prepare=False, send="seule"),
        SendRule(canal=TEAMS, dest="rh", prepare=False, send="accord"),
        SendRule(canal=TEAMS, prepare=True, send="accord"))
    assert got.default == DEFAULT
    # rien de réglé : ce que faisaient les défauts d'alors (Teams préparait, en brouillon ; le courrier attendait)
    assert from_before({}, approval=True, teams=None).rules == (SendRule(canal=TEAMS, prepare=True, send="brouillon"),)
    # une boîte qui ne prépare rien et attend l'accord : la règle par défaut suffit
    assert from_before({"perso": {}}, approval=True, teams={"autodraft": False, "mode": "validation"}).rules == ()


def test_a_table_sent_from_the_page_is_read_in_its_order_and_moved():
    data = {"canal.2": TEAMS, "dest.2": "RH", "send.2": "seule", "canal.1": MAIL, "prepare.1": "on",
            "send.1": "brouillon", "defaut_send": "seule"}
    rules, default = parse(data)
    assert rules == [SendRule(canal=MAIL, prepare=True, send="accord"), SendRule(canal=TEAMS, dest="rh", send="seule")]
    assert default == SendRule(send="seule") and not default.prepare
    assert moved(rules, "monter:2")[0] == rules[::-1]
    assert moved(rules, "descendre:1")[0] == rules[::-1]
    assert moved(rules, "retirer:1")[0] == rules[1:]
    assert moved(rules, "ajouter")[0] == [*rules, NEW_RULE]
    assert moved(rules, "monter:1")[0] == rules  # rien au-dessus : rien ne bouge
    with pytest.raises(ValueError, match="Règle 1"):
        parse({"canal.1": "sms"})
    with pytest.raises(ValueError, match="choisis un canal"):
        parse({"canal.1": ""})


async def test_the_old_settings_are_kept_when_mail_or_teams_is_rewritten(tmp_path):
    store = SqlStore(tmp_path / "mind.db", tmp_path / "views.db", threaded=False)
    await store.open()
    try:
        settings = Settings(store, SecretBox.for_data(tmp_path))
        await settings.open()
        await settings._put(EMAIL_KEY, {"accounts": {"perso": {"autodraft": True, "autodraft_skip": ["@shop.fr"]}}})
        await settings._put(TEAMS_KEY, {"enabled": True, "mode": "autonome", "autodraft": False})
        await settings._put(OVERRIDES_KEY, {"email": {"send_needs_approval": False, "max_per_day": 3}})
        before = settings.sending()
        assert before.rules[1] == SendRule(canal="courrier:perso", prepare=True, send="seule")
        assert before.rules[-1] == SendRule(canal=TEAMS, prepare=False, send="seule")
        # réécrire Teams efface ses anciens champs : les règles sont d'abord écrites sous leur forme neuve
        await settings.save_teams(TeamsConfig(enabled=True))
        assert settings._get(SENDING_KEY) == before.model_dump(mode="json") and settings.sending() == before
        # enregistrées, elles retirent la surcharge qui les disait ; les autres surcharges restent
        await settings.save_sending(Sending(rules=before.rules[:1]))
        assert settings.overrides() == {"email": {"max_per_day": 3}}
        assert settings.sending().rules == before.rules[:1]
        # illisibles : la règle par défaut seule, jamais une panne
        await settings._put(SENDING_KEY, {"rules": [{"canal": "sms"}]})
        assert settings.sending() == Sending()
    finally:
        await store.close()
