"""Les comptes d'agenda dans les réglages (ADR 0309) : à qui, quelle sorte, leurs identifiants scellés, et par agenda
sa couleur, s'il est masqué, le rappel de Mika, ses partages.

- un compte branché est à toi ou à une personne qui a un compte, jamais à elle (pas encore) ; le compte du système
  d'une personne est à elle, existe sans être réglé, et ne se range sous aucun autre nom ;
- le mot de passe et l'adresse d'un abonnement (une adresse secrète ouvre l'agenda) sont scellés, jamais en clair dans
  ``mind.db`` ; des réglages illisibles ne bloquent rien ;
- ce que le plugin en reçoit, journalisé : à qui, la sorte, les partages, les masqués, les rappels choisis — jamais un
  identifiant ni une adresse ; les paramètres du plugin l'acceptent tels quels ;
- les rappels par défaut et ce que Mika peut lire, d'après ces paramètres.
"""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from mika.adapters.agenda import AgendaAccount, AgendaConfig, CalendarSetting
from mika.adapters.store_sql import SqlStore
from mika.app.domains.agenda.settings import AGENDA_KEY, AgendaSettings
from mika.app.settings import SecretBox, Settings
from mika.plugins.agenda import AgendaParams, hers, owner, reminder

SECRET_ICS = "https://calendar.google.com/calendar/ical/adrien%40gmail.com/private-abc123/basic.ics"
PASSWORD = "mot-de-passe-d-application-42"


def _run(tmp_path, scenario):
    async def run():
        store = SqlStore(tmp_path / "mind.db", tmp_path / "views.db", threaded=False)
        await store.open()
        try:
            settings = Settings(store, SecretBox.for_data(tmp_path))
            await settings.open()
            return await scenario(store, settings)
        finally:
            await store.close()

    return asyncio.run(run())


def config() -> AgendaConfig:
    return AgendaConfig(accounts={
        "lumen": AgendaAccount(kind="caldav", label="Lumen (Outlook pro)", url="http://127.0.0.1:1080/users/a/calendar/",
                               username="a.moreau@lumen-conseil.fr", password=PASSWORD,
                               address="A.Moreau@lumen-conseil.fr",
                               calendars={"travail": CalendarSetting(color="bleu", reminder="15")}),
        "feries": AgendaAccount(kind="ical", url=SECRET_ICS, enabled=False),
        "lea-google": AgendaAccount(kind="google", owner="personne:user_2",
                                    calendars={"h4a633282412d516": CalendarSetting(hidden=True)}),
        "moi:user_1": AgendaAccount(kind="systeme", calendars={
            "mon-agenda": CalendarSetting(color="indigo", shares={"personne:user_2": "preparer"})}),
    })


def test_who_an_account_is_for_and_how_a_system_account_is_named():
    with pytest.raises(ValidationError):
        AgendaAccount(kind="google", owner="elle")  # pas de compte d'agenda « à Mika » pour l'instant
    with pytest.raises(ValidationError):
        AgendaAccount(kind="google", owner="Léa")
    with pytest.raises(ValidationError):
        AgendaConfig(accounts={"Perso": AgendaAccount(kind="google")})
    with pytest.raises(ValidationError):  # le système n'est que celui d'une personne
        AgendaConfig(accounts={"serveur": AgendaAccount(kind="systeme")})
    with pytest.raises(ValidationError):
        AgendaConfig(accounts={"moi:user_1": AgendaAccount(kind="google")})
    with pytest.raises(ValidationError):  # le compte du système d'une personne est à elle
        AgendaConfig(accounts={"moi:user_1": AgendaAccount(kind="systeme", owner="personne:user_2")})
    with pytest.raises(ValidationError):
        CalendarSetting(shares={"tous": "lire"})
    cfg = config()
    assert cfg.account("moi:user_7") == AgendaAccount(kind="systeme")  # sans rien régler, il existe
    assert cfg.account("inconnu") is None
    assert cfg.system("personne:user_1").setting("mon-agenda").color == "indigo"


def test_connections_carry_what_joins_an_account():
    found = {c.key: c for c in config().connections()}
    assert found["lumen"].secret == PASSWORD and found["lumen"].address == "a.moreau@lumen-conseil.fr"
    assert found["moi:user_1"].owner == "personne:user_1" and found["lea-google"].owner == "personne:user_2"
    assert not found["feries"].enabled
    assert PASSWORD not in repr(found["lumen"]) and SECRET_ICS not in repr(found["feries"])


def test_what_the_plugin_receives_is_journaled_without_an_identifier():
    given = config().params()
    assert given == {
        "owners": {"feries": "", "lea-google": "personne:user_2", "lumen": ""},
        "kinds": {"feries": "ical", "lea-google": "google", "lumen": "caldav"},
        "shares": {"moi:user_1~mon-agenda": {"personne:user_2": "preparer"}},
        "hidden": ["lea-google~h4a633282412d516"],
        "reminders": {"lumen~travail": "15"},
        "accounts_off": ["feries"],
    }
    text = repr(given)
    assert PASSWORD not in text and "127.0.0.1" not in text and "@" not in text
    p = AgendaParams.model_validate(given)
    assert owner(p, "moi:user_1") == "personne:user_1" and owner(p, "lea-google") == "personne:user_2"
    assert owner(p, "lumen") == ""
    assert not hers(p, "lea-google~h4a633282412d516") and not hers(p, "feries~jours")
    assert hers(p, "lumen~travail") and hers(p, "moi:user_1~mon-agenda")
    assert reminder(p, "lumen~travail", "caldav") == "15" and reminder(p, "lumen~autre", "caldav") == "non"
    assert reminder(p, "moi:user_1~mon-agenda", "systeme") == "30" and reminder(p, "feries~jours", "ical") == "non"
    tuned = p.model_copy(update={"system_reminder": "60", "provider_reminder": "30"})
    assert reminder(tuned, "moi:user_1~sport", "systeme") == "60" and reminder(tuned, "x~y", "google") == "30"
    assert reminder(tuned, "feries~jours", "ical") == "non"


def test_secrets_are_sealed_in_the_settings_and_read_back(tmp_path):
    async def scenario(store, settings):
        await settings.of(AgendaSettings).save_agenda(config())
        raw = [r[0] for r in store.query_mind("SELECT value FROM settings")]
        return raw, settings._get(AGENDA_KEY), settings.of(AgendaSettings).agenda(), settings.of(AgendaSettings).agenda_connections()

    raw, kept, read, connections = _run(tmp_path, scenario)
    assert all(PASSWORD not in r and "private-abc123" not in r for r in raw)
    lumen = kept["accounts"]["lumen"]
    assert "password" not in lumen and lumen["password_sealed"] and "url" not in lumen and lumen["url_sealed"]
    assert read == config()
    assert {c.key for c in connections} == {"lumen", "feries", "lea-google", "moi:user_1"}
    assert not (tmp_path / "mind.db").read_bytes().count(PASSWORD.encode())


def test_unreadable_settings_block_nothing(tmp_path):
    async def scenario(store, settings):
        await settings._put(AGENDA_KEY, {"accounts": {"Pas Valide": {"kind": "google"}}})
        return settings.of(AgendaSettings).agenda(), settings.of(AgendaSettings).agenda_connections()

    read, connections = _run(tmp_path, scenario)
    assert read == AgendaConfig() and connections == []
