"""Son recueil de phrases : tout ce qui la façonne, lu dans un seul fichier, ``persona/voix.yaml`` (ADR 0071).

Ce que le modèle lit quand elle parle, se souvient, rêve ou se raconte — ses consignes, les sections de son prompt,
les briefs de ses épisodes, la description de ses outils, les mots de ses humeurs — et ce qu'elle produit sans
modèle (sa journée « à raconter », les repères de temps, ses bonjours de secours) : rien de tout cela n'est écrit
dans le code. Le code demande une phrase par sa **clé** ; le fichier la donne. On change sa grammaire, son ton,
une règle de vie en éditant ce fichier, sans toucher au code.

- ``phrase("self.nature.embodied")`` : une phrase ; ``phrase("dream.system", tone="doux, lumineux")`` : une phrase
  à **trous** (``{tone}``), remplis par le code. Les trous sont vérifiés strictement : le code passe exactement
  les trous du texte, ni plus ni moins — un trou renommé dans le fichier, ou oublié par le code, lève une
  ``VoiceError`` qui dit lequel (et les tests d'architecture le voient avant).
- ``phrases("expression.cues")`` : une liste de phrases (une entrée par ligne du fichier).
- ``family("affect.mood")`` : toutes les phrases sous une clé, par leur dernier nom (``{"happy": "contente", …}``) —
  pour ce que le code choisit à l'exécution (une émotion, une raison, un ton).

Le fichier se lit une fois, au premier besoin. Il est cherché à côté de la persona (``backendv2/persona/
voix.yaml``), ou là où pointe ``MIKA_VOIX`` (un jumeau peut avoir sa propre voix). Un fichier illisible, une clé
absente, une feuille qui n'est ni un texte ni une liste de textes : refusés avec le fichier, la clé et la cause, en
français. Changer le fichier demande un redémarrage (rien ne se recharge à chaud : ce qu'elle a dit sous une voix
reste dit sous elle).
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType

import yaml

#: où il est cherché par défaut : à côté de la persona (``src/mika/vocab/phrasebook.py`` → ``backendv2/persona``)
DEFAULT_FILE = Path(__file__).resolve().parents[3] / "persona" / "voix.yaml"
#: une autre voix (un autre fichier) : ``MIKA_VOIX=/chemin/voix.yaml``
ENV = "MIKA_VOIX"
#: un trou dans une phrase : ``{name}``, ``{tone}`` (minuscules, chiffres, soulignés)
HOLE = re.compile(r"\{([a-z_][a-z0-9_]*)\}")
_KEY = re.compile(r"^[a-z0-9_]+$")

Leaf = str | tuple[str, ...]


class VoiceError(RuntimeError):
    """Le fichier de sa voix ne dit pas ce que le code lui demande (ou ne se lit pas)."""


def voice_file() -> Path:
    env = os.environ.get(ENV, "").strip()
    return Path(env).expanduser() if env else DEFAULT_FILE


def _flatten(node: object, prefix: str, out: dict[str, Leaf], source: Path) -> None:
    if isinstance(node, str):
        out[prefix] = node
        return
    if isinstance(node, list):
        if not all(isinstance(x, str) for x in node):
            raise VoiceError(f"{source} : « {prefix} » est une liste qui ne contient pas que des phrases")
        out[prefix] = tuple(node)
        return
    if not isinstance(node, dict):
        raise VoiceError(f"{source} : « {prefix or '(racine)'} » n'est ni une phrase, ni une liste de phrases, ni "
                         f"un groupe de phrases ({type(node).__name__})")
    for key, value in node.items():
        if not isinstance(key, str) or not _KEY.match(key):
            raise VoiceError(f"{source} : clé « {key} » sous « {prefix or '(racine)'} » — des minuscules, chiffres "
                             "et soulignés seulement")
        _flatten(value, f"{prefix}.{key}" if prefix else key, out, source)


def _read(path: Path) -> dict[str, Leaf]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise VoiceError(f"le fichier de sa voix est introuvable : {path} (voir ADR 0071 ; {ENV} pour un autre)") \
            from exc
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f", ligne {mark.line + 1}, colonne {mark.column + 1}" if mark is not None else ""
        raise VoiceError(f"{path}{where} : YAML illisible — {getattr(exc, 'problem', exc)}") from exc
    out: dict[str, Leaf] = {}
    _flatten(raw or {}, "", out, path)
    return out


@lru_cache(maxsize=4)
def _catalog(path: Path) -> Mapping[str, Leaf]:
    out = _read(path)
    # MIGRATION (ADR 0071) : pendant qu'on y range les phrases, des fragments ``voix.d/*.yaml`` complètent le
    # fichier ; ils y sont fusionnés à la fin, et ce dossier disparaît
    fragments = path.with_suffix(".d")
    for extra in sorted(fragments.glob("*.yaml")) if fragments.is_dir() else ():
        more = _read(extra)
        twice = sorted(set(more) & set(out))
        if twice:
            raise VoiceError(f"{extra} : {', '.join(twice[:5])} déjà dit ailleurs")
        out.update(more)
    return MappingProxyType(out)


def catalog() -> Mapping[str, Leaf]:
    """Toutes ses phrases, par clé pointée."""
    return _catalog(voice_file())


def reset() -> None:
    """Oublier le fichier lu (pour les tests, ou après avoir changé ``MIKA_VOIX``)."""
    _catalog.cache_clear()


def _leaf(key: str) -> Leaf:
    found = catalog().get(key)
    if found is None:
        raise VoiceError(f"{voice_file()} : la phrase « {key} » n'existe pas (ajoutée au code sans l'être au "
                         "fichier, ou renommée dans le fichier)")
    return found


def holes(text: str) -> frozenset[str]:
    """Les trous d'une phrase."""
    return frozenset(HOLE.findall(text))


