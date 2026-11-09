"""Réglages › Intelligence : les fournisseurs de modèles et d'images, et lequel sert chaque rôle."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from mika.adapters.imaging.config import ImagingConfig
from mika.adapters.imaging.models import ListingFailed as ImageListingFailed
from mika.adapters.imaging.models import list_image_models
from mika.adapters.llm.config import KIND_LABELS, REPLY, ROLE_LABELS, BackendSpec, LLMConfig, tokens_fr
from mika.adapters.llm.models import ListingFailed, list_models, settle_limits
from mika.app.handmade import ago
from mika.inspector.catalog import SettingsPage, SettingsSection
from mika.kernel import forms
from mika.kernel.clock import DAY
from mika.kernel.inspect import Note
from mika.ports.imaging import DRAW
from mika.vocab.episodes import FALLBACKS, VOICE_ROLES, Role

if TYPE_CHECKING:
    from mika.app.server import Live

#: la famille de chaque rôle (la page « Qui sert quoi »)
ROLE_FAMILIES = {**{str(r): "voix" for r in VOICE_ROLES}, "extract": "mémoire", "validate": "mémoire",
                 "compact": "mémoire", "profile": "compréhension", "interpret": "compréhension",
                 "triage": "sens", "caption": "sens", "plan": "travail", "job": "travail", "polish": "voix",
                 "character": "voix"}


def _count(n: int) -> str:
    """Un nombre, ses milliers séparés : « 24 000 »."""
    return f"{n:,}".replace(",", " ")


def _seconds(s: float) -> str:
    """Une durée de réponse : « 2,3 s », « 1,5 min »."""
    if not s:
        return "—"
    if s < 0.1:
        return "moins de 0,1 s"
    return f"{s:.1f} s".replace(".", ",") if s < 60 else f"{s / 60:.1f} min".replace(".", ",")


def _cost(usd: float) -> str:
    """Un coût : « 1,24 $ », « moins de 0,01 $ », rien quand c'est gratuit ou non compté."""
    if not usd:
        return "—"
    return f"{usd:.2f} $".replace(".", ",") if usd >= 0.01 else "moins de 0,01 $"


