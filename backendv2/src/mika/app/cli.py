"""Ligne de commande : ``python -m mika <commande>``.

- ``replay --verify`` : reconstruit tout depuis la genèse et compare à l'état
  obtenu par instantané + queue ;
- ``rebuild <propriétaire>…`` : reconstruction par clôture ;
- ``forget <sujet>`` : oubli (contenus et projections) ;
- ``sim selftest`` : auto-test du simulateur ;
- ``serve`` : le serveur ;
- ``backup DEST`` / ``verify ARCHIVE`` / ``restore ARCHIVE`` : sauvegarde
  (sans risque serveur en marche), vérification, restauration (serveur
  arrêté ; l'ancien dossier est mis de côté) ;
- ``llm show|backend|route|remove|context`` : les modèles (clés chiffrées) ;
- ``account <nom> [<mot de passe>] [--operator]`` : un compte (sans mot de passe : demandé sans écho) ;
- ``token create <compte> [--label …] [--client screen|mobile]`` / ``token list [<compte>]`` / ``token revoke <id>`` :
  les jetons d'un client natif (un moteur de jeu sur ``/ws/world``, ADR 0051 ; l'application du téléphone, ADR
  0062, qui obtient d'ordinaire le sien par ``POST /auth/token``) — montrés une seule fois, gardés en empreinte ;
  serveur en marche, une révocation ferme ses connexions au plus tard dix secondes après ;
- ``serve --origin URL --cookie-secure --behind-proxy`` : derrière un mandataire TLS ;
- ``console apercu --out DOSSIER`` : chaque page de la console, exportée ;
- ``identity link|unlink``, ``social closeness`` et ``forge promote|demote`` : ce
  qu'un opérateur sait mieux qu'elle (serveur arrêté : une seule écriture à la fois
  dans ``mind.db``). Ce sont les actions de la console, par le même chemin
  (``runtime/operations.py``) : mêmes refus, même garde, même audit.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from mika.adapters.imaging.config import ImageBackendSpec, ImagingConfig
from mika.adapters.imaging.config import build_gateway as build_image_gateway
from mika.adapters.llm.claude_code import FORBIDDEN, ClaudeCodeBackend, ClaudeCodeError, runtime_dir
from mika.adapters.llm.config import REPLY, ROLE_LABELS, ROLES, BackendSpec, LLMConfig, build_backend
from mika.adapters.mail import LEGACY_ACCOUNT
from mika.adapters.mcp.hub import McpHub
from mika.adapters.mcp.relay import Relay
from mika.adapters.shares import DiskShares
from mika.adapters.store_sqlite import SqliteStore
from mika.adapters.system import RandomIdGen, RealClock
from mika.adapters.vectors import SentenceEmbedder, SqliteVectorIndex
from mika.adapters.web.accounts import Accounts, password_problems
from mika.app import backup, composition, datadir
from mika.app.composition import faculties, for_simulation
from mika.app.server import serve
from mika.app.settings import SecretBox, Settings
from mika.app.teams import TeamsDesk
from mika.app.wakeups import WakeupDesk
from mika.contracts import identity as identity_c
from mika.kernel import forms
from mika.kernel.codec import digest
from mika.kernel.events import Origin
from mika.kernel.inspect import Head
from mika.kernel.registry import Registry
from mika.ports.imaging import ASPECTS, QUALITIES, ImageRequest
from mika.ports.imaging import ROLE_LABELS as IMAGE_ROLE_LABELS
from mika.ports.imaging import ROLES as IMAGE_ROLES
from mika.ports.llm import LLMRequest, Message
from mika.runtime import operations
from mika.runtime.bootstrap import Kernel
from mika.runtime.inspection import Inspection
from mika.runtime.mind import Mind
from mika.runtime.state import RUNTIME
from mika.sim.catalog import run_lane
from mika.sim.report import write as write_report
from mika.sim.selftest import run as sim_selftest
from mika.sim.sonde import run_probe
from mika.vocab.people import is_identifiable

#: qui opère depuis la ligne de commande (l'audit ``runtime.operated`` le dit)
CLI_BY = "ligne de commande"

#: ce que ``mika --help`` dit à qui la lance pour la première fois
FIRST_STEPS = """Premiers pas :
  1. mika serve                 la lance (http://127.0.0.1:8001), ses données dans ./data/v2
  2. http://127.0.0.1:8001/inspecteur/
                                la console : crée le compte opérateur (le premier compte l'est)
  3. Configuration › Fournisseurs › Ajouter
                                un modèle (Claude, Ollama…) : le premier déclaré la fait parler
  4. le frontend : cd frontend/Web && npm install && npm run dev, puis http://localhost:3000
                                (il vise :8001 ; VITE_BACKEND_ORIGIN pour une autre adresse)

Tout se règle aussi d'ici : mika llm, mika account, mika token… (mika <commande> --help).
Démarrage local pas à pas : backendv2/README.md ; en service (systemd) : deploy/README.md."""


def ask_password(ask: Callable[[str], str] | None = None) -> str | None:
    """Le mot de passe demandé sans écho, deux fois ; ``None`` s'ils diffèrent."""
    ask = ask or getpass.getpass
    first = ask("Mot de passe : ")
    return first if ask("Encore une fois : ") == first else None


def _mind(data: Path, *, snapshot_every: int = 500) -> Mind:
    datadir.hold(data)  # le journal ne s'écrit qu'à un seul à la fois (serveur arrêté)
    store = SqliteStore(data / "mind.db", data / "views.db", threaded=False)
    return Mind(Registry([RUNTIME, *faculties()]), store, RealClock(), RandomIdGen(), snapshot_every=snapshot_every)


def _state(mind: Mind) -> str:
    return digest({o: mind.root.slices[o] for o in mind.registry.persisted_owners()})


async def replay_verify(data: Path) -> dict[str, object]:
    fast = _mind(data)
    r1 = await fast.boot(append_boot=False)
    d1 = _state(fast)
    await fast.close()

    full = _mind(data)
    await full.store.open()
    snaps = full.store.query_mind("SELECT seq, at, data FROM snapshots")
    await full.store.run_mind(lambda sql: sql.execute("DELETE FROM snapshots"))
    await full.store.close()
    r2 = await full.boot(append_boot=False)
    d2 = _state(full)

    async def restore(sql_rows=snaps) -> None:
        def put(sql) -> None:
            for seq, at, payload in sql_rows:
                sql.execute("INSERT OR REPLACE INTO snapshots(seq, at, data) VALUES(?,?,?)", (seq, at, payload))

        await full.store.run_mind(put)

    await restore()
    await full.close()
    return {"identiques": d1 == d2, "instantané": r1.snapshot_seq, "rejoués_depuis_genèse": r2.replayed,
            "tête": r2.head}


async def rebuild(data: Path, owners: list[str]) -> dict[str, object]:
    mind = _mind(data)
    await mind.boot(append_boot=False)
    report = await mind.rebuild(owners)
    # sans instantané, le prochain démarrage relirait l'ancien : la reconstruction ne durerait pas
    root = mind.root
    data_json = mind.snapshot_data(root)
    await mind.store.run_mind(lambda sql: sql.execute(
        "INSERT OR REPLACE INTO snapshots(seq, at, data) VALUES(?,?,?)", (root.seq, root.at, data_json)))
    await mind.close()
    return report


async def _offline(data: Path, *, vectors: bool = False) -> Kernel:
    """Un noyau relu, rien de vivant : aucun processus, aucun modèle (serveur arrêté)."""
    datadir.hold(data)  # serveur arrêté : une seule écriture à la fois
    store = SqliteStore(data / "mind.db", data / "views.db", threaded=False)
    ports: dict[str, object] = {}
    if vectors:  # le modèle ne se charge qu'à un plongement : jamais ici
        ports["vectors"] = SqliteVectorIndex(store, SentenceEmbedder())
    # les octets des fichiers qu'elle a envoyés (ADR 0062) : l'oubli d'une personne les efface aussi d'ici
    ports["shares"] = DiskShares(data / "partages")
    kernel = Kernel(composition.deps(store=store, clock=RealClock(), ids=RandomIdGen(), ports=ports))
    try:
        await kernel.mind.boot(append_boot=False)
    except BaseException:
        datadir.release(data)
        raise
    return kernel


async def _close(kernel: Kernel, data: Path) -> None:
    try:
        await kernel.mind.close()
    finally:
        datadir.release(data)


async def forget(data: Path, subject: str) -> dict[str, object]:
    """L'oubli, comme la console le fait (``operations.forget_subject``) : la clé et tout ce qui
    la désigne — pour une personne, ses autres adresses et les noms qui ne désignent qu'elle —,
    contenus et projections, traces d'épisode, et tout port qui garde une trace dérivée (l'index
    des vecteurs). Audité. Rien ne démarre : aucun processus, aucun modèle."""
    kernel = await _offline(data, vectors=True)
    try:
        await kernel.deps.ports["vectors"].open()
        await kernel.traces.open()
        kinds = sorted(k for k, spec in kernel.registry.subjects.items() if spec.forgettable)
        ins = Inspection(kernel)
        kind = next((k for k in kinds if isinstance(ins.head(k, subject), Head)), "")
        gone = await operations.forget_subject(kernel, kind, subject, by=CLI_BY, action=f"cli.oublier.{kind or 'cle'}")
    finally:
        await _close(kernel, data)
    return {"sujet": subject, "clés": list(gone.keys), "contenus_effacés": gone.counts.get("contents", 0),
            "traces_effacées": gone.counts.get("traces", 0), "vecteurs_effacés": gone.counts.get("vectors", 0),
            "fichiers_effacés": gone.counts.get("shares", 0)}


async def _perform(kernel: Kernel, key: str, subject: str, values: dict[str, str]) -> dict[str, object]:
    spec = kernel.registry.actions.get(key)
    if spec is not None and not operations.offered(kernel, spec, subject):
        return {"ok": False, "message": f"Pas possible sur « {subject} » : {spec.description}".strip()}
    form = {forms.RENDERED: list(values), **{k: [v] for k, v in values.items()}}
    out = await operations.perform(kernel, key, form, by=CLI_BY, subject=subject)
    got: dict[str, object] = {"ok": out.ok and not out.deduped, "message": out.message}
    if out.errors:
        got["erreurs"] = dict(out.errors)
    if out.seqs:
        got["seq"] = out.seqs[-1]
    return got


async def operate(data: Path, key: str, subject: str, values: dict[str, str]) -> dict[str, object]:
    """Une action d'opérateur de la console (``faculté.action``), par le même chemin qu'elle
    (``operations.perform``) : ce qu'elle refuserait est refusé, en le disant ; rien ne dit « ok »
    sans effet ; l'audit ``runtime.operated`` est écrit. La commande tapée vaut confirmation."""
    kernel = await _offline(data)
    try:
        return await _perform(kernel, key, subject, values)
    finally:
        await _close(kernel, data)


async def _prelink(kernel: Kernel, handle: str, person: str) -> dict[str, object]:
    """Relier une adresse qui n'a encore jamais écrit (un compte qu'on attend) : la console
    n'en a pas la fiche, le réducteur l'accepte. Seulement vers une personne connue, par sa clé ;
    jamais une adresse interne ou jetable. Audité."""
    frame = kernel.mind.frame()
    root = frame.get(identity_c.PERSON(person))
    if not is_identifiable(handle):
        return {"ok": False, "message": f"« {handle} » n'est pas une adresse durable : on ne la relie pas."}
    if not frame.get(identity_c.IDENTITY(person)).known or not is_identifiable(root):
        return {"ok": False, "message": f"Personne inconnue : « {person} ». Donne la clé d'une personne connue "
                                        "(une de ses adresses, ex. user_2)."}
    draft = identity_c.LINKED.draft(handle=handle, person=root, by="operator")
    commit = await kernel.mind.append([draft], emitter=identity_c.OWNER, correlation="opérateur:cli.identity",
                                      origin=Origin.EXTERNAL)
    seqs = tuple(commit.seqs)
    await operations.audit(kernel, "cli.identity.relier", by=CLI_BY, subject_kind="handle", subject=handle, seqs=seqs)
    return {"ok": True, "message": f"« {handle} » parlera pour {root} dès qu'elle écrira.",
            "seq": seqs[-1] if seqs else None}


async def identity_command(data: Path, cmd: str, handle: str, person: str | None) -> dict[str, object]:
    """``identity link|unlink`` : l'action de la console sur une adresse connue (mêmes refus : jamais
    une session authentifiée, que le réducteur ignorerait) ; une adresse jamais vue ne peut qu'être
    reliée d'avance."""
    kernel = await _offline(data)
    try:
        view = kernel.mind.frame().get(identity_c.IDENTITY(handle))
        if cmd == "link" and person is not None:
            if view.authenticated:
                return {"ok": False, "message": "Une session authentifiée prouve déjà qui écrit : on ne la relie "
                                                "à personne."}
            if not view.known:
                return await _prelink(kernel, handle, person)
            return await _perform(kernel, "identity.relier", handle, {"person": person, "confirmed": "1"})
        if not view.known:
            return {"ok": False, "message": f"Adresse inconnue : « {handle} »."}
        return await _perform(kernel, "identity.delier", handle, {})
    finally:
        await _close(kernel, data)


async def mcp_command(settings: Settings, args: argparse.Namespace) -> dict[str, object]:
    """``mika mcp serveurs`` / ``mika mcp essai <serveur>`` : ce qui est branché, et ce qu'un serveur propose
    maintenant (avec, pour chaque outil, ce que l'opérateur en a décidé). Aucun secret n'est rendu."""
    hub = McpHub(settings.mcp, settings.mcp_tools, settings.save_mcp_tools, local_root=args.data / "mcp")
    try:
        if args.mcp_cmd == "serveurs":
            return {"ok": True, "serveurs": [
                {"nom": n, "ou": s.transport, "actif": s.enabled, "a_quoi": s.purpose,
                 "adresse": s.url if not s.local else s.command, "pour": s.audience, "manque": s.problems()}
                for n, s in sorted(settings.mcp().servers.items())]}
        ok, message = await hub.test(args.serveur)
        status = hub.status(args.serveur)
        tools = []
        for t in status.live if status is not None else ():
            review = status.reviews.get(t.remote) if status is not None else None
            state = ("à regarder" if review is None else "suspendu (changé)" if review.enabled
                     and review.fingerprint != t.fingerprint else "approuvé" if review.enabled else "désactivé")
            tools.append({"outil": t.remote, "description": t.description, "lecture_seule": t.read_only_hint,
                          "etat": state})
        return {"ok": ok, "message": message, "outils": tools}
    finally:
        await hub.aclose()


async def _with_settings(data: Path, fn):  # type: ignore[no-untyped-def]
    store = SqliteStore(data / "mind.db", data / "views.db", threaded=False)
    await store.open()
    try:
        settings = Settings(store, SecretBox.for_data(data))
        await settings.open()
        return await fn(settings, store)
    finally:
        await store.close()


async def teams_command(settings: Settings, args: argparse.Namespace) -> dict[str, object]:
    """Teams (ADR 0069) hors ligne : la clé de l'extension (neuve, montrée une fois ; retirée), et l'état."""
    desk = TeamsDesk(settings, RealClock().now, None)
    if args.teams_cmd == "key":
        return {"ok": True, "key": await desk.new_key("ligne de commande"),
                "usage": "à coller dans l'extension de navigateur ; Authorization: Bearer <clé> sur /api/teams/…"}
    if args.teams_cmd == "revoke":
        return {"ok": await desk.revoke_key("ligne de commande")}
    cfg, key = settings.teams(), desk.key_state()
    return {"ok": True, "enabled": cfg.enabled, "mode": cfg.mode, "sign": cfg.sign, "autodraft": cfg.autodraft,
            "key": f"{key.hint}…" if key is not None else None}


async def wakeup_command(settings: Settings, args: argparse.Namespace) -> dict[str, object]:
    """Les réveils par API (ADR 0068) hors ligne : les lister, leur donner une clé (montrée une fois), la retirer."""
    desk = WakeupDesk(settings, RealClock().now)
    if args.wakeup_cmd == "list":
        return {"ok": True, "endpoints": [
            {"name": ep.name, "label": ep.label, "enabled": ep.enabled, "project": ep.project or None,
             "plain": ep.plain, "tools": list(ep.bundles), "rouse": ep.rouse, "notify": ep.notify,
             "key": f"{ep.key.hint}…" if ep.key is not None else None} for ep in desk.endpoints()]}
    if args.wakeup_cmd == "key":
        try:
            key = await desk.new_key(args.name, "ligne de commande")
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "name": args.name, "key": key,
                "usage": f"POST /api/wake/{args.name} avec l'en-tête Authorization: Bearer <clé>"}
    if not await desk.revoke_key(args.name, "ligne de commande"):
        return {"ok": False, "error": f"« {args.name} » n'a pas de clé."}
    return {"ok": True, "name": args.name, "revoked": True}


def _sonde(data: Path, args: argparse.Namespace) -> int:
    """Une semaine de sa vie avec le vrai modèle configuré dans ``data`` (sans y écrire : la semaine vit à part,
    dans ``--out``)."""
    cfg = asyncio.run(_with_settings(data, _llm_of))
    name = args.backend or cfg.routes.get("reply", "")
    spec = cfg.backends.get(name)
    if spec is None:
        print(f"Aucun fournisseur « {name or '(rôle reply)'} » : déclare-le avec « mika llm backend » d'abord.")
        return 2
    if spec.kind == "claude_code":
        print("La sonde ne passe pas par Claude Code : son relais d'outils ne vit que dans le serveur.")
        return 2
    # le vrai modèle de plongements quand il est installé (la mémoire rappelle comme en service), sinon le hachage
    embedder = SentenceEmbedder() if importlib.util.find_spec("sentence_transformers") else None
    out = run_probe(for_simulation(), build_backend(name, spec), args.out, embedder=embedder,
                    which=args.semaine)
    print((out / "bilan.txt").read_text(), end="")
    print(f"la semaine : {out / 'fil.txt'}")
    return 0


async def _llm_of(settings: Settings, store: object) -> LLMConfig:
    return settings.llm()


async def llm_command(data: Path, args: argparse.Namespace) -> dict[str, object]:
    async def run(settings: Settings, store) -> dict[str, object]:  # type: ignore[no-untyped-def]
        cfg = settings.llm()
        backends = dict(cfg.backends)
        routes = dict(cfg.routes)
        context = cfg.context_tokens
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
                quota_ceiling=previous.quota_ceiling if previous else 0.8,
                auth=kept(args.auth, "auth", "abonnement"), claude_bin=kept(args.claude_bin, "claude_bin", ""),
                config_dir=kept(args.config_dir, "config_dir", ""), fallback=kept(args.fallback, "fallback", ""),
            )
        elif args.llm_cmd == "route":
            for role in args.roles:
                routes[role] = args.name
        elif args.llm_cmd == "remove":
            backends.pop(args.name, None)
            routes = {r: b for r, b in routes.items() if b != args.name}
        elif args.llm_cmd == "context":
            context = args.tokens
        if args.llm_cmd != "show":
            # ce qui vaut désormais : le premier fournisseur déclaré y sert « répondre » d'office ; une
            # configuration refusée (un fournisseur inconnu) l'est en le disant, rien n'est gardé
            try:
                cfg = await settings.save_llm(LLMConfig(backends=backends, routes=routes, context_tokens=context))
            except ValueError as exc:
                return {"ok": False, "problems": [p.strip() for p in str(exc).split(";") if p.strip()]}
        return {"backends": {n: b.redacted() for n, b in cfg.backends.items()}, "routes": cfg.routes,
                "répondre": cfg.routes.get(REPLY, ""), "context_tokens": cfg.context_tokens,
                "problems": cfg.problems()}

    return await _with_settings(data, run)


