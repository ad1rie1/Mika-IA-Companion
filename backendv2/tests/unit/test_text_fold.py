"""Un seul repli du texte (ADR 0212) et les petites aides du socle.

- ``kernel.text.fold`` : ni casse ni accents, les ligatures dépliées ; ses copies du socle s'y ramènent ;
- ce qui est écrit replié suit : les colonnes de ``mail``, ``teams`` et ``feeds`` passent par une révision, les tables
  du journal se reconstruisent ; une recherche trouve « sœur » pour « soeur », sur ce qui était déjà là aussi ;
- une clé ``name:…`` est écrite au journal : son repli à elle ne bouge pas, comparer deux noms suit le repli commun, et
  la tranche d'``identity``, dont les réducteurs décident par cette comparaison, se reconstruit ;
- ``size_fr`` ; ``why_words`` n'est plus dans le noyau.
- la console suit : ses recherches replient comme le noyau, ses tailles se lisent pareil, ``tabs.number`` relit un
  nombre à la française dans une cellule ou un texte.
"""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from alembic import command

from mika.adapters.workshop import author_identity
from mika.app import schema
from mika.app.genesis import named
from mika.app.handmade.tabs import number
from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import transcript as transcript_c
from mika.faculties.identity.actions import _named_key
from mika.faculties.identity.faculty import IDENTITY, Handle, IdentityState, _claimed, denial_target
from mika.faculties.memory.faculty import MEMORY
from mika.faculties.projects import inspect as projects_inspect
from mika.faculties.transcript import TRANSCRIPT
from mika.inspector.pages import reglages, settings_directory, subjects
from mika.inspector.pages import rights as rights_page
from mika.inspector.pages import system as system_page
from mika.inspector.pages import tools as tools_page
from mika.kernel import rights as kernel_rights
from mika.kernel.inspect import Param, read_params, size_fr
from mika.kernel.prompt import unveiled
from mika.kernel.state import FrozenDict
from mika.kernel.text import fold, unaccented
from mika.plugins.email.console import common as email_console
from mika.plugins.forge import console as forge_console
from mika.plugins.forge import views as forge_views
from mika.ports.forge import AppViewSpec
from mika.ports.paging import fold_text, has_words, words_of
from mika.vocab import access, people, words
from mika.vocab.affect import Emotion, emotion_named
from mika.vocab.affect import fold as emotion_key
from mika.vocab.privacy import ChannelTrust
from tests.fixtures import backend

# ── le repli ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("text", "folded"), [
    ("Sœur", "soeur"), ("SŒUR", "soeur"), ("Lætitia", "laetitia"), ("ÆTHER", "aether"), ("ǽ", "ae"),
    ("Été à la plage", "ete a la plage"), ("Straße", "strasse"), ("ﬁn", "fin"), ("Ⅷ", "viii"), ("", ""),
])
def test_fold_ignores_case_and_accents_and_unfolds_ligatures(text: str, folded: str) -> None:
    assert fold(text) == folded


def test_folding_what_is_folded_changes_nothing() -> None:
    for code in range(sys.maxunicode + 1):
        if not 0xD800 <= code <= 0xDFFF:
            once = fold(chr(code))
            assert fold(once) == once, hex(code)


def test_unaccented_keeps_the_case_and_the_ligatures() -> None:
    assert unaccented("Lætitia ÉTÉ") == "Lætitia ETE"


def test_the_copies_of_the_base_are_this_fold() -> None:
    assert words.fold is fold
    assert fold_text("Sœur") == "soeur"
    assert fold_text(12) == "12"  # une page de données cherche aussi dans ce qui n'est pas un texte


def test_a_search_finds_a_ligature_either_way() -> None:
    assert has_words("Ma sœur arrive", "soeur") and has_words("Ma soeur arrive", "sœur")
    assert words_of("« SŒUR »") == ["soeur"]


def test_a_filter_understands_a_label_typed_without_its_ligature() -> None:
    specs = [Param("genre", "Genre", kind="select", choices=(("fratrie", "Sœur ou frère"),))]
    assert read_params(specs, {"genre": "soeur ou frere"})[0]["genre"] == "fratrie"


def test_a_veiled_name_is_found_without_its_ligature() -> None:
    assert unveiled(["Lætitia"], "Laetitia est passée hier")
    assert unveiled(["Laetitia"], "J'ai vu Lætitia")


def test_an_emotion_written_with_its_ligature_is_understood() -> None:
    assert emotion_key("  très-écœurée ") == "tres_ecoeuree"
    assert emotion_named("écœurée") is Emotion.DISGUSTED


