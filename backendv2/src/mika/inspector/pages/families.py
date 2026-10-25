"""Outils › Ses propres outils (ADR 0134) : ses outils internes, famille par famille (un lot), chacune avec son
tableau de droits — né du minimum vital que ses outils déclarent (``owner_only``), modifiable, et « Revenir au
minimum vital ». Les outils venus d'ailleurs (un service, une app) ont leurs tableaux chez leur propriétaire.

Les tableaux se rangent dans les réglages (``Settings.save_family``) ; la porte d'offre les lit à chaque épisode.
"""

from __future__ import annotations

import secrets as _secrets
from typing import Annotated, Any
from urllib.parse import urlencode

from pydantic import Field, ValidationError
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from mika.inspector.catalog import Panel
from mika.inspector.pages.droits_tables import choices, one_page, rows_of, table_args
from mika.inspector.pages.tabs import TABS
from mika.inspector.ui import PREFIX, secure
from mika.kernel.forms import Knob
from mika.kernel.frame import Audience
from mika.kernel.rights import Rights
from mika.runtime import operations as ops
from mika.runtime.tools import gate_of
from mika.vocab.access import (
    ALONE,
    CARD,
    KEEPS,
    NO,
    OWNER,
    OWNER_OK,
    POLICIES,
    Table,
    TableArgs,
    ToolRule,
    moved,
)
from mika.vocab.episodes import Kind
from mika.vocab.privacy import ChannelTrust
from mika.vocab.rights import tool_allowance, vital_family

BASE = f"{PREFIX}/outils/familles"
MAX_ROWS = 40
#: la ligne qu'on ajoute : toi, par tous les canaux, toujours, fermée
NEW_ROW = ToolRule(who=(OWNER,))
FLOORS = ("une inconnue n'obtient au plus que des outils qui lisent, jamais une action",
          "à plusieurs (un salon), un outil qui lit au plus ; rien de ce qui vient du dehors",
          "elle seule : un projet ou un réveil seulement s'il a pris ce lot, une tâche seulement si c'est la sienne")
#: elle seule, et toi : les deux audiences du minimum vital
WORKING = Audience(persons=(), channel="internal", public=False, trust=ChannelTrust.INTERNAL.value, owner=True)
YOU = Audience(persons=("familles:toi",), channel="web", public=False, trust=ChannelTrust.AUTHENTICATED.value,
               owner=True, person="familles:toi")


class FamilyArgs(TableArgs):
    """Le tableau d'une famille, d'un seul envoi : ses lignes (``TableArgs``, ses outils) et ses colonnes — un outil
    qui lit, un outil qui agit, ce qu'elle en garde ; la ligne par défaut à part ; la clé de la famille (``cle``)."""

    cle: Annotated[str, Knob(label="Famille")] = Field("", max_length=80)
    lecture: Annotated[dict[str, str], Knob(label="Un outil qui lit", advanced=False)] = Field(default_factory=dict)
    action: Annotated[dict[str, str], Knob(label="Un outil qui agit", advanced=False)] = Field(default_factory=dict)
    garde: Annotated[dict[str, str], Knob(label="Ce qu'elle en garde", advanced=False)] = Field(default_factory=dict)
    defaut_lecture: Annotated[str, Knob(label="Par défaut, un outil qui lit")] = "non"
    defaut_action: Annotated[str, Knob(label="Par défaut, un outil qui agit")] = "non"
    defaut_garde: Annotated[str, Knob(label="Par défaut, ce qu'elle en garde")] = "rien"


def family_rows(args: FamilyArgs, known: list[str]) -> list[ToolRule]:
    """Les lignes du tableau envoyé (``vocab.access.rows_sent``) ; un outil que la famille n'a plus n'est pas gardé."""
    sent = args.rows(tools=True, read=args.lecture, act=args.action, keep=args.garde)
    return [ToolRule(who=r["who"], canal=r["canal"], when=r["when"], read=r["read"] or NO, act=r["act"] or NO,
                     keep=r["keep"] or "rien", tools=tuple(t for t in known if t in r["tools"])) for r in sent]


def _values(a: ToolRule) -> dict[str, Any]:
    return {"lecture": a.read, "action": a.act, "garde": a.keep}


def _below(specs: list[Any], lines: tuple[ToolRule, ...], default: ToolRule, rights: Rights) -> str:
    """Ce qui manque au minimum vital : un outil que le code ouvrait à elle seule ou à toi, et que le tableau ferme."""
    lost = []
    for spec in specs:
        for who, aud in (("elle seule", WORKING), ("toi", YOU)):
            got = tool_allowance(lines, default, aud, Kind.WORK if who == "elle seule" else Kind.REPLY, spec.acts,
                                 rights, lambda r, n=spec.name: r.concerns(n), outside=spec.outside)
            if got is None or got.level == NO:
                lost.append(f"{spec.name} ({who})")
    return ", ".join(lost[:6]) + (f" et {len(lost) - 6} autres" if len(lost) > 6 else "")


