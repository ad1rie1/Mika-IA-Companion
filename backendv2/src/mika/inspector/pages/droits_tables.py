"""Ce que partagent les tableaux de droits de la console (ADR 0131, 0133, 0134) — ceux de l'application (Réglages ›
Canaux, Outils › Ses propres outils) et ceux des propriétaires (un service, un projet, une app) : les personnes qu'une
ligne peut nommer, ses sources, ses canaux et ses moments à cocher, un formulaire de tableau lu d'un coup, le dessin
(``handmade/droits/tableau.html``). Rien d'une faculté ici : les personnes viennent des comptes, les instances des
réglages."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from mika.inspector import render
from mika.inspector.ui import UI
from mika.kernel.inspect import Pager
from mika.vocab.access import (
    ANY,
    CANALS,
    INTERNAL,
    MAIL,
    MOMENTS,
    PERSON,
    PRIVATE,
    SOURCE_WORDS,
    SOURCES,
    TOGETHER,
    WEB,
    TableArgs,
    canal_key,
    canal_words,
    when_words,
    who_words,
)

#: les moments d'une ligne, dans sa liste à cocher
MOMENT_CHOICES = tuple((k, label[:1].upper() + label[1:]) for k, label in MOMENTS)
#: les instances qu'un canal peut avoir, telles que la console les propose : par type, (clé, nom)
Instances = dict[str, list[tuple[str, str]]]


def people(ui: UI) -> list[dict[str, str]]:
    """Les personnes qu'une ligne peut nommer : celles qui ont un compte (seules à pouvoir être reconnues), par leur
    nom — jamais un opérateur propriétaire, que « Toi » désigne déjà."""
    out = []
    for account in ui.deps.accounts.all():
        handle = getattr(account, "handle", "")
        if not handle or getattr(account, "operator", False):
            continue
        person = ui.names.person_of(handle) or handle
        out.append({"key": person, "name": ui.names.name_of(handle)})
    return sorted({p["key"]: p for p in out}.values(), key=lambda p: p["name"].casefold())


def who_choices(who: Sequence[str], people_: Sequence[dict[str, str]], name: Callable[[str], str]) -> dict[str, Any]:
    """Les cases « qui » d'une ligne : ses sources, puis les personnes qui ont un compte ; une personne qu'elle coche
    et qui n'a plus de compte, une adresse (un canal de messagerie), restent là, cochées, pour qu'on puisse les
    décocher."""
    got = set(who)
    boxes = [{"value": k, "label": label, "word": SOURCE_WORDS[k], "on": k in got} for k, label in SOURCES]
    listed = {PERSON + p["key"] for p in people_}
    boxes += [{"value": PERSON + p["key"], "label": p["name"], "word": p["name"], "on": PERSON + p["key"] in got}
              for p in people_]
    for w in sorted(got):
        if w in listed or w in dict(SOURCES):
            continue
        label = name(w[len(PERSON):]) if w.startswith(PERSON) else w.partition(":")[2]
        boxes.append({"value": w, "label": label, "word": label, "on": True})
    return {"boxes": boxes, "said": who_words(who, name) if who else "Personne"}


def canal_instances(ui: UI) -> Instances:
    """Les instances de chaque type de canal : le chat web (en privé, en salon), chaque boîte de courrier, et celles
    qu'un tableau réglé nomme déjà."""
    out: Instances = {WEB: [(f"{WEB}:{PRIVATE}", "en privé"), (f"{WEB}:{TOGETHER}", "en salon")]}
    settings = ui.deps.settings
    try:
        accounts = settings.email().accounts if settings is not None else {}
    except Exception:  # noqa: BLE001 — des boîtes illisibles : aucune instance, le type reste
        accounts = {}
    out[MAIL] = [(f"{MAIL}:{key}", a.label or key) for key, a in sorted(accounts.items())]
    try:
        keys = sorted(settings.canals().tables) if settings is not None else []
    except Exception:  # noqa: BLE001 — des tableaux illisibles : les minimums vitaux, aucune instance de plus
        keys = []
    for key in keys:
        kind, instance = canal_key(key)
        if instance and key not in {k for k, _ in out.get(kind, ())}:
            out.setdefault(kind, []).append((key, instance))
    return out


