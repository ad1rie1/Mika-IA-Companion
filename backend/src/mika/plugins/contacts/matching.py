"""Le juge des rapprochements (ADR 0304) : le processus ``contacts.match``.

- **Ce qui est sûr se réunit d'office.** Un identifiant commun réunit deux fiches dès la collecte (ADR 0298) — un
  identifiant Teams se compare sous sa forme canonique (``ports.teams.person_key``), quelle que soit celle reçue. Pour
  le reste, le nom ne prouve rien : c'est un juge, le modèle (rôle ``match``), qui dit si deux fiches sont la même
  personne, à partir de tout ce que l'annuaire sait d'elles. Ce dont il est sûr se fait seul : il les réunit
  (``ContactsPort.unite``, comme une preuve : jamais deux fiches qu'une opératrice a séparées, ni reliées à deux
  personnes différentes, ni un nom raconté face à quelqu'un qui lui parle), ou les sait deux et ne te les propose
  plus. Ce dont il n'est pas sûr t'attend dans À valider › Rapprochements, avec son avis en ses mots.
- **Qui il juge** (``ContactsPort.likenesses``) : les paires des suggestions (le même nom, une initiale, un prénom
  seul) et celles qui ont un mot rare de leurs noms en commun, quelle que soit sa forme — « Kévin Massol » et « Kévin
  MASSOL-EXT », « Moussaab KHALID » et « khalid moussaab » : rien n'est retiré des noms, c'est la rareté d'un mot
  dans l'annuaire qui dit s'il compte. Une paire n'est jugée qu'une fois sur ce qu'elle est (``bases``,
  ``pair_basis``) : une fiche qui change (un nouvel identifiant, un nouveau nom, une organisation) se rejuge.
- **Comment** : par groupes — une fiche et celles qui lui ressemblent (``GROUP_MAX`` au plus), la plus récente
  d'abord (un nouveau moyen de communication trouve vite sa fiche). Le juge voit de chacune ses noms, son organisation,
  son poste, ses identifiants (ses adresses et ses numéros en clair ; de Teams, seulement la sorte de compte : de son
  organisation, invité anonyme d'une réunion, personnel), où et quand elle la voit, les conversations Teams où elle
  écrit, l'objet de ses derniers mails, les groupes du téléphone, qui l'a racontée, la personne qui lui est reliée. Il
  rend qui est qui : des personnes (des numéros de fiches, sûres ou non, et pourquoi) et les fiches qu'il sait
  différentes. Sa consigne est dans ``persona/voix.yaml`` (``contacts.match``) ; sa réponse est relue strictement
  (``parse``) — illisible, rien ne change et le groupe attend que ses fiches changent.
- **Combien** : au plus ``match_per_run`` appels par passage et ``match_calls_per_day`` en vingt-quatre heures (les
  appels se comptent dans l'annuaire, ``judge_calls``) ; un appel qui échoue (une panne, un quota retenu) n'est pas
  compté, le passage suivant reprend. Un passage toutes les heures, et peu après un message remarqué.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from mika.contracts import email as email_c
from mika.contracts import identity as identity_c
from mika.contracts import phone as phone_c
from mika.contracts import self_ as self_c
from mika.contracts import teams as teams_c
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.faculty import CatchUp
from mika.kernel.frame import Frame
from mika.plugins.contacts import CONTACTS, ContactsState, params
from mika.plugins.contacts.inspect import account_name, app_word, name_of
from mika.plugins.contacts.portrait import teams_place
from mika.ports.contacts import (
    APART,
    EMAIL,
    PERSON_KIND,
    PHONE,
    PHONE_APP,
    PHONE_SOURCE,
    REASON_MAX,
    SAME,
    TEAMS_ID,
    TOLD,
    TOLD_NAME,
    ContactSheet,
    JudgeCall,
    Judgement,
    Likeness,
    pair_basis,
)
from mika.ports.llm import LLMRequest, Message, json_object
from mika.ports.preprocess import inert
from mika.vocab.access import SELF
from mika.vocab.phrasebook import phrase

log = logging.getLogger("mika.contacts.match")

#: le rôle de ses appels
ROLE = "match"
#: un passage : au plus tôt tant après un message remarqué (la collecte range d'abord), sinon toutes les heures ; le
#: premier, peu après le démarrage
WAKE_GAP = 3 * MINUTE
EVERY = HOUR
START_DELAY = 3 * MINUTE
#: les plafonds se comptent sur ce qui précède (vingt-quatre heures)
CAP_SPAN = DAY
#: au plus tant de fiches par appel : une fiche et celles qui lui ressemblent le plus
GROUP_MAX = 8
#: ce qu'il voit d'une fiche, au plus : ses autres noms, ses conversations Teams, l'objet de ses derniers mails, les
#: groupes du téléphone
NAMES_SHOWN, CONVERSATIONS, SUBJECTS, GROUPS = 4, 4, 2, 3
#: la sortie d'un appel, au plus (jetons) : huit fiches, leurs personnes et les paires dites deux, chacune sa raison
#: courte — une réponse coupée ne se lit pas, et son groupe attendrait que ses fiches changent
OUTPUT_MAX = 4000
#: la forme de la réponse, que le fournisseur garantit quand il le sait (ADR 0267) ; ``parse`` relit toujours du texte
_CARDS = {"type": "array", "items": {"type": "integer"}}
PERSON_SCHEMA = json_object(fiches=_CARDS, sure={"type": "boolean"}, raison={"type": "string"})
APART_SCHEMA = json_object(fiches=_CARDS, raison={"type": "string"})
MATCH_SCHEMA = json_object(personnes={"type": "array", "items": PERSON_SCHEMA},
                           differentes={"type": "array", "items": APART_SCHEMA})
_JSON = re.compile(r"\{.*\}", re.S)


@dataclass(frozen=True, slots=True)
class Group:
    """Une personne selon le juge : les numéros de ses fiches (de 1 au nombre de fiches), s'il en est sûr, pourquoi."""

    cards: tuple[int, ...]
    sure: bool
    reason: str = ""


