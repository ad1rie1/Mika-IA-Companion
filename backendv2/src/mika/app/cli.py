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
- ``account <nom> <mot de passe> [--operator]`` : un compte ;
- ``telegram show|token|allow|disallow|owner|open|close`` : le robot Telegram
  (jeton chiffré ; fermé par défaut : liste blanche et propriétaires) ;
- ``serve --origin URL --cookie-secure --behind-proxy`` : derrière un mandataire TLS ;
- ``console apercu --out DOSSIER`` : chaque page de la console, exportée ;
- ``identity link|unlink`` et ``social closeness`` : ce qu'un opérateur sait
  mieux qu'elle (serveur arrêté : une seule écriture à la fois dans ``mind.db``).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from mika.adapters.llm.claude_code import FORBIDDEN, ClaudeCodeBackend, ClaudeCodeError, runtime_dir
from mika.adapters.llm.config import BackendSpec, LLMConfig
from mika.adapters.mail import LEGACY_ACCOUNT
from mika.adapters.mcp.relay import Relay
from mika.adapters.store_sqlite import SqliteStore
from mika.adapters.system import RandomIdGen, RealClock
from mika.adapters.vectors import SentenceEmbedder, SqliteVectorIndex
from mika.adapters.web.accounts import Accounts, password_problems
from mika.app import backup, composition, datadir
from mika.app.composition import faculties, for_simulation
from mika.app.server import serve
from mika.app.settings import SecretBox, Settings
from mika.contracts import identity as identity_c
from mika.contracts import social as social_c
from mika.kernel.codec import digest
from mika.kernel.registry import Registry
from mika.plugins.forge import SWITCHED
from mika.ports.llm import LLMRequest, Message
from mika.runtime.bootstrap import Kernel
from mika.runtime.mind import Mind
from mika.runtime.state import RUNTIME
from mika.sim.catalog import run_lane
from mika.sim.report import write as write_report
from mika.sim.selftest import run as sim_selftest


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
    await mind.close()
    return report


async def forget(data: Path, subject: str) -> dict[str, object]:
    """L'oubli, comme la console le fait : par ``Kernel.forget`` — contenus et
    projections, traces d'épisode, et tout port qui garde une trace dérivée
    (l'index des vecteurs). Rien ne démarre : aucun processus, aucun modèle."""
    datadir.hold(data)  # serveur arrêté : une seule écriture à la fois
    store = SqliteStore(data / "mind.db", data / "views.db", threaded=False)
    vectors = SqliteVectorIndex(store, SentenceEmbedder())  # le modèle ne se charge qu'à un plongement : jamais ici
    kernel = Kernel(composition.deps(store=store, clock=RealClock(), ids=RandomIdGen(), ports={"vectors": vectors}))
    try:
        await kernel.mind.boot(append_boot=False)
        await vectors.open()
        await kernel.traces.open()
        report = await kernel.forget(subject)
    finally:
        await kernel.mind.close()
        datadir.release(data)
    return {"sujet": subject, "contenus_effacés": report.get("contents", 0), "traces_effacées": report.get("traces", 0),
            "vecteurs_effacés": report.get("vectors", 0)}


async def _with_settings(data: Path, fn):  # type: ignore[no-untyped-def]
    store = SqliteStore(data / "mind.db", data / "views.db", threaded=False)
    await store.open()
    try:
        settings = Settings(store, SecretBox.for_data(data))
        await settings.open()
        return await fn(settings, store)
    finally:
        await store.close()


