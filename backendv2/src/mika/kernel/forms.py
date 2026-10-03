"""Formulaires de configuration décrits par les modèles pydantic.

La console ne dessine pas chaque page à la main : elle lit un modèle
(paramètres d'une faculté, réglages d'un adaptateur, persona, tempérament),
en tire la liste de ses champs (``describe``), en rend les valeurs
(``flatten``, ``as_text``), relit une soumission (``parse``), la borne
(``within``) puis la fait valider par le modèle lui-même (``validate``).

Conventions (reprises de la v1) :

- chaque champ affiché émet un ``_champs`` caché portant son chemin : une case
  décochée (absente de la soumission, mais affichée) vaut ``False``, et un
  champ qui n'était pas à l'écran n'est pas touché ;
- un secret ne redescend jamais : le champ part vide, vide veut dire
  « inchangé », et ``_effacer`` est la seule façon de le vider ;
- un nombre ne s'édite que borné : sans bornes déclarées il est en lecture
  seule, pour qu'une valeur absurde ne puisse pas se taper ;
- les bornes de la console (``Knob``) ne valident rien au décodage : elles ne
  s'appliquent qu'à l'écriture (``within``). Poser un ``Knob`` sur un champ ne
  change ni la validation ni le JSON — le rejeu relit l'ancien journal à
  l'identique.

Module du noyau : stdlib et pydantic seulement.
"""

from __future__ import annotations

import enum
import json
import math
import re
import types
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Annotated, Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel, ValidationError
from pydantic.fields import FieldInfo

#: Champ caché : les chemins réellement rendus dans le formulaire.
RENDERED = "_champs"
#: Champ caché : les secrets à vider (un secret laissé vide reste inchangé).
CLEARED = "_effacer"

KINDS = frozenset({
    "text", "textarea", "int", "float", "slider", "bool", "select", "lines", "duration", "secret",
    "subject", "yaml", "group", "records", "mapping", "hidden", "datetime", "file",
})
#: ``datetime`` : une date et une heure (un calendrier dans le navigateur) ; ``suggest`` : un texte libre
#: accompagné de suggestions (``choices``), jamais limité à elles
WIDGETS = frozenset({"", "slider", "textarea", "lines", "yaml", "password", "select", "duration", "subject",
                     "hidden", "datetime", "suggest", "file"})
#: ``file`` : un fichier envoyé (champ ``Upload | None``) ; la console le lit borné à ``UPLOAD_MAX`` octets
UPLOAD_MAX = 5 * 1024 * 1024
_UNSAFE_NAME = re.compile(r"[\\/\x00-\x1f\x7f]")

# mêmes unités que kernel.clock (le noyau n'importe rien de mika)
_US, _MS, _SECOND = 1, 1_000, 1_000_000
_MINUTE, _HOUR, _DAY = 60 * _SECOND, 3_600 * _SECOND, 86_400 * _SECOND

#: Unités de temps d'un champ → microsecondes. Une durée sans unité est en µs.
UNIT_US: Mapping[str, int] = MappingProxyType({"us": _US, "ms": _MS, "s": _SECOND, "min": _MINUTE, "h": _HOUR})
# suffixe du nom → unité devinée (les unités de temps sont retirées du libellé)
_SUFFIXES = (("_us", "us"), ("_ms", "ms"), ("_s", "s"), ("_min", "min"), ("_h", "h"), ("_tokens", "tokens"))
# un texte dont le nom dit « secret » ne s'affiche jamais, Knob ou non
_SECRET_NAMES = ("password", "api_key", "token", "secret", "passphrase")
_NUMERIC = frozenset({"int", "float", "slider", "duration"})
#: un libellé qui dit déjà son unité, entre parenthèses à la fin (« Contexte (jetons) »)
_LABEL_UNIT = re.compile(r"\([^()]+\)\s*$")
UNBOUNDED_NOTE = "(bornes non déclarées : lecture seule)"

Only = tuple[tuple[str, tuple[str, ...]], ...]
Pairs = tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class Knob:
    """Ce que la console sait d'un champ. Se pose dans ``Annotated[T, Knob(...)]`` :
    pydantic le garde dans ``FieldInfo.metadata`` et ne l'applique jamais."""

    label: str = ""
    help: str = ""
    group: str = ""
    advanced: bool = True
    lo: float | None = None
    hi: float | None = None
    step: float | None = None
    #: "us" | "ms" | "s" | "min" | "h" | "%" | "tokens" | "" ; deviné du suffixe du nom quand vide — jamais une
    #: durée pour un débit (``…_per_h``, ``…_per_min``, ``…_per_s`` : tant par heure)
    unit: str = ""
    widget: str = ""
    choices: Pairs = ()
    #: choix chargés à la demande par un chargeur nommé (ex. « models »)
    loader: str = ""
    #: widget « subject » : clé d'un genre d'objet
    subject: str = ""
    #: champ dict[str, X] : les clés attendues (valeur, libellé)
    keys: Pairs = ()
    #: valeurs d'un dict : choisies parmi les clés d'un autre champ dict (chemin relatif au modèle)
    choices_from: str = ""
    #: affiché seulement si le champ ``chemin`` (relatif au modèle) vaut l'une de ces valeurs
    only: Only = ()
    #: affiché si **l'une** de ces conditions tient (chacune comme ``only``) — « ou » ; s'ajoute à ``only``
    only_any: tuple[Only, ...] = ()
    secret: bool = False
    readonly: bool = False
    order: int = 100

    def __post_init__(self) -> None:
        if self.widget not in WIDGETS:
            raise ValueError(f"widget inconnu : « {self.widget} » (attendu : {', '.join(sorted(WIDGETS - {''}))})")


