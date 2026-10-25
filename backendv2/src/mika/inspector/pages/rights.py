"""Réglages › Droits (ADR 0133) : qui peut quoi, lu des types de règles que chaque propriétaire déclare
(``Faculty.rights``) — jamais une recopie.

- ``tables`` : chaque tableau de règles, par ressource (un service, un projet, ce qu'elle envoie), en mots ;
- ``grants`` : ce qu'une audience aurait à un moment, et la ligne qui en décide.

La page dessinée (``app/handmade/rights.py``) les montre par personne et par ressource ; l'onglet lui-même rend les
tableaux en blocs, son repli.
"""

from __future__ import annotations

from typing import Any

from starlette.requests import Request

from mika.inspector.pages import canals as canals_page
from mika.inspector.pages import families as families_page
from mika.inspector.pages.tabs import TABS
from mika.kernel.inspect import Block, Note, Ref, Table
from mika.kernel.rights import Grant, RightsSpec, RuleTable, why_words
from mika.runtime.boundary import Failed, call
from mika.runtime.tools import allowed, gate_of
from mika.vocab.access import (
    INTERNAL,
    KEEP_WORDS,
    NO,
    POLICY_WORDS,
    REPLY_WORDS,
    STEER_WORDS,
    TALKING,
    canal_key,
    canal_words,
    when_words,
    who_words,
)
from mika.vocab.canals import Canals, canal_verdict


def _ran(ui: Any, spec: RightsSpec, fn: Any, *args: Any) -> list[Any]:
    """Ce qu'un type de règles rend (une panne tait ce type, jamais la page : elle est au journal)."""
    frame = ui.kernel.mind.frame()
    ctx = ui.inspection.context(when=ui.when)
    got = call(fn, frame.state(spec.owner), frame, ctx, *args, label=f"droits {spec.key}")
    return [] if isinstance(got, Failed) or got is None else list(got)


#: les deux sortes de tableaux de l'application (ADR 0134), avant ceux des facultés : les canaux, ses propres outils
CANALS_SPEC = RightsSpec("app", "canaux", "Canaux", "Par où ça lui arrive, et ce que chaque canal laisse passer au "
                         "plus : la première porte (ADR 0134).", tables=None, grants=None, order=0)
FAMILIES_SPEC = RightsSpec("app", "familles", "Ses propres outils", "Ses outils internes, famille par famille : "
                           "nés du minimum vital que le code déclare, modifiables (ADR 0134).", tables=None,
                           grants=None, order=1)
CANAL_COLUMNS = ("qui", "quand", "répondre", "préparer", "outils : lecture / action", "projets", "fichiers", "garde")
FAMILY_COLUMNS = ("qui", "par où", "quand", "lecture", "action", "garde", "outils")


def _canal_row(a: Any, ui: Any) -> tuple[str, ...]:
    return (who_words(a.who, ui.names.name_of) if a.who else ("—" if tuple(a.canal) == (INTERNAL,)
                                                                         else "Comportement par défaut"),
            when_words(a.when) if a.who else "—", REPLY_WORDS.get(a.reply, a.reply), "oui" if a.prepare else "non",
            f"{POLICY_WORDS.get(a.read, a.read)} / {POLICY_WORDS.get(a.act, a.act)}",
            STEER_WORDS.get(a.steer, a.steer), "oui" if a.files else "non", KEEP_WORDS.get(a.keep, a.keep))


def canal_tables(ui: Any) -> list[RuleTable]:
    return [RuleTable(f"canal:{e['key']}", f"Le canal « {e['label']} »", CANAL_COLUMNS,
                      tuple(_canal_row(a, ui) for a in e["table"].lines), _canal_row(e["table"].default, ui),
                      href=Ref("local", f"{canals_page.BASE}?canal={e['key']}", "Réglages › Canaux"),
                      floors=canals_page.FLOORS,
                      note="" if e["set"] else "Son minimum vital, tant qu'on ne l'a pas réglé.")
            for e in canals_page.entries(ui)]


def _family_row(a: Any, ui: Any) -> tuple[str, ...]:
    return (who_words(a.who, ui.names.name_of) if a.who else ("—" if tuple(a.canal) == (INTERNAL,)
                                                                         else "Comportement par défaut"),
            canal_words(a.canal), when_words(a.when) if a.who else "—", POLICY_WORDS.get(a.read, a.read),
            POLICY_WORDS.get(a.act, a.act), KEEP_WORDS.get(a.keep, a.keep), "tous" if not a.tools else ", ".join(a.tools))


def family_tables(ui: Any) -> list[RuleTable]:
    return [RuleTable(f"famille:{e['key']}", f"Ses outils « {e['label']} »", FAMILY_COLUMNS,
                      tuple(_family_row(a, ui) for a in e["lines"]), _family_row(e["default"], ui),
                      href=Ref("local", f"{families_page.BASE}?famille={e['key']}", "Ses propres outils"),
                      floors=families_page.FLOORS,
                      note="" if e["set"] else "Son minimum vital, tel que le code le déclare.")
            for e in families_page.entries(ui)]


