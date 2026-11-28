"""L'offre d'outils : ce que les deux portes laissent, et comment on le lui présente.

Une seule porte offre ses outils (``offer``, qui passe ``judge`` sur chacun) : le pipeline l'applique à chaque
épisode, la console à des audiences de synthèse, le prêt d'outils à chaque appel, et ce qu'une personne a, écran par
écran, se lit de ``judge`` — jamais une recopie. Elle lit du registre les tableaux réglés et qui est proche d'elle
(``gate_of``, ADR 0134) : le port que l'outil attend (``needs``), sa condition sur qui est en face (``when``), puis,
pour un des siens, les deux portes sous le plafond de qui est en face — le tableau du canal, celui de sa famille
(ADR 0133) —, pour un outil venu d'ailleurs, la condition de sa ressource (``fits``) ; une ressource de l'outil qui
est à qui est en face l'offre aussi (``owns``, ADR 0185). L'offre réglée d'un outil — en main, ou à chercher quand il
lui faut — se lit de même (``deferred``, ADR 0122). Un gestionnaire revérifie par la même règle.

Comment on le lui présente : ses déclarations (``declare``), la liste des lots qu'elle peut aller chercher
(``catalogue``), la règle de ses mains (``acting``). La boucle qui exécute les appels est ``runtime.tools``, qui
n'importe rien d'ici.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from mika.kernel.episode import EpisodePolicy
from mika.kernel.faculty import ToolSpec, schema_of
from mika.kernel.frame import Audience
from mika.ports.llm import ToolDecl
from mika.runtime import boundary
from mika.runtime.boundary import Failed
from mika.vocab.access import NO
from mika.vocab.phrasebook import phrase
from mika.vocab.rights import Rights, closeness_of, family_table, rights_of, tool_allowance

#: l'offre réglée d'un outil (ADR 0122, 0134) : en main (dans son prompt), ou à chercher quand il lui faut — un
#: réglage de l'outil, plus une grille par situation ; un outil qui clôt la boucle (``ends_loop`` : rendre compte
#: d'un pas) ne se règle pas
HAND, ASK = "hand", "ask"
RULES = (HAND, ASK)


def rule_of(spec: ToolSpec, rights: Rights | None) -> str | None:
    """L'offre réglée de cet outil, s'il y en a une qui compte (aucune sur un outil qui clôt la boucle)."""
    return None if rights is None or spec.ends_loop else rights.in_hand.get(spec.name)


def deferred(spec: ToolSpec, core: frozenset[str] | None, rights: Rights | None = None) -> bool:
    """Cet outil offert est-il à la demande ? Pas quand tout est en main (``core`` vide de sens : ``None``) ; sinon
    son offre réglée s'il y en a une, et à défaut son lot ou l'outil lui-même (``in_hand``)."""
    if core is None:
        return False
    rule = rule_of(spec, rights)
    if rule in (HAND, ASK):
        return rule == ASK
    return spec.bundle not in core and not spec.in_hand


def gate_of(registry: Any, frame: Any = None) -> tuple[Rights, Callable[[str], bool] | None]:
    """Ce que la porte lit du registre (ADR 0134) : les tableaux réglés (``access_tables``) et qui est proche
    d'elle, devant ce qu'elle vit (``closeness``)."""
    return rights_of(registry), closeness_of(registry, frame)


def family_of(tools: Mapping[str, ToolSpec], rights: Rights, bundle: str) -> tuple[tuple[Any, ...], Any]:
    """Le tableau d'une famille de ses propres outils : réglé, sinon le minimum vital que ses outils déclarent."""
    return family_table(rights, bundle, [s for s in tools.values() if s.bundle == bundle])


def allowed(tools: Mapping[str, ToolSpec], spec: ToolSpec, audience: Audience, kind: str, rights: Rights,
            close: Callable[[str], bool] | None = None) -> Any:
    """Ce que les deux portes laissent de cet outil de ses familles (``vocab.rights.tool_allowance``) ; ``None`` hors
    de toute situation."""
    lines, default = family_of(tools, rights, spec.bundle)
    return tool_allowance(lines, default, audience, kind, spec.acts, rights, lambda r: r.concerns(spec.name),
                          close=close, outside=spec.outside)


