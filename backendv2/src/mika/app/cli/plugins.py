"""Ce qui se branche : ``mail``, ``stt`` (ce qu'elle perçoit du dehors), ``sensors``, ``teams``, ``agenda`` ;
puis la commande de chaque domaine qui a la sienne (``Domain.cli``, ADR 0310)."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from mika.adapters.agenda.oauth import RETURN_PATH
from mika.adapters.contacts import ContactsStore
from mika.adapters.mail import LEGACY_ACCOUNT
from mika.adapters.system import RealClock
from mika.adapters.teams import TeamsStore
from mika.app import datadir, schema
from mika.app.cli.common import _with_settings
from mika.app.domains import DOMAINS, part
from mika.app.settings import Settings
from mika.app.teams import TeamsDesk
from mika.ports.teams import DEFAULT_ACCOUNT as DEFAULT_TEAMS_ACCOUNT


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
    if args.teams_cmd == "purge":
        return purge_teams(args.data, settings, account)
    cfg = settings.teams()
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
        teams, contacts = TeamsStore(settings.teams, bases["teams"], now=now), ContactsStore(bases["contacts"], now=now)
        try:
            rows, seen = teams.drop_account(account), contacts.drop_source("teams", account)
        finally:
            teams.close()
            contacts.close()
    finally:
        datadir.release(data)
    return {"ok": True, "compte": account, "lignes_teams": rows, "vues_annuaire": seen,
            "ensuite": "relancer le serveur, recharger l'extension et l'onglet Teams, puis « Charger tout l'historique »"}


async def outside_command(data: Path, args: argparse.Namespace) -> dict[str, object]:
    """Le courrier, la transcription : ce qu'elle perçoit du monde."""

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
                    keep_all=None if args.tout_en_local is None else args.tout_en_local == "oui",
                    voice=args.voix,
                    display_name=args.nom, auth=args.auth, oauth_client_id=args.client_id, oauth_tenant=args.tenant)
            elif args.mail_cmd == "application":
                if args.defaut:
                    await settings.save_mail_application("")
                elif args.client_id is not None:
                    try:
                        await settings.save_mail_application(args.client_id)
                    except ValueError as exc:
                        raise SystemExit(str(exc)) from None
                return {"application": settings.mail_application(),
                        "par_defaut": not settings.own_mail_application()}
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
        if args.stt_cmd == "set":
            await settings.save_stt(args.base_url, args.api_key, args.model)
        cfg = settings.stt()
        return {"base_url": cfg["base_url"], "model": cfg["model"], "api_key": "…" if cfg["api_key"] else ""}

    return await _with_settings(data, run)


async def agenda_command(settings: Settings, args: argparse.Namespace) -> dict[str, object]:
    """``mika agenda google`` (ADR 0309, lot 2) : l'application Google du serveur — un client OAuth d'un projet Google
    Cloud, « Application de bureau » (ou « Application Web » avec ``--web``) —, la poser, l'effacer (``--defaut``) ou
    la montrer, jamais son secret. En changer demande de reconnecter les comptes Google."""
    if args.defaut:
        await settings.save_google_application("")
    elif args.client_id is not None:
        try:
            await settings.save_google_application(args.client_id, args.secret or "", web=args.web)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
    app = settings.google_application()
    if app is None:
        return {"ok": True, "application": None,
                "usage": "mika agenda google <identifiant>.apps.googleusercontent.com --secret GOCSPX-…"}
    return {"ok": True, "application": app.client_id, "secret": "…", "type": "web" if app.web else "bureau",
            "retour": f"https://<origine du serveur>{RETURN_PATH}" if app.web else "http://127.0.0.1:<port>/ (on colle "
                                                                                 "l'adresse)"}


def _run_outside(args: argparse.Namespace) -> int:
    print(json.dumps(asyncio.run(outside_command(args.data, args)), ensure_ascii=False, indent=2))
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


def _run_agenda(args: argparse.Namespace) -> int:
    out = asyncio.run(_with_settings(args.data, lambda settings, _store: agenda_command(settings, args)))
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
    ms.add_argument("--client-id", help="une application Microsoft propre à cette boîte (client ID), avec --auth "
                                        "microsoft ; sans elle, celle de l'instance, ou celle livrée d'origine")
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
    ms.add_argument("--tout-en-local", choices=["oui", "non"],
                    help="tout garder ici, historique compris (ADR 0249) ; non : une recherche demande au serveur")
    ms.add_argument("--voix", choices=["elle", "assistante", "proprietaire"])
    ms.add_argument("--nom", help="ton nom (pour écrire en assistante ou à ta place)")
    ma = msub.add_parser("application", help="l'application Microsoft par laquelle entrent les boîtes Microsoft qui "
                                             "n'en déclarent pas (ADR 0238) : celle livrée d'origine, ou celle "
                                             "de l'instance ; sans argument, la montre")
    ma.add_argument("client_id", nargs="?", help="celle de l'instance : son identifiant (client ID), inscrit dans "
                                                 "Microsoft Entra")
    ma.add_argument("--defaut", action="store_true", help="revient à celle livrée d'origine")
    mr = msub.add_parser("remove", help="retire un compte")
    mr.add_argument("--compte", required=True)
    st = sub.add_parser("stt", help="la transcription des messages vocaux (/audio/transcriptions)")
    stsub = st.add_subparsers(dest="stt_cmd", required=True)
    stsub.add_parser("show")
    sts = stsub.add_parser("set")
    sts.add_argument("base_url")
    sts.add_argument("api_key")
    sts.add_argument("--model", default="whisper-1")
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
    tmp = tmsub.add_parser("purge", help="effacer ce que l'extension d'un compte a apporté (sa clé reste ; serveur "
                                         "arrêté), puis recharger l'historique depuis l'extension")
    tmp.add_argument("--compte", default=DEFAULT_TEAMS_ACCOUNT, help="le compte Teams (par défaut : principal)")
    tmsub.add_parser("status", help="l'état de Teams, sans secret")
    ag = sub.add_parser("agenda", help="les agendas branchés (ADR 0309) : l'application Google du serveur")
    agsub = ag.add_subparsers(dest="agenda_cmd", required=True)
    agg = agsub.add_parser("google", help="l'application Google par laquelle se branchent les comptes Google Agenda "
                                          "(un client OAuth d'un projet Google Cloud) ; sans argument, la montre")
    agg.add_argument("client_id", nargs="?", help="l'identifiant du client (….apps.googleusercontent.com)")
    agg.add_argument("--secret", help="le secret du client (GOCSPX-…), scellé ; omis, celui de la même application "
                                      "reste")
    agg.add_argument("--web", action="store_true",
                     help=f"un client « Application Web » : il revient seul à l'origine HTTPS du serveur ({RETURN_PATH}) "
                          "au lieu qu'on colle l'adresse")
    agg.add_argument("--defaut", action="store_true", help="l'efface : brancher Google est alors refusé")
    ag.set_defaults(run=_run_agenda)
    for parser in (ml, st):
        parser.set_defaults(run=_run_outside)
    se.set_defaults(run=_run_sensors)
    tm.set_defaults(run=_run_teams)
    # puis la commande de chaque domaine qui a la sienne (``Domain.cli``, ADR 0310)
    for domain in DOMAINS:
        if domain.cli is not None:
            part(domain.cli, "add")(sub)
