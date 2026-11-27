"""Les fournisseurs de modèles : le texte (``llm``) et la CLI Claude Code (``claude-code``) ; entre les deux, la
commande des domaines qui sont des passerelles de fournisseurs, comme les modèles (``BESIDE_MODELS`` : les images,
``mika images``, la commande de leur domaine, ADR 0317)."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import time
from pathlib import Path

from pydantic import ValidationError

from mika.adapters.llm.claude import AUTHS
from mika.adapters.llm.claude_code import FORBIDDEN, ClaudeCodeBackend, ClaudeCodeError, runtime_dir
from mika.adapters.llm.config import REPLY, ROLE_LABELS, ROLES, BackendSpec, LLMConfig
from mika.adapters.mcp.relay import Relay
from mika.app.cli.common import with_settings
from mika.app.domains import DOMAINS, Domain, part
from mika.app.settings import Settings
from mika.kernel import forms
from mika.ports.llm import EFFORTS, LLMRequest, Message

#: ``mika llm effort defaut <rôles>`` : le rôle n'a plus d'effort à lui, il suit la fiche de son fournisseur
EFFORT_OF_BACKEND = "defaut"
#: les domaines dont la commande vient juste après ``llm`` dans ``mika --help``, dans cet ordre : une passerelle de
#: fournisseurs, comme les modèles (ADR 0317). Leur place, que le cadre garde en noms comme celle d'une ligne de la
#: page des plugins (``ORDER``) ; la commande, elle, est à leur fiche (``Domain.cli``). Celle des autres domaines vient
#: après les commandes du cadre, dans l'ordre des fiches (``app/cli/plugins.py``)
BESIDE_MODELS: tuple[str, ...] = ("imaging",)


def beside_models() -> tuple[Domain, ...]:
    """Les fiches de ``BESIDE_MODELS``, dans son ordre ; un nom sans fiche ou sans commande est refusé
    (``ValueError``) : il n'aurait pas de place, sans bruit."""
    found = {d.name: d for d in DOMAINS if d.cli is not None}
    lost = [name for name in BESIDE_MODELS if name not in found]
    if lost:
        raise ValueError(f"mika --help : {lost} n'ont pas de commande dans leur fiche (Domain.cli)")
    return tuple(found[name] for name in BESIDE_MODELS)


async def llm_command(data: Path, args: argparse.Namespace) -> dict[str, object]:
    async def run(settings: Settings, store) -> dict[str, object]:  # type: ignore[no-untyped-def]
        cfg = settings.llm()
        backends = dict(cfg.backends)
        routes = dict(cfg.routes)
        efforts = dict(cfg.efforts)
        if args.llm_cmd == "backend":
            previous = backends.get(args.name)

            def kept(value, attr, default):  # type: ignore[no-untyped-def]
                return value if value is not None else (getattr(previous, attr) if previous else default)

            # une option omise garde la valeur déclarée, l'adresse comprise : la remettre à vide en gardant
            # la clé enverrait celle-ci à l'hôte par défaut, chez un tiers qui ne l'a pas émise
            # un contexte ni donné ni déjà déclaré n'est pas dit : le modèle choisit le défaut du type (un
            # fournisseur Claude en reçoit 40 000, pas les 24 000 communs)
            context = kept(getattr(args, "context_tokens", None), "context_tokens", None)
            backends[args.name] = BackendSpec(
                **({} if context is None else {"context_tokens": context}),
                kind=args.kind, model=args.model, api_key=kept(args.api_key, "api_key", ""),
                base_url=kept(args.base_url, "base_url", ""), host=kept(args.host, "host", ""),
                slots=kept(args.slots, "slots", 0), temperature=kept(args.temperature, "temperature", None),
                think=kept(args.think, "think", False),
                cache_ttl=previous.cache_ttl if previous else "5m",
                max_reply_tokens=previous.max_reply_tokens if previous else 0,
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
        elif args.llm_cmd == "effort":
            # l'effort d'un rôle (ADR 0285) ; « defaut » le rend à la fiche de son fournisseur
            for role in args.roles:
                if args.level == EFFORT_OF_BACKEND:
                    efforts.pop(role, None)
                else:
                    efforts[role] = args.level
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
                cfg = await settings.save_llm(LLMConfig(backends=backends, routes=routes, efforts=efforts))
            except ValueError as exc:
                return {"ok": False, "problems": [p.strip() for p in str(exc).split(";") if p.strip()]}
        return {"backends": {n: b.redacted() for n, b in cfg.backends.items()}, "routes": cfg.routes,
                "efforts": cfg.efforts, "répondre": cfg.routes.get(REPLY, ""),
                "problems": cfg.problems()}

    try:
        return await with_settings(data, run)
    except ValidationError as exc:  # une fiche refusée (un contexte au-delà de la fenêtre lue du modèle)
        return {"ok": False, "problems": list(forms.errors_fr(exc).values())}


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

    return await with_settings(data, run)


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
    lb.add_argument("--auth", choices=list(AUTHS), default=None,
                    help="claude_code : le login de la CLI (défaut) ou une clé d'API")
    lb.add_argument("--claude-bin", default=None, help="claude_code : la commande claude (vide : PATH)")
    lb.add_argument("--config-dir", default=None, help="claude_code : un dossier de CLI à part (vide : l'habituel)")
    lb.add_argument("--effort", default=None, choices=list(EFFORTS),
                    help="claude_code : l'effort de réflexion (vide : le défaut de la CLI ; omis : la valeur actuelle)")
    # juste après ``llm`` : la commande des domaines qui sont des passerelles de fournisseurs (``BESIDE_MODELS``,
    # ADR 0317) — ``mika images``
    for domain in beside_models():
        part(domain.cli, "add")(sub)
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
    le = lsub.add_parser("effort", help="l'effort de réflexion d'un ou plusieurs rôles : il l'emporte sur celui de "
                                        "la fiche du fournisseur (« defaut » : le rôle la suit de nouveau)",
                         epilog="Les rôles : " + " ; ".join(f"{r} ({ROLE_LABELS.get(r, r)})" for r in ROLES))
    le.add_argument("level", choices=[*(e for e in EFFORTS if e), EFFORT_OF_BACKEND], metavar="effort",
                    help=f"{', '.join(e for e in EFFORTS if e)}, ou {EFFORT_OF_BACKEND}")
    le.add_argument("roles", nargs="+", choices=ROLES, metavar="rôle", help="polish, triage, caption…")
    lx = lsub.add_parser("remove")
    lx.add_argument("name")
    lb.add_argument("--context-tokens", type=int, default=None, help="fenêtre totale de ce fournisseur")
    lb.add_argument("--max-output-tokens", type=int, default=None, help="plafond de sortie de ce fournisseur")
    lc = lsub.add_parser("context", help="taille du contexte d'un fournisseur (jetons)")
    lc.add_argument("tokens", type=int)
    lc.add_argument("--name", default=None, help="fournisseur ; par défaut celui du rôle reply")
    lm.set_defaults(run=_run_llm)
    cc.set_defaults(run=_run_claude_code)
