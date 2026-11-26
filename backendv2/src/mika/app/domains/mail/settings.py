"""Les réglages du courrier (ADR 0027, 0166, 0175, 0238, 0310) : ses boîtes (chacune à quelqu'un, leurs mots de passe
scellés), la connexion Microsoft de chacune, l'application Microsoft de l'instance, les expéditeurs dont les images
distantes s'affichent.

Rangés dans les réglages du serveur (``mind.db``), par leur porte (``app/settings.py::SettingsPart``) ; le domaine
les prend par leur classe (``settings.of(MailSettings)``), une page du cadre par le nom du domaine
(``Settings.named("mail")``).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from mika.adapters.mail import MailAccount, MailConfig, from_stored
from mika.adapters.mail.config import DEFAULT_APPLICATION, application_id
from mika.adapters.mail.oauth import Grant
from mika.app.settings import Settings, SettingsPart

EMAIL_KEY = "email"
#: les connexions Microsoft des boîtes aux lettres (ADR 0166) : par boîte, le jeton de renouvellement scellé, et
#: l'application et l'annuaire qui l'ont délivré — à part des comptes, que le formulaire de la console réécrit
MAIL_GRANTS_KEY = "mail_oauth"
#: les expéditeurs dont la console affiche les images distantes (ADR 0175) : des adresses, les plus récentes d'abord
MAIL_IMAGES_KEY = "mail_images"
#: l'application Microsoft propre à l'instance, à la place de celle que Mika livre (son client ID, ADR 0238)
MAIL_APPLICATION_KEY = "mail_application"
#: ce qu'une connexion Microsoft garde scellé : son jeton de renouvellement
GRANT_SECRETS = ("refresh",)


class MailSettings(SettingsPart):
    def __init__(self, door: Settings) -> None:
        super().__init__(door)
        #: les connexions Microsoft des boîtes se relisent puis se réécrivent ensemble : une à la fois
        self._grants_lock = asyncio.Lock()
        #: prévenu après chaque enregistrement des boîtes ou de leur connexion Microsoft : le courrier en direct s'y
        #: règle aussitôt (ADR 0308 ; posé par son câblage)
        self.mail_saved: Callable[[], None] = lambda: None

    #: les secrets d'un compte de courrier (scellés à part, jamais en clair dans ``mind.db``)
    MAIL_SECRETS = ("password", "smtp_password")

    def email(self) -> MailConfig:
        """Les comptes de courrier (mots de passe déchiffrés).

        Une configuration gardée d'avant plusieurs boîtes (ADR 0027 : un seul compte, ses secrets scellés au premier
        niveau) se lit encore comme le compte « principal » : ses secrets ouverts ici, le reste par ``from_stored``.
        Cette branche part avec lui, quand une révision de données de la base ``mind`` aura réécrit les réglages
        gardés à la forme du jour (audit du 2026-11-05)."""
        raw = dict(self._get(EMAIL_KEY) or {})
        if "accounts" not in raw:  # la forme d'avant plusieurs boîtes : un compte, ses secrets au premier niveau
            data = from_stored(self._opened(raw, self.MAIL_SECRETS))
        else:
            data = {"accounts": {name: self._opened(spec, self.MAIL_SECRETS)
                                 for name, spec in dict(raw.get("accounts") or {}).items()}}
        try:
            return MailConfig.model_validate(data)
        except ValueError:
            return MailConfig()

    async def save_email(self, cfg: MailConfig) -> MailConfig:
        accounts = {name: self._sealed(account.model_dump(mode="json"), self.MAIL_SECRETS)
                    for name, account in cfg.accounts.items()}
        await self._put(EMAIL_KEY, {"accounts": accounts})
        async with self._grants_lock:  # la connexion d'une boîte retirée, ou qui reprend un mot de passe, ne reste pas
            grants = dict(self._get(MAIL_GRANTS_KEY) or {})
            kept = {k: v for k, v in grants.items() if k in cfg.accounts and cfg.accounts[k].microsoft}
            if kept != grants:
                await self._put(MAIL_GRANTS_KEY, kept)
        self.mail_saved()
        return cfg

    def mail_grant(self, account: str) -> Grant | None:
        """La connexion Microsoft d'une boîte (son jeton de renouvellement déchiffré) ; aucune : ``None``."""
        spec = dict(self._get(MAIL_GRANTS_KEY) or {}).get(account)
        if not isinstance(spec, dict):
            return None
        refresh = self._opened(spec, GRANT_SECRETS)["refresh"]
        if not refresh:  # un scellé qui ne s'ouvre plus (``secret.key`` changée) : il faut se reconnecter
            return None
        return Grant(refresh, str(spec.get("client_id") or ""), str(spec.get("tenant") or ""))

    async def save_mail_grant(self, account: str, grant: Grant) -> None:
        """Garde la connexion Microsoft d'une boîte, son jeton de renouvellement scellé."""
        async with self._grants_lock:
            grants = dict(self._get(MAIL_GRANTS_KEY) or {})
            grants[account] = self._sealed({"refresh": grant.refresh, "client_id": grant.client_id,
                                            "tenant": grant.tenant}, GRANT_SECRETS)
            await self._put(MAIL_GRANTS_KEY, grants)
        self.mail_saved()

    def own_mail_application(self) -> str:
        """L'application Microsoft que cette instance s'est donnée (son client ID, ADR 0238) ; vide : aucune, elle
        se sert de celle que Mika livre."""
        got = self._get(MAIL_APPLICATION_KEY)
        try:
            return application_id(got) if isinstance(got, str) else ""
        except ValueError:
            return ""

    def mail_application(self) -> str:
        """L'application par laquelle entre une boîte Microsoft qui n'en déclare pas (ADR 0238) : celle de
        l'instance si elle s'en est donné une, sinon celle que Mika livre."""
        return self.own_mail_application() or DEFAULT_APPLICATION

    async def save_mail_application(self, client_id: str) -> str:
        """Garde l'application propre à l'instance (vide : revient à celle que Mika livre) ; ``ValueError`` si ce
        n'est pas un client ID."""
        client_id = application_id(client_id)
        await self._put(MAIL_APPLICATION_KEY, client_id)
        return client_id

    def mail_images(self) -> tuple[str, ...]:
        """Les expéditeurs dont les images distantes s'affichent d'emblée (ADR 0175)."""
        got = self._get(MAIL_IMAGES_KEY)
        return tuple(str(a) for a in got if isinstance(a, str)) if isinstance(got, list | tuple) else ()

    async def save_mail_images(self, addresses: tuple[str, ...]) -> None:
        await self._put(MAIL_IMAGES_KEY, list(addresses))

    async def save_mail_account(self, name: str, **fields: Any) -> MailConfig:
        """Crée ou modifie un compte (la ligne de commande) : les champs ``None`` ne changent pas."""
        cfg = self.email()
        current = cfg.accounts[name].model_dump() if name in cfg.accounts else {}
        current.update({k: v for k, v in fields.items() if v is not None})
        account = MailAccount.model_validate(current)
        return await self.save_email(MailConfig(accounts={**cfg.accounts, name: account}))


SETTINGS = MailSettings