def offer(tools: Mapping[str, ToolSpec], policy: EpisodePolicy, kind: str, audience: Audience,
          only: Any = None, frame: Any = None, rights: Rights | None = None,
          close: Callable[[str], bool] | None = None, ports: Mapping[str, Any] | None = None) -> dict[str, ToolSpec]:
    """Les outils offerts : les lots de la politique — restreints, quand le candidat le dit (``bundles`` :
    « goals,workshop »), à ceux-là seuls. Un lot est offert entier ou pas du tout, moins ce que ses droits ferment
    (ADR 0134) : pour un outil venu d'ailleurs, sa condition (``fits`` : les lignes de son service, de son projet) ;
    pour un des siens, le tableau de sa famille, serré par celui du canal et par le plafond de qui est en face.

    La seule porte : le pipeline l'applique à chaque épisode, la console à des audiences de synthèse (« qui reçoit
    quoi ») — jamais une recopie. ``frame`` : ce qu'elle vit, pour une condition qui lit son journal ; ``rights``
    et ``close`` : ce que ``gate_of`` lit du registre ; ``ports`` : ceux du noyau, pour un outil qui en attend un
    configuré (``needs``, ADR 0160) — sans eux, la porte ne le juge pas."""
    bundles = policy.tool_bundles
    if only:
        bundles = frozenset(b for b in (x.strip() for x in str(only).split(",")) if b and admitted(policy.tool_bundles, b))
    rights = rights if rights is not None else Rights()
    out = {}
    for name, spec in tools.items():
        if kind not in spec.episodes or not admitted(bundles, spec.bundle):
            continue
        got = judge(tools, spec, audience, kind, rights, close, frame, ports)
        if got is not None and got.offered:
            out[name] = spec
    return out


#: ce qui ferme un outil avant ses lignes : son service n'est pas configuré (``needs``), la condition qu'il déclare
#: sur qui est en face (``when``), celle de la ressource d'ailleurs qui le porte (``fits`` : un service, une app)
NEEDS, WHEN, FITS = "needs", "when", "fits"


@dataclass(frozen=True, slots=True)
class Judged:
    """Ce que la porte dit d'un outil devant une audience, à un moment : offert ou non ; pour un des siens, ce qu'elle
    en fait (``level``), ce qu'elle en garde et les lignes qui en décident (``why``) ; ``reason`` : ce qui l'a fermé
    avant ses lignes ; ``owned`` : offert parce qu'une ressource de l'outil est à qui est en face (ADR 0185)."""

    offered: bool
    level: str = NO
    keep: str = "rien"
    why: str = ""
    reason: str = ""
    owned: bool = False


def judge(tools: Mapping[str, ToolSpec], spec: ToolSpec, audience: Audience, kind: str, rights: Rights,
          close: Callable[[str], bool] | None = None, frame: Any = None,
          ports: Mapping[str, Any] | None = None) -> Judged | None:
    """La porte d'offre pour un seul outil (``offer`` la passe pour chacun ; ce qu'une personne a, écran par écran,
    la lit aussi — jamais une recopie) ; ``None`` : il ne sert pas à ce moment (``spec.episodes``). Un outil venu
    d'ailleurs (``fits``) ne dit ici qu'offert ou non : ce qu'elle en fait est la ligne de son service."""
    if kind not in spec.episodes:
        return None
    if spec.needs and ports is not None and not ready(ports.get(spec.needs)):
        return Judged(False, reason=NEEDS)
    if spec.when is not None and boundary.call(spec.when, audience, label=f"offre de {spec.name}") is not True:
        return Judged(False, reason=WHEN)
    if spec.fits is not None:
        fits = boundary.call(spec.fits, audience, kind, frame, label=f"offre de {spec.name}") is True
        return Judged(fits, reason="" if fits else FITS)
    got = allowed(tools, spec, audience, kind, rights, close)
    level, keep, why = (got.level, got.keep, got.why) if got is not None else (NO, "rien", "")
    if level != NO:
        return Judged(True, level, keep, why)
    if owns(spec, audience, kind, frame):
        return Judged(True, level, keep, why, owned=True)
    return Judged(False, level, keep, why)


def owns(spec: ToolSpec, audience: Audience, kind: str, frame: Any = None) -> bool:
    """Une ressource de l'outil appartient à qui est en face (``ToolSpec.owned``, ADR 0185) : une boîte, un compte.
    Offert alors même que sa famille ne l'ouvre pas ; son gestionnaire ne montre que ce qui est à elle."""
    return spec.owned is not None and \
        boundary.call(spec.owned, audience, kind, frame, label=f"offre de {spec.name} (à qui)") is True


def ready(port: Any) -> bool:
    """Un port là et configuré (``configured``, propriété ou méthode ; sans lui, sa présence suffit)."""
    if port is None:
        return False
    flag = getattr(port, "configured", True)
    return bool(flag() if callable(flag) else flag)


