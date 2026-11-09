"""Outils, pour qui est connecté (ADR 0187) : ce que Mika fait de chacun de ses outils **pour elle**, par chaque canal
(le chat web, en privé ou dans un salon, l'app Android, Teams, le courrier) et à chaque moment (quand elle lui répond,
quand elle lui parle d'elle-même), et seule quand elle travaille.

Chaque case est la décision même de la porte d'offre (``runtime.tools.judge`` : les deux portes, le plafond, la
condition d'un outil, une ressource à son nom), jamais une recopie ; pour un service ou une app de la Forge, la ligne de
leurs accès, telle que leur faculté la déclare (``RightsSpec.grants``). Ses ressources s'y rangent : ses propres
outils, famille par famille, chacun nommé pour elle (``label``, ADR 0208) ; ses comptes (chaque boîte, chaque compte
Teams, avec la règle qui vaut pour son canal — qui, préparer d'elle-même, comment ça part) ; les services et les apps
qu'au moins une case lui ouvre (un service qu'une personne a branché, avec son but ; jamais la ligne du catalogue d'un
service de Mika, écrite pour elle). Rien n'y dit les droits d'une autre personne : les lignes d'une famille
ne se montrent pas, seulement ses cases à elle, et pourquoi — la part de la ligne qui la concerne, en mots (``said_to``,
ADR 0209) ; le numéro de la ligne et la page de la console où elle se lit, seulement à une opératrice.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any
from urllib.parse import urlencode

from starlette.routing import Route

from mika.app.console import LABELS
from mika.app.moi import mail as mail_moi
from mika.app.moi import teams as teams_moi
from mika.app.moi.api import Call, Me, MeApiBase
from mika.app.moi.common import OWN
from mika.contracts import forge as forge_c
from mika.contracts import identity as identity_c
from mika.contracts import self_ as self_c
from mika.inspector.names import Names
from mika.inspector.pages.accounts import RIGHTS
from mika.inspector.pages.tools import condition
from mika.kernel.frame import Audience
from mika.runtime.boundary import Failed, call
from mika.runtime.inspection import Inspection
from mika.runtime.tools import FITS, NEEDS, WHEN, Judged, allowed, gate_of, judge
from mika.vocab.access import (
    ACCOUNT,
    ALONE,
    AT_OWNER,
    CLOSE,
    EVERYONE,
    INTERNAL,
    KEEP_WORDS,
    MAIL,
    MOBILE,
    NO,
    OWNER,
    PERSON,
    POLICY_WORDS,
    PRIVATE,
    REPLY_WORDS,
    SOURCE_WORDS,
    SOURCE_WORDS_OTHER,
    TEAMS,
    TOGETHER,
    WEB,
    Canal,
    canal_key,
    situation,
    when_words,
    who_words,
)
from mika.vocab.access import WORK as AT_WORK
from mika.vocab.canals import Canals
from mika.vocab.episodes import Kind
from mika.vocab.privacy import ChannelTrust
from mika.vocab.rights import Allowance, tool_allowance

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
#: pourquoi un outil s'ouvre quand une de ses ressources est à toi (``owned``, ADR 0185 ; un partage aussi, ADR 0188)
OWNED = "une boîte ou un compte à ton nom, ou qu'on te partage"
#: le canal par où ça arrive a serré ce que la ligne laissait (``Allowance.narrowed``), dit à la personne
NARROWED = "ce canal le restreint"
#: une case d'ailleurs dont on ne sait pas redire la ligne (une app) : ses accès, en mots
OUTSIDE_WHY = {"services": "les accès de ce service", "apps": "les accès de cette app"}
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


def _cell(got: Judged | None, spec: Any, said: str = "", line: str = "") -> dict[str, Any] | None:
    """Une case : ce qu'elle fait de l'outil (``seule``, ``carte`` — elle te demande —, ``toi`` — ton accord —,
    ``non``), ce qu'elle en garde et pourquoi ; ``None`` : il ne sert pas à ce moment. Décidée par ses lignes, son
    pourquoi est ``said`` (la part de la ligne qui te concerne) et ``line`` la ligne même, pour une opératrice."""
    if got is None:
        return None
    if got.reason:
        why = condition(spec) if got.reason == WHEN else REASONS.get(got.reason, "")
        return {"level": NO, "keep": "rien", "why": why, "line": "", "reason": got.reason, "owned": False}
    if got.owned:
        return {"level": ALONE, "keep": got.keep, "why": OWNED, "line": "", "reason": "", "owned": True}
    if spec.fits is not None:  # gardé par sa condition, pas par des lignes : offert, il sert tel qu'il l'a dit
        return {"level": ALONE if got.offered else NO, "keep": "public" if got.offered else "rien",
                "why": condition(spec), "line": "", "reason": "", "owned": False}
    return {"level": got.level, "keep": got.keep if got.level != NO else "rien", "why": said, "line": line,
            "reason": "", "owned": False}


def _grant_cell(g: Any, said: Callable[[str], str], line: str) -> dict[str, Any]:
    """Une case lue de la ligne d'une ressource d'ailleurs (un service, une app) : ses mots rendus à leur code ;
    ``said`` : son pourquoi, d'après ce qu'elle fait de l'outil."""
    words = dict(g.what)
    level = next((POLICY_CODES.get(v, NO) for k, v in words.items() if k in ("lit", "agit")), NO)
    keep = KEEP_CODES.get(str(words.get("garde", "")), "rien")
    return {"level": level, "keep": keep if level != NO else "rien", "why": said(level), "line": line, "reason": "",
            "owned": False}


