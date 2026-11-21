"""Les mains du propriétaire simulé, pour le scénario de la chaîne (ADR 0279).

Dans le chat, il écrit (``banc.py``). Ici, il **agit** : ce qu'un propriétaire fait dans la console et chez l'hôte de
ses dépôts, par les mêmes portes que lui — les actions déclarées du moteur (``runtime.operations.perform``), l'accord
d'un effet proposé (``runtime.decisions``), et les gestes du faux hôte (``hote.FakeHost``). Rien n'est écrit au
journal par un autre chemin.

- ``plug`` : brancher le dépôt d'un projet et le faire récupérer ;
- ``look`` : un passage sur la console et chez l'hôte — accepter ou écarter un ticket proposé, répondre à une
  question, valider le plan d'un ticket, valider un point d'arrêt, donner son accord à ce qui attend, fusionner ou
  renvoyer une pull request ;
- ``happen`` : un événement du scénario (une issue d'un inconnu, un ticket de lui, des entreprises contactées, une
  réponse reçue).

Ce qui demande un jugement (accepter ce ticket ? valider ce plan ?) passe par ``judge`` : en mode sec, une règle
(``sec_chaine.owner_judges``) ; en mesure réelle, le modèle qui joue le propriétaire, avec sa fiche.
"""

from __future__ import annotations

import itertools
import unicodedata
from collections import Counter
from collections.abc import Callable, Sequence
from typing import Any

from chaine import CONFLICT_LOOKS, GIVEN_UP, LOOKS, RETOUCH, SENT_BACK, Brief, Chain, Happening
from hote import FakeHost, url_of

from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.faculties.projects import tracker
from mika.runtime import decisions
from mika.runtime.operations import perform

#: ce qu'il juge : (la sorte de décision, le projet par sa clé, le texte qu'il a sous les yeux) → (oui, sa raison)
Judge = Callable[[str, str, str], tuple[bool, str]]