@dataclass(frozen=True, slots=True)
class Verdict:
    """Ce que le juge rend d'un groupe : qui est qui (``people``), et les paires de fiches (numéros, la plus petite
    d'abord) qu'il sait deux personnes, avec pourquoi (``apart``)."""

    people: tuple[Group, ...]
    apart: tuple[tuple[int, int, str], ...] = ()


def _reason(value: object) -> str:
    return " ".join(value.split())[:REASON_MAX] if isinstance(value, str) else ""


def _cards(value: object, count: int) -> list[int]:
    """Des numéros de fiches, chacun une fois, de 1 à ``count`` (le reste tombe)."""
    if not isinstance(value, list):
        return []
    out: list[int] = []
    for n in value:
        if isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= count and n not in out:
            out.append(n)
    return out


def parse(text: str, count: int) -> Verdict | None:
    """La réponse du juge, relue strictement : un objet JSON dont « personnes » est une liste ; chaque personne, des
    numéros de fiches (de 1 à ``count``), « sure » vrai ou non, une raison — une fiche déjà placée ne compte qu'à sa
    première personne ; « differentes », des paires de deux fiches distinctes. Une paire dite à la fois la même
    personne et deux rend cette personne incertaine. ``None`` : rien de lisible (pas de JSON, pas de liste, aucune
    personne qui tienne)."""
    found = _JSON.search(text or "")
    if not found:
        return None
    try:
        data = json.loads(found.group(0))
    except ValueError:
        return None
    raw = data.get("personnes") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return None
    placed: set[int] = set()
    people: list[Group] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        cards = [n for n in _cards(item.get("fiches"), count) if n not in placed]
        if not cards:
            continue
        placed.update(cards)
        people.append(Group(tuple(cards), item.get("sure") is True, _reason(item.get("raison"))))
    if not people:
        return None
    apart: dict[tuple[int, int], str] = {}
    listed = data.get("differentes")
    for item in listed if isinstance(listed, list) else ():
        if not isinstance(item, dict):
            continue
        cards = _cards(item.get("fiches"), count)
        if len(cards) == 2:
            apart.setdefault((min(cards), max(cards)), _reason(item.get("raison")))
    # dites à la fois la même personne et deux : il n'en est pas sûr
    for i, g in enumerate(people):
        inside = {(a, b) for a in g.cards for b in g.cards if a < b}
        if inside & set(apart):
            people[i] = Group(g.cards, False, g.reason)
            for pair in inside:
                apart.pop(pair, None)
    return Verdict(tuple(people), tuple((a, b, why) for (a, b), why in sorted(apart.items())))


