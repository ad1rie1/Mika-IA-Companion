"""Rendre la vue d'une app forgée : l'appeler dans le bac à sable, décoder son
enveloppe avec le décodeur partagé (``kernel/envelope.py``), qualifier ses
formulaires.

- **Jamais journalisé, jamais compté par le disjoncteur** : une vue est une
  lecture d'opérateur. Elle a 3 s et 256 Ko ; au-delà, une note le dit.
- **Liens** : seulement vers une autre vue déclarée de la même app (sa fiche,
  onglet « Vues »), avec les seuls paramètres que cette vue déclare (et
  ``page``) ; ou une adresse http(s) (le décodeur s'en charge).
- **Formulaires** : ``{"type": "form", "action": "ajouter"}`` désigne une action
  déclarée *de la même vue* ; il devient le formulaire de ``forge.agir`` (l'app,
  la vue et l'action y sont des valeurs fixes, jamais celles de l'app).

Tout ce qui ne va pas devient une note en français, jamais une exception.
"""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from mika.kernel.envelope import decode
from mika.kernel.inspect import (
    ActionSlot,
    Block,
    Code,
    Disclosure,
    Grid,
    Note,
    Param,
    Ref,
    Row,
    Section,
    Table,
    read_params,
)
from mika.ports.forge import AppInfo, AppViewSpec, CallResult
from mika.vocab.affect import Emotion

VIEW_TIMEOUT_S = 3.0
VIEW_MAX_BYTES = 256_000
VIEW_CACHE_S = 2.0
ACTION_TIMEOUT_S = 5.0
MAX_PAGE = 100_000
#: les pastilles d'émotion admises dans une vue (les 29 noms canoniques)
EMOTIONS = frozenset(e.value for e in Emotion)
#: l'action de la console qui exécute une action d'app
ACT = "forge.agir"
INVALID = "Vue invalide"


def fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(text).lower()) if not unicodedata.combining(c))


@dataclass(frozen=True, slots=True)
class Links:
    """La politique de liens d'une app : une autre de ses vues, sur sa fiche."""

    app: str
    views: Mapping[str, AppViewSpec]

    def view(self, key: str, params: Mapping[str, str]) -> Ref | None:
        spec = self.views.get(key)
        if spec is None:
            return None
        declared = {p.key for p in spec.params} | {"page"}
        kept = tuple((k, str(v)) for k, v in params.items() if k in declared)
        return Ref("subject", f"app/{self.app}", "", (("onglet", "vues"), ("vue", key), *kept))


def links(app: str, info: AppInfo) -> Links:
    return Links(app, {v.key: v for v in info.views})


def view_params(spec: AppViewSpec, raw: Mapping[str, str]) -> tuple[dict[str, Any], list[str]]:
    """Les paramètres déclarés, vérifiés (une valeur inconnue retombe sur le défaut,
    et le dit), plus ``page`` (≥ 1)."""
    specs = [Param(p.key, p.label, p.kind, p.choices, p.default) for p in spec.params]
    values, notes = read_params(specs, raw)
    try:
        page = int(str(raw.get("page", "") or 1))
    except ValueError:
        page = 1
    values["page"] = max(1, min(page, MAX_PAGE))
    return values, notes


def find_view(info: AppInfo, wanted: str) -> AppViewSpec | None:
    """Une vue par sa clé, ou par son libellé tapé à la main."""
    if not wanted:
        return None
    folded = fold(wanted)
    return next((v for v in info.views if v.key == wanted or fold(v.label) == folded or fold(v.key) == folded), None)


class _Bad(Exception):
    pass


def qualify(blocks: Sequence[Any], app: str, spec: AppViewSpec) -> list[Any]:
    """Chaque formulaire de la vue devient celui de ``forge.agir`` ; un formulaire
    qui désigne une action que la vue ne déclare pas lève ``_Bad``."""

    def one(b: Any) -> Any:
        if isinstance(b, ActionSlot):
            action = spec.action(b.action)
            if action is None:
                declared = ", ".join(a.key for a in spec.actions) or "aucune"
                raise _Bad(f"le formulaire « {b.action} » désigne une action que la vue « {spec.key} » ne déclare "
                           f"pas (déclarées : {declared})")
            fields = {f.path for f in action.fields}
            given = tuple(sorted((k, v) for k, v in b.initial if k in fields))
            label = ("⚠ " if action.danger else "") + action.label
            fixed = (("action", action.key), ("app", app), ("vue", spec.key), ("_bouton", label))
            return ActionSlot(ACT, initial=(*fixed, *given), title=b.title or action.label, compact=b.compact)
        if isinstance(b, Grid | Section | Disclosure):
            return replace(b, items=tuple(one(x) for x in b.items))
        if isinstance(b, Table):
            return replace(b, rows=tuple(replace(r, detail=tuple(one(x) for x in r.detail))
                                         if isinstance(r, Row) else r for r in b.rows))
        return b

    return [one(b) for b in blocks]


