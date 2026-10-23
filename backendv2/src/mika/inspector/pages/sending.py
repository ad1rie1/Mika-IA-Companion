"""Relations & échanges › Envoyer à ta place (ADR 0132) : ses règles d'envoi, courrier et Teams, en un tableau lu
de haut en bas — canal, destinataire, préparer d'elle-même, comment ça part —, puis la règle par défaut, obligatoire.

Les règles se rangent dans les réglages (``Settings.sending``) et passent aux paramètres du courrier et de Teams
(journalisés : sa vie se rejoue) ; chaque bouton envoie tout le tableau, rien de ce qu'on a changé ne se perd.
"""

from __future__ import annotations

import secrets as _secrets
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlencode

from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from mika.inspector import render
from mika.inspector.catalog import Panel
from mika.inspector.pages.tabs import TABS
from mika.inspector.ui import PREFIX, secure
from mika.kernel.inspect import Pager
from mika.runtime import operations as ops
from mika.vocab.sending import MAIL, TEAMS, Sending, SendRule

BASE = f"{PREFIX}/envoi"
#: comment ça part, dans un sélecteur
SEND_CHOICES = (("brouillon", "Brouillon (tu l'envoies)"), ("accord", "Ton accord"), ("seule", "Seule"))
#: au plus tant de règles (un tableau qu'on lit d'un regard)
MAX_RULES = 40
#: la règle qu'on ajoute : le courrier, tout le monde, elle prépare, ton accord
NEW_RULE = SendRule(canal=MAIL, prepare=True, send="accord")


def _channels(settings: Any) -> list[tuple[str, str]]:
    """Les canaux qu'une règle peut viser : le courrier (toutes ses boîtes, puis chacune), Teams."""
    out = [(MAIL, "Courrier — toutes les boîtes")]
    try:
        accounts = settings.email().accounts if settings is not None else {}
    except Exception:  # noqa: BLE001 — des boîtes illisibles : « toutes les boîtes » reste
        accounts = {}
    out += [(f"{MAIL}:{key}", f"Courrier — {a.label or key}") for key, a in sorted(accounts.items())]
    return [*out, (TEAMS, "Teams")]


@TABS.tab("envoi.regles", title="Envoyer à ta place",
          description="Ce qu'elle prépare d'elle-même et comment ça part, courrier et Teams : des règles lues de "
                      "haut en bas, puis la règle par défaut.")
async def rules_page(ui: Any, request: Request) -> Any:
    settings = ui.deps.settings
    try:
        cfg = settings.sending() if settings is not None else Sending()
    except Exception:  # noqa: BLE001 — des règles illisibles : la règle par défaut seule, jamais une page cassée
        cfg = Sending()
    channels = _channels(settings)
    known = {k for k, _ in channels}
    rows = []
    for n, r in enumerate(cfg.rules, start=1):
        options = channels if r.canal in known else [*channels, (r.canal, r.canal)]
        rows.append({"n": n, "canal": r.canal, "channels": options, "dest": r.dest, "prepare": r.prepare,
                     "send": r.send, "mail": r.canal.startswith(MAIL), "first": n == 1, "last": n == len(cfg.rules)})
    return {"blocks": [], "panel": Panel("handmade/envoi/regles.html", {
        "rows": rows, "default": cfg.default, "sends": SEND_CHOICES, "action": f"{BASE}/regler",
        # une seule page (au plus ``MAX_RULES`` règles), que la pagination dit comme partout
        "pager": render._pager(Pager(size=len(rows) + 1, total=len(rows) + 1), {}),
        "writable": settings is not None}, styles=("handmade/tools.css",))}


def _number(key: str) -> int:
    return int(key) if key.isdigit() else 10**6


def parse(data: Mapping[str, str]) -> tuple[list[SendRule], SendRule]:
    """Le tableau envoyé : ses règles dans l'ordre (``canal.<n>``, ``dest.<n>``, ``prepare.<n>``, ``send.<n>``) et
    la règle par défaut ; lève ``ValueError`` (en français) sur une règle illisible."""
    keys = sorted((k.partition(".")[2] for k in data if k.startswith("canal.")), key=_number)
    rules = []
    for n, key in enumerate(keys, start=1):
        try:
            rules.append(SendRule(canal=str(data.get(f"canal.{key}", "")), dest=str(data.get(f"dest.{key}", "")),
                                  prepare=bool(data.get(f"prepare.{key}")),
                                  send=str(data.get(f"send.{key}", "accord"))))  # type: ignore[arg-type]
        except ValidationError:
            raise ValueError(f"Règle {n} illisible : un canal, un destinataire, un envoi parmi ceux proposés.") \
                from None
        if not rules[-1].canal:
            raise ValueError(f"Règle {n} : choisis un canal.")
    try:
        default = SendRule(canal="", prepare=bool(data.get("defaut_prepare")),
                           send=str(data.get("defaut_send", "accord")))  # type: ignore[arg-type]
    except ValidationError:
        raise ValueError("La règle par défaut est illisible.") from None
    return rules, default


def moved(rules: Sequence[SendRule], faire: str) -> tuple[list[SendRule], str]:
    """Ce qu'un bouton demande en plus d'enregistrer : ajouter une règle, en monter, descendre ou retirer une."""
    op, _, at = faire.partition(":")
    i = int(at) - 1 if at.isdigit() else -1
    out = list(rules)
    if op == "ajouter":
        if len(out) >= MAX_RULES:
            raise ValueError(f"{MAX_RULES} règles au plus.")
        out.append(NEW_RULE)
        return out, f"Règle {len(out)} ajoutée : règle-la, puis enregistre."
    if op == "monter" and 0 < i < len(out):
        out[i - 1], out[i] = out[i], out[i - 1]
        return out, f"Règle {i + 1} montée."
    if op == "descendre" and 0 <= i < len(out) - 1:
        out[i], out[i + 1] = out[i + 1], out[i]
        return out, f"Règle {i + 1} descendue."
    if op == "retirer" and 0 <= i < len(out):
        del out[i]
        return out, f"Règle {i + 1} retirée."
    return out, "Règles enregistrées."


async def rules_post(ui: Any, request: Request) -> Response:
    """Ses règles d'envoi enregistrées (``Settings.save_sending``), puis rejournalisées dans les paramètres du
    courrier et de Teams ; auditées."""
    got = await ui.form_lists(request)
    account = ui.operator(request)
    token = _secrets.token_urlsafe(9)
    settings, parameters = ui.deps.settings, ui.deps.parameters
    if got is None or account is None:
        ui.flash(token, "danger", "Jeton de formulaire invalide : recharge la page.")
    elif settings is None:
        ui.flash(token, "warn", "Les réglages ne sont pas joignables : rien n'a été enregistré.")
    else:
        data, _lists = got
        try:
            rules, default = parse(data)
            rules, said = moved(rules, str(data.get("faire", "")))
            await settings.save_sending(Sending(rules=tuple(rules), default=default))
            problems = await parameters.apply() if parameters is not None else []
            await ops.audit(ui.kernel, "console.envoi.regler", by=account.handle, subject_kind="", subject="")
            ui.flash(token, "warn" if problems else "ok", said + (f" ({'; '.join(problems)})" if problems else ""))
        except ValueError as exc:
            ui.flash(token, "danger", str(exc))
    return secure(RedirectResponse(f"{BASE}?" + urlencode({"flash": token}), status_code=303))