def verdicts(order: Sequence[int], verdict: Verdict | None, bases: Mapping[int, str], now: int,
             call_id: str) -> list[Judgement]:
    """Ce que le juge dit de chaque paire du groupe (``order`` : les fiches, dans l'ordre de leurs numéros) : la même
    personne (sûre ou non) quand il les met ensemble ; deux, sûrement, quand il le dit ; deux, sans en être sûr,
    quand il les met à part sans rien dire. Rien de lisible : un avis vide, qui attend que les fiches changent."""
    where: dict[int, Group] = {}
    for g in verdict.people if verdict is not None else ():
        for n in g.cards:
            where[n] = g
    apart = {(a, b): why for a, b, why in (verdict.apart if verdict is not None else ())}
    out = []
    for i in range(1, len(order) + 1):
        for j in range(i + 1, len(order) + 1):
            a, b = sorted((order[i - 1], order[j - 1]))
            basis = pair_basis(bases.get(a, ""), bases.get(b, ""))
            if verdict is None:
                out.append(Judgement(a, b, "", False, "", basis, now, call_id))
            elif where.get(i) is not None and where.get(i) is where.get(j):
                g = where[i]
                out.append(Judgement(a, b, SAME, g.sure, g.reason, basis, now, call_id))
            elif (i, j) in apart:
                out.append(Judgement(a, b, APART, True, apart[(i, j)], basis, now, call_id))
            else:
                out.append(Judgement(a, b, APART, False, "", basis, now, call_id))
    return out


def system(name: str) -> str:
    """La consigne du juge, au nom de celle dont il tient l'annuaire (celui de sa persona : jamais écrit ici)."""
    return phrase("contacts.match.system", name=name)


def day(frame: Frame, at: int) -> str:
    then = frame.local(at)
    return phrase("contacts.match.day", day=f"{then.day:02d}", month=f"{then.month:02d}", year=then.year)


def teams_word(value: str) -> str:
    """La sorte d'un compte Teams, sans son identifiant (qui ne dit rien au juge) : de son organisation, invité anonyme
    d'une réunion, personnel."""
    if value.startswith("8:orgid:"):
        return phrase("contacts.match.teams.org")
    if value.startswith("8:teamsvisitor:"):
        return phrase("contacts.match.teams.visitor")
    if value.startswith("8:live:"):
        return phrase("contacts.match.teams.personal")
    return phrase("contacts.match.teams.other")


def card(ctx: Any, frame: Frame, n: int, sheet: ContactSheet, her: str) -> str:
    """Ce que le juge voit d'une fiche : ses noms, son organisation et son poste, ses identifiants, où et quand elle la
    voit, où elle écrit, qui l'a racontée, la personne qui lui est reliée — ce qui vient d'ailleurs, inerte."""
    lines = [phrase("contacts.match.card", n=n, name=inert(sheet.name, 80))]
    others = [x for x in sheet.names if x != sheet.name][:NAMES_SHOWN]
    if others:
        lines.append(phrase("contacts.match.names", names=", ".join(f"« {inert(x, 80)} »" for x in others)))
    if sheet.org is not None:
        lines.append(phrase("contacts.match.org", org=inert(sheet.org.name, 80)))
    if sheet.title or sheet.department:
        lines.append(phrase("contacts.match.role", role=inert(" · ".join(x for x in (sheet.title, sheet.department)
                                                                           if x), 120)))
    said: list[str] = []
    tellers: list[str] = []
    places: dict[tuple[str, str], list[Any]] = {}
    groups: list[str] = []
    own = False
    for i in sheet.identifiers:
        for x in i.sightings:
            places.setdefault((x.source, x.account), []).append(x)
            own = own or x.own
            groups += [t.title for t in x.threads if t.group and t.title]
        if i.kind == EMAIL and not i.generic:
            said.append(phrase("contacts.match.email", value=inert(i.value, 120)))
        elif i.kind == PHONE:
            said.append(phrase("contacts.match.phone", value=inert(i.value, 40)))
        elif i.kind == TEAMS_ID:
            said.append(teams_word(i.value))
        elif i.kind == PHONE_APP:
            said += [phrase("contacts.match.phone_app", app=app_word(i.value), owner=inert(name_of(frame, x.account),
                                                                                          80))
                     for x in i.sightings if x.source == PHONE_SOURCE]
        elif i.kind == TOLD_NAME:
            tellers += [name_of(frame, x.account) if x.account != SELF else phrase("contacts.match.herself", name=her)
                        for x in i.sightings if x.source == TOLD]
    lines += list(dict.fromkeys(said))
    if tellers:
        lines.append(phrase("contacts.match.told", by=", ".join(inert(t, 80) for t in dict.fromkeys(tellers))))
    for (source, account), seen in sorted(places.items()):
        if source == TOLD:
            continue
        firsts, lasts = [x.first for x in seen if x.first], [x.last for x in seen if x.last]
        lines.append(phrase("contacts.match.seen", where=inert(account_name(ctx, source, account, frame), 80),
                            count=sum(x.count for x in seen),
                            first=day(frame, min(firsts)) if firsts else "—",
                            last=day(frame, max(lasts)) if lasts else "—"))
    authors = [i.value for i in sheet.identifiers if i.kind == TEAMS_ID]
    teams = ctx.ports.get("teams")
    if authors and teams is not None:
        found = teams.written_in(authors, CONVERSATIONS)
        if found:
            lines.append(phrase("contacts.match.wrote", places=" ; ".join(teams_place(c.kind, c.title)
                                                                         for c, _n, _at in found)))
    addresses = [i.value for i in sheet.identifiers if i.kind == EMAIL and not i.generic]
    mail = ctx.ports.get("mail")
    if addresses and mail is not None:
        subjects = [m.subject for a in addresses[:2] for m in mail.letters_from(a, limit=SUBJECTS) if m.subject]
        if subjects:
            lines.append(phrase("contacts.match.mails", subjects=" ; ".join(
                f"« {inert(x, 100)} »" for x in list(dict.fromkeys(subjects))[:SUBJECTS])))
    if groups:
        lines.append(phrase("contacts.match.groups", titles=" ; ".join(
            f"« {inert(x, 80)} »" for x in list(dict.fromkeys(groups))[:GROUPS])))
    if sheet.person:
        lines.append(phrase("contacts.match.linked", who=inert(name_of(frame, sheet.person), 80), name=her))
    if own:
        lines.append(phrase("contacts.match.own"))
    return "\n".join(lines)


