"""Ce qui se branche : ``mail``, ``rss``, ``stt`` (ce qu'elle perçoit du dehors), ``mcp``, ``sensors``, ``teams``, ``wakeup``."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from mika.adapters.mail import LEGACY_ACCOUNT
from mika.adapters.mcp.hub import McpHub
from mika.adapters.system import RealClock
from mika.app.cli.common import _with_settings
from mika.app.settings import Settings
from mika.app.teams import TeamsDesk
from mika.app.wakeups import WakeupDesk
from mika.ports.teams import DEFAULT_ACCOUNT as DEFAULT_TEAMS_ACCOUNT


async def mcp_command(settings: Settings, args: argparse.Namespace) -> dict[str, object]:
    """``mika mcp serveurs`` / ``mika mcp essai <serveur>`` : ce qui est branché, et ce qu'un serveur propose
    maintenant (avec, pour chaque outil, ce que l'opérateur en a décidé). Aucun secret n'est rendu."""
    hub = McpHub(settings.mcp, settings.mcp_tools, settings.save_mcp_tools, local_root=args.data / "mcp")
    try:
        if args.mcp_cmd == "serveurs":
            return {"ok": True, "serveurs": [
                {"nom": n, "ou": s.transport, "actif": s.enabled, "a_quoi": s.purpose,
                 "adresse": s.url if not s.local else s.command,
                 "acces": [{"qui": a.who, "quand": list(a.when) or "toujours", "lecture": a.read, "action": a.act, "garde": a.keep,
                            "outils": list(a.tools) or "tous"} for a in s.access],
                 "par_defaut": {"lecture": s.default_read, "action": s.default_act, "garde": s.default_keep},
                 "manque": s.problems()}
                for n, s in sorted(settings.mcp().servers.items())]}
        ok, message = await hub.test(args.serveur)
        status = hub.status(args.serveur)
        tools = []
        for t in status.live if status is not None else ():
            review = status.reviews.get(t.remote) if status is not None else None
            state = ("à regarder" if review is None else "suspendu (changé)" if review.enabled
                     and review.fingerprint != t.fingerprint else "approuvé" if review.enabled else "désactivé")
            tools.append({"outil": t.remote, "description": t.description, "lecture_seule": t.read_only_hint,
                          "etat": state})
        return {"ok": ok, "message": message, "outils": tools}
    finally:
        await hub.aclose()


async def teams_command(settings: Settings, args: argparse.Namespace) -> dict[str, object]:
    """Teams (ADR 0069, 0186) hors ligne : la clé de l'extension d'un compte (neuve, montrée une fois ; retirée), et
    l'état de chaque compte."""
    desk = TeamsDesk(settings, RealClock().now, None)
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
    cfg = settings.teams()
    teams_rules = [a.model_dump() for a in settings.canals().table("teams").lines]
    accounts = {}
    for name, a in sorted(cfg.accounts.items()):
        key = desk.key_state(name)
        accounts[name] = {"label": a.label, "owner": a.owner or "toi", "sign": a.sign,
                          "key": f"{key.hint}…" if key is not None else None}
    return {"ok": True, "enabled": cfg.enabled, "comptes": accounts, "envoi": teams_rules}


async def wakeup_command(settings: Settings, args: argparse.Namespace) -> dict[str, object]:
    """Les réveils par API (ADR 0068) hors ligne : les lister, leur donner une clé (montrée une fois), la retirer."""
    desk = WakeupDesk(settings, RealClock().now)
    if args.wakeup_cmd == "list":
        return {"ok": True, "endpoints": [
            {"name": ep.name, "label": ep.label, "enabled": ep.enabled, "project": ep.project or None,
             "plain": ep.plain, "tools": list(ep.bundles), "rouse": ep.rouse, "notify": ep.notify,
             "signed": ep.signed, "fields": list(ep.fields),
             "key": f"{ep.key.hint}…" if ep.key is not None else None} for ep in desk.endpoints()]}
    if args.wakeup_cmd == "key":
        try:
            key = await desk.new_key(args.name, "ligne de commande")
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        usage = f"POST /api/wake/{args.name} avec l'en-tête Authorization: Bearer <clé>"
        ep = desk.endpoint(args.name)
        if ep is not None and ep.signed:
            usage += " — ou le corps signé par la clé (X-Hub-Signature-256 : le « secret » d'un webhook GitHub)"
        return {"ok": True, "name": args.name, "key": key, "usage": usage}
    if not await desk.revoke_key(args.name):
        return {"ok": False, "error": f"« {args.name} » n'a pas de clé."}
    return {"ok": True, "name": args.name, "revoked": True}


async def outside_command(data: Path, args: argparse.Namespace) -> dict[str, object]:
    """Le courrier, les flux, la transcription : ce qu'elle perçoit du monde."""

    async def run(settings: Settings, store) -> dict[str, object]:  # type: ignore[no-untyped-def]
        if args.cmd == "mail":
            if args.mail_cmd == "set":
                await settings.save_mail_account(
                    args.compte, address=args.address, imap_host=args.imap_host, imap_port=args.imap_port,
                    imap_ssl=None if args.imap_ssl is None else args.imap_ssl == "oui", user=args.user,
                    password=args.password, smtp_host=args.smtp_host, smtp_port=args.smtp_port,
                    smtp_security=args.smtp_security, since_days=args.since_days,
                    folders=tuple(args.dossiers) if args.dossiers else None,
                    sync_all=None if args.tous_les_dossiers is None else args.tous_les_dossiers == "oui",
                    voice=args.voix,
                    display_name=args.nom, auth=args.auth, oauth_client_id=args.client_id, oauth_tenant=args.tenant)
            elif args.mail_cmd == "remove":
                cfg = settings.email()
                if args.compte not in cfg.accounts:
                    raise SystemExit(f"compte inconnu : {args.compte}")
                await settings.save_email(cfg.model_copy(update={"accounts": {
                    k: a for k, a in cfg.accounts.items() if k != args.compte}}))
            out = {}
            for name, account in settings.email().accounts.items():
                shown = account.model_dump(mode="json")
                for secret in ("password", "smtp_password"):
                    shown[secret] = "…" if shown[secret] else ""
                out[name] = shown
            return {"accounts": out}
        if args.cmd == "rss":
            feeds = settings.feeds()
            if args.rss_cmd == "add":
                feeds = await settings.save_feeds([*feeds, *args.urls])
            elif args.rss_cmd == "remove":
                feeds = await settings.save_feeds([f for f in feeds if f not in args.urls])
            return {"feeds": feeds}
        if args.stt_cmd == "set":
            await settings.save_stt(args.base_url, args.api_key, args.model)
        cfg = settings.stt()
        return {"base_url": cfg["base_url"], "model": cfg["model"], "api_key": "…" if cfg["api_key"] else ""}

    return await _with_settings(data, run)


def _run_outside(args: argparse.Namespace) -> int:
    print(json.dumps(asyncio.run(outside_command(args.data, args)), ensure_ascii=False, indent=2))
    return 0


def _run_mcp(args: argparse.Namespace) -> int:
    if args.mcp_cmd in ("serveurs", "essai"):
        out = asyncio.run(_with_settings(args.data, lambda settings, _store: mcp_command(settings, args)))
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if out.get("ok", True) else 1

    async def mcp_token(settings: Settings, store) -> dict[str, object]:  # type: ignore[no-untyped-def]
        token = await settings.new_console_mcp_token()
        return {"token": token, "usage": "claude mcp add --transport http mika http://127.0.0.1:8001/mcp/console/ "
                                          f"--header \"Authorization: Bearer {token}\""}

    print(json.dumps(asyncio.run(_with_settings(args.data, mcp_token)), ensure_ascii=False, indent=2))
    return 0


def _run_sensors(args: argparse.Namespace) -> int:
    async def token(settings: Settings, store) -> dict[str, object]:  # type: ignore[no-untyped-def]
        return {"token": await settings.new_sensors_token(),
                "usage": "Authorization: Bearer <jeton> sur POST /api/perceptions"}

    print(json.dumps(asyncio.run(_with_settings(args.data, token)), ensure_ascii=False, indent=2))
    return 0


def _run_teams(args: argparse.Namespace) -> int:
    out = asyncio.run(_with_settings(args.data, lambda settings, _store: teams_command(settings, args)))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok", True) else 1


def _run_wakeup(args: argparse.Namespace) -> int:
    out = asyncio.run(_with_settings(args.data, lambda settings, _store: wakeup_command(settings, args)))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok", True) else 1


def add_plugins(sub) -> None:  # type: ignore[no-untyped-def]
    ml = sub.add_parser("mail", help="sa boîte aux lettres (IMAP pour lire, SMTP pour envoyer)")
    msub = ml.add_subparsers(dest="mail_cmd", required=True)
    msub.add_parser("show")
    ms = msub.add_parser("set", help="crée ou modifie un compte")
    ms.add_argument("--compte", default=LEGACY_ACCOUNT, help="le nom court du compte (défaut : principal)")
    ms.add_argument("--address")
    ms.add_argument("--imap-host")
    ms.add_argument("--imap-port", type=int)
    ms.add_argument("--imap-ssl", choices=["oui", "non"])
    ms.add_argument("--auth", choices=["password", "microsoft"],
                    help="microsoft : Hotmail, Outlook.com (OAuth2, ADR 0166) ; on se connecte ensuite depuis la "
                         "fiche de la boîte, dans la console")
    ms.add_argument("--client-id", help="l'application Microsoft (client ID), avec --auth microsoft")
    ms.add_argument("--tenant", help="l'annuaire Microsoft (défaut : consumers, les comptes personnels)")
    ms.add_argument("--user")
    ms.add_argument("--password")
    ms.add_argument("--smtp-host")
    ms.add_argument("--smtp-port", type=int)
    ms.add_argument("--smtp-security", choices=["ssl", "starttls", "none"])
    ms.add_argument("--since-days", type=int)
    ms.add_argument("--dossiers", nargs="+", help="les dossiers relevés (défaut : INBOX)")
    ms.add_argument("--tous-les-dossiers", choices=["oui", "non"],
                    help="tenir aussi les autres dossiers à jour à chaque relève (elle ne remarque que les relevés)")
    ms.add_argument("--voix", choices=["elle", "assistante", "proprietaire"])
    ms.add_argument("--nom", help="ton nom (pour écrire en assistante ou à ta place)")
    mr = msub.add_parser("remove", help="retire un compte")
    mr.add_argument("--compte", required=True)
    rs = sub.add_parser("rss", help="les flux qu'elle suit")
    rsub = rs.add_subparsers(dest="rss_cmd", required=True)
    rsub.add_parser("list")
    for name in ("add", "remove"):
        r = rsub.add_parser(name)
        r.add_argument("urls", nargs="+")
    st = sub.add_parser("stt", help="la transcription des messages vocaux (/audio/transcriptions)")
    stsub = st.add_subparsers(dest="stt_cmd", required=True)
    stsub.add_parser("show")
    sts = stsub.add_parser("set")
    sts.add_argument("base_url")
    sts.add_argument("api_key")
    sts.add_argument("--model", default="whisper-1")
    mc = sub.add_parser("mcp", help="la lire depuis ton Claude Code (point /mcp/console, lecture seule)")
    mcsub = mc.add_subparsers(dest="mcp_cmd", required=True)
    mcsub.add_parser("token", help="un jeton neuf (l'ancien ne vaut plus), montré une fois")
    mcsub.add_parser("serveurs", help="les serveurs MCP branchés (ADR 0064) et leurs réglages, sans secret")
    mce = mcsub.add_parser("essai", help="joindre un serveur MCP branché et lister ses outils (rien n'est approuvé)")
    mce.add_argument("serveur")
    se = sub.add_parser("sensors", help="le jeton des appareils (POST /api/perceptions)")
    sesub = se.add_subparsers(dest="sensors_cmd", required=True)
    sesub.add_parser("token", help="un jeton neuf (l'ancien ne vaut plus), montré une fois")
    tm = sub.add_parser("teams", help="l'extension Teams (ADR 0069) : sa clé et l'état")
    tmsub = tm.add_subparsers(dest="teams_cmd", required=True)
    tmk = tmsub.add_parser("key", help="une clé neuve pour l'extension d'un compte (l'ancienne ne vaut plus), montrée "
                                       "une fois")
    tmk.add_argument("--compte", default=DEFAULT_TEAMS_ACCOUNT, help="le compte Teams (par défaut : principal)")
    tmr = tmsub.add_parser("revoke", help="retirer la clé de l'extension d'un compte (plus rien ne passe pour lui)")
    tmr.add_argument("--compte", default=DEFAULT_TEAMS_ACCOUNT, help="le compte Teams (par défaut : principal)")
    tmsub.add_parser("status", help="l'état de Teams, sans secret")
    wk = sub.add_parser("wakeup", help="les réveils par API (POST /api/wake/<nom>, ADR 0068 ; serveur arrêté)")
    wksub = wk.add_subparsers(dest="wakeup_cmd", required=True)
    wksub.add_parser("list", help="les réveils déclarés et l'état de leur clé, sans secret")
    wkk = wksub.add_parser("key", help="une clé neuve pour un réveil (l'ancienne ne vaut plus), montrée une fois")
    wkk.add_argument("name")
    wkr = wksub.add_parser("revoke", help="retirer la clé d'un réveil (plus aucun appel ne passe)")
    wkr.add_argument("name")
    for parser in (ml, rs, st):
        parser.set_defaults(run=_run_outside)
    mc.set_defaults(run=_run_mcp)
    se.set_defaults(run=_run_sensors)
    tm.set_defaults(run=_run_teams)
    wk.set_defaults(run=_run_wakeup)