def fold(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return " ".join(plain.lower().split())


#: les champs qu'un formulaire de la console porte cachés (la ligne visée) : ils se disent à part de ceux qu'on saisit
HIDDEN = frozenset({"item", "plan", "objective", "milestone", "list_name"})


def form(**values: str) -> dict[str, list[str]]:
    """Un formulaire de la console : ce qu'on y saisit (``_champs``), et ce que sa ligne porte fixé (``_fixes``)."""
    return {"_champs": [k for k in values if k not in HIDDEN], "_fixes": [k for k in values if k in HIDDEN],
            **{k: [v] for k, v in values.items()}}


class Owner:
    """Le propriétaire et ce qu'il fait de ses mains. ``ids`` : le numéro de chaque projet, par sa clé, rempli par le
    banc quand le projet naît."""

    def __init__(self, sc: Chain, handle: str, kernel: Callable[[], Any], host: FakeHost, clock: Any,
                 log: Callable[[str], None], judge: Judge) -> None:
        self.sc, self.handle, self.kernel, self.host, self.clock = sc, handle, kernel, host, clock
        self.log, self.judge = log, judge
        self.ids: dict[str, int] = {}
        self.plugged: set[str] = set()
        self.sent_back: set[str] = set()
        #: les pull requests qu'il a vues en conflit, et à combien de ses passages ; celles qu'il a fermées (leur
        #: ticket reste à écarter)
        self.conflicts: Counter[str] = Counter()
        self.closing: list[tuple[str, int]] = []
        #: les retouches qu'il poussera lui-même sur une branche principale (les événements ``push``)
        self.pushes: list[Happening] = []
        self.done: Counter[str] = Counter()
        self.failed: list[str] = []
        self._nonce = itertools.count(1)
        #: les propositions qu'il a déjà tranchées, les tickets déjà refusés une fois
        self._settled: set[int] = set()

    # ── les portes ──
    def _state(self) -> Any:
        return self.kernel().mind.frame().state(c.OWNER)

    def _project(self, key: str) -> Any:
        return self._state().projects.get(self.ids.get(key, -1))

    def key_of(self, pid: int) -> str:
        return next((k for k, v in self.ids.items() if v == pid), "")

    async def op(self, name: str, key: str, **values: str) -> bool:
        """Une action de la console sur un projet. Un refus est noté : c'est un constat, pas une panne."""
        got = await perform(self.kernel(), f"projects.{name}", form(**values), by=self.handle,
                            subject=str(self.ids[key]), nonce=f"banc-{next(self._nonce)}")
        self.done[name if got.ok else f"{name} (refusé)"] += 1
        self.log(f"   geste : {name} sur {key} → {'ok' if got.ok else 'refusé'} — {got.message}"
                 f"{' ' + str(got.errors) if getattr(got, 'errors', None) else ''}")
        if not got.ok:
            self.failed.append(f"{name} sur {key} : {got.message} {getattr(got, 'errors', '') or ''}".strip())
        return bool(got.ok)

    # ── brancher un dépôt ──
    async def plug(self, brief: Brief) -> None:
        """Le dépôt distant du projet, puis sa récupération (un atelier vierge prend son histoire). Une exécution en
        cours fait attendre la récupération : il réessaie à son passage suivant."""
        if not brief.repo or brief.key in self.plugged or brief.key not in self.ids:
            return
        p = self._project(brief.key)
        if p is None:
            return
        if not p.remote and not await self.op("depot_distant", brief.key, remote=url_of(brief.repo), branch="main",
                                              flow="auto"):
            return
        if await self.op("recuperer", brief.key):
            self.plugged.add(brief.key)

    # ── un passage ──
    def due(self, before: int, now: int, local: Callable[[int], Any]) -> bool:
        """Une de ses heures de passage est-elle tombée entre ``before`` et ``now`` ?"""
        a, b = local(before), local(now)
        marks = [b.replace(hour=h, minute=m, second=0, microsecond=0) for h, m in LOOKS]
        return any(a < mark <= b for mark in marks)

    async def look(self) -> None:
        for brief in self.sc.briefs:
            await self.plug(brief)
            if brief.key in self.ids:
                await self._tickets(brief.key)
                await self._milestones(brief.key)
        await self._accords()
        for brief in self.sc.briefs:
            if brief.repo and brief.key in self.plugged:
                self._pulls(brief)
        for key, number in self.closing:  # la pull request fermée pour un conflit : son ticket s'écarte
            for e in self._entries(key, *c.STAGES_OPEN):
                if e.item.pull_number == number:
                    await self.op("ticket_trancher", key, item=f"#{e.item.number}", verdict="dismiss",
                                  reason=GIVEN_UP, plan="0")
        self.closing.clear()

    def _entries(self, key: str, *stages: str) -> list[Any]:
        store = self.kernel().ports.get("store")
        return list(reversed(tracker.page(store, self.ids[key], c.TICKETS, statuses=stages, limit=50)))

    async def _tickets(self, key: str) -> None:
        for e in self._entries(key, c.STAGE_PROPOSED):
            wanted = self._planned(key, e.title)
            yes, why = (wanted.accept, wanted.reason) if wanted is not None else \
                self.judge("ticket", key, f"{e.title}\n{e.body}")
            await self.op("ticket_trancher", key, item=f"#{e.item.number}", verdict="accept" if yes else "dismiss",
                          reason="" if yes else (why or "hors sujet"), plan="0")
        for e in self._entries(key, c.STAGE_VALIDATION):
            plan = tracker.note_text(self.kernel().ports.get("store"), e.item.plan_seq)
            yes, why = self.judge("plan", key, f"{e.title}\n{plan}")
            if not yes and e.item.number in self._settled:
                continue  # il a déjà dit ce qui manquait : il attend le plan suivant
            self._settled.add(e.item.number)
            await self.op("ticket_trancher", key, item=f"#{e.item.number}", verdict="validate" if yes else "refuse",
                          reason=why, plan=str(e.item.plan_seq))
        for e in self._entries(key, c.STAGE_DECISION):
            if e.item.dismissal_at:  # elle propose de l'écarter : il confirme
                yes, why = self.judge("dismissal", key, f"{e.title}\n{e.body}")
                if yes:
                    await self.op("ticket_trancher", key, item=f"#{e.item.number}", verdict="dismiss", reason=why,
                                  plan="0")
            elif getattr(e.item, "blocked_at", 0) or e.item.number in self._settled:
                continue
            else:  # sa question : il répond dans le fil
                self._settled.add(e.item.number)
                _, said = self.judge("question", key, f"{e.title}\n{e.body}")
                await self.op("element_noter", key, list_name=c.TICKETS, item=f"#{e.item.number}",
                              text=said or "fais au plus simple")

    def _planned(self, key: str, title: str) -> Happening | None:
        """L'issue du scénario que ce ticket proposé reflète (sa fiche dit déjà ce qu'il en fait)."""
        return next((h for h in self.sc.happenings if h.kind == "issue" and h.project == key
                     and fold(h.title) == fold(title)), None)

    async def _milestones(self, key: str) -> None:
        p = self._project(key)
        for o in (p.objectives if p is not None else ()):
            for m in o.milestones:
                if m.status == c.OPEN and m.ready_at and m.ready_at > m.refused_at:
                    yes, why = self.judge("milestone", key, f"objectif n° {o.id}, jalon n° {m.id}")
                    await self.op("jalon_trancher", key, objective=str(o.id), milestone=str(m.id),
                                  verdict="validate" if yes else "refuse", reason=why)

    async def _accords(self) -> None:
        """Ce qui attend son accord (une pull request à ouvrir, un envoi, une issue à publier) : il lit l'aperçu,
        puis il tranche."""
        kernel = self.kernel()
        for pending in kernel.mind.frame().get(rt.PENDING_EFFECTS) or ():
            if pending.proposal in self._settled:
                continue
            self._settled.add(pending.proposal)
            stored = kernel.mind.store.get_events([pending.proposal])
            args_json = kernel.mind.decode(stored[0]).data.args_json if stored else "{}"
            seen = await decisions.preview(kernel.mind, kernel.ports, pending.capability, args_json)
            text = seen.text if seen is not None else pending.capability
            yes, why = self.judge("accord", pending.capability, text)
            got = await decisions.decide(kernel.mind, kernel.ports, pending.proposal, yes, by=self.handle, note=why,
                                         seen=seen.digest if seen is not None and yes else "")
            self.done[f"accord {pending.capability} : {got.status}"] += 1
            self.log(f"   geste : accord {pending.capability} n° {pending.proposal} → {got.status} {got.message}")
            if got.draft is None:
                self.failed.append(f"accord {pending.capability} : {got.status} {got.message}")

    def _pulls(self, brief: Brief) -> None:
        """Chez l'hôte : il fusionne une pull request dont les vérifications sont passées ; la première du site, il
        la renvoie une fois avec un mot, puis la fusionne quand un nouveau commit y est arrivé."""
        url = url_of(brief.repo)
        for pull in self.host.open_pulls(url):
            if not self.host.ready(url, pull):
                self.log(f"   hôte : la pull request n° {pull.number} de {brief.key} attend ses vérifications")
                continue
            if pull.review and pull.at <= pull.review_at:
                continue  # renvoyée : il attend qu'elle y revienne
            if brief.key == "site" and brief.key not in self.sent_back:
                self.sent_back.add(brief.key)
                self.host.send_back(url, pull.number, SENT_BACK)
                self.done["pull request renvoyée"] += 1
                continue
            mark = f"{brief.key}:{pull.number}"
            self._retouch(brief, url, pull)
            if not self.host.mergeable(url, pull):
                # l'hôte la dit impossible à fusionner : il n'y touche pas — le moteur le lit chez l'hôte, rouvre
                # l'objectif, et c'est à elle de ramener la base dans sa branche (ADR 0280). Le filet : encore en
                # conflit trois jours plus tard, il la ferme et écarte son ticket — ce travail-là ne passera pas
                self.conflicts[mark] += 1
                if self.conflicts[mark] == 1:
                    self.done["pull request en conflit, laissée à elle"] += 1
                    self.log(f"   hôte : la pull request n° {pull.number} de {brief.key} est en conflit avec la base")
                if self.conflicts[mark] > CONFLICT_LOOKS:
                    self.failed.append(f"pull request n° {pull.number} de {brief.key} : encore en conflit après "
                                       f"{CONFLICT_LOOKS} passages, fermée")
                    self.host.send_back(url, pull.number, GIVEN_UP, close=True)
                    self.closing.append((brief.key, pull.number))
                    self.done["pull request en conflit, fermée"] += 1
                continue
            why = self.host.merge(url, pull.number)
            self.done["pull request fusionnée" if not why else f"fusion impossible ({why})"] += 1
            if why:
                self.failed.append(f"fusion de la pull request n° {pull.number} de {brief.key} : {why}")
            elif self.conflicts[mark]:
                self.done["pull request en conflit, résolue puis fusionnée"] += 1

    def _retouch(self, brief: Brief, url: str, pull: Any) -> None:
        """Sa retouche à lui, poussée sur la branche principale (un événement ``push``) : elle part au passage où
        la pull request du ticket qu'elle croise attend sa fusion."""
        for h in [x for x in self.pushes if x.project == brief.key]:
            crossed = any(fold(h.text) in fold(e.title) and e.item.pull_number == pull.number
                          for e in self._entries(brief.key, *c.STAGES_OPEN))
            if not crossed:
                continue
            self.pushes.remove(h)
            why = self.host.direct_commit(url, *RETOUCH, message=h.title)
            self.done["retouche poussée sur la branche principale" if not why else f"retouche impossible ({why})"] += 1
            if why:
                self.failed.append(f"retouche sur {brief.key} : {why}")

    # ── les événements ──
    async def happen(self, h: Happening) -> None:
        self.log(f"   événement : {h.said()}")
        if h.kind == "push":  # elle partira à son passage chez l'hôte (``_retouch``)
            self.pushes.append(h)
            return
        if h.kind == "issue":
            brief = self.sc.brief(h.project)
            self.host.stranger_issue(url_of(brief.repo), h.title, h.text, h.who[0])
        elif h.kind == "ticket" and h.project in self.ids:
            await self.op("ticket_ouvrir", h.project, title=h.title, text=h.text, kind=c.TASK, priority=c.NORMAL)
        elif h.kind in ("contacted", "answer") and h.project in self.ids:
            for name in h.who:
                await self._company(h, name)

    async def _company(self, h: Happening, name: str) -> None:
        """Une entreprise de la liste : il la marque contactée, ou note ce qu'elle a répondu. Sans liste, ou sans
        cette entreprise dedans, il ne peut rien noter : c'est un constat."""
        p = self._project(h.project)
        store = self.kernel().ports.get("store")
        for lst in (p.board.lists if p is not None else ()):
            for e in tracker.page(store, p.id, lst.name, limit=100):
                if fold(name) not in fold(e.title):
                    continue
                if h.kind == "answer":
                    await self.op("element_noter", h.project, list_name=lst.name, item=e.item.key, text=h.text)
                    wanted = _status(lst, ("repondu",), 1)
                else:
                    wanted = _status(lst, ("contactee", "contacte"), 1)
                if wanted and wanted != e.item.status:
                    await self.op("element_statut", h.project, list_name=lst.name, item=e.item.key, status=wanted,
                                  note="contactée" if h.kind == "contacted" else "a répondu")
                return
        self.failed.append(f"{h.kind} : « {name} » n'est dans aucune liste du projet {h.project}")
        self.log(f"   geste impossible : « {name} » n'est dans aucune liste du projet {h.project}")


def _status(lst: Any, words: Sequence[str], fallback: int) -> str:
    """Le statut de cette liste dont le mot dit ce qu'il veut noter ; sinon celui de ce rang parmi les ouverts."""
    for status in (*lst.open, *lst.closed):
        said = fold(tracker.status_words(lst.name, status))
        if any(w in said or w in fold(status) for w in words):
            return str(status)
    return str(lst.open[fallback]) if len(lst.open) > fallback else ""
