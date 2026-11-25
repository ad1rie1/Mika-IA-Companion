"""Les réglages de l'agenda (ADR 0309, 0310) : l'application Google du serveur — le client OAuth d'un projet Google
Cloud, son secret scellé —, par laquelle se branchent les comptes Google Agenda.

Rangés dans les réglages du serveur (``mind.db``), par leur porte (``app/settings.py::SettingsPart``) ; le domaine
les prend par leur classe (``settings.of(AgendaSettings)``), une page du cadre par le nom du domaine
(``Settings.named("agenda")``). Le reste de ce qu'il règle est encore dans ``Settings`` : ses comptes, leurs
connexions et le partage d'un agenda (``agenda``, ``save_agenda``, ``agenda_grant``, ``share_calendar``…), dont les
écritures se relisent sous le verrou des connexions Microsoft du courrier (``Settings._grants_lock``) ; et ses
droits (``agenda_tables``), lus à chaque épisode avec ceux des canaux et des familles d'outils (``access_tables``).
"""

from __future__ import annotations

import logging

from mika.adapters.agenda.oauth import GoogleApplication
from mika.app.settings import SettingsPart

log = logging.getLogger("mika.settings")

#: l'application Google du serveur (ADR 0309, lot 2) : le client OAuth d'un projet Google Cloud, son secret scellé
AGENDA_GOOGLE_KEY = "agenda_google"


class AgendaSettings(SettingsPart):
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


#: la classe que le cadre prend par le nom du domaine (``Settings.named``)
SETTINGS = AgendaSettings
