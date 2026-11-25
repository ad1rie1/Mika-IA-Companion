"""Les connexions des agendas Google et Microsoft dans les réglages (ADR 0309, lot 2) : à part des comptes, scellées,
et l'application Google du serveur.

- la connexion d'un compte (le jeton de renouvellement) est scellée sous ``agenda_oauth``, avec sa sorte ; elle part
  avec son compte, ou quand il change de sorte ; jamais en clair dans ``mind.db`` ; une autre sorte ne la lit pas ;
- l'application Google du serveur : son identifiant et son secret vérifiés, le secret scellé et jamais rendu, gardé
  quand on ne redonne que l'identifiant ; l'effacer ; ``mika agenda google`` la règle ainsi ;
- un compte Microsoft déclare son application et son annuaire (vérifiés comme ceux d'une boîte), que sa connexion
  reçoit ; ce qu'on colle à la fin d'une connexion Google se lit (l'adresse entière, sa requête, ou le code seul).
"""

from __future__ import annotations

import asyncio
import json
from argparse import Namespace

import pytest
from pydantic import ValidationError

from mika.adapters.agenda import AgendaAccount, AgendaConfig
from mika.adapters.agenda.oauth import pasted
from mika.adapters.mail.oauth import Grant
from mika.adapters.store_sql import SqlStore
from mika.app.domains.agenda.cli import agenda_command
from mika.app.domains.agenda.settings import AGENDA_GOOGLE_KEY, AGENDA_GRANTS_KEY, AgendaSettings
from mika.app.settings import SecretBox, Settings

CLIENT = "123456789012-abcdefgh12345678.apps.googleusercontent.com"
SECRET = "GOCSPX-un-secret-de-client-42"
REFRESH = "1//0g-un-jeton-de-renouvellement"


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


def _raw(store) -> list[str]:
    return [r[0] for r in store.query_mind("SELECT value FROM settings")]


def test_a_connection_is_sealed_apart_and_leaves_with_its_account(tmp_path):
    async def scenario(store, settings):
        await settings.of(AgendaSettings).save_agenda(AgendaConfig(accounts={"google": AgendaAccount(kind="google"),
                                                          "outlook": AgendaAccount(kind="microsoft")}))
        await settings.of(AgendaSettings).save_agenda_grant("google", Grant(REFRESH, CLIENT, ""), "google")
        await settings.of(AgendaSettings).save_agenda_grant("outlook", Grant("M.C5-renouv", "app", "consumers"), "microsoft")
        sealed = _raw(store)
        read = (settings.of(AgendaSettings).agenda_grant("google", "google"), settings.of(AgendaSettings).agenda_grant("google", "microsoft"))
        await settings.of(AgendaSettings).save_agenda(AgendaConfig(accounts={"google": AgendaAccount(kind="caldav"),
                                                          "outlook": AgendaAccount(kind="microsoft")}))
        after_kind = (settings.of(AgendaSettings).agenda_grant("google", "google"), settings.of(AgendaSettings).agenda_grant("outlook", "microsoft"))
        await settings.of(AgendaSettings).save_agenda(AgendaConfig())
        gone = settings._get(AGENDA_GRANTS_KEY)
        await settings.of(AgendaSettings).save_agenda_grant("x", Grant(REFRESH, CLIENT, ""), "google")
        dropped = await settings.of(AgendaSettings).drop_agenda_grant("x"), await settings.of(AgendaSettings).drop_agenda_grant("x")
        return sealed, read, after_kind, gone, dropped

    sealed, read, after_kind, gone, dropped = _run(tmp_path, scenario)
    assert all(REFRESH not in r and "M.C5-renouv" not in r for r in sealed)
    assert read == (Grant(REFRESH, CLIENT, ""), None)  # une autre sorte ne la lit pas
    assert after_kind[0] is None and after_kind[1] == Grant("M.C5-renouv", "app", "consumers")
    assert gone == {} and dropped == (True, False)
    assert not (tmp_path / "mind.db").read_bytes().count(REFRESH.encode())


