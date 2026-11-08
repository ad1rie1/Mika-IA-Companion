"""Les feuilles de la console se lisent sans piège : ce qu'elles déclarent sert, et leurs noms disent vrai.

Une classe que plus rien n'emploie laisse croire qu'une mise en page existe encore ; une règle recopiée fait diverger les
pages ; une variable au nom trompeur passe pour une infraction. Les commentaires sont retirés d'abord : ils nomment
justement ce qu'il ne faut pas faire.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import mika

SOURCE = Path(mika.__file__).parent
STATIC = SOURCE / "inspector" / "static"
SHEETS = sorted(STATIC.rglob("*.css"))

# ce qu'un gabarit construit (``grid c{{ b.columns }}``, la légende d'un graphique) : aucune recherche ne le trouve
BUILT_IN_TEMPLATE = {"c2", "s2", "s3"}
# un préfixe suivi d'une construction : « can-where-{{ w.state }} », "document-cols-" + …, f"is-{tone}"
BUILT_PREFIX = re.compile(r"([A-Za-z][\w-]*-)(?=\{\{|[\"']\s*~|[\"']\s*\+|\$\{|%s|\{[a-z_])")


def rules(sheet: Path) -> str:
    return re.sub(r"/\*.*?\*/", "", sheet.read_text(encoding="utf-8"), flags=re.S)


def selector_classes(css: str) -> set[str]:
    found: set[str] = set()
    for selector in re.findall(r"([^{}]+)\{", css):
        if not selector.strip().startswith("@"):
            found.update(re.findall(r"\.([A-Za-z_][\w-]*)", selector))
    return found


@pytest.fixture(scope="module")
def code() -> str:
    return "\n".join(f.read_text(encoding="utf-8", errors="replace") for f in (SOURCE.parent).rglob("*")
                     if f.is_file() and f.suffix in {".py", ".html", ".js"})


@pytest.mark.parametrize("name", ["console.css", "handmade/tools.css", "handmade/base.css",
                                  "handmade/reglages_onglets.css"])
def test_every_class_of_a_cleaned_sheet_is_used(code, name):
    used = set(re.findall(r"[A-Za-z_][\w-]*", code))
    prefixes = tuple(set(BUILT_PREFIX.findall(code)))
    dead = {c for c in selector_classes(rules(STATIC / name)) - used - BUILT_IN_TEMPLATE if not c.startswith(prefixes)}
    assert not dead, f"{name} : plus rien n'emploie {sorted(dead)}"


def test_the_setting_row_is_written_once():
    """Nom et aide à gauche, valeur à droite : une seule écriture, pour chaque page qui a des réglages."""
    written = {s.name: rules(s).count("grid-row: 1 / span 3") for s in SHEETS if "grid-row: 1 / span 3" in rules(s)}
    assert written == {"console.css": 1}
    css = rules(STATIC / "console.css")
    selector = css[:css.index("grid-row: 1 / span 3")].rsplit("}", 1)[-1]
    for container in (".group", ".params-form .param-main", ".mailset-panes .mailset-param"):
        assert container in selector, container


def test_a_setting_row_only_changes_its_value_column_by_the_variable():
    declared = {s.name: re.findall(r"--field-value:\s*([^;]+);", rules(s)) for s in SHEETS}
    assert {k: v for k, v in declared.items() if v} == {"base.css": ["minmax(130px, 200px)"]}


def test_no_variable_is_named_after_a_font_the_console_does_not_use():
    named = {s.name: re.findall(r"--[\w-]*serif[\w-]*", rules(s)) for s in SHEETS}
    assert not {k: v for k, v in named.items() if v}


def test_every_variable_read_is_declared():
    css = "\n".join(rules(s) for s in SHEETS)
    read = set(re.findall(r"var\(\s*(--[\w-]+)\s*\)", css))
    declared = set(re.findall(r"(--[\w-]+)\s*:", css))
    assert not read - declared
