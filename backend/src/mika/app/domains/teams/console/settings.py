"""Sa rubrique de réglages (ADR 0069, 0186, 0206, 0310) : dans Teams, derrière sa roue (Teams › Paramètres) — actif
ou non, ses comptes (à qui est chacun, sa façon d'y écrire, sa signature)."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

from mika.adapters.teams import TeamsConfig
from mika.app.domains.teams.settings import TeamsSettings
from mika.app.handmade import ago
from mika.app.settings_sections.common import owner_words, owners
from mika.inspector.catalog import SettingsPage, SettingsSection
from mika.inspector.ui import PREFIX
from mika.kernel.inspect import Ref, plural
from mika.plugins.teams.inspect import owner_name as teams_account_owner

log = logging.getLogger("mika.reglages")


def sections(live: Any) -> tuple[SettingsSection, ...]:
    """Sa rubrique de réglages, pour ce serveur (``live`` : ses réglages, son noyau, ses comptes)."""
    settings = live.settings
    own = settings.of(TeamsSettings)

    def teams_owners() -> list[tuple[str, str]]:
        """À qui un compte Teams peut être (ADR 0186) : les mêmes qu'une boîte (toi, elle, une personne qui a un
        compte)."""
        return owners(live)

    async def save_teams(cfg: TeamsConfig) -> list[str]:
        """Un compte Teams est à toi, à elle ou à une personne qui a un compte (ADR 0186) — sauf ce qui était déjà là
        (un compte fermé depuis reste affiché, pour qu'on le corrige)."""
        before, known = own.teams().accounts, {v for v, _ in teams_owners()}
        problems = [f"« {name} » : il est à toi, à elle, ou à une personne qui a un compte."
                    for name, a in cfg.accounts.items()
                    if a.owner not in known and (name not in before or before[name].owner != a.owner)]
        if problems:
            return problems
        await own.save_teams(cfg)
        # un compte supprimé : ce que son extension avait apporté s'efface avec lui (ADR 0186)
        store = live.kernel.ports.get("teams") if live.kernel is not None else None
        for gone in sorted(set(before) - set(cfg.accounts)):
            if store is not None:
                store.drop_account(gone)
        # actif ou non, et à qui est chaque compte, sont lus par ses proposeurs et ses outils : un réglage journalisé
        problems = await live.reconfigure()
        if problems:
            log.warning("teams enregistré, paramètres non rejournalisés : %s", "; ".join(problems))
        return []

    def teams_facts() -> list[tuple[str, Any]]:
        """Ses comptes en chiffres, et une fois chacun, en liens, les pages où le reste se fait (C7-15). La page vit
        dans Teams (ADR 0206) : ses conversations et ses réponses sont les onglets d'à côté, pas un fait de plus."""
        accounts, keys = own.teams().accounts, own.teams_keys()
        store = live.kernel.ports.get("teams") if live.kernel is not None else None
        plugged = sum(1 for k in accounts if store is not None and store.configured(k))
        keyed = sum(1 for k in accounts if k in keys)
        return [("Comptes", f"{len(accounts)} ({keyed} avec une clé, {plural(plugged, 'branché', 'branchés')})"),
                ("La clé de chaque extension", Ref("local", f"{PREFIX}/teams/extension", "Teams › Extension")),
                ("Ce qu'elle prépare, comment ça part", Ref("local", f"{PREFIX}/reglages/canaux",
                                                            "Canaux, le tableau de Teams ou celui d'un compte"))]

    def describe_teams_account(key: str, account: Any) -> dict[str, Any]:
        """La carte d'un compte Teams (ADR 0186) : à qui il est, sa clé, ce que son extension a apporté — et, comme la
        carte d'une boîte mène à sa fiche et à ses messages, son extension (où sa clé se crée) et ses conversations."""
        store = live.kernel.ports.get("teams") if live.kernel is not None else None
        info = store.account(key) if store is not None else None
        has_key = key in own.teams_keys()
        plugged = info is not None and bool(info.last_batch)
        tags = [("branché", "ok")] if plugged else [("clé créée", "info")] if has_key else [("sans clé", "warn")]
        if not account.enabled:  # décoché : son extension est refusée
            tags.insert(0, ("inactif", ""))
        tags.append((f"à {owner_words(live, account.owner, teams_account_owner)}" if account.owner else "à toi",
                     "owner" if account.owner else ""))
        if account.sign:
            tags.append(("signé", ""))
        now = live.kernel.mind.clock.now() if live.kernel is not None else 0
        # le chemin de sa clé est dit une fois, en lien, dans les faits de la page : le bandeau ne le répète pas
        activity = f"Son extension a poussé {ago(now, info.last_batch)}" if plugged else \
            "Son extension n'a encore rien apporté." + ("" if has_key else " Sa clé n'est pas encore créée.")
        return {"title": account.label or key, "tags": tags, "lead_label": "Elle y écrit à la place de",
                "lead": account.display_name or (info.self_name if info is not None and info.self_name else "") or
                "la personne du compte (le nom que Teams donne)", "lead_plain": True,
                "facts": [("Ton", account.tone or "—"), ("Consignes", "oui" if account.instructions.strip() else "aucune")],
                "activity": activity, "activity_tone": "" if plugged else "warn",
                "links": (("Son extension", f"{PREFIX}/teams/extension?" + urlencode({"compte": key})),
                          ("Ses conversations", f"{PREFIX}/teams/conversations?" + urlencode({"compte": key})))}

    return (
        SettingsSection("teams", "Teams", "plugins", TeamsConfig, own.teams, save_teams, order=12,
                        lock=settings.writing,
                        description="Les conversations Teams que l'extension de navigateur de chaque compte lui "
                                    "apporte, et ce qu'elle fait des réponses qu'elle y prépare.",
                        facts=teams_facts, fixed_names=("accounts",), describe={"accounts": describe_teams_account},
                        choices={"accounts.owner": teams_owners},
                        # dans Teams, en haut à droite, comme le courrier (ADR 0173, 0206)
                        pages=(SettingsPage("teams", "Paramètres", home="teams/parametres", description=(
                            "Chaque compte Teams — le tien, le sien, celui d'une personne qui a un compte — a son "
                            "extension, qui lit ce que Teams web reçoit dans le navigateur où il "
                            "est ouvert et l'apporte ici, avec la clé de ce compte (montrée une seule fois). Elle y "
                            "écrit à la place de la personne du compte : un brouillon posé dans Teams, un envoi après "
                            "accord, ou un envoi sans demander — toujours de ce compte, sous son nom.")),)),
    )