def fill(key: str, text: str, fields: Mapping[str, object]) -> str:
    """Remplir les trous de ``text`` : exactement ceux qu'il a, ni plus ni moins."""
    wanted = holes(text)
    given = frozenset(fields)
    if wanted != given:
        missing = ", ".join(sorted(wanted - given)) or "—"
        extra = ", ".join(sorted(given - wanted)) or "—"
        raise VoiceError(f"{voice_file()} : la phrase « {key} » a les trous {sorted(wanted)} ; le code donne "
                         f"{sorted(given)} (manquants : {missing} ; en trop : {extra})")
    for name, value in fields.items():
        text = text.replace("{" + name + "}", str(value))
    return text


def phrase(key: str, /, **fields: object) -> str:
    """Une phrase, ses trous remplis."""
    leaf = _leaf(key)
    if not isinstance(leaf, str):
        raise VoiceError(f"{voice_file()} : « {key} » est une liste de phrases (``phrases``), pas une phrase")
    return fill(key, leaf, fields)


def phrases(key: str, /) -> tuple[str, ...]:
    """Une liste de phrases (sans trous : ce sont des exemples, des tournures, des mots)."""
    leaf = _leaf(key)
    if isinstance(leaf, str):
        raise VoiceError(f"{voice_file()} : « {key} » est une phrase (``phrase``), pas une liste")
    return leaf


def family(prefix: str, /) -> Mapping[str, str]:
    """Les phrases directement sous ``prefix``, par leur dernier nom (pour ce que le code choisit à l'exécution)."""
    start = prefix + "."
    found = {k[len(start):]: v for k, v in catalog().items() if k.startswith(start) and "." not in k[len(start):]}
    if not found:
        raise VoiceError(f"{voice_file()} : aucune phrase sous « {prefix} »")
    bad = [k for k, v in found.items() if not isinstance(v, str)]
    if bad:
        raise VoiceError(f"{voice_file()} : sous « {prefix} », {', '.join(bad)} ne sont pas des phrases")
    return MappingProxyType(found)  # type: ignore[arg-type]


def main() -> int:
    """``python -m mika.vocab.phrasebook`` : le fichier se lit-il ? (les clés du code : ``tests/architecture``)."""
    try:
        found = catalog()
    except VoiceError as exc:
        print(f"ERREUR : {exc}")
        return 1
    lists = sum(1 for v in found.values() if isinstance(v, tuple))
    with_holes = sum(1 for v in found.values() if isinstance(v, str) and holes(v))
    print(f"{voice_file()} : {len(found)} entrées ({len(found) - lists} phrases dont {with_holes} à trous, "
          f"{lists} listes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
