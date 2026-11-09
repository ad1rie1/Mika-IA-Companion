"""Les fournisseurs de modèles : le texte (``llm``), les images (``images``), la CLI Claude Code (``claude-code``)."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import time
from pathlib import Path

from pydantic import ValidationError

from mika.adapters.imaging.config import ImageBackendSpec, ImagingConfig
from mika.adapters.imaging.config import build_gateway as build_image_gateway
from mika.adapters.llm.claude_code import FORBIDDEN, ClaudeCodeBackend, ClaudeCodeError, runtime_dir
from mika.adapters.llm.config import REPLY, ROLE_LABELS, ROLES, BackendSpec, LLMConfig
from mika.adapters.mcp.relay import Relay
from mika.adapters.system import RealClock
from mika.app.cli.common import _with_settings
from mika.app.settings import Settings
from mika.kernel import forms
from mika.ports.imaging import ASPECTS, QUALITIES, ImageRequest
from mika.ports.imaging import ROLE_LABELS as IMAGE_ROLE_LABELS
from mika.ports.imaging import ROLES as IMAGE_ROLES
from mika.ports.llm import LLMRequest, Message


async def llm_command(data: Path, args: argparse.Namespace) -> dict[str, object]:
    async def run(settings: Settings, store) -> dict[str, object]:  # type: ignore[no-untyped-def]
        cfg = settings.llm()
        backends = dict(cfg.backends)
        routes = dict(cfg.routes)
        if args.llm_cmd == "backend":
            previous = backends.get(args.name)

            def kept(value, attr, default):  # type: ignore[no-untyped-def]
                return value if value is not None else (getattr(previous, attr) if previous else default)

            # une option omise garde la valeur déclarée, l'adresse comprise : la remettre à vide en gardant
            # la clé enverrait celle-ci à l'hôte par défaut, chez un tiers qui ne l'a pas émise
            backends[args.name] = BackendSpec(
                kind=args.kind, model=args.model, api_key=kept(args.api_key, "api_key", ""),
                base_url=kept(args.base_url, "base_url", ""), host=kept(args.host, "host", ""),
                slots=kept(args.slots, "slots", 0), temperature=kept(args.temperature, "temperature", None),
                think=kept(args.think, "think", False),
                cache_ttl=previous.cache_ttl if previous else "5m",
                max_reply_tokens=previous.max_reply_tokens if previous else 0,
                context_tokens=kept(getattr(args, "context_tokens", None), "context_tokens", 24_000),
                max_output_tokens=kept(getattr(args, "max_output_tokens", None), "max_output_tokens", 0),
                chars_per_token=previous.chars_per_token if previous else 3.6,
                quota_ceiling=previous.quota_ceiling if previous else 0.8,
                auth=kept(args.auth, "auth", "abonnement"), claude_bin=kept(args.claude_bin, "claude_bin", ""),
                config_dir=kept(args.config_dir, "config_dir", ""),
                effort=kept(getattr(args, "effort", None), "effort", ""),
                workspace=kept(getattr(args, "workspace", None), "workspace", ""),
                # ce que la console a lu du modèle (ADR 0136) ; un autre modèle l'oublie de lui-même
                detected_window=previous.detected_window if previous else 0,
                detected_output=previous.detected_output if previous else 0,
                detected_for=previous.detected_for if previous else "",
            )
        elif args.llm_cmd == "route":
            for role in args.roles:
                routes[role] = args.name
        elif args.llm_cmd == "remove":
            backends.pop(args.name, None)
            routes = {r: b for r, b in routes.items() if b != args.name}
        elif args.llm_cmd == "context":
            name = args.name or routes.get(REPLY, "")
            if name not in backends:
                return {"ok": False, "problems": ["Déclarer le fournisseur avant de régler son contexte."]}
            raw = backends[name].model_dump()
            raw["context_tokens"] = args.tokens
            backends[name] = BackendSpec.model_validate(raw)
        if args.llm_cmd != "show":
            # ce qui vaut désormais : le premier fournisseur déclaré y sert « répondre » d'office ; une
            # configuration refusée (un fournisseur inconnu) l'est en le disant, rien n'est gardé
            try:
                cfg = await settings.save_llm(LLMConfig(backends=backends, routes=routes))
            except ValueError as exc:
                return {"ok": False, "problems": [p.strip() for p in str(exc).split(";") if p.strip()]}
        return {"backends": {n: b.redacted() for n, b in cfg.backends.items()}, "routes": cfg.routes,
                "répondre": cfg.routes.get(REPLY, ""),
                "problems": cfg.problems()}

    try:
        return await _with_settings(data, run)
    except ValidationError as exc:  # une fiche refusée (un contexte au-delà de la fenêtre lue du modèle)
        return {"ok": False, "problems": list(forms.errors_fr(exc).values())}


async def images_command(data: Path, args: argparse.Namespace) -> dict[str, object]:
    """Les fournisseurs d'images : montrer, déclarer, router, retirer — ou faire un essai avec la
    configuration enregistrée (``essai`` n'écrit rien d'autre que l'image demandée)."""
    async def run(settings: Settings, store) -> dict[str, object]:  # type: ignore[no-untyped-def]
        cfg = settings.imaging()
        if args.images_cmd == "essai":
            return await _image_trial(cfg, args)
        backends = dict(cfg.backends)
        routes = dict(cfg.routes)
        if args.images_cmd == "backend":
            previous = backends.get(args.name)

            def kept(value, attr, default):  # type: ignore[no-untyped-def]
                return value if value is not None else (getattr(previous, attr) if previous else default)

            backends[args.name] = ImageBackendSpec(
                kind=args.kind, model=args.model, api_key=kept(args.api_key, "api_key", ""),
                base_url=kept(args.base_url, "base_url", ""), fallback=kept(args.fallback, "fallback", ""),
                adult=kept(args.adult, "adult", False), moderation=kept(args.moderation, "moderation", "auto"),
                slots=kept(args.slots, "slots", 0))
        elif args.images_cmd == "route":
            for role in args.roles:
                routes[role] = args.name
        elif args.images_cmd == "remove":
            backends.pop(args.name, None)
            routes = {r: b for r, b in routes.items() if b != args.name}
        if args.images_cmd != "show":
            try:
                cfg = await settings.save_imaging(ImagingConfig(backends=backends, routes=routes))
            except ValueError as exc:
                return {"ok": False, "problems": [p.strip() for p in str(exc).split(";") if p.strip()]}
        return {"ok": True, "activée": cfg.enabled, "backends": {n: b.redacted() for n, b in cfg.backends.items()},
                "routes": cfg.routes, "problems": cfg.problems()}

    return await _with_settings(data, run)


async def _image_trial(cfg: ImagingConfig, args: argparse.Namespace) -> dict[str, object]:
    if not cfg.enabled:
        return {"ok": False, "problems": ["aucun fournisseur d'images : déclare-en un (mika images backend …)"]}
    gateway = build_image_gateway(cfg, RealClock())
    try:
        result = await gateway.generate(ImageRequest(role=args.role, call_id=f"essai-{os.getpid()}",
                                                     prompt=args.prompt, aspect=args.aspect, quality=args.quality,
                                                     lane="conversation", priority=0))
    finally:
        for backend in gateway.backends.values():
            close = getattr(backend, "aclose", None)
            if close is not None:
                await close()
    files = []
    ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
    for i, picture in enumerate(result.images):
        out: Path = args.out if args.out.suffix else args.out.with_suffix(ext.get(picture.mime, ".png"))
        if i:
            out = out.with_name(f"{out.stem}-{i + 1}{out.suffix}")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(picture.data)
        files.append(str(out))
    return {"ok": result.ok, "issue": result.outcome, "fournisseur": result.backend, "modèle": result.model,
            "taille": result.size, "qualité": result.quality, "coût_usd": round(result.cost_usd, 4),
            "raison": result.reason, "prompt_réécrit": result.revised_prompt, "fichiers": files, "problems": []}


async def _claude_code_spec(data: Path, name: str | None) -> BackendSpec:
    """Le fournisseur Claude Code déclaré (le premier, ou celui nommé) ; à défaut, la CLI telle quelle."""
    async def run(settings: Settings, store) -> BackendSpec:  # type: ignore[no-untyped-def]
        backends = settings.llm().backends
        if name:
            if name not in backends or backends[name].kind != "claude_code":
                raise SystemExit(f"aucun fournisseur Claude Code nommé « {name} »")
            return backends[name]
        return next((b for b in backends.values() if b.kind == "claude_code"),
                    BackendSpec(kind="claude_code", model=""))

    return await _with_settings(data, run)


async def claude_code_check(data: Path, name: str | None) -> dict[str, object]:
    """Un appel sans outil : la CLI répond-elle, avec quel modèle, quel usage de l'abonnement ?"""
    spec = await _claude_code_spec(data, name)
    backend = ClaudeCodeBackend(spec.model, relay=Relay(), relay_base=None, auth=spec.auth, api_key=spec.api_key,
                                claude_bin=spec.claude_bin, config_dir=spec.config_dir, work_dir=runtime_dir(data))
    req = LLMRequest(role="check", call_id="verification#0", system_stable="Réponds exactement : ok",
                     messages=(Message("user", "ping"),), priority=0)
    t0 = time.monotonic()
    done = asyncio.Event()

    async def watch() -> bool:
        """Pendant l'appel : la CLI ouvre-t-elle une socket de messagerie entre sessions ? (elle ne devrait plus)"""
        seen = False
        while not done.is_set():
            seen = seen or backend.opened_socket(req.call_id)
            await asyncio.sleep(0.05)
        return seen

    watcher = asyncio.create_task(watch())
    try:
        resp = await backend.complete(req)
    except ClaudeCodeError as exc:
        return {"ok": False, "erreur": str(exc), "commande": backend.binary(), "connexion": spec.auth}
    finally:
        done.set()
        socket = await watcher
        await backend.aclose()
    return {"ok": True, "réponse": resp.text, "modèle": resp.model, "connexion": spec.auth,
            "secondes": round(time.monotonic() - t0, 1), "abonnement": backend.status()["quota"],
            "messagerie_entre_sessions": "ouverte" if socket else "fermée"}


def claude_code_login(data: Path, name: str | None) -> int:
    """Ouvre la CLI en interactif dans son dossier dédié : l'utilisateur s'y connecte lui-même
    (``/login``) ; Mika ne voit rien passer."""
    spec = asyncio.run(_claude_code_spec(data, name))
    if not spec.config_dir:
        print("Ce fournisseur utilise la CLI telle que tu l'as connectée : lance « claude » et « /login » "
              "si elle ne l'est pas.")
        return 0
    env = {k: v for k, v in os.environ.items() if k not in FORBIDDEN}
    env["CLAUDE_CONFIG_DIR"] = spec.config_dir
    binary = ClaudeCodeBackend(relay=Relay(), relay_base=None, claude_bin=spec.claude_bin).binary()
    print(f"Connexion de la CLI dans {spec.config_dir} : tape /login, puis quitte.")
    return subprocess.run([binary], env=env, check=False).returncode


def _run_llm(args: argparse.Namespace) -> int:
    out = asyncio.run(llm_command(args.data, args))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if not out["problems"] else 1


def _run_images(args: argparse.Namespace) -> int:
    out = asyncio.run(images_command(args.data, args))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok") and not out.get("problems") else 1


def _run_claude_code(args: argparse.Namespace) -> int:
    if args.cc_cmd == "login":
        return claude_code_login(args.data, args.name)
    out = asyncio.run(claude_code_check(args.data, args.name))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out["ok"] else 1


def add_models(sub) -> None:  # type: ignore[no-untyped-def]
    lm = sub.add_parser("llm", help="fournisseurs de modèles et rôles")
    lsub = lm.add_subparsers(dest="llm_cmd", required=True)
    lsub.add_parser("show")
    lb = lsub.add_parser("backend", help="déclarer ou modifier un fournisseur")
    lb.add_argument("name")
    lb.add_argument("--kind", required=True, choices=["claude", "claude_code", "openai", "ollama", "ollama_cloud"])
    lb.add_argument("--model", required=True)
    lb.add_argument("--api-key", default=None, help="laissé vide : la clé actuelle est gardée")
    lb.add_argument("--workspace", default=None,
                    help="claude : l'espace de travail (wrkspc_…) d'une clé qui n'y est pas attachée (omis : l'actuel)")
    lb.add_argument("--base-url", default=None, help="openai : un serveur compatible (omis : l'adresse actuelle)")
    lb.add_argument("--host", default=None, help="ollama : l'hôte (omis : l'hôte actuel)")
    lb.add_argument("--slots", type=int, default=None, help="appels simultanés (omis : la valeur actuelle)")
    lb.add_argument("--temperature", type=float, default=None, help="omise : la valeur actuelle")
    lb.add_argument("--think", action=argparse.BooleanOptionalAction, default=None,
                    help="ollama : laisser réfléchir (omis : la valeur actuelle)")
    lb.add_argument("--auth", choices=["abonnement", "cle_api"], default=None,
                    help="claude_code : le login de la CLI (défaut) ou une clé d'API")
    lb.add_argument("--claude-bin", default=None, help="claude_code : la commande claude (vide : PATH)")
    lb.add_argument("--config-dir", default=None, help="claude_code : un dossier de CLI à part (vide : l'habituel)")
    lb.add_argument("--effort", default=None, choices=["", "low", "medium", "high", "xhigh", "max"],
                    help="claude_code : l'effort de réflexion (vide : le défaut de la CLI ; omis : la valeur actuelle)")
    im = sub.add_parser("images", help="fournisseurs d'images et rôles (aucun : elle n'en génère pas)")
    isub = im.add_subparsers(dest="images_cmd", required=True)
    isub.add_parser("show")
    ib = isub.add_parser("backend", help="déclarer ou modifier un fournisseur d'images (le premier sert « draw »)")
    ib.add_argument("name")
    ib.add_argument("--kind", required=True, choices=["openai", "sdcpp", "openai_compatible"])
    ib.add_argument("--model", required=True)
    ib.add_argument("--api-key", default=None, help="laissé vide : la clé actuelle est gardée")
    ib.add_argument("--base-url", default=None, help="sdcpp : http://127.0.0.1:8190 ; openai_compatible : jusqu'à /v1")
    ib.add_argument("--fallback", default=None, help="le fournisseur qui prend le relais d'une panne")
    ib.add_argument("--adult", action=argparse.BooleanOptionalAction, default=None,
                    help="sdcpp, openai_compatible : le serveur accepte le contenu pour adultes")
    ib.add_argument("--moderation", choices=["auto", "low"], default=None, help="openai : sévérité de la modération")
    ib.add_argument("--slots", type=int, default=None, help="images en même temps (0 : 1 en local, 2 ailleurs)")
    ir = isub.add_parser("route", help="associer des rôles à un fournisseur d'images",
                         epilog="Les rôles : " + " ; ".join(f"{r} ({IMAGE_ROLE_LABELS[r]})" for r in IMAGE_ROLES))
    ir.add_argument("name")
    ir.add_argument("roles", nargs="+", choices=IMAGE_ROLES, metavar="rôle", help="draw, edit, own")
    ix = isub.add_parser("remove")
    ix.add_argument("name")
    ie = isub.add_parser("essai", help="générer une image avec la configuration enregistrée")
    ie.add_argument("prompt")
    ie.add_argument("--out", type=Path, required=True, help="le fichier (l'extension suit le format rendu)")
    ie.add_argument("--role", default="draw", choices=IMAGE_ROLES)
    ie.add_argument("--aspect", default="square", choices=list(ASPECTS))
    ie.add_argument("--quality", default="normal", choices=QUALITIES)
    cc = sub.add_parser("claude-code", help="la CLI Claude Code comme moteur (son login, jamais un jeton)")
    ccsub = cc.add_subparsers(dest="cc_cmd", required=True)
    for name, text in (("check", "un appel d'essai : connectée ? quel modèle ? quel usage de l'abonnement ?"),
                       ("login", "se connecter dans le dossier dédié du fournisseur (s'il en a un)")):
        c = ccsub.add_parser(name, help=text)
        c.add_argument("--name", default=None, help="le fournisseur (défaut : le premier de type claude_code)")
    lr = lsub.add_parser("route", help="associer des rôles à un fournisseur (seul « reply » est nécessaire : le "
                                       "premier fournisseur déclaré le sert d'office, les autres rôles y "
                                       "retombent)",
                         epilog="Les rôles : " + " ; ".join(f"{r} ({ROLE_LABELS.get(r, r)})" for r in ROLES))
    lr.add_argument("name", help="un fournisseur déclaré (mika llm backend …)")
    lr.add_argument("roles", nargs="+", choices=ROLES, metavar="rôle", help="reply, initiative, extract…")
    lx = lsub.add_parser("remove")
    lx.add_argument("name")
    lb.add_argument("--context-tokens", type=int, default=None, help="fenêtre totale de ce fournisseur")
    lb.add_argument("--max-output-tokens", type=int, default=None, help="plafond de sortie de ce fournisseur")
    lc = lsub.add_parser("context", help="taille du contexte d'un fournisseur (jetons)")
    lc.add_argument("tokens", type=int)
    lc.add_argument("--name", default=None, help="fournisseur ; par défaut celui du rôle reply")
    lm.set_defaults(run=_run_llm)
    im.set_defaults(run=_run_images)
    cc.set_defaults(run=_run_claude_code)
