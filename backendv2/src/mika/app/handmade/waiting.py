"""La file « À valider » (ADR 0177) : une seule page pour tout ce qui attend une décision. La composition lui donne ses
onglets (``TABS`` : les courriers à envoyer, les réponses Teams, les identités à confirmer, les rapprochements —
« Tout » et l'historique sont ceux de la console), ce qui n'est pas une demande d'envoi (``Waiting.items``) — les
identités à confirmer, lues dans la vue de la faculté d'identité, avec leurs faits, leur source et leurs actions déjà
orientées (``tabs/identities.py``) ; les rapprochements — deux fiches de l'annuaire au même nom, sans identifiant
commun (ADR 0298, lues dans le port ``contacts``, avec l'avis du juge quand il en a un : ADR 0304 — ce dont il est sûr
s'est fait d'office), et une personne dont on lui a parlé que porte quelqu'un qui lui
parle (la vue « Noms à relier » de l'identité, ``NAMES_VIEW``) —, leurs deux fiches côte à côte (``QueueItem.body``)
et leurs deux gestes — et ce que concerne une demande (``Waiting.about``, lu dans son contexte par
``approval_sources.about`` : une personne, un projet, un service, une app, un canal). « Noms à relier » n'est plus un
onglet (ADR 0298, lot 5) : une personne dont on lui parle a sa fiche d'emblée, et se rapproche des autres comme
n'importe quelle fiche ; face à quelqu'un qui lui parle, c'est l'identité qui les relie (sa mémoire le saura). Les vues
de la faculté d'identité n'ont plus de destination : la file est le seul endroit où l'on en décide (ADR 0180).
L'inspecteur dessine la file sans nommer ni plugin ni faculté.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from mika.app.handmade import approval_sources
from mika.app.handmade.pages import PARTS
from mika.app.handmade.tabs import Got, Line, instant, raw_lines, text, view_of
from mika.app.handmade.tabs.identities import claim_entry, handle_of
from mika.inspector.ui import UI, QueueItem, QueueTab

#: la sorte d'élément que le cadre met dans la file : une identité à confirmer (celles des domaines — un nom à relier,
#: un rapprochement de l'annuaire — sont dans leur part)
CLAIM = "identite"
#: la vue de la faculté d'identité d'où elles viennent : (propriétaire, vue)
CLAIMS_VIEW = ("identity", "revendications")
#: la part de chaque domaine dans la file (ADR 0310, ``QueuePart``), dans l'ordre des fiches
QUEUES = tuple(console.queue for console in PARTS if console.queue is not None)

#: ses onglets, dans leur ordre : celui du cadre, et ceux que chaque domaine inscrit
TABS: tuple[QueueTab, ...] = tuple(sorted((
    QueueTab("identites", "Identités à confirmer", kinds=(CLAIM,), order=30,
         description="Qui dit être quelqu'un d'autre, sans preuve encore : t'en porter garant, la démentir ou "
                     "relier ce moyen de communication.",
         empty="Personne ne dit être quelqu'un d'autre sans preuve en ce moment.",
         hint="Qui est qui, à valider"),
    *(tab for queue in QUEUES for tab in queue.tabs),
), key=lambda tab: tab.order))


def _claim_item(got: Got, line: Line, raw: dict[str, Any], rule: str) -> QueueItem:
    c = claim_entry(got, line)
    handle = handle_of(c["handle"])
    target = c["target"] if c["known"] else None
    facts: list[tuple[str, Any]] = [("vise", c["target"]), ("canal", c["channel"])]
    if (meter := line.get("vers la barre")) is not None:
        facts.append(("vers la barre", meter))
    facts += [("preuves comptées", {"t": "text", "text": c["evidence"] or "—"}), ("depuis", c["since"]),
              ("s'éteint", c["ends"])]
    sources = [("Le moyen de communication", line.href)] if line.href else []
    if target is not None and target.get("href"):
        sources.append((f"La fiche de {text(target)}", target["href"]))
    return QueueItem(CLAIM, handle, "Identité à confirmer", f"{text(c['handle'])} se présente comme {c['name']}",
                     context=text(target) if target is not None else "plusieurs personnes portent ce nom",
                     at=instant(raw.get("depuis")), facts=tuple(facts), sources=tuple(sources),
                     links=tuple((a["label"], a["href"]) for a in c["actions"]), note=rule)


class Waiting:
    """Ce que la composition met dans la file « À valider » (``InspectorDeps.queue``)."""

    tabs: Sequence[QueueTab] = TABS
    #: les feuilles de ce qu'elle dessine dans la liseuse (deux fiches côte à côte) : celles que les parts disent, dans
    #: l'ordre des fiches, chacune une fois
    styles: Sequence[str] = tuple(dict.fromkeys(sheet for queue in QUEUES for sheet in queue.styles))
    #: les vues qui montrent les mêmes demandes que la file, dans leur destination : l'accueil ne les compte pas une
    #: seconde fois (``UI.attention_items(distinct=True)``)
    covers: Sequence[str] = tuple(path for queue in QUEUES for path in queue.covers)
    #: les vues de ce qui attend ta décision hors des demandes d'envoi : la console en MCP les sert sous leur part, « la
    #: file « À valider » » (``inspector.mcp.QUEUE``), que la page Outils › Prêter à un agent montre (ADR 0304)
    views: Sequence[tuple[str, str]] = (CLAIMS_VIEW, *(view for queue in QUEUES for view in queue.views))

    def count(self, ui: UI, kinds: Sequence[str] | None) -> int:
        """Combien d'éléments de ces sortes attendent (toutes : ``kinds`` vide) — les compteurs de leurs vues."""
        total = 0
        if kinds is None or CLAIM in kinds:
            spec = ui.inspection.find(*CLAIMS_VIEW)
            got = ui.inspection.badge(spec) if spec is not None else None
            total += int(got[0]) if got else 0
        return total + sum(queue.count(ui, kinds) for queue in QUEUES if queue.count is not None)

    def about(self, ui: UI, context: str) -> tuple[str, str | None]:
        """Ce que concerne une demande, dit simplement (« Adrien », « projet n° 61 », « Teams »), et la fiche où ça
        mène (``None`` : aucune) — la file, sa demande ouverte et l'historique le disent tous ainsi."""
        return approval_sources.about(ui, context)

    async def items(self, ui: UI) -> list[QueueItem]:
        """Les identités à confirmer, telles que leur vue les dit ; puis ce que chaque domaine y met (les
        rapprochements de l'annuaire)."""
        out: list[QueueItem] = []
        got = await view_of(ui, *CLAIMS_VIEW)
        table = got.table("Revendications en attente") if got is not None else None
        if got is not None and table is not None:
            rule = next((n["text"] for n in got.notes()), "")
            out += [_claim_item(got, x, r, rule) for x, r in zip(got.lines("Revendications en attente"),
                                                                 raw_lines(got, table), strict=False)]
        for queue in QUEUES:
            if queue.items is not None:
                out += await queue.items(ui)
        return out


QUEUE = Waiting()
