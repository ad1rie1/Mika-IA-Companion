"""Réglages › Canaux (ADR 0134) : par où ça arrive, et ce que chaque canal laisse passer au plus — un tableau par
canal (un type, ou une instance pour une exception), lu de haut en bas puis sa ligne par défaut. Sur tes comptes (une
boîte de courrier, Teams), elle écrit à ta place : ses colonnes sont « préparer d'elle-même » et comment ça part
(l'ADR 0132 s'y fond). Un canal qu'on n'a pas réglé montre son minimum vital ; « Revenir au minimum vital » retire
ce qu'on avait réglé.

Les tableaux se rangent dans les réglages (``Settings.save_canal``) et passent au courrier et à Teams en paramètre
(journalisé : sa vie se rejoue) ; le registre les lit à chaque épisode.
"""

from __future__ import annotations

import secrets as _secrets
from typing import Annotated, Any
from urllib.parse import urlencode

from pydantic import Field, ValidationError
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from mika.inspector.catalog import Panel
from mika.inspector.pages.droits_tables import canal_instances, choices, one_page, rows_of, table_args
from mika.inspector.pages.tabs import TABS
from mika.inspector.ui import PREFIX, secure
from mika.kernel.forms import Knob
from mika.runtime import operations as ops
from mika.vocab.access import (
    CANAL_WORDS,
    CANALS,
    EVERYONE,
    INTERNAL,
    KEEP_WORDS,
    KEEPS,
    MAIL,
    POLICIES,
    POLICY_WORDS,
    REPLIES,
    REPLY_WORDS,
    STEER_WORDS,
    STEERS,
    TALKING,
    TableArgs,
    canal_key,
    moved,
)
from mika.vocab.canals import CanalRule, Canals, CanalTable, vital

BASE = f"{PREFIX}/reglages/canaux"
MAX_ROWS = 40
#: la ligne qu'on ajoute : tout le monde, toujours, fermée
NEW_ROW = CanalRule(who=(EVERYONE,))
#: ce qu'aucune ligne d'un canal n'ouvre
FLOORS = ("une inconnue n'obtient au plus que des outils qui lisent, jamais une action, une garde « rien »",
          "à plusieurs (un salon, un groupe), aucun outil venu d'ailleurs, un projet en lecture seule au plus",
          "ce qui est reconnu tient au moyen de communication, pas au canal")


class CanalArgs(TableArgs):
    """Le tableau d'un canal, d'un seul envoi : ses lignes (``TableArgs``) et ses colonnes — répondre ou écrire,
    préparer d'elle-même, un outil qui lit, un outil qui agit, piloter un projet, ses fichiers, ce qu'elle en
    garde ; la ligne par défaut à part ; la clé du canal (``cle``)."""

    cle: Annotated[str, Knob(label="Canal")] = Field("", max_length=80)
    repondre: Annotated[dict[str, str], Knob(label="Répondre, écrire", advanced=False)] = Field(default_factory=dict)
    preparer: Annotated[dict[str, bool], Knob(label="Préparer d'elle-même", advanced=False)] = Field(default_factory=dict)
    lecture: Annotated[dict[str, str], Knob(label="Un outil qui lit, au plus", advanced=False)] = Field(default_factory=dict)
    action: Annotated[dict[str, str], Knob(label="Un outil qui agit, au plus", advanced=False)] = Field(default_factory=dict)
    projets: Annotated[dict[str, str], Knob(label="Piloter un projet, au plus", advanced=False)] = Field(default_factory=dict)
    fichiers: Annotated[dict[str, bool], Knob(label="Ses fichiers", advanced=False)] = Field(default_factory=dict)
    garde: Annotated[dict[str, str], Knob(label="Ce qu'elle en garde, au plus", advanced=False)] = Field(default_factory=dict)
    defaut_repondre: Annotated[str, Knob(label="Par défaut, répondre")] = "non"
    defaut_preparer: Annotated[bool, Knob(label="Par défaut, préparer")] = False
    defaut_lecture: Annotated[str, Knob(label="Par défaut, un outil qui lit")] = "non"
    defaut_action: Annotated[str, Knob(label="Par défaut, un outil qui agit")] = "non"
    defaut_projets: Annotated[str, Knob(label="Par défaut, piloter un projet")] = "non"
    defaut_fichiers: Annotated[bool, Knob(label="Par défaut, ses fichiers")] = False
    defaut_garde: Annotated[str, Knob(label="Par défaut, ce qu'elle en garde")] = "rien"


