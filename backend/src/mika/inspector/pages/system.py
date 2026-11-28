"""Système : santé, appels de modèle, chronologie, état et faits,
contributions, journal d'exploitation, simulations, toutes les vues."""

from __future__ import annotations

import asyncio
import json
import re
import secrets as _secrets
import shlex
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from sqlalchemy import column, func, inspect, select
from sqlalchemy import table as sa_table
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from mika.adapters.llm.config import ROLE_LABELS
from mika.contracts import runtime as rt
from mika.inspector import names, render
from mika.inspector.catalog import Panel
from mika.inspector.pages.diagnostics import health_page
from mika.inspector.pages.runtime_diagnostics import anomaly_blocks, process_blocks, rebuildable, tainted_said
from mika.inspector.pages.tabs import TABS
from mika.inspector.ui import PREFIX, secure
from mika.kernel.clock import DAY, US
from mika.kernel.events import RETIRED_OWNER
from mika.kernel.facts import FactKey
from mika.kernel.faculty import (
    ActionSpec,
    CapabilitySpec,
    InspectSpec,
    ProcessSpec,
    ProposerSpec,
    SectionSpec,
    SubjectSpec,
    ToolSpec,
)
from mika.kernel.inspect import (
    Badge,
    Chart,
    Code,
    Column,
    Disclosure,
    Fields,
    Head,
    Nav,
    NavItem,
    Note,
    Pager,
    Param,
    Prose,
    Ref,
    Row,
    Series,
    Stat,
    Stats,
    Table,
    Text,
    When,
    agree,
    cursor_page,
    money_fr,
    num_fr,
    pct_fr,
    plural,
    read_params,
    short_day_fr,
    size_fr,
)
from mika.kernel.text import clipped, fold
from mika.ports.errors import describe_error
from mika.ports.journal import JournalContent, JournalEvent, JournalOutbox, JournalSnapshot
from mika.ports.llm import EFFORT_LABELS
from mika.runtime import health
from mika.runtime import operations as ops
from mika.runtime.boundary import Failed, acall, call
from mika.runtime.effects import OUTBOX_LABELS, OUTBOX_PROBLEMS, OUTBOX_SEEN_ONLY
from mika.vocab.episodes import OPTIONAL_ROLES, Role

#: le ton de chaque état d'une ligne de la file de sortie (ses états, leurs mots et ce qui est « à traiter » :
#: ``runtime/effects.py``, où ils s'écrivent)
OUTBOX_TONES = {"pending": "info", "running": "info", "done": "ok", "failed": "danger", "orphan": "warn",
                "stale": "warn", "interrupted": "warn", "seen": "muted"}
#: ce qui est « en route » : en attente ou en cours d'envoi
OUTBOX_ROUTE = ("pending", "running")
#: des départs par page, et des effets à traiter montrés avec leurs boutons (les plus récents) : la page dessinée
#: lit ces pages-là (``app/handmade/tabs/system.py::outbox``), la console en MCP aussi (ADR 0177)
OUTBOX_PAGE, OUTBOX_PROBLEMS_SHOWN = 20, 8
#: les titres de ses listes, que la page dessinée lit
OUTBOX_RECENT_TITLE, OUTBOX_TODO_TITLE, OUTBOX_KINDS_TITLE = "Effets", "À traiter", "Par sorte"
#: les sortes de départ qu'un récit distingue (``departure_sort``, ``departures``) : une parole, « une réponse qui ne
#: viendra pas », une action (proposée ou autorisée) ; tout autre effet n'a que son nom
SPEECH, ENDING, ACTION = "parole", "fin", "action"
#: ce qu'on montre d'une parole ou du résumé d'une action, sur une ligne
DEPARTURE_TEXT = 120
#: que faire d'un départ à traiter, par (état, sorte) ; « » : toute autre sorte (``guidance``)
OUTBOX_GUIDANCE: dict[tuple[str, str], str] = {
    ("failed", SPEECH): "Ce message n'est pas parti. Tu peux le relancer ou le marquer comme vu.",
    ("failed", ENDING): "Ses écrans n'ont pas appris qu'aucune réponse ne viendra. Tu peux relancer ce départ ou le "
                        "marquer comme vu.",
    ("failed", ACTION): "L'action a échoué. Tu peux la relancer ou la marquer comme vue.",
    ("failed", ""): "Ce départ a échoué. Tu peux le relancer ou le marquer comme vu.",
    ("orphan", SPEECH): "Aucun exécuteur ne l'a pris en charge : ce message n'est pas parti.",
    ("orphan", ACTION): "Aucun exécuteur ne l'a prise en charge.",
    ("orphan", ""): "Aucun exécuteur ne l'a pris en charge : rien n'est parti.",
    ("stale", SPEECH): "Ce message est périmé : elle ne le dira plus.",
    ("stale", ""): "Ce départ est périmé : il ne partira plus.",
    ("interrupted", ACTION): "Cette action a peut-être déjà eu lieu. Vérifie son résultat avant de la marquer comme "
                             "vue.",
    ("interrupted", ""): "Ce départ a peut-être déjà eu lieu. Vérifie son résultat avant de le marquer comme vu.",
}


def guidance(state: str, sort: str) -> str:
    """Que faire d'un départ à traiter : la consigne de son état pour sa sorte (« Ce message n'est pas parti… »),
    sinon celle de son état ; rien pour un départ qui n'est pas à traiter."""
    return OUTBOX_GUIDANCE.get((state, sort)) or OUTBOX_GUIDANCE.get((state, ""), "")


@dataclass(frozen=True, slots=True)
class Departure:
    """Ce qu'un départ fait partir, dit une seule fois (``departures``) pour la File de sortie (le panneau « À
    traiter », son tableau, que lit la page dessinée) et pour la page d'un événement (« Ses départs ») : sa sorte, le
    nom de son effet (``Names.effect``), l'action nommée (sa capacité), à qui (une parole, une réponse qui ne viendra
    pas), et ce qu'il dit — le début d'une parole entre guillemets (« texte oublié » si l'oubli l'a effacé), le résumé
    d'une action."""

    sort: str
    name: str
    action: str = ""
    to: str = ""
    text: str = ""

    @property
    def title(self) -> str:
        """Son nom, et l'action qu'il fait partir : « Une action que tu as autorisée : Envoyer un mail »."""
        return f"{self.name} : {self.action}" if self.action else self.name


def departure_sort(effect: str) -> str:
    """La sorte d'un départ, par son effet (« propriétaire:type ») : une parole (le type d'une parole, qui que ce soit
    qui la livre), une réponse qui ne viendra pas ou une action (du runtime) ; « » sinon."""
    owner, _, type_name = effect.partition(":")
    if type_name == rt.UTTERANCE.name:
        return SPEECH
    if owner == rt.OWNER and type_name == rt.EPISODE_ENDED.name:
        return ENDING
    if owner == rt.OWNER and type_name in (rt.EFFECT_PROPOSED.name, rt.EFFECT_RESOLVED.name):
        return ACTION
    return ""


def _line(content: Any) -> str | None:
    """Un texte gardé (un ``Content`` décodé), sur une ligne (``DEPARTURE_TEXT``) ; ``None`` si l'oubli l'a effacé ;
    rien sans texte."""
    if content is None:
        return ""
    text = getattr(content, "text", None)
    if text is None:
        return None if getattr(content, "ref", None) else ""
    return clipped(text, DEPARTURE_TEXT)


def departures(ui: Any, lines: Any, events: Any) -> dict[tuple[int, str], Departure]:
    """Le récit de chaque départ (``lines`` : des ``(seq, effet)``), lu dans les événements de la page (``events`` : le
    numéro vers l'événement gardé, relus d'un coup par ``store.get_events``). Seuls ceux d'une parole, d'une fin ou
    d'une action se décodent (leurs textes remplis) ; les propositions des actions autorisées, pour leur résumé, se
    relisent d'un seul coup aussi."""
    wanted = list(dict.fromkeys((int(seq), str(effect)) for seq, effect in lines))
    decoded = {seq: ui.decode(events[seq]) for seq in {s for s, e in wanted if departure_sort(e) and s in events}}
    asked = {int(ev.data.proposal) for ev in decoded.values() if ev.type.name == rt.EFFECT_RESOLVED.name}
    proposals = {ev.seq: ui.decode(ev) for ev in ui.kernel.mind.store.get_events(sorted(asked))} if asked else {}
    out: dict[tuple[int, str], Departure] = {}
    for seq, effect in wanted:
        sort, name, ev = departure_sort(effect), ui.names.effect(effect).name, decoded.get(seq)
        if ev is None:
            out[(seq, effect)] = Departure(sort, name)
        elif sort == SPEECH:
            said = _line(getattr(ev.data, "text", None))
            out[(seq, effect)] = Departure(sort, name, to=ui.names.who(getattr(ev.data, "target", None)),
                                           text="texte oublié" if said is None else f"« {said} »" if said else "")
        elif sort == ENDING:
            out[(seq, effect)] = Departure(sort, name, to=ui.names.who(getattr(ev.data, "target", None)))
        else:
            capability = str(getattr(ev.data, "capability", "") or "")
            proposed = ev if ev.type.name == rt.EFFECT_PROPOSED.name else proposals.get(int(ev.data.proposal))
            said = _line(getattr(proposed.data, "summary", None) if proposed is not None else None)
            out[(seq, effect)] = Departure(sort, name, ui.names.capability(capability) if capability else "",
                                           text="résumé oublié" if said is None else said)
    return out


#: les pages de Système qui lisent le journal ou une table, par page
PAGE = 50
REPORT_NAME = re.compile(r"^[\w.-]{1,120}\.(md|html|json|txt)$")
REPORT_MAX = 400_000


def _names(items: Any) -> str:
    return ", ".join(sorted(items)) or "—"


@TABS.tab("systeme.sante", title="Santé générale", group="Surveiller", badge=lambda ui: sum(
    1 for c in health.report(ui.kernel).checks if c.state != health.OK),
          description="Repérer les problèmes de fonctionnement et retrouver le diagnostic utile pour chacun.")
