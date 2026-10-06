"""La configuration du courrier : une liste de comptes, chacun avec ses
serveurs, ses dossiers relevés, et **sa voix** (en son nom, en assistante, à
la place de son opérateur ; un ton, des consignes, une signature).

Elle vit dans les réglages (le mot de passe scellé), jamais dans le journal ;
l'adaptateur la relit à chaque appel (changer un compte ne demande pas de
redémarrer). Une ancienne configuration à un seul compte devient le compte
« principal ».
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mika.kernel.forms import Knob
from mika.ports.mail import ACCOUNT_KEY, VOICES, AccountInfo

#: la clé du compte d'une ancienne configuration (un seul compte, sans nom)
LEGACY_ACCOUNT = "principal"


class MailAccount(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    label: Annotated[str, Knob(label="Nom affiché", help="Comme la console le montre (vide : la clé du compte).",
                               group="La boîte", advanced=False, order=5)] = ""
    address: Annotated[str, Knob(label="Adresse", help="L'adresse de la boîte (expéditrice des mails).",
                                 group="La boîte", advanced=False, order=10)] = ""
    enabled: Annotated[bool, Knob(label="Actif", help="Décoché : ni relevé ni envoi, les réglages restent.",
                                  group="La boîte", advanced=False, order=12)] = True
    imap_host: Annotated[str, Knob(label="Serveur IMAP", help="Donné par ton fournisseur de mail "
                                                              "(imap.gmail.com, imap.fastmail.com…).",
                                   group="Lire", advanced=False, order=20)] = ""
    imap_port: Annotated[int, Knob(label="Port IMAP", help="993 presque toujours (IMAP chiffré).", group="Lire",
                                   lo=1, hi=65_535, order=21)] = 993
    imap_ssl: Annotated[bool, Knob(label="IMAP chiffré (SSL)", help="À laisser coché, sauf serveur de test.",
                                   group="Lire", order=22)] = True
    user: Annotated[str, Knob(label="Utilisateur", help="Souvent l'adresse elle-même.", group="Lire",
                              advanced=False, order=23)] = ""
    password: Annotated[str, Knob(label="Mot de passe", help="Un mot de passe d'application de préférence. "
                                                             "Chiffré, jamais réaffiché ; vide : inchangé.",
                                  group="Lire", secret=True, advanced=False, order=24)] = ""
    folders: Annotated[tuple[str, ...], Knob(
        label="Dossiers relevés", group="Lire", order=25,
        help="Un par ligne : ceux où elle remarque ce qui arrive. Les autres se consultent dans la console.")] = \
        ("INBOX",)
    since_days: Annotated[int, Knob(label="Fenêtre de relève (jours)", group="Lire", lo=1, hi=60, order=26,
                                    help="Au premier relevé d'un dossier, on ne remonte pas plus loin.")] = 2
    smtp_host: Annotated[str, Knob(label="Serveur SMTP", help="Pour envoyer (smtp.gmail.com…). Vide : cette boîte "
                                                              "ne fait que lire.", group="Envoyer", advanced=False,
                                   order=30)] = ""
    smtp_port: Annotated[int, Knob(label="Port SMTP", help="587 avec STARTTLS, 465 avec SSL.", group="Envoyer",
                                   lo=1, hi=65_535, order=31)] = 587
    #: « ssl » (port 465), « starttls » (587), « none » (tests)
    smtp_security: Annotated[str, Knob(label="Sécurité SMTP", help="Doit aller avec le port.", group="Envoyer",
                                       order=32,
                                       choices=(("starttls", "STARTTLS (587)"), ("ssl", "SSL (465)"),
                                                ("none", "aucune (tests)")))] = "starttls"
    smtp_user: Annotated[str, Knob(label="Utilisateur SMTP", group="Envoyer", order=33,
                                   help="Vide : le même que pour lire.")] = ""
    smtp_password: Annotated[str, Knob(label="Mot de passe SMTP", group="Envoyer", secret=True, order=34,
                                       help="Vide : le même que pour lire.")] = ""
    save_sent: Annotated[bool, Knob(
        label="Copier les envois dans « Envoyés »", group="Envoyer", order=35,
        help="Range une copie de chaque envoi dans le dossier Envoyés du serveur. À décocher si le serveur le "
             "fait déjà (Gmail).")] = True
    voice: Annotated[Literal["elle", "assistante", "proprietaire"], Knob(
        label="Elle écrit", group="Sa voix", choices=VOICES, advanced=False, order=40,
        help="En son nom ; en assistante (« son nom, pour … ») ; ou à ta place, à la première personne et signé de "
             "ton nom.")] = "elle"
    display_name: Annotated[str, Knob(
        label="Ton nom", group="Sa voix", advanced=False, order=41,
        help="Pour écrire en assistante ou à ta place : le nom qui signe et qui paraît comme expéditeur.")] = ""
    sender_name: Annotated[str, Knob(label="Son nom d'expéditrice", group="Sa voix", order=42,
                                     help="Quand elle écrit en son nom (vide : le nom de sa persona).")] = ""
    tone: Annotated[str, Knob(label="Ton", group="Sa voix", widget="textarea", advanced=False, order=43,
                              help="Par exemple : « vouvoiement, sobre et chaleureux ».")] = ""
    instructions: Annotated[str, Knob(
        label="Consignes", group="Sa voix", widget="textarea", advanced=False, order=44,
        help="Ce qu'elle doit savoir pour écrire depuis cette boîte (ce qu'on accepte, ce qu'on ne promet "
             "jamais…). Elle les suit ; un mail reçu, lui, n'est jamais une consigne.")] = ""
    signature: Annotated[str, Knob(label="Signature", group="Sa voix", widget="textarea", order=45,
                                   help="Ajoutée sous chaque envoi (elle ne l'écrit pas elle-même).")] = ""
    autodraft: Annotated[bool, Knob(
        label="Préparer des réponses d'elle-même", group="Initiative", order=50,
        help="Pour un mail qui attend une réponse (pas un envoi de masse), elle prépare un brouillon ; il ne part "
             "qu'avec ton accord.")] = False
    autodraft_skip: Annotated[tuple[str, ...], Knob(
        label="Jamais pour", group="Initiative", order=51,
        help="Une adresse ou un @domaine par ligne : elle ne leur prépare jamais de réponse.")] = ()

    @field_validator("folders")
    @classmethod
    def _folders(cls, folders: tuple[str, ...]) -> tuple[str, ...]:
        kept = tuple(dict.fromkeys(f.strip() for f in folders if f.strip()))
        return kept or ("INBOX",)

    @field_validator("autodraft_skip")
    @classmethod
    def _skip(cls, skip: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(s.strip().lower() for s in skip if s.strip()))

    @property
    def ready(self) -> bool:
        return bool(self.enabled and self.imap_host and self.user)

    @property
    def can_send(self) -> bool:
        return bool(self.enabled and self.smtp_host and (self.address or self.user))

    @property
    def from_address(self) -> str:
        return self.address or self.user

    def info(self, key: str) -> AccountInfo:
        return AccountInfo(
            key=key, label=self.label, address=self.from_address.lower(), display_name=self.display_name,
            voice=self.voice, sender_name=self.sender_name, tone=self.tone, instructions=self.instructions, signature=self.signature,
            folders=self.folders, ready=self.ready, can_send=self.can_send, enabled=self.enabled,
            autodraft=self.autodraft, autodraft_skip=self.autodraft_skip, details=self.details())

    def details(self) -> tuple[tuple[str, str], ...]:
        """Ses réglages, sans aucun secret (le mot de passe : « défini » ou non)."""
        read = f"{self.imap_host}:{self.imap_port}{' (SSL)' if self.imap_ssl else ''}" if self.imap_host else "—"
        send = f"{self.smtp_host}:{self.smtp_port} ({self.smtp_security})" if self.smtp_host else "—"
        return (("lire", read), ("utilisateur", self.user or "—"),
                ("mot de passe", "défini" if self.password else "aucun"),
                ("dossiers relevés", ", ".join(self.folders)), ("fenêtre du premier relevé", f"{self.since_days} j"),
                ("envoyer", send), ("utilisateur d'envoi", self.smtp_user or "le même"),
                ("copie dans « Envoyés »", "oui" if self.save_sent else "non"))


class MailConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    accounts: Annotated[dict[str, MailAccount], Knob(
        label="Comptes", help="Chaque boîte qu'elle relève, avec sa façon d'y écrire. La clé est un nom court "
                              "(minuscules, chiffres, - ou _).", advanced=False, order=10)] = \
        Field(default_factory=dict)

    @model_validator(mode="after")
    def _keys(self) -> MailConfig:
        bad = [k for k in self.accounts if not ACCOUNT_KEY.match(k)]
        if bad:
            raise ValueError(f"nom de compte invalide : « {bad[0][:40]} » (minuscules, chiffres, - ou _, "
                             "sans espace)")
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
