"""Un mandataire local qui enregistre ce que la CLI Claude Code envoie vraiment au modèle (système, messages, outils).

Il transmet tout à l'API d'Anthropic tel quel (en-têtes compris : la CLI garde son login) et n'écrit que le corps des
requêtes, jamais les en-têtes. Pour voir ce que la CLI ajoute de son cru au prompt de Mika.

    .venv/bin/python tools/banc_conversation/audit/mandataire.py PORT SORTIE.jsonl
    ANTHROPIC_BASE_URL=http://127.0.0.1:PORT claude -p …
"""

from __future__ import annotations

import json
import sys

import aiohttp
from aiohttp import web

UPSTREAM = "https://api.anthropic.com"
OUT = open(sys.argv[2], "a")  # noqa: SIM115


async def forward(request: web.Request) -> web.StreamResponse:
    body = await request.read()
    if request.method == "POST" and body:
        try:
            OUT.write(json.dumps({"chemin": request.path, "corps": json.loads(body)}, ensure_ascii=False) + "\n")
            OUT.flush()
        except ValueError:
            pass
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length")}
    async with aiohttp.ClientSession(auto_decompress=False) as s, s.request(
            request.method, UPSTREAM + request.path_qs, headers=headers, data=body) as up:
        resp = web.StreamResponse(status=up.status, headers={k: v for k, v in up.headers.items()
                                                            if k.lower() not in ("content-length", "transfer-encoding")})
        await resp.prepare(request)
        async for chunk in up.content.iter_any():
            await resp.write(chunk)
        await resp.write_eof()
        return resp


app = web.Application(client_max_size=64 * 1024 * 1024)
app.router.add_route("*", "/{tail:.*}", forward)
web.run_app(app, host="127.0.0.1", port=int(sys.argv[1]), print=None)
