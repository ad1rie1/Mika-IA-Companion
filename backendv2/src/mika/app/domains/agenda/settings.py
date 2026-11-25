"""Les réglages de l'agenda (ADR 0309, 0310) : ses comptes (chacun à quelqu'un, leurs secrets scellés) et le
réglage de chacun de leurs agendas ; les connexions Google et Microsoft de ses comptes ; l'application Google du
serveur ; le partage d'un agenda.

Rangés dans les réglages du serveur (``mind.db``), par leur porte (``app/settings.py::SettingsPart``) ; le domaine
les prend par leur classe (``settings.of(AgendaSettings)``), une page du cadre par le nom du domaine
(``Settings.named("agenda")``). Ses *droits* — le tableau réglé de chaque agenda — restent dans ``Settings``
(``agenda_tables``, ``save_agenda_table``) : ils vivent dans le cache lu à chaque épisode avec ceux des canaux et des
familles d'outils (``access_tables``) ; partager un agenda les lit et les écrit par la porte.
"""

from __future__ import annotations

import asyncio
import logging

from mika.adapters.agenda.config import AgendaConfig
from mika.adapters.agenda.oauth import GoogleApplication
from mika.adapters.mail.oauth import Grant
from mika.app.settings import Settings, SettingsPart
from mika.plugins.agenda.rights import shared_table
from mika.ports.agenda import Connection, split_calendar_key

log = logging.getLogger("mika.settings")

#: l'agenda (ADR 0309) : ses comptes, chacun à quelqu'un, et le réglage de chacun de leurs agendas (identifiants et
#: adresse d'un abonnement scellés)
AGENDA_KEY = "agenda"
#: les connexions des comptes d'agenda Google et Microsoft (ADR 0309, lot 2) : par compte, sa sorte, le jeton de
#: renouvellement scellé, l'application et l'annuaire qui l'ont délivré — à part des comptes, comme ``mail_oauth``
AGENDA_GRANTS_KEY = "agenda_oauth"
#: l'application Google du serveur (ADR 0309, lot 2) : le client OAuth d'un projet Google Cloud, son secret scellé
AGENDA_GOOGLE_KEY = "agenda_google"


