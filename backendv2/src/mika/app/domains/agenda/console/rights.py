"""Les agendas dans Réglages › Droits (ADR 0309, lot 5 ; ADR 0310) : leur sous-onglet, un agenda par ligne, et le
tableau de droits de chacun, réglé là — ses lignes, leur ordre, sa ligne par défaut, que l'opérateur enregistre d'un
coup. La part de l'agenda dans cette page (``SORT``, une ``RightsSort`` ; la page, ``app/handmade/rights.py``, et son
gabarit, ``handmade/droits/tableau.html``, restent au cadre). « Modifier », sur le détail des accès d'un agenda,
l'ouvre à la place de sa lecture (``edit``).
"""

from __future__ import annotations

import secrets
from typing import Annotated, Any
from urllib.parse import urlencode

from pydantic import Field, ValidationError
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

from mika.app.domains.domain import RightsSort
from mika.app.handmade.access import KEEP_CHOICES, capitalized
from mika.app.handmade.rights import PAGE, one_page
from mika.inspector.pages.rights_tables import choices, rows_of, table_args
from mika.inspector.pages.subjects import subject_url
from mika.inspector.ui import UI, secure
from mika.kernel.forms import Knob
from mika.plugins.agenda import params_of as agenda_params
from mika.plugins.agenda.inspect import FLOORS as AGENDA_FLOORS
from mika.plugins.agenda.rights import table_of as agenda_table
from mika.runtime import operations
from mika.vocab.access import NO, OWNER, RESPONDS, WRITES, AgendaRule, Table, TableArgs, moved
from mika.vocab.rights import rights_of

#: où « Enregistrer » le tableau d'un agenda envoie son formulaire (ADR 0309, lot 5), et sa ligne qu'on ajoute : toi,
#: par tous les canaux, toujours, fermée
AGENDA_TABLE = f"{PAGE}/agenda"
AGENDA_NEW_ROW = AgendaRule(who=(OWNER,))
AGENDA_ROWS = 30

#: ses colonnes, dans l'ordre de la maquette : lire ; ajouter, modifier, supprimer ; répondre ; ce qu'elle en garde
AGENDA_COLUMNS = (
    {"key": "lire", "label": "Lire", "kind": "pick", "choices": choices((("oui", "Oui"), (NO, "Non"))), "help": ""},
    {"key": "ecrire", "label": "Ajouter, modifier, supprimer", "kind": "pick", "choices": choices(capitalized(WRITES)),
     "help": "Avec ton accord : une carte dans le chat de la personne, ou À valider."},
    {"key": "repondre", "label": "Répondre aux invitations", "kind": "pick", "choices": choices(capitalized(RESPONDS)),
     "help": "Une réponse ne part jamais sans un accord."},
    {"key": "garde", "label": "Ce qu'elle en garde", "kind": "pick", "choices": choices(KEEP_CHOICES), "help": ""})


class AgendaTableArgs(TableArgs):
    """Le tableau d'un agenda, d'un seul envoi : ses lignes (``TableArgs``) et ses colonnes, puis sa ligne par
    défaut ; la clé de l'agenda (``cle``)."""

    cle: Annotated[str, Knob(label="Agenda")] = Field("", max_length=300)
    lire: Annotated[dict[str, str], Knob(label="Lire", advanced=False)] = Field(default_factory=dict)
    ecrire: Annotated[dict[str, str], Knob(label="Ajouter, modifier, supprimer", advanced=False)] = \
        Field(default_factory=dict)
    repondre: Annotated[dict[str, str], Knob(label="Répondre aux invitations", advanced=False)] = \
        Field(default_factory=dict)
    garde: Annotated[dict[str, str], Knob(label="Ce qu'elle en garde", advanced=False)] = Field(default_factory=dict)
    defaut_lire: Annotated[str, Knob(label="Par défaut, lire")] = NO
    defaut_ecrire: Annotated[str, Knob(label="Par défaut, ajouter")] = NO
    defaut_repondre: Annotated[str, Knob(label="Par défaut, répondre")] = NO
    defaut_garde: Annotated[str, Knob(label="Par défaut, ce qu'elle en garde")] = "rien"


def _agenda_cells(line: AgendaRule) -> dict[str, Any]:
    return {"lire": "oui" if line.read else NO, "ecrire": line.write, "repondre": line.respond, "garde": line.keep}


