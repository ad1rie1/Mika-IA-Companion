"""La configuration du courrier : une liste de comptes, chacun avec ses
serveurs, ses dossiers relevés, et **sa voix** (en son nom, en assistante, à
la place de son opérateur ; un ton, des consignes, une signature).

Elle vit dans les réglages (le mot de passe scellé), jamais dans le journal ;
l'adaptateur la relit à chaque appel (changer un compte ne demande pas de
redémarrer). Une ancienne configuration à un seul compte devient le compte
« principal ».

Une boîte entre par mot de passe, ou par un compte Microsoft (Hotmail,
Outlook.com, Live ; Microsoft 365 si son administrateur le permet), où le mot
de passe est refusé : OAuth2 (``oauth``, ADR 0166). Le jeton de cette connexion
n'est pas ici : il est gardé à part, scellé, et ce formulaire ne le touche
jamais.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mika.kernel.forms import Knob
from mika.ports.mail import ACCOUNT_KEY, VOICES, AccountInfo

#: la clé du compte d'une ancienne configuration (un seul compte, sans nom)
LEGACY_ACCOUNT = "principal"
ACCOUNT_KEY_RULE = "des minuscules, chiffres, - ou _ (40 au plus), en commençant par une lettre ou un chiffre"
#: comment une boîte entre : par mot de passe, ou par un compte Microsoft (OAuth2, ADR 0166)
PASSWORD, MICROSOFT = "password", "microsoft"
AUTHS: tuple[tuple[str, str], ...] = ((PASSWORD, "par mot de passe"),
                                      (MICROSOFT, "par un compte Microsoft (Hotmail, Outlook.com, Live)"))
#: l'annuaire Microsoft des comptes personnels (Hotmail, Outlook.com, Live)
CONSUMERS = "consumers"
#: l'identifiant d'une application Microsoft (un GUID) ; un annuaire (``consumers``, ``organizations``, un domaine ou
#: un GUID) : il entre dans l'adresse de Microsoft, rien d'autre n'y passe
_CLIENT_ID = re.compile(r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
_TENANT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,99}$")
#: sans serveur d'envoi, une boîte ne fait que lire : ses réglages d'envoi et sa voix attendent qu'on le donne
_NO_SMTP = (("smtp_host", ("",)),)


class MailAccount(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # Sa page (Courrier › Paramètres) les range par sujet, dans cet ordre : la boîte, comment elle y entre, lire,
    # envoyer, sa voix. Ce qui ne sert pas au choix fait ne paraît pas (``only``) ; l'envoi et la voix attendent un
    # serveur d'envoi (``unless``).
    label: Annotated[str, Knob(label="Nom affiché", help="Comme la console le montre (vide : la clé du compte).",
                               group="La boîte", advanced=False, order=5)] = ""
    address: Annotated[str, Knob(label="Adresse", help="L'adresse de la boîte (expéditrice des mails).",
                                 group="La boîte", advanced=False, order=3)] = ""
    enabled: Annotated[bool, Knob(label="Actif", help="Décoché : ni relevé ni envoi, les réglages restent.",
                                  group="La boîte", advanced=False, order=12)] = True
    auth: Annotated[Literal["password", "microsoft"], Knob(
        label="Connexion", group="Connexion", choices=AUTHS, advanced=False, order=15,
        help="Hotmail, Outlook.com et Live refusent les mots de passe : choisis alors ton compte Microsoft.")] = \
        PASSWORD
    imap_host: Annotated[str, Knob(label="Serveur IMAP", help="Donné par ton fournisseur de mail (imap.gmail.com, "
                                                              "outlook.office365.com…) ; proposé d'après l'adresse "
                                                              "pour les plus courants.",
                                   group="Lire", advanced=False, order=20)] = ""
    imap_port: Annotated[int, Knob(label="Port IMAP", help="993 presque toujours (IMAP chiffré).", group="Lire",
                                   lo=1, hi=65_535, order=21)] = 993
    imap_ssl: Annotated[bool, Knob(label="IMAP chiffré (SSL)", help="À laisser coché, sauf serveur de test.",
                                   group="Lire", order=22)] = True
    user: Annotated[str, Knob(label="Utilisateur", help="Souvent l'adresse elle-même.", group="Connexion",
                              advanced=False, order=16)] = ""
    password: Annotated[str, Knob(label="Mot de passe", help="Un mot de passe d'application de préférence. "
                                                             "Chiffré, jamais réaffiché ; vide : inchangé.",
                                  group="Connexion", secret=True, advanced=False, order=17,
                                  only=(("auth", (PASSWORD,)),))] = ""
    folders: Annotated[tuple[str, ...], Knob(
        label="Dossiers relevés", group="Lire", advanced=False, order=25, loader="folders",
        help="Ceux où elle remarque ce qui arrive. « Charger la liste » lit les dossiers sur le serveur de la boîte "
             "enregistrée, à cocher ; sinon, un nom par ligne.")] = ("INBOX",)
    sync_all: Annotated[bool, Knob(
        label="Synchroniser tous les dossiers", group="Lire", advanced=False, order=26,
        help="À chaque relève, tous les dossiers du serveur sont tenus à jour dans la console. Elle ne remarque "
             "toujours que les dossiers relevés.")] = False
    since_days: Annotated[int, Knob(label="Fenêtre de relève (jours)", group="Lire", lo=1, hi=60, order=27,
                                    help="Au premier relevé d'un dossier, on ne remonte pas plus loin.")] = 2
    oauth_client_id: Annotated[str, Knob(
        label="Application Microsoft (client ID)", group="Connexion", advanced=False, order=18,
        only=(("auth", (MICROSOFT,)),),
        help="L'identifiant de l'application inscrite dans Microsoft Entra (portail Azure › Inscriptions "
             "d'applications) — comptes Microsoft personnels acceptés, « Autoriser les flux de clients publics » "
             "activé. La boîte enregistrée, « Se connecter à Microsoft » sur sa fiche. Changer d'application demande "
             "de se reconnecter.")] = ""
    oauth_tenant: Annotated[str, Knob(
        label="Annuaire Microsoft", group="Connexion", advanced=False, order=19, only=(("auth", (MICROSOFT,)),),
        help="« consumers » pour un compte personnel (Hotmail, Outlook.com, Live) ; pour un compte Microsoft 365, "
             "« organizations » ou l'identifiant de l'annuaire. Changer d'annuaire demande de se reconnecter.")] = \
        CONSUMERS
    smtp_host: Annotated[str, Knob(label="Serveur SMTP", help="Pour envoyer (smtp.gmail.com…). Vide : cette boîte "
                                                              "ne fait que lire.", group="Envoyer", advanced=False,
                                   order=30)] = ""
    smtp_port: Annotated[int, Knob(label="Port SMTP", help="587 avec STARTTLS, 465 avec SSL.", group="Envoyer",
                                   lo=1, hi=65_535, order=32, unless=_NO_SMTP)] = 587
    #: « ssl » (port 465), « starttls » (587), « none » (tests)
    smtp_security: Annotated[str, Knob(label="Sécurité SMTP", help="Le port la suit.", group="Envoyer", order=31,
                                       unless=_NO_SMTP,
                                       choices=(("starttls", "STARTTLS (587)"), ("ssl", "SSL (465)"),
                                                ("none", "aucune (tests)")))] = "starttls"
    smtp_user: Annotated[str, Knob(label="Utilisateur SMTP", group="Envoyer", order=33, unless=_NO_SMTP,
                                   help="Vide : le même que pour lire.")] = ""
    smtp_password: Annotated[str, Knob(label="Mot de passe SMTP", group="Envoyer", secret=True, order=34,
                                       only=(("auth", (PASSWORD,)),), unless=_NO_SMTP,
                                       help="Vide : le même que pour lire.")] = ""
    save_sent: Annotated[bool, Knob(
        label="Copier les envois dans « Envoyés »", group="Envoyer", order=35, unless=_NO_SMTP,
        help="Range une copie de chaque envoi dans le dossier Envoyés du serveur. À décocher si le serveur le "
             "fait déjà (Gmail).")] = True
    voice: Annotated[Literal["elle", "assistante", "proprietaire"], Knob(
        label="Elle écrit", group="Sa voix", choices=VOICES, advanced=False, order=40, unless=_NO_SMTP,
        help="En son nom ; en assistante (« son nom, pour … ») ; ou à ta place, à la première personne et signé de "
             "ton nom.")] = "elle"
    display_name: Annotated[str, Knob(
        label="Ton nom", group="Sa voix", advanced=False, order=42, only=(("voice", ("assistante", "proprietaire")),),
        unless=_NO_SMTP, help="Le nom qui signe et qui paraît comme expéditeur.")] = ""
    sender_name: Annotated[str, Knob(label="Son nom d'expéditrice", group="Sa voix", advanced=False, order=41,
                                     only=(("voice", ("elle",)),), unless=_NO_SMTP,
                                     help="Le nom qui paraît comme expéditeur (vide : le nom de sa persona).")] = ""
    tone: Annotated[str, Knob(label="Ton", group="Sa voix", widget="textarea", advanced=False, order=43,
                              unless=_NO_SMTP, help="Par exemple : « vouvoiement, sobre et chaleureux ».")] = ""
    instructions: Annotated[str, Knob(
        label="Consignes", group="Sa voix", widget="textarea", advanced=False, order=44, unless=_NO_SMTP,
        help="Ce qu'elle doit savoir pour écrire depuis cette boîte (ce qu'on accepte, ce qu'on ne promet "
             "jamais…). Elle les suit ; un mail reçu, lui, n'est jamais une consigne.")] = ""
    signature: Annotated[str, Knob(label="Signature", group="Sa voix", widget="textarea", advanced=False, order=45,
                                   unless=_NO_SMTP,
                                   help="Ajoutée sous chaque envoi (elle ne l'écrit pas elle-même).")] = ""

    @field_validator("folders")
    @classmethod
    def _folders(cls, folders: tuple[str, ...]) -> tuple[str, ...]:
        kept = tuple(dict.fromkeys(f.strip() for f in folders if f.strip()))
        return kept or ("INBOX",)

    @field_validator("oauth_client_id")
    @classmethod
    def _client_id(cls, client_id: str) -> str:
        client_id = client_id.strip()
        if client_id and not _CLIENT_ID.match(client_id):
            raise ValueError("l'application Microsoft se donne par son identifiant (client ID), de la forme "
                             "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx")
        return client_id.lower()

    @field_validator("oauth_tenant")
    @classmethod
    def _tenant(cls, tenant: str) -> str:
        tenant = tenant.strip() or CONSUMERS
        if not _TENANT.match(tenant):
            raise ValueError("l'annuaire Microsoft est « consumers », « organizations », un domaine ou un identifiant")
        return tenant

    @property
    def ready(self) -> bool:
        return bool(self.enabled and self.imap_host and self.user)

    @property
    def can_send(self) -> bool:
        return bool(self.enabled and self.smtp_host and (self.address or self.user))

    @property
    def from_address(self) -> str:
        return self.address or self.user

    @property
    def microsoft(self) -> bool:
        """Elle entre par un compte Microsoft (OAuth2), pas par mot de passe."""
        return self.auth == MICROSOFT

    def info(self, key: str) -> AccountInfo:
        return AccountInfo(
            key=key, label=self.label, address=self.from_address.lower(), display_name=self.display_name,
            voice=self.voice, sender_name=self.sender_name, tone=self.tone, instructions=self.instructions, signature=self.signature,
            folders=self.folders, ready=self.ready, can_send=self.can_send, enabled=self.enabled,
            details=self.details())

    def details(self) -> tuple[tuple[str, str], ...]:
        """Ses réglages, sans aucun secret (le mot de passe : « défini » ou non)."""
        read = f"{self.imap_host}:{self.imap_port}{' (SSL)' if self.imap_ssl else ''}" if self.imap_host else "—"
        send = f"{self.smtp_host}:{self.smtp_port} ({self.smtp_security})" if self.smtp_host else "—"
        secret = (("connexion", f"compte Microsoft (application {self.oauth_client_id or 'non déclarée'}, annuaire "
                                f"{self.oauth_tenant})"),) if self.microsoft else \
            (("mot de passe", "défini" if self.password else "aucun"),)
        return (("lire", read), ("utilisateur", self.user or "—"), *secret,
                ("dossiers relevés", ", ".join(self.folders)),
                ("autres dossiers", "synchronisés à chaque relève" if self.sync_all else "relus à la demande"),
                ("fenêtre du premier relevé", f"{self.since_days} j"),
                ("envoyer", send), ("utilisateur d'envoi", self.smtp_user or "le même"),
                ("copie dans « Envoyés »", "oui" if self.save_sent else "non"))


class MailConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    accounts: Annotated[dict[str, MailAccount], Knob(
        label="Comptes", help=f"Chaque boîte qu'elle relève, avec sa façon d'y écrire. La clé est un nom court "
                              f"({ACCOUNT_KEY_RULE}).", advanced=False, order=10,
        key_pattern=ACCOUNT_KEY, key_rule=ACCOUNT_KEY_RULE)] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _keys(self) -> MailConfig:
        bad = [k for k in self.accounts if not ACCOUNT_KEY.match(k)]
        if bad:
            raise ValueError(f"nom de compte invalide : « {bad[0][:40]} » ({ACCOUNT_KEY_RULE})")
        return self

    @property
    def ready(self) -> bool:
        return any(a.ready for a in self.accounts.values())

    def first_ready(self) -> tuple[str, MailAccount] | None:
        return next(((k, a) for k, a in sorted(self.accounts.items()) if a.ready), None)


def from_stored(data: Mapping[str, Any]) -> dict[str, Any]:
    """Une configuration enregistrée, mise à la forme actuelle : une ancienne
    configuration plate (un seul compte) devient le compte « principal »."""
    data = dict(data)
    if "accounts" in data:
        return {"accounts": dict(data["accounts"] or {})}
    legacy = {k: v for k, v in data.items() if k in MailAccount.model_fields and k != "folders"}
    folder = data.get("folder")
    if folder:
        legacy["folders"] = (str(folder),)
    if not (legacy.get("imap_host") or legacy.get("address") or legacy.get("smtp_host")):
        return {"accounts": {}}
    return {"accounts": {LEGACY_ACCOUNT: legacy}}
