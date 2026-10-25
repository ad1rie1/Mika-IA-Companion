"""Ce qu'elle envoie à ta place (ADR 0132) : des règles lues de haut en bas, la première qui correspond décide ;
rangées à part dans les réglages, illisibles elles laissent la règle par défaut seule."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mika.adapters.store_sql import SqlStore
from mika.adapters.teams import TeamsConfig
from mika.app.settings import SENDING_KEY, SecretBox, Settings
from mika.inspector.pages.sending import NEW_RULE, moved, parse
from mika.vocab.sending import (
    DEFAULT,
    MAIL,
    TEAMS,
    Sending,
    SendRule,
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


async def test_its_rules_are_kept_apart_and_unreadable_ones_give_the_default(tmp_path):
    """Rien d'enregistré : la règle par défaut seule ; enregistrées, réécrire Teams n'y touche pas ; illisibles, la
    règle par défaut seule — jamais une panne. Les champs d'avant l'ADR 0132 ne se lisent plus (2026-10-25 : les
    réglages repartent de zéro)."""
    store = SqlStore(tmp_path / "mind.db", tmp_path / "views.db", threaded=False)
    await store.open()
    try:
        settings = Settings(store, SecretBox.for_data(tmp_path))
        await settings.open()
        assert settings.sending() == Sending()
        rules = Sending(rules=(SendRule(canal="courrier:perso", prepare=True, send="seule"),))
        await settings.save_sending(rules)
        await settings.save_teams(TeamsConfig(enabled=True))
        assert settings.sending() == rules
        await settings._put(SENDING_KEY, {"rules": [{"canal": "sms"}]})
        assert settings.sending() == Sending()
        with pytest.raises(ValidationError):
            TeamsConfig.model_validate({"enabled": True, "mode": "autonome"})
    finally:
        await store.close()