def test_a_git_identity_keeps_the_letters_of_a_ligature() -> None:
    assert "user.email=coeur.de.lion@atelier.local" in author_identity("Cœur de Lion")
    assert "user.email=lea.martin@atelier.local" in author_identity("Léa Martin")


# ── une clé de nom ne bouge pas ───────────────────────────────────────────


@pytest.mark.parametrize("key", [named, _named_key])
def test_a_name_key_written_in_the_journal_does_not_move(key) -> None:
    assert key("Lætitia Müller") == "name:lætitia muller"
    assert key("Hans Straße") == "name:hans straße"


def test_the_fold_of_a_name_is_the_one_its_keys_were_written_with() -> None:
    assert people.fold("  Lætitia ") == "lætitia"


def test_two_names_compare_through_the_common_fold() -> None:
    assert people.same_name("Lætitia", "Laetitia Martin")
    assert people.mentions("Hier, Laetitia m'a écrit", ["Lætitia"])


def _known_as(name: str) -> Handle:
    return Handle("web", ChannelTrust.ACCOUNT, first_seen=1, name=name)


def test_saying_her_name_in_another_spelling_is_not_a_claim() -> None:
    """Le réducteur décide par ``same_name`` : une adresse connue comme « Lætitia » qui se dit « Laetitia » garde son
    nom, sans revendication qui attendrait des preuves."""
    known = IdentityState(handles=FrozenDict({"web_1": _known_as("Lætitia")}))
    said = SimpleNamespace(at=2, data=identity_c.Claimed(handle="web_1", name="Laetitia", target="web_1"))

    after = _claimed(known, said, None).handles["web_1"]

    assert (after.name, after.claim) == ("Lætitia", None)


def test_a_denial_reaches_the_name_she_knows_in_another_spelling() -> None:
    """Le réducteur d'un démenti ancien (``legacy_name``) passe par ``denial_target``."""
    assert denial_target(_known_as("Lætitia"), "Laetitia") == identity_c.DENIES_NAME


def test_the_slice_whose_reducers_compare_names_is_rebuilt() -> None:
    """Un instantané d'avant le repli commun a décidé par l'ancien ``same_name`` : il ne vaut plus un rejeu complet
    du même journal."""
    assert IDENTITY.state_version >= 8


# ── ce qui est écrit replié suit ──────────────────────────────────────────

OLD_FOLD = "ma sœur et l'æther"
NEW_FOLD = "ma soeur et l'aether"
#: la révision d'avant le repli commun, et les colonnes repliées de chaque table
FOLDED = {
    "mail": ("7d0011ebffaa", {"messages": ("fold_subject", "fold_sender", "fold_dest", "fold_body", "fold_who"),
                              "drafts": ("fold_search",), "sent": ("fold_subject", "fold_dest", "fold_body"),
                              "recipients": ("fold_who",)}),
    "teams": ("a3c71e5d9b20", {"conversations": ("title_fold", "id_fold")}),
    "feeds": ("efbc9585b3aa", {"entries": ("feed_fold", "text_fold")}),
}
#: ce qui n'est pas replié garde sa ligature
PLAIN = {"mail": ("messages", "subject"), "teams": ("conversations", "title"), "feeds": ("entries", "title")}


def _old_rows(conn, name: str, tables: dict[str, tuple[str, ...]]) -> None:
    """Une ligne dans chaque table, ses colonnes repliées comme avant."""
    filler = {int: 1, bool: True, float: 1.0, str: "x", bytes: b"x"}
    plain_table, plain_column = PLAIN[name]
    for table, columns in tables.items():
        reflected = sa.inspect(conn).get_columns(table)
        row = {c["name"]: filler[c["type"].python_type] for c in reflected}
        row |= dict.fromkeys(columns, OLD_FOLD)
        if table == plain_table:
            row[plain_column] = "Ma sœur"
        conn.execute(sa.insert(sa.table(table, *(sa.column(c["name"]) for c in reflected))).values(**row))


@pytest.mark.parametrize("name", sorted(FOLDED))
def test_what_a_base_kept_folded_unfolds_its_ligatures(tmp_path, name: str) -> None:
    before, tables = FOLDED[name]
    target = backend.target(tmp_path, name)
    target.ensure()
    engine = target.engine()
    cfg = schema._config(name)
    try:
        with engine.connect() as conn:
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, before)
            conn.commit()
        with engine.begin() as conn:
            _old_rows(conn, name, tables)
        schema.migrate_data(tmp_path, {name: target})
        schema.migrate_data(tmp_path, {name: target})  # deux fois : rien ne change
        with engine.connect() as conn:
            for table, columns in tables.items():
                found = conn.execute(sa.select(*(sa.column(c) for c in columns)).select_from(sa.table(table))).one()
                assert set(found) == {NEW_FOLD}, table
            plain_table, plain_column = PLAIN[name]
            assert conn.execute(sa.select(sa.column(plain_column)).select_from(sa.table(plain_table))).scalar() == "Ma sœur"
    finally:
        engine.dispose()