class AgendaSettings(SettingsPart):
    #: ce qu'un compte d'agenda garde scellé : son mot de passe, son adresse (celle d'un abonnement ouvre l'agenda à
    #: qui la connaît)
    AGENDA_SECRETS = ("password", "url")

    def __init__(self, door: Settings) -> None:
        super().__init__(door)
        #: les connexions de ses comptes se relisent puis se récrivent ensemble : une à la fois. Un verrou à lui —
        #: il ne garde que ses clés (celles du courrier ont le leur) ; jamais ``writing``, sous lequel on partage
        self._grants_lock = asyncio.Lock()

    def agenda(self) -> AgendaConfig:
        """Les comptes d'agenda (leurs secrets ouverts) ; illisibles, aucun (jamais bloquant)."""
        accounts = {}
        for name, spec in dict((self._get(AGENDA_KEY) or {}).get("accounts") or {}).items():
            spec = dict(spec)
            for k in self.AGENDA_SECRETS:
                spec[k] = self.box.open(spec.pop(f"{k}_sealed", ""))
            accounts[name] = spec
        try:
            return AgendaConfig.model_validate({"accounts": accounts})
        except ValueError:
            log.warning("agenda : réglages illisibles, aucun compte")
            return AgendaConfig()

    async def save_agenda(self, cfg: AgendaConfig) -> AgendaConfig:
        """Enregistre les comptes d'agenda (revalidés) ; leurs secrets scellés."""
        cfg = AgendaConfig.model_validate(cfg.model_dump())
        accounts = {}
        for name, account in cfg.accounts.items():
            spec = account.model_dump(mode="json")
            for k in self.AGENDA_SECRETS:
                spec[f"{k}_sealed"] = self.box.seal(spec.pop(k))
            accounts[name] = spec
        await self._put(AGENDA_KEY, {"accounts": accounts})
        async with self._grants_lock:  # la connexion d'un compte retiré, ou qui change de sorte, ne reste pas
            grants = dict(self._get(AGENDA_GRANTS_KEY) or {})
            kept = {k: v for k, v in grants.items()
                    if k in cfg.accounts and isinstance(v, dict) and v.get("kind") == cfg.accounts[k].kind}
            if kept != grants:
                await self._put(AGENDA_GRANTS_KEY, kept)
        return cfg

    def agenda_grant(self, account: str, kind: str) -> Grant | None:
        """La connexion Google ou Microsoft d'un compte d'agenda (son jeton de renouvellement ouvert) ; aucune, ou
        d'une autre sorte : ``None``."""
        spec = dict(self._get(AGENDA_GRANTS_KEY) or {}).get(account)
        if not isinstance(spec, dict) or spec.get("kind") != kind:
            return None
        refresh = self.box.open(str(spec.get("refresh_sealed") or ""))
        if not refresh:  # un scellé qui ne s'ouvre plus (``secret.key`` changée) : il faut se reconnecter
            return None
        return Grant(refresh, str(spec.get("client_id") or ""), str(spec.get("tenant") or ""))

    async def save_agenda_grant(self, account: str, grant: Grant, kind: str) -> None:
        """Garde la connexion d'un compte d'agenda, son jeton de renouvellement scellé."""
        async with self._grants_lock:
            grants = dict(self._get(AGENDA_GRANTS_KEY) or {})
            grants[account] = {"kind": kind, "refresh_sealed": self.box.seal(grant.refresh),
                               "client_id": grant.client_id, "tenant": grant.tenant}
            await self._put(AGENDA_GRANTS_KEY, grants)

    async def drop_agenda_grant(self, account: str) -> bool:
        """La connexion d'un compte d'agenda oubliée (on le déconnecte) ; vrai s'il en avait une."""
        async with self._grants_lock:
            grants = dict(self._get(AGENDA_GRANTS_KEY) or {})
            if grants.pop(account, None) is None:
                return False
            await self._put(AGENDA_GRANTS_KEY, grants)
            return True

    def agenda_connections(self) -> list[Connection]:
        """Les comptes d'agenda réglés, pour qui les joint (le port ``agenda_providers``, relu à chaque usage)."""
        return self.agenda().connections()

    def google_application(self) -> GoogleApplication | None:
        """L'application Google du serveur (son secret ouvert) ; aucune, ou illisible : ``None`` (brancher Google est
        alors refusé en mots)."""
        got = self._get(AGENDA_GOOGLE_KEY)
        if not isinstance(got, dict) or not got.get("client_id"):
            return None
        try:
            return GoogleApplication.of(str(got["client_id"]), self.box.open(str(got.get("secret_sealed") or "")),
                                        web=bool(got.get("web")))
        except ValueError:
            log.warning("agenda : l'application Google gardée est illisible (le secret ne s'ouvre plus ?)")
            return None

    async def save_google_application(self, client_id: str, secret: str = "", *,
                                      web: bool = False) -> GoogleApplication | None:
        """Garde l'application Google du serveur (``client_id`` vide : l'efface) ; un secret vide garde celui de la
        même application. ``ValueError`` si l'identifiant ou le secret n'en ont pas la forme. En changer demande de
        reconnecter les comptes Google."""
        if not client_id.strip():
            await self._put(AGENDA_GOOGLE_KEY, {})
            return None
        known = self.google_application()
        if not secret.strip() and known is not None and known.client_id == client_id.strip().lower():
            secret = known.secret
        app = GoogleApplication.of(client_id, secret, web=web)
        await self._put(AGENDA_GOOGLE_KEY, {"client_id": app.client_id, "secret_sealed": self.box.seal(app.secret),
                                            "web": app.web})
        return app

    async def share_calendar(self, calendar: str, person: str, level: str | None) -> AgendaConfig:
        """Partager un agenda (ADR 0309, 0188) avec une personne (« personne:<clé> »), à un niveau — lire, lire et
        préparer, s'en servir ; ``None`` retire son partage. Rangé avec l'agenda (ses réglages), et son tableau suit :
        réglé, il reçoit la ligne de la personne à la place de celle qu'elle avait, ou la perd
        (``plugins/agenda/rights.py::shared_table``) ; sinon, la ligne se dérive du partage. Seul son propriétaire
        partage : qui appelle l'a vérifié. À appeler sous ``writing``, puis rejournaliser (``Live.reconfigure``) :
        ce que Mika en fait se relit tel qu'il était. ``ValueError`` : pas un agenda, un compte inconnu, une personne
        ou un niveau mal formés."""
        account, local = split_calendar_key(calendar)
        cfg = self.agenda()
        found = cfg.account(account) if account else None
        if found is None:
            raise ValueError(f"agenda inconnu : « {calendar[:60]} »")
        shares = dict(found.setting(local).shares)
        if level:
            shares[person] = level
        else:
            shares.pop(person, None)
        setting = found.setting(local).model_copy(update={"shares": shares})
        changed = found.model_copy(update={"calendars": {**found.calendars, local: setting}})
        cfg = await self.save_agenda(cfg.model_copy(update={"accounts": {**cfg.accounts, account: changed}}))
        stored = self.door.agenda_tables().get(calendar)
        if stored is not None:
            await self.door.save_agenda_table(calendar, shared_table(stored, person, level))
        return cfg


#: la classe que le cadre prend par le nom du domaine (``Settings.named``)
SETTINGS = AgendaSettings
