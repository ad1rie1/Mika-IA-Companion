"""Une entrée lisible vers les réglages déclarés, sans charger leurs valeurs : l'annuaire (Réglages › Tous les
réglages) et la recherche dans les réglages (``find``), que la recherche de toute la console reprend.

Chaque page de réglages y a son entrée : celles de Réglages, et celles qui vivent là où l'on se sert de ce qu'elles
règlent (``SettingsPage.home``, ADR 0173, 0206 : Courrier › Paramètres, Teams › Paramètres, Ses sens › Flux suivis…),
dans leur rubrique, sous le nom de leur destination ; une description courte (la première
phrase de ce qu'elle règle, jamais une introduction coupée) ; et ce qu'on y cherche — son titre, son introduction, sa
rubrique, son adresse, le nom et l'aide de chacun de ses champs (``forms.describe`` : des modèles, aucune valeur).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from starlette.requests import Request

from mika.inspector.catalog import Panel, SettingsPage, SettingsSection
from mika.inspector.pages.tabs import TABS
from mika.inspector.ui import PREFIX
from mika.kernel import forms
from mika.kernel.inspect import Param
from mika.kernel.text import fold

#: les pages des facultés (Paramètres avancés › une faculté) : leurs champs sont leurs paramètres
FACULTY_PAGE = "reglages.comportement-"
#: la fin d'une phrase (suivie d'une majuscule : « … son fournisseur. Laisse vide… »)
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-ZÀ-ÖØ-Þ«])")
#: les champs trouvés qu'une entrée nomme, au plus
FIELDS_SHOWN = 3


def first_sentence(text: str) -> str:
    """Sa première phrase, entière : une description courte, jamais coupée au milieu."""
    return _SENTENCE.split(text.strip(), maxsplit=1)[0]


@dataclass(frozen=True, slots=True)
class Entry:
    """Une page de réglages dans l'annuaire."""

    title: str
    group: str
    summary: str
    href: str
    #: ce qu'on y cherche, plié : titre, introduction, rubrique, adresse, nom et aide de ses champs
    text: str
    #: le nom de ses champs, et chacun plié avec son aide (ce qu'une recherche peut y avoir trouvé)
    fields: tuple[tuple[str, str], ...] = ()

    @property
    def advanced(self) -> bool:
        return self.group.startswith("Paramètres avancés")


def _field_texts(fields: Any) -> list[tuple[str, str]]:
    """Le nom et l'aide de chaque champ (ceux d'une entrée de liste compris : le modèle d'un fournisseur)."""
    out: list[tuple[str, str]] = []
    for f in fields:
        if f.kind != "group" and f.label:
            out.append((f.label, fold(f"{f.label} {f.help}")))
        if f.kind in ("records", "mapping"):
            out += _field_texts(f.item)
            out += [(label, fold(label)) for _key, label in f.keys]
    return out


def _form_fields(s: SettingsSection, pg: SettingsPage) -> list[tuple[str, str]]:
    if s.model is None or not pg.form:
        return []
    shown = [f for f in forms.describe(s.model)
             if not any(f.path == e or f.path.startswith(e + ".") for e in s.exclude)
             and (not pg.fields or any(f.path == w or f.path.startswith(w + ".") for w in pg.fields))]
    return _field_texts(shown)


def entries(ui: Any) -> list[Entry]:
    """Toutes les pages de réglages, dans l'ordre de l'annuaire (rubrique, puis page)."""
    settings = getattr(ui, "settings_forms", None)
    form_pages = dict(settings.pages) if settings is not None else {}
    # une page de réglages qui vit ailleurs (Courrier › Paramètres) : sa clé est celle de son onglet là-bas
    by_builtin = {(pg.home.replace("/", ".", 1) if pg.home else f"reglages.{key}"): key
                  for key, (_s, pg) in form_pages.items()}
    ps = ui.deps.parameters
    params = {f.name: f.params for f in ps.faculties()} if ps is not None else {}
    # une page qui vit dans sa destination se nomme par elle (« Teams › Paramètres », « Ses sens › Flux suivis »)
    places = {d.key: d.label for group in ui.deps.navigation for d in group.items}
    out = []
    for item in sorted(ui.builtins.values(), key=lambda b: (b.order, b.title)):
        page = by_builtin.get(item.key)
        if item.key == "reglages.apercu" or (page is None and not item.key.startswith("reglages.")):
            continue
        if page is not None:
            s, pg = form_pages[page]
            rubric = settings.rubrics.get(s.tab)
            group = rubric.title if rubric is not None else ""
            # une page seule dans sa section : la description de la section, écrite courte ; sinon la sienne
            alone = len(settings.pages_of(s)) == 1 and s.description
            summary = first_sentence(s.description if alone else pg.description or s.description)
            title = f"{places.get(pg.home.split('/', 1)[0], s.label)} › {pg.title}" if pg.home else pg.title
            href, fields = settings.url(page), _form_fields(s, pg)
        else:
            group, summary, title = item.group, first_sentence(item.description), item.title
            href = f"{PREFIX}/reglages/{item.slug}"
            owner = item.key.removeprefix(FACULTY_PAGE) if item.key.startswith(FACULTY_PAGE) else ""
            model = params.get(owner)
            fields = _field_texts(forms.describe(model)) if model is not None else []
        text = fold(" ".join((title, item.description, summary, group, href.rsplit("/", 1)[-1])))
        out.append(Entry(title, group or "Autres", summary, href, text, tuple(fields)))
    return out


def find(ui: Any, query: str, among: list[Entry] | None = None) -> list[tuple[Entry, list[str]]]:
    """Les pages de réglages qui répondent à ``query`` (chaque mot, plié, dans le titre, l'introduction, la rubrique,
    l'adresse ou un champ de la page), et le nom des champs où un mot a été trouvé. Vide : toutes les pages.
    ``among`` : les entrées déjà lues (``entries``), pour ne pas les relire."""
    terms = fold(query).split()
    found = []
    for entry in entries(ui) if among is None else among:
        hits = [label for label, folded in entry.fields if any(t in folded for t in terms)]
        if all(t in entry.text or any(t in folded for _l, folded in entry.fields) for t in terms):
            found.append((entry, list(dict.fromkeys(hits))[:FIELDS_SHOWN]))
    return found


@TABS.tab("reglages.apercu", title="Tous les réglages", group="", order=0,
          description="Trouve le bon réglage : personnalité, modèles, connexions ou accès.")
async def directory(ui: Any, request: Request) -> dict[str, Any]:
    query = request.query_params.get("q", "")
    every = entries(ui)
    groups: dict[str, dict[str, Any]] = {}
    found = find(ui, query, every)
    for entry, hits in found:
        group = groups.setdefault(entry.group, {
            "title": entry.group, "id": f"reglages-groupe-{len(groups)}", "items": [], "advanced": entry.advanced,
        })
        group["items"].append({"title": entry.title, "description": entry.summary, "href": entry.href,
                               "fields": hits})
    return {"filters": (Param("q", "Rechercher un réglage", placeholder="ex. voix, modèle, boîte, mémoire"),),
            "panel": Panel("handmade/reglages/annuaire.html", {
                "settings_groups": list(groups.values()), "settings_count": len(found), "settings_total": len(every),
                "settings_search": bool(fold(query).split()),
            })}
