"""Ses rubriques de réglages (ADR 0206, 0310) : les flux qu'elle suit, dans Ses sens, derrière sa roue (Ses sens ›
Flux suivis). La transcription et l'accès des appareils, sur la même roue, restent au cadre
(``app/settings_sections/plugins.py``) : ils règlent ce que tiennent les réglages du serveur."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, field_validator

from mika.app.domains.senses.settings import SensesSettings
from mika.inspector.catalog import SettingsPage, SettingsSection
from mika.inspector.ui import PREFIX
from mika.kernel.forms import Knob
from mika.kernel.inspect import Ref


class FeedsSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    urls: Annotated[tuple[str, ...], Knob(label="Flux suivis", help="Une adresse http(s) par ligne (RSS ou Atom).",
                                          advanced=False)] = ()

    @field_validator("urls")
    @classmethod
    def _http(cls, urls: tuple[str, ...]) -> tuple[str, ...]:
        bad = [u for u in urls if not u.startswith(("http://", "https://"))]
        if bad:
            raise ValueError(f"adresse non http(s) : {bad[0][:80]}")
        return tuple(sorted(set(urls)))


def sections(live: Any) -> tuple[SettingsSection, ...]:
    """Ses rubriques de réglages, pour ce serveur (``live`` : ses réglages)."""
    settings = live.settings.of(SensesSettings)

    async def save_feeds(cfg: FeedsSettings) -> list[str]:
        await settings.save_feeds(list(cfg.urls))
        return []

    return (
        SettingsSection("flux", "Flux", "plugins", FeedsSettings, lambda: FeedsSettings(urls=tuple(settings.feeds())),
                        save_feeds, description="Ce qu'elle lit du monde.", order=20,
                        facts=lambda: [("Suivis", str(len(settings.feeds()))),
                                       ("Ce qu'elle en remarque", Ref("local", f"{PREFIX}/sens/flux", "Flux RSS"))],
                        pages=(SettingsPage("flux", "Flux suivis", description=(
                            "Les flux RSS ou Atom qu'elle relève."), home="sens/parametres-flux"),)),
    )