class Upload(BaseModel):
    """Un fichier envoyé par un formulaire : son nom (assaini, sans dossier) et ses octets.
    ``too_big`` : il dépassait ``UPLOAD_MAX`` (ses octets ne sont pas gardés)."""

    model_config = {"frozen": True}

    name: str
    data: bytes = b""
    too_big: bool = False


def safe_name(name: str) -> str:
    """Un nom de fichier sans dossier ni caractère de contrôle, borné (vide s'il ne reste rien)."""
    base = _UNSAFE_NAME.sub("_", name.replace("\\", "/").rsplit("/", 1)[-1]).strip().strip(".")
    return base[:120]


@dataclass(frozen=True, slots=True)
class FormField:
    """Un champ à rendre. ``path`` est pointé pour les modèles imbriqués
    (« sleep.tau_wake_h ») ; ``item`` porte les champs d'un enregistrement
    (``records``) ou le seul champ d'une valeur (``mapping``)."""

    path: str
    label: str
    help: str
    group: str
    kind: str
    advanced: bool
    secret: bool
    readonly: bool
    required: bool
    default: Any
    lo: float | None
    hi: float | None
    step: float | None
    unit: str
    choices: Pairs
    loader: str
    subject: str
    only: Only
    order: int
    item: tuple[FormField, ...] = ()
    keys: Pairs = ()
    choices_from: str = ""
    #: ``T | None`` : un champ laissé vide vaut ``None``
    nullable: bool = False
    #: d'autres conditions d'affichage, dont une seule doit tenir (``Knob.only_any``)
    only_any: tuple[Only, ...] = ()


# ── Décrire ───────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class _Scope:
    """Ce qu'un modèle imbriqué hérite de son champ parent."""

    prefix: str = ""
    group: str = ""
    advanced: bool = False
    readonly: bool = False
    only: Only = ()
    defaults: BaseModel | None = None  # la valeur par défaut du parent, qui prime sur celles du modèle


def describe(model: type[BaseModel]) -> tuple[FormField, ...]:
    """Les champs du modèle, dans l'ordre (``Knob.order`` puis déclaration) ;
    un modèle imbriqué donne un champ ``group`` suivi de ses champs pointés."""
    return tuple(_describe(model, _Scope()))


def _describe(model: type[BaseModel], scope: _Scope) -> list[FormField]:
    entries = []
    for index, (name, info) in enumerate(model.model_fields.items()):
        entries.append((_knob_of(info.metadata).order, index, name, info))
    out: list[FormField] = []
    for _, _, name, info in sorted(entries, key=lambda e: (e[0], e[1])):
        out.extend(_describe_field(name, info, scope))
    return out


def _describe_field(name: str, info: FieldInfo, scope: _Scope) -> list[FormField]:
    annotation, extra, nullable = _unwrap(info.annotation)
    metadata = _expand((*info.metadata, *extra))
    knob = _knob_of(metadata)
    path = scope.prefix + name
    label = knob.label or _humanize(name)
    default = _default_of(name, info, scope)
    common: dict[str, Any] = {
        "path": path, "label": label, "help": knob.help or info.description or "",
        "group": knob.group or scope.group, "advanced": scope.advanced or knob.advanced,
        "readonly": scope.readonly or knob.readonly, "required": info.is_required(),
        "default": _plain(default), "order": knob.order, "loader": knob.loader,
        "subject": knob.subject, "only": scope.only + _rebase_only(knob.only, scope.prefix),
        "keys": knob.keys, "choices_from": scope.prefix + knob.choices_from if knob.choices_from else "",
        "nullable": nullable,
        "only_any": tuple(_rebase_only(alt, scope.prefix) for alt in knob.only_any),
    }
    if knob.widget == "file":  # un modèle (``Upload``), mais un seul contrôle : pas un groupe
        return [_make(kind="file", **common)]
    if _groups(annotation, knob, nullable):
        marker = _make(kind="group", **{**common, "default": None, "only_any": ()})
        child = _Scope(prefix=path + ".", group=label, advanced=marker.advanced, readonly=marker.readonly,
                       only=marker.only, defaults=default if isinstance(default, BaseModel) else None)
        return [marker, *_describe(annotation, child)]
    record = _record_model(annotation)
    if record is not None and knob.widget != "yaml":
        return [_make(kind="records", item=tuple(_describe(record, _Scope())), **common)]
    value = _mapping_value(annotation)
    if value is not None and knob.widget != "yaml":
        item = _value_item(value)
        if item.readonly:
            return [_make(kind="mapping", item=(item,), **{**common, "readonly": True,
                                                            "help": _note(common["help"])})]
        return [_make(kind="mapping", item=(item,), **common)]
    return [_scalar(name, annotation, knob, metadata, common)]