async def images_command(data: Path, args: argparse.Namespace) -> dict[str, object]:
    """Les fournisseurs d'images : montrer, déclarer, router, retirer — ou faire un essai avec la
    configuration enregistrée (``essai`` n'écrit rien d'autre que l'image demandée)."""
    async def run(settings: Settings, store) -> dict[str, object]:  # type: ignore[no-untyped-def]
        cfg = settings.imaging()
        if args.images_cmd == "essai":
            return await _image_essai(cfg, args)
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


async def _image_essai(cfg: ImagingConfig, args: argparse.Namespace) -> dict[str, object]:
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
    try:
        resp = await backend.complete(req)
    except ClaudeCodeError as exc:
        return {"ok": False, "erreur": str(exc), "commande": backend.binary(), "connexion": spec.auth}
    finally:
        await backend.aclose()
    return {"ok": True, "réponse": resp.text, "modèle": resp.model, "connexion": spec.auth,
            "secondes": round(time.monotonic() - t0, 1), "abonnement": backend.status()["quota"]}


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


async def account_command(data: Path, args: argparse.Namespace) -> dict[str, object]:
    async def run(settings: Settings, store) -> dict[str, object]:  # type: ignore[no-untyped-def]
        accounts = Accounts(store)
        await accounts.open()
        problems = password_problems(args.password, args.username)
        if problems:
            return {"ok": False, "error": " ".join(problems)}
        acc = await accounts.create(args.username, args.password, operator=args.operator,
                                    full_name=args.full_name or "")
        return {"ok": True, "person_id": acc.handle, "operator": acc.operator}

    return await _with_settings(data, run)


