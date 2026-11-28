"""La rubrique des dessins (ADR 0061, 0197, 0317) : Réglages › Intelligence › Images — les fournisseurs qui génèrent
ses images, et lequel sert chaque rôle, en deux pages (Fournisseurs d'images, Qui dessine quoi). Elle suit celle des
modèles dans la même rubrique (``app/settings_sections/intelligence.py`` ; sa place : son ``order``)."""

from __future__ import annotations

from typing import Any

from mika.adapters.imaging.config import ImagingConfig
from mika.adapters.imaging.models import list_image_models
from mika.adapters.listing import ListingFailed
from mika.app.domains.imaging.settings import ImagingSettings
from mika.app.domains.imaging.wiring import NAME, ImagingService
from mika.inspector.catalog import SettingsPage, SettingsSection
from mika.kernel import forms
from mika.ports.imaging import DRAW


def sections(live: Any) -> tuple[SettingsSection, ...]:
    """Sa rubrique de réglages, pour ce serveur (``live`` : ses réglages, ses dessins en service)."""
    settings = live.settings.of(ImagingSettings)
    drawings: ImagingService = live.parts[NAME]

    async def save_images(cfg: ImagingConfig) -> list[str]:
        # un fournisseur retiré emporte les rôles qui le visaient (ils retombent sur « dessiner ») et les replis
        # qui menaient à lui
        cfg = cfg.model_copy(update={
            "routes": {r: b for r, b in cfg.routes.items() if b in cfg.backends},
            "backends": {n: s if not s.fallback or s.fallback in cfg.backends else s.model_copy(update={"fallback": ""})
                         for n, s in cfg.backends.items()}})
        previous = settings.imaging()
        await settings.save_imaging(cfg)  # une configuration qui a un problème est refusée (ValueError), en le disant
        problems = await drawings.reload()
        if problems:
            await settings.save_imaging(previous)
            await drawings.reload()
        return problems

    async def image_models(values: Any) -> list[tuple[str, str]]:
        data = forms.nest(dict(values))
        try:
            names = await list_image_models(str(data.get("kind") or ""), api_key=str(data.get("api_key") or ""),
                                            base_url=str(data.get("base_url") or ""))
        except ListingFailed as exc:
            raise ValueError(str(exc)) from None
        return [(name, name) for name in names]

    def image_route(role: str, _chosen: Any) -> dict[str, Any]:
        """La ligne d'un rôle d'images dans Qui dessine quoi (en table) : ce qui le sert, son type et son modèle, où
        il tourne, ce qu'il sait aussi faire, et comment il y est arrivé. Sans fournisseur déclaré, elle ne génère pas
        d'images ; le premier déclaré sert « dessiner », les autres rôles y retombent."""
        cfg = settings.imaging()
        name = drawings.gateway.resolution().get(role, "")
        spec = cfg.backends.get(name)
        caps = next((row for row in drawings.gateway.status() if row["name"] == name), {}) if name else {}
        how = "déclaré" if cfg.routes.get(role) == name else "par repli (dessiner)"
        return {"title": "Ce qui sert chaque rôle", "key_head": "Rôle", "choice_head": "Son fournisseur",
                "cells": [{"head": "Ce qui le sert", "text": name or "aucun", "mono": bool(name),
                           "tone": "" if name else "muted", "sub": f"{spec.kind} · {spec.model}" if spec else ""},
                          {"head": "Où", "text": ("local" if caps.get("local") else "hébergé") if name else "—",
                           "tone": "muted"},
                          {"head": "Sait aussi", "text": ", ".join(w for w, on in (("retouche", caps.get("edit")),
                                                                                    ("adulte", caps.get("adult")))
                                                                    if on) or "—", "tone": "muted"},
                          {"head": "Comment", "text": how if name else "désactivé",
                           "tag": how == "déclaré" or not name, "tone": "ok" if name and how == "déclaré" else "muted"}]}

    def image_facts() -> list[tuple[str, str]]:
        cfg = settings.imaging()
        serving = drawings.gateway.serving(DRAW)
        return [("Dessiner", f"servi par « {serving} »" if serving else "désactivé : aucun fournisseur"),
                ("Fournisseurs", str(len(cfg.backends)))]

    return (
        SettingsSection("images", "Images", "intelligence", ImagingConfig, settings.imaging, save_images, order=120,
                        description="Les fournisseurs qui génèrent ses images, et lequel sert chaque rôle. Aucun "
                                    "fournisseur : elle n'en génère pas. Les clés sont chiffrées, jamais "
                                    "réaffichées.", loaders={"image_models": image_models}, facts=image_facts,
                        describe={"routes": image_route},
                        pages=(
                            SettingsPage("images-fournisseurs", "Fournisseurs d'images", ("backends",), order=10,
                                         description=(
                                             "OpenAI (son API Images), ou un serveur compatible : le tien, qui "
                                             "fait tourner un modèle sur ta machine, ou un proxy. Le premier "
                                             "déclaré sert « dessiner » d'office. Un repli prend le relais "
                                             "d'une panne, ou de ce que le premier ne sait pas faire ; jamais "
                                             "d'un refus de modération.")),
                            SettingsPage("images-roles", "Qui dessine quoi", ("routes",), order=20,
                                         facts=False, description=(
                                             "Dessiner (une demande), retoucher une image reçue, ses dessins à "
                                             "elle. Laisse vide : le rôle retombe sur « dessiner ».")),
                        )),
    )