def entries(ui: Any) -> list[dict[str, Any]]:
    """Chaque famille de ses propres outils (les outils du code, pas ceux d'un service ou d'une app) : ses outils,
    son tableau — réglé, ou son minimum vital."""
    registry = ui.kernel.registry
    rights, _close = gate_of(registry)
    families: dict[str, list[Any]] = {}
    for spec in sorted(registry.tools.values(), key=lambda t: t.name):
        if not registry.is_dynamic(spec.name):
            families.setdefault(spec.bundle, []).append(spec)
    out = []
    for bundle, specs in sorted(families.items(), key=lambda kv: ui.names.bundle(kv[0]).casefold()):
        table = rights.families.get(bundle)
        lines, default = (tuple(table.lines), table.default) if table is not None else vital_family(specs)
        deferrable, outside = any(s.deferrable for s in specs), any(s.outside for s in specs)
        locked_policies = () if deferrable else (CARD, OWNER_OK)
        out.append({
            "key": bundle, "id": bundle.replace(".", "-"), "label": ui.names.bundle(bundle), "set": table is not None,
            "reserved": any(s.owner_only for s in specs),
            "tools": [{"name": s.name, "nature": "agit" if s.acts else "lit"} for s in specs],
            "lines": lines, "default": default,
            "columns": [
                {"key": "lecture", "label": "Un outil qui lit", "kind": "pick", "choices": choices(POLICIES, locked_policies),
                 "help": "" if deferrable else "Ces outils ne se diffèrent pas : seule, ou non."},
                {"key": "action", "label": "Un outil qui agit", "kind": "pick", "choices": choices(POLICIES, locked_policies),
                 "help": "" if deferrable else "Ces outils ne se diffèrent pas : seule, ou non."},
                {"key": "garde", "label": "Ce qu'elle en garde", "kind": "pick",
                 "choices": choices(KEEPS, () if outside else tuple(k for k, _ in KEEPS if k != "public")),
                 "help": "" if outside else "Ce que rendent ces outils est déjà à elle : rien à garder de plus."}],
            "below": _below(specs, lines, default, rights) if table is not None else ""})
    return out


@TABS.tab("outils.familles", title="Ses propres outils", order=15,
          description="Ses outils internes, famille par famille, chacune avec son tableau de droits : qui, par où, "
                      "quand, ce qu'elle fait d'un outil qui lit et d'un outil qui agit — né du minimum vital, "
                      "modifiable.")
async def families_page(ui: Any, request: Request) -> Any:
    focus = str(request.query_params.get("famille", "") or "")
    account = ui.operator(request)
    csrf = request.cookies.get("csrftoken", "")
    shown = []
    for e in entries(ui):
        tools = [(x["name"], x["nature"]) for x in e["tools"]]
        rows = rows_of(ui, e["lines"], _values, tools=tools)
        shown.append({**e, "t": {
            "id": e["id"], "key": e["key"], "title": e["label"],
            "intro": "De haut en bas : pour un outil, la première ligne qui le concerne (qui, par où, quand, l'outil "
                     "dans sa colonne) décide ; aucune, le comportement par défaut — après le tableau du canal, sous "
                     "le plafond de qui est en face.",
            "note": "Son minimum vital, tel que le code le déclare, tant qu'on ne l'a pas réglé." if not e["set"] else "",
            "below": e["below"], "action": f"{BASE}/regler", "csrf": csrf, "rows": rows,
            "default": _values(e["default"]), "columns": e["columns"], "show_canal": True, "show_tools": True,
            "pager": one_page(len(rows) + 1), "floors": FLOORS, "set": e["set"]},
            "open": e["key"] == focus})
    return {"blocks": [], "panel": Panel("handmade/droits/familles.html", {
        "families": shown, "focus": focus, "locked": account is None}, styles=("handmade/tools.css", "handmade/rights.css"))}


async def families_post(ui: Any, request: Request) -> Response:
    """Le tableau d'une famille, enregistré d'un coup (``cle``) ; « remettre » revient à son minimum vital."""
    got = await ui.form_lists(request)
    account = ui.operator(request)
    token = _secrets.token_urlsafe(9)
    data = got[0] if got is not None else {}
    key = str(data.get("cle", ""))
    settings, registry = ui.deps.settings, ui.kernel.registry
    known = sorted(s.name for s in registry.tools.values() if s.bundle == key and not registry.is_dynamic(s.name))
    if got is None or account is None:
        ui.flash(token, "danger", "Jeton de formulaire invalide : recharge la page.")
    elif settings is None or not known:
        ui.flash(token, "warn", "Aucune famille de ce nom, ou les réglages ne sont pas joignables : rien n'a été "
                                "enregistré.")
    else:
        try:
            args = table_args(FamilyArgs, data)
            if args.faire.strip() == "remettre":
                await settings.save_family(key, None)
                said = "Revenu au minimum vital."
            else:
                rows, said = moved(family_rows(args, known), args.faire.strip(), NEW_ROW, MAX_ROWS)
                default = ToolRule(read=args.defaut_lecture, act=args.defaut_action, keep=args.defaut_garde)
                await settings.save_family(key, Table[ToolRule](lines=tuple(rows), default=default))
            await ops.audit(ui.kernel, "console.outils.familles", by=account.handle, subject_kind="famille",
                            subject=key)
            ui.flash(token, "ok", f"{said} Vaut dès son prochain épisode.")
        except (ValueError, ValidationError) as exc:
            ui.flash(token, "danger", str(exc)[:300])
    return secure(RedirectResponse(f"{BASE}?" + urlencode({"famille": key, "flash": token}) + f"#f-{key.replace('.', '-')}",
                                   status_code=303))


__all__ = ["ALONE", "families_page", "families_post"]
