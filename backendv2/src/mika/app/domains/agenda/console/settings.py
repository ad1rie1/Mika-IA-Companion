"""Sa rubrique de réglages (ADR 0206, 0309, 0310) : dans Agendas, derrière sa roue (Agendas › Paramètres) — les
applications par lesquelles entrent les agendas Google et Microsoft de ce serveur, et les paramètres du plugin sur la
même page (``templates/handmade/agendas/parametres.html``). L'application Microsoft est celle du courrier (ADR 0238) :
elle se lit et s'enregistre dans les réglages du serveur."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, field_validator

from mika.adapters.signin.google import google_client_id
from mika.adapters.signin.microsoft import application_id
from mika.app.domains.agenda.settings import AgendaSettings
from mika.app.domains.mail.settings import MailSettings
from mika.inspector.catalog import SettingsPage, SettingsSection
from mika.inspector.ui import PREFIX
from mika.kernel.forms import Knob
from mika.kernel.inspect import Ref


class AgendaApps(BaseModel):
    """Les applications par lesquelles entrent les agendas branchés (ADR 0309) : celle de Google, une par serveur, et
    celle de Microsoft, la même que pour le courrier (ADR 0238)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    google_client_id: Annotated[str, Knob(
        label="Identifiant client", group="Application Google", advanced=False, order=10,
        help="Celui d'un client « Application de bureau » de ton projet Google Cloud (…apps.googleusercontent.com). "
             "Vide : Google ne se branche pas sur ce serveur.")] = ""
    google_secret: Annotated[str, Knob(
        label="Secret client", group="Application Google", secret=True, advanced=False, order=20,
        help="Scellé : il ne se relit plus. Vide : inchangé. Changer d'application demande de reconnecter les comptes "
             "Google.")] = ""
    google_web: Annotated[bool, Knob(
        label="Un client « Application Web » (retour direct)", group="Application Google", order=30,
        help="Avec une adresse HTTPS déclarée chez Google, le retour du consentement revient ici seul ; sinon on colle "
             "l'adresse où Google renvoie (http://127.0.0.1/…?code=…).")] = False
    microsoft_app: Annotated[str, Knob(
        label="Application Microsoft (client ID)", group="Application Microsoft", advanced=False, order=40,
        help="Vide : celle livrée d'origine. La même que celle des boîtes (Courrier › Paramètres › Compte Microsoft) : "
             "un seul réglage pour les deux. Pour l'agenda, elle demande en plus Calendars.ReadWrite au moment de se "
             "connecter. La changer demande de reconnecter les boîtes et les agendas qui entraient par elle.")] = ""

    @field_validator("google_client_id")
    @classmethod
    def _google(cls, client_id: str) -> str:
        return google_client_id(client_id)

    @field_validator("microsoft_app")
    @classmethod
    def _microsoft(cls, client_id: str) -> str:
        return application_id(client_id)


def sections(live: Any) -> tuple[SettingsSection, ...]:
    """Sa rubrique de réglages, pour ce serveur (``live`` : ses réglages)."""
    settings = live.settings

    def agenda_apps() -> AgendaApps:
        """L'application Google du serveur (son secret ouvert) et celle de Microsoft, propre à l'instance (ADR 0238)."""
        google = settings.of(AgendaSettings).google_application()
        return AgendaApps(google_client_id=google.client_id if google is not None else "",
                          google_secret=google.secret if google is not None else "",
                          google_web=bool(google.web) if google is not None else False,
                          microsoft_app=settings.of(MailSettings).own_mail_application())

    async def save_agenda_apps(cfg: AgendaApps) -> list[str]:
        """L'application Google (un secret vide garde celui de la même application) ; celle de Microsoft, partagée
        avec le courrier."""
        if cfg.google_client_id and not cfg.google_secret:
            known = settings.of(AgendaSettings).google_application()
            if known is None or known.client_id != cfg.google_client_id:
                return ["Le secret client de cette application Google, avec son identifiant."]
        try:
            await settings.of(AgendaSettings).save_google_application(cfg.google_client_id, cfg.google_secret, web=cfg.google_web)
        except ValueError as exc:
            return [str(exc)]
        if cfg.microsoft_app != settings.of(MailSettings).own_mail_application():
            await settings.of(MailSettings).save_mail_application(cfg.microsoft_app)
        return []

    def agenda_facts() -> list[tuple[str, Any]]:
        accounts = settings.of(AgendaSettings).agenda().accounts
        google = sum(1 for a in accounts.values() if a.kind == "google")
        microsoft = sum(1 for a in accounts.values() if a.kind == "microsoft")
        return [("Application Google", "réglée" if settings.of(AgendaSettings).google_application() is not None else "pas réglée"),
                ("Comptes Google", str(google)), ("Comptes Microsoft", str(microsoft)),
                ("Les comptes eux-mêmes", Ref("local", f"{PREFIX}/agendas/comptes", "Agendas › Comptes"))]

    return (
        # les agendas (ADR 0309, lot 5) : dans Agendas, en haut à droite (ADR 0206) — leurs applications, et les
        # paramètres du plugin (la synchronisation, les rappels par défaut) sur la même page
        SettingsSection("agendas", "Agendas", "plugins", AgendaApps, agenda_apps, save_agenda_apps, order=13,
                        lock=settings.writing, facts=agenda_facts,
                        description="Les applications par lesquelles entrent les agendas Google et Microsoft de ce "
                                    "serveur, ce que la synchronisation relit et à quel rythme, et le rappel qu'elle "
                                    "propose d'office.",
                        pages=(SettingsPage("agendas", "Paramètres", description=(
                            "Les applications par lesquelles entrent les agendas Google et Microsoft de ce serveur, ce "
                            "que la synchronisation relit et à quel rythme, et le rappel qu'elle propose d'office. "
                            "Les comptes eux-mêmes, chacun les branche dans son espace."), home="agendas/parametres",
                            params="agenda", template="handmade/agendas/parametres.html",
                            styles=("handmade/agendas.css", "handmade/courrier_reglages.css")),)),
    )
