"""Les comptes d'agenda tels que les réglages les gardent (ADR 0309), comme les boîtes et les comptes Teams : à qui
est chaque compte, sa sorte, ses identifiants (scellés par ``app/settings.py``), ce qu'on suit de ses agendas, et par
agenda sa couleur, s'il est masqué, le rappel de Mika et ses partages.

- **Le compte du système d'une personne** (``moi:<sa clé>``, ``ports.agenda.system_account``) n'a rien à y faire pour
  exister : chaque personne qui a un compte a le sien et son « Mon agenda » ; il ne s'y range que quand elle en règle
  un agenda (sa couleur, un partage). Il est à elle (``personne:<clé>``), jamais à toi ni à elle.
- **Un compte branché** a un nom court (des minuscules, des chiffres, « - » ou « _ ») ; il est à toi (vide) ou à une
  personne qui a un compte (``personne:<clé>``). Pas de compte « à Mika » pour l'instant (ADR 0309).
- **Masquer un agenda** le retire aussi à Mika ; le décocher dans la vue ne change que l'affichage (l'écran).
- **Partager un agenda** : à une personne (``personne:<clé>``), lire, lire et préparer, ou s'en servir
  (``vocab.access.SHARES``). Les partages et les propriétaires sont journalisés avec les paramètres du plugin
  (``params``), comme ceux des boîtes : ce que Mika en fait se relit tel qu'il était.
- **Google et Microsoft** (lot 2) n'ont ni mot de passe ni adresse de serveur : leur connexion (le jeton de
  renouvellement) est gardée à part, scellée (``app/settings.py`` : ``agenda_oauth``), que ce formulaire ne touche
  jamais. Un compte Microsoft entre par l'application de l'instance, celle du courrier (ADR 0238), ou par la sienne
  (``oauth_client_id``), dans son annuaire (``oauth_tenant``) ; un compte Google, par l'application Google du
  serveur, réglée par un opérateur.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mika.adapters.signin.microsoft import CONSUMERS, application_id, tenant_id
from mika.kernel.forms import Knob
from mika.ports.agenda import (
    KIND_WORDS,
    KINDS,
    REMINDERS,
    SYSTEM,
    SYSTEM_PREFIX,
    Connection,
    calendar_key,
    system_account,
    system_person,
)
from mika.vocab.access import PERSON, Share

#: le nom court d'un compte branché (comme une boîte, un compte Teams)
ACCOUNT_KEY = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
ACCOUNT_KEY_RULE = "des minuscules, chiffres, - ou _ (40 au plus), en commençant par une lettre ou un chiffre"
#: la clé courte d'un agenda, telle que la base la donne (``ports.agenda.local_key``)
LOCAL_KEY = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
#: les couleurs qu'on choisit pour un agenda (le rose n'y est pas : il est à Mika)
COLORS = (("indigo", "Indigo"), ("bleu", "Bleu"), ("sarcelle", "Sarcelle"), ("vert", "Vert"), ("ambre", "Ambre"),
          ("orange", "Orange"), ("violet", "Violet"), ("ardoise", "Ardoise"))

Color = Literal["", "indigo", "bleu", "sarcelle", "vert", "ambre", "orange", "violet", "ardoise"]


def _person_keys(shares: dict[str, str]) -> dict[str, str]:
    bad = [k for k in shares if not (k.startswith(PERSON) and len(k) > len(PERSON))]
    if bad:
        raise ValueError(f"un partage va à une personne (« personne:<clé> »), pas à « {bad[0][:40]} »")
    return dict(shares)


class CalendarSetting(BaseModel):
    """Ce qu'on règle d'un agenda."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    color: Annotated[Color, Knob(label="Couleur", choices=(("", "Celle du fournisseur"), *COLORS),
                                 help="Sa couleur dans l'Agenda (vide : celle que le fournisseur lui donne).")] = ""
    hidden: Annotated[bool, Knob(
        label="Masqué", help="Masqué : il ne s'affiche plus dans l'Agenda, et elle ne s'en sert plus ; il reste branché "
                             "et se synchronise.")] = False
    reminder: Annotated[Literal["", "non", "15", "30", "60", "veille"], Knob(
        label="Elle te le rappelle", choices=(("", "Comme le dit le serveur"), *REMINDERS),
        help="Avant chaque rendez-vous de cet agenda (vide : le réglage du serveur pour sa sorte — 30 min avant pour "
             "le système, rien chez un fournisseur ni pour un abonnement).")] = ""
    followed: Annotated[bool | None, Knob(
        label="Suivi", help="Synchronisé (vide : ce que le fournisseur coche, son agenda principal toujours).")] = None
    shares: Annotated[dict[str, Share], Knob(
        label="Partagé avec", readonly=True,
        help="Réglé par son propriétaire : pour chaque personne (« personne:<clé> »), lire, lire et préparer, ou s'en "
             "servir. Un partage ici n'est pas un partage chez Google ou Microsoft.")] = Field(default_factory=dict)

    @field_validator("shares")
    @classmethod
    def _shares(cls, shares: dict[str, str]) -> dict[str, str]:
        return _person_keys(shares)