def agenda_editor(ui: UI, key: str, csrf: str) -> dict[str, Any] | None:
    """Le tableau d'un agenda, à régler (``handmade/droits/tableau.html``) : ses lignes, sa ligne par défaut, leur
    ordre ; ``None`` : pas un agenda d'ici."""
    calendar = key.removeprefix("agenda:")
    store = ui.kernel.ports.get("agenda")
    found = store.calendar(calendar) if store is not None and key.startswith("agenda:") else None
    if found is None:
        return None
    frame = ui.kernel.mind.frame()
    table = agenda_table(agenda_params(frame), rights_of(frame.env), calendar)
    stored = calendar in rights_of(frame.env).agendas
    rows = rows_of(ui, table.lines, _agenda_cells)
    return {"id": "agenda", "key": calendar, "title": f"Qui peut quoi sur « {found.name or calendar} »",
            "intro": "De haut en bas : la première ligne qui correspond (qui, par où, quand) décide ; aucune, le "
                     "comportement par défaut — après le propriétaire et ses partages, le tableau du canal et le "
                     "plafond de qui est en face. Un partage ajoute la ligne de la personne.",
            "note": "" if stored else "Le tableau que son propriétaire et ses partages donnent, tant qu'on ne l'a pas "
                                      "réglé.",
            "below": "", "action": AGENDA_TABLE, "csrf": csrf, "rows": rows, "default": _agenda_cells(table.default),
            "columns": list(AGENDA_COLUMNS), "show_canal": True, "show_tools": False,
            "pager": one_page(len(rows) + 1), "floors": AGENDA_FLOORS, "set": stored,
            "fiche": subject_url("agenda", calendar, "droits")}


def _agenda_rows(args: AgendaTableArgs) -> list[AgendaRule]:
    sent = args.rows(read=args.lire, write=args.ecrire, respond=args.repondre, keep=args.garde)
    return [AgendaRule(who=r["who"], canal=r["canal"], when=r["when"], read=r["read"] == "oui",
                       write=r["write"] or NO, respond=r["respond"] or NO, keep=r["keep"] or "rien") for r in sent]


async def agenda_table_post(ui: UI, request: Request) -> Response:
    """Le tableau d'un agenda, enregistré d'un coup par un opérateur (``cle``) ; « remettre » revient au tableau que
    son propriétaire et ses partages donnent. Audité ; vaut dès son prochain épisode."""
    got = await ui.form_lists(request)
    account = ui.operator(request)
    token = secrets.token_urlsafe(9)
    data = got[0] if got is not None else {}
    key = str(data.get("cle", ""))
    settings, store = ui.deps.settings, ui.kernel.ports.get("agenda")
    if got is None or account is None:
        ui.flash(token, "danger", "Jeton de formulaire invalide : recharge la page.")
    elif settings is None or store is None or store.calendar(key) is None:
        ui.flash(token, "warn", "Cet agenda n'est plus là, ou les réglages ne sont pas joignables : rien n'a été "
                                "enregistré.")
    else:
        try:
            args = table_args(AgendaTableArgs, data)
            if args.faire.strip() == "remettre":
                await settings.named("agenda").save_agenda_table(key, None)
                said = "Revenu au tableau que son propriétaire et ses partages donnent."
            else:
                rows, said = moved(_agenda_rows(args), args.faire.strip(), AGENDA_NEW_ROW, AGENDA_ROWS)
                default = AgendaRule(read=args.defaut_lire == "oui", write=args.defaut_ecrire or NO,
                                     respond=args.defaut_repondre or NO, keep=args.defaut_garde or "rien")
                await settings.named("agenda").save_agenda_table(
                    key, Table[AgendaRule](lines=tuple(rows), default=default))
            await operations.audit(ui.kernel, "console.droits.agenda", by=account.handle, subject_kind="agenda",
                                   subject=key)
            ui.flash(token, "ok", f"{said} Vaut dès son prochain épisode.")
        except (ValueError, ValidationError) as exc:
            ui.flash(token, "danger", str(exc)[:300])
    target = f"{PAGE}?" + urlencode({"detail": f"agenda:{key}", "regler": "1", "flash": token}) + "#t-agenda"
    return secure(RedirectResponse(target, status_code=303))


def edit(key: str) -> str:
    """Où mène « Modifier » sur le détail des accès d'un agenda : son tableau, à régler ici même."""
    return f"{PAGE}?" + urlencode({"detail": key, "regler": "1"}) + "#t-agenda"


def routes(ui: UI) -> list[Route]:
    async def agenda(request: Request) -> Response:
        return await agenda_table_post(ui, request)

    return [Route(AGENDA_TABLE, ui.guarded(agenda), methods=["POST"])]


#: sa sorte dans Réglages › Droits : chaque agenda, son tableau (ADR 0309) — le lire, y écrire, répondre à ses
#: invitations, ce qu'elle en garde —, réglé ici même ; ce qu'une personne a de chacun, rangé sous « agendas »
SORT = RightsSort("agendas", title="Agendas",
                  hint="le lire, y écrire, répondre à ses invitations : son propriétaire et ses partages",
                  prefix="agenda:", sort="agendas", edit=edit, editor=agenda_editor, routes=routes,
                  named="La fiche de l'agenda")