def ask(ctx: Any, frame: Frame, sheets: Sequence[ContactSheet], her: str) -> str:
    """Le message du juge : les fiches du groupe, numérotées dans cet ordre."""
    return phrase("contacts.match.ask", count=len(sheets),
                  cards="\n\n".join(card(ctx, frame, n, x, her) for n, x in enumerate(sheets, 1)))


def groups(due: Sequence[Likeness], likes: Sequence[Likeness]) -> list[list[int]]:
    """Les groupes à juger : pour chaque fiche d'une paire à juger, la plus récente d'abord (le plus grand numéro), elle
    et celles qui lui ressemblent (``GROUP_MAX`` au plus) — d'abord celles dont la paire est à juger, puis les autres,
    les plus fortes d'abord : un groupe couvre toujours ce qui l'a ouvert, et ne se redemande pas pour rien. Une fiche
    déjà dans un groupe n'en ouvre pas un autre ; un groupe sans paire à juger ne s'ouvre pas."""
    near: dict[int, list[Likeness]] = {}
    for x in likes:  # la plus forte d'abord (``likenesses``)
        near.setdefault(x.a, []).append(x)
        near.setdefault(x.b, []).append(x)
    pending = {(x.a, x.b) for x in due}
    seeds = sorted({c for x in due for c in (x.a, x.b)}, reverse=True)
    taken: set[int] = set()
    out: list[list[int]] = []
    for seed in seeds:
        if seed in taken:
            continue
        mine = near.get(seed, [])
        group, fresh = [seed], False
        for x in [x for x in mine if (x.a, x.b) in pending] + [x for x in mine if (x.a, x.b) not in pending]:
            if len(group) >= GROUP_MAX:
                break
            other = x.b if x.a == seed else x.a
            if other not in group and other not in taken:
                group.append(other)
                fresh = fresh or (x.a, x.b) in pending
        if not fresh:
            continue
        taken.update(group)
        out.append(group)
    return out


@CONTACTS.process("contacts.match", wake_on=[teams_c.NOTICED, email_c.NOTICED, phone_c.RECEIVED,
                                               identity_c.NAME_BOUND],
                  reads=[identity_c.IDENTITY, self_c.PERSONA], catch_up=CatchUp.ONCE, max_quantum_s=1800, priority=96,
                  deadline_s=1800)