def admitted(bundles: frozenset[str], bundle: str) -> bool:
    """Un lot est-il admis ? Par son nom, ou par sa famille (``mcp.*`` admet ``mcp.meteo`` : des lots que des
    sources dynamiques ajoutent, ADR 0064) — et le lot qui porte le nom d'une famille l'admet entière
    (``forge_apps`` admet ``forge_apps.cours`` : chaque app est un lot, ses apps en sont un, ADR 0104)."""
    if bundle in bundles:
        return True
    family, dot, _rest = bundle.partition(".")
    return bool(dot) and (f"{family}.*" in bundles or family in bundles)


def defers_tools(gateway: Any, role: str) -> bool:
    """Le fournisseur de ce rôle sait-il différer des outils ? Sans réponse (ou en panne) : oui."""
    ask = getattr(gateway, "defers_tools", None)
    if ask is None:
        return True
    got = boundary.call(ask, role, label="outils différables")
    return True if isinstance(got, Failed) else bool(got)


def declare(specs: Sequence[ToolSpec], core: frozenset[str] | None = None,
            rights: Rights | None = None) -> tuple[ToolDecl, ...]:
    """Déclarations triées par nom : un préfixe stable pour le cache. Un outil
    dont le lot n'est pas « en main » (``core``) est déclaré à la demande, sauf
    règle d'un opérateur (``deferred``)."""
    return tuple(
        ToolDecl(s.name, s.description, dict(s.schema) if s.schema is not None else schema_of(s.args),
                 deferred=deferred(s, core, rights))
        for s in sorted(specs, key=lambda s: s.name)
    )


# ce qu'on lui dit de ses outils quand elle parle à quelqu'un (``runtime.tools.acting``) : faire plutôt qu'annoncer,
# et ne rien raconter qu'un outil ne lui a pas rendu (2026-10-04, nemotron : « peux-tu regarder les nouvelles ? » —
# « je vais regarder », aucun appel, puis Product Hunt et l'actualité française inventés sur quatre tours)


def means() -> tuple[tuple[str, str], ...]:
    """De quoi se donner les moyens de ce qu'elle ne sait pas faire, quand l'outil est là : (outil, en mots)."""
    return (("forge_write", phrase("runtime.tools.means_forge")), ("start_project", phrase("runtime.tools.means_project")))


def acting(specs: Sequence[ToolSpec]) -> str:
    """La règle de ses mains, pour une parole qui porte des outils (vide sans outil). Ce qu'elle peut se fabriquer
    n'est cité que si l'outil lui est offert : une inconnue ne voit pas la Forge, une initiative non plus. Quand un de
    ses outils parle à un service extérieur (ADR 0064) : ce qui en revient, ce qui y part."""
    if not specs:
        return ""
    names = {s.name for s in specs}
    found = [words for tool, words in means() if tool in names]
    text = phrase("runtime.tools.acting")
    if found:
        text = phrase("runtime.tools.acting_means", acting=text, means=phrase("runtime.tools.means_or").join(found))
        if "start_project" in names:  # un travail se lance maintenant, ou il n'existe pas (ADR 0104)
            text = f"{text} {phrase('runtime.tools.means_work')}"
    return f"{text} {phrase('runtime.tools.outside')}" if any(getattr(s, "outside", False) for s in specs) else text


def catalogue(specs: Sequence[ToolSpec], core: frozenset[str] | None, described: Mapping[str, str],
              rights: Rights | None = None) -> str:
    """Les lots offerts mais pas en main, une ligne chacun : ce qu'elle peut
    aller chercher. Vide quand tout est en main. Stable d'un tour à l'autre
    (trié), donc à sa place dans le préfixe en cache."""
    if core is None:
        return ""
    away: dict[str, list[str]] = {}
    for s in specs:
        if deferred(s, core, rights):
            away.setdefault(s.bundle, []).append(s.name)
    if not away:
        return ""
    lines = [f"- {b} : {described.get(b) or ', '.join(sorted(names))}" for b, names in sorted(away.items())]
    return "\n".join([phrase("runtime.tools.catalogue_header"), phrase("runtime.tools.catalogue_intro"), *lines])


def lendable(offered: Mapping[str, ToolSpec]) -> dict[str, ToolSpec]:
    """Ce qu'un point MCP peut prêter à un agent (ADR 0122) : ce que la porte lui offre en conversation, moins ce
    qui clôt une boucle. Un outil ne dit pas s'il écrit : la lecture seule se tient à l'exécution
    (``ReadingContext``)."""
    return {n: s for n, s in offered.items() if not s.ends_loop}