def _when(ts: int | None) -> str | None:
    return datetime.fromtimestamp(ts, tz=UTC).isoformat(timespec="seconds") if ts else None


async def token_command(data: Path, args: argparse.Namespace) -> dict[str, object]:
    """Les jetons des clients natifs : un jeton parle sous l'adresse de son compte (``user_<pk>``)."""
    async def run(settings: Settings, store) -> dict[str, object]:  # type: ignore[no-untyped-def]
        accounts = Accounts(store)
        await accounts.open()
        if args.token_cmd == "create":
            found = accounts.by_name(args.username)
            if found is None:
                return {"ok": False, "error": f"Compte inconnu : « {args.username} »."}
            try:
                info, raw = await accounts.create_token(found[0].id, args.label, client=args.client)
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}
            return {"ok": True, "id": info.id, "person_id": found[0].handle, "client": info.client, "token": raw,
                    "usage": "montré une seule fois : hello.token, ou l'en-tête « Authorization: Bearer <jeton> », "
                             "sur /ws/world (et /ws, sans en-tête Origin)"}
        if args.token_cmd == "list":
            account = None
            if args.username:
                found = accounts.by_name(args.username)
                if found is None:
                    return {"ok": False, "error": f"Compte inconnu : « {args.username} »."}
                account = found[0].id
            return {"ok": True, "tokens": [{"id": t.id, "account": t.username, "label": t.label,
                                            "client": t.client, "source": t.source,
                                            "created": _when(t.created_at), "last_used": _when(t.last_used),
                                            "revoked": t.revoked} for t in accounts.tokens(account)]}
        if await accounts.revoke_token(args.id):
            return {"ok": True, "revoked": args.id}
        return {"ok": False, "error": f"Jeton inconnu ou déjà révoqué : {args.id}."}

    return await _with_settings(data, run)