def _scalar(name: str, annotation: Any, knob: Knob, metadata: Sequence[Any], common: dict[str, Any]) -> FormField:
    """Un champ feuille : texte, nombre, case, choix, lignes — ou YAML à défaut."""
    choices = knob.choices
    if knob.widget == "yaml":
        return _make(kind="yaml", **common)
    if annotation is bool:
        return _make(kind="bool", **common)
    if get_origin(annotation) is Literal:
        values = tuple((str(v), str(v)) for v in get_args(annotation))
        return _make(kind="select", choices=choices or values, **common)
    if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
        values = tuple((str(m.value), _enum_label(m)) for m in annotation)
        return _make(kind="select", choices=choices or values, **common)
    if annotation in (int, float):
        return _number(name, annotation, knob, metadata, common)
    if annotation is str:
        if knob.widget == "hidden":
            # posé par la page (le mail auquel on répond), jamais tapé : reposté tel quel
            return _make(kind="hidden", **common)
        if knob.secret or knob.widget == "password" or (not knob.widget and _secret_name(name)):
            return _make(kind="secret", secret=True, **common)
        if knob.widget == "datetime":
            return _make(kind="datetime", **common)
        if knob.widget == "suggest":  # un texte libre : les choix ne sont que des suggestions
            return _make(kind="text", choices=choices, **common)
        if choices or knob.loader or knob.widget == "select":
            return _make(kind="select", choices=choices, **common)
        if knob.widget == "textarea":
            return _make(kind="textarea", **common)
        if knob.widget == "subject" or knob.subject:
            return _make(kind="subject", **common)
        return _make(kind="text", **common)
    if _is_str_sequence(annotation):
        return _make(kind="lines", **common)
    # le reste se lit en YAML ; il ne s'édite que si on l'a demandé (widget « yaml »)
    return _make(kind="yaml", **{**common, "readonly": True})


def _number(name: str, annotation: Any, knob: Knob, metadata: Sequence[Any], common: dict[str, Any]) -> FormField:
    lo, hi, step = _bounds(knob, metadata)
    unit = knob.unit or _guess_unit(name)
    if unit == "min" and not knob.unit and annotation is float:
        unit = ""  # « fond_min », « esteem_min » : un seuil minimal, pas des minutes
    if not knob.unit and unit not in UNIT_US and _LABEL_UNIT.search(common["label"]):
        unit = ""  # « Contexte (jetons) » porte déjà son unité : pas de « (tokens) » deviné en plus
    bounds = {"lo": lo, "hi": hi, "step": step, "unit": unit}
    if knob.choices:
        return _make(kind="select", choices=knob.choices, **bounds, **common)
    if knob.widget == "slider":
        kind = "slider"
    elif knob.widget == "duration" or unit in UNIT_US:
        kind, bounds["unit"] = "duration", unit if unit in UNIT_US else "us"
    else:
        kind = "int" if annotation is int else "float"
    if lo is None and hi is None:
        # la console n'édite que des nombres bornés
        return _make(kind=kind, **bounds, **{**common, "readonly": True, "help": _note(common["help"])})
    return _make(kind=kind, **bounds, **common)


def _value_item(annotation: Any) -> FormField:
    """Le champ d'une valeur de dictionnaire (chemin relatif vide)."""
    inner, extra, nullable = _unwrap(annotation)
    metadata = _expand(extra)
    knob = _knob_of(metadata)
    common: dict[str, Any] = {
        "path": "", "label": knob.label, "help": knob.help, "group": "", "advanced": knob.advanced,
        "readonly": knob.readonly, "required": True, "default": None, "order": knob.order,
        "loader": knob.loader, "subject": knob.subject, "only": (), "keys": (), "choices_from": "",
        "nullable": nullable, "only_any": (),
    }
    return _scalar("", inner, knob, metadata, common)


def _make(*, kind: str, path: str, label: str, help: str, group: str, advanced: bool, readonly: bool,
          required: bool, default: Any, order: int, loader: str, subject: str, only: Only, keys: Pairs,
          choices_from: str, nullable: bool, secret: bool = False, choices: Pairs = (),
          lo: float | None = None, hi: float | None = None, step: float | None = None, unit: str = "",
          item: tuple[FormField, ...] = (), only_any: tuple[Only, ...] = ()) -> FormField:
    return FormField(path=path, label=label, help=help, group=group, kind=kind, advanced=advanced, secret=secret,
                     readonly=readonly, required=required, default=default, lo=lo, hi=hi, step=step, unit=unit,
                     choices=choices, loader=loader, subject=subject, only=only, order=order, item=item,
                     keys=keys, choices_from=choices_from, nullable=nullable, only_any=only_any)


def _knob_of(metadata: Iterable[Any]) -> Knob:
    for m in metadata:
        if isinstance(m, Knob):
            return m
    return Knob()


def _unwrap(annotation: Any) -> tuple[Any, tuple[Any, ...], bool]:
    """Retire ``Annotated`` (en gardant ses métadonnées) et ``| None``."""
    extra: tuple[Any, ...] = ()
    nullable = False
    while True:
        origin = get_origin(annotation)
        if origin is Annotated:
            base, *more = get_args(annotation)
            annotation, extra = base, (*extra, *more)
            continue
        if origin in (Union, types.UnionType):
            args = get_args(annotation)
            others = [a for a in args if a is not type(None)]
            if len(args) == 2 and len(others) == 1:
                annotation, nullable = others[0], True
                continue
        return annotation, extra, nullable


def _expand(metadata: Iterable[Any]) -> tuple[Any, ...]:
    """Un ``Field(...)`` imbriqué (``Annotated[int, Field(ge=0)]``) porte ses propres contraintes."""
    out: list[Any] = []
    for m in metadata:
        if isinstance(m, FieldInfo):
            out.extend(m.metadata)
        else:
            out.append(m)
    return tuple(out)


