"""Une politique : un secret ne va ni au journal, ni à un prompt, ni à une trace (ADR 0311).

Ce que les réglages d'un domaine donnent aux paramètres de ses plugins (``inputs(settings)``, dans son câblage) est
journalisé avec eux (``kernel.params_changed``) : il dit à qui est un compte et s'il est coché, jamais son mot de
passe. Cette garde range, pour chaque domaine qui a des ``inputs``, un réglage qui porte un secret repérable
(``SAMPLES``), puis vérifie que ce secret est scellé là où il est gardé et qu'il ne paraît pas dans ce que ses
``inputs`` rendent. Un domaine qui n'en garde aucun dans ses réglages le dit (``NO_SECRET``, avec sa raison) ; un
domaine neuf qui n'est dans aucune des deux tables fait échouer la garde.
"""

from __future__ import annotations

import asyncio
import importlib
import json
from collections.abc import Awaitable, Callable
from typing import Any

from mika.adapters.agenda import AgendaAccount, AgendaConfig
from mika.adapters.mail import MailAccount, MailConfig
from mika.adapters.store_sql import SqlStore
from mika.app.domains import DOMAINS
from mika.app.domains.agenda.settings import AgendaSettings
from mika.app.domains.mail.settings import MailSettings
from mika.app.settings import SecretBox, Settings

#: ce qu'on cherche ensuite partout où un secret n'a rien à faire
MARK = "s3cr3t-rep3rable"


async def _mail(settings: Settings) -> str:
    """Une boîte et ses deux mots de passe ; rend ce que ses réglages relisent (le secret y est, rouvert)."""
    own = settings.of(MailSettings)
    await own.save_email(MailConfig(accounts={"pro": MailAccount.model_validate({
        "label": "Pro", "address": "pro@example.test", "imap_host": "imap.example.test", "user": "pro@example.test",
        "password": f"{MARK}-imap", "smtp_host": "smtp.example.test", "smtp_user": "pro@example.test",
        "smtp_password": f"{MARK}-smtp"})}))
    return repr(own.email())


async def _agenda(settings: Settings) -> str:
    """Un compte CalDAV et son mot de passe, un abonnement et son adresse (qui ouvre l'agenda à qui la connaît)."""
    own = settings.of(AgendaSettings)
    await own.save_agenda(AgendaConfig(accounts={
        "lumen": AgendaAccount(kind="caldav", url="https://dav.example.test/a/", username="a@example.test",
                               password=f"{MARK}-dav"),
        "feries": AgendaAccount(kind="ical", url=f"https://example.test/{MARK}.ics")}))
    return repr(own.agenda())


#: domaine → de quoi ranger dans ses réglages un secret repérable
SAMPLES: dict[str, Callable[[Settings], Awaitable[str]]] = {"mail": _mail, "agenda": _agenda}
#: domaine → pourquoi ses réglages ne gardent aucun secret
NO_SECRET: dict[str, str] = {
    "teams": "la clé de l'extension d'un compte n'est gardée qu'en empreinte, jamais réversible",
}


def _inputs(wiring: str | None) -> Callable[[Settings], dict[str, dict[str, Any]]] | None:
    found = getattr(importlib.import_module(wiring), "inputs", None) if wiring is not None else None
    return found if callable(found) else None


def feeding() -> dict[str, Callable[[Settings], dict[str, dict[str, Any]]]]:
    """Les domaines dont les réglages donnent quelque chose aux paramètres de leurs plugins, et ce qui le donne."""
    return {d.name: given for d in DOMAINS if (given := _inputs(d.wiring)) is not None}


def test_every_domain_that_feeds_its_plugins_says_its_secrets():
    assert not set(SAMPLES) & set(NO_SECRET), "un domaine garde un secret, ou n'en garde pas"
    assert set(feeding()) == set(SAMPLES) | set(NO_SECRET), \
        "chaque domaine qui a des ``inputs`` range ici un secret repérable (SAMPLES), ou dit pourquoi il n'en garde aucun"
    assert all(why.strip() for why in NO_SECRET.values())


def test_what_settings_give_the_plugins_never_carries_a_secret(tmp_path):
    async def run() -> tuple[dict[str, str], list[str], dict[str, str]]:
        store = SqlStore(tmp_path / "mind.db", tmp_path / "views.db", threaded=False)
        await store.open()
        try:
            settings = Settings(store, SecretBox.for_data(tmp_path))
            await settings.open()
            read = {name: await sample(settings) for name, sample in SAMPLES.items()}
            kept = [row[0] for row in store.query_mind("SELECT value FROM settings")]
            given = {name: json.dumps(inputs(settings), ensure_ascii=False, default=str)
                     for name, inputs in feeding().items()}
            return read, kept, given
        finally:
            await store.close()

    read, kept, given = asyncio.run(run())
    # le secret est bien là pour qui a le droit de le lire : la garde ne cherche pas un secret qui n'existe pas
    assert all(MARK in text for text in read.values()), read
    # scellé là où il est gardé
    assert not [row for row in kept if MARK in row]
    # jamais dans ce qui part aux paramètres journalisés
    leaked = sorted(name for name, text in given.items() if MARK in text)
    assert not leaked, f"les ``inputs`` de {leaked} portent un secret : il irait au journal (ADR 0311)"