def canal_choices(canal: Sequence[str], instances: Instances) -> dict[str, Any]:
    """Les cases « par où » d'une ligne : « tous », chaque type, puis ses instances ; ce qu'elle coche d'autre (une
    instance disparue) reste là, coché, pour qu'on puisse le décocher."""
    got = set(canal)
    boxes: list[dict[str, Any]] = [{"value": ANY, "label": "Tous", "on": not got, "all": True}]
    listed = set()
    for kind, label in CANALS:
        boxes.append({"value": kind, "label": label, "on": kind in got})
        listed.add(kind)
        for key, name in instances.get(kind, ()):
            boxes.append({"value": key, "label": f"{label} · {name}", "on": key in got, "sub": True})
            listed.add(key)
    boxes += [{"value": c, "label": c, "on": True} for c in sorted(got) if c not in listed]
    names = {key: name for kind in instances for key, name in instances[kind]}
    return {"boxes": boxes, "said": canal_words(canal, lambda kind, inst: names.get(f"{kind}:{inst}", inst))}


def table_args(model: type[TableArgs], data: Mapping[str, Any]) -> TableArgs:
    """Un formulaire de tableau envoyé (``<champ>.<numéro>``, ``<champ>.<numéro>|<valeur>``) lu dans son modèle : chaque
    champ-dictionnaire reçoit ses entrées telles quelles (une case cochée vaut « on », que le modèle lit vrai), les
    autres leur valeur."""
    dicts = {name for name, f in model.model_fields.items() if str(f.annotation).startswith("dict[")}
    raw: dict[str, Any] = {name: {} for name in dicts}
    for key, value in data.items():
        head, dot, rest = key.partition(".")
        if dot and head in dicts:
            raw[head][rest] = value
        elif not dot and key in model.model_fields:
            raw[key] = value
    return model.model_validate(raw)


def choices(options: Sequence[tuple[str, str]], locked: Sequence[str] = ()) -> list[tuple[str, str, bool]]:
    """Les choix d'une colonne, chacun avec « verrouillé » (grisé, et pourquoi dans le titre de la colonne)."""
    return [(k, text, k in locked) for k, text in options]


def rows_of(ui: UI, lines: Sequence[Any], values: Callable[[Any], dict[str, Any]],
            tools: Sequence[tuple[str, str]] = (), show_canal: bool = True) -> list[dict[str, Any]]:
    """Les lignes d'un tableau, telles que le gabarit les dessine : qui (à cocher), par où (à cocher), quand, ses
    colonnes (``values(line) -> {clé: valeur}``), ses outils (``tools`` : (nom, lit/agit))."""
    known, instances = people(ui), canal_instances(ui)
    out = []
    for n, a in enumerate(lines, start=1):
        chosen = set(a.tools) if hasattr(a, "tools") else set()
        out.append({
            "n": n, "alone": not a.who and tuple(a.canal) == (INTERNAL,),
            "who": who_choices(a.who, known, ui.names.name_of),
            "canal": canal_choices(a.canal, instances) if show_canal else None,
            "always": not a.when, "when_said": when_words(a.when).capitalize() if a.when else "Toujours",
            "moments": [{"key": k, "label": label, "on": k in a.when} for k, label in MOMENT_CHOICES],
            "values": values(a),
            "all": not chosen, "tools_said": "Tous" if not chosen else f"{len(chosen)} outil{'s' if len(chosen) > 1 else ''}",
            "tools": [{"name": t, "nature": nature, "on": t in chosen} for t, nature in tools],
            "first": n == 1, "last": n == len(lines)})
    return out


def one_page(rows: int) -> Any:
    """La pagination d'un tableau qui tient en une page, dite comme partout."""
    return render._pager(Pager(size=max(1, rows), total=max(1, rows)), {})
