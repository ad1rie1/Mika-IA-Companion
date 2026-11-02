"""La file « À valider » (ADR 0177) : une seule page pour tout ce qui attend une décision. La composition lui donne ses
onglets (``TABS`` : les courriers à envoyer, les réponses Teams, les identités à confirmer, les noms à relier — « Tout »
et l'historique sont ceux de la console) et ce qui n'est pas une demande d'envoi (``Waiting.items``) : les identités à
confirmer et les noms à relier, lus dans les vues de la faculté d'identité, avec leurs faits, leur source et leurs
actions déjà orientées (``tabs/identities.py``). Ces deux vues n'ont plus de destination : la file est le seul
endroit où l'on en décide (ADR 0180). L'inspecteur dessine la file sans nommer ni plugin ni faculté.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from mika.app.handmade.tabs import Got, Line, blank, instant, raw_lines, text
from mika.app.handmade.tabs.identities import claim_entry, handle_of, name_entry
from mika.contracts import email as email_c
from mika.contracts import teams as teams_c
from mika.inspector.ui import UI, QueueItem, QueueTab

#: les sortes d'éléments que la composition met dans la file
CLAIM, NAME = "identite", "nom"
#: les vues de la faculté d'où ils viennent : (propriétaire, vue)
CLAIMS_VIEW, NAMES_VIEW = ("identity", "revendications"), ("identity", "noms")

TABS: tuple[QueueTab, ...] = (
    QueueTab("courriers", "Courriers à envoyer", capabilities=(email_c.SEND,), order=10,
             description="Les mails qu'elle voudrait envoyer : ce qui partira, tel quel, après ton accord.",
             empty="Aucun mail n'attend ton accord."),
    QueueTab("teams", "Réponses Teams", capabilities=(teams_c.SEND,), order=20,
             description="Ses réponses dans Teams, à ta place : ce qui sera posé, après ton accord.",
             empty="Aucune réponse Teams n'attend ton accord."),
    QueueTab("identites", "Identités à confirmer", kinds=(CLAIM,), order=30,
             description="Qui dit être quelqu'un d'autre, sans preuve encore : t'en porter garant, la démentir ou "
                         "relier ce moyen de communication.",
             empty="Personne ne dit être quelqu'un d'autre sans preuve en ce moment."),
    QueueTab("noms", "Noms à relier", kinds=(NAME,), order=40,
             description="Un nom dont on lui a parlé, porté par quelqu'un qu'elle connaît : c'est elle, ou non. Rien "
                         "n'est relié d'une ressemblance de nom.",
             empty="Aucun nom dont on lui a parlé n'attend quelqu'un."),
)


async def _view(ui: UI, owner: str, name: str) -> Got | None:
    spec = ui.inspection.find(owner, name)
    if spec is None:
        return None
    return Got(ui, list(await ui.inspection.arun(spec, {}, ui.when_long)), {}, {})


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


def _name_item(line: Line, raw: dict[str, Any], rule: str) -> QueueItem:
    w = name_entry(line)
    person = w["person"]
    facts = [(k, v) for k, v in (("qui lui en a parlé", w["told"]), ("ce qui attend", {"t": "text", "text": w["what"]}),
                                 ("personne qui le porte", person), ("par où", {"t": "text", "text": w["where"]}),
                                 ("vue pour la première fois", w["first"])) if not blank(v)]
    dismiss = w["dismiss"]
    return QueueItem(NAME, f"{w['name']}|{text(person)}", "Nom à relier", f"On lui a parlé de {w['name']}",
                     context=f"porté par {text(person)}", at=instant(raw.get("vue pour la première fois")),
                     facts=tuple(facts),
                     sources=((f"La fiche de {text(person)}", person["href"]),) if (person or {}).get("href") else (),
                     links=(("C'est elle : relier…", w["href"]),) if w["href"] else (),
                     actions=((dismiss["key"], dismiss.get("initial") or {}, dismiss.get("title") or "Ce n'est pas elle"),)
                     if dismiss else (), note=rule, warn=w["homonyms"])


class Waiting:
    """Ce que la composition met dans la file « À valider » (``InspectorDeps.queue``)."""

    tabs: Sequence[QueueTab] = TABS
    #: les vues qui montrent les mêmes demandes que la file, dans leur destination : l'accueil ne les compte pas une
    #: seconde fois (``UI.attention_items(distinct=True)``)
    covers: Sequence[str] = ("courrier/brouillons", "teams/reponses", "projets/tous")

    def count(self, ui: UI, kinds: Sequence[str] | None) -> int:
        """Combien d'éléments de ces sortes attendent (toutes : ``kinds`` vide) — les compteurs de leurs vues."""
        total = 0
        for kind, (owner, name) in ((CLAIM, CLAIMS_VIEW), (NAME, NAMES_VIEW)):
            if kinds is not None and kind not in kinds:
                continue
            spec = ui.inspection.find(owner, name)
            got = ui.inspection.badge(spec) if spec is not None else None
            total += int(got[0]) if got else 0
        return total

    async def items(self, ui: UI) -> list[QueueItem]:
        """Les identités à confirmer et les noms à relier, tels que leurs vues les disent."""
        out: list[QueueItem] = []
        got = await _view(ui, *CLAIMS_VIEW)
        table = got.table("Revendications en attente") if got is not None else None
        if got is not None and table is not None:
            rule = next((n["text"] for n in got.notes()), "")
            out += [_claim_item(got, x, r, rule) for x, r in zip(got.lines("Revendications en attente"),
                                                                 raw_lines(got, table), strict=False)]
        got = await _view(ui, *NAMES_VIEW)
        table = got.table("Noms qui attendent") if got is not None else None
        if got is not None and table is not None:
            rule = next((n["text"] for n in got.notes()), "")
            out += [_name_item(x, r, rule) for x, r in zip(got.lines("Noms qui attendent"),
                                                          raw_lines(got, table), strict=False)]
        return out


QUEUE = Waiting()