async def sante(ui: Any, request: Request) -> Any:
    # l'état des sauvegardes, pour sa tuile : ``diagnostics`` ne peut pas lire ce module, qui l'importe
    return health_page(ui, backup_state(ui))


#: la période d'Appels et coûts, ses mots : un bouton à choix au bout de la barre d'onglets, 14 jours posé (ADR 0176 :
#: un petit choix toujours posé, appliqué d'un clic). Elle vaut pour toute la page — ses chiffres, son graphe, où va le
#: coût, le détail jour par jour —, sauf la liste de tous les appels, paginée sans période (audit du 2026-11-05,
#: C8-13) ; le registre en garde trente (``adapters/llm/calls.py``, ``KEEP_DAYS``)
CALL_PERIODS = {"7": "7 jours", "14": "14 jours", "30": "30 jours"}
CALL_PERIOD = Param("periode", "période", kind="select", default="14", choices=tuple(CALL_PERIODS.items()))
#: les titres des blocs d'Appels et coûts que lit sa page dessinée (``app/handmade/tabs/system.py``), par préfixe :
#: le graphe porte la période (``since`` : le premier jour entamé, ``until`` : aujourd'hui) et le coût de chaque
#: jour ; les tableaux, leurs agrégats (leur clé en colonne repliée, « jour (clé) », « rôle (clé) ») — un seul calcul,
#: celui de la vue (audit du 2026-11-05, C8-05)
CALLS_CHART_TITLE = "Coût par jour"
CALLS_DAYS_TITLE = "Par jour"
CALLS_ROLES_TITLE = "Par rôle"
CALLS_BACKENDS_TITLE = "Par fournisseur"
CALLS_MODELS_TITLE = "Par modèle"
CALLS_ALL_TITLE = "Tous les appels"


def call_period(query: Mapping[str, str]) -> tuple[int, str]:
    """La période choisie d'Appels et coûts (``CALL_PERIOD``) : son nombre de jours et ses mots (« 14 jours ») ; une
    valeur inconnue retombe sur le défaut. La vue la lit pour ses requêtes et ses titres, la page dessinée pour ses
    seuls mots : ses jours sont ceux du graphe de la vue."""
    values, _ = read_params((CALL_PERIOD,), query)
    key = str(values[CALL_PERIOD.name] or CALL_PERIOD.default)
    return int(key), CALL_PERIODS[key]


@TABS.tab("systeme.appels", title="Appels et coûts", group="Surveiller",
          description="Chaque appel de modèle : combien, par qui, pour combien, combien de temps, avec quelle part "
                      "de cache (30 jours gardés).")
async def appels(ui: Any, request: Request) -> Any:
    """Système › Appels et coûts : sur la période choisie (``CALL_PERIOD``), ses chiffres, le coût par jour (une barre
    par jour, le premier jour entamé compris), où va le coût (par jour, par rôle, par fournisseur, par modèle) ; puis
    tous les appels, paginés sans période. Chaque agrégat se calcule ici, une fois : la page dessinée les lit."""
    calls = ui.deps.calls
    now = ui.now()

    def day_of(at: int) -> str:
        return datetime.fromtimestamp(at / US, ui.tz).strftime("%Y-%m-%d")

    def stamp(key: str) -> int:
        return int(datetime.strptime(key, "%Y-%m-%d").replace(tzinfo=ui.tz).timestamp() * US)

    if calls is None:
        return [Note("Le registre des appels n'est pas branché : seuls les derniers appels en mémoire comptent.",
                     "muted")]
    period, words = call_period(request.query_params)
    since = now - period * DAY
    days = calls.usage(since, by="day", day_of=day_of)
    roles = calls.usage(since, by="role")
    backends = calls.usage(since, by="backend")
    models = calls.usage(since, by="model")
    total_cost = sum(u.cost_usd for u in days)
    today = next((u for u in days if u.key == day_of(now)), None)
    out: list[Any] = [Stats((
        Stat("Aujourd'hui", today.calls if today else 0, money_fr(today.cost_usd) if today else money_fr(0.0)),
        Stat(words, sum(u.calls for u in days), money_fr(total_cost)),
        Stat(f"Échecs ({words})", sum(u.failures for u in days), "",
             "danger" if any(u.failures for u in days) else ""),
        Stat(f"Part du cache ({words})", pct_fr(_cache(roles)), "entrée lue depuis le cache"),
    ))]
    # chaque jour de la période, du premier entamé à aujourd'hui, même sans appel : ``since`` et ``until``
    out.append(Chart((Series("coût", tuple((stamp(u.key), u.cost_usd) for u in days), 2),), kind="bars",
                     title=f"{CALLS_CHART_TITLE} ({words})", unit="$", since=stamp(day_of(since)),
                     until=stamp(day_of(now)), empty=f"aucun appel ces {words}"))

    def day_label(key: str) -> str:
        d = datetime.strptime(key, "%Y-%m-%d").replace(tzinfo=ui.tz)
        return short_day_fr(d)

    def usage_table(rows: list[Any], label: str, title: str, show: Any = None) -> Table:
        # un agrégat dit par d'autres mots que sa clé (un jour, un rôle) la garde en colonne repliée
        keyed = (Column(f"{label} (clé)", detail=True),) if show is not None else ()
        return Table((label, Column("appels", "num"), Column("échecs", "num"), Column("entrée", "num", detail=True),
                      Column("sortie", "num", detail=True), Column("cache lu", "num", detail=True),
                      Column("part du cache", "num", detail=True), Column("coût", "num"), Column("durée moy.", "num"),
                      *keyed),
                     tuple(Row((show(u.key) if show is not None else u.key, u.calls, u.failures,
                                num_fr(u.input_tokens), num_fr(u.output_tokens), num_fr(u.cache_read),
                                pct_fr(u.cache_ratio), money_fr(u.cost_usd), f"{num_fr(u.latency_avg_s, 1)} s",
                                *((u.key,) if keyed else ())), tone="danger" if u.failures else "")
                           for u in rows), title=f"{title} ({words})", empty="aucun appel")

    breakdown = [usage_table(list(reversed(days)), "jour", CALLS_DAYS_TITLE, day_label),
                 usage_table(roles, "rôle", CALLS_ROLES_TITLE, names.role),
                 usage_table(backends, "fournisseur", CALLS_BACKENDS_TITLE),
                 usage_table(models, "fournisseur · modèle", CALLS_MODELS_TITLE)]
    ctx = ui.inspection.context(request.query_params)
    pager = ctx.pager("page", size=PAGE, total=calls.count())
    recent = calls.recent(pager.size, offset=pager.offset)
    corr_of = {id(t): getattr(t, "correlation", "") or t.call_id.split("#")[0] for t in recent}
    episodes = _episode_correlations(ui, set(corr_of.values()))
    out.append(Table((Column("quand", "fit"), "rôle", "fournisseur", Column("modèle", detail=True),
                      Column("attente", "num", detail=True), Column("durée", "num"), Column("jetons", "num", detail=True),
                      Column("coût", "num"), "issue"), tuple(
        Row((When(t.at), names.role(t.role), t.backend, Text(t.model, "mono"), f"{num_fr(t.wait_us / 1e6, 1)} s",
             f"{num_fr(t.latency_us / 1e6, 1)} s", f"{num_fr(t.input_tokens)} → {num_fr(t.output_tokens)}",
             money_fr(t.cost_usd),
             Badge("réussi" if t.outcome == "ok" else names.detail(t.outcome), "ok" if t.outcome == "ok" else "danger")),
            href=Ref("episode", corr_of[id(t)], "") if corr_of[id(t)] in episodes else None) for t in recent),
        title=f"{CALLS_ALL_TITLE}, du plus récent", empty="aucun appel", pager=pager))
    out.append(Disclosure(f"Répartition des appels et des coûts ({words})", tuple(breakdown)))
    return {"blocks": out, "filters": (CALL_PERIOD,)}


def _cache(rows: list[Any]) -> float:
    read = sum(u.cache_read for u in rows)
    total = sum(u.input_tokens + u.cache_read + u.cache_write for u in rows)
    return read / total if total else 0.0


TIMELINE_PARAMS = (Param("type", "type d'événement", placeholder="memory., episode.utterance…"),
                   Param("correlation", "corrélation", placeholder="un épisode, une action"))


@TABS.tab("systeme.chronologie", title="Journal d’événements", group="Journaux",
          description="Le journal d'événements, du plus récent : tout ce qui lui est arrivé, filtrable par type ou "
                      "par épisode.")
async def chronologie(ui: Any, request: Request) -> Any:
    kernel = ui.kernel
    values, _ = read_params(TIMELINE_PARAMS, request.query_params)
    ctx = ui.inspection.context(request.query_params)
    before = ctx.int_param("avant", 0) or None
    # un type commence par ce qu'on tape, en minuscules (tous les types le sont) : un préfixe comparé tel quel, pareil
    # sur les deux moteurs (``LIKE`` ignore la casse sous SQLite, pas sous MariaDB)
    kind = str(values["type"] or "")[:80].lower()
    corr = str(values["correlation"] or "")[:160]
    query = select(JournalEvent.seq)
    if kind:
        query = query.where(func.substr(JournalEvent.type, 1, len(kind)) == kind)
    if corr:
        query = query.where(JournalEvent.correlation == corr)
    if before:
        query = query.where(JournalEvent.seq < before)
    seqs = [int(r[0]) for r in kernel.mind.store.query_mind(
        query.order_by(JournalEvent.seq.desc()).limit(CHRONOLOGY_PAGE + 1))]
    found = sorted((ui.decode(s) for s in kernel.mind.store.get_events(seqs)), key=lambda e: -e.seq)
    events, pager = cursor_page(found, CHRONOLOGY_PAGE, current=before or 0)
    episodes = _episode_correlations(ui, {e.correlation for e in events})
    rows = tuple(Row((When(e.at), _what_happened(ui, e), _correlation_cell(e.correlation, episodes),
                      _faculty_cell(ui, e), Ref("event", str(e.seq), f"n° {e.seq}"), Text(e.type.name, "mono"),
                      Text(e.correlation, "mono")),
                     href=Ref("event", str(e.seq), ""), detail=(Code(ui.show(e, 4000), "Données"),))
                 for e in events)
    notes = [Note(f"Les événements de « {corr[:80]} » : ce n'est pas un épisode (un geste audité, un effet, "
                  "un processus).", "info")] if corr and corr not in episodes and events else []
    return {"blocks": [*notes, Table((Column("quand", "fit"), Column("ce qui s'est passé", role="title"), "lié à",
                                      Column("faculté", detail=True), Column("événement", detail=True),
                                      Column("type", detail=True),
                                      Column("corrélation", detail=True)), rows,
                                     title="Le journal", empty="Rien ne correspond.", pager=pager,
                                     layout="list", link_label="Ouvrir l’événement")],
            "filters": TIMELINE_PARAMS}