class AgendaAccount(BaseModel):
    """Un compte d'agenda : sa sorte, à qui il est, comment le joindre, ses agendas."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Annotated[Literal["systeme", "google", "microsoft", "caldav", "ical"], Knob(
        label="Sorte", choices=tuple((k, KIND_WORDS[k]) for k in KINDS), advanced=False, order=1,
        help="Le système (sur ce serveur), Google Agenda, Outlook.com / Microsoft 365, un serveur CalDAV (Outlook pro "
             "par DavMail, iCloud, Nextcloud, Fastmail) ou un abonnement iCal (une adresse .ics, en lecture seule).")]
    label: Annotated[str, Knob(label="Nom affiché", advanced=False, order=2,
                               help="Comme tu l'appelles, et comme elle l'appelle (vide : son nom court).")] = ""
    owner: Annotated[str, Knob(
        label="À qui", advanced=False, order=3,
        help="À toi (vide), ou à une personne qui a un compte (« personne:<clé> ») : ses outils ne voient que les "
             "agendas de qui est en face. Le compte du système d'une personne est à elle.")] = ""
    enabled: Annotated[bool, Knob(
        label="Actif", advanced=False, order=4,
        help="Décoché : il ne se synchronise plus et elle ne s'en sert plus ; ce qui est gardé reste.")] = True
    address: Annotated[str, Knob(
        label="Son adresse", order=10,
        help="L'adresse du compte chez le fournisseur : elle y reconnaît les invitations qui lui sont faites.")] = ""
    url: Annotated[str, Knob(
        label="Adresse du serveur", order=11,
        help="CalDAV : l'adresse du serveur (DavMail sur cette machine pour Outlook pro) ; iCal : l'adresse .ics, "
             "qu'on garde scellée (une adresse secrète ouvre l'agenda à qui la connaît).")] = ""
    username: Annotated[str, Knob(label="Identifiant", order=12, help="CalDAV : l'identifiant du compte.")] = ""
    password: Annotated[str, Knob(label="Mot de passe d'application", secret=True, order=13,
                                  help="CalDAV : un mot de passe d'application, scellé.")] = ""
    oauth_client_id: Annotated[str, Knob(
        label="Application Microsoft (client ID)", order=14, only=(("kind", ("microsoft",)),),
        help="Vide : l'application de l'instance, celle du courrier (Courrier › Paramètres › Compte Microsoft). "
             "Sinon, celle d'un annuaire Microsoft 365 qui n'admet que les siennes. En changer demande de se "
             "reconnecter.")] = ""
    oauth_tenant: Annotated[str, Knob(
        label="Annuaire Microsoft", order=15, only=(("kind", ("microsoft",)),),
        help="« consumers » pour Outlook.com (un compte personnel) ; pour un compte Microsoft 365, « organizations » "
             "ou l'identifiant de l'annuaire. En changer demande de se reconnecter.")] = CONSUMERS
    internet: Annotated[bool, Knob(
        label="Internet seulement", order=16, only=(("kind", ("caldav", "ical")),),
        help="Posé quand une personne qui n'est pas opératrice règle ce compte dans son espace : son serveur est "
             "revérifié sur Internet à chaque connexion (ni cette machine, ni le réseau privé).")] = False
    calendars: Annotated[dict[str, CalendarSetting], Knob(
        label="Ses agendas", readonly=True, order=20,
        help="Par agenda (sa clé courte) : sa couleur, s'il est masqué, le rappel qu'elle en fait, s'il est suivi, ses "
             "partages.")] = Field(default_factory=dict)

    @field_validator("owner")
    @classmethod
    def _owner(cls, owner: str) -> str:
        owner = owner.strip()
        if owner and not (owner.startswith(PERSON) and len(owner) > len(PERSON)):
            raise ValueError("un compte d'agenda est à toi (vide) ou à une personne (« personne:<clé> »)")
        return owner

    @field_validator("oauth_client_id")
    @classmethod
    def _client_id(cls, client_id: str) -> str:
        return application_id(client_id)

    @field_validator("oauth_tenant")
    @classmethod
    def _tenant(cls, tenant: str) -> str:
        return tenant_id(tenant)

    @field_validator("calendars")
    @classmethod
    def _locals(cls, calendars: dict[str, CalendarSetting]) -> dict[str, CalendarSetting]:
        bad = [k for k in calendars if not LOCAL_KEY.match(k)]
        if bad:
            raise ValueError(f"clé d'agenda invalide : « {bad[0][:40]} »")
        return dict(calendars)

    def setting(self, local: str) -> CalendarSetting:
        return self.calendars.get(local) or CalendarSetting()


class AgendaConfig(BaseModel):
    """Les comptes d'agenda des réglages ; ceux du système d'une personne n'y sont que s'ils ont été réglés."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    accounts: Annotated[dict[str, AgendaAccount], Knob(
        label="Comptes", noun="un compte", advanced=False, key_pattern=ACCOUNT_KEY, key_rule=ACCOUNT_KEY_RULE,
        help="Chaque compte d'agenda branché : à qui il est, sa sorte, ses agendas. Le compte du système de chaque "
             "personne existe sans rien faire.")] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _keys(self) -> AgendaConfig:
        for key, account in self.accounts.items():
            person = system_person(key)
            if person:
                if account.kind != SYSTEM:
                    raise ValueError(f"« {key[:40]} » est le compte du système d'une personne")
                if account.owner and account.owner != PERSON + person:
                    raise ValueError(f"le compte du système de « {person[:40]} » est à elle")
            elif not ACCOUNT_KEY.match(key):
                raise ValueError(f"nom de compte invalide : « {key[:40]} » ({ACCOUNT_KEY_RULE})")
            elif account.kind == SYSTEM:
                raise ValueError(f"« {key[:40]} » : un compte du système est celui d'une personne "
                                 f"(« {SYSTEM_PREFIX}<sa clé> »)")
        return self

    def account(self, key: str) -> AgendaAccount | None:
        """Un compte ; celui du système d'une personne, réglé ou non."""
        found = self.accounts.get(key)
        if found is not None or not system_person(key):
            return found
        return AgendaAccount(kind=SYSTEM)

    def system(self, person: str) -> AgendaAccount:
        """Le compte du système de cette personne (sa clé, sans ``personne:``)."""
        found = self.account(system_account(person))
        assert found is not None
        return found

    def connections(self) -> list[Connection]:
        """Les comptes réglés, pour qui les joint (leurs identifiants ouverts)."""
        out = []
        for key, a in sorted(self.accounts.items()):
            person = system_person(key)
            followed = {local: s.followed for local, s in a.calendars.items() if s.followed is not None}
            out.append(Connection(key=key, kind=a.kind, owner=PERSON + person if person else a.owner,
                                  label=a.label, address=a.address.strip().lower(), enabled=a.enabled, url=a.url,
                                  username=a.username, secret=a.password, followed=followed,
                                  oauth_client_id=a.oauth_client_id, oauth_tenant=a.oauth_tenant,
                                  internet=a.internet))
        return out

    def params(self) -> dict[str, Any]:
        """Ce que les paramètres du plugin ``agenda`` en reçoivent (journalisés, jamais un identifiant) : à qui est
        chaque compte branché, sa sorte, ceux qui sont décochés ; par agenda, ses partages, s'il est masqué, le rappel
        choisi."""
        owners: dict[str, str] = {}
        kinds: dict[str, str] = {}
        shares: dict[str, dict[str, str]] = {}
        reminders: dict[str, str] = {}
        hidden: list[str] = []
        for key, a in sorted(self.accounts.items()):
            if not system_person(key):
                owners[key], kinds[key] = a.owner, a.kind
            for local, s in sorted(a.calendars.items()):
                cal = calendar_key(key, local)
                if s.shares:
                    shares[cal] = dict(sorted(s.shares.items()))
                if s.hidden:
                    hidden.append(cal)
                if s.reminder:
                    reminders[cal] = s.reminder
        return {"owners": owners, "kinds": kinds, "shares": shares, "hidden": hidden, "reminders": reminders,
                "accounts_off": sorted(k for k, a in self.accounts.items() if not a.enabled)}


__all__ = ["ACCOUNT_KEY", "ACCOUNT_KEY_RULE", "COLORS", "LOCAL_KEY", "AgendaAccount", "AgendaConfig", "CalendarSetting"]
