"""Ce qui se branche sans être à un domaine : ``stt`` (la transcription), ``sensors`` ; puis la commande de chaque
domaine qui a la sienne (``Domain.cli``, ADR 0310 : ``mail``, ``teams``, ``agenda``…)."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from mika.app.cli.common import _with_settings
from mika.app.domains import DOMAINS, part
from mika.app.settings import Settings


async def outside_command(data: Path, args: argparse.Namespace) -> dict[str, object]:
    """La transcription des messages vocaux."""

    async def run(settings: Settings, store) -> dict[str, object]:  # type: ignore[no-untyped-def]
        if args.stt_cmd == "set":
            await settings.save_stt(args.base_url, args.api_key, args.model)
        cfg = settings.stt()
        return {"base_url": cfg["base_url"], "model": cfg["model"], "api_key": "…" if cfg["api_key"] else ""}

    return await _with_settings(data, run)


def _run_outside(args: argparse.Namespace) -> int:
    print(json.dumps(asyncio.run(outside_command(args.data, args)), ensure_ascii=False, indent=2))
    return 0


def _run_sensors(args: argparse.Namespace) -> int:
    async def token(settings: Settings, store) -> dict[str, object]:  # type: ignore[no-untyped-def]
        return {"token": await settings.new_sensors_token(),
                "usage": "Authorization: Bearer <jeton> sur POST /api/perceptions"}

    print(json.dumps(asyncio.run(_with_settings(args.data, token)), ensure_ascii=False, indent=2))
    return 0


def add_plugins(sub) -> None:  # type: ignore[no-untyped-def]
    st = sub.add_parser("stt", help="la transcription des messages vocaux (/audio/transcriptions)")
    stsub = st.add_subparsers(dest="stt_cmd", required=True)
    stsub.add_parser("show")
    sts = stsub.add_parser("set")
    sts.add_argument("base_url")
    sts.add_argument("api_key")
    sts.add_argument("--model", default="whisper-1")
    se = sub.add_parser("sensors", help="le jeton des appareils (POST /api/perceptions)")
    sesub = se.add_subparsers(dest="sensors_cmd", required=True)
    sesub.add_parser("token", help="un jeton neuf (l'ancien ne vaut plus), montré une fois")
    st.set_defaults(run=_run_outside)
    se.set_defaults(run=_run_sensors)
    # puis la commande de chaque domaine qui a la sienne (``Domain.cli``, ADR 0310)
    for domain in DOMAINS:
        if domain.cli is not None:
            part(domain.cli, "add")(sub)