async def world_command(data: Path, args: argparse.Namespace) -> dict[str, object]:
    """Le courrier, les flux, la transcription : ce qu'elle perçoit du monde."""

    async def run(settings: Settings, store) -> dict[str, object]:  # type: ignore[no-untyped-def]
        if args.cmd == "mail":
            if args.mail_cmd == "set":
                await settings.save_mail_account(
                    args.compte, address=args.address, imap_host=args.imap_host, imap_port=args.imap_port,
                    imap_ssl=None if args.imap_ssl is None else args.imap_ssl == "oui", user=args.user,
                    password=args.password, smtp_host=args.smtp_host, smtp_port=args.smtp_port,
                    smtp_security=args.smtp_security, since_days=args.since_days,
                    folders=tuple(args.dossiers) if args.dossiers else None, voice=args.voix,
                    display_name=args.nom)
            elif args.mail_cmd == "remove":
                cfg = settings.email()
                if args.compte not in cfg.accounts:
                    raise SystemExit(f"compte inconnu : {args.compte}")
                await settings.save_email(cfg.model_copy(update={"accounts": {
                    k: a for k, a in cfg.accounts.items() if k != args.compte}}))
            out = {}
            for name, account in settings.email().accounts.items():
                shown = account.model_dump(mode="json")
                for secret in ("password", "smtp_password"):
                    shown[secret] = "…" if shown[secret] else ""
                out[name] = shown
            return {"accounts": out}
        if args.cmd == "rss":
            feeds = settings.feeds()
            if args.rss_cmd == "add":
                feeds = await settings.save_feeds([*feeds, *args.urls])
            elif args.rss_cmd == "remove":
                feeds = await settings.save_feeds([f for f in feeds if f not in args.urls])
            return {"feeds": feeds}
        if args.stt_cmd == "set":
            await settings.save_stt(args.base_url, args.api_key, args.model)
        cfg = settings.stt()
        return {"base_url": cfg["base_url"], "model": cfg["model"], "api_key": "…" if cfg["api_key"] else ""}

    return await _with_settings(data, run)