def is_invalid(blocks: Sequence[Any]) -> bool:
    return len(blocks) == 1 and isinstance(blocks[0], Note) and blocks[0].title == INVALID


def _looks_like_envelope(value: Any) -> bool:
    return isinstance(value, dict) and ("version" in value or "blocks" in value)


def failure_note(label: str, r: CallResult, timeout_s: float = VIEW_TIMEOUT_S) -> Note:
    """Pourquoi une vue ne se montre pas (rien n'est compté contre l'app)."""
    if r.killed and "délai" in r.error:
        return Note(f"La vue « {label} » a mis plus de {timeout_s:g} s : arrêtée. Rien n'est compté contre l'app.",
                    tone="warn", title="Vue trop lente")
    if "trop gros" in r.error:
        return Note(f"La vue « {label} » rend trop de données ({r.error}). Rien n'est compté contre l'app.",
                    tone="warn", title="Vue trop grosse")
    return Note(f"La vue « {label} » n'a pas pu se rendre : {r.error[:600]}", tone="danger", title="Vue en panne")


def decode_view(value: Any, app: str, info: AppInfo, spec: AppViewSpec) -> list[Block]:
    """Les blocs d'une vue rendue, ou une note qui dit pourquoi pas."""
    if spec.function == "view" and not _looks_like_envelope(value):  # une ancienne vue : une donnée brute
        text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
        cut = len(text) > 20_000
        return [Note("Cette ancienne vue rend une donnée brute, pas une enveloppe {\"version\": 2, \"blocks\": […]} "
                     "(forge_help blocs).", tone="muted"),
                Code(text[:20_000] + ("\n…" if cut else ""), title="Ce que rend view(api)")]
    blocks = decode(value, links=links(app, info), emotions=EMOTIONS)
    if is_invalid(blocks):
        return blocks
    try:
        return qualify(blocks, app, spec)
    except _Bad as exc:
        return [Note(str(exc), tone="danger", title=INVALID)]


async def render(port: Any, app: str, info: AppInfo, spec: AppViewSpec, values: Mapping[str, Any], *,
                 cache_s: float = VIEW_CACHE_S) -> list[Block]:
    """Appelle la vue (3 s, 256 Ko) et la décode."""
    args = {} if spec.function == "view" else dict(values)
    r: CallResult = await port.call(app, spec.function, args, timeout_s=VIEW_TIMEOUT_S, max_result=VIEW_MAX_BYTES,
                                    cache_s=cache_s)
    if not r.ok:
        return [failure_note(spec.label, r)]
    return decode_view(r.value, app, info, spec)


def without_forms(blocks: Sequence[Any]) -> list[Any]:
    """Les formulaires deviennent des notes (un résultat de test n'est pas une vue vivante)."""

    def one(b: Any) -> Any:
        if isinstance(b, ActionSlot):
            label = dict(b.initial).get("_bouton", b.action)
            return Note(f"Formulaire « {label} » (utilisable depuis l'onglet Vues).", tone="muted")
        if isinstance(b, Grid | Section | Disclosure):
            return replace(b, items=tuple(one(x) for x in b.items))
        if isinstance(b, Table):
            return replace(b, rows=tuple(replace(r, detail=tuple(one(x) for x in r.detail))
                                         if isinstance(r, Row) else r for r in b.rows))
        return b

    return [one(b) for b in blocks]


def summary(blocks: Sequence[Any]) -> str:
    """Ce que contient une vue valide, en une ligne (pour ``forge_test``)."""
    counts: dict[str, int] = {}
    forms: list[str] = []

    def walk(items: Sequence[Any]) -> None:
        for b in items:
            name = type(b).__name__.lower()
            if isinstance(b, ActionSlot):
                forms.append(dict(b.initial).get("action", b.action))
                name = "form"
            counts[name] = counts.get(name, 0) + 1
            if isinstance(b, Grid | Section | Disclosure):
                walk(b.items)
            elif isinstance(b, Table):
                walk([x for r in b.rows if isinstance(r, Row) for x in r.detail])

    walk(blocks)
    parts = ", ".join(f"{n} {k}" for k, n in sorted(counts.items()))
    return f"enveloppe valide : {parts or 'aucun bloc'}" + (f" ; formulaires : {', '.join(forms)}" if forms else "")
