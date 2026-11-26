"""``mika mail`` (ADR 0027, 0166, 0238, 0310) : ses boîtes aux lettres hors ligne — créer ou modifier un compte, le
retirer, les montrer sans leurs secrets ; et l'application Microsoft par laquelle entrent les boîtes qui n'en
déclarent pas."""

from __future__ import annotations

import argparse
import asyncio
import json

from mika.adapters.mail import LEGACY_ACCOUNT
from mika.app.cli.common import with_settings
from mika.app.domains.mail.settings import MailSettings
from mika.app.settings import Settings


async def mail_command(settings: Settings, args: argparse.Namespace) -> dict[str, object]:
    """Ses boîtes (``set``, ``remove``, ``show``) et l'application Microsoft de l'instance (``application``)."""
    own = settings.of(MailSettings)
    if args.mail_cmd == "set":
        await own.save_mail_account(
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
            await own.save_mail_application("")
        elif args.client_id is not None:
            try:
                await own.save_mail_application(args.client_id)
            except ValueError as exc:
                raise SystemExit(str(exc)) from None
        return {"application": own.mail_application(),
                "par_defaut": not own.own_mail_application()}
    elif args.mail_cmd == "remove":
        cfg = own.email()
        if args.compte not in cfg.accounts:
            raise SystemExit(f"compte inconnu : {args.compte}")
        await own.save_email(cfg.model_copy(update={"accounts": {
            k: a for k, a in cfg.accounts.items() if k != args.compte}}))
    out = {}
    for name, account in own.email().accounts.items():
        shown = account.model_dump(mode="json")
        for secret in ("password", "smtp_password"):
            shown[secret] = "…" if shown[secret] else ""
        out[name] = shown
    return {"accounts": out}


def _run_mail(args: argparse.Namespace) -> int:
    out = asyncio.run(with_settings(args.data, lambda settings, _store: mail_command(settings, args)))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def add(sub) -> None:  # type: ignore[no-untyped-def]
    """Sa commande et ses sous-commandes, dans l'analyseur de ``mika``."""
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
    ml.set_defaults(run=_run_mail)
