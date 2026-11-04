"""Outils, pour qui est connecté (ADR 0187) : ce que Mika fait de chacun de ses outils **pour elle**, par chaque canal
(le chat web, en privé ou dans un salon, l'app Android, Teams, le courrier) et à chaque moment (quand elle lui répond,
quand elle lui parle d'elle-même), et seule quand elle travaille.

Chaque case est la décision même de la porte d'offre (``runtime.tools.judge`` : les deux portes, le plafond, la
condition d'un outil, une ressource à son nom), jamais une recopie ; pour un service ou une app de la Forge, la ligne de
leurs accès, telle que leur faculté la déclare (``RightsSpec.grants``). Ses ressources s'y rangent : ses propres
outils, famille par famille ; ses comptes (chaque boîte, chaque compte Teams, avec la règle de son canal — qui,
préparer d'elle-même, comment ça part) ; les services et les apps qu'au moins une case lui ouvre. Rien n'y dit les
droits d'une autre personne : les lignes d'une famille ne se montrent pas, seulement ses cases à elle, et pourquoi.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from starlette.routing import Route

from mika.app.console import LABELS
from mika.app.moi import Call, Me, MeApi
from mika.app.moi import mail as mail_moi
from mika.app.moi import teams as teams_moi
from mika.contracts import identity as identity_c
from mika.contracts import self_ as self_c
from mika.inspector.names import Names
from mika.inspector.pages.tools import condition
from mika.kernel.frame import Audience
from mika.runtime.boundary import Failed, call
from mika.runtime.inspection import Inspection
from mika.runtime.tools import FITS, NEEDS, WHEN, Judged, gate_of, judge
from mika.vocab.access import (
    ALONE,
    INTERNAL,
    KEEP_WORDS,
    MAIL,
    MOBILE,
    NO,
    POLICY_WORDS,
    PRIVATE,
    REPLY_WORDS,
    SOURCE_WORDS,
    SOURCE_WORDS_OTHER,
    TEAMS,
    TOGETHER,
    WEB,
    canal_key,
    when_words,
    who_words,
)
from mika.vocab.canals import Canals
from mika.vocab.episodes import Kind
from mika.vocab.privacy import ChannelTrust

#: les canaux de la matrice, dans l'ordre de ses colonnes : (clé, canal du moteur, libellé)
CANALS: tuple[tuple[str, str, str], ...] = (
    ("web", f"{WEB}:{PRIVATE}", "Chat web"), ("salon", f"{WEB}:{TOGETHER}", "Un salon"),
    ("mobile", MOBILE, "App Android"), ("teams", TEAMS, "Teams"), ("courrier", MAIL, "Courrier"),
    ("seule", INTERNAL, "Elle seule"))
#: les moments : quand elle te répond, quand elle te parle d'elle-même ; seule, quand elle travaille
MOMENTS: tuple[tuple[str, str, str], ...] = (
    ("reply", Kind.REPLY, "quand elle te répond"), ("initiative", Kind.INITIATIVE, "quand elle te parle d'elle-même"))
WORK = ("work", Kind.WORK, "quand elle travaille seule")
#: elle travaille seule : personne n'écoute (la règle de la console, ``app/handmade/rights.py``)
WORKING = Audience(persons=(), channel="internal", public=False, trust=ChannelTrust.INTERNAL.value, owner=True)
#: les mots d'une ligne, rendus à leur code
POLICY_CODES = {v: k for k, v in POLICY_WORDS.items()}
KEEP_CODES = {v: k for k, v in KEEP_WORDS.items()}
#: pourquoi un outil est fermé avant ses lignes
REASONS = {NEEDS: "son service n'est pas configuré", FITS: "les accès de sa ressource ne te l'ouvrent pas"}
#: les sortes de ressources que les facultés déclarent et que la matrice montre : (clé du type de règles, groupe)
OUTSIDE = (("services", "services"), ("apps", "apps"))


def audience_of(me: Me, canal: str) -> Audience:
    """L'audience de la personne connectée par ce canal, telle que le pipeline la lirait : par le chat web ou l'app
    Android, sa session la prouve ; par Teams ou le courrier, un moyen relié à elle ; dans un salon, personne n'est
    reconnu, même elle ; elle seule, personne n'écoute."""
    kind, instance = canal_key(canal)
    if kind == INTERNAL:
        return WORKING
    together = instance == TOGETHER
    channel = {WEB: "web", MOBILE: "mobile", TEAMS: "teams", MAIL: "email"}[kind]
    trust = ChannelTrust.AUTHENTICATED if kind in (WEB, MOBILE) else ChannelTrust.ACCOUNT
    if together:
        trust = ChannelTrust.PUBLIC
    return Audience(persons=(me.handle,), channel=channel, room="salon" if together else None, public=together,
                    trust=trust.value, owner=me.owner and not together, person=me.person)


