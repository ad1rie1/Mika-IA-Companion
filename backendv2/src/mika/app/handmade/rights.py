"""Réglages › Droits, dessiné (ADR 0133, 0134) : ce qu'elle a, ressource par ressource — sa vie interne (ses
familles d'outils), les apps de la Forge, les services MCP, ses projets, ses canaux —, chaque outil avec sa
description, et pour chaque ressource un lien vers **le détail de ses accès** : son tableau de règles, lu tel qu'il est
écrit, avec « Modifier » vers la page qui le règle et « Retour ». Les droits exacts, outil par outil, seulement quand
on a choisi **qui** et **par quel canal** : la règle du moteur, appliquée à cette personne par ce canal (les deux
portes, le plafond) — jamais une recopie.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from markupsafe import Markup

from mika.app.handmade.access import people_with_accounts
from mika.contracts import forge as forge_c
from mika.inspector import render
from mika.inspector.pages import rights
from mika.inspector.pages import tools as catalog
from mika.inspector.ui import UI, env
from mika.kernel.frame import Audience
from mika.kernel.inspect import Pager
from mika.kernel.rights import Grant
from mika.vocab.access import INTERNAL, INTERNET, MOBILE, PRIVATE, TOGETHER, WEB, canal_key
from mika.vocab.episodes import Kind
from mika.vocab.privacy import ChannelTrust

#: ce que le code fixe et qui n'est pas un outil (les outils, eux, se lisent : ``fixed_tools``)
FIXED = (
    "Ce que le téléphone envoie : toujours ton geste.",
    "À qui elle rend compte (un courrier qui arrive, un réveil, un projet) : toi, selon la confidentialité.",
    "Un réveil par API agit avec tes droits, dans les seuls outils qu'il déclare ; prêter à un agent, avec les tiens "
    "et tes règles d'outils.",
    "Une carte d'accord : la personne à qui elle est adressée la tranche dans son chat ; un opérateur, toutes, dans "
    "la console (« À valider »).",
    "Les plafonds : une inconnue n'obtient au plus que des outils qui lisent, jamais une action ; à plusieurs, un de "
    "ses outils qui lit au plus, rien venu d'ailleurs ; un projet s'y lit, sans plus ; sans personne en face, rien.",
)
#: les canaux qu'on peut choisir pour lire les droits exacts
CANAL_CHOICES = ((f"{WEB}:{PRIVATE}", "le chat web, en privé"), (f"{WEB}:{TOGETHER}", "le chat web, en salon"),
                 (MOBILE, "l'app Android"), (INTERNET, "Internet (un moyen que rien ne prouve)"),
                 (INTERNAL, "elle seule (elle travaille)"))
#: elle travaille seule : personne n'écoute (l'audience d'un pas, d'une exécution, d'une tâche)
WORKING = Audience(persons=(), channel="internal", public=False, trust=ChannelTrust.INTERNAL.value, owner=True)
_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")


@dataclass(frozen=True, slots=True)
class Who:
    """Une personne type : qui est en face, et à quel moment."""

    key: str
    label: str
    person: str = ""
    owner: bool = False
    kind: str = Kind.REPLY
    unknown: bool = False


def whos(ui: UI) -> list[Who]:
    """Qui on peut choisir : toi (quand elle te répond, quand elle te parle d'elle-même), chaque personne qui a un
    compte, un autre compte, une inconnue, elle seule."""
    out = [Who("toi", "toi, quand elle te répond", "toi", True),
           Who("toi-parle", "toi, quand elle te parle d'elle-même", "toi", True, Kind.INITIATIVE)]
    out += [Who(f"p:{x['key']}", x["name"], x["key"]) for x in people_with_accounts(ui)]
    out += [Who("compte", "un autre compte", "compte"), Who("inconnue", "une inconnue", "", unknown=True),
            Who("seule", "elle seule, quand elle travaille", kind=Kind.WORK)]
    return out


def audience_for(who: Who, canal: str) -> tuple[Audience, str]:
    """L'audience qu'une personne type a par ce canal, et la sorte d'épisode : la règle du moteur la lira comme le
    pipeline. Elle seule, par tout canal, c'est elle qui travaille ; dans un salon, personne n'est reconnu, même
    toi ; par Internet ou sans session, rien ne prouve qui parle, sauf un moyen relié à toi."""
    kind_, instance = canal_key(canal)
    if who.key == "seule" or kind_ == INTERNAL:
        return WORKING, Kind.WORK
    together = instance == TOGETHER
    channel = {WEB: "web", MOBILE: "mobile"}.get(kind_, "external")
    if who.unknown:
        trust = ChannelTrust.PUBLIC if kind_ == WEB else ChannelTrust.ACCOUNT
    else:
        trust = ChannelTrust.AUTHENTICATED if kind_ in (WEB, MOBILE) else ChannelTrust.ACCOUNT
    if together:
        trust = ChannelTrust.PUBLIC
    return Audience(persons=(f"droits:{who.key}",), channel=channel, room="salon" if together else None,
                    public=together, trust=trust.value, owner=who.owner and not together,
                    person="" if who.unknown else who.person), who.kind


def _tool_of(ui: UI, spec: Any, g: Grant) -> str:
    """Le nom chez elle de l'outil qu'un droit désigne : ses familles (« Mémoire · memory_search »), un service
    (« « meteo » · echo » : ``mcp_<serveur>_<outil>``), une app (le nom même)."""
    kind = spec.key.rsplit(".", 1)[-1]
    if kind == "familles":
        return g.title.rsplit(" · ", 1)[-1]
    if kind == "services":
        server, remote = g.resource.partition(":")[2], g.title.rsplit(" · ", 1)[-1]
        base = f"mcp_{server}_{_UNSAFE.sub('_', remote)}"
        if base in ui.kernel.registry.tools:
            return base
        return next((n for n in ui.kernel.registry.tools if n.startswith(f"mcp_{server}_")
                     and n.endswith(_UNSAFE.sub("_", remote)[-20:])), base)
    return g.title


def exact(ui: UI, who: Who, canal: str) -> dict[str, Any]:
    """Les droits exacts de cette personne par ce canal : par outil (son niveau, sa garde, pourquoi), par projet, et
    ce que le canal laisse au plus."""
    audience, kind = audience_for(who, canal)
    tools: dict[str, Grant] = {}
    projects: dict[str, Grant] = {}
    through: Grant | None = None
    for spec, found in rights.grants(ui, audience, kind):
        sort = spec.key.rsplit(".", 1)[-1]
        for g in found:
            if sort == "canaux":
                through = g
            elif sort == "projets":
                projects[g.resource] = g
            else:
                tools[_tool_of(ui, spec, g)] = g
    return {"tools": tools, "projects": projects, "canal": through, "kind": kind}


def _what(g: Grant | None) -> str:
    """Un droit en une phrase : ses actions et leurs réponses, et la ligne qui en décide."""
    if g is None:
        return "rien ici"
    said = " · ".join(f"{k} : {v}" for k, v in g.what)
    return f"{said} — {g.why}" if g.why else said


def _tool_row(ui: UI, spec: Any, got: Mapping[str, Grant] | None) -> dict[str, Any]:
    return {"name": spec.name, "description": spec.description, "nature": "agit" if spec.acts else "lit",
            "href": f"{catalog.BASE}/tous?outil={spec.name}",
            "exact": _what(got.get(spec.name)) if got is not None else "",
            "closed": got is not None and (got.get(spec.name) is None or got[spec.name].closed)}


def sections(ui: UI, got: Mapping[str, Any] | None, query: str) -> list[dict[str, Any]]:
    """Les ressources, par sorte : sa vie interne (ses familles, par lot), les apps de la Forge, les services MCP,
    ses projets, ses canaux — chacune avec ses outils décrits et le lien de son détail."""
    registry, frame = ui.kernel.registry, ui.kernel.mind.frame()
    tables = {t.resource: t for _spec, found in rights.tables(ui) for t in found}
    apps = {a.name: a for a in frame.get(forge_c.APPS)}
    by_bundle: dict[str, list[Any]] = {}
    for spec in sorted(registry.tools.values(), key=lambda t: t.name):
        by_bundle.setdefault(spec.bundle, []).append(spec)
    tools_got = got["tools"] if got else None

    def entry(key: str, label: str, description: str, specs: Sequence[Any], detail: str,
              exact_: str = "") -> dict[str, Any]:
        table = tables.get(detail)
        return {"key": key, "label": label, "description": description,
                "tools": [_tool_row(ui, s, tools_got) for s in specs],
                "detail": "?" + "&".join(filter(None, (f"detail={detail}", query))) if table is not None else "",
                "edit": render.href(table.href) if table is not None and table.href is not None else "",
                "exact": exact_}

    internal = [entry(b, ui.names.bundle(b), registry.bundles.get(b, ""), specs, f"famille:{b}")
                for b, specs in sorted(by_bundle.items(), key=lambda kv: ui.names.bundle(kv[0]).casefold())
                if not any(registry.is_dynamic(s.name) for s in specs)]
    forged = []
    for b, specs in sorted(by_bundle.items()):
        if not b.startswith("forge_apps."):
            continue
        name = b.partition(".")[2]
        app = apps.get(name)
        detail = f"project:{app.project}" if app is not None and app.project else f"forge:{name}"
        label = (app.title if app is not None and app.title else name)
        forged.append(entry(b, f"App « {label} »", registry.bundles.get(b, ""), specs, detail))
    services = [entry(b, f"Service « {b.partition('.')[2]} »", registry.bundles.get(b, ""), specs,
                      f"mcp:{b.partition('.')[2]}")
                for b, specs in sorted(by_bundle.items()) if b.startswith("mcp.")]
    projects_got = got["projects"] if got else {}
    projects = [entry(t.resource, t.title, t.note, (), t.resource, _what(projects_got.get(t.resource)) if got else "")
                for t in tables.values() if t.resource.startswith("project:")]
    canals = [entry(t.resource, t.title, t.note, (), t.resource) for t in tables.values()
              if t.resource.startswith("canal:")]
    out = [{"title": "Vie interne", "hint": "ses propres outils, famille par famille", "rows": internal},
           {"title": "Apps de la Forge", "hint": "une app suit son projet ; sans projet, ses propres lignes",
            "rows": forged},
           {"title": "Services MCP", "hint": "les outils venus d'ailleurs, service par service", "rows": services},
           {"title": "Projets", "hint": "le voir, le piloter, ses fichiers, ses apps", "rows": projects},
           {"title": "Canaux", "hint": "par où ça lui arrive : ce que chaque canal laisse au plus", "rows": canals}]
    for s in out:
        s["pager"] = _one_page(sum(1 + len(r["tools"]) for r in s["rows"]))
    return out


def _one_page(rows: int) -> Any:
    return render._pager(Pager(size=max(1, rows), total=max(1, rows)), {})


def detail(ui: UI, key: str) -> dict[str, Any] | None:
    """Le détail des accès d'une ressource : son tableau tel qu'il est écrit, ses planchers, où il se règle."""
    for spec, found in rights.tables(ui):
        for t in found:
            if t.resource == key:
                return {"kind": spec.title, "title": t.title, "columns": t.columns,
                        "rows": [(str(i), *r) for i, r in enumerate(t.rows, start=1)], "default": t.default,
                        "floors": t.floors, "note": t.note,
                        "edit": render.href(t.href) if t.href is not None else "",
                        "pager": _one_page(len(t.rows) + 1)}
    return None


def fixed_tools(ui: UI) -> dict[str, Any]:
    """Ce que le code déclare, lu des outils mêmes : ceux dont le minimum vital est à toi et elle seule
    (``owner_only``), par famille ; ceux qu'une condition garde (``when``), regroupés par sa phrase. Un outil réservé
    peut être gardé aussi : une ligne qui l'ouvre ne lève pas sa condition (ADR 0148)."""
    reserved: dict[str, list[str]] = {}
    guarded: dict[str, list[str]] = {}
    for spec in sorted(ui.kernel.registry.tools.values(), key=lambda t: t.name):
        if spec.owner_only:
            reserved.setdefault(ui.names.bundle(spec.bundle), []).append(spec.name)
        if spec.when is not None:
            guarded.setdefault(catalog.condition(spec), []).append(spec.name)
    return {"reserved": sorted(reserved.items()), "guarded": sorted(guarded.items(), key=lambda x: -len(x[1])),
            "count": sum(len(n) for n in reserved.values()), "guarded_count": sum(len(n) for n in guarded.values())}


def page(ui: UI, items: Sequence[Any], query: Mapping[str, str]) -> Markup:
    """La page : les ressources et leurs outils ; le détail d'une (``?detail=``) ; les droits exacts quand on a choisi
    qui (``?qui=``) et par quel canal (``?canal=``)."""
    all_whos = whos(ui)
    who = next((w for w in all_whos if w.key == query.get("qui", "")), None)
    canal = query.get("canal", "") if query.get("canal", "") in dict(CANAL_CHOICES) else ""
    got = exact(ui, who, canal) if who is not None and canal else None
    kept = "&".join(f"{k}={v}" for k, v in (("qui", who.key if who else ""), ("canal", canal)) if v)
    shown = detail(ui, query["detail"]) if query.get("detail") else None
    return Markup(env.get_template("handmade/droits/page.html").render(
        whos=[{"key": w.key, "label": w.label, "on": w is who} for w in all_whos],
        canals=[{"key": k, "label": label, "on": k == canal} for k, label in CANAL_CHOICES],
        chosen=(who.label if who else "", dict(CANAL_CHOICES).get(canal, "")), got=got,
        canal_said=_what(got["canal"]) if got else "", sections=sections(ui, got, kept), kept=kept,
        detail=shown, fixed=FIXED, tools=fixed_tools(ui), catalogue=f"{catalog.BASE}/tous"))