#: la chronologie, par page : deux colonnes de vingt sur un écran large (ADR 0176)
CHRONOLOGY_PAGE = 40


def _episode_correlations(ui: Any, correlations: set[str]) -> set[str]:
    """Parmi ces corrélations, celles d'un épisode (un début ou une fin au journal)."""
    corrs = sorted(c for c in correlations if c)[:500]
    if not corrs:
        return set()
    rows = ui.kernel.mind.store.query_mind(
        select(JournalEvent.correlation).distinct()
        .where(JournalEvent.type.in_([rt.EPISODE_STARTED.name, rt.EPISODE_ENDED.name]),
               JournalEvent.correlation.in_(corrs)))
    return {str(r[0]) for r in rows}


def _what_happened(ui: Any, e: Any) -> Text:
    """Ce qui s'est passé : le nom de son type, son type au survol. Un geste audité dit lequel et qui l'a fait — le
    journal en garde beaucoup, qui se suivent (C8-08) : la console en MCP et le repli le disent comme la page."""
    said = ui.names.event(e.type.name)
    if e.type.name == rt.OPERATED.name and isinstance(e.data, rt.Operated):
        said = f"{said} : {ui.names.action(e.data.action)}, par {ui.names.who(e.data.by)}"
    return Text(said, hint=e.type.name)


def _faculty_cell(ui: Any, e: Any) -> Text:
    """La faculté qui possède son type (son propriétaire au registre), son nom en mots, sa clé au survol ; un type que
    plus personne ne déclare, celle de son préfixe. La page dessinée en nomme les familles de la page."""
    owner = e.type.owner if e.type.owner != RETIRED_OWNER else e.type.name.partition(".")[0]
    return Text(ui.names.faculty(owner), hint=owner)


def _correlation_cell(corr: str, episodes: set[str]) -> Any:
    """Un épisode mène à sa page ; le reste (un geste audité — fait depuis la console ou depuis l'espace d'une
    personne, ADR 0203 —, un effet) à ses événements. La clé ``opérateur:…`` reste celle que le journal garde."""
    if corr in episodes:
        return Ref("episode", corr, "un épisode")
    if corr.startswith("opérateur:"):
        label = "un geste audité"
    elif corr.startswith("effet:"):
        label = "un effet"
    else:
        label = "les événements liés"
    return Ref("local", f"{PREFIX}/systeme/chronologie", label, (("correlation", corr),))


@TABS.tab("systeme.etat", title="Diagnostic avancé", group="Anatomie",
          description="Les faits que les facultés se partagent, lus maintenant, et l'état brut de chaque tranche.")
async def etat(ui: Any, request: Request) -> list[Any]:
    kernel = ui.kernel
    frame = kernel.mind.frame()
    root = kernel.mind.root
    values = fact_values(kernel, frame)
    rows = []
    for name, spec in sorted(kernel.registry.providers.items()):
        value = values.get(name, "famille : dépend de son argument")
        rows.append((Text(name, "mono"), spec.owner, Text(getattr(spec.key, "doc", ""), "muted"),
                     Text(value[:600], "mono", clamp=200)))
    tainted = dict(root.tainted.items())
    out: list[Any] = []
    if tainted:
        out.append(Note(tainted_said(tainted), "danger"))
    out.append(Table(("fait", "fourni par", "sens", "valeur"), tuple(rows), title="Faits (lus maintenant)"))
    out.append(Disclosure("Tranches", tuple(
        Disclosure(f"{owner} · modifiée au n° {root.changed.get(owner, 0)}", (Code(repr(root.slices[owner])[:8000]),))
        for owner in root.slices)))
    return out


def fact_values(kernel: Any, frame: Any) -> dict[str, str]:
    """Les faits non familiaux lus dans ce cadre, en texte (une erreur dite comme telle) ; une famille dépend
    de son argument et ne se lit pas seule."""
    out = {}
    for name, spec in sorted(kernel.registry.providers.items()):
        if isinstance(spec.key, FactKey):
            got = call(frame.get, spec.key, label=f"fait {name}")
            out[name] = f"(erreur : {describe_error(got.error)})" if isinstance(got, Failed) else repr(got)
    return out


def facts_diff(kernel: Any, before: Any, after: Any) -> Table:
    """Les faits non familiaux dont la valeur change d'un cadre à l'autre (la lecture du « Diagnostic avancé », en
    différence) : deux cadres du même instant, l'un avec les paramètres en vigueur, l'autre avec d'autres."""
    old, new = fact_values(kernel, before), fact_values(kernel, after)
    providers = kernel.registry.providers
    rows = tuple((Text(name, "mono"), providers[name].owner, Text(getattr(providers[name].key, "doc", ""), "muted"),
                  Text(old[name][:600], "mono", clamp=200), Text(new.get(name, "—")[:600], "mono", clamp=200))
                 for name in old if old[name] != new.get(name))
    return Table(("fait", "fourni par", Column("sens", detail=True), "avant", "après"), rows,
                 title="Ce qu'elle se dirait", empty="Aucun fait partagé entre ses facultés ne change à cet instant.",
                 caption="Les faits que ses facultés se partagent (Système › Diagnostic avancé), lus au même instant "
                         "avec les paramètres en vigueur, puis avec les valeurs tapées.")


@dataclass(frozen=True, slots=True)
class SharedFact:
    """Un fait qu'une faculté fournit, et les autres facultés qui le lisent (leurs noms techniques, triés)."""
    key: FactKey
    readers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Contribution:
    """Ce qu'une faculté apporte (Système › Contributions), en listes et en noms techniques : sa vue les joint en
    texte, la page dessinée (``app/handmade/tabs/system.py``) y ajoute ses mots et ses indices. Chaque liste est
    triée par son nom technique (un titre, un libellé), sauf ses faits, ses sections et ses preuves, dans l'ordre
    déclaré."""
    owner: str
    #: les types de ses événements publics, que les autres peuvent écouter
    publishes: tuple[str, ...]
    #: les types des autres qu'elle réduit
    listens: tuple[str, ...]
    #: les formes de signal qu'elle réduit (le nom de leur classe)
    shapes: tuple[str, ...]
    facts: tuple[SharedFact, ...]
    sections: tuple[SectionSpec, ...]
    #: ce qu'elle propose à l'arbitre (``reasons`` : chaque raison et ses bornes)
    proposers: tuple[ProposerSpec, ...]
    #: ses processus de fond, ceux de l'ordonnanceur
    processes: tuple[ProcessSpec, ...]
    tools: tuple[ToolSpec, ...]
    capabilities: tuple[CapabilitySpec, ...]
    views: tuple[InspectSpec, ...]
    subjects: tuple[SubjectSpec, ...]
    actions: tuple[ActionSpec, ...]


def contributions_of(kernel: Any) -> list[Contribution]:
    """Ce que chaque faculté apporte, dans l'ordre du registre : la seule lecture du registre de Système ›
    Contributions, que sa vue et sa page dessinée partagent (la page a besoin de listes que la vue ne dit qu'en
    texte). Ses processus sont ceux de l'ordonnanceur (``scheduler.specs``), rangés par propriétaire, comme Système ›
    Processus les compte : ceux que le noyau y ajoute hors du registre (l'arbitre, le relevé des courbes) vont au
    « Noyau »."""
    reg = kernel.registry
    processes: dict[str, list[ProcessSpec]] = defaultdict(list)
    for spec in kernel.scheduler.specs:
        processes[spec.owner].append(spec)
    readers: dict[str, set[str]] = defaultdict(set)
    for f in reg.faculties.values():
        for s in [*f.reducers, *f.facts, *f.sections, *f.enrichers, *f.proposers, *f.modulators,
                  *processes.get(f.name, ()), *f.appraisals]:
            for r in getattr(s, "reads", ()):
                readers[r].add(f.name)
    out = []
    for f in reg.faculties.values():
        own = set(f.events)
        out.append(Contribution(
            owner=f.name,
            publishes=tuple(sorted(n for n, t in f.events.items() if t.public)),
            listens=tuple(sorted({t.name for s in f.reducers for t in s.types if t.name not in own})),
            shapes=tuple(sorted({sh.__name__ for s in f.reducers for sh in s.shapes})),
            facts=tuple(SharedFact(s.key, tuple(sorted(readers.get(s.key.name, set()) - {f.name})))
                        for s in f.facts),
            sections=tuple(f.sections),
            proposers=tuple(f.proposers),
            processes=tuple(sorted(processes.get(f.name, ()), key=lambda s: s.name)),
            tools=tuple(sorted(f.tools, key=lambda s: s.name)),
            capabilities=tuple(sorted(f.capabilities, key=lambda s: s.name)),
            views=tuple(sorted(f.inspectors, key=lambda v: v.title)),
            subjects=tuple(sorted(f.subjects, key=lambda s: s.label)),
            actions=tuple(sorted(f.actions, key=lambda a: a.title)),
        ))
    return out


@TABS.tab("systeme.contributions", title="Contributions", group="Anatomie",
          description="Ce que chaque faculté apporte, lu dans le registre et à l'ordonnanceur : événements, faits, "
                      "sections, preuves, processus, outils, vues.")