def main(argv: list[str] | None = None) -> int:
    try:
        return _run(argv)
    except datadir.DataDirBusy as exc:  # un autre Mika tient le dossier : refusé, en le disant
        print(f"Refusé : {exc}", file=sys.stderr)
        return 3


def _run(argv: list[str] | None) -> int:
    p = argparse.ArgumentParser(prog="mika", description="Le serveur, sa console, et ce qu'un opérateur "
                                                         "règle sans elle.",
                                epilog=FIRST_STEPS, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", type=Path, default=Path("data/v2"), help="dossier des bases (mind.db, views.db)")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="commande")
    rp = sub.add_parser("replay", help="rejouer sa vie depuis la genèse (--verify : comparer à l'état sauvegardé)")
    rp.add_argument("--verify", action="store_true", help="comparer le rejeu complet à instantané + queue")
    rb = sub.add_parser("rebuild", help="reconstruire des tranches depuis le journal (diagnostic, serveur arrêté)")
    rb.add_argument("owners", nargs="+", help="les facultés à reconstruire (memory, social…)")
    fg = sub.add_parser("forget", help="oublier quelqu'un (serveur arrêté), comme la console")
    fg.add_argument("subject", help="sa clé ou l'une de ses adresses : elle est oubliée avec toutes ses adresses "
                                    "et les noms qui ne désignent qu'elle")
    sm = sub.add_parser("sim", help="le simulateur ; « sonde » : une semaine de sa vie avec le vrai modèle configuré")
    sm.add_argument("action", choices=["selftest", "run", "sonde"])
    sm.add_argument("--lane", default="quick", choices=["quick"])
    sm.add_argument("--report", type=Path, default=Path("sim-reports"))
    sm.add_argument("--out", type=Path, default=Path("sonde"), help="sonde : où écrire la semaine (vidé d'abord)")
    sm.add_argument("--backend", default="", help="sonde : le fournisseur (défaut : celui qui répond, rôle reply)")
    sm.add_argument("--semaine", default="1", choices=["1", "2"],
                    help="sonde : 1 = Adrien, Chloé, Léo ; 2 = Sam (un deuil, un rappel, ses 30 ans), Inès, un salon")
    sv = sub.add_parser("serve", help="la lancer : le serveur du chat et sa console (http://127.0.0.1:8001/"
                                      "inspecteur/)")
    sv.add_argument("--port", type=int, default=8001, help="le port (défaut : 8001)")
    sv.add_argument("--host", default="127.0.0.1", help="l'adresse d'écoute (défaut : cette machine seulement)")
    sv.add_argument("--reports", type=Path, default=None, help="dossier des rapports de simulation (inspecteur)")
    sv.add_argument("--origin", action="append", default=[], dest="origins",
                    help="une origine admise du frontend (répétable, ex. https://mika.example) ; remplace celles "
                         "du développement")
    sv.add_argument("--cookie-secure", action="store_true", help="cookies « Secure » (servi en HTTPS)")
    sv.add_argument("--behind-proxy", action="store_true",
                    help="derrière un mandataire TLS local : l'adresse du client vient de ses en-têtes, cookies "
                         "« Secure », et les points MCP refusent toute requête relayée")
    bk = sub.add_parser("backup", help="archiver ce qui ne se reconstruit pas (serveur en marche : sans risque)")
    bk.add_argument("dest", type=Path, help="dossier des archives")
    bk.add_argument("--keep", type=int, default=0, help="n'en garder que les N plus récentes (0 : toutes)")
    vf = sub.add_parser("verify", help="vérifier une archive (sommes, rejeu, empreinte) sans rien restaurer")
    vf.add_argument("archive", type=Path)
    rt_ = sub.add_parser("restore", help="restaurer une archive dans --data (serveur arrêté)")
    rt_.add_argument("archive", type=Path)
    rt_.add_argument("--force", action="store_true", help="remplacer un dossier non vide (mis de côté, pas effacé)")
    lm = sub.add_parser("llm", help="fournisseurs de modèles et rôles")
    lsub = lm.add_subparsers(dest="llm_cmd", required=True)
    lsub.add_parser("show")
    lb = lsub.add_parser("backend", help="déclarer ou modifier un fournisseur")
    lb.add_argument("name")
    lb.add_argument("--kind", required=True, choices=["claude", "claude_code", "openai", "ollama", "ollama_cloud"])
    lb.add_argument("--model", required=True)
    lb.add_argument("--api-key", default=None, help="laissé vide : la clé actuelle est gardée")
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
    lb.add_argument("--fallback", default=None, help="le fournisseur qui prend le relais en cas d'échec")
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
    lc = lsub.add_parser("context", help="taille du contexte (jetons)")
    lc.add_argument("tokens", type=int)
    ac = sub.add_parser("account", help="créer un compte (serveur arrêté)")
    ac.add_argument("username")
    ac.add_argument("password", nargs="?", default=None,
                    help="laissé vide : demandé sans écho (il ne reste ni dans l'historique du shell, ni dans ps)")
    ac.add_argument("--operator", action="store_true", help="ouvre la console")
    ac.add_argument("--full-name", default="")
    tk = sub.add_parser("token", help="les jetons d'un client natif (un moteur de jeu sur /ws/world)")
    tksub = tk.add_subparsers(dest="token_cmd", required=True)
    tkc = tksub.add_parser("create", help="un jeton neuf pour un compte, montré une seule fois")
    tkc.add_argument("username")
    tkc.add_argument("--label", default="", help="à quoi il sert (« Unity, PC du salon »)")
    tkc.add_argument("--client", choices=("screen", "mobile"), default="screen",
                     help="screen : un écran ou un moteur ; mobile : l'application du téléphone (une messagerie)")
    tkl = tksub.add_parser("list", help="les jetons, jamais leur secret")
    tkl.add_argument("username", nargs="?", default=None)
    tkr = tksub.add_parser("revoke", help="révoquer un jeton : il ne vaut plus rien, ses connexions se ferment")
    tkr.add_argument("id", type=int)
    idp = sub.add_parser("identity", help="relier une adresse à une personne (serveur arrêté)")
    isub = idp.add_subparsers(dest="id_cmd", required=True)
    il = isub.add_parser("link")
    il.add_argument("handle")
    il.add_argument("person")
    iu = isub.add_parser("unlink")
    iu.add_argument("handle")
    so = sub.add_parser("social", help="ce qu'un opérateur sait des liens (serveur arrêté)")
    ssub = so.add_subparsers(dest="social_cmd", required=True)
    sc = ssub.add_parser("closeness")
    sc.add_argument("person")
    sc.add_argument("level", choices=["stranger", "acquaintance", "friend", "close", "auto"])
    ml = sub.add_parser("mail", help="sa boîte aux lettres (IMAP pour lire, SMTP pour envoyer)")
    msub = ml.add_subparsers(dest="mail_cmd", required=True)
    msub.add_parser("show")
    ms = msub.add_parser("set", help="crée ou modifie un compte")
    ms.add_argument("--compte", default=LEGACY_ACCOUNT, help="le nom court du compte (défaut : principal)")
    ms.add_argument("--address")
    ms.add_argument("--imap-host")
    ms.add_argument("--imap-port", type=int)
    ms.add_argument("--imap-ssl", choices=["oui", "non"])
    ms.add_argument("--user")
    ms.add_argument("--password")
    ms.add_argument("--smtp-host")
    ms.add_argument("--smtp-port", type=int)
    ms.add_argument("--smtp-security", choices=["ssl", "starttls", "none"])
    ms.add_argument("--since-days", type=int)
    ms.add_argument("--dossiers", nargs="+", help="les dossiers relevés (défaut : INBOX)")
    ms.add_argument("--voix", choices=["elle", "assistante", "proprietaire"])
    ms.add_argument("--nom", help="ton nom (pour écrire en assistante ou à ta place)")
    mr = msub.add_parser("remove", help="retire un compte")
    mr.add_argument("--compte", required=True)
    rs = sub.add_parser("rss", help="les flux qu'elle suit")
    rsub = rs.add_subparsers(dest="rss_cmd", required=True)
    rsub.add_parser("list")
    for name in ("add", "remove"):
        r = rsub.add_parser(name)
        r.add_argument("urls", nargs="+")
    st = sub.add_parser("stt", help="la transcription des messages vocaux (/audio/transcriptions)")
    stsub = st.add_subparsers(dest="stt_cmd", required=True)
    stsub.add_parser("show")
    sts = stsub.add_parser("set")
    sts.add_argument("base_url")
    sts.add_argument("api_key")
    sts.add_argument("--model", default="whisper-1")
    mc = sub.add_parser("mcp", help="la lire depuis ton Claude Code (point /mcp/console, lecture seule)")
    mcsub = mc.add_subparsers(dest="mcp_cmd", required=True)
    mcsub.add_parser("token", help="un jeton neuf (l'ancien ne vaut plus), montré une fois")
    mcsub.add_parser("serveurs", help="les serveurs MCP branchés (ADR 0064) et leurs réglages, sans secret")
    mce = mcsub.add_parser("essai", help="joindre un serveur MCP branché et lister ses outils (rien n'est approuvé)")
    mce.add_argument("serveur")
    se = sub.add_parser("sensors", help="le jeton des appareils (POST /api/perceptions)")
    sesub = se.add_subparsers(dest="sensors_cmd", required=True)
    sesub.add_parser("token", help="un jeton neuf (l'ancien ne vaut plus), montré une fois")
    tm = sub.add_parser("teams", help="l'extension Teams (ADR 0069) : sa clé et l'état")
    tmsub = tm.add_subparsers(dest="teams_cmd", required=True)
    tmsub.add_parser("key", help="une clé neuve pour l'extension (l'ancienne ne vaut plus), montrée une fois")
    tmsub.add_parser("revoke", help="retirer la clé de l'extension (plus rien ne passe)")
    tmsub.add_parser("status", help="l'état de Teams, sans secret")
    wk = sub.add_parser("wakeup", help="les réveils par API (POST /api/wake/<nom>, ADR 0068 ; serveur arrêté)")
    wksub = wk.add_subparsers(dest="wakeup_cmd", required=True)
    wksub.add_parser("list", help="les réveils déclarés et l'état de leur clé, sans secret")
    wkk = wksub.add_parser("key", help="une clé neuve pour un réveil (l'ancienne ne vaut plus), montrée une fois")
    wkk.add_argument("name")
    wkr = wksub.add_parser("revoke", help="retirer la clé d'un réveil (plus aucun appel ne passe)")
    wkr.add_argument("name")
    co = sub.add_parser("console", help="la console d'exploitation")
    csub = co.add_subparsers(dest="console_cmd", required=True)
    cap = csub.add_parser("apercu", help="exporter chaque page (clair et sombre) d'une vie neuve, sans serveur")
    cap.add_argument("--out", type=Path, required=True)
    fo = sub.add_parser("forge", help="ce qu'un opérateur décide de ses apps (serveur arrêté)")
    fsub = fo.add_subparsers(dest="forge_cmd", required=True)
    for name in ("promote", "demote"):
        f = fsub.add_parser(name, help="offrir (ou retirer) ses outils en conversation")
        f.add_argument("app")
    args = p.parse_args(argv)

    if args.cmd == "replay":
        out = asyncio.run(replay_verify(args.data))
        print(json.dumps(out, ensure_ascii=False))
        return 0 if out["identiques"] else 1
    if args.cmd == "rebuild":
        print(json.dumps(asyncio.run(rebuild(args.data, args.owners)), ensure_ascii=False))
        return 0
    if args.cmd == "forget":
        print(json.dumps(asyncio.run(forget(args.data, args.subject)), ensure_ascii=False))
        return 0
    if args.cmd in ("identity", "social", "forge"):
        if args.cmd == "identity":
            out = asyncio.run(identity_command(args.data, args.id_cmd, args.handle,
                                               args.person if args.id_cmd == "link" else None))
        elif args.cmd == "social":
            out = asyncio.run(operate(args.data, "social.proximite", args.person,
                                      {"closeness": args.level, "confirmed": "1"}))
        else:
            action = "forge.promouvoir" if args.forge_cmd == "promote" else "forge.retrograder"
            out = asyncio.run(operate(args.data, action, args.app, {}))
        print(json.dumps(out, ensure_ascii=False))
        return 0 if out["ok"] else 1
    if args.cmd == "sim" and args.action == "run":
        with tempfile.TemporaryDirectory() as tmp:
            results = run_lane(for_simulation(), Path(tmp))
        path = write_report(results, args.report)
        for r in results:
            print(f"{'✔' if r.ok else '✘'} {r.name} (graine {r.seed}, {r.seconds:.1f} s)")
            for c in r.checks:
                if not c.ok:
                    print(f"    ✘ {c.name} : {c.detail}")
        print(f"rapport : {path}")
        return 0 if all(r.ok for r in results) else 1
    if args.cmd == "sim" and args.action == "sonde":
        return _sonde(args.data, args)
    if args.cmd == "sim":
        out = sim_selftest()
        print(json.dumps(out, ensure_ascii=False))
        return 0 if all(out.values()) else 1
    if args.cmd == "console":
        from mika.app import apercu  # noqa: PLC0415 — le client de test n'est chargé que pour l'aperçu

        try:
            pages = apercu.export(args.out)
        except apercu.ExportFailed as exc:
            print(f"Aperçu exporté, sauf : {exc}", file=sys.stderr)
            return 1
        print(f"{len(pages)} pages exportées : {args.out / 'index.html'}")
        return 0
    if args.cmd == "serve":
        serve(host=args.host, port=args.port, data=args.data, reports=args.reports, origins=args.origins,
              cookie_secure=args.cookie_secure, behind_proxy=args.behind_proxy)
        return 0
    if args.cmd in ("backup", "verify", "restore"):
        try:
            if args.cmd == "backup":
                done = backup.backup(args.data, args.dest, keep=args.keep)
            elif args.cmd == "verify":
                done = backup.verify(args.archive, record=args.data if (args.data / "mind.db").exists() else None)
            else:
                done = backup.restore(args.archive, args.data, force=args.force)
        except backup.BackupError as exc:
            print(json.dumps({"ok": False, "erreur": str(exc)}, ensure_ascii=False))
            return 1
        print(json.dumps({"ok": True, "archive": str(done.archive), "tête": done.head, "empreinte": done.state,
                          "fichiers": done.files, "octets": done.size, "remarques": list(done.warnings)},
                         ensure_ascii=False))
        return 0
    if args.cmd == "llm":
        out = asyncio.run(llm_command(args.data, args))
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if not out["problems"] else 1
    if args.cmd == "images":
        out = asyncio.run(images_command(args.data, args))
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if out.get("ok") and not out.get("problems") else 1
    if args.cmd == "claude-code":
        if args.cc_cmd == "login":
            return claude_code_login(args.data, args.name)
        out = asyncio.run(claude_code_check(args.data, args.name))
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if out["ok"] else 1
    if args.cmd == "account":
        if args.password is None:
            args.password = ask_password()
            if args.password is None:
                print(json.dumps({"ok": False, "error": "Les deux mots de passe ne sont pas les mêmes."},
                                 ensure_ascii=False))
                return 1
        out = asyncio.run(account_command(args.data, args))
        print(json.dumps(out, ensure_ascii=False))
        return 0 if out["ok"] else 1
    if args.cmd == "token":
        out = asyncio.run(token_command(args.data, args))
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if out["ok"] else 1
    if args.cmd == "mcp" and args.mcp_cmd in ("serveurs", "essai"):
        out = asyncio.run(_with_settings(args.data, lambda settings, _store: mcp_command(settings, args)))
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if out.get("ok", True) else 1
    if args.cmd == "mcp":
        async def mcp_token(settings: Settings, store) -> dict[str, object]:  # type: ignore[no-untyped-def]
            token = await settings.new_console_mcp_token()
            return {"token": token, "usage": "claude mcp add --transport http mika http://127.0.0.1:8001/mcp/console "
                                              f"--header \"Authorization: Bearer {token}\""}

        print(json.dumps(asyncio.run(_with_settings(args.data, mcp_token)), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "sensors":
        async def token(settings: Settings, store) -> dict[str, object]:  # type: ignore[no-untyped-def]
            return {"token": await settings.new_sensors_token(),
                    "usage": "Authorization: Bearer <jeton> sur POST /api/perceptions"}

        print(json.dumps(asyncio.run(_with_settings(args.data, token)), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "teams":
        out = asyncio.run(_with_settings(args.data, lambda settings, _store: teams_command(settings, args)))
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if out.get("ok", True) else 1
    if args.cmd == "wakeup":
        out = asyncio.run(_with_settings(args.data, lambda settings, _store: wakeup_command(settings, args)))
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if out.get("ok", True) else 1
    if args.cmd in ("mail", "rss", "stt"):
        print(json.dumps(asyncio.run(world_command(args.data, args)), ensure_ascii=False, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
