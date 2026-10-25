"""Les deux portes (ADR 0134) : ce que le canal par où ça arrive laisse passer au plus, puis ce que la ressource
accorde — la plus stricte gagne, sous le plafond de qui est en face.

``tool_allowance`` : ce qu'elle fait d'un outil (un service, une app, une de ses familles) et ce qu'elle en garde ;
``project_allowance`` : le voir, le piloter, ses fichiers, ses apps. Chaque réponse dit les lignes qui ont décidé
(``why``). Les tableaux réglés viennent du registre (``rights_of`` : ``Registry.access_tables``, donné par
l'application) ; sans eux, les minimums vitaux. Une famille de ses propres outils naît de ce que ses outils déclarent
(``vital_family`` : ``owner_only``).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from mika.kernel.rights import Rights
from mika.vocab.access import (
    ALONE,
    EVERYONE,
    INTERNAL,
    KEEP_RANK,
    NO,
    OWNER,
    POLICY_RANK,
    ROOM,
    STEER_NO,
    STEER_RANK,
    Ceiling,
    ToolRule,
    Verdict,
    at_work_with,
    ceiling,
    situation,
    tighten,
    verdict,
    why_words,
)
from mika.vocab.canals import CanalRule, Canals, canal_verdict


def rights_of(env: Any) -> Rights:
    """Les tableaux réglés, par ce qui les donne (le registre, ``access_tables``) ; sans rien, les minimums vitaux."""
    give = getattr(env, "access_tables", None)
    got = give() if callable(give) else None
    return got if isinstance(got, Rights) else Rights()


def closeness_of(env: Any, frame: Any) -> Callable[[str], bool] | None:
    """Qui est proche d'elle, devant ce qu'elle vit (``Registry.closeness``) ; rien sans vie à lire."""
    ask = getattr(env, "closeness", None)
    return ask(frame) if callable(ask) and frame is not None else None


# ── ses propres outils : une famille par lot ───────────────────────────────


def vital_family(specs: Iterable[Any]) -> tuple[tuple[ToolRule, ...], ToolRule]:
    """Le minimum vital d'une famille d'outils, tel que ses outils le déclarent : à toi, et elle seule, tout ; à
    tout le monde, ceux que rien ne réserve (``owner_only``). Ce qui vient du dehors (``outside``) se garde comme un
    savoir : rien de plus serré qu'avant."""
    named = list(specs)
    reserved = [s.name for s in named if getattr(s, "owner_only", False)]
    opened = [s.name for s in named if not getattr(s, "owner_only", False)]
    lines: list[ToolRule] = [ToolRule(who=(OWNER,), read=ALONE, act=ALONE, keep="public"),
                             ToolRule(canal=(INTERNAL,), read=ALONE, act=ALONE, keep="public")]
    if opened:
        lines.append(ToolRule(who=(EVERYONE,), read=ALONE, act=ALONE, keep="public",
                              tools=tuple(sorted(opened)) if reserved else ()))
    return tuple(lines), ToolRule()


def family_table(rights: Rights, bundle: str, specs: Iterable[Any]) -> tuple[tuple[ToolRule, ...], ToolRule]:
    """Le tableau d'une famille : celui qu'un opérateur a réglé, sinon son minimum vital."""
    table = rights.families.get(bundle)
    if table is not None:
        return tuple(table.lines), table.default
    return vital_family(specs)


# ── les deux portes ─────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Allowance:
    """Ce qu'elle fait d'un outil ici, et ce qu'elle en garde, une fois les deux portes passées ; ``why`` : les
    lignes qui ont décidé, en mots ; ``capped`` : le plafond a serré."""

    level: str
    keep: str
    why: str
    resource: Verdict[Any]
    canal: Verdict[CanalRule]
    canal_key: str
    ceiling: Ceiling
    capped: bool = False


def _why(canal_key: str, got: Verdict[Any], through: Verdict[Any], cap: Ceiling, capped: bool) -> str:
    said = f"{why_words(got.index)} ; canal « {canal_key} » : {why_words(through.index)}"
    return f"{said} ; plafond : {cap.why}" if capped and cap.why else said