def said_to(got: Allowance | None, acts: bool, audience: Audience, kind: str, close: Callable[[str], bool] | None,
            sources: Mapping[str, str]) -> str:
    """Pourquoi une case, dit à la personne (ADR 0209) : la part de la ligne qui décide qui la concerne — qui la
    désigne, et quand (« tout le monde, quand elle répond », « toi, toujours ») ; « par défaut : personne » quand
    aucune ne la désigne — puis le canal ou le plafond, s'ils ont serré. Jamais son numéro (un tableau qu'elle ne voit
    pas), ni les autres personnes que la ligne nomme."""
    if got is None:
        return ""
    line, where = got.resource.line, situation(audience, kind)
    if got.resource.by_default:
        opened = getattr(line, "act" if acts else "read", NO) != NO
        said = "par défaut : " + (("elle seule" if where == AT_WORK else sources[EVERYONE]) if opened else "personne")
    elif where == AT_WORK:
        said = "elle seule, quand elle travaille"
    else:
        said = f"{_who_for(tuple(getattr(line, 'who', ())), where, audience, close, sources)}, " \
               f"{when_words(getattr(line, 'when', ()))}"
    if got.narrowed:
        said += f" — {NARROWED}"
    if got.capped and got.ceiling.why:
        said += f" — {got.ceiling.why}"
    return said


def _who_for(who: tuple[str, ...], where: str | None, audience: Audience, close: Callable[[str], bool] | None,
             sources: Mapping[str, str]) -> str:
    """Ce qui, dans une ligne qui la désigne, la désigne elle, le plus précis d'abord : toi (une de ses propriétaires,
    ou ta personne par son nom), ses proches, tout le monde (une ligne sans personne aussi)."""
    person = audience.person or ""
    if (where == AT_OWNER and OWNER in who) or (where == ACCOUNT and person and PERSON + person in who):
        return SOURCE_WORDS[OWNER]
    if where == ACCOUNT and CLOSE in who and close is not None and person and close(person):
        return sources[CLOSE]
    return sources[EVERYONE]


def _rule_json(line: Any, name: Callable[[str], str], her: str, sources: Mapping[str, str]) -> dict[str, Any]:
    """Une ligne de la règle d'un de tes comptes, en mots : qui, quand, préparer d'elle-même, comment ça part."""
    return {"who": who_words(line.who, name, her, sources) if line.who else "", "when": when_words(line.when),
            "prepare": bool(line.prepare), "reply": line.reply, "reply_words": REPLY_WORDS.get(line.reply, line.reply)}


def _rules(canals: Any, key: str, name: Callable[[str], str], her: str, sources: Mapping[str, str]) -> dict[str, Any]:
    """La règle qui vaut pour un de tes comptes, telle que le courrier et Teams la lisent (``Canals.table_of``) : la
    sienne si elle est réglée (``set``), sinon celle de tout son canal (``common``, réglée dans la console), sinon le
    minimum vital."""
    kind, instance = canal_key(key)
    table, used = canals.table_of(Canal(kind, instance))
    return {"canal": key, "set": used == key, "common": used == kind and kind in canals.tables,
            "lines": [_rule_json(a, name, her, sources) for a in table.lines],
            "default": _rule_json(table.default, name, her, sources)}