def canal_rows(args: CanalArgs, key: str) -> list[CanalRule]:
    """Les lignes du tableau envoyé pour ce canal (``vocab.access.rows_sent``) : le canal d'une ligne est celui du
    tableau (pas de colonne « par où ») ; pour « elle seule », personne en face."""
    kind = canal_key(key)[0]
    ligne = dict(args.ligne)
    canal = {f"{n}|{key}": True for n in ligne}
    args = args.model_copy(update={"canal": canal, "qui": {} if kind == INTERNAL else args.qui})
    sent = args.rows(reply=args.repondre, prepare=args.preparer, read=args.lecture, act=args.action,
                     steer=args.projets, files=args.fichiers, keep=args.garde)
    return [CanalRule(who=r["who"], canal=(key,), when=r["when"], reply=r["reply"] or "non",
                      prepare=bool(r["prepare"]), read=r["read"] or "non", act=r["act"] or "non",
                      steer=r["steer"] or "non", files=bool(r["files"]), keep=r["keep"] or "rien") for r in sent]


def _columns(kind: str) -> list[dict[str, Any]]:
    """Les colonnes d'un canal : sur tes comptes, préparer et comment ça part ; sur les siens, ses plafonds."""
    if kind not in TALKING:
        send = choices(REPLIES, locked=("brouillon",) if kind == MAIL else ())
        return [{"key": "preparer", "label": "Préparer d'elle-même", "kind": "bool",
                 "help": "Pour un message qui attend une réponse, elle en prépare une sans qu'on le lui demande."},
                {"key": "repondre", "label": "Comment ça part", "kind": "pick", "choices": send,
                 "help": "Brouillon : posé, c'est toi qui l'envoies (le courrier n'en a pas : ton accord) ; ton "
                         "accord ; seule ; non."}]
    reply = choices(REPLIES, locked=("brouillon",))
    return [{"key": "repondre", "label": "Répondre", "kind": "pick", "choices": reply,
             "help": "Elle parle en son nom : seule, ou non."},
            {"key": "lecture", "label": "Outils : lecture, au plus", "kind": "pick", "choices": choices(POLICIES),
             "help": "Le plafond d'un outil qui lit ; la ressource (service, app, famille) décide ensuite."},
            {"key": "action", "label": "Outils : action, au plus", "kind": "pick", "choices": choices(POLICIES),
             "help": "Le plafond d'un outil qui agit."},
            {"key": "projets", "label": "Projets, au plus", "kind": "pick", "choices": choices(STEERS),
             "help": "Le plafond du pilotage d'un projet."},
            {"key": "fichiers", "label": "Fichiers", "kind": "bool",
             "help": "Elle peut envoyer les fichiers d'un projet par ce canal."},
            {"key": "garde", "label": "Garde, au plus", "kind": "pick", "choices": choices(KEEPS),
             "help": "Le plafond de ce qu'elle garde de ce qu'un outil rend."}]


def _values(a: CanalRule) -> dict[str, Any]:
    return {"repondre": a.reply, "preparer": a.prepare, "lecture": a.read, "action": a.act, "projets": a.steer,
            "fichiers": a.files, "garde": a.keep}


def _words(kind: str, a: CanalRule) -> str:
    if kind not in TALKING:
        return f"préparer : {'oui' if a.prepare else 'non'} · part : {REPLY_WORDS.get(a.reply, a.reply)}"
    return (f"répondre : {REPLY_WORDS.get(a.reply, a.reply)} · outils {POLICY_WORDS.get(a.read, a.read)} / "
            f"{POLICY_WORDS.get(a.act, a.act)} · projets {STEER_WORDS.get(a.steer, a.steer)} · fichiers "
            f"{'oui' if a.files else 'non'} · garde {KEEP_WORDS.get(a.keep, a.keep)}")


def _below(key: str, table: CanalTable) -> str:
    """Ce qui manque au minimum vital : un canal où elle parle en son nom (le chat web, l'app Android, Internet) ou
    elle seule fermé à tout."""
    kind = canal_key(key)[0]
    if kind not in TALKING:
        return ""
    if not any(a.read != "non" or a.act != "non" for a in (*table.lines, table.default)):
        return "plus aucun outil ne passe par ce canal" if kind != INTERNAL else "elle seule n'a plus aucun outil"
    return ""