def situations(me: Me) -> list[tuple[str, str, Audience, str]]:
    """Chaque case de la matrice : (canal, moment, audience, sorte d'épisode)."""
    out = []
    for key, canal, _label in CANALS:
        if canal == INTERNAL:
            out.append((key, WORK[0], WORKING, WORK[1]))
            continue
        audience = audience_of(me, canal)
        out.extend((key, moment, audience, kind) for moment, kind, _ in MOMENTS)
    return out


def _cell(got: Judged | None, spec: Any) -> dict[str, Any] | None:
    """Une case : ce qu'elle fait de l'outil (``seule``, ``carte`` — elle te demande —, ``toi`` — ton accord —,
    ``non``), ce qu'elle en garde et pourquoi ; ``None`` : il ne sert pas à ce moment."""
    if got is None:
        return None
    if got.reason:
        why = condition(spec) if got.reason == WHEN else REASONS.get(got.reason, "")
        return {"level": NO, "keep": "rien", "why": why, "reason": got.reason, "owned": False}
    if got.owned:
        return {"level": ALONE, "keep": got.keep, "why": "une ressource à ton nom (ADR 0185)", "reason": "",
                "owned": True}
    if spec.fits is not None:  # gardé par sa condition, pas par des lignes : offert, il sert tel qu'il l'a dit
        return {"level": ALONE if got.offered else NO, "keep": "public" if got.offered else "rien",
                "why": condition(spec), "reason": "", "owned": False}
    return {"level": got.level, "keep": got.keep if got.level != NO else "rien", "why": got.why, "reason": "",
            "owned": False}


def _grant_cell(g: Any) -> dict[str, Any]:
    """Une case lue de la ligne d'une ressource d'ailleurs (un service, une app) : ses mots rendus à leur code."""
    said = dict(g.what)
    level = next((POLICY_CODES.get(v, NO) for k, v in said.items() if k in ("lit", "agit")), NO)
    keep = KEEP_CODES.get(str(said.get("garde", "")), "rien")
    return {"level": level, "keep": keep if level != NO else "rien", "why": g.why, "reason": "", "owned": False}


def _rule_json(line: Any, name: Callable[[str], str], her: str, sources: Mapping[str, str]) -> dict[str, Any]:
    """Une ligne de la règle d'un de tes comptes, en mots : qui, quand, préparer d'elle-même, comment ça part."""
    return {"who": who_words(line.who, name, her, sources) if line.who else "", "when": when_words(line.when),
            "prepare": bool(line.prepare), "reply": line.reply, "reply_words": REPLY_WORDS.get(line.reply, line.reply)}


def _rules(canals: Any, key: str, name: Callable[[str], str], her: str, sources: Mapping[str, str]) -> dict[str, Any]:
    table = canals.table(key)
    return {"canal": key, "set": key in canals.tables,
            "lines": [_rule_json(a, name, her, sources) for a in table.lines],
            "default": _rule_json(table.default, name, her, sources)}