async def contributions(ui: Any, request: Request) -> list[Any]:
    """Une faculté par repli, ce qu'elle apporte en texte : ce que lit ``contributions_of``, joint."""
    out: list[Any] = [Note("Ce que chaque faculté apporte, lu dans le registre ; ses processus, à l'ordonnanceur, comme "
                           "Système › Processus. Elles ne se connaissent pas : elles lisent les faits et les événements "
                           "publics des autres.", "muted")]
    for c in contributions_of(ui.kernel):
        pairs = [
            ("publie", _names(c.publishes)),
            ("écoute", _names([*c.listens, *(f"forme {n}" for n in c.shapes)])),
            ("fournit", "\n".join(f"{x.key.name} → {_names(x.readers)}" for x in c.facts) or "—"),
            ("sections", "\n".join(f"{s.key} ({s.zone.value})" for s in c.sections) or "—"),
            ("preuves", "\n".join(", ".join(f"{r} [{num_fr(lo)} ; {num_fr(hi)}]" for r, (lo, hi) in s.reasons.items())
                                  for s in c.proposers) or "—"),
            ("processus", _names(s.name for s in c.processes)),
            ("outils", _names(s.name for s in c.tools)),
            ("capacités", _names(s.name for s in c.capabilities)),
            ("vues", _names(ui.named(v.title) for v in c.views)),
            ("fiches", _names(s.label for s in c.subjects)),
            ("actions", _names(a.title for a in c.actions)),
        ]
        label = ui.names.faculty(c.owner)
        out.append(Disclosure(label if label == c.owner else f"{label} ({c.owner})",
                              (Fields(tuple((k, Text(v, "mono") if "\n" in v else v) for k, v in pairs)),)))
    return out


#: d'où vient un geste, en bouton à choix au bout de la barre d'onglets (ADR 0176 : quatre choix au plus, toujours
#: posé)
ORIGIN_PARAM = Param("depuis", "depuis", kind="select", default="tout", choices=(("tout", "tout"),
                                                                                 *names.ORIGINS.items()))


@TABS.tab("systeme.operations", title="Gestes audités", group="Journaux",
          description="Ce que les opérateurs ont fait dans la console, et chacun depuis son espace : le geste, qui, "
                      "d'où, sur quoi, l'issue (jamais un contenu).")
async def operations(ui: Any, request: Request) -> Any:
    ctx = ui.inspection.context(request.query_params)
    values, _ = read_params((ORIGIN_PARAM,), request.query_params)
    wanted = str(values["depuis"] or "")
    operators = operator_handles(ui)

    def origin(e: Any) -> str:
        return gesture_origin(e.data.action, e.data.by, operators)

    if wanted in names.ORIGINS:
        done, pager = _older_where(ctx, [rt.OPERATED], OPERATIONS_PAGE, lambda e: origin(e) == wanted)
    else:
        done, pager = ctx.older([rt.OPERATED], OPERATIONS_PAGE)
    rows = tuple(operation_row(ui, e, origin(e)) for e in done)
    empty = f"Aucun geste depuis {names.ORIGINS[wanted]}." if wanted in names.ORIGINS else "Aucun geste audité encore."
    return {"blocks": [Table((Column("quand", "fit"), "action", "par", "depuis", "sur", "issue",
                              Column("action (clé)", detail=True), Column("sur (clé)", detail=True),
                              Column("événements", detail=True)), rows,
                             title=OPERATIONS_TITLE, empty=empty, pager=pager)],
            "filters": (ORIGIN_PARAM,)}


#: les gestes audités, par page ; le titre de leur tableau (la page dessinée le lit, ``app/handmade/tabs/system.py``)
OPERATIONS_PAGE = 100
OPERATIONS_TITLE = "Gestes audités"
#: un filtre que le journal ne sait pas dire (d'où vient un geste) se lit par lots du plus récent, au plus tant
#: d'événements par page
SCAN_BATCH, SCAN_MAX = 200, 2000


def operator_handles(ui: Any) -> frozenset[str]:
    """Les adresses des opérateurs (``user_N``) : la console n'est qu'à eux (vide si les comptes ne se lisent pas)."""
    got = call(ui.deps.accounts.all, label="comptes des opérateurs")
    return frozenset() if isinstance(got, Failed) else frozenset(a.handle for a in got if a.operator)


def gesture_origin(action: str, by: str, operators: frozenset[str]) -> str:
    """D'où vient un geste : ce que dit sa clé (``operations.origin``) ; une action déclarée sous sa clé nue, la console
    si c'est un opérateur qui l'a faite (elle n'est qu'à eux), sinon l'espace de la personne."""
    return ops.origin(action, by) or (ops.CONSOLE if by in operators else ops.SPACE)


def _older_where(ctx: Any, types: list[Any], size: int, keep: Any) -> tuple[list[Any], Pager]:
    """Une page du journal à curseur, réduite à ce que garde ``keep`` : lue par lots du plus récent, jusqu'à une page et
    une ligne de plus, ou ``SCAN_MAX`` événements lus — « Plus anciens » reprend alors après le dernier lu."""
    current = ctx.int_param("avant", 0)
    cursor: int | None = current or None
    found: list[Any] = []
    read, exhausted = 0, False
    while len(found) <= size and read < SCAN_MAX:
        batch = ctx.events(types, SCAN_BATCH, before=cursor)
        read += len(batch)
        found.extend(e for e in batch if keep(e))
        if len(batch) < SCAN_BATCH:
            exhausted = True
            break
        cursor = batch[-1].seq
    if len(found) > size or exhausted:
        return cursor_page(found, size, current=current)
    return found, Pager(param="avant", size=size, older=(("avant", str(cursor)),))


def operation_row(ui: Any, e: Any, origin: str) -> Row:
    """Un geste audité : son titre, qui (un nom), d'où, sur quoi (un nom), l'issue en mots ; les clés au détail. Sur quoi
    ne mène qu'à une fiche qui s'ouvre, sous le titre de sa fiche (``on_title`` : « Pièce reçue « facture.pdf » »,
    jamais son identifiant, C8-07) — sous sa clé si son en-tête a échoué. Le journal garde des objets retirés depuis,
    et des sortes que la console donne à autre chose (un compte de connexion sous « compte », dont les fiches sont des
    boîtes) : ceux-là restent du texte, leur clé. Une tranche ou un processus (les gestes de Système) se dit par son
    nom, sans lien. La clé de l'objet reste au détail (« sur (clé) »), que la page dessinée montre au survol."""
    label, tone = names.OPERATED.get(e.data.outcome, (e.data.outcome, ""))
    subject, kind = e.data.subject or "", e.data.subject_kind or ""
    on: Any = "—"
    spec = ui.inspection.subject(kind) if kind else None
    head = ui.inspection.head(kind, subject) if subject and spec is not None and kind not in ("person", "handle") \
        else None
    if subject and kind in ("person", "handle"):
        on = ui.names.who_cell(subject)
    elif spec is not None and isinstance(head, Head):
        on = Ref.subject(kind, subject, on_title(spec.label, head.title, subject))
    elif spec is not None and head is not None:  # son en-tête a échoué : sa fiche s'ouvre et dit pourquoi
        on = Ref.subject(kind, subject, f"{spec.label} {subject}")
    elif subject and not kind and ui.names.name_of(subject):
        # une action qui ne déclare pas d'objet, faite depuis la fiche d'une personne (supprimer un de ses voyages,
        # ADR 0204) : la personne par son nom, pas sa clé (C9-01)
        on = ui.names.who_cell(subject)
    elif subject and kind in ("tranche", "processus"):
        # les gestes de Système (ADR 0234) : une tranche par le nom de sa faculté, un processus par le sien
        on = Text(ui.names.faculty(subject) if kind == "tranche" else ui.names.process(subject), hint=subject)
    elif subject:
        on = Text(subject, hint=kind)
    return Row((When(e.at), ui.names.action(e.data.action), ui.names.who(e.data.by),
                names.ORIGINS.get(origin, origin), on, Badge(label, tone), Text(e.data.action, "mono"),
                Text(subject, "mono", hint=kind) if subject else "—",
                ", ".join(str(s) for s in e.data.seqs) or "—"),
               href=Ref("event", str(e.seq), ""))


#: le titre d'une fiche, au plus, dans « sur quoi » d'un geste audité
ON_TITLE_MAX = 80


def on_title(label: str, title: str, key: str) -> str:
    """Sur quoi porte un geste, sous le titre de sa fiche : sa sorte puis son titre (« Pièce reçue « facture.pdf » »),
    le titre seul s'il dit déjà sa sorte (« Projet Atlas » pour un projet) ; un titre vide, sa sorte et sa clé."""
    said = clipped(title, ON_TITLE_MAX)
    if not said:
        return f"{label} {key}"
    folded, kind = fold(said), fold(label)
    return said if folded == kind or folded.startswith(f"{kind} ") else f"{label} « {said} »"


@TABS.tab("systeme.simulations", title="Simulations", group="Anatomie",
          description="Les rapports de simulation (« mika sim run --report »).")
async def simulations(ui: Any, request: Request) -> list[Any]:
    folder = ui.deps.reports
    if folder is None or not folder.is_dir():
        return [Note("Aucun dossier de rapports (lance le serveur avec --reports DOSSIER, et "
                     "« mika sim run --report DOSSIER »).", "muted")]
    files = sorted((f for f in folder.rglob("*") if f.is_file() and REPORT_NAME.match(f.name)),
                   key=lambda f: f.stat().st_mtime, reverse=True)
    chosen = request.query_params.get("fichier", "")
    out: list[Any] = [Table(("fichier", "modifié"), tuple(
        (Ref("local", f"{PREFIX}/systeme/simulations?fichier={_q(str(f.relative_to(folder)))}",
             str(f.relative_to(folder))), When(int(f.stat().st_mtime * US))) for f in files),
        title="Rapports", empty="aucun rapport")]
    if chosen:
        match = next((f for f in files if str(f.relative_to(folder)) == chosen), None)
        out.append(Prose(match.read_text(encoding="utf-8", errors="replace")[:REPORT_MAX], chosen) if match
                   else Note("Fichier inconnu.", "warn"))
    return out