async def matrix(call_: Call) -> dict[str, Any]:
    kernel, me = call_.kernel, call_.me
    registry, frame = kernel.registry, call_.frame
    rights, close = gate_of(registry, frame)
    names = Names(kernel, LABELS)
    places = situations(me)
    tools = registry.tools
    # « toi » n'est toi que pour une de ses propriétaires : aux autres, la ligne dit « ses propriétaires »
    sources = SOURCE_WORDS if me.owner else SOURCE_WORDS_OTHER

    def own(spec: Any, aud: Audience, kind: str) -> dict[str, Any] | None:
        """La case d'un de ses outils : la porte la décide ; décidée par ses lignes, la même lecture (``allowed``) en
        dit la ligne, en mots pour toi, et telle quelle pour une opératrice."""
        got = judge(tools, spec, aud, kind, rights, close, frame, kernel.ports)
        if got is None or got.reason or got.owned or spec.fits is not None:
            return _cell(got, spec)
        said = said_to(allowed(tools, spec, aud, kind, rights, close), spec.acts, aud, kind, close, sources)
        return _cell(got, spec, said, got.why if me.operator else "")

    # ses propres outils : la porte, outil par outil, case par case
    families: dict[str, list[dict[str, Any]]] = {}
    for spec in sorted(tools.values(), key=lambda s: (s.bundle, s.name)):
        if registry.is_dynamic(spec.name):
            continue
        cells = {f"{c}/{m}": own(spec, aud, kind) for c, m, aud, kind in places}
        families.setdefault(spec.bundle, []).append(
            {"name": spec.name, "label": spec.label, "description": spec.description, "acts": spec.acts,
             "cells": cells})

    # ce qui vient d'ailleurs : la ligne de son service ou de son app, telle que sa faculté la déclare
    ctx = Inspection(kernel).context()
    outside: dict[str, dict[str, dict[str, Any]]] = {group: {} for _key, group in OUTSIDE}
    port = kernel.ports.get("mcp")
    offered = {(t.server, t.remote): t for t in (port.offered() if port else ())}
    statuses = {st.name: st for st in (port.statuses() if port else ())}
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
                spec = tools[tool]
                row = entry.setdefault(tool, {"name": tool, "label": spec.label, "description": spec.description,
                                              "acts": spec.acts, "cells": {}})
                judged = judge(tools, spec, aud, kind, rights, close, frame, kernel.ports)
                if judged is None or not judged.offered:
                    row["cells"][f"{c}/{m}"] = _cell(judged, spec)
                    continue
                mirror = _service_allowance(g, offered, statuses, aud, kind, rights, close) if sort == "services" \
                    else None

                def said(level: str, g: Any = g, mirror: Allowance | None = mirror, aud: Audience = aud,
                         kind: str = kind, acts: bool = spec.acts, sort: str = sort) -> str:
                    # la ligne redite seulement si c'est bien celle qui a décidé ; sinon, ses accès en mots
                    if mirror is not None and mirror.why == g.why:
                        return said_to(mirror, acts, aud, kind, close, sources)
                    return f"{OUTSIDE_WHY[sort]} " + ("ne te l'ouvrent pas" if level == NO else "te l'ouvrent")

                row["cells"][f"{c}/{m}"] = _grant_cell(g, said, g.why if me.operator else "")

    her = self_c.name_of(frame.get(self_c.PERSONA))
    name = _person_name(frame)
    canals = rights.canals or Canals()
    apps = {a.name: a for a in frame.get(forge_c.APPS) or ()}
    # la page de la console où se lit le tableau d'une ressource : seulement pour une opératrice
    href = (lambda key: f"{RIGHTS}?{urlencode({'detail': key})}") if me.operator else (lambda _key: "")
    groups = [
        {"key": "families", "title": "Ses propres outils", "resources": [
            {"key": f"famille:{b}", "title": names.bundle(b), "description": registry.bundles.get(b, ""),
             "href": href(f"famille:{b}"), "tools": rows}
            for b, rows in sorted(families.items(), key=lambda kv: names.bundle(kv[0]).casefold())
            if not b.startswith(("mcp.", "forge_apps."))]},
        {"key": "accounts", "title": "Tes comptes", "resources": [
            *({"key": f"courrier:{key}", "kind": "mail", "title": a.name, "address": a.address,
               "family": "famille:email", "rules": _rules(canals, f"{MAIL}:{key}", name, her, sources)}
              # les siennes seulement : la règle d'une boîte qu'on lui partage est l'affaire de son propriétaire
              for key, (a, level) in mail_moi.boxes(call_).items() if level == OWN),
            *({"key": f"teams:{key}", "kind": "teams", "title": a.name, "family": "famille:teams",
               "rules": _rules(canals, f"{TEAMS}:{key}", name, her, sources)}
              for key, (a, level) in teams_moi.accounts(call_).items() if level == OWN)]},
        *({"key": group, "title": "Services" if group == "services" else "Apps de la Forge", "resources": [
            {"key": resource, "title": _outside_title(resource, apps),
             "description": _outside_about(resource, statuses), "href": href(resource), "tools": list(rows.values())}
            for resource, rows in sorted(outside[group].items()) if _opens(rows.values())]}
          for _sort, group in OUTSIDE),
    ]
    return {"canals": [{"key": k, "label": label} for k, _c, label in CANALS],
            "moments": [{"key": k, "label": label} for k, _kind, label in (*MOMENTS, WORK)], "groups": groups}


