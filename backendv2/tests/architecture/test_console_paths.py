"""Facultés et plugins ne nomment pas les adresses de la console (ADR 0216) : ils disent ce qu'ils visent (``Ref``), la
console sait où cela vit (``render.href``). Renommer une page ne fait plus éditer une vingtaine de fichiers, et une
adresse écrite à la main ne se vérifie pas : l'une d'elles était déjà morte (audit du 2026-11-05, K11-01, K11-03)."""

from __future__ import annotations

import ast
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from mika.inspector import render
from mika.kernel.inspect import Ref
from mika.vocab.phrasebook import catalog, phrase

SRC = Path(render.__file__).resolve().parents[1]
ROOTS = ("faculties", "plugins")
#: la seule phrase qui porte une adresse : un prompt ne passe pas par ``render.href``
SAID_WITH_ITS_ADDRESS = "projects.share.app_link"

Finding = tuple[int, str]


def written_addresses(tree: ast.Module) -> Iterator[Finding]:
    """Les chaînes qui commencent par l'adresse de la console (le début d'une f-string est une chaîne comme une autre)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith(render.PREFIX):
            yield node.lineno, node.value


def local_links(tree: ast.Module) -> Iterator[Finding]:
    """Les ``Ref("local", …)`` : un lien qui porte une adresse déjà construite, ce que seule la console fait."""
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Ref" and node.args
                and isinstance(node.args[0], ast.Constant) and node.args[0].value == "local"):
            yield node.lineno, 'Ref("local", …)'


def _everywhere(find: Callable[[ast.Module], Iterator[Finding]]) -> list[str]:
    return [f"{path.relative_to(SRC)}:{line} : {what}"
            for root in ROOTS for path in sorted((SRC / root).rglob("*.py"))
            for line, what in find(ast.parse(path.read_text(encoding="utf-8")))]


@pytest.mark.parametrize("find", [written_addresses, local_links], ids=["adresses", "liens locaux"])
def test_no_faculty_or_plugin_writes_an_address_of_the_console(find):
    assert not _everywhere(find)


@pytest.mark.parametrize(("source", "find"), [
    ('x = "/inspecteur/reglages/teams"', written_addresses),
    ('x = f"/inspecteur/{section}/parametres"', written_addresses),
    ('Ref("local", PAGE, "Retour")', local_links),
], ids=["chaîne", "f-string", "lien local"])
def test_the_guard_sees_what_it_forbids(source, find):
    assert list(find(ast.parse(source)))


def test_a_comment_or_a_sentence_about_the_console_is_not_an_address():
    source = '# voir /inspecteur/reglages\nx = "pour l\'inspecteur : /inspecteur/reglages"\n'
    assert not list(written_addresses(ast.parse(source)))


def test_the_only_address_she_reads_is_the_one_the_console_writes():
    """Le lien des vues d'une app fait partie d'une phrase qu'elle lit : aucun rendu n'y passe. Elle reste dans sa voix,
    et ce test la confronte à l'adresse que la console écrit."""
    said = phrase(SAID_WITH_ITS_ADDRESS, title="Cours", app="cours")
    assert render.href(Ref.subject("app", "cours", "", "vues")) in said


def test_her_voice_carries_no_other_address():
    """Sinon, la voix deviendrait le détour pour écrire une adresse que la garde refuse dans le code."""
    assert [key for key, text in catalog().items() if render.PREFIX + "/" in str(text)] == [SAID_WITH_ITS_ADDRESS]