def _q(text: str) -> str:
    return quote(text, safe="")


@TABS.tab("systeme.vues", title="Toutes les vues", group="Anatomie",
          description="Chaque vue que les facultés déclarent, et où elle est rangée.")
async def all_views(ui: Any, request: Request) -> list[Any]:
    rows = tuple((Ref.view(v.owner, v.name, v.title), Text(ui.names.faculty(v.owner), hint=v.owner),
                  v.section or "—", v.subject or "—",
                  Badge("cachée", "muted") if v.hidden else "—") for v in ui.inspection.views())
    return [Table(("vue", "faculté", "destination", "fiche", ""), rows, title="Ce que chaque faculté montre d'elle")]


@TABS.tab("systeme.processus", title="Processus", group="Surveiller",
          badge=lambda ui: _failing(ui),
          description="Ses processus de fond (relire la mémoire, dormir, relever le courrier…) : combien de passages, "
                      "d'échecs, la dernière erreur — et les échecs gardés au journal, qui survivent au redémarrage.")
async def processus(ui: Any, request: Request) -> list[Any]:
    return process_blocks(ui, request.query_params)


@TABS.tab("systeme.anomalies", title="Anomalies", group="Surveiller",
          badge=lambda ui: _anomalies(ui),
          description="Ce qui s'est mal passé sans tout arrêter : une évaluation, une réduction, un choix de l'arbitre ; et "
                      "les traces du journal (épisode supplanté, oubli, reconstruction). En mémoire depuis le "
                      "démarrage.")
async def anomalies(ui: Any, request: Request) -> list[Any]:
    return anomaly_blocks(ui)


@TABS.tab("systeme.sorties", title="File de sortie", group="Surveiller",
          badge=lambda ui: _outbox_problems(ui),
          description="Ce qui part d'elle vers les écrans et les services — ses messages, ce que montrent ses "
                      "écrans, ses actions (un mail, une réponse Teams…) — après son écriture au journal. Ce qui n'a "
                      "pas pu partir t'attend ici.")
async def sorties(ui: Any, request: Request) -> Any:
    """La file de sortie, d'un seul calcul : ses comptes par état et par sorte (une lecture groupée), une page de
    départs, les effets à traiter — chacun dit ce qu'il fait partir et à qui (``departures``), et que faire pour sa
    sorte (``guidance``) —, et les événements qui les ont fait partir. La page dessinée lit ces blocs-là, sans rien
    relire (ADR 0177) ; ce qui n'est que pour elle (par sorte, les lignes à traiter) est replié."""
    store = ui.kernel.mind.store
    o = JournalOutbox
    counts: dict[str, int] = defaultdict(int)
    kinds: dict[str, dict[str, Any]] = {}
    for effect, st, n, last in store.query_mind(select(o.effect, o.status, func.count(), func.max(o.seq))
                                                .group_by(o.effect, o.status)):
        counts[st] += int(n)
        kind = kinds.setdefault(effect, {"by": defaultdict(int), "last": 0})
        kind["by"][st] += int(n)
        kind["last"] = max(kind["last"], int(last or 0))
    ctx = ui.inspection.context(request.query_params)
    status = request.query_params.get("etat", "")[:40]
    labels = OUTBOX_LABELS
    invalid = bool(status and status not in labels and status not in counts)
    if invalid:
        status = ""
    where = (o.status == status,) if status else ()
    total = counts.get(status, 0) if status else sum(counts.values())
    pager = ctx.pager("page", size=OUTBOX_PAGE, total=total)
    # départagés par la clé : un événement fait partir plusieurs effets (la même page sur les deux moteurs)
    rows = store.query_mind(select(o.key, o.seq, o.effect, o.status, o.attempts, o.last_error).where(*where)
                            .order_by(o.seq.desc(), o.key).limit(pager.size).offset(pager.offset))
    # « à traiter » suit le filtre : un état à traiter, lui seul ; un autre état, rien ; aucun, tous
    selected_problems = (status,) if status in OUTBOX_PROBLEMS else OUTBOX_PROBLEMS if not status else ()
    problem_total = sum(counts.get(st, 0) for st in selected_problems)
    problem_page = ctx.pager("page_problemes", size=OUTBOX_PROBLEMS_SHOWN, total=problem_total)
    stuck = store.query_mind(select(o.key, o.seq, o.effect, o.status, o.last_error)
                             .where(o.status.in_(selected_problems))
                             .order_by(o.seq.desc(), o.key).limit(problem_page.size).offset(problem_page.offset)) \
        if problem_total else []
    seqs = {r[1] for r in rows} | {r[1] for r in stuck} | {k["last"] for k in kinds.values() if k["last"]}
    events = {ev.seq: ev for ev in store.get_events(seqs)} if seqs else {}
    # ce que chaque départ à traiter fait partir, et à qui : dit une fois, pour le panneau et son tableau
    told = departures(ui, ((seq, effect) for _key, seq, effect, _st, _err in stuck), events)

    def when(seq: int) -> Any:
        ev = events.get(seq)
        return When(ev.at) if ev is not None else "—"

    def action(seq: int, effect: str) -> Any:
        said = _action(ui, events[seq]) if seq in events and effect.startswith("runtime:effect.") else ""
        return Text(said) if said else "—"

    tones = OUTBOX_TONES
    chips = tuple(NavItem(f"{labels.get(k, k)}", Ref("local", f"{PREFIX}/systeme/sorties", k, (("etat", k),)),
                          count=n, active=k == status, tone=tones.get(k, "")) for k, n in sorted(counts.items()))
    back = request.url.path + (f"?{urlencode(_without(request.query_params, 'flash'))}"
                               if _without(request.query_params, "flash") else "")
    problems = [outbox_card(key, seq, told[(seq, effect)], st, err) for key, seq, effect, st, err in stuck]
    panel = Panel("handmade/systeme/a-traiter.html", {"problems": problems, "back": back,
                                  "problem_total": problem_total, "problem_pager": render.pager_ctx(problem_page, request.query_params),
                                  "panel_after_blocks": 3 if invalid else 2})
    by_kind = sorted(kinds.items(), key=lambda e: (-sum(e[1]["by"].values()), e[0]))
    return {"panel": panel, "blocks": [
        *([Note("État inconnu : affichage de tous les effets.", "warn")] if invalid else []),
        Stats(tuple(Stat(labels.get(k, k).capitalize(), n, "", tones.get(k, "") if k not in ("done", "seen") else "")
                    for k, n in sorted(counts.items())) or (Stat("File", 0, "vide"),)),
        Nav((NavItem("tout", Ref("local", f"{PREFIX}/systeme/sorties", "tout"), count=sum(counts.values()),
                     active=not status), *chips), title="État"),
        Table((Column("n°", "fit", hint="l'événement qui l'a fait partir"), Column("quand", "fit"), "effet", "état",
               Column("essais", "num"), "dernière erreur", Column("effet (clé)", detail=True),
               Column("action", detail=True, hint="ce qu'une action autorisée fait partir")), tuple(
            Row((Ref("event", str(seq), f"n° {seq}"), when(seq), Text(ui.names.effect(effect).name, hint=effect),
                 Badge(labels.get(st, st), tones.get(st, ""), key=st), attempts,
                 Text(names.detail(err) if err else "—", "muted", clamp=200), Text(effect, "mono"),
                 action(seq, effect)),
                href=Ref("event", str(seq), ""),
                tone={"failed": "danger", "orphan": "warn", "stale": "warn", "interrupted": "warn"}.get(st, ""))
            for _key, seq, effect, st, attempts, err in rows),
            title=OUTBOX_RECENT_TITLE, empty="Aucun effet.", pager=pager,
            caption="Orphelin : aucun exécuteur n'était déclaré pour cet effet quand il est parti — il n'a rien fait. "
                    "Périmé : une parole qui n'a pas pu partir dans les dix minutes — elle ne la dira plus. "
                    "Interrompu : une action coupée en cours (un arrêt, son délai) — on ne sait pas si elle a eu "
                    "lieu, à vérifier. Un effet échoué ou orphelin se relance (un essai de plus) ou se marque comme "
                    "vu ; un effet périmé ou interrompu se marque comme vu : le badge « à traiter » s'éteint, la "
                    "ligne reste."),
        Disclosure("Ce qui part, par sorte", (Table(
            ("effet", Column("départs", "num"), Column("parti", "num"), Column("en route", "num"),
             Column("à traiter", "num"), Column("vu, laissé", "num"), Column("dernier départ", "fit"),
             Column("effet (clé)", detail=True)),
            tuple(Row((Text(ui.names.effect(effect).name, hint=effect), sum(k["by"].values()), k["by"].get("done", 0),
                       sum(k["by"].get(s, 0) for s in OUTBOX_ROUTE), sum(k["by"].get(s, 0) for s in OUTBOX_PROBLEMS),
                       k["by"].get("seen", 0), when(k["last"]) if k["last"] else "—", Text(effect, "mono")),
                      href=Ref("event", str(k["last"]), "") if k["last"] else None)
                  for effect, k in by_kind),
            title=OUTBOX_KINDS_TITLE, empty="La file est vide.",
            caption="Ce que la file garde, sorte par sorte : les départs réussis des 30 derniers jours, et tout ce "
                    "qui n'est pas parti. Chaque ligne mène au dernier événement qui l'a fait partir."),)),
        Disclosure("À traiter, ligne par ligne", (Table(
            (Column("n°", "fit", hint="l'événement qui l'a fait partir"), Column("quand", "fit"), "effet",
             Column("à qui", hint="à qui la parole, ou la réponse qui ne viendra pas, n'est pas partie"),
             Column("quoi", hint="le début de la parole, ou le résumé de l'action"), "état", "erreur", "que faire",
             Column("effet (clé)", detail=True),
             Column("action", detail=True, hint="ce qu'une action autorisée fait partir"),
             Column("clé", detail=True, hint="la ligne de la file, que Relancer et Marquer comme vu désignent")),
            tuple(Row((Ref("event", str(seq), f"n° {seq}"), when(seq), Text(d.name, hint=effect), d.to or "—",
                       d.text or "—",  # déjà coupé sur une ligne (``_line``) : rien à replier
                       Badge(labels.get(st, st), tones.get(st, "warn"), key=st),
                       Text(names.detail(err) if err else "—", "muted", clamp=200), guidance(st, d.sort),
                       Text(effect, "mono"), Text(d.action) if d.action else "—", Text(key, "mono")),
                      href=Ref("event", str(seq), ""), tone="danger" if st in ("failed", "orphan") else "warn")
                  for key, seq, effect, st, err in stuck for d in (told[(seq, effect)],)),
            title=OUTBOX_TODO_TITLE, empty="Rien à traiter.", pager=problem_page),)),
    ]}