def _bounds(knob: Knob, metadata: Iterable[Any]) -> tuple[float | None, float | None, float | None]:
    """Bornes du Knob, sinon celles de pydantic (ge/gt/le/lt, lues comme bornes ; le modèle garde
    l'exclusivité à la validation). Le pas : ``Knob.step``, sinon ``multiple_of``."""
    lowers: list[float] = []
    uppers: list[float] = []
    steps: list[float] = []
    for m in metadata:
        if isinstance(m, Knob):
            continue
        lowers += [v for v in (getattr(m, "ge", None), getattr(m, "gt", None)) if _is_number(v)]
        uppers += [v for v in (getattr(m, "le", None), getattr(m, "lt", None)) if _is_number(v)]
        steps += [v for v in (getattr(m, "multiple_of", None),) if _is_number(v)]
    lo = knob.lo if knob.lo is not None else (max(lowers) if lowers else None)
    hi = knob.hi if knob.hi is not None else (min(uppers) if uppers else None)
    step = knob.step if knob.step is not None else (steps[0] if steps else None)
    return lo, hi, step


def _groups(annotation: Any, knob: Knob, nullable: bool) -> bool:
    """Un modèle imbriqué (non optionnel) se déplie en champs pointés."""
    return (isinstance(annotation, type) and issubclass(annotation, BaseModel) and not nullable
            and knob.widget != "yaml")


def _record_model(annotation: Any) -> type[BaseModel] | None:
    origin, args = get_origin(annotation), get_args(annotation)
    if origin is dict and len(args) == 2 and args[0] is str:
        target = _unwrap(args[1])[0]
    elif origin in (list, tuple, Sequence) and args and (origin is not tuple or args[-1] is Ellipsis):
        target = _unwrap(args[0])[0]
    else:
        return None
    return target if isinstance(target, type) and issubclass(target, BaseModel) else None


#: le nom d'une entrée de liste (un fournisseur, une boîte) : lettres, chiffres, tirets, soulignés
RECORD_NAME = re.compile(r"[^\W_][\w-]{0,59}")
RECORD_NAME_RULE = "lettres, chiffres, tirets ou soulignés (60 au plus), en commençant par une lettre ou un chiffre"


def references(model: type[BaseModel], flat: Mapping[str, Any], path: str, key: str) -> list[tuple[str, str]]:
    """Ce qui désigne l'entrée ``key`` de la liste ``path`` par son nom (``choices_from``) : les
    valeurs d'une correspondance (les rôles qui visent un fournisseur), un champ des entrées d'une
    liste (le repli d'un autre fournisseur), un champ simple. ``flat`` : la section aplatie
    (``flatten``). Rend des couples (chemin, libellé lisible) : « routes.reply », « Rôles · répondre »."""
    out: list[tuple[str, str]] = []
    for f in describe(model):
        if f.kind == "mapping" and f.choices_from == path:
            labels = dict(f.keys)
            for k, v in (flat.get(f.path) or {}).items():
                if v == key:
                    out.append((f"{f.path}.{k}", f"{f.label} · {labels.get(k, k)}"))
        elif f.kind == "records":
            entries = flat.get(f.path) or {}
            items = list(entries.items() if isinstance(entries, Mapping) else enumerate(entries))
            for item in f.item:
                if item.choices_from != path or "." in item.path:
                    continue
                for k, entry in items:
                    if isinstance(entry, Mapping) and entry.get(item.path) == key and str(k) != key:
                        out.append((f"{f.path}.{k}.{item.path}", f"{f.label} · {k} · {item.label}"))
        elif f.choices_from == path and f.kind not in ("group", "records", "mapping") and flat.get(f.path) == key:
            out.append((f.path, f.label))
    return out


def rename_references(model: type[BaseModel], flat: Mapping[str, Any], path: str, old: str,
                      new: str) -> tuple[dict[str, Any], list[str]]:
    """Ce qui change quand l'entrée ``old`` de ``path`` s'appelle désormais ``new`` : chaque
    référence suit (``references``). Rend les changements (chemins de premier niveau → valeurs, à
    fondre par ``validate``) et ce qui a suivi, en mots."""
    changes: dict[str, Any] = {}
    touched: list[str] = []
    for ref, label in references(model, flat, path, old):
        top, _, rest = ref.partition(".")
        value = changes.get(top, _plain(flat.get(top)))
        if not rest:
            changes[top] = new
        elif isinstance(value, Mapping):
            key, _, field = rest.partition(".")
            value = dict(value)
            if field:
                entry = dict(value.get(key) or {})
                entry[field] = new
                value[key] = entry
            else:
                value[key] = new
            changes[top] = value
        else:
            continue
        touched.append(label)
    return changes, touched


def record_model(model: type[BaseModel], path: str) -> tuple[type[BaseModel], bool] | None:
    """Le modèle des enregistrements d'un champ ``records`` de premier niveau, et s'ils
    sont rangés par clé (``dict[str, M]``) plutôt qu'en liste."""
    info = model.model_fields.get(path)
    if info is None:
        return None
    annotation = _unwrap(info.annotation)[0]
    found = _record_model(annotation)
    return None if found is None else (found, get_origin(annotation) is dict)


def _mapping_value(annotation: Any) -> Any:
    origin, args = get_origin(annotation), get_args(annotation)
    if origin is dict and len(args) == 2 and args[0] is str and _is_scalar(_unwrap(args[1])[0]):
        return args[1]
    return None