def entries(ui: Any) -> list[dict[str, Any]]:
    """Chaque canal : ses types, puis les instances connues (une boîte, un réseau, le chat web en privé ou en
    salon), avec son tableau — réglé, ou son minimum vital."""
    settings = ui.deps.settings
    canals: Canals = settings.canals() if settings is not None else Canals()
    instances = canal_instances(ui)
    keys: list[tuple[str, str]] = []
    for kind, label in CANALS:
        keys.append((kind, label))
        keys += [(k, f"{label} · {name}") for k, name in instances.get(kind, ())]
    known = {k for k, _ in keys}
    keys += [(k, k) for k in sorted(canals.tables) if k not in known]
    out = []
    for key, label in keys:
        kind = canal_key(key)[0]
        table = canals.tables.get(key) or vital(key)
        out.append({"key": key, "label": label, "kind": kind, "set": key in canals.tables, "table": table,
                    "instance": ":" in key, "words": [_words(kind, a) for a in table.lines],
                    "below": _below(key, table) if key in canals.tables else ""})
    return out


@TABS.tab("reglages.canaux", title="Canaux", group="Droits", order=2400,
          description="Par où ça lui arrive, et ce que chaque canal laisse passer au plus : le chat web, l'app "
                      "Android, Teams, le courrier, Internet, elle seule — un tableau par canal, lu de haut en bas.")
async def canals_page(ui: Any, request: Request) -> Any:
    focus = str(request.query_params.get("canal", "") or "")
    account = ui.operator(request)
    csrf = request.cookies.get("csrftoken", "")
    shown = []
    for e in entries(ui):
        kind, table = e["kind"], e["table"]
        rows = rows_of(ui, table.lines, _values, show_canal=False)
        shown.append({**e, "t": {
            "id": e["key"].replace(":", "-").replace(".", "-"), "key": e["key"], "title": e["label"],
            "intro": ("Elle écrit à ta place : qui écrit (tout le monde, ou une adresse, un @domaine, un morceau du "
                      "nom), préparer d'elle-même, comment ça part." if kind not in TALKING else
                      "Ce que ce canal laisse passer au plus ; le tableau de la ressource décide ensuite, et la plus "
                      "stricte gagne."),
            "note": "Son minimum vital, tant qu'on ne l'a pas réglé." if not e["set"] else "",
            "below": e["below"], "action": f"{BASE}/regler", "csrf": csrf, "rows": rows,
            "default": _values(table.default), "columns": _columns(kind), "show_canal": False, "show_tools": False,
            "pager": one_page(len(rows) + 1), "floors": FLOORS, "set": e["set"]},
            "open": e["key"] == focus or (not focus and not e["instance"])})
    return {"blocks": [], "panel": Panel("handmade/droits/canaux.html", {
        "canals": shown, "focus": focus, "locked": account is None, "words": CANAL_WORDS}, styles=("handmade/tools.css", "handmade/rights.css"))}


async def canals_post(ui: Any, request: Request) -> Response:
    """Le tableau d'un canal, enregistré d'un coup (``cle``) ; « remettre » revient à son minimum vital."""
    got = await ui.form_lists(request)
    account = ui.operator(request)
    token = _secrets.token_urlsafe(9)
    data = got[0] if got is not None else {}
    key = str(data.get("cle", ""))
    settings = ui.deps.settings
    if got is None or account is None:
        ui.flash(token, "danger", "Jeton de formulaire invalide : recharge la page.")
    elif settings is None or not key:
        ui.flash(token, "warn", "Les réglages ne sont pas joignables : rien n'a été enregistré.")
    else:
        try:
            args = table_args(CanalArgs, data)
            if args.faire.strip() == "remettre":
                await settings.save_canal(key, None)
                said = "Revenu au minimum vital."
            else:
                rows, said = moved(canal_rows(args, key), args.faire.strip(), NEW_ROW.model_copy(update={"canal": (key,)}),
                                   MAX_ROWS)
                default = CanalRule(canal=(key,), reply=args.defaut_repondre, prepare=args.defaut_preparer,
                                    read=args.defaut_lecture, act=args.defaut_action, steer=args.defaut_projets,
                                    files=args.defaut_fichiers, keep=args.defaut_garde)
                await settings.save_canal(key, CanalTable(lines=tuple(rows), default=default))
            await ops.audit(ui.kernel, "console.canaux.regler", by=account.handle, subject_kind="canal", subject=key)
            if ui.deps.reconfigure is not None:  # le courrier et Teams lisent les tableaux en paramètre
                await ui.deps.reconfigure()
            ui.flash(token, "ok", f"{said} Vaut dès son prochain épisode.")
        except (ValueError, ValidationError) as exc:
            ui.flash(token, "danger", str(exc)[:300])
    return secure(RedirectResponse(f"{BASE}?" + urlencode({"canal": key, "flash": token}) + f"#t-{key.replace(':', '-')}",
                                   status_code=303))
