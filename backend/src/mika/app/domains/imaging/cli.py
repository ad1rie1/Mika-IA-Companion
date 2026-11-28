"""``mika images`` (ADR 0061, 0317) : les fournisseurs d'images hors ligne — montrer, déclarer, router, retirer, ou
faire un essai avec la configuration enregistrée. Serveur arrêté : une seule écriture à la fois dans ``mind.db``. Sa
place dans ``mika --help``, juste après ``llm``, se dit au cadre (``app/cli/models.py::BESIDE_MODELS``)."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from mika.adapters.imaging.config import ImageBackendSpec, ImagingConfig
from mika.adapters.imaging.config import build_gateway as build_image_gateway
from mika.adapters.system import RealClock
from mika.app.cli.common import with_settings
from mika.app.domains.imaging.settings import ImagingSettings
from mika.app.settings import Settings
from mika.ports.imaging import ASPECTS, QUALITIES, ImageRequest
from mika.ports.imaging import ROLE_LABELS as IMAGE_ROLE_LABELS
from mika.ports.imaging import ROLES as IMAGE_ROLES


async def images_command(data: Path, args: argparse.Namespace) -> dict[str, object]:
    """Les fournisseurs d'images : montrer, déclarer, router, retirer — ou faire un essai avec la
    configuration enregistrée (``essai`` n'écrit rien d'autre que l'image demandée)."""
    async def run(settings: Settings, store) -> dict[str, object]:  # type: ignore[no-untyped-def]
        images = settings.of(ImagingSettings)
        cfg = images.imaging()
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
                cfg = await images.save_imaging(ImagingConfig(backends=backends, routes=routes))
            except ValueError as exc:
                return {"ok": False, "problems": [p.strip() for p in str(exc).split(";") if p.strip()]}
        return {"ok": True, "activée": cfg.enabled, "backends": {n: b.redacted() for n, b in cfg.backends.items()},
                "routes": cfg.routes, "problems": cfg.problems()}

    return await with_settings(data, run)


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


def _run_images(args: argparse.Namespace) -> int:
    out = asyncio.run(images_command(args.data, args))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok") and not out.get("problems") else 1


def add(sub) -> None:  # type: ignore[no-untyped-def]
    """Sa commande et ses sous-commandes, dans l'analyseur de ``mika``."""
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
    im.set_defaults(run=_run_images)