def test_the_google_application_is_checked_sealed_and_kept_without_its_secret(tmp_path):
    async def scenario(store, settings):
        none = settings.of(AgendaSettings).google_application()
        with pytest.raises(ValueError):
            await settings.of(AgendaSettings).save_google_application("pas-un-client", SECRET)
        with pytest.raises(ValueError):
            await settings.of(AgendaSettings).save_google_application(CLIENT, "")  # pas de secret à garder
        await settings.of(AgendaSettings).save_google_application(CLIENT.upper(), SECRET)
        first = settings.of(AgendaSettings).google_application()
        await settings.of(AgendaSettings).save_google_application(CLIENT, web=True)  # l'identifiant seul : le secret reste
        second = settings.of(AgendaSettings).google_application()
        raw = settings._get(AGENDA_GOOGLE_KEY)
        sealed = _raw(store)
        await settings.of(AgendaSettings).save_google_application("")
        return none, first, second, raw, sealed, settings.of(AgendaSettings).google_application()

    none, first, second, raw, sealed, erased = _run(tmp_path, scenario)
    assert none is None and erased is None
    assert first.client_id == CLIENT and first.secret == SECRET and not first.web
    assert second.secret == SECRET and second.web
    assert "secret" not in raw and raw["secret_sealed"] and all(SECRET not in r for r in sealed)


def test_the_command_line_sets_and_shows_the_google_application_without_its_secret(tmp_path):
    def args(client_id=None, secret=None, web=False, defaut=False):
        return Namespace(client_id=client_id, secret=secret, web=web, defaut=defaut)

    async def scenario(store, settings):
        empty = await agenda_command(settings, args())
        bad = await agenda_command(settings, args("x", SECRET))
        made = await agenda_command(settings, args(CLIENT, SECRET))
        web = await agenda_command(settings, args(CLIENT, web=True))
        erased = await agenda_command(settings, args(defaut=True))
        return empty, bad, made, web, erased

    empty, bad, made, web, erased = _run(tmp_path, scenario)
    assert empty["application"] is None and "mika agenda google" in empty["usage"]
    assert not bad["ok"] and "client OAuth" in bad["error"]
    assert made == {"ok": True, "application": CLIENT, "secret": "…", "type": "bureau",
                    "retour": "http://127.0.0.1:<port>/ (on colle l'adresse)"}
    assert web["type"] == "web" and web["retour"].endswith("/api/moi/agenda/google/retour")
    assert erased["application"] is None
    assert SECRET not in json.dumps([made, web])


def test_a_microsoft_account_declares_its_application_and_directory():
    with pytest.raises(ValidationError):
        AgendaAccount(kind="microsoft", oauth_client_id="pas-un-guid")
    with pytest.raises(ValidationError):
        AgendaAccount(kind="microsoft", oauth_tenant="un annuaire/../")
    account = AgendaAccount(kind="microsoft", oauth_client_id="0A1B2C3D-4E5F-4A6B-8C7D-9E0F1A2B3C4D",
                            oauth_tenant="organizations")
    found = AgendaConfig(accounts={"pro": account, "perso": AgendaAccount(kind="microsoft")}).connections()
    pro, perso = sorted(found, key=lambda c: c.key, reverse=True)
    assert (pro.oauth_client_id, pro.oauth_tenant) == ("0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d", "organizations")
    assert (perso.oauth_client_id, perso.oauth_tenant) == ("", "consumers")
    assert "oauth" not in json.dumps(AgendaConfig(accounts={"pro": account}).params())  # rien de plus au journal


def test_what_is_pasted_at_the_end_of_a_google_connection_reads():
    url = "http://127.0.0.1:53682/?state=abc&code=4%2F0AQ-code&scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fcalendar"
    assert pasted(url) == ("4/0AQ-code", "abc", "")
    assert pasted("?state=abc&code=4/0AQ") == ("4/0AQ", "abc", "")
    assert pasted("http://127.0.0.1:53682/?error=access_denied&state=abc") == ("", "abc", "access_denied")
    assert pasted("  4/0AQ-code-seul  ") == ("4/0AQ-code-seul", "", "")
    assert pasted("deux mots") == ("", "", "") and pasted("") == ("", "", "")