def _outside_tool(sort: str, g: Any, offered: Mapping[tuple[str, str], Any]) -> tuple[str, str]:
    """(l'outil chez elle, sa ressource) d'une ligne d'ailleurs : un service (« « meteo » · echo »), une app (son
    nom même)."""
    if sort == "services":
        found = offered.get(_served(g))
        return (found.name if found is not None else ""), g.resource
    return g.title, g.resource


def _served(g: Any) -> tuple[str, str]:
    """(son service, son outil là-bas) d'une ligne d'un service : sa ressource (``mcp:<service>``), son titre."""
    return g.resource.partition(":")[2], g.title.rsplit(" · ", 1)[-1]


def _service_allowance(g: Any, offered: Mapping[tuple[str, str], Any], statuses: Mapping[str, Any],
                       aud: Audience, kind: str, rights: Any, close: Callable[[str], bool] | None) -> Allowance | None:
    """La lecture même des lignes de son service (``tool_allowance``, comme sa faculté la fait), pour en redire la
    ligne : ``None`` sans le service ou l'outil."""
    server, remote = _served(g)
    status, found = statuses.get(server), offered.get((server, remote))
    if status is None or found is None:
        return None
    return tool_allowance(status.access, status.default, aud, kind, found.nature != "lecture", rights,
                          lambda a: a.concerns(remote), close=close, outside=True)


def _outside_title(resource: str, apps: Mapping[str, Any]) -> str:
    """Le nom d'une ressource d'ailleurs : un service par son nom, une app par son titre quand elle en a un."""
    kind, _, key = resource.partition(":")
    if kind == "forge":
        app = apps.get(key)
        return f"App « {app.title if app is not None and app.title else key} »"
    return {"mcp": f"Service « {key} »", "project": f"Projet n° {key}"}.get(kind, resource)


def _outside_about(resource: str, statuses: Mapping[str, Any]) -> str:
    """À quoi sert un service qu'une personne a branché (``owner``, ADR 0192), tel qu'elle l'a dit (``purpose``) :
    Paramètres le montre déjà à elle et à qui elle le partage. Rien pour un service de Mika (sans propriétaire : réglé
    dans la console, ou un service système comme ``web``) : son ``purpose`` est la ligne de son catalogue, écrite pour
    elle et au « tu » qui la désigne, pas pour la personne (ADR 0209) ; rien pour une app."""
    kind, _, key = resource.partition(":")
    status = statuses.get(key) if kind == "mcp" else None
    return status.purpose if status is not None and status.owner else ""


def _opens(rows: Iterable[Mapping[str, Any]]) -> bool:
    """Au moins une case de ses outils s'ouvre à la personne : sinon, ce service n'est pas pour elle."""
    return any(cell is not None and cell["level"] != NO for row in rows for cell in row["cells"].values())


def _person_name(frame: Any) -> Callable[[str], str]:
    def name(key: str) -> str:
        view = frame.get(identity_c.IDENTITY(key))
        return getattr(view, "name", "") or key

    return name


def routes(api: MeApiBase) -> list[Route]:
    return [api.route("/rights", matrix)]
