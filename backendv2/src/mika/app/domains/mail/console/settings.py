"""Sa rubrique de réglages (ADR 0173, 0185, 0206, 0238, 0310) : dans le Courrier, derrière sa roue (Courrier ›
Paramètres) — ses boîtes aux lettres, l'application Microsoft de l'instance, et les paramètres du plugin sur la même
page (``templates/handmade/courrier/parametres.html``)."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

from mika.adapters.mail import MailConfig
from mika.adapters.mail.config import MailAccount
from mika.app.connections import ConnectionSettings
from mika.app.domains.mail.settings import MailSettings
from mika.app.handmade import ago
from mika.app.settings_sections.common import owner_words, owners
from mika.inspector.catalog import SettingsPage, SettingsSection
from mika.inspector.pages.settings_form import RECORD_KEY
from mika.inspector.pages.subjects import subject_url
from mika.inspector.ui import PREFIX
from mika.kernel.inspect import Ref, plural
from mika.plugins.email.inspect.common import VOICE_LABEL
from mika.plugins.email.inspect.common import owner_name as mailbox_owner

log = logging.getLogger("mika.reglages")


def sections(live: Any) -> tuple[SettingsSection, ...]:
    """Sa rubrique de réglages, pour ce serveur (``live`` : ses réglages, son noyau, ses comptes)."""
    settings = live.settings
    own, apps = settings.of(MailSettings), settings.of(ConnectionSettings)

    def mail_owners() -> list[tuple[str, str]]:
        """À qui une boîte peut être (ADR 0185) : toi, elle, ou une personne qui a un compte."""
        return owners(live)

    def mail() -> MailConfig:
        """Ses boîtes, et l'application Microsoft propre à l'instance, gardée à part d'elles (ADR 0238)."""
        return own.email().model_copy(update={"microsoft_app": apps.own_microsoft_application()})

    async def save_mail(cfg: MailConfig) -> list[str]:
        """Une boîte est à toi, à elle ou à une personne qui a un compte (ADR 0185) — sauf ce qui était déjà là (un
        compte fermé depuis reste affiché, pour qu'on le corrige)."""
        before, known = own.email().accounts, {v for v, _ in mail_owners()}
        problems = [f"« {name} » : elle est à toi, à elle, ou à une personne qui a un compte."
                    for name, a in cfg.accounts.items()
                    if a.owner not in known and (name not in before or before[name].owner != a.owner)]
        if problems:
            return problems
        await own.save_email(cfg)
        # l'application Microsoft de l'instance se garde à part des comptes (ADR 0238)
        if cfg.microsoft_app != apps.own_microsoft_application():
            await apps.save_microsoft_application(cfg.microsoft_app)
        # ce que ses proposeurs lisent (les comptes où elle prépare des réponses) est un réglage journalisé
        problems = await live.reconfigure()
        if problems:  # le courrier est enregistré ; seuls ses paramètres attendent la prochaine reconfiguration
            log.warning("courrier enregistré, paramètres non rejournalisés : %s", "; ".join(problems))
        return []

    async def mail_folders(values: Any) -> list[tuple[str, str]]:
        """Les dossiers d'une boîte enregistrée, lus sur son serveur avec sa connexion, à cocher (la liste
        gardée pour la console se relit du même coup)."""
        port = live.kernel.ports.get("mail") if live.kernel is not None else None
        key = str(values.get(RECORD_KEY) or "")
        if port is None or not key or port.account(key) is None:
            raise ValueError("enregistre d'abord la boîte : ses dossiers se lisent sur son serveur, avec ce qui est "
                             "enregistré")
        try:
            found = await port.refresh_folders(key)
        except (OSError, RuntimeError, EOFError) as exc:
            raise ValueError(str(exc)[:200] or type(exc).__name__) from None
        return [(f.name, f.name if f.label == f.name else f"{f.label} ({f.name})") for f in found]

    def describe_mailbox(key: str, account: MailAccount) -> dict[str, Any]:
        """La carte d'une boîte (Courrier › Paramètres, ADR 0173) : où elle en est, son adresse, comment elle lit et
        envoie, sa voix, ce que dit son dernier relevé — et où la lire."""
        port = live.kernel.ports.get("mail") if live.kernel is not None else None
        status = port.status(key) if port is not None and port.account(key) is not None else None
        if not account.enabled:
            tags = [("inactive", "")]
        elif not account.ready:
            tags = [("incomplète", "warn")]
        elif status is not None and status.error:
            tags = [("en erreur", "danger")]
        else:
            tags = [("prête", "ok")]
        tags.append((f"elle y écrit {VOICE_LABEL.get(account.voice, account.voice)}", "info"))
        if account.owner:  # à qui elle est, quand ce n'est pas à toi (ADR 0185)
            tags.append((f"à {owner_words(live, account.owner, mailbox_owner)}", "owner"))
        if account.microsoft:
            tags.append(("compte Microsoft", ""))
        reads = f"{account.imap_host} · {account.user}" if account.imap_host else "pas de serveur IMAP"
        facts = [("Lire", reads), ("Envoyer", account.smtp_host or "rien : elle ne fait que lire"),
                 ("Dossiers relevés", ", ".join(account.folders))]
        now = live.kernel.mind.clock.now() if live.kernel is not None else 0
        if status is not None and status.error:
            activity, tone = f"Dernière erreur : {status.error}"[:300], "danger"
        elif status is not None and status.last_poll:
            activity, tone = f"Relevée {ago(now, status.last_poll)}", ""
        else:
            activity, tone = "Jamais relevée encore", ""
        return {"title": account.label or key, "tags": tags, "lead_label": "Adresse", "lead": account.address or "—",
                "lead_plain": True, "facts": facts, "activity": activity, "activity_tone": tone,
                "fiche": subject_url("compte", key), "box": f"{PREFIX}/courrier/reception?" + urlencode({"compte": key})}

    def mail_facts() -> list[tuple[str, Any]]:
        accounts = own.email().accounts
        ready = sum(1 for a in accounts.values() if a.ready)
        return [("Comptes", f"{len(accounts)} ({plural(ready, 'prête à relever', 'prêtes à relever')})"
                 if accounts else "aucun"),
                # ADR 0238 : une boîte Microsoft entre par elle, sans donner la sienne
                ("Application Microsoft", apps.own_microsoft_application() or "celle livrée d'origine"),
                ("Lire et envoyer", Ref("local", f"{PREFIX}/courrier/reception", "Courrier › Réception"))]

    return (
        SettingsSection("courrier", "Courrier", "plugins", MailConfig, mail, save_mail, lock=settings.writing,
                        description="Ses boîtes aux lettres (IMAP pour lire et ranger, SMTP pour envoyer) et, pour "
                                    "chacune, sa façon d'y écrire. Relues à chaque relève.", order=10,
                        facts=mail_facts, fixed_names=("accounts",), describe={"accounts": describe_mailbox},
                        loaders={"folders": mail_folders}, named_loaders=("folders",),
                        choices={"accounts.owner": mail_owners},
                        # ses paramètres vivent dans le Courrier, en haut à droite : ses boîtes et ses paramètres
                        # généraux (relevé, ce qu'elle en dit, ses brouillons), sur une seule page (ADR 0173)
                        pages=(SettingsPage("boites", "Paramètres", ("accounts", "microsoft_app"), description=(
                            "Ses boîtes aux lettres — lire (IMAP), envoyer (SMTP), sa voix dans chacune —, l'application "
                            "Microsoft par laquelle entrent les boîtes Hotmail et Outlook.com, et ce que "
                            "fait le courrier de toutes : son relevé, ce qu'elle en dit, les réponses qu'elle "
                            "prépare."), home="courrier/parametres", params="email",
                            template="handmade/courrier/parametres.html", styles=("handmade/courrier_reglages.css",)),)),
    )
