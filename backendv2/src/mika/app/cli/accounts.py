"""Les comptes et ce qu'un opérateur sait mieux qu'elle : ``account``, ``token``, ``identity``, ``social``, ``forge``."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from mika.adapters.web.accounts import Accounts, password_problems
from mika.app.cli.common import CLI_BY, _close, _offline, _with_settings
from mika.app.settings import Settings
from mika.contracts import identity as identity_c
from mika.kernel import forms
from mika.kernel.events import Origin
from mika.runtime import operations
from mika.runtime.bootstrap import Kernel
from mika.vocab.people import is_identifiable


def ask_password(ask: Callable[[str], str] | None = None) -> str | None:
    """Le mot de passe demandé sans écho, deux fois ; ``None`` s'ils diffèrent."""
    ask = ask or getpass.getpass
    first = ask("Mot de passe : ")
    return first if ask("Encore une fois : ") == first else None


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


def _run_account(args: argparse.Namespace) -> int:
    if args.password is None:
        args.password = ask_password()
        if args.password is None:
            print(json.dumps({"ok": False, "error": "Les deux mots de passe ne sont pas les mêmes."},
                             ensure_ascii=False))
            return 1
    out = asyncio.run(account_command(args.data, args))
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out["ok"] else 1


def _run_token(args: argparse.Namespace) -> int:
    out = asyncio.run(token_command(args.data, args))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out["ok"] else 1


def _run_identity(args: argparse.Namespace) -> int:
    out = asyncio.run(identity_command(args.data, args.id_cmd, args.handle,
                                       args.person if args.id_cmd == "link" else None))
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out["ok"] else 1


def _run_social(args: argparse.Namespace) -> int:
    out = asyncio.run(operate(args.data, "social.proximite", args.person,
                              {"closeness": args.level, "confirmed": "1"}))
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out["ok"] else 1


def _run_forge(args: argparse.Namespace) -> int:
    action = "forge.promouvoir" if args.forge_cmd == "promote" else "forge.retrograder"
    out = asyncio.run(operate(args.data, action, args.app, {}))
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out["ok"] else 1


def add_accounts(sub) -> None:  # type: ignore[no-untyped-def]
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
    ac.set_defaults(run=_run_account)
    tk.set_defaults(run=_run_token)
    idp.set_defaults(run=_run_identity)
    so.set_defaults(run=_run_social)


def add_forge(sub) -> None:  # type: ignore[no-untyped-def]
    fo = sub.add_parser("forge", help="ce qu'un opérateur décide de ses apps (serveur arrêté)")
    fsub = fo.add_subparsers(dest="forge_cmd", required=True)
    for name in ("promote", "demote"):
        f = fsub.add_parser(name, help="offrir (ou retirer) ses outils en conversation")
        f.add_argument("app")
    fo.set_defaults(run=_run_forge)