def tool_allowance(lines: Iterable[Any], default: Any, audience: Any, kind: str, acts: bool, rights: Rights,
                   concerns: Callable[[Any], bool] | None = None, *,
                   close: Callable[[str], bool] | None = None, outside: bool = False) -> Allowance | None:
    """Ce qu'elle fait d'un outil qui lit ou qui agit (``acts``) devant cette audience, à ce moment, et ce qu'elle
    en garde : la ligne de la ressource qui le concerne, serrée par la ligne du canal et par le plafond ; ``None``
    hors de toute situation. Ce qui vient du dehors (``outside`` : un service, une app) ne se lit pas devant des
    témoins : à plusieurs, rien."""
    cap = ceiling(audience)
    if outside and cap is not None and situation(audience) == ROOM:
        cap = Ceiling(read=NO, act=NO, keep="rien", steer=cap.steer, files=cap.files,
                      why="venu d'ailleurs, devant des témoins")
    through = canal_verdict(rights.canals or Canals(), audience, kind, close=close)
    got = verdict(tuple(lines), default, audience, kind, concerns, close=close)
    if cap is None or through is None or got is None:
        return None
    canal_line, key = through
    mine = got.line.act if acts else got.line.read
    yours = canal_line.line.act if acts else canal_line.line.read
    top = cap.act if acts else cap.read
    level = tighten(tighten(mine, yours, POLICY_RANK), top, POLICY_RANK)
    keep = tighten(tighten(getattr(got.line, "keep", "public"), canal_line.line.keep, KEEP_RANK), cap.keep, KEEP_RANK)
    capped = POLICY_RANK[top] < POLICY_RANK[tighten(mine, yours, POLICY_RANK)]
    return Allowance(level, keep, _why(key, got, canal_line, cap, capped), got, canal_line, key, cap, capped)


@dataclass(frozen=True, slots=True)
class ProjectAllowance:
    """Ce qu'elle laisse d'un projet à qui est en face : le voir, le piloter, ses fichiers, ce qu'elle fait d'un
    outil de ses apps qui lit et qui agit ; ``why`` : les lignes qui ont décidé."""

    see: bool
    steer: str
    files: bool
    read: str
    act: str
    why: str
    resource: Verdict[Any]
    canal: Verdict[CanalRule]
    canal_key: str
    ceiling: Ceiling

    @property
    def reads(self) -> bool:
        """Elle peut lui en dire le détail : le voir, et le piloter au moins en lecture seule."""
        return self.see and self.steer != STEER_NO


def project_allowance(lines: Iterable[Any], default: Any, audience: Any, kind: str, rights: Rights,
                      concerns: Callable[[Any], bool] | None = None, *,
                      close: Callable[[str], bool] | None = None) -> ProjectAllowance | None:
    """Ce qu'un projet laisse à qui est en face, à ce moment : sa ligne, serrée par celle du canal et par le
    plafond (jamais piloter au-delà de la lecture seule, ni un fichier, dans un salon ou avec une inconnue)."""
    cap = ceiling(audience)
    through = canal_verdict(rights.canals or Canals(), audience, kind, close=close)
    got = verdict(tuple(lines), default, audience, kind, concerns, close=close)
    if cap is None or through is None or got is None:
        return None
    canal_line, key = through
    line, via = got.line, canal_line.line
    see = bool(line.see)
    steer = tighten(tighten(line.steer, via.steer, STEER_RANK), cap.steer, STEER_RANK) if see else STEER_NO
    files = bool(line.files) and via.files and cap.files and see
    read = tighten(tighten(line.read, via.read, POLICY_RANK), cap.read, POLICY_RANK)
    act = tighten(tighten(line.act, via.act, POLICY_RANK), cap.act, POLICY_RANK)
    capped = see and STEER_RANK[cap.steer] < STEER_RANK[tighten(line.steer, via.steer, STEER_RANK)]
    return ProjectAllowance(see, steer, files, read, act, _why(key, got, canal_line, cap, capped), got, canal_line,
                            key, cap)


def here_allowed(frame: Any, bundle: str, tool: str = "", acts: bool = False,
                 tasks: Callable[[str], bool] | None = None, outside: bool = False) -> bool:
    """Ce qu'un gestionnaire revérifie à l'exécution, par la même règle que la porte (ADR 0134) : elle seule, avec ce
    lot (``at_work_with``) ; devant quelqu'un, le tableau de la famille de l'outil, serré par le canal et le
    plafond."""
    work = at_work_with(frame, bundle, tasks)
    if work is not None:
        return work
    registry = frame.env
    kind = frame.episode.kind if frame.episode is not None else ""
    specs = [s for s in getattr(registry, "tools", {}).values() if getattr(s, "bundle", "") == bundle]
    rights = rights_of(registry)
    lines, default = family_table(rights, bundle, specs)
    concerns = (lambda r: r.concerns(tool)) if tool else None
    got = tool_allowance(lines, default, frame.audience, kind, acts, rights, concerns,
                         close=closeness_of(registry, frame), outside=outside)
    return got is not None and got.level != NO


def grants_of(allowance: Allowance | None) -> tuple[str, str]:
    """(niveau, garde) d'une réponse, ou fermé."""
    return (allowance.level, allowance.keep) if allowance is not None else (NO, "rien")


def names_of(rights: Rights) -> Mapping[str, Any]:
    """Les tableaux de familles réglés, par lot (pour la console)."""
    return rights.families