def canal_grants(ui: Any, audience: Any, kind: str) -> list[Grant]:
    """Ce que le canal par où cette audience arrive laisse au plus, et la ligne qui en décide."""
    rights, close = gate_of(ui.kernel.registry, ui.kernel.mind.frame())
    got = canal_verdict(rights.canals or Canals(), audience, kind, close=close)
    if got is None:
        return []
    line, key = got
    a = line.line
    label = next((e["label"] for e in canals_page.entries(ui) if e["key"] == key), key)
    talking = canal_key(key)[0] in TALKING
    what = (("répondre", REPLY_WORDS.get(a.reply, a.reply)),) if talking else (
        ("préparer d'elle-même", "oui" if a.prepare else "non"), ("comment ça part", REPLY_WORDS.get(a.reply, a.reply)))
    if talking:
        what += (("outils : lecture", POLICY_WORDS.get(a.read, a.read)), ("outils : action", POLICY_WORDS.get(a.act, a.act)),
                 ("projets", STEER_WORDS.get(a.steer, a.steer)), ("fichiers", "oui" if a.files else "non"),
                 ("garde", KEEP_WORDS.get(a.keep, a.keep)))
    return [Grant(f"canal:{key}", f"Le canal « {label} »", what, why_words(line.index),
                  href=Ref("local", f"{canals_page.BASE}?canal={key}", "Réglages › Canaux"),
                  closed=a.reply == "non" and a.read == "non" and a.act == "non" and a.steer == "non")]


def family_grants(ui: Any, audience: Any, kind: str) -> list[Grant]:
    """Ce qu'elle fait de chacun de ses propres outils devant cette audience, à ce moment (les deux portes)."""
    registry = ui.kernel.registry
    rights, close = gate_of(registry, ui.kernel.mind.frame())
    out = []
    for spec in sorted(registry.tools.values(), key=lambda t: (t.bundle, t.name)):
        if registry.is_dynamic(spec.name) or kind not in spec.episodes:
            continue
        got = allowed(registry.tools, spec, audience, kind, rights, close)
        if got is None:
            continue
        out.append(Grant(f"famille:{spec.bundle}", f"{ui.names.bundle(spec.bundle)} · {spec.name}",
                         (("agit" if spec.acts else "lit", POLICY_WORDS.get(got.level, got.level)),
                          ("garde", KEEP_WORDS.get(got.keep, got.keep) if got.level != NO and spec.outside else "—")),
                         got.why, href=Ref("local", f"{families_page.BASE}?famille={spec.bundle}", "Ses propres outils"),
                         closed=got.level == NO))
    return out


def tables(ui: Any) -> list[tuple[RightsSpec, list[RuleTable]]]:
    """Chaque type de règles et ses tableaux : les canaux et ses propres outils (l'application), puis ceux que les
    facultés déclarent, dans leur ordre."""
    mine = [(CANALS_SPEC, canal_tables(ui)), (FAMILIES_SPEC, family_tables(ui))]
    return [*mine, *((spec, _ran(ui, spec, spec.tables)) for spec in ui.kernel.registry.rights)]


def grants(ui: Any, audience: Any, kind: str) -> list[tuple[RightsSpec, list[Grant]]]:
    """Ce que chaque type de règles accorde à cette audience, à ce moment : le canal par où elle arrive, ses propres
    outils, puis ce que les facultés déclarent."""
    mine = [(CANALS_SPEC, canal_grants(ui, audience, kind)), (FAMILIES_SPEC, family_grants(ui, audience, kind))]
    return [*mine, *((spec, _ran(ui, spec, spec.grants, audience, kind)) for spec in ui.kernel.registry.rights
                     if spec.grants is not None)]


@TABS.tab("reglages.droits", title="Droits", group="Droits", order=2500,
          description="Qui peut quoi : les services, les projets et leurs apps, ce qu'elle envoie à ta place — par "
                      "personne et par ressource, avec la ligne qui en décide.")
async def rights_page(ui: Any, request: Request) -> Any:
    blocks: list[Block] = []
    for _spec, found in tables(ui):
        for t in found:
            rows = tuple((str(i), *r) for i, r in enumerate(t.rows, start=1)) + (("", *t.default),)
            blocks.append(Table(("#", *t.columns), rows, title=t.title,
                                caption=" · ".join(("ce qu'aucune ligne n'ouvre : " + " ; ".join(t.floors),)
                                                   if t.floors else ()) + (f" {t.note}" if t.note else "")))
    return {"blocks": blocks or [Note("Aucune règle déclarée.", tone="muted")]}
