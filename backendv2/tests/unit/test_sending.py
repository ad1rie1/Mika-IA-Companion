"""Les tableaux de ses canaux dans les réglages (ADR 0134) : rangés à part, un canal absent a son minimum vital, un
tableau illisible est écarté ; tes comptes (le courrier, Teams) y lisent ce qu'elle envoie à ta place (ADR 0132)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mika.adapters.store_sql import SqlStore
from mika.app.settings import CANALS_KEY, FAMILIES_KEY, SecretBox, Settings
from mika.vocab.access import ALONE, EVERYONE, OWNER, Table, ToolRule
from mika.vocab.canals import CanalRule, Canals, CanalTable, mail_rule, vital


async def test_canal_tables_are_kept_apart_and_a_missing_one_has_its_vital_minimum(tmp_path):
    store = SqlStore(tmp_path / "mind.db", tmp_path / "views.db", threaded=False)
    await store.open()
    try:
        settings = Settings(store, SecretBox.for_data(tmp_path))
        await settings.open()
        assert settings.canals() == Canals() and settings.access_tables().canals == Canals()
        assert mail_rule(settings.canals(), "perso", "a@b.fr").reply == "accord"  # le minimum vital du courrier
        table = CanalTable(lines=(CanalRule(who=(EVERYONE,), canal=("courrier:perso",), prepare=True, reply="seule"),))
        await settings.save_canal("courrier:perso", table)
        assert settings.canals().tables == {"courrier:perso": table}
        assert mail_rule(settings.canals(), "perso", "a@b.fr").prepare and settings.canals().table("courrier") == vital("courrier")
        await settings.save_canal("courrier:perso", None)  # revenir au minimum vital
        assert settings.canals() == Canals()
        # une famille de ses outils, de même ; un tableau illisible est écarté, jamais une panne
        family = Table[ToolRule](lines=(ToolRule(who=(OWNER,), read=ALONE),), default=ToolRule())
        await settings.save_family("memoire", family)
        assert settings.families() == {"memoire": family} and settings.access_tables().families["memoire"] == family
        await settings._put(FAMILIES_KEY, {"memoire": {"lines": [{"who": ["salon"]}], "default": {}}})
        await settings._put(CANALS_KEY, {"tables": {"web": {"lines": [{"when": ["travail"]}], "default": {}}}})
        settings._rights = settings._read_rights()
        assert settings.families() == {} and settings.canals() == Canals()
        await settings.save_in_hand("memory_search", "hand")
        assert settings.in_hand() == {"memory_search": "hand"}
        with pytest.raises(ValueError):
            await settings.save_in_hand("memory_search", "off")
    finally:
        await store.close()


def test_a_canal_line_keeps_only_its_own_fields():
    with pytest.raises(ValidationError):
        CanalRule(who=("toi",))
    with pytest.raises(ValidationError):
        CanalRule(canal=("sms",))
    with pytest.raises(ValidationError):
        CanalRule(reply="peut-etre")
    assert CanalRule(who=(EVERYONE,), when=("conversation", "initiative")).when == ()