def _without(query: Any, *keys: str) -> dict[str, str]:
    return {k: v for k, v in query.items() if k not in keys}


def outbox_card(key: str, seq: int | str, d: Departure, state: str, error: str | None, **more: Any) -> dict[str, Any]:
    """Un départ à traiter, tel que le dessine ``outbox_item`` (``handmade/systeme/macros.html``) : ce qu'il fait
    partir, à qui, son état, ce qu'il faut faire, son erreur en clair, s'il se relance ; ``more`` : ce qu'ajoute une
    page (l'instant, les essais)."""
    return {"key": key, "seq": seq, "name": d.title, "to": d.to, "text": d.text,
            "state": OUTBOX_LABELS.get(state, state), "tone": OUTBOX_TONES.get(state, "warn"),
            "error": names.detail(error) if error else "", "retry": state not in OUTBOX_SEEN_ONLY,
            "hint": guidance(state, d.sort), **more}


def _action(ui: Any, ev: Any) -> str:
    """L'action qu'une proposition autorisée fait partir (« email.send » : son nom), lue dans son événement ; rien
    sans."""
    try:
        data = json.loads(ev.data)
    except (TypeError, ValueError):
        return ""
    name = data.get("capability") if isinstance(data, dict) else None
    return ui.names.capability(name) if isinstance(name, str) and name else ""


def _outbox_problems(ui: Any) -> tuple[int, str]:
    """Le badge de la file de sortie : ce qui n'a pas pu partir, et l'indice qui le dit."""
    rows = ui.kernel.mind.store.query_mind(select(func.count()).select_from(JournalOutbox)
                                           .where(JournalOutbox.status.in_(OUTBOX_PROBLEMS)))
    n = int(rows[0][0]) if rows else 0
    return n, agree(n, "effet qui n'a pas pu partir", "effets qui n'ont pas pu partir")


# Les badges des onglets de Système disent ce qu'ils comptent (C1-10) : l'accueil montre l'indice après le nombre,
# jamais un « à regarder » qui ne dit rien.

def _failing(ui: Any) -> tuple[int, str]:
    """Les processus en échec d'affilée, par leur nom (trois au plus)."""
    sched = ui.kernel.scheduler
    failing = [ui.names.process(s.name) for s in sched.specs
               if sched.consecutive.get(s.name, 0) >= health.PROCESS_FAILURES_MAX]
    shown = ", ".join(failing[:3]) + (f" et {len(failing) - 3} de plus" if len(failing) > 3 else "")
    return len(failing), f"en échec d'affilée : {shown}" if failing else ""


def _anomalies(ui: Any) -> tuple[int, str]:
    n = len(getattr(ui.kernel.mind, "anomalies", ()) or ())
    return n, agree(n, "chose qui s'est mal passée depuis le démarrage, sans rien arrêter",
                    "choses qui se sont mal passées depuis le démarrage, sans rien arrêter")


def _returned(data: Mapping[str, Any] | None, default: str) -> str:
    """Où revient un geste de Système : le ``_retour`` du formulaire, s'il reste dans la console ; sinon sa page."""
    back = str((data or {}).get("_retour", "")) or default
    if not back.startswith(PREFIX + "/") or "//" in back or "\\" in back or "#" in back:
        back = default
    return back


def _flashed(back: str, token: str) -> Response:
    sep = "&" if "?" in back else "?"
    return secure(RedirectResponse(f"{back}{sep}flash={token}", status_code=303))


async def outbox_post(ui: Any, request: Request) -> Response:
    """Relancer un effet échoué ou orphelin (un essai de plus, tout de suite), ou le marquer comme vu (il
    n'allume plus « à traiter ») — audité, jamais sur un effet qui n'est pas en échec."""
    data = await ui.form(request)
    account = ui.operator(request)
    back = _returned(data, f"{PREFIX}/systeme/sorties")
    token = _secrets.token_urlsafe(9)
    if data is None or account is None:
        ui.flash(token, "danger", "Jeton de formulaire invalide : recharge la page.")
    else:
        key, what = str(data.get("cle", ""))[:300], str(data.get("faire", ""))
        store = ui.kernel.mind.store
        found = store.query_mind(select(JournalOutbox.status, JournalOutbox.last_error).where(JournalOutbox.key == key))
        if not found or found[0][0] not in OUTBOX_PROBLEMS or what not in ("relancer", "vu"):
            ui.flash(token, "warn", "Rien à faire : cet effet n'est plus en échec (déjà relancé ou vu ?).")
        elif what == "relancer" and found[0][0] in OUTBOX_SEEN_ONLY:
            ui.flash(token, "warn", "Pas relancé : une parole périmée ne part plus, et une action interrompue a "
                                    "peut-être déjà eu lieu. Vérifie, puis marque-le comme vu.")
        else:
            error = found[0][1]
            if what == "relancer":
                await store.mark_outbox(key, "pending", error)
                ui.kernel.effects.wake()
                ui.flash(token, "ok", "Relancé : l'effet repart pour un essai.")
            else:
                await store.mark_outbox(key, "seen", error)
                ui.flash(token, "ok", "Marqué comme vu : il n'est plus « à traiter ».")
            await ops.audit(ui.kernel, f"console.sorties.{what}", by=account.handle, subject_kind="effet",
                            subject=key)
    return _flashed(back, token)


async def rebuild_post(ui: Any, request: Request) -> Response:
    """« Reconstruire » une tranche corrompue (Anomalies, Diagnostic avancé ; ADR 0234) : ``Mind.rebuild`` la rejoue
    depuis la genèse dans une racine à part, sans arrêter les ajouts, puis bascule — la reconstruction en ligne dont
    l'oubli d'un nom se sert déjà. Refusé pour une tranche qui n'est pas corrompue, ou qui ne se rejoue pas
    (``rebuildable``). Le message dit le résultat : saine, ou encore corrompue au n° N — le réducteur lève toujours
    avec ce code : le geste ne sert qu'une fois le réducteur corrigé et le serveur relancé dessus — et les tranches
    qu'elle lit qui ne rejouent pas à l'identique (``mismatches``, tracées « reconstruction divergente »). Audité
    ``console.systeme.reconstruire`` (sur la tranche : sa faculté), « échouée » si elle reste corrompue."""
    data = await ui.form(request)
    account = ui.operator(request)
    back = _returned(data, f"{PREFIX}/systeme/anomalies")
    token = _secrets.token_urlsafe(9)
    mind = ui.kernel.mind
    owner = str((data or {}).get("faculte", ""))[:200]
    if data is None or account is None:
        ui.flash(token, "danger", "Jeton de formulaire invalide : recharge la page.")
    elif mind.root.tainted.get(owner) is None:
        ui.flash(token, "warn", "Rien à reconstruire : cette tranche n'est pas corrompue (déjà reconstruite ?).")
    elif not rebuildable(ui.kernel, owner):
        ui.flash(token, "warn", "Pas reconstruite : cette tranche ne se rejoue pas depuis le journal (elle ne garde "
                                "que le présent).")
    else:
        shown = ui.names.faculty(owner)
        got = await acall(mind.rebuild, [owner], label=f"reconstruction de {owner}")
        still = mind.root.tainted.get(owner)
        healed = not isinstance(got, Failed) and still is None
        if isinstance(got, Failed):
            tone, said = "danger", (f"« {shown} » : la reconstruction a échoué ({names.detail(repr(got.error))}). La "
                                    "tranche reste telle qu'elle était.")
        elif still is not None:
            tone, said = "danger", (f"« {shown} » encore corrompue au n° {still} : le réducteur lève toujours avec ce "
                                    "code — corrige-le, redémarre, puis reconstruis.")
        else:
            replayed = int(got.get("replayed", 0))
            tone, said = "ok", (f"« {shown} » reconstruite : la tranche est saine "
                                f"({plural(replayed, 'événement relu', 'événements relus')}).")
        drift = [] if isinstance(got, Failed) else [ui.names.faculty(o) for o in got.get("mismatches") or ()]
        if drift:
            tone = "warn" if tone == "ok" else tone
            said += (" " + agree(len(drift), "Une tranche qu'elle lit ne rejoue pas", "Des tranches qu'elle lit ne "
                                 "rejouent pas") + f" à l'identique : {', '.join(drift)} (« reconstruction "
                     "divergente », dans les traces d'Anomalies).")
        ui.flash(token, tone, said)
        await ops.audit(ui.kernel, "console.systeme.reconstruire", by=account.handle, subject_kind="tranche",
                        subject=owner, outcome="done" if healed else "failed")
    return _flashed(back, token)


