"""Les réglages des projets (ADR 0183, 0310) : le jeton de leurs dépôts git distants (GitHub ou un autre hôte
https), scellé, que l'atelier passe à git — et à lui seul —, avec l'utilisateur qui l'accompagne et les hôtes à qui il
est montré.

Rangés dans les réglages du serveur (``mind.db``), par leur porte (``app/settings.py::SettingsPart``).
"""

from __future__ import annotations

from mika.app.settings import SettingsPart

#: le jeton des dépôts git distants des projets (GitHub ou un autre hôte https), scellé
GIT_KEY = "git"


class ProjectsSettings(SettingsPart):
    # ── Dépôts git (ses projets poussent vers un dépôt distant) ──
    def git(self) -> dict[str, str]:
        """``{"token": …, "user": …}`` (jeton déchiffré) : ce que l'atelier passe à git, et à lui seul."""
        data = dict(self._get(GIT_KEY) or {})
        return {"token": self.box.open(data.get("token_sealed", "")), "user": data.get("user", "") or "x-access-token",
                "hosts": list(data.get("hosts") or ["github.com"])}

    async def save_git(self, token: str, user: str = "", hosts: list[str] | None = None) -> None:
        clean = sorted({h.strip().lower() for h in (hosts or []) if h.strip()}) or ["github.com"]
        await self._put(GIT_KEY, {"token_sealed": self.box.seal(token.strip()), "user": user.strip(), "hosts": clean})


SETTINGS = ProjectsSettings
