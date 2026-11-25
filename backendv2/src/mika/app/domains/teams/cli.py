"""``mika teams`` (ADR 0069, 0186, 0300, 0310) : Teams hors ligne — la clé de l'extension d'un compte (neuve, montrée
une fois ; retirée), l'état de chaque compte, et l'effacement de ce que l'extension d'un compte a apporté (serveur
arrêté). Il lit l'annuaire : ce qu'un compte y a fait voir part avec lui."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from mika.adapters.contacts import ContactsStore
from mika.adapters.system import RealClock
from mika.adapters.teams import TeamsStore
from mika.app import datadir, schema
from mika.app.cli.common import _with_settings
from mika.app.domains.teams.desk import TeamsDesk
from mika.app.domains.teams.settings import TeamsSettings
from mika.app.settings import Settings
from mika.ports.teams import DEFAULT_ACCOUNT as DEFAULT_TEAMS_ACCOUNT


async def teams_command(settings: Settings, args: argparse.Namespace) -> dict[str, object]:
    """Teams (ADR 0069, 0186) hors ligne : la clé de l'extension d'un compte (neuve, montrée une fois ; retirée), et
    l'état de chaque compte."""
    desk = TeamsDesk(settings.of(TeamsSettings), RealClock().now, None)
    account = getattr(args, "compte", "") or DEFAULT_TEAMS_ACCOUNT
    if args.teams_cmd == "key":
        try:
            key = await desk.new_key(account, "ligne de commande")
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "compte": account, "key": key,
                "usage": "à coller dans l'extension de navigateur de ce compte ; Authorization: Bearer <clé> sur "
                         "/api/teams/…"}
    if args.teams_cmd == "revoke":
        return {"ok": await desk.revoke_key(account), "compte": account}
    if args.teams_cmd == "purge":
        return purge_teams(args.data, settings, account)
    cfg = settings.of(TeamsSettings).teams()
    teams_rules = [a.model_dump() for a in settings.canals().table("teams").lines]
    accounts = {}
    for name, a in sorted(cfg.accounts.items()):
        key = desk.key_state(name)
        accounts[name] = {"label": a.label, "owner": a.owner or "toi", "sign": a.sign,
                          "key": f"{key.hint}…" if key is not None else None}
    return {"ok": True, "enabled": cfg.enabled, "comptes": accounts, "envoi": teams_rules}


def purge_teams(data: Path, settings: Settings, account: str) -> dict[str, object]:
    """``mika teams purge`` (serveur arrêté) : tout ce que l'extension d'un compte a apporté s'efface — conversations,
    messages et leurs réactions, images, brouillons, profils, photos (ADR 0300) — et ses vues dans l'annuaire avec
    (ADR 0298 : sinon le rechargement les compterait deux fois). Sa clé reste : on recharge ensuite tout l'historique
    depuis l'extension, plutôt que de convertir ce qui avait été rangé de travers."""
    datadir.hold(data)
    try:
        bases = schema.targets(data)
        schema.migrate_data(data, bases)
        now = RealClock().now
        teams, contacts = TeamsStore(settings.of(TeamsSettings).teams, bases["teams"], now=now), ContactsStore(bases["contacts"], now=now)
        try:
            rows, seen = teams.drop_account(account), contacts.drop_source("teams", account)
        finally:
            teams.close()
            contacts.close()
    finally:
        datadir.release(data)
    return {"ok": True, "compte": account, "lignes_teams": rows, "vues_annuaire": seen,
            "ensuite": "relancer le serveur, recharger l'extension et l'onglet Teams, puis « Charger tout l'historique »"}


def _run_teams(args: argparse.Namespace) -> int:
    out = asyncio.run(_with_settings(args.data, lambda settings, _store: teams_command(settings, args)))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok", True) else 1


def add(sub) -> None:  # type: ignore[no-untyped-def]
    """Sa commande et ses sous-commandes, dans l'analyseur de ``mika``."""
    tm = sub.add_parser("teams", help="l'extension Teams (ADR 0069) : sa clé et l'état")
    tmsub = tm.add_subparsers(dest="teams_cmd", required=True)
    tmk = tmsub.add_parser("key", help="une clé neuve pour l'extension d'un compte (l'ancienne ne vaut plus), montrée "
                                       "une fois")
    tmk.add_argument("--compte", default=DEFAULT_TEAMS_ACCOUNT, help="le compte Teams (par défaut : principal)")
    tmr = tmsub.add_parser("revoke", help="retirer la clé de l'extension d'un compte (plus rien ne passe pour lui)")
    tmr.add_argument("--compte", default=DEFAULT_TEAMS_ACCOUNT, help="le compte Teams (par défaut : principal)")
    tmp = tmsub.add_parser("purge", help="effacer ce que l'extension d'un compte a apporté (sa clé reste ; serveur "
                                         "arrêté), puis recharger l'historique depuis l'extension")
    tmp.add_argument("--compte", default=DEFAULT_TEAMS_ACCOUNT, help="le compte Teams (par défaut : principal)")
    tmsub.add_parser("status", help="l'état de Teams, sans secret")
    tm.set_defaults(run=_run_teams)
