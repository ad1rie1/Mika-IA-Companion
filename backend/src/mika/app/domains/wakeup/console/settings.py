"""La page de réglages des réveils par API (ADR 0068, 0206, 0310) : Réveils par API › Paramètres, en haut à droite de
leur destination. Un réveil y a sa page : ce qu'il lui fait faire, son projet, ses outils, à qui elle rend compte.
Ce qu'on y enregistre est vérifié contre ce qui existe : un projet vivant, un compte actif, des lots permis."""

from __future__ import annotations

from typing import Any

from mika.app.domains.wakeup.desk import NO_PROJECT, TOOLS, WakeupConfig
from mika.app.domains.wakeup.settings import WakeupSettings
from mika.contracts import projects as projects_c
from mika.contracts import wakeup as wakeup_c
from mika.inspector.catalog import SettingsPage, SettingsSection
from mika.inspector.ui import PREFIX
from mika.kernel.inspect import Ref


def sections(live: Any) -> tuple[SettingsSection, ...]:
    """Ses rubriques de réglages, pour ce serveur (``live`` : son noyau, ses comptes, ses réglages)."""
    wakeups = live.settings.of(WakeupSettings)

    def wake_tools() -> list[str]:
        """Les lots qu'un réveil peut avoir : ceux du code, et ceux des serveurs extérieurs branchés."""
        return [*TOOLS, *sorted(b for b in live.kernel.registry.bundles if b.startswith("mcp."))]

    def wake_projects() -> list[tuple[str, str]]:
        views = list(live.kernel.mind.frame().get(projects_c.LIVE))
        titles = live.kernel.mind.store.content([v.title_ref for v in views if v.title_ref])
        return [(NO_PROJECT, "aucun — un travail à part"), *(
            (str(v.id), f"n° {v.id} — {titles.get(v.title_ref) or '(sans titre)'}"
             + (" (en pause)" if v.status == projects_c.PAUSED else "")) for v in views)]

    def wake_notify() -> list[tuple[str, str]]:
        return [(wakeup_c.OWNERS, "ses propriétaires"),
                (wakeup_c.NOBODY, "personne (le compte rendu reste dans la console)"),
                *((a.handle, f"{a.display_name} (compte)") for a in live.accounts.all() if a.active)]

    async def save_wakeup(cfg: WakeupConfig) -> list[str]:
        """Un projet, une personne, des outils qui existent — sauf ce qui était déjà là (un projet archivé depuis
        reste affiché, pour qu'on le corrige)."""
        before = wakeups.wakeup().endpoints
        projects, notify, tools = {v for v, _ in wake_projects()}, {v for v, _ in wake_notify()}, set(wake_tools())
        problems = []
        for name, ep in cfg.endpoints.items():
            old = before.get(name)
            if ep.project not in projects and (old is None or old.project != ep.project):
                problems.append(f"« {name} » : projet inconnu ou archivé ({ep.project}).")
            if ep.notify not in notify and (old is None or old.notify != ep.notify):
                problems.append(f"« {name} » : il rend compte à ses propriétaires, à un compte actif, ou à personne.")
            bad = [t for t in ep.tools if t not in tools and (old is None or t not in old.tools)]
            if bad:
                problems.append(f"« {name} » : lot inconnu ou qu'un réveil ne peut pas avoir : {', '.join(bad)} "
                                f"(permis : {', '.join(sorted(tools))}).")
        if problems:
            return problems
        await wakeups.save_wakeup(cfg)
        return []

    def wakeup_facts() -> list[tuple[str, Any]]:
        endpoints, keys = wakeups.wakeup().endpoints, wakeups.wakeup_keys()
        keyed = sum(1 for n in endpoints if n in keys)
        return [("Réveils", f"{len(endpoints)} ({keyed} avec une clé)" if endpoints else "aucun"),
                ("Lots permis", ", ".join(wake_tools())),
                ("Clés, appels et ce qu'ils ont donné", Ref("local", f"{PREFIX}/reveils", "Réveils par API"))]

    return (
        SettingsSection("reveils", "Réveils par API", "plugins", WakeupConfig, wakeups.wakeup, save_wakeup,
                        order=45,
                        description="Les réveils que des systèmes extérieurs appellent (POST /api/wake/<nom>) : ce "
                                    "qu'ils lui font faire, quand, à qui elle en rend compte. Leurs clés se génèrent "
                                    "sur leur fiche, montrées une seule fois.",
                        facts=wakeup_facts, fixed_names=("endpoints",),
                        choices={"endpoints.project": wake_projects, "endpoints.notify": wake_notify},
                        # dans Réveils par API, en haut à droite (ADR 0206)
                        pages=(SettingsPage("reveils", "Paramètres", ("endpoints",), description=(
                            "Chaque réveil a sa page : à quoi il sert, ses consignes (elles priment sur le texte "
                            "qu'un appel apporte, qui n'est jamais une consigne), son projet, son mode, ses outils, "
                            "s'il passe outre son sommeil, à qui elle rend compte, ses bornes. Son nom est la fin de "
                            "son URL."), home="reveils/parametres"),)),
    )