def _is_scalar(annotation: Any) -> bool:
    return (annotation in (bool, int, float, str) or get_origin(annotation) is Literal
            or (isinstance(annotation, type) and issubclass(annotation, enum.Enum)))


def _is_str_sequence(annotation: Any) -> bool:
    """Une liste de textes (ou de nombres entiers : des identifiants), une par ligne ;
    le modèle convertit chaque ligne à la validation."""
    origin, args = get_origin(annotation), get_args(annotation)
    if origin is tuple:
        return len(args) == 2 and args[1] is Ellipsis and _unwrap(args[0])[0] in (str, int)
    return origin in (list, Sequence, frozenset, set) and len(args) == 1 and _unwrap(args[0])[0] in (str, int)


def _default_of(name: str, info: FieldInfo, scope: _Scope) -> Any:
    """La valeur par défaut brute : celle du parent d'abord, sinon celle déclarée."""
    if scope.defaults is not None:
        return getattr(scope.defaults, name)
    if info.is_required():
        return None
    return info.get_default(call_default_factory=True)


def _rebase_only(only: Only, prefix: str) -> Only:
    return tuple((prefix + path, tuple(values)) for path, values in only)


def _rate(name: str) -> bool:
    """« empty_growth_per_h », « steps_per_s » : un débit (tant par heure), pas une durée."""
    return any(name.endswith(f"_per{suffix}") for suffix, unit in _SUFFIXES if unit in UNIT_US)


def _guess_unit(name: str) -> str:
    if _rate(name):
        return ""  # « par heure » est dans le nom, pas une unité de la valeur : 0,05 par heure n'est pas 3 min
    for suffix, unit in _SUFFIXES:
        if name.endswith(suffix):
            return unit
    return ""


def _humanize(name: str) -> str:
    """``tau_wake_h`` → « Tau wake » : l'unité de temps s'affiche à part."""
    base = name
    for suffix, unit in _SUFFIXES:
        if unit in UNIT_US and base.endswith(suffix) and len(base) > len(suffix) and not _rate(base):
            base = base[: -len(suffix)]
            break
    text = base.replace("_", " ").strip()
    return text[:1].upper() + text[1:] if text else name


def _secret_name(name: str) -> bool:
    return any(name == s or name.endswith("_" + s) for s in _SECRET_NAMES)


def _enum_label(member: enum.Enum) -> str:
    label = getattr(member, "label", None)
    return label if isinstance(label, str) else str(member.value)


def _note(text: str) -> str:
    return f"{text} {UNBOUNDED_NOTE}".strip()


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# ── Aplatir, emboîter ─────────────────────────────────────────────────────


class PathConflict(ValueError):
    """Deux chemins se contredisent (une feuille et un sous-arbre au même endroit)."""

    def __init__(self, path: str, message: str) -> None:
        super().__init__(message)
        self.path = path


def flatten(value: BaseModel) -> dict[str, Any]:
    """Les valeurs du modèle par chemin pointé ; seuls les modèles imbriqués
    se déplient (un dictionnaire d'enregistrements reste une valeur)."""
    out: dict[str, Any] = {}
    for name, info in type(value).model_fields.items():
        current = getattr(value, name)
        annotation, extra, nullable = _unwrap(info.annotation)
        knob = _knob_of(_expand((*info.metadata, *extra)))
        if isinstance(current, BaseModel) and _groups(annotation, knob, nullable):
            out.update({f"{name}.{path}": sub for path, sub in flatten(current).items()})
        else:
            out[name] = _plain(current)
    return out


def nest(flat: Mapping[str, Any]) -> dict[str, Any]:
    """L'inverse de ``flatten`` : ``{"a.b": 1}`` → ``{"a": {"b": 1}}``. Un chemin
    plus profond qu'une valeur dictionnaire s'y fond (sans la modifier)."""
    root: dict[str, Any] = {}
    ours: set[int] = {id(root)}
    for path in sorted(flat, key=lambda p: p.count(".")):
        parts = path.split(".")
        if not all(parts):
            raise PathConflict(path, f"chemin invalide : « {path} »")
        node = root
        for depth, part in enumerate(parts[:-1]):
            child = node.get(part)
            if child is None:
                child = node[part] = {}
                ours.add(id(child))
            elif isinstance(child, Mapping) and id(child) not in ours:
                child = node[part] = dict(child)
                ours.add(id(child))
            elif not isinstance(child, Mapping):
                where = ".".join(parts[: depth + 1])
                raise PathConflict(path, f"« {path} » contredit la valeur de « {where} »")
            node = child
        node[parts[-1]] = flat[path]
    return root


def plain(value: Any) -> Any:
    """Une valeur sans modèles (enums et tuples gardés) : ce que ``flatten`` rend."""
    return _plain(value)