async def llm_command(data: Path, args: argparse.Namespace) -> dict[str, object]:
    async def run(settings: Settings, store) -> dict[str, object]:  # type: ignore[no-untyped-def]
        cfg = settings.llm()
        backends = dict(cfg.backends)
        routes = dict(cfg.routes)
        context = cfg.context_tokens
        if args.llm_cmd == "backend":
            previous = backends.get(args.name)
            key = args.api_key if args.api_key is not None else (previous.api_key if previous else "")

            def kept(value, attr, default):  # type: ignore[no-untyped-def]
                return value if value is not None else (getattr(previous, attr) if previous else default)

            backends[args.name] = BackendSpec(
                kind=args.kind, model=args.model, api_key=key, base_url=args.base_url or "", host=args.host or "",
                slots=args.slots, temperature=args.temperature, think=args.think,
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
        cfg = LLMConfig(backends=backends, routes=routes, context_tokens=context)
        if args.llm_cmd != "show":
            await settings.save_llm(cfg)
        return {"backends": {n: b.redacted() for n, b in cfg.backends.items()}, "routes": cfg.routes,
                "context_tokens": cfg.context_tokens, "problems": cfg.problems()}

    return await _with_settings(data, run)


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


async def telegram_command(data: Path, args: argparse.Namespace) -> dict[str, object]:
    async def run(settings: Settings, store) -> dict[str, object]:  # type: ignore[no-untyped-def]
        cfg = settings.telegram()
        if args.tg_cmd == "token":
            await settings.save_telegram(token=args.token)
        elif args.tg_cmd == "allow":
            await settings.save_telegram(allowed_chats=[*cfg["allowed_chats"], *args.chats])
        elif args.tg_cmd == "disallow":
            await settings.save_telegram(allowed_chats=[c for c in cfg["allowed_chats"] if c not in args.chats])
        elif args.tg_cmd == "owner":
            await settings.save_telegram(owners=[*cfg["owners"], *args.users])
        elif args.tg_cmd in ("open", "close"):
            await settings.save_telegram(open_to_all=args.tg_cmd == "open")
        cfg = settings.telegram()
        return {"token": "…" + cfg["token"][-4:] if cfg["token"] else "", "allowed_chats": cfg["allowed_chats"],
                "owners": cfg["owners"], "open": cfg["open"]}

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


async def operator_event(data: Path, draft, emitter: str) -> dict[str, object]:  # type: ignore[no-untyped-def]
    from mika.kernel.events import Origin  # noqa: PLC0415

    mind = _mind(data)
    await mind.boot(append_boot=False)
    try:
        commit = await mind.append([draft], emitter=emitter, correlation="opérateur", origin=Origin.EXTERNAL)
    finally:
        await mind.close()
    return {"ok": True, "seq": commit.seqs[-1] if commit.seqs else None}


def main(argv: list[str] | None = None) -> int:
    try:
        return _run(argv)
    except datadir.DataDirBusy as exc:  # un autre Mika tient le dossier : refusé, en le disant
        print(f"Refusé : {exc}", file=sys.stderr)
        return 3


def _run(argv: list[str] | None) -> int:
    p = argparse.ArgumentParser(prog="mika")
    p.add_argument("--data", type=Path, default=Path("data/v2"), help="dossier des bases (mind.db, views.db)")
    sub = p.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("replay")
    rp.add_argument("--verify", action="store_true")
    rb = sub.add_parser("rebuild")
    rb.add_argument("owners", nargs="+")
    fg = sub.add_parser("forget")
    fg.add_argument("subject")
    sm = sub.add_parser("sim")
    sm.add_argument("action", choices=["selftest", "run"])
    sm.add_argument("--lane", default="quick", choices=["quick"])
    sm.add_argument("--report", type=Path, default=Path("sim-reports"))
    sv = sub.add_parser("serve")
    sv.add_argument("--port", type=int, default=8001)
    sv.add_argument("--host", default="127.0.0.1")
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
    lb.add_argument("--base-url", default="")
    lb.add_argument("--host", default="")
    lb.add_argument("--slots", type=int, default=0)
    lb.add_argument("--temperature", type=float, default=None)
    lb.add_argument("--think", action="store_true")
    lb.add_argument("--auth", choices=["abonnement", "cle_api"], default=None,
                    help="claude_code : le login de la CLI (défaut) ou une clé d'API")
    lb.add_argument("--claude-bin", default=None, help="claude_code : la commande claude (vide : PATH)")
    lb.add_argument("--config-dir", default=None, help="claude_code : un dossier de CLI à part (vide : l'habituel)")
    lb.add_argument("--fallback", default=None, help="le fournisseur qui prend le relais en cas d'échec")
    cc = sub.add_parser("claude-code", help="la CLI Claude Code comme moteur (son login, jamais un jeton)")
    ccsub = cc.add_subparsers(dest="cc_cmd", required=True)
    for name, text in (("check", "un appel d'essai : connectée ? quel modèle ? quel usage de l'abonnement ?"),
                       ("login", "se connecter dans le dossier dédié du fournisseur (s'il en a un)")):
        c = ccsub.add_parser(name, help=text)
        c.add_argument("--name", default=None, help="le fournisseur (défaut : le premier de type claude_code)")
    lr = lsub.add_parser("route", help="associer des rôles à un fournisseur")
    lr.add_argument("name")
    lr.add_argument("roles", nargs="+")
    lx = lsub.add_parser("remove")
    lx.add_argument("name")
    lc = lsub.add_parser("context", help="taille du contexte (jetons)")
    lc.add_argument("tokens", type=int)
    ac = sub.add_parser("account", help="créer un compte")
    ac.add_argument("username")
    ac.add_argument("password")
    ac.add_argument("--operator", action="store_true")
    ac.add_argument("--full-name", default="")
    tg = sub.add_parser("telegram", help="le robot Telegram")
    tsub = tg.add_subparsers(dest="tg_cmd", required=True)
    tsub.add_parser("show")
    tt = tsub.add_parser("token")
    tt.add_argument("token")
    ta = tsub.add_parser("allow", help="n'écouter que ces conversations (identifiants de chat)")
    ta.add_argument("chats", nargs="+", type=int)
    td = tsub.add_parser("disallow")
    td.add_argument("chats", nargs="+", type=int)
    to = tsub.add_parser("owner", help="comptes Telegram propriétaires (identifiants d'utilisateur)")
    to.add_argument("users", nargs="+", type=int)
    tsub.add_parser("open", help="ouvrir à tout le monde, liste blanche comprise (sinon : fermé par défaut)")
    tsub.add_parser("close", help="revenir à la liste blanche et aux propriétaires")
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
    ml = sub.add_parser("mail", help="la boîte aux lettres de Mika (IMAP pour lire, SMTP pour envoyer)")
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
    mc = sub.add_parser("mcp", help="lire Mika depuis ton Claude Code (point /mcp/console, lecture seule)")
    mcsub = mc.add_subparsers(dest="mcp_cmd", required=True)
    mcsub.add_parser("token", help="un jeton neuf (l'ancien ne vaut plus), montré une fois")
    se = sub.add_parser("sensors", help="le jeton des appareils (POST /api/perceptions)")
    sesub = se.add_subparsers(dest="sensors_cmd", required=True)
    sesub.add_parser("token", help="un jeton neuf (l'ancien ne vaut plus), montré une fois")
    co = sub.add_parser("console", help="la console d'exploitation")
    csub = co.add_subparsers(dest="console_cmd", required=True)
    cap = csub.add_parser("apercu", help="exporter chaque page (clair et sombre) d'une Mika neuve, sans serveur")
    cap.add_argument("--out", type=Path, required=True)
    fo = sub.add_parser("forge", help="ce qu'un opérateur décide des apps de Mika (serveur arrêté)")
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
    if args.cmd == "sim":
        out = sim_selftest()
        print(json.dumps(out, ensure_ascii=False))
        return 0 if all(out.values()) else 1
    if args.cmd == "console":
        from mika.app.apercu import export  # noqa: PLC0415 — le client de test n'est chargé que pour l'aperçu

        pages = export(args.out)
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
    if args.cmd == "claude-code":
        if args.cc_cmd == "login":
            return claude_code_login(args.data, args.name)
        out = asyncio.run(claude_code_check(args.data, args.name))
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if out["ok"] else 1
    if args.cmd == "account":
        out = asyncio.run(account_command(args.data, args))
        print(json.dumps(out, ensure_ascii=False))
        return 0 if out["ok"] else 1
    if args.cmd == "telegram":
        print(json.dumps(asyncio.run(telegram_command(args.data, args)), ensure_ascii=False))
        return 0
    if args.cmd == "identity":
        person = args.person if args.id_cmd == "link" else None
        draft = identity_c.LINKED.draft(handle=args.handle, person=person, by="operator")
        print(json.dumps(asyncio.run(operator_event(args.data, draft, "identity")), ensure_ascii=False))
        return 0
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
    if args.cmd in ("mail", "rss", "stt"):
        print(json.dumps(asyncio.run(world_command(args.data, args)), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "forge":
        draft = SWITCHED.draft(app=args.app, state=f"{args.forge_cmd}d", reason="opérateur")
        print(json.dumps(asyncio.run(operator_event(args.data, draft, "forge")), ensure_ascii=False))
        return 0
    if args.cmd == "social":
        level = "" if args.level == "auto" else args.level
        draft = social_c.CLOSENESS_SET.draft(person=args.person, closeness=level, by="operator")
        print(json.dumps(asyncio.run(operator_event(args.data, draft, "social")), ensure_ascii=False))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