def test_the_tables_of_the_journal_that_keep_folded_text_are_rebuilt() -> None:
    """Une table tirée du journal se réécrit par sa version : celle d'avant le repli commun gardait « sœur »."""
    assert next(p for p in TRANSCRIPT.projectors if p.name == transcript_c.THREAD_TABLE).version >= 10
    assert next(p for p in MEMORY.projectors if p.name == memory_c.ITEMS_TABLE).version >= 21


# ── une taille ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("octets", "said"), [
    (0, "0 o"), (512, "512 o"), (1023, "1 023 o"), (1024, "1 Ko"), (1536, "1,5 Ko"), (200_000, "195 Ko"),
    (5 * 1024 ** 2, "5 Mo"), (int(12.34 * 1024 ** 2), "12,3 Mo"), (1024 ** 3, "1 Go"), (int(1.5 * 1024 ** 3), "1,5 Go"),
    (2048 * 1024 ** 3, "2 048 Go"),
])
def test_a_size_reads_in_french_in_base_1024(octets: int, said: str) -> None:
    assert size_fr(octets).replace(" ", " ") == said


@pytest.mark.parametrize("nothing", [None, float("nan"), float("inf"), True])
def test_a_size_that_is_not_one_reads_as_a_dash(nothing) -> None:
    assert size_fr(nothing) == "—"


# ── la console : ses recherches, ses tailles, ses nombres ─────────────────


@pytest.mark.parametrize("module", [email_console, forge_views, forge_console, settings_directory, tools_page, subjects])
def test_the_searches_of_the_console_fold_like_the_kernel(module) -> None:
    assert module.fold is fold


def test_a_forged_view_is_found_without_its_ligature() -> None:
    spec = AppViewSpec("cadette", "Ma sœur", "view_cadette")
    assert forge_views.find_view(SimpleNamespace(views=(spec,)), "ma soeur") is spec


def test_a_settings_group_keeps_the_word_its_ligature_is_in() -> None:
    assert reglages._slug("Cœur de métier") == "coeur-de-metier"


@pytest.mark.parametrize(("module", "copy"), [
    (forge_console, "_octets"), (projects_inspect, "_size"), (system_page, "_bytes"), (system_page, "_size"),
])
def test_the_pages_of_the_console_have_no_size_of_their_own(module, copy: str) -> None:
    assert not hasattr(module, copy) and module.size_fr is size_fr


def test_the_size_of_a_forged_base_reads_like_any_other_size() -> None:
    class Port:
        def info(self, name: str) -> SimpleNamespace:
            return SimpleNamespace()

        async def db_schema(self, name: str) -> dict:
            return {"engine": "sqlite", "size": 0, "max": 1024 ** 3, "views": [], "tables": []}

    ctx = SimpleNamespace(subject="essai", ports={"forge": Port()}, param=lambda _name: "")
    facts = dict(asyncio.run(forge_console._tab_base(SimpleNamespace(apps={}), None, ctx))[0].pairs)
    assert facts["taille"] == size_fr(0) and facts["plafond"] == size_fr(1024 ** 3)  # c'était « 1 Ko » et « 1073,7 Mo »


@pytest.mark.parametrize(("said", "read"), [
    ("0,040", 0.04), ("12 personnes", 12.0), ("−0,35", -0.35), ("+1,00", 1.0), ("-2", -2.0),
    ("1\u202f234,5", 1234.5), ("12\u00a0345", 12345.0), ("42\u202f%", 42.0), ("  7 ", 7.0),
    ("—", None), ("", None), (None, None), ("environ 12", None), ("12h", None),
    ({"text": "0,5"}, 0.5), ({"text": "2\u202f048 liens"}, 2048.0), ({}, None),
])
def test_a_french_number_reads_from_a_text_or_a_cell(said, read) -> None:
    assert number(said) == read


# ── ce qui a quitté le socle ──────────────────────────────────────────────


def test_the_kernel_keeps_no_interface_words_about_rights() -> None:
    assert not hasattr(kernel_rights, "why_words")
    assert rights_page.why_words is access.why_words


def test_an_account_handle_is_not_forged_by_a_dead_helper() -> None:
    assert not hasattr(people, "account_handle")
