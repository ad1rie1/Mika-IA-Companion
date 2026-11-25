"""Le tableau de droits de chaque agenda (ADR 0309, lot 3a), sur le moteur commun : ses deux portes, sa ligne par défaut,
ce qu'un partage y ajoute, et où il se range.

- **Le tableau par défaut** : son propriétaire, quand elle lui répond, lire, écrire et répondre avec son accord ; d'elle-
  même, lire ; elle seule, au travail, lire et répondre avec accord ; personne d'autre.
- **La première porte** : un agenda sert à son propriétaire (« à toi » : à une de ses propriétaires), en tête-à-tête, et
  à qui il le partage ; jamais dans un salon, jamais une inconnue, jamais masqué ni sous un compte décoché.
- **Un partage ajoute la ligne de la personne**, et il est un plafond : « lire » n'écrit pas ; « lire et préparer »
  écrit sur l'accord du propriétaire, sans répondre ; « s'en servir » comme le propriétaire. Retiré, la ligne part.
- **Rangé dans les réglages**, lu à chaque épisode (``Rights.agendas``) ; partager un agenda au tableau réglé y pose ou
  y retire la ligne de la personne, d'une seule écriture.
- **La page « Droits »** de la console connaît cette sorte de tableau.
"""

from __future__ import annotations

import asyncio

from mika.adapters.agenda import AgendaConfig
from mika.adapters.store_sql import SqlStore
from mika.app.composition import arbitration, faculties
from mika.app.domains.agenda.settings import AgendaSettings
from mika.app.settings import SecretBox, Settings
from mika.kernel.frame import Audience
from mika.kernel.registry import Registry
from mika.plugins.agenda import AgendaParams
from mika.plugins.agenda.rights import (
    OWNED,
    default_lines,
    here,
    reach,
    share_line,
    shared_table,
    table_of,
)
from mika.runtime.state import RUNTIME
from mika.vocab.access import (
    AGREE,
    ALONE,
    CARD,
    CLOSED_AGENDA,
    NO,
    OWNER,
    OWNER_OK,
    SELF,
    AgendaRule,
    Table,
)
from mika.vocab.episodes import Kind
from mika.vocab.privacy import ChannelTrust
from mika.vocab.rights import Rights

ADRIEN = Audience(persons=("user_1",), channel="web", public=False, trust=ChannelTrust.AUTHENTICATED.value,
                  owner=True, person="user_1")
BEA = Audience(persons=("user_2",), channel="web", public=False, trust=ChannelTrust.AUTHENTICATED.value,
               person="user_2")
CHLOE = Audience(persons=("user_3",), channel="web", public=False, trust=ChannelTrust.AUTHENTICATED.value,
                 person="user_3")
STRANGER = Audience(persons=("web-x",), channel="web", public=False, trust=ChannelTrust.ACCOUNT.value)
ROOM = Audience(persons=("user_1", "user_2"), channel="web", room="salon", public=True,
                trust=ChannelTrust.AUTHENTICATED.value, owner=True, person="user_2")
ALONE_AT_WORK = Audience(persons=(), channel="internal", public=False, trust=ChannelTrust.INTERNAL.value, owner=True)

BEA_CAL, ADRIEN_CAL, FAMILY = "moi:user_2~mon-agenda", "moi:user_1~mon-agenda", "famille~principal"


def test_an_agenda_never_set_has_its_owner_lines_then_nobody():
    lines = default_lines("personne:user_2")
    assert [(tuple(x.who), tuple(x.when), x.read, x.write, x.respond) for x in lines] == [
        (("personne:user_2",), ("conversation",), True, AGREE, AGREE),
        (("personne:user_2",), ("initiative",), True, NO, NO),
        ((SELF,), (), True, NO, AGREE),
    ]
    assert lines[0].keep == "perso" and lines[1].keep == lines[2].keep == "rien"
    assert tuple(default_lines("")[0].who) == (OWNER,)  # un compte « à toi » : ses propriétaires
    table = table_of(AgendaParams(), Rights(), BEA_CAL)
    assert table.lines == lines and table.default == CLOSED_AGENDA


def test_it_serves_its_owner_and_whom_it_is_shared_with_never_a_room_or_a_stranger():
    p = AgendaParams(shares={ADRIEN_CAL: {"personne:user_2": "lire"}}, owners={"famille": ""},
                     kinds={"famille": "google"})
    assert reach(p, BEA_CAL, BEA, Kind.REPLY) == OWNED
    assert reach(p, BEA_CAL, ADRIEN, Kind.REPLY) == ""  # le sien n'est pas à une autre, même propriétaire
    assert reach(p, ADRIEN_CAL, ADRIEN, Kind.REPLY) == OWNED  # l'agenda du système d'une opératrice est à son nom
    assert reach(p, ADRIEN_CAL, BEA, Kind.REPLY) == "lire" and reach(p, ADRIEN_CAL, CHLOE, Kind.REPLY) == ""
    assert reach(p, FAMILY, ADRIEN, Kind.REPLY) == OWNED and reach(p, FAMILY, BEA, Kind.REPLY) == ""
    assert reach(p, BEA_CAL, ROOM, Kind.REPLY) == "" and reach(p, BEA_CAL, STRANGER, Kind.REPLY) == ""
    assert reach(p, BEA_CAL, ALONE_AT_WORK, Kind.TASK) == OWNED  # elle seule : son tableau décide
    hidden = AgendaParams(hidden=(BEA_CAL,), accounts_off=("famille",))
    assert reach(hidden, BEA_CAL, BEA, Kind.REPLY) == "" and reach(hidden, FAMILY, ADRIEN, Kind.REPLY) == ""