async def matrix(call_: Call) -> dict[str, Any]:
    kernel, me = call_.kernel, call_.me
    registry, frame = kernel.registry, call_.frame
    rights, close = gate_of(registry, frame)
    names = Names(kernel, LABELS)
    places = situations(me)
    tools = registry.tools

    # ses propres outils : la porte, outil par outil, case par case
    families: dict[str, list[dict[str, Any]]] = {}
    for spec in sorted(tools.values(), key=lambda s: (s.bundle, s.name)):
        if registry.is_dynamic(spec.name):
            continue
        cells = {f"{c}/{m}": _cell(judge(tools, spec, aud, kind, rights, close, frame, kernel.ports), spec)
                 for c, m, aud, kind in places}
        families.setdefault(spec.bundle, []).append(
            {"name": spec.name, "description": spec.description, "acts": spec.acts, "cells": cells})

    # ce qui vient d'ailleurs : la ligne de son service ou de son app, telle que sa faculté la déclare
    ctx = Inspection(kernel).context()
    outside: dict[str, dict[str, dict[str, Any]]] = {group: {} for _key, group in OUTSIDE}
    offered = {(t.server, t.remote): t for t in (kernel.ports["mcp"].offered() if kernel.ports.get("mcp") else ())}
    specs = {s.key.rsplit(".", 1)[-1]: s for s in registry.rights if s.grants is not None}
    for sort, group in OUTSIDE:
        rspec = specs.get(sort)
        if rspec is None:
            continue
        for c, m, aud, kind in places:
            got = call(rspec.grants, frame.state(rspec.owner), frame, ctx, aud, kind, label=f"droits {rspec.key}")
            for g in [] if isinstance(got, Failed) or got is None else got:
                tool, resource = _outside_tool(sort, g, offered)
                if not tool or tool not in tools:
                    continue
                entry = outside[group].setdefault(resource, {})
                row = entry.setdefault(tool, {"name": tool, "description": tools[tool].description,
                                              "acts": tools[tool].acts, "cells": {}})
                judged = judge(tools, tools[tool], aud, kind, rights, close, frame, kernel.ports)
                row["cells"][f"{c}/{m}"] = _grant_cell(g) if judged is not None and judged.offered else \
                    _cell(judged, tools[tool])

    her = self_c.name_of(frame.get(self_c.PERSONA))
    name = _person_name(frame)
    # « toi » n'est toi que pour une de ses propriétaires : aux autres, la ligne dit « ses propriétaires »
    sources = SOURCE_WORDS if me.owner else SOURCE_WORDS_OTHER
    canals = rights.canals or Canals()
    groups = [
        {"key": "families", "title": "Ses propres outils", "resources": [
            {"key": f"famille:{b}", "title": names.bundle(b), "description": registry.bundles.get(b, ""),
             "tools": rows} for b, rows in sorted(families.items(), key=lambda kv: names.bundle(kv[0]).casefold())
            if not b.startswith(("mcp.", "forge_apps."))]},
        {"key": "accounts", "title": "Tes comptes", "resources": [
            *({"key": f"courrier:{key}", "kind": "mail", "title": a.name, "address": a.address,
               "family": "famille:email", "rules": _rules(canals, f"{MAIL}:{key}", name, her, sources)}
              # les siennes seulement : la règle d'une boîte qu'on lui partage est l'affaire de son propriétaire
              for key, (a, level) in mail_moi.boxes(call_).items() if level == mail_moi.OWN),
            *({"key": f"teams:{key}", "kind": "teams", "title": a.name, "family": "famille:teams",
               "rules": _rules(canals, f"{TEAMS}:{key}", name, her, sources)}
              for key, (a, level) in teams_moi.accounts(call_).items() if level == teams_moi.OWN)]},
        *({"key": group, "title": "Services" if group == "services" else "Apps de la Forge", "resources": [
            {"key": resource, "title": _outside_title(resource), "tools": list(rows.values())}
            for resource, rows in sorted(outside[group].items()) if _opens(rows.values())]}
          for _sort, group in OUTSIDE),
    ]
    return {"canals": [{"key": k, "label": label} for k, _c, label in CANALS],
            "moments": [{"key": k, "label": label} for k, _kind, label in (*MOMENTS, WORK)], "groups": groups}


def _outside_tool(sort: str, g: Any, offered: Mapping[tuple[str, str], Any]) -> tuple[str, str]:
    """(l'outil chez elle, sa ressource) d'une ligne d'ailleurs : un service (« « meteo » · echo »), une app (son
    nom même)."""
    if sort == "services":
        server, remote = g.resource.partition(":")[2], g.title.rsplit(" · ", 1)[-1]
        found = offered.get((server, remote))
        return (found.name if found is not None else ""), g.resource
    return g.title, g.resource


def _outside_title(resource: str) -> str:
    kind, _, key = resource.partition(":")
    return {"mcp": f"Service « {key} »", "forge": f"App « {key} »", "project": f"Projet n° {key}"}.get(kind, resource)


def _opens(rows: Iterable[Mapping[str, Any]]) -> bool:
    """Au moins une case de ses outils s'ouvre à la personne : sinon, ce service n'est pas pour elle."""
    return any(cell is not None and cell["level"] != NO for row in rows for cell in row["cells"].values())


def _person_name(frame: Any) -> Callable[[str], str]:
    def name(key: str) -> str:
        view = frame.get(identity_c.IDENTITY(key))
        return getattr(view, "name", "") or key

    return name


def routes(api: MeApi) -> list[Route]:
    return [api.route("/rights", matrix)]