def _plain(value: Any) -> Any:
    """Les modèles contenus deviennent des dictionnaires (enums et tuples gardés)."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="python")
    if isinstance(value, Mapping):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return tuple(_plain(v) for v in value)
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


# ── Rendre, relire ────────────────────────────────────────────────────────


def as_text(field: FormField, value: Any) -> str:
    """La valeur telle qu'elle s'affiche dans son champ (l'inverse de ``parse``).
    Un secret ne s'affiche jamais ; ``mapping`` se rend clé par clé avec ``field.item[0]``."""
    if field.kind in ("secret", "file") or value is None or field.kind in ("group", "records", "mapping"):
        return ""
    if isinstance(value, enum.Enum):
        value = value.value
    if field.kind == "bool":
        return "1" if value else ""
    if field.kind == "lines":
        items = sorted(value, key=str) if isinstance(value, set | frozenset) else value
        return "\n".join(str(v) for v in items)
    if field.kind == "duration":
        return show_duration(round(value * UNIT_US[field.unit]))
    if field.kind == "yaml":
        return json.dumps(_plain(value), ensure_ascii=False, indent=2, default=str)
    return str(value)


_KEEP = object()  # un secret laissé vide : inchangé


def parse(fields: Sequence[FormField], form: Mapping[str, Any], *, current: Mapping[str, Any],
          load: Callable[[str], Any] = json.loads) -> tuple[dict[str, Any], dict[str, str]]:
    """Relit une soumission brute (multi-dictionnaire : chaque valeur est une liste).

    Seuls les chemins listés dans ``_champs`` sont lus ; un champ en lecture
    seule, un groupe ou des enregistrements ne le sont jamais. Rend (valeurs
    des chemins rendus, erreurs par chemin) ; le reste garde sa valeur
    courante (à l'appelant de fusionner). ``current`` : valeurs aplaties
    actuelles. ``load`` décode un champ YAML et lève ``ValueError`` s'il est
    illisible (défaut : JSON, que tout YAML sait lire)."""
    rendered = set(_values(form, RENDERED))
    cleared = set(_values(form, CLEARED))
    values: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for f in fields:
        if f.path not in rendered or f.readonly or f.kind in ("group", "records"):
            continue
        if f.kind == "mapping":
            mapping, problems = _read_mapping(f, form, current, load)
            errors.update(problems)
            if not problems:
                values[f.path] = mapping
            continue
        try:
            value = _read(f, form, cleared, load)
        except ValueError as exc:
            errors[f.path] = str(exc)
            continue
        if value is not _KEEP:
            values[f.path] = value
    # un champ masqué par sa condition ne s'écrit pas (sa case absente n'est pas un « non »)
    merged = {**current, **values}
    for f in fields:
        if (f.only or f.only_any) and not _visible(f, merged):
            values.pop(f.path, None)
            for path in [p for p in errors if p == f.path or p.startswith(f.path + ".")]:
                del errors[path]
    return values, errors


def _read(f: FormField, form: Mapping[str, Any], cleared: set[str], load: Callable[[str], Any]) -> Any:
    if f.kind == "file":
        return _read_file(f, form)
    if f.kind == "bool":
        # une case décochée n'est pas envoyée : affichée et absente, elle vaut False
        return bool(_values(form, f.path))
    if f.kind == "secret":
        if f.path in cleared:
            return ""
        raw = _last(form, f.path)
        return _KEEP if not raw.strip() else raw
    return _read_text(f, _last(form, f.path), load)


def _read_file(f: FormField, form: Mapping[str, Any]) -> Upload | None:
    """Le dernier fichier envoyé sous ce chemin (la console l'a lu en ``Upload``) ; lève
    ``ValueError`` s'il manque alors qu'il est requis, s'il est trop gros ou sans nom."""
    raw = form.get(f.path)
    got = raw[-1] if isinstance(raw, list | tuple) and raw else raw
    if not isinstance(got, Upload) or (not got.name and not got.data):
        if f.required and not f.nullable:
            raise ValueError("choisis un fichier")
        return None
    if got.too_big:
        raise ValueError(f"fichier trop gros : {UPLOAD_MAX // (1024 * 1024)} Mo au plus")
    name = safe_name(got.name)
    if not name:
        raise ValueError("nom de fichier illisible")
    return Upload(name=name, data=got.data)


def _read_text(f: FormField, raw: str, load: Callable[[str], Any]) -> Any:
    """Une saisie texte selon le genre du champ ; lève ``ValueError`` (en français)."""
    text = raw.replace("\r\n", "\n").strip()
    if f.kind == "lines":
        return tuple(line.strip() for line in text.splitlines() if line.strip())
    if f.kind in ("text", "textarea", "subject", "datetime"):
        return None if not text and f.nullable else text
    if not text:
        if f.nullable:
            return None
        raise ValueError("choisissez une valeur" if f.kind == "select" else "valeur requise")
    if f.kind == "int":
        return _parse_int(text)
    if f.kind in ("float", "slider"):
        return _parse_float(text)
    if f.kind == "duration":
        us, size = parse_duration(text), UNIT_US[f.unit]
        return us // size if us % size == 0 else us / size
    if f.kind == "select":
        if f.choices and text not in {value for value, _ in f.choices}:
            raise ValueError(f"choix inconnu : « {text} »")
        return text
    if f.kind == "yaml":
        try:
            return load(text)
        except ValueError as exc:
            raise ValueError(f"illisible : {exc}") from exc
    raise ValueError(f"champ non modifiable ici ({f.kind})")


def _read_mapping(f: FormField, form: Mapping[str, Any], current: Mapping[str, Any],
                  load: Callable[[str], Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Un dictionnaire arrive en entrées ``chemin.clé`` ; une clé laissée vide est absente."""
    item = f.item[0] if f.item else _make(
        kind="text", path="", label="", help="", group="", advanced=True, readonly=False, required=True,
        default=None, order=100, loader="", subject="", only=(), keys=(), choices_from="", nullable=False)
    prefix = f.path + "."
    keys = [k for k, _ in f.keys] if f.keys else sorted(
        name[len(prefix):] for name in form if name.startswith(prefix) and len(name) > len(prefix))
    source = current.get(f.choices_from) if f.choices_from else None
    allowed = {str(k) for k in source} if isinstance(source, Mapping) else None
    out: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for key in keys:
        path = prefix + key
        if item.kind == "bool":
            out[key] = bool(_values(form, path))
            continue
        raw = _last(form, path)
        if not raw.strip():
            continue
        try:
            value = _read_text(item, raw, load)
        except ValueError as exc:
            errors[path] = str(exc)
            continue
        if allowed is not None and str(value) not in allowed:
            errors[path] = f"choix inconnu : « {value} »"
            continue
        out[key] = value
    return out, errors


def _visible(f: FormField, values: Mapping[str, Any]) -> bool:
    def holds(only: Only) -> bool:
        return all(_choice(values.get(path)) in allowed for path, allowed in only)

    return holds(f.only) and (not f.only_any or any(holds(alt) for alt in f.only_any))


def visible(f: FormField, values: Mapping[str, Any]) -> bool:
    """Le champ s'affiche-t-il avec ces valeurs (aplaties) ? (``only`` et ``only_any``)."""
    return _visible(f, values)


def _choice(value: Any) -> str:
    """Une valeur comparée à une condition ``only`` : ce que le formulaire en enverrait."""
    if isinstance(value, enum.Enum):
        value = value.value
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else str(value)


def _values(form: Mapping[str, Any], key: str) -> list[str]:
    raw = form.get(key)
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    return [str(v) for v in raw]


def _last(form: Mapping[str, Any], key: str) -> str:
    found = _values(form, key)
    return found[-1] if found else ""


_SPACES = re.compile(r"\s")  # espaces des milliers compris (insécables : \s les couvre)


def _parse_int(text: str) -> int:
    compact = _SPACES.sub("", text)
    if not re.fullmatch(r"[+-]?[0-9]+", compact):
        raise ValueError("doit être un nombre entier")
    return int(compact)


def _parse_float(text: str) -> float:
    compact = _SPACES.sub("", text).replace(",", ".")
    try:
        value = float(compact)
    except ValueError:
        raise ValueError("doit être un nombre") from None
    if not math.isfinite(value):
        raise ValueError("doit être un nombre fini")
    return value


# ── Bornes et validation ──────────────────────────────────────────────────


def within(fields: Sequence[FormField], values: Mapping[str, Any]) -> dict[str, str]:
    """Les bornes de la console, à l'écriture seulement (jamais au décodage)."""
    errors: dict[str, str] = {}
    for f in fields:
        if f.path not in values:
            continue
        value = values[f.path]
        if f.kind == "mapping" and f.item and isinstance(value, Mapping):
            for key, sub in value.items():
                if message := _out_of_bounds(f.item[0], sub):
                    errors[f"{f.path}.{key}"] = message
        elif message := _out_of_bounds(f, value):
            errors[f.path] = message
    return errors


def _out_of_bounds(f: FormField, value: Any) -> str:
    if f.kind not in _NUMERIC or not _is_number(value):
        return ""
    lo, hi = f.lo, f.hi
    if (lo is None or value >= lo) and (hi is None or value <= hi):
        return ""
    if f.kind == "duration":
        size = UNIT_US[f.unit]

        def show(x: float) -> str:
            return show_duration(round(x * size))
    else:
        show = _num
    if lo is not None and hi is not None:
        return f"doit être entre {show(lo)} et {show(hi)}"
    if lo is not None:
        return f"doit être au moins {show(lo)}"
    return f"doit être au plus {show(hi)}"


def validate(model: type[BaseModel], base: BaseModel,
             changes: Mapping[str, Any]) -> tuple[BaseModel | None, dict[str, str]]:
    """Fond ``changes`` (chemins pointés) dans ``base`` et fait valider le tout par
    le modèle : le nouveau modèle, ou les erreurs en français par chemin."""
    flat = {path: value for path, value in flatten(base).items()
            if not any(path.startswith(change + ".") for change in changes)}
    flat.update(changes)
    try:
        data = nest(flat)
    except PathConflict as exc:
        return None, {exc.path: str(exc)}
    try:
        return model.model_validate(data), {}
    except ValidationError as exc:
        return None, errors_fr(exc)


_FIXED_FR: Mapping[str, str] = MappingProxyType({
    "missing": "valeur requise",
    "extra_forbidden": "champ inconnu",
    "int_parsing": "doit être un nombre entier",
    "int_type": "doit être un nombre entier",
    "int_from_float": "doit être un nombre entier",
    "float_parsing": "doit être un nombre",
    "float_type": "doit être un nombre",
    "finite_number": "doit être un nombre fini",
    "bool_parsing": "doit être oui ou non",
    "bool_type": "doit être oui ou non",
    "string_type": "doit être du texte",
    "dict_type": "doit être un dictionnaire",
    "list_type": "doit être une liste",
    "tuple_type": "doit être une liste",
    "model_type": "doit être un objet",
    "model_attributes_type": "doit être un objet",
    "frozen_field": "non modifiable",
    "frozen_instance": "non modifiable",
})


def errors_fr(exc: ValidationError) -> dict[str, str]:
    """Les erreurs de pydantic en phrases françaises, par chemin pointé."""
    grouped: dict[str, list[str]] = {}
    for err in exc.errors(include_url=False):
        path = ".".join(str(part) for part in err["loc"])
        message = _message_fr(err)
        bucket = grouped.setdefault(path, [])
        if message not in bucket:
            bucket.append(message)
    return {path: " ; ".join(messages) for path, messages in grouped.items()}


def message_fr(err: Mapping[str, Any]) -> str:
    """Une erreur de pydantic (un élément de ``ValidationError.errors()``) en une phrase française."""
    return _message_fr(err)


def _message_fr(err: Mapping[str, Any]) -> str:
    kind = str(err.get("type", ""))
    ctx = err.get("ctx") or {}
    if kind in _FIXED_FR:
        return _FIXED_FR[kind]
    if kind in ("literal_error", "enum"):
        expected = str(ctx.get("expected", "")).replace("' or '", "', '")
        return f"doit être l'une des valeurs : {expected}"
    if kind == "greater_than_equal":
        return f"doit être supérieur ou égal à {_num(ctx.get('ge'))}"
    if kind == "greater_than":
        return f"doit être strictement supérieur à {_num(ctx.get('gt'))}"
    if kind == "less_than_equal":
        return f"doit être inférieur ou égal à {_num(ctx.get('le'))}"
    if kind == "less_than":
        return f"doit être strictement inférieur à {_num(ctx.get('lt'))}"
    if kind == "multiple_of":
        return f"doit être un multiple de {_num(ctx.get('multiple_of'))}"
    if kind in ("too_long", "string_too_long"):
        what = "caractères" if kind.startswith("string") else "éléments"
        return f"trop long : {ctx.get('max_length')} {what} au plus"
    if kind in ("too_short", "string_too_short"):
        what = "caractères" if kind.startswith("string") else "éléments"
        return f"trop court : {ctx.get('min_length')} {what} au moins"
    if kind == "value_error":
        return f"valeur refusée : {ctx.get('error', err.get('msg', ''))}"
    return f"valeur invalide ({err.get('msg', kind)})"


def _num(value: Any) -> str:
    """Un nombre à la française : « 0,5 », « 1 » (pas « 1.0 »)."""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).replace(".", ",") if _is_number(value) else str(value)


# ── Durées ────────────────────────────────────────────────────────────────

_DURATION_UNITS: Mapping[str, int] = MappingProxyType({
    "j": _DAY, "jour": _DAY, "jours": _DAY, "d": _DAY,
    "h": _HOUR, "heure": _HOUR, "heures": _HOUR,
    "min": _MINUTE, "mn": _MINUTE, "m": _MINUTE, "minute": _MINUTE, "minutes": _MINUTE,
    "s": _SECOND, "sec": _SECOND, "seconde": _SECOND, "secondes": _SECOND,
    "ms": _MS, "µs": _US, "μs": _US, "us": _US,
})
_STEPS = (_DAY, _HOUR, _MINUTE, _SECOND, _MS, _US)
_SHOWN = ((_DAY, "j"), (_HOUR, "h"), (_MINUTE, "min"), (_SECOND, "s"), (_MS, "ms"), (_US, "µs"))
_TOKEN = re.compile(r"\s*([0-9]+(?:[.,][0-9]+)?)\s*([^\W\d_]+)?\s*")
_EXAMPLES = "exemples : 10 min, 1 h 30, 1,5 h, 250 ms"


def parse_duration(text: str) -> int:
    """« 10 min », « 1 h 30 », « 1.5h », « 250 ms », « 3 j 2 h » → microsecondes.

    Unités décroissantes, chacune une fois ; un nombre final sans unité prend
    l'unité juste en dessous de la précédente (« 1 h 30 » = 1 h 30 min).
    Lève ``ValueError`` (en français) sur tout le reste."""
    raw = text.strip()
    if not raw:
        raise ValueError("durée vide")
    if raw[0] in "-−":
        raise ValueError("une durée ne peut pas être négative")
    tokens: list[tuple[str, str | None]] = []
    pos = 0
    while pos < len(raw):
        match = _TOKEN.match(raw, pos)
        if match is None:
            raise ValueError(f"durée illisible : « {raw} » ({_EXAMPLES})")
        tokens.append((match.group(1), match.group(2)))
        pos = match.end()
    total = Decimal(0)
    previous: int | None = None
    for index, (number, name) in enumerate(tokens):
        amount = Decimal(number.replace(",", "."))
        if name is not None:
            size = _DURATION_UNITS.get(name.lower())
            if size is None:
                raise ValueError(f"unité inconnue : « {name} » (j, h, min, s, ms, µs)")
        elif index == len(tokens) - 1 and previous is not None and previous > _US:
            size = _STEPS[_STEPS.index(previous) + 1]
        elif len(tokens) == 1 and amount == 0:
            size = _US
        else:
            raise ValueError(f"précisez l'unité de « {number} » ({_EXAMPLES})")
        if previous is not None and size >= previous:
            raise ValueError(f"unités répétées ou dans le désordre : « {raw} » (du jour à la microseconde)")
        total += amount * size
        previous = size
    return int(total.to_integral_value())


def show_duration(us: int) -> str:
    """Microsecondes → « 1 h 30 min », « 45 s », « 3 j 2 h » (relu par ``parse_duration``)."""
    sign, rest = ("-", -us) if us < 0 else ("", us)
    parts = []
    for size, name in _SHOWN:
        count, rest = divmod(rest, size)
        if count:
            parts.append(f"{count} {name}")
    return sign + (" ".join(parts) or "0 s")
