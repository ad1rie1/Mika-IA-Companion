"""L'agenda dans le vrai serveur (ADR 0309, lot 0) : ses ports, ses paramètres journalisés depuis les réglages, l'oubli
du noyau qui atteint sa base.

- le serveur compose le plugin ``agenda`` et ses ports (``agenda`` : la base ; ``agenda_providers`` : le système et
  les comptes des réglages, relus à chaque usage) ; chaque personne a « Mon agenda » sans rien faire ;
- les comptes et les réglages de leurs agendas, enregistrés puis rejournalisés, sont ce que lisent les paramètres du
  plugin (à qui, partagés avec qui, masqués, leur rappel) — jamais un identifiant ;
- l'oubli d'une adresse, par le noyau (``Kernel.forget``, comme la console), atteint la base de l'agenda.
"""

from __future__ import annotations

from mika.adapters.agenda import AgendaAccount, AgendaConfig, AgendaStore, CalendarSetting, Providers
from mika.app.domains.agenda.settings import AgendaSettings
from mika.plugins.agenda import AgendaParams, hers, owner
from mika.ports.agenda import US_PER_S, EventDraft, Participant, Span
from tests.protocol.test_web import world  # noqa: F401 — fixture partagée

HOUR = 3600 * US_PER_S


def test_the_server_composes_the_agenda_and_journals_its_settings(world):  # noqa: F811
    client, live, _ = world
    kernel = live.kernel
    store, providers = kernel.ports["agenda"], kernel.ports["agenda_providers"]
    assert isinstance(store, AgendaStore) and isinstance(providers, Providers)
    assert "agenda" in kernel.registry.faculties
    mon = providers.system.default_calendar("user_1")
    assert mon.name == "Mon agenda" and providers.connection("moi:user_1").owner == "personne:user_1"
    client.portal.call(lambda: live.settings.of(AgendaSettings).save_agenda(AgendaConfig(accounts={
        "feries": AgendaAccount(kind="ical", url="https://secret.example/abc.ics"),
        "moi:user_1": AgendaAccount(kind="systeme", calendars={
            "mon-agenda": CalendarSetting(shares={"personne:user_2": "lire"}, reminder="60")}),
        "lea": AgendaAccount(kind="google", owner="personne:user_2", calendars={"perso": CalendarSetting(hidden=True)}),
    })))
    # les réglages se lisent dans le fil de la boucle (le magasin du serveur), comme le processus les lit
    assert {c.key for c in client.portal.call(providers.connections)} == {"feries", "moi:user_1", "lea"}
    assert client.portal.call(live.reconfigure) == []
    p = kernel.mind.registry.params_of("agenda", kernel.mind.root)
    assert isinstance(p, AgendaParams)
    assert p.shares == {"moi:user_1~mon-agenda": {"personne:user_2": "lire"}}
    assert p.reminders == {"moi:user_1~mon-agenda": "60"} and p.hidden == ("lea~perso",)
    assert owner(p, "lea") == "personne:user_2" and not hers(p, "lea~perso")
    assert "secret.example" not in repr(p.model_dump())


def test_forgetting_an_address_through_the_kernel_reaches_the_agenda(world):  # noqa: F811
    client, live, _ = world
    kernel = live.kernel
    providers = kernel.ports["agenda_providers"]
    me = providers.connection("moi:user_1")
    mon = providers.system.default_calendar("user_1")
    now = kernel.mind.frame().now
    made = client.portal.call(lambda: providers.system.create(me, mon, EventDraft(
        "Déjeuner", Span(now + HOUR, now + 2 * HOUR), participants=(Participant("julien@x.fr", "Julien"),))))
    gone = client.portal.call(lambda: kernel.forget("mail:julien@x.fr"))
    assert gone["agenda"] == 1
    assert kernel.ports["agenda"].find(mon.key, made.uid).participants == ()