async def retry_post(ui: Any, request: Request) -> Response:
    """« Réessayer maintenant » un processus en échec (Processus › Ce qui ne va pas ; ADR 0234) : son recul est
    effacé et l'ordonnanceur fait une passe (``Scheduler.retry_now``) — il repart à sa prochaine échéance, tout de
    suite s'il était dû. Jamais un processus en cours, ni un processus qui n'est pas en échec, ni un processus retenu
    pour une rafale, même en échec : la retenue ne se force pas (le message le dit). Audité
    ``console.systeme.reessayer`` (sur le processus : son nom technique)."""
    data = await ui.form(request)
    account = ui.operator(request)
    back = _returned(data, f"{PREFIX}/systeme/processus")
    token = _secrets.token_urlsafe(9)
    name = str((data or {}).get("processus", ""))[:200]
    if data is None or account is None:
        ui.flash(token, "danger", "Jeton de formulaire invalide : recharge la page.")
    elif not ui.kernel.scheduler.retry_now(name):
        ui.flash(token, "warn", "Pas relancé : ce processus est retenu pour une rafale — la retenue ne se force pas, "
                                "il repart à sa fin." if ui.kernel.scheduler.held(name) else
                                "Pas relancé : ce processus n'est plus en échec, ou il tourne déjà.")
    else:
        ui.flash(token, "ok", f"« {ui.names.process(name)} » relancé : son recul est effacé, il repart à sa prochaine "
                              "échéance — tout de suite s'il était dû.")
        await ops.audit(ui.kernel, "console.systeme.reessayer", by=account.handle, subject_kind="processus",
                        subject=name)
    return _flashed(back, token)


@TABS.tab("systeme.passerelle", title="Moteur des modèles", group="Surveiller",
          description="La passerelle des modèles telle qu'elle tourne : pour chaque fournisseur, ses créneaux "
                      "(occupés, en attente), son quota ; pour chaque rôle, qui le sert vraiment.")
async def passerelle(ui: Any, request: Request) -> list[Any]:
    gateway = ui.kernel.deps.gateway
    status = list(getattr(gateway, "status", lambda: [])() or [])
    resolution = dict(getattr(gateway, "resolution", lambda: {})() or {})
    if not getattr(gateway, "configured", gateway is not None):
        return [Note("Aucun modèle n'est configuré : chaque tour échoue proprement. Déclare un fournisseur dans "
                     "Réglages › Modèles de texte › Fournisseurs.", "danger")]
    rows = []
    for b in status:
        quota = (b.get("extra") or {}).get("quota") or {}
        quota_text = " · ".join(f"{k} {pct_fr(v)}" for k, v in quota.items()) if quota else "—"
        rows.append(Row((Text(b["name"], "mono"), Text(f"{b['busy']} / {b['slots']}", "num"), b["waiting"],
                         Badge("oui", "info") if b["preempt"] else Text("non", "muted"),
                         quota_text),
                        tone="warn" if b["waiting"] else ""))
    # un rôle facultatif sans modèle (``OPTIONAL_ROLES`` : rendre naturel) est coupé, par choix — sa passe ne se fait
    # pas, aucun appel n'échoue (ADR 0140) : il ne compte pas parmi les rôles sans fournisseur, ni dans leur alarme
    unserved = [r for r, name in resolution.items() if not name and r not in OPTIONAL_ROLES]
    optional = ", ".join(f"« {names.role(r)} »" for r in sorted(OPTIONAL_ROLES))
    lacks = agree(len(OPTIONAL_ROLES), "n'a", "n'ont")
    return [
        Stats((Stat("Fournisseurs", len(status)), Stat("Créneaux occupés", sum(b["busy"] for b in status),
                                                       f"sur {sum(b['slots'] for b in status)}"),
               Stat("En attente d'un créneau", sum(b["waiting"] for b in status), "",
                    "warn" if any(b["waiting"] for b in status) else ""),
               Stat("Rôles sans fournisseur", len(unserved), ", ".join(names.role(r) for r in unserved) or "aucun",
                    "danger" if unserved else ""))),
        Table(("fournisseur", Column("créneaux", "num"), Column("en attente", "num"), "préempte",
               "quota d'abonnement"), tuple(rows), title="Fournisseurs",
              caption="Un fournisseur à un seul créneau préempte : une réponse interrompt un travail de fond."),
        Table(("rôle", Column("nom technique", "fit"), "servi par", "effort"), tuple(
            Row((ROLE_LABELS.get(r, r), Text(r, "mono"), _served_by(r, n), _effort(gateway, r) if n else ""),
                tone="" if n or r in OPTIONAL_ROLES else "danger")
            for r, n in resolution.items()), title="Qui sert quoi, en vrai",
            caption="Replis compris : un rôle sans fournisseur retombe sur un autre rôle (murmurer → répondre). "
                    f"{optional} {lacks} pas de repli : sans modèle, sa passe ne se fait pas, et aucun appel "
                    "n'échoue. L'effort est celui réglé pour le rôle, sinon celui de la fiche de son fournisseur. "
                    "Se règle dans Réglages › Modèles de texte › Qui sert quoi."),
    ]


def _effort(gateway: Any, role: str) -> Text | str:
    """La cellule « effort » d'un rôle servi : l'effort auquel partent ses appels (ADR 0285), et d'où il vient — le
    sien, ou celui de la fiche de son fournisseur ; aucun : le défaut du modèle."""
    asked = getattr(gateway, "effort_of", None)
    effort, own = asked(role) if callable(asked) else ("", False)
    if not effort:
        return Text("défaut du modèle", "muted")
    return f"{EFFORT_LABELS.get(effort, effort)} — {'réglé pour ce rôle' if own else 'celui de sa fiche'}"


#: ce qu'un rôle facultatif coupé ne fait pas (``OPTIONAL_ROLES``)
OPTIONAL_CUT, OPTIONAL_CUT_ANY = {str(Role.POLISH): "la seconde passe ne se fait pas",
                                  str(Role.CORRECT): "« Corriger » reste éteint dans Mail et Teams"}, "sa passe ne se fait pas"


def _served_by(role: str, name: str) -> Text:
    """La cellule « servi par » d'un rôle : son fournisseur ; aucun — un rôle facultatif est coupé, en ton neutre, et
    tout autre échoue à chaque appel."""
    if name:
        return Text(name, "mono")
    if role in OPTIONAL_ROLES:
        return Text(f"coupée : aucun modèle, {OPTIONAL_CUT.get(role, OPTIONAL_CUT_ANY)}", "muted")
    return Text("aucun : chaque appel échoue", "muted")


@TABS.tab("systeme.stockage", title="Stockage et sauvegardes", group="Surveiller",
          description="Chacune de ses bases et chacun de ses dossiers : la place qu'il prend, ce qu'il garde, ce que la "
                      "sauvegarde en fait ; le dernier instantané et ce que garde le journal. Les sauvegardes se font "
                      "par « mika backup ».")
async def stockage(ui: Any, request: Request) -> list[Any]:
    store = ui.kernel.mind.store
    mind = ui.kernel.mind
    mind_base = call(store.read_mind, _base, label="stockage : mind")
    views_base = call(store.read_views, _base, label="stockage : views")
    mind_base = mind_base if not isinstance(mind_base, Failed) else _Base("mind", None, " (illisible)", {})
    views_base = views_base if not isinstance(views_base, Failed) else _Base("views", None, " (illisible)", {})

    def count(table: str) -> int:
        return mind_base.counts.get(table, 0)

    snap = store.latest_snapshot()
    boots = mind.root.slices["kernel"].boots
    places = await _places(ui)
    return [
        Stats((Stat(mind_base.name, size_fr(mind_base.size), f"sa vie : à sauvegarder{mind_base.note}"),
               Stat(views_base.name, size_fr(views_base.size), f"reconstruisible{views_base.note}"),
               Stat("Événements", mind.head, plural(boots, "démarrage", "démarrages")),
               Stat("Dernier instantané", f"n° {snap.seq}" if snap else "aucun",
                    ui.when_long(snap.at) if snap else "le démarrage rejoue tout"))),
        Table(("table", Column("lignes", "num"), "ce qu'elle garde"), (
            ("events", count("events"), "le journal : tout ce qui lui est arrivé"),
            ("content", count("content"), "les textes libres, effaçables par l'oubli"),
            ("snapshots", count("snapshots"), "les instantanés (démarrage rapide)"),
            ("outbox", count("outbox"), "la file de sortie"),
            ("settings", count("settings"), "les réglages d'exploitation"),
        ), title=f"Ce que garde {mind_base.name}"),
        *([_places_table(places)] if places is not None else []),
        *backup_blocks(ui),
        Note(backup_note((ui.deps.backups() or {}) if ui.deps.backups is not None else {}), "muted"),
    ]


#: ce que la sauvegarde fait d'une base ou d'un dossier (``app/backup.place``) : en mots, et son ton
KEPT_WORDS = {"oui": ("sauvegardé", "ok"), "jetable": ("jetable : se reconstruit", "muted"),
              "réextrait": ("pas sauvegardé : se réextrait", "muted"),
              "retéléchargé": ("pas sauvegardé : se retélécharge", "muted"), "non": ("pas sauvegardé", "muted"),
              "mis de côté": ("mis de côté par une restauration", "warn")}
PLACES_TITLE = "Ses bases et ses dossiers"


async def _places(ui: Any) -> list[dict[str, Any]] | None:
    """Ce que porte son dossier de données (``app/backup.place``, que fournit la composition), mesuré hors de la
    boucle d'événements (un parcours du dossier) ; ``None`` : ce serveur ne le dit pas, ou la mesure a échoué."""
    fn = ui.deps.backups
    measure = (fn() or {}).get("place") if fn is not None else None
    if not callable(measure):
        return None
    got = await acall(lambda: asyncio.to_thread(measure), label="stockage : le dossier de données")
    return None if isinstance(got, Failed) else list(got)


