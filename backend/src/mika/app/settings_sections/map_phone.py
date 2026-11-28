"""Réglages › Carte et téléphone : les notifications du téléphone. Les autres rubriques de cet onglet — la carte de sa
position, les lieux, les itinéraires, les données touristiques, les avis, le réchauffage des caches — sont celles de
la carte, que sa fiche inscrit (``app/domains/maps/console/settings.py``, ADR 0310)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from pydantic import BaseModel, ConfigDict, field_validator

from mika.adapters.push import parse_service_account
from mika.app.settings import PUSH_KEY_FILE, push_key_file
from mika.app.settings_sections.common import tolerant
from mika.inspector.catalog import SettingsPage, SettingsSection
from mika.kernel.forms import Knob

if TYPE_CHECKING:
    from mika.app.server import Live


class PushSettings(BaseModel):
    """Les notifications du téléphone (ADR 0077) : la clé avec laquelle le serveur parle à Firebase."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    service_account: Annotated[str, Knob(
        label="Clé du compte de service", help="Le fichier JSON téléchargé dans la console Firebase (Paramètres du "
        "projet › Comptes de service › Générer une nouvelle clé privée), collé tel quel. Chiffrée, jamais réaffichée. "
        "Vide : inchangée ; « effacer » coupe les notifications.", secret=True, advanced=False, order=10)] = ""

    @field_validator("service_account")
    @classmethod
    def _key(cls, text: str) -> str:
        text = text.strip()
        if text:
            parse_service_account(text)  # ValueError en français : la page le dit sous le champ
        return text


def sections(live: Live) -> tuple[SettingsSection, ...]:
    settings = live.settings

    # ── notifications du téléphone (ADR 0077) ──
    async def save_push(cfg: PushSettings) -> list[str]:
        await settings.save_push(cfg.service_account)
        return []

    def push_facts() -> list[tuple[str, str]]:
        pasted = settings.push()
        filed = push_key_file(live.data) if live.data is not None and not pasted else ""
        key = pasted or filed
        try:
            project = parse_service_account(key).project_id if key else ""
        except ValueError as exc:
            project = f"clé illisible : {exc}"
        where = ("collée ici" if pasted else f"fichier {PUSH_KEY_FILE} du dossier de données" if filed
                 else f"aucune (colle-la ici, ou pose {PUSH_KEY_FILE} dans le dossier de données)")
        facts = [("Clé", where), ("Projet Firebase", project or "rien ne part"),
                 ("Téléphones notifiables", str(live.accounts.push_count()))]
        stats = live.hub.push.stats if live.hub.push is not None else None
        if stats is not None and (stats.sent or stats.failed or stats.gone):
            facts.append(("Depuis le démarrage", f"{stats.sent} envoyée(s), {stats.failed} en échec, "
                                                 f"{stats.gone} téléphone(s) oublié(s)"))
        if stats is not None and stats.last_error:
            facts.append(("Dernier échec", stats.last_error))
        return facts

    return (
        SettingsSection("notifications", "Notifications du téléphone", "carte-telephone", PushSettings,
                        lambda: tolerant(PushSettings, service_account=settings.push()), save_push, order=20,
                        description="Ce qu'elle écrit à quelqu'un dont l'application est fermée part par Firebase, "
                                    "chiffré pour son seul téléphone.", facts=push_facts,
                        pages=(SettingsPage("notifications", "Notifications du téléphone", description=(
                            "L'application Android ne garde aucune connexion ouverte quand elle est fermée : ce "
                            "qu'elle écrit à la personne lui arrive en notification par Firebase Cloud Messaging, "
                            "chiffré avec une clé que seul son téléphone connaît (Google ne transporte qu'un "
                            "chiffré). Il faut un projet Firebase où l'application est déclarée, et la clé d'un "
                            "compte de service de ce projet : collée ici, ou posée dans le dossier de données sous "
                            "le nom firebase-service-account.json (droits 600) — collée ici, elle prime. Sans elle, "
                            "l'application ne reçoit que ce qu'elle trouve en s'ouvrant.")),)),
    )