def sections(live: Live) -> tuple[SettingsSection, ...]:
    settings = live.settings

    # ── modèles ──
    async def save_llm(cfg: LLMConfig) -> list[str]:
        # un fournisseur retiré emporte les rôles qui le visaient (ils retombent sur leur repli)
        cfg = cfg.model_copy(update={"routes": {r: b for r, b in cfg.routes.items() if b in cfg.backends}})
        previous = settings.llm()
        await settings.save_llm(cfg)
        problems = await live.reload_llm()
        if problems:
            await settings.save_llm(previous)
            await live.reload_llm()
        return problems

    async def models(values: Any) -> list[tuple[str, str]]:
        try:
            spec = BackendSpec.model_validate(forms.nest(dict(values)))
        except ValidationError:
            raise ValueError("fournisseur incomplet (type, hôte ou clé)") from None
        try:
            # ce que la liste dit de chacun (l'API Claude : fenêtre et réponse) se lit avant de choisir
            return [(name, f"{name} — fenêtre {tokens_fr(got.window)}"
                           + (f", réponse {tokens_fr(got.output)}" if got.output else "") if got.window else name)
                    for name, got in await list_models(spec)]
        except ListingFailed as exc:
            raise ValueError(str(exc)) from None

    async def settle_llm(cfg: LLMConfig) -> tuple[LLMConfig, list[str]]:
        """Ce que chaque fournisseur dit de son modèle, lu avant d'enregistrer (ADR 0136)."""
        if live.read_limits is None:
            return cfg, []
        return await settle_limits(cfg, live.read_limits)

    def route(role: str, _chosen: Any) -> dict[str, Any]:
        """La ligne d'un rôle dans Qui sert quoi (la correspondance rôle → fournisseur, en table) : sa famille, puis
        ce qui le sert vraiment — le fournisseur déclaré, sinon celui de son rôle de repli, ou rien (chaque appel
        échoue) —, son type et son modèle, et comment il y est arrivé."""
        cfg = settings.llm()
        chain, seen, cur, served = [], set(), role, ""
        while cur and cur not in seen:
            seen.add(cur)
            name = cfg.routes.get(cur)
            if name and name in cfg.backends:
                served = name
                break
            chain.append(ROLE_LABELS.get(cur, cur))
            nxt = FALLBACKS.get(Role(cur)) if cur in {str(x) for x in Role} else None
            cur = str(nxt) if nxt else ""
        spec = cfg.backends.get(served)
        how = "déclaré" if cfg.routes.get(role) == served and served else \
            (f"par repli ({' → '.join(chain[1:] + [ROLE_LABELS.get(cur, cur)])})" if served else "")
        return {"title": "Ce qui sert vraiment chaque rôle", "key_head": "Rôle", "choice_head": "Son fournisseur",
                "tone": "" if served else "danger",
                "cells": [{"head": "Famille", "text": ROLE_FAMILIES.get(role, "—"), "tag": True, "before": True},
                          {"head": "Ce qui le sert vraiment", "text": served or "aucun", "mono": bool(served),
                           "tone": "" if served else "muted", "sub": f"{spec.kind} · {spec.model}" if spec else ""},
                          # une étiquette pour ce qui se lit d'un coup (déclaré, rien) ; la chaîne d'un repli, en texte
                          {"head": "Comment", "text": how or "chaque appel échoue", "tag": how in ("déclaré", ""),
                           "tone": "ok" if how == "déclaré" else "muted" if served else "danger"}]}

    # ── images ──
    async def save_images(cfg: ImagingConfig) -> list[str]:
        # un fournisseur retiré emporte les rôles qui le visaient (ils retombent sur « dessiner ») et les replis
        # qui menaient à lui
        cfg = cfg.model_copy(update={
            "routes": {r: b for r, b in cfg.routes.items() if b in cfg.backends},
            "backends": {n: s if not s.fallback or s.fallback in cfg.backends else s.model_copy(update={"fallback": ""})
                         for n, s in cfg.backends.items()}})
        previous = settings.imaging()
        await settings.save_imaging(cfg)  # une configuration qui a un problème est refusée (ValueError), en le disant
        problems = await live.reload_imaging()
        if problems:
            await settings.save_imaging(previous)
            await live.reload_imaging()
        return problems

    async def image_models(values: Any) -> list[tuple[str, str]]:
        data = forms.nest(dict(values))
        try:
            names = await list_image_models(str(data.get("kind") or ""), api_key=str(data.get("api_key") or ""),
                                            base_url=str(data.get("base_url") or ""))
        except ImageListingFailed as exc:
            raise ValueError(str(exc)) from None
        return [(name, name) for name in names]

    def image_route(role: str, _chosen: Any) -> dict[str, Any]:
        """La ligne d'un rôle d'images dans Qui dessine quoi (en table) : ce qui le sert, son type et son modèle, où
        il tourne, ce qu'il sait aussi faire, et comment il y est arrivé. Sans fournisseur déclaré, elle ne génère pas
        d'images ; le premier déclaré sert « dessiner », les autres rôles y retombent."""
        cfg = settings.imaging()
        name = live.imaging.resolution().get(role, "")
        spec = cfg.backends.get(name)
        caps = next((row for row in live.imaging.status() if row["name"] == name), {}) if name else {}
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
        serving = live.imaging.serving(DRAW)
        return [("Dessiner", f"servi par « {serving} »" if serving else "désactivé : aucun fournisseur"),
                ("Fournisseurs", str(len(cfg.backends)))]

    def llm_facts() -> list[tuple[str, str]]:
        cfg = settings.llm()
        serving = live.gateway.serving(REPLY) if live.gateway.configured else ""
        return [("Répondre", f"servi par « {serving} »" if serving else "aucun modèle : chaque tour échoue "
                 "proprement"), ("Fournisseurs", str(len(cfg.backends))), ("Rôles routés", str(len(cfg.routes)))]

    def describe_backend(key: str, spec: BackendSpec) -> dict[str, Any]:
        """La carte d'un fournisseur : son type, s'il la fait parler, sa connexion, son modèle, les rôles qui le
        désignent, ses bornes en mots, et ce qu'il a fait ces dernières 24 h (le registre des appels)."""
        cfg = settings.llm()
        serves = [ROLE_LABELS.get(r, r) for r, name in cfg.routes.items() if name == key]
        speaks = live.gateway.configured and live.gateway.serving(REPLY) == key
        tags = [(KIND_LABELS.get(spec.kind, spec.kind), "info")]
        if speaks:
            tags.append(("la fait parler", "ok"))
        if spec.kind == "claude_code":
            tags.append(("clé d'API définie", "ok") if spec.auth == "cle_api" and spec.api_key else
                        ("clé d'API manquante", "warn") if spec.auth == "cle_api" else ("son login (abonnement)", ""))
        elif spec.kind != "ollama":
            tags.append(("clé d'API définie", "ok") if spec.api_key else ("clé d'API manquante", "warn"))
        if not serves:
            said = "aucun rôle ne le désigne" + (" ; ceux qui n'ont pas de fournisseur y retombent" if speaks else "")
        else:
            said = ", ".join(serves[:6]) + (f" et {len(serves) - 6} autres" if len(serves) > 6 else "")
        if spec.detected_window:
            accepts = f"{tokens_fr(spec.detected_window)} jetons" + (
                f", réponse {tokens_fr(spec.detected_output)}" if spec.detected_output else "")
        else:
            accepts = "son fournisseur ne le dit pas" if spec.detected_for == spec.detection_key else \
                "lu au prochain enregistrement"
        facts = [("Sert", f"{len(serves)} rôle{'s' if len(serves) > 1 else ''} : {said}" if serves else said),
                 ("Contexte", f"{spec.context_tokens:,} jetons".replace(",", " ") if spec.context_tokens
                  else "celui du modèle"),
                 ("Réponse au plus", f"{spec.max_output_tokens:,} jetons".replace(",", " ") if spec.max_output_tokens
                  else "ce que prévoit son type"),
                 ("Le modèle accepte", accepts),
                 ("Appels en même temps", str(spec.slots) if spec.slots else "selon son type (1 en local, 4 hébergé)")]
        where = spec.base_url or spec.host
        if where:
            facts.append(("Adresse", where))
        calls = live.calls
        now = live.kernel.mind.clock.now()
        day = calls.profile(key, now - DAY) if calls else None
        week = calls.profile(key, now - 7 * DAY) if calls else None
        last = next((tr for tr in calls.recent(50) if tr.backend == key), None) if calls else None
        if day is None:
            activity, tone = "Aucun appel ces dernières 24 h.", ""
        else:
            used = day.total
            activity = (f"{used.calls} appel{'s' if used.calls > 1 else ''} ces dernières 24 h"
                        + (f", {used.failures} en échec" if used.failures else ", tous réussis")
                        + f" · {_seconds(used.latency_avg_s)} en moyenne")
            tone = "warn" if used.failures else "ok"
        if last is not None:
            activity += f" · dernier appel {ago(now, last.at)} ({'réussi' if last.outcome == 'ok' else 'en échec'})"
        return {"tags": tags, "lead": spec.model or "aucun modèle choisi", "lead_label": "Modèle", "facts": facts,
                "activity": activity, "activity_tone": tone, "detail": _detail(day, week, now)}

    def _detail(day: Any, week: Any, now: int) -> dict[str, Any] | None:
        """Le détail d'un fournisseur : sa consommation et ses temps de réponse, sur 24 h et sur 7 jours, puis rôle
        par rôle sur 7 jours."""
        if week is None:
            return None

        def period(prof: Any) -> list[str]:
            if prof is None:
                return ["0", "—", "—", "—", "—", "—", "—", "—", "—", "—"]
            u = prof.total
            share = f" ({u.failures * 100 // u.calls} %)" if u.failures else ""
            return [_count(u.calls), f"{_count(u.failures)}{share}", _seconds(u.latency_avg_s),
                    _seconds(prof.median_s), _seconds(prof.slow_s), _seconds(prof.wait_avg_s),
                    _count(u.input_tokens), _count(u.output_tokens),
                    f"{round(u.cache_ratio * 100)} %" if u.cache_read or u.cache_write else "—", _cost(u.cost_usd)]

        labels = ("Appels", "En échec", "Temps de réponse moyen", "Temps médian", "Les plus lents (95 %)",
                  "Attente d'un créneau", "Jetons lus", "Jetons écrits", "Lus depuis le cache", "Coût")
        day_cells, week_cells = period(day), period(week)
        failure = (f"Dernier échec {ago(now, week.last_failure_at)}, pour « "
                   f"{ROLE_LABELS.get(week.last_failure_role, week.last_failure_role)} ».") \
            if week.last_failure_at else "Aucun échec ces 7 derniers jours."
        return {"rows": [(label, day_cells[i], week_cells[i]) for i, label in enumerate(labels)],
                "roles": [{"role": ROLE_LABELS.get(u.key, u.key), "calls": _count(u.calls),
                           "failures": _count(u.failures), "avg": _seconds(u.latency_avg_s),
                           "tokens": f"{_count(u.input_tokens)} / {_count(u.output_tokens)}", "cost": _cost(u.cost_usd)}
                          for u in week.by_role],
                "failure": failure, "href": "/inspecteur/systeme/appels"}

    def who_replies() -> list[Any]:
        """Qui la fait parler : le premier fournisseur déclaré sert « répondre » d'office — la page le dit,
        pour qu'il n'y ait pas de seconde étape à deviner."""
        cfg = settings.llm()
        name = cfg.routes.get(REPLY, "")
        spec = cfg.backends.get(name)
        if spec is None:
            return [Note("Aucun fournisseur : elle ne peut pas parler. Ajoute-en un — le premier déclaré sert "
                         "« répondre » d'office, et tous les autres rôles y retombent.", "warn",
                         title="Elle ne peut pas encore répondre")]
        others = len(cfg.backends) - 1
        return [Note(f"« {name} » ({spec.kind} · {spec.model}) sert « répondre » : c'est lui qui la fait parler, "
                     "et les rôles sans fournisseur à eux y retombent. Le premier fournisseur déclaré le sert "
                     "d'office" + (" ; pour en changer, va dans Qui sert quoi." if others else "."), "info",
                     title="Qui la fait parler")]

    return (
        SettingsSection("modeles", "Modèles", "intelligence", LLMConfig, settings.llm, save_llm,
                        description="Les fournisseurs de modèles, et lequel sert chaque rôle. Les clés sont "
                                    "chiffrées, jamais réaffichées.", loaders={"models": models}, facts=llm_facts,
                        describe={"backends": describe_backend, "routes": route}, adjust=settle_llm,
                        pages=(
                            SettingsPage("fournisseurs", "Fournisseurs", ("backends",), order=10, extra=who_replies,
                                         description=(
                                "Les services qui font tourner ses modèles. Chaque fournisseur a sa page : son "
                                "type, le modèle choisi dans la liste qu'il propose, sa clé ; le reste est rangé "
                                "dans « Options avancées ». Le premier déclaré sert « répondre » d'office.")),
                            SettingsPage("roles", "Qui sert quoi", ("routes",), order=20, facts=False, description=(
                                             "Chaque rôle (répondre, rêver, retenir, trier le courrier…) choisit "
                                             "son fournisseur. Laisse vide : le rôle retombe sur son repli. "
                                             "« Répondre » est toujours servi : sans choix, par le premier "
                                             "fournisseur déclaré.")),
                        )),
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