def _places_table(places: list[dict[str, Any]]) -> Table:
    rows = []
    for p in places:
        said, tone = KEPT_WORDS.get(str(p.get("sauvegarde")), (str(p.get("sauvegarde") or "—"), ""))
        size = "sur le serveur MariaDB" if p.get("serveur") else size_fr(int(p.get("octets") or 0))
        name = f"{p['nom']}/" if p.get("dossier") else str(p["nom"])
        rows.append(Row((Text(name, "mono"), Text(size, "num"), Text(str(p.get("garde") or "—"), "muted"),
                         Badge(said, tone)), tone="warn" if tone == "warn" else ""))
    return Table(("nom", Column("place", "num"), "ce qu'il garde", "sauvegarde"), tuple(rows), title=PLACES_TITLE,
                 empty="Le dossier de données ne se lit pas.",
                 caption="La sauvegarde (« mika backup ») emporte ce qui ne se reconstruit pas ; views.db se reconstruit "
                         "depuis le journal (les traces et les appels de modèle des derniers jours s'y perdent), la "
                         "carte se réextrait, le modèle de plongements se retélécharge. Sous MariaDB, ses bases sont "
                         "sur le serveur : la sauvegarde en fait une copie SQL.")


@dataclass(frozen=True, slots=True)
class _Base:
    """Une base telle que la page Stockage la montre : son nom, sa place (``None`` : le moteur ne la dit pas), ce
    qu'en dit la mesure, et le nombre de lignes des tables qu'elle détaille."""

    name: str
    size: int | None
    note: str
    counts: dict[str, int]


#: les tables de ``mind`` que la page détaille ; ``settings`` est à l'application (``app/settings.py``), qu'on ne
#: nomme pas d'ici : compté par son nom
_COUNTED = {"events": JournalEvent.__table__, "content": JournalContent.__table__,
            "snapshots": JournalSnapshot.__table__, "outbox": JournalOutbox.__table__, "settings": sa_table("settings")}


def _base(sql: Any) -> _Base:
    """Une base lue par sa connexion : ses tables (``inspect`` de SQLAlchemy, jamais le catalogue d'un moteur) et sa
    place, qui dépend du moteur et le dit — la taille du fichier et de son journal d'écriture sous SQLite, ce qu'InnoDB
    déclare de ses données et de ses index sous MariaDB (``information_schema`` : une estimation, sans les journaux du
    serveur)."""
    bind = sql.session.get_bind()
    tables = set(inspect(bind).get_table_names())
    counts = {name: int(sql.query(select(func.count()).select_from(t))[0][0])
              for name, t in _COUNTED.items() if name in tables}
    url = bind.engine.url
    engine = sql.dialect.name
    if engine == "sqlite":
        path = Path(url.database) if url.database and url.database != ":memory:" else None
        # avec son journal d'écriture (``-wal``, ``-shm``) : la place qu'elle prend, comme « Ses bases et ses dossiers »
        size = sum(p.stat().st_size for p in (path, *(Path(f"{path}{s}") for s in ("-wal", "-shm"))) if p.exists()) \
            if path is not None and path.exists() else None
        return _Base(path.name if path is not None else "en mémoire", size, "", counts)
    if engine in ("mysql", "mariadb"):
        info = sa_table("tables", column("table_schema"), column("data_length"), column("index_length"),
                        schema="information_schema")
        got = sql.query(select(func.coalesce(func.sum(info.c.data_length + info.c.index_length), 0))
                        .where(info.c.table_schema == func.database()))
        return _Base(str(url.database or engine), int(got[0][0] or 0), " (estimation d'InnoDB)", counts)
    return _Base(str(url.database or engine), None, f" (place inconnue sous {engine})", counts)


#: au-delà, une sauvegarde est « ancienne » (l'accueil le signale)
BACKUP_LATE_DAYS = 2


def _failed_attempt(got: Any) -> dict[str, Any]:
    """La dernière tentative de sauvegarde si elle a échoué après la dernière réussite (vide sinon : une
    réussite ultérieure éteint l'alerte d'elle-même ; une installation qui n'a rien noté n'en a pas)."""
    attempt = got.get("tentative") or {}
    last = got.get("sauvegarde") or {}
    if attempt and not attempt.get("ok") and int(attempt.get("at") or 0) > int(last.get("at") or 0):
        return attempt
    return {}


def backup_state(ui: Any) -> tuple[str, str]:
    """(ton, phrase) : l'état des sauvegardes, pour l'accueil, la santé générale (sa tuile) et la page Stockage et
    sauvegardes. Une phrase sans commande, que le bandeau termine d'un point (« Sauvegardes : aucune sauvegarde
    notée. ») : les commandes vivent dans la note de la page (``backup_note``)."""
    fn = ui.deps.backups
    if fn is None:
        return "", ""
    got = fn() or {}
    last = got.get("sauvegarde") or {}
    failed = _failed_attempt(got)
    if failed:
        return "danger", f"la dernière tentative a échoué : {failed.get('erreur', '?')}"[:160]
    if not last:
        return "warn", "aucune sauvegarde notée"
    age = (ui.now() - int(last.get("at") or 0)) / DAY
    check = got.get("verification") or {}
    if check and not check.get("ok"):
        return "danger", f"la dernière vérification a échoué : {check.get('erreur', '?')}"[:160]
    if age > BACKUP_LATE_DAYS:
        return "warn", f"la dernière date de {age:.0f} jours"
    return "ok", f"il y a {age * 24:.0f} h"


def backup_blocks(ui: Any) -> list[Any]:
    fn = ui.deps.backups
    if fn is None:
        return []
    got = fn() or {}
    last, check, archives = got.get("sauvegarde") or {}, got.get("verification") or {}, got.get("archives") or []
    failed = _failed_attempt(got)
    head = ui.kernel.mind.head
    tone, text = backup_state(ui)
    since = head - int(last.get("tete") or 0) if last else 0
    out: list[Any] = [Stats((
        Stat("Dernière sauvegarde", When(int(last["at"])) if last else "jamais", text, tone),
        *([Stat("Dernière tentative", When(int(failed.get("at") or 0)), f"échec : {failed.get('erreur', '?')}"[:120],
                "danger")] if failed else []),
        Stat("Depuis", plural(since, "événement", "événements") if last else "—", "pas encore dans une archive",
             "warn" if last and since > 0 and (tone == "warn" or failed) else ""),
        Stat("Dernière vérification", When(int(check["at"])) if check else "jamais",
             ("réussie" + "".join(f" — {r}" for r in check.get("remarques") or []) if check.get("ok")
              else f"échec : {check.get('erreur', '?')}")[:120] if check else
             (f"la vérification rejoue la dernière archive, {Path(str(last['archive'])).name}, sans rien toucher : "
              "sa commande est plus bas" if last.get("archive") else
              "la vérification rejoue une archive sans rien toucher : sa commande est plus bas"),
             "" if not check else "ok" if check.get("ok") else "danger"),
        Stat("Archives gardées", len(archives), size_fr(sum(int(a.get("octets") or 0) for a in archives))
             + (f" · {last.get('dossier')}" if last else "")),
    ), title="Sauvegardes")]
    if last:
        out.append(Fields((("archive", Text(str(last.get("archive", "—")), "mono")), ("fichiers", last.get("fichiers")),
                           ("taille", size_fr(int(last.get("octets") or 0))), ("tête du journal", last.get("tete")),
                           ("en garde", f"les {last['garde']} plus récentes" if last.get("garde") else "toutes"),
                           ("remarques", "; ".join(last.get("remarques") or []) or "—")),
                          title="La dernière sauvegarde", columns=2))
    if archives:
        out.append(Table((Column("archive"), Column("taille", "num"), Column("écrite", "fit")), tuple(
            (Text(a["nom"], "mono"), size_fr(int(a.get("octets") or 0)), When(int(a.get("at") or 0)))
            for a in archives), title=f"Archives ({len(archives)})"))
    return out


#: le nombre d'archives que garde la sauvegarde du service (``deploy/mika-backup.service``, ``--keep 14``)
BACKUP_KEEP = 14


def _arg(value: Any, unknown: str) -> str:
    """Un chemin d'une commande à taper, entre guillemets s'il le faut (une espace, une apostrophe) ; ce qu'il faut y
    mettre, entre chevrons, quand on ne le connaît pas."""
    return shlex.quote(str(value)) if value else f"<{unknown}>"


def backup_commands(got: Mapping[str, Any]) -> tuple[str, str, str]:
    """(sauvegarder, vérifier, restaurer) : les commandes telles qu'on les tape, avec les vrais dossiers quand
    ``app/backup.overview`` les connaît (``donnees`` : le dossier de données ; celui de la dernière archive ou de la
    dernière tentative ; ``unite`` : l'unité de sauvegarde installée pour ce dossier), un mot entre chevrons à leur place
    sinon, jamais « DOSSIER » à remplir (audit du 2026-11-05, C8-04). Là où l'unité est installée, on sauvegarde par
    elle : la même sauvegarde, avec l'environnement du service (``deploy/README.md``, « Sauvegarder »). Restaurer
    remplace un dossier qui ne sera jamais vide, d'où ``--force`` (l'ancien contenu mis de côté, jamais effacé)."""
    last = got.get("sauvegarde") or {}
    data = _arg(got.get("donnees"), "dossier de données")
    keep = int(last.get("garde") or 0) if "garde" in last else BACKUP_KEEP  # 0 : elle les gardait toutes
    folder = _arg(last.get("dossier") or (got.get("tentative") or {}).get("dossier"), "dossier des archives")
    save = (f"sudo systemctl start {got['unite']}" if got.get("unite") else
            f"mika --data {data} backup {folder}" + (f" --keep {keep}" if keep else ""))
    return (save, f"mika --data {data} verify {_arg(last.get('archive'), 'dernière archive')}",
            f"mika --data {data} restore <archive> --force")


def backup_note(got: Mapping[str, Any]) -> str:
    """La note de Stockage et sauvegardes : les trois commandes (``backup_commands``), quand chacune se lance, et ce que
    la page en garde."""
    save, verify, restore = backup_commands(got)
    return (f"Sauvegarder (sans risque serveur en marche) : « {save} » ; vérifier : « {verify} » ; restaurer (serveur "
            f"arrêté ; l'ancien contenu est mis de côté, jamais effacé) : « {restore} », <archive> étant l'une des "
            "archives gardées. Chaque sauvegarde (réussie ou non) et chaque vérification se notent ici.")
