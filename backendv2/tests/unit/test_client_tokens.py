"""Les jetons de client natif disent ce qu'ils ouvrent et d'où ils viennent (ADR 0062).

- une table ``client_tokens`` d'avant (sans ``client`` ni ``source``) se complète à l'ouverture : ses jetons sont
  des écrans donnés en ligne de commande, et le restent ;
- un jeton ``mobile`` créé ou révoqué prévient ``on_change`` (la joignabilité de la personne en dépend), un écran non ;
- une sorte de client inconnue est refusée ;
- changer le mot de passe ou désactiver le compte révoque les jetons obtenus par mot de passe, et eux seuls.
"""

from __future__ import annotations

import sqlite3

import pytest

from mika.adapters.store_sqlite.store import SqliteStore
from mika.adapters.web.accounts import Accounts

PASSWORD = "un-mot-de-passe-long"


@pytest.fixture
async def store(tmp_path):
    s = SqliteStore(tmp_path / "mind.db", tmp_path / "views.db", threaded=False)
    await s.open()
    yield s
    await s.close()


async def test_une_table_d_avant_se_complete(tmp_path) -> None:
    db = sqlite3.connect(tmp_path / "mind.db")
    db.execute("CREATE TABLE client_tokens(id INTEGER PRIMARY KEY, account INTEGER NOT NULL, "
               "label TEXT NOT NULL DEFAULT '', digest TEXT UNIQUE NOT NULL, created_at INTEGER NOT NULL, "
               "last_used INTEGER, revoked_at INTEGER)")
    db.execute("INSERT INTO client_tokens(account, label, digest, created_at) VALUES(1, 'Unity', 'x', 1)")
    db.commit()
    db.close()
    s = SqliteStore(tmp_path / "mind.db", tmp_path / "views.db", threaded=False)
    await s.open()
    try:
        accounts = Accounts(s)
        await accounts.open()
        await accounts.open()  # deux fois : rien ne casse
        [old] = accounts.tokens()
        assert (old.label, old.client, old.source) == ("Unity", "screen", "cli")
        assert accounts.token_client(old.id) == "screen"
    finally:
        await s.close()


async def test_un_telephone_previent_un_ecran_non(store) -> None:
    accounts = Accounts(store)
    await accounts.open()
    acc = await accounts.create("bea", PASSWORD, operator=False)
    calls: list[int] = []

    async def changed() -> None:
        calls.append(1)

    accounts.on_change = changed
    screen, _ = await accounts.create_token(acc.id, "moteur")
    assert calls == [] and not accounts.has_mobile(acc.id)
    phone, _ = await accounts.create_token(acc.id, "Pixel", client="mobile", source="login")
    assert calls == [1] and accounts.has_mobile(acc.id)
    assert accounts.token_client(phone.id) == "mobile"
    assert await accounts.revoke_token(screen.id)
    assert calls == [1]
    assert await accounts.revoke_token(phone.id)
    assert calls == [1, 1] and not accounts.has_mobile(acc.id)
    with pytest.raises(ValueError):
        await accounts.create_token(acc.id, "?", client="grille-pain")


@pytest.mark.parametrize("change", [{"password": "un-autre-mot-de-passe"}, {"active": False}])
async def test_le_mot_de_passe_emporte_ses_jetons(store, change) -> None:
    accounts = Accounts(store)
    await accounts.open()
    await accounts.create("adrien", PASSWORD, operator=True)  # pas le dernier opérateur
    acc = await accounts.create("bea", PASSWORD, operator=False)
    revoked: list[int] = []

    async def heard(token_id: int) -> None:
        revoked.append(token_id)

    accounts.on_token_revoke.append(heard)
    by_login, _ = await accounts.create_token(acc.id, "Pixel", client="mobile", source="login")
    given, _ = await accounts.create_token(acc.id, "Unity")
    assert await accounts.update(acc.id, **change) is None
    states = {t.id: t.revoked for t in accounts.tokens(acc.id)}
    assert states == {by_login.id: True, given.id: False}
    assert revoked == [by_login.id]  # ses connexions se ferment
    assert not accounts.has_mobile(acc.id)
