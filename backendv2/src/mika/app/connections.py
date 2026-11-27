"""Les applications de l'instance par lesquelles on se connecte à un compte Microsoft ou Google (ADR 0238, 0309,
0318) : un réglage du cadre, que les domaines partagent.

Se connecter n'est à aucun domaine (le moteur est dans ``adapters/signin/``) ; l'application par laquelle on entre ne
l'est pas non plus : celle de Microsoft sert les boîtes Hotmail et les agendas Outlook.com, celle de Google les
agendas Google, et un domaine neuf (un Drive) s'en servira de même. Un domaine les prend par leur classe
(``settings.of(ConnectionSettings)``) ; ses jetons, eux, restent dans ses réglages, sous sa clé (``mail_oauth``,
``agenda_oauth``).

- **L'application Microsoft** : celle que Mika livre (``adapters/signin/microsoft.py::DEFAULT_APPLICATION``), ou celle
  que l'instance s'est donnée (son client ID, ADR 0238 ; réglée dans Courrier › Paramètres › Compte Microsoft,
  Agendas › Paramètres, ou par ``mika mail application``). Un compte qui déclare la sienne passe devant.
- **L'application Google du serveur** (ADR 0309, lot 2) : le client OAuth d'un projet Google Cloud, son secret scellé,
  et s'il est une « Application Web » (réglée dans Agendas › Paramètres, ou par ``mika agenda google``).

Leurs clés de réglage sont celles qu'elles avaient quand le courrier et l'agenda les portaient (``mail_application``,
``agenda_google``), sous la même forme : une instance déjà connectée le reste. Rangées par la porte des réglages
(``app/settings.py::SettingsPart`` : ``_get``, ``_put``, ``_sealed``, ``_opened``).
"""

from __future__ import annotations

import logging

from mika.adapters.signin.google import GoogleApplication
from mika.adapters.signin.microsoft import DEFAULT_APPLICATION, application_id
from mika.app.settings import SettingsPart

log = logging.getLogger("mika.settings")

#: l'application Microsoft propre à l'instance, à la place de celle que Mika livre (son client ID, ADR 0238) — sous
#: la clé qu'elle avait quand elle était un réglage du courrier
MICROSOFT_APPLICATION_KEY = "mail_application"
#: l'application Google du serveur (ADR 0309, lot 2) : le client OAuth d'un projet Google Cloud, son secret scellé —
#: sous la clé qu'elle avait quand elle était un réglage de l'agenda
GOOGLE_APPLICATION_KEY = "agenda_google"
#: ce que l'application Google garde scellé : son secret
GOOGLE_SECRETS = ("secret",)


class ConnectionSettings(SettingsPart):
    """Les applications de l'instance par lesquelles on se connecte à Microsoft et à Google : une part du cadre."""

    def own_microsoft_application(self) -> str:
        """L'application Microsoft que cette instance s'est donnée (son client ID, ADR 0238) ; vide : aucune, elle
        se sert de celle que Mika livre."""
        got = self._get(MICROSOFT_APPLICATION_KEY)
        try:
            return application_id(got) if isinstance(got, str) else ""
        except ValueError:
            return ""

    def microsoft_application(self) -> str:
        """L'application par laquelle entre un compte Microsoft qui n'en déclare pas — une boîte, un compte d'agenda
        (ADR 0238) : celle de l'instance si elle s'en est donné une, sinon celle que Mika livre."""
        return self.own_microsoft_application() or DEFAULT_APPLICATION

    async def save_microsoft_application(self, client_id: str) -> str:
        """Garde l'application propre à l'instance (vide : revient à celle que Mika livre) ; ``ValueError`` si ce
        n'est pas un client ID."""
        client_id = application_id(client_id)
        await self._put(MICROSOFT_APPLICATION_KEY, client_id)
        return client_id

    def google_application(self) -> GoogleApplication | None:
        """L'application Google du serveur (son secret ouvert) ; aucune, ou illisible : ``None`` (brancher Google est
        alors refusé en mots)."""
        got = self._get(GOOGLE_APPLICATION_KEY)
        if not isinstance(got, dict) or not got.get("client_id"):
            return None
        try:
            return GoogleApplication.of(str(got["client_id"]), self._opened(got, GOOGLE_SECRETS)["secret"],
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
            await self._put(GOOGLE_APPLICATION_KEY, {})
            return None
        known = self.google_application()
        if not secret.strip() and known is not None and known.client_id == client_id.strip().lower():
            secret = known.secret
        app = GoogleApplication.of(client_id, secret, web=web)
        await self._put(GOOGLE_APPLICATION_KEY, self._sealed({"client_id": app.client_id, "secret": app.secret,
                                                              "web": app.web}, GOOGLE_SECRETS))
        return app
