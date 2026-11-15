"""Une nouvelle version d'une app qui attend un accord (ADR 0104, 0105).

Une app qui a des secrets sans avoir jamais été validée voit sa nouvelle version mise de côté et proposée
(``install_draft``, que ``forge_write`` et ``forge_edit`` proposent) : l'aperçu montre exactement ce qui changerait,
le manifeste et le code en diff (``install_preview``), et la capacité ``forge.install`` l'installe après l'accord d'un
opérateur. Les réducteurs suivent les propositions en route (``ForgeState.installs``) : refusée, l'app le sait, et la
version mise de côté ne traîne plus dans l'hôte (``_install_refused``) ; installée, elle entre dans sa vie, validée
(``_installed``, qui passe aussi à ``calls.came_back`` ce que rend un appel d'outil fait après accord).

Ces contributions s'inscrivent sur ``FORGE`` à l'import du module, que le paquet fait en fin de fichier. Il importe
``calls.py`` à sa fin, après ses décorateurs : ses réducteurs, sa capacité et ses effets restent inscrits avant ceux
des appels sur accord, comme dans l'ancien fichier unique.
"""

from __future__ import annotations

import difflib
import hashlib
import json
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from mika.contracts import runtime as rt
from mika.kernel.events import Content
from mika.kernel.operate import Preview
from mika.kernel.state import FrozenDict
from mika.plugins.forge import BUNDLE, FORGE, App, ForgeState, written_draft
from mika.ports.forge import ForgeRefused

# ── Une nouvelle version qui attend un accord ─────────────────────────────

INSTALL = f"{BUNDLE}.install"


def install_draft(app: str, print_: str, current: App | None, why: str, *, decider: str = "") -> Any:
    """La proposition d'installer une version mise de côté : l'accord d'un opérateur, qui voit ce qui change — et,
    quand on sait à qui la montrer, une carte dans le chat de sa propriétaire (``decider``, ADR 0104)."""
    title = current.title if current is not None else app
    summary = f"Installer une nouvelle version de l'app « {title} » ({app}) — {why}."
    args: dict[str, Any] = {"app": app, "version": print_, "from": current.fingerprint if current else ""}
    if decider:
        args[rt.DECIDER] = decider
    return rt.EFFECT_PROPOSED.draft(capability=INSTALL, owner=FORGE.name, approval=True, context=f"forge:{app}",
                                    args_json=json.dumps(args), summary=Content.of(summary, level=0))


def _lines(text: str) -> list[str]:
    return text.splitlines(keepends=False)


def install_preview(args: Mapping[str, Any], ports: Mapping[str, Any]) -> Preview | None:
    """Exactement ce qui changerait : le manifeste en diff, le code en diff. Son condensé épingle la version mise de
    côté **et** celle qu'elle remplace."""
    port = ports.get("forge")
    app, print_ = str(args.get("app") or ""), str(args.get("version") or "")
    if port is None:
        return None
    staged = port.staged(app, print_)
    if staged is None:
        return Preview("(cette version mise de côté n'existe plus)", "", blocked="la version proposée a disparu")
    try:
        current = port.source(app) or ("", "")
    except ForgeRefused:
        current = ("", "")
    info = port.info(app)
    if str(args.get("from") or "") != (info.fingerprint if info is not None else ""):
        return Preview("(l'app a changé depuis cette proposition)", "",
                       blocked="l'app a changé depuis : cette proposition ne vaut plus")
    # son réseau est libre (ADR 0105) : ce qui compte, c'est le code — tout Internet lui est ouvert
    head = [f"App : {app}"]
    head.append("Si tu approuves, tu lui fais confiance : cette version lit ses réglages secrets, et les suivantes "
                "s'installeront sans te redemander (« Ne plus lui faire confiance », sur sa fiche, l'arrête).")
    manifest_diff = "".join(f"{line}\n" for line in difflib.unified_diff(
        _lines(current[0]), _lines(staged.manifest), "manifest.yaml (en place)", "manifest.yaml (proposé)",
        lineterm=""))
    code_diff = "".join(f"{line}\n" for line in difflib.unified_diff(
        _lines(current[1]), _lines(staged.code), "main.py (en place)", "main.py (proposé)", lineterm=""))
    text = "\n".join(head) + "\n\n" + (manifest_diff or "(manifeste inchangé)\n") + "\n" + \
        (code_diff or "(code inchangé)\n")
    return Preview(text[:200_000], hashlib.sha256(f"{print_}:{args.get('from')}".encode()).hexdigest()[:24])