def test_the_table_decides_what_she_does_when_she_answers_and_when_she_speaks():
    p, rights = AgendaParams(), Rights()
    answering = here(p, rights, BEA_CAL, BEA, Kind.REPLY)
    assert answering is not None and answering.read and answering.write == CARD and answering.respond == CARD
    speaking = here(p, rights, BEA_CAL, BEA, Kind.INITIATIVE)
    assert speaking is not None and speaking.read and speaking.write == NO and speaking.keep == "rien"
    mine = here(p, rights, ADRIEN_CAL, ADRIEN, Kind.REPLY)  # son nom la désigne, même propriétaire
    assert mine is not None and mine.write == CARD
    working = here(p, rights, BEA_CAL, ALONE_AT_WORK, Kind.TASK)
    assert working is not None and working.write == NO and working.respond == CARD
    assert here(p, rights, BEA_CAL, ROOM, Kind.REPLY) is None and here(p, rights, BEA_CAL, STRANGER, Kind.REPLY) is None


def test_a_share_adds_her_line_and_caps_what_she_gets():
    def shared(level: str):
        p = AgendaParams(shares={ADRIEN_CAL: {"personne:user_2": level}})
        return table_of(p, Rights(), ADRIEN_CAL), here(p, Rights(), ADRIEN_CAL, BEA, Kind.REPLY)

    table, read = shared("lire")
    assert table.lines[-1] == share_line("personne:user_2", "lire")
    assert read is not None and read.read and read.write == NO and read.respond == NO and not read.owned
    _table, prepare = shared("preparer")
    assert prepare is not None and prepare.write == OWNER_OK and prepare.owner_decides and prepare.respond == NO
    _table, use = shared("servir")
    assert use is not None and use.write == CARD and use.respond == CARD and not use.owner_decides
    # le partage est un plafond : une ligne réglée plus large ne le dépasse pas
    wide = Table[AgendaRule](lines=(AgendaRule(who=("personne:user_2",), read=True, write=ALONE, respond=AGREE),),
                             default=CLOSED_AGENDA)
    capped = here(AgendaParams(shares={ADRIEN_CAL: {"personne:user_2": "lire"}}), Rights(agendas={ADRIEN_CAL: wide}),
                  ADRIEN_CAL, BEA, Kind.REPLY)
    assert capped is not None and capped.write == NO


def test_a_set_table_takes_and_loses_a_shared_line():
    base = Table[AgendaRule](lines=default_lines("personne:user_1"), default=CLOSED_AGENDA)
    with_bea = shared_table(base, "personne:user_2", "preparer")
    assert with_bea.lines[-1] == share_line("personne:user_2", "preparer") and len(with_bea.lines) == 4
    upgraded = shared_table(with_bea, "personne:user_2", "servir")
    assert len(upgraded.lines) == 4 and upgraded.lines[-1].respond == AGREE
    assert shared_table(upgraded, "personne:user_2", None).lines == base.lines


def test_a_table_is_kept_in_the_settings_and_a_share_rewrites_its_line(tmp_path):
    async def run():
        store = SqlStore(tmp_path / "mind.db", tmp_path / "views.db", threaded=False)
        await store.open()
        try:
            settings = Settings(store, SecretBox.for_data(tmp_path))
            await settings.open()
            mine = Table[AgendaRule](lines=(AgendaRule(who=("personne:user_1",), when=("conversation",), read=True,
                                                       write=ALONE),), default=CLOSED_AGENDA)
            await settings.of(AgendaSettings).save_agenda_table(ADRIEN_CAL, mine)
            await settings.of(AgendaSettings).share_calendar(ADRIEN_CAL, "personne:user_2", "lire")
            shared = settings.access_tables().agendas[ADRIEN_CAL]
            params = settings.of(AgendaSettings).agenda().params()
            reopened = Settings(store, SecretBox.for_data(tmp_path))
            await reopened.open()
            await settings.of(AgendaSettings).share_calendar(ADRIEN_CAL, "personne:user_2", None)
            return shared, params, reopened.agenda_tables(), settings.access_tables().agendas[ADRIEN_CAL], \
                settings.of(AgendaSettings).agenda()
        finally:
            await store.close()

    shared, params, reopened, unshared, cfg = asyncio.run(run())
    assert shared.lines == (*shared.lines[:1], share_line("personne:user_2", "lire"))
    assert params["shares"] == {ADRIEN_CAL: {"personne:user_2": "lire"}}
    assert reopened[ADRIEN_CAL] == shared  # relu à l'ouverture
    assert len(unshared.lines) == 1 and isinstance(cfg, AgendaConfig) and cfg.params()["shares"] == {}


def test_the_rights_page_knows_the_agenda_tables():
    registry = Registry([RUNTIME, *faculties()], arbitration=arbitration())
    assert "agenda.agendas" in {s.key for s in registry.rights}
