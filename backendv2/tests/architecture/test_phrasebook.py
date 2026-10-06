"""Une politique : ses phrases vivent dans ``persona/voix.yaml``, et le code ne demande que ce qui y est (ADR 0071).

On lit le code par l'AST (jamais par le texte : un commentaire qui cite une clé ne compte pas) :

- chaque ``phrase("clé", …)``, ``phrases("clé")``, ``family("préfixe")`` du code vise une clé du fichier ;
- une ``phrase`` reçoit exactement les trous de son texte (un trou renommé dans le fichier, ou oublié par le code,
  serait une erreur au premier appel — parfois des jours plus tard) ;
- aucune phrase du fichier n'est orpheline : chacune est demandée quelque part (sinon on la modifierait pour
  rien, sans comprendre pourquoi rien ne change).

Une clé construite à l'exécution (``phrase(f"affect.mood.{nom}")``) compte pour toutes les clés sous son préfixe
littéral (``affect.mood``) ; ses trous ne se vérifient pas statiquement — elle doit passer par ``family`` ou par un
préfixe dont aucune phrase n'a de trou.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from mika.vocab import phrasebook

SRC = Path(__file__).resolve().parents[2] / "src" / "mika"
CALLS = ("phrase", "phrases", "family")


@dataclass(frozen=True)
class Use:
    where: str
    call: str
    key: str  # la clé (ou le préfixe d'une clé construite)
    exact: bool  # une clé écrite en entier (sinon un préfixe)
    fields: frozenset[str] | None  # les trous donnés (None : ``**champs``, on ne sait pas)


def _name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name) and func.id in CALLS:
        return func.id
    if isinstance(func, ast.Attribute) and func.attr in CALLS and isinstance(func.value, ast.Name) \
            and func.value.id in ("phrasebook", "pb"):
        return func.attr
    return None


def uses() -> list[Use]:
    out = []
    for path in sorted(SRC.rglob("*.py")):
        if path.name == "phrasebook.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "phrasebook" not in text:
            continue
        for node in ast.walk(ast.parse(text)):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            call = _name(node.func)
            if call is None:
                continue
            where = f"{path.relative_to(SRC)}:{node.lineno}"
            first = node.args[0]
            if any(kw.arg is None for kw in node.keywords):
                fields = None
            else:
                fields = frozenset(kw.arg for kw in node.keywords if kw.arg)
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                out.append(Use(where, call, first.value, call != "family", fields))
            elif isinstance(first, ast.JoinedStr) and first.values and isinstance(first.values[0], ast.Constant):
                head = str(first.values[0].value)
                out.append(Use(where, call, head.rsplit(".", 1)[0] if "." in head else head, False, None))
            else:
                out.append(Use(where, call, "", False, None))
    return out


def test_the_file_reads():
    phrasebook.reset()
    assert phrasebook.catalog() is not None


def test_every_key_the_code_asks_for_exists_with_its_holes():
    cat = phrasebook.catalog()
    problems = []
    for u in uses():
        if not u.key:
            problems.append(f"{u.where} : {u.call}(…) avec une clé que l'AST ne lit pas — écrire la clé, ou un "
                            "préfixe littéral (f\"famille.{…}\")")
            continue
        if u.exact:
            leaf = cat.get(u.key)
            if leaf is None:
                problems.append(f"{u.where} : « {u.key} » absent du fichier")
            elif u.call == "phrase" and not isinstance(leaf, str):
                problems.append(f"{u.where} : « {u.key} » est une liste (phrases), pas une phrase")
            elif u.call == "phrases" and isinstance(leaf, str):
                problems.append(f"{u.where} : « {u.key} » est une phrase, pas une liste")
            elif u.call == "phrase" and u.fields is not None and phrasebook.holes(leaf) != u.fields:  # type: ignore[arg-type]
                problems.append(f"{u.where} : « {u.key} » a les trous {sorted(phrasebook.holes(leaf))}, le code "  # type: ignore[arg-type]
                                f"donne {sorted(u.fields)}")
        elif not any(k.startswith(u.key + ".") for k in cat):
            problems.append(f"{u.where} : rien sous « {u.key} »")
    assert problems == [], "\n".join(problems)


def test_no_phrase_is_an_orphan():
    used = uses()
    exact = {u.key for u in used if u.exact}
    prefixes = {u.key for u in used if not u.exact and u.key}
    orphans = [k for k in phrasebook.catalog()
               if k not in exact and not any(k.startswith(p + ".") for p in prefixes)]
    assert orphans == [], "phrases que le code ne demande jamais :\n" + "\n".join(sorted(orphans))


def test_a_dynamic_key_never_has_holes():
    """Une clé construite à l'exécution ne se vérifie pas statiquement : ses phrases n'ont pas de trou."""
    cat = phrasebook.catalog()
    holed = sorted({k for u in uses() if not u.exact and u.key and u.call == "phrase"
                    for k, v in cat.items() if k.startswith(u.key + ".") and isinstance(v, str)
                    and phrasebook.holes(v)})
    assert holed == [], holed