@FORGE.capability("install", description="Installer une version d'une app mise de côté (après l'accord d'un "
                  "opérateur).", preview=install_preview)
async def install(args: Mapping[str, Any], context: str, ports: Mapping[str, Any]) -> tuple[bool, str]:
    port = ports.get("forge")
    app, print_ = str(args.get("app") or ""), str(args.get("version") or "")
    if port is None:
        return False, "la Forge n'est pas là"
    info = port.info(app)
    if str(args.get("from") or "") != (info.fingerprint if info is not None else ""):
        return False, "refusé : l'app a changé depuis l'accord"
    try:
        version = await port.install(app, print_)
    except ForgeRefused as exc:
        return False, f"refusé : {exc}"
    return True, f"version {version} installée"


@FORGE.reducer(rt.EFFECT_PROPOSED)
def _install_proposed(s: ForgeState, e, cx) -> ForgeState:
    if e.data.owner != FORGE.name or e.data.capability != INSTALL:
        return s
    app = str(rt.proposal_args(e.data.args_json).get("app") or "")
    if not app:  # une charge illisible, ou sans app : rien à attendre
        return s
    installs = dict(s.installs)
    installs[e.seq] = app
    return replace(s, installs=FrozenDict(dict(sorted(installs.items())[-32:])))


@FORGE.reducer(rt.EFFECT_RESOLVED)
def _install_resolved(s: ForgeState, e, cx) -> ForgeState:
    """Une version proposée est tranchée : elle n'attend plus ; refusée, l'app le sait (ADR 0104 — un refus ne lui
    revenait pas, et la proposition restait dans la carte pour toujours)."""
    app = s.installs.get(e.data.proposal)
    if e.data.owner != FORGE.name or e.data.capability != INSTALL or app is None:
        return s
    if e.data.approved:
        # elle attend son exécution : ``_installed`` relit d'ici quelle app entre dans sa vie, puis la version
        # écrite (validée) la retire — l'oublier ici la faisait installer sur le disque sans jamais entrer dans sa
        # vie comme validée (ADR 0105)
        return s
    s = replace(s, installs=s.installs.delete(e.data.proposal))
    current = s.apps.get(app)
    if current is None:
        return s
    return replace(s, apps=s.apps.set(app, replace(current, install_refused=True)))


@FORGE.reducer(rt.EFFECT_EXECUTED)
def _install_failed(s: ForgeState, e, cx) -> ForgeState:
    """Une installation approuvée qui n'a pas pu se faire n'attend plus rien."""
    if e.data.ok or e.data.proposal not in s.installs:
        return s
    return replace(s, installs=s.installs.delete(e.data.proposal))


@FORGE.effect(rt.EFFECT_RESOLVED)
async def _install_refused(ev: Any, ports: Mapping[str, Any]) -> list[Any] | None:
    """Une version mise de côté que l'opérateur a refusée ne traîne plus dans l'hôte (ADR 0104)."""
    port = ports.get("forge")
    d = ev.data
    if port is None or d.owner != FORGE.name or d.capability != INSTALL or d.approved:
        return None
    args = rt.proposal_args(d.args_json)
    if args.get("app") and args.get("version"):
        port.discard(str(args["app"]), str(args["version"]))
    return None


@FORGE.effect(rt.EFFECT_EXECUTED)
async def _installed(ev: Any, ports: Mapping[str, Any]) -> list[Any] | None:
    """Une version installée après accord entre dans sa vie, validée : un opérateur l'a lue. Un appel d'outil fait
    après accord revient comme un contenu (``calls.came_back``)."""
    frame_of, port = ports.get("frame"), ports.get("forge")
    if frame_of is None or port is None:
        return None
    state = frame_of().state("forge")
    if ev.data.proposal in state.calls:
        return calls.came_back(ev, state, frame_of(), port)
    if not ev.data.ok:
        return None
    app = state.installs.get(ev.data.proposal)
    info = port.info(app) if app else None
    current = state.apps.get(app) if app else None
    return [written_draft(info, vouched=True, project=current.project if current is not None else 0)] \
        if info is not None else None


# ses appels sur accord, après l'installation : ``_installed`` leur passe ce qui revient d'un appel
from mika.plugins.forge import calls  # noqa: E402
