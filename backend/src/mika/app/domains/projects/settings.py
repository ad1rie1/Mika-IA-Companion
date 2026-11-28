"""Les réglages des projets (ADR 0183, 0310) : le jeton de leurs dépôts git distants (GitHub ou un autre hôte
https), scellé, que l'atelier passe à git — et à lui seul —, avec l'utilisateur qui l'accompagne et les hôtes à qui il
est montré.

Rangés dans les réglages du serveur (``mind.db``), par leur porte (``app/settings.py::SettingsPart``).
"""

from __future__ import annotations

from mika.app.settings import SettingsPart

#: le jeton des dépôts git distants des projets (GitHub ou un autre hôte https), scellé
GIT_KEY = "git"
#: ce qu'il garde scellé : le jeton
GIT_SECRETS = ("token",)


class ProjectsSettings(SettingsPart):
    # ── Dépôts git (ses projets poussent vers un dépôt distant) ──
    def git(self) -> dict[str, str]:
        """``{"token": …, "user": …}`` (jeton déchiffré) : ce que l'atelier passe à git, et à lui seul."""
        data = self._opened(self._get(GIT_KEY) or {}, GIT_SECRETS)
        return {"token": data["token"], "user": data.get("user", "") or "x-access-token",
                "hosts": list(data.get("hosts") or ["github.com"])}

    async def save_git(self, token: str, user: str = "", hosts: list[str] | None = None) -> None:
        clean = sorted({h.strip().lower() for h in (hosts or []) if h.strip()}) or ["github.com"]
        await self._put(GIT_KEY, self._sealed({"token": token.strip(), "user": user.strip(), "hosts": clean},
                                              GIT_SECRETS))


SETTINGS = ProjectsSettings