class Matching:
    def __init__(self) -> None:
        #: les messages remarqués au début du dernier passage (``None`` : pas encore passé)
        self.handled: int | None = None
        #: la fin du dernier passage : la cadence se compte d'elle
        self.done_at: int | None = None
        #: le démarrage (le premier passage attend un peu)
        self.born: int | None = None

    def next_due(self, s: ContactsState | None, frame: Frame, last_run: int | None) -> int | None:
        if not params(frame.env.params_of(CONTACTS.name, frame.root)).matching:
            return None
        if self.handled is None:
            self.born = self.born if self.born is not None else frame.now
            return max(frame.now, self.born + START_DELAY)
        since = max(self.done_at or 0, last_run or 0)
        if (s.heard if s is not None else 0) != self.handled:
            return max(frame.now, since + WAKE_GAP)
        return max(frame.now, since + EVERY)

    async def run(self, ctx: Any) -> None:
        heard = ctx.state.heard if ctx.state is not None else 0
        try:
            await self._run(ctx)
        finally:
            self.handled, self.done_at = heard, ctx.now

    async def _run(self, ctx: Any) -> None:
        store = ctx.ports.get("contacts")
        p = params(ctx.frame.env.params_of(CONTACTS.name, ctx.frame.root))
        serving = getattr(ctx.llm, "serving", None)
        if store is None or ctx.llm is None or not p.matching or (callable(serving) and not serving(ROLE)):
            return
        now = ctx.now
        calls = len(store.judge_calls(since=now - CAP_SPAN))
        if calls >= p.match_calls_per_day:
            return
        likes = store.likenesses()
        if not likes:
            return
        bases = store.bases({c for x in likes for c in (x.a, x.b)})
        said = {(j.a, j.b): j for j in store.judgements([(x.a, x.b) for x in likes])}
        due = [x for x in likes if (j := said.get((x.a, x.b))) is None
               or j.basis != pair_basis(bases.get(x.a, ""), bases.get(x.b, ""))]
        if not due:
            return
        held = getattr(ctx.llm, "held", None)
        if callable(held) and held(ROLE, 3):
            return  # le quota est réservé à la conversation : le passage suivant reprendra
        her = self_c.name_of(ctx.frame.get(self_c.PERSONA))
        pending = {(x.a, x.b) for x in due}
        made = 0
        for group in groups(due, likes):
            if made >= p.match_per_run or calls >= p.match_calls_per_day:
                break
            sheets = [x for c in group if (x := store.sheet(c)) is not None and x.kind == PERSON_KIND]
            shown = {x.id for x in sheets}
            # une fiche qu'on ne peut pas lui montrer (plus rien de vu, réunie entre-temps) : ses paires attendent
            # qu'elle change, sans appel — sinon le groupe se redemanderait à chaque passage sans elle
            store.judged(None, [Judgement(a, b, "", False, "", pair_basis(bases.get(a, ""), bases.get(b, "")), now)
                                for a, b in sorted(pending) if (a in group and a not in shown)
                                or (b in group and b not in shown)])
            if len(sheets) < 2 or not any(a in shown and b in shown for a, b in pending):
                continue
            order = [x.id for x in sheets]
            mine = store.bases(order)  # ce qu'il voit, avant qu'il n'en réunisse
            request = LLMRequest(role=ROLE, call_id=f"{ctx.run_id}#match:{order[0]}",
                                 system_stable=system(her),
                                 messages=(Message("user", ask(ctx, ctx.frame, sheets, her)),),
                                 max_tokens=OUTPUT_MAX, lane="background", priority=3, output_schema=MATCH_SCHEMA)
            response = await ctx.ask(request)
            if response is None:
                return  # une panne, un quota : pas compté, le passage suivant reprend
            made, calls = made + 1, calls + 1
            verdict = parse(response.text, len(order))
            if verdict is None:
                log.warning("réponse illisible du juge sur les fiches %s : rien ne change (%s)", order,
                            request.call_id)
            store.judged(JudgeCall(now, request.call_id, len(order), ok=verdict is not None),
                         verdicts(order, verdict, mine, now, request.call_id))
            if verdict is None:
                continue
            # pendant l'appel, une fiche a pu changer (une preuve, un lien) : son avis ne vaut plus, il se refera
            still = store.bases(order)
            for g in verdict.people:
                cards = [order[n - 1] for n in g.cards]
                if not g.sure or len(cards) < 2 or any(still.get(c) != mine.get(c) for c in cards):
                    continue
                keep = cards[0]
                for other in cards[1:]:
                    # réunies comme une preuve les réunirait ; refusée (séparées par toi, deux personnes de
                    # l'identité, un nom raconté face à quelqu'un qui lui parle), rien ne change
                    keep = store.unite(keep, other, reason=g.reason, call_id=request.call_id) or keep


__all__ = ["MATCH_SCHEMA", "ROLE", "Group", "Matching", "Verdict", "ask", "card", "groups", "parse", "system",
           "verdicts"]
