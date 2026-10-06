"""Décisions : pourquoi elle parle ou se tait. L'arbitre en direct, ses choix
passés (avec le détail de chaque ligne), ses épisodes, ses échéances — et, pour
une personne, ce qu'elle ferait maintenant et ce qui la retient."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from starlette.requests import Request

from mika.contracts import runtime as rt
from mika.inspector import names
from mika.inspector.names import KINDS, OUTCOMES
from mika.inspector.pages.home import episode_row
from mika.inspector.pages.tabs import TABS
from mika.kernel.clock import DAY, US
from mika.kernel.inspect import (
    Badge,
    Chart,
    Column,
    Disclosure,
    Fields,
    Note,
    Pager,
    Param,
    Ref,
    Row,
    Series,
    Stat,
    Stats,
    Table,
    Text,
    When,
    num_fr,
    read_params,
)
from mika.runtime.boundary import Failed, call

EPISODES_PAGE = 50
#: un filtre lit le journal par lots de tant d'épisodes, au plus tant de lots par page
EPISODE_SCAN = 200
EPISODE_SCAN_BATCHES = 10
#: ses choix, par page
SELECTIONS_PAGE = 40


def _signed(value: float) -> str:
    return num_fr(value, 2, signed=True)


def _rate(hazard: float) -> str:
    """Un taux d'arbitre (par seconde) en « fois par heure »."""
    return num_fr(hazard * 3600, 2)


def evidence_text(ui: Any, r: Any) -> str:
    """Les preuves d'une ligne, une par ligne, en mots (la clé technique reste dans le détail)."""
    return "\n".join(f"{ui.names.reason(owner, reason)}  {_signed(value)}" for owner, reason, value in r.parts) or "—"


def vetoes_text(ui: Any, r: Any) -> str:
    return ", ".join(ui.names.veto(owner, code) for owner, code in r.vetoes)


def waterfall(ui: Any, r: Any, *, title: str = "Du signal au score") -> Table:
    """Le score d'une ligne pas à pas : chaque preuve, chaque modulation, l'attente, puis le seuil de la
    sorte d'épisode — et le cumul à chaque étape ; en dessous, le taux qui en sort et les vetos."""
    steps: list[tuple[str, str, str, float]] = [
        ("preuve", ui.names.reason(owner, reason), f"{owner} · {reason}", value) for owner, reason, value in r.parts]
    shifts = tuple(getattr(r, "shifts", ()) or ())
    if shifts:
        steps += [("modulation", ui.names.faculty(owner), owner, value) for owner, value in shifts]
    elif r.shift:
        steps.append(("modulation", "toutes les modulations", "", r.shift))
    aging = getattr(r, "aging", 0.0)
    if aging:
        steps.append(("attente", "ce qu'a ajouté l'attente de la ligne", "", aging))
    threshold = getattr(r, "threshold", 0.0)
    if threshold:
        steps.append(("seuil", f"le seuil de la sorte « {names.kind(r.kind)} »", "", -threshold))
    total = 0.0
    rows = []
    for what, why, key, value in steps:
        total += value
        rows.append(Row((Badge(what, "info" if what == "preuve" else "muted"), Text(why, hint=key),
                         Text(_signed(value), "num", "ok" if value > 0 else "danger" if value < 0 else ""),
                         Text(_signed(total), "num"))))
    rows.append(Row((Badge("score", "ok" if r.score > 0 else "warn"), "le score final de la ligne",
                     "", Text(_signed(r.score), "num", "ok" if r.score > 0 else "")), tone="muted"))
    if r.vetoes:
        rows.append(Row((Badge("veto", "danger"), vetoes_text(ui, r), "", "—"), tone="danger"))
    drift = r.score - total
    caption = (f"Le score devient un taux : {_rate(r.hazard)} fois par heure au plus"
               + (" (zéro : un veto l'en empêche)" if r.vetoes else "")
               + (f" · écart d'arrondi {_signed(drift)}" if abs(drift) > 0.05 else "") + ".")
    return Table((Column("étape", "fit"), "quoi", Column("apport", "num"), Column("cumul", "num")), tuple(rows),
                 title=title, caption=caption)


def arbiter_rows(ui: Any, rows: Any, *, fired: frozenset[str] = frozenset()) -> tuple[Row, ...]:
    """Les lignes de l'arbitre en table : sorte et cible nommées, preuves en mots, détail pas à pas."""
    return tuple(
        Row((ui.names.arbiter_row(r.kind, r.target), Text(evidence_text(ui, r), "text"), Text(_signed(r.score), "num",
             "ok" if r.score > 0 else ""), _rate(r.hazard),
             Badge(vetoes_text(ui, r), "danger") if r.vetoes else "—"),
            tone="ok" if f"{r.kind}:{r.target}" in fired or (not fired and r.hazard > 0 and not r.vetoes) else "",
            detail=(waterfall(ui, r),)) for r in rows)


ARBITER_COLUMNS = ("ligne", Column("ce qui pousse", hint="les preuves, en points (log-odds) par raison"),
                   Column("score", "num"), Column("fois / h", "num", hint="le taux qui sort du score"),
                   "ce qui l'empêche")


def _possible(r: Any | None) -> str:
    """Ce qu'une ligne lui permet, en mots : son taux, ou ce qui l'en empêche."""
    if r is None:
        return "aucune ligne"
    if r.vetoes:
        return "bloqué"
    return f"{_rate(r.hazard)} fois / h"


def arbiter_diff(ui: Any, before: Sequence[Any], after: Sequence[Any]) -> Table:
    """Deux tables de l'arbitre du même instant (avec les paramètres en vigueur, avec d'autres) : les lignes
    dont le score, le taux ou les vetos changent à l'affichage, avant → après — une ligne qui naît ou
    disparaît comprise —, le plus grand écart de taux d'abord ; le calcul pas à pas de chaque côté."""
    old, new = {r.key: r for r in before}, {r.key: r for r in after}
    changed = []
    for key in old.keys() | new.keys():
        a, b = old.get(key), new.get(key)
        if a is not None and b is not None and _signed(a.score) == _signed(b.score) \
                and _rate(a.hazard) == _rate(b.hazard) and a.vetoes == b.vetoes:
            continue
        gap = abs((b.hazard if b is not None else 0.0) - (a.hazard if a is not None else 0.0))
        changed.append((-gap, key))
    rows = []
    for _gap, key in sorted(changed):
        a, b = old.get(key), new.get(key)
        r = b if b is not None else a
        detail = tuple(waterfall(ui, x, title=title) for x, title in ((b, "Après : du signal au score"),
                                                                       (a, "Avant : du signal au score"))
                       if x is not None)
        rows.append(Row((ui.names.arbiter_row(r.kind, r.target),
                         Text(f"{_signed(a.score) if a is not None else '—'} → "
                              f"{_signed(b.score) if b is not None else '—'}", "num"),
                         Text(f"{_possible(a)} → {_possible(b)}", "num"),
                         Badge(vetoes_text(ui, b), "danger") if b is not None and b.vetoes else "—"),
                        detail=detail))
    return Table(("ligne", Column("score", "num", hint="avant → après"),
                  Column("elle ferait", "num", hint="avant → après : le taux qui sort du score, ou « bloqué »"),
                  Column("ce qui l'empêche, après")), tuple(rows), title="Ce qu'elle ferait",
                 empty="Aucune ligne de l'arbitre ne change : à cet instant, elle ferait la même chose.",
                 caption="Avant : les paramètres en vigueur ; après : les valeurs tapées. Le taux est un nombre de "
                         "fois par heure au plus (un tirage au hasard décide) ; ouvre une ligne pour le calcul pas "
                         "à pas.")


@TABS.tab("decisions.en_cours", title="En cours",
          description="Ce qui tourne à cet instant : les épisodes ouverts, les files d'attente, les baux tenus, les "
                      "questions qui attendent une réponse.")
async def running(ui: Any, request: Request) -> list[Any]:
    kernel = ui.kernel
    frame = kernel.mind.frame()
    now = ui.now()
    rt_state = frame.state("runtime")
    open_ = sorted(rt_state.open.items(), key=lambda kv: kv[1].started_at)
    lanes = kernel.lanes
    leases = frame.root.slices["kernel"].leases
    procs = sorted(kernel.scheduler.running())
    blocks: list[Any] = [Stats((
        Stat("Épisodes ouverts", len(open_), "en train de se dérouler", "info" if open_ else ""),
        Stat("En file", sum(lanes.pending(x) for x in lanes.capacities),
             " · ".join(f"{names.lane(x)} {lanes.pending(x)}/{c}" for x, c in lanes.capacities.items())),
        Stat("Processus en cours", len(procs), ", ".join(ui.names.process(p) for p in procs)[:90] or "aucun"),
        Stat("Questions sans réponse", len(rt_state.pending), "attendent qu'elle réponde",
             "warn" if rt_state.pending else "", Ref("local", "/inspecteur/fil/questions", "questions")),
    ))]
    blocks.append(Table((Column("depuis", "fit"), "épisode", "vers", Column("durée", "num"), "en réponse à"), tuple(
        Row((When(o.started_at), names.kind(o.kind), ui.names.who_cell(o.target),
             f"{num_fr(max(0, now - o.started_at) / US, 0)} s",
             Ref("event", str(o.reply_to), f"message n° {o.reply_to}") if o.reply_to else "—"),
            href=Ref("episode", corr, ""), tone="warn" if now - o.started_at > 120 * US else "")
        for corr, o in open_), title="Épisodes ouverts", empty="Aucun épisode en cours."))
    blocks.append(Table(("voie", Column("capacité", "num"), Column("en attente", "num")), tuple(
        (Text(names.lane(lane), hint=lane), cap, lanes.pending(lane)) for lane, cap in lanes.capacities.items()),
        title="Files d'attente",
        caption="Une voie exécute au plus « capacité » épisodes à la fois ; les autres attendent leur tour."))
    blocks.append(Table(("ce qui est réservé", "par", "jusqu'à"), tuple(
        (Text(ui.names.resource(res), hint=res), Ref("episode", lease.holder, "l'épisode qui le tient"),
         When(lease.until)) for res, lease in sorted(leases.items())),
        title="Baux tenus", empty="Aucun bail tenu.",
        caption="Un bail réserve une ressource (la parole avec quelqu'un, un atelier) le temps d'un épisode."))
    return blocks


@TABS.tab("decisions.maintenant", title="Maintenant",
          description="La table de l'arbitre à cet instant : pour chaque ligne (une sorte d'épisode envers "
                      "quelqu'un), ce qui pousse, le seuil, le score et le taux qui en sortent.")
async def live(ui: Any, request: Request) -> list[Any]:
    kernel = ui.kernel
    rows = kernel.arbiter.rows(kernel.mind.frame())
    policy = kernel.registry.arbitration
    table = Table(ARBITER_COLUMNS, arbiter_rows(ui, rows),
                  title="La table de l'arbitre, maintenant",
                  empty="Aucune ligne : personne de présent et rien qui pousse à agir.",
                  caption="Les preuves se cumulent par sorte d'épisode et par personne ; plus le score est haut, "
                          "plus elle a de chances d'agir bientôt (un tirage au hasard, au taux indiqué).")
    policy_fields = Fields(tuple((f"seuil · {names.kind(k)}", f"{num_fr(v, 2)} (retiré du score)")
                                 for k, v in sorted(policy.thresholds.items()))
                           + tuple((f"taux max · {names.kind(k)}", f"{_rate(v)} fois / h")
                                   for k, v in sorted(policy.max_rates.items())), title="Politique")
    anomalies = list(getattr(kernel.arbiter, "anomalies", []))[-10:]
    return [*[Note(names.detail(str(a)), "warn") for a in anomalies], table,
            Disclosure("Comprendre les seuils de décision", (policy_fields,))]


PERSON_PARAMS = (Param("personne", "personne", "search", placeholder="un nom (Adrien) ou une adresse"),)


@TABS.tab("decisions.envers", title="Que ferait-elle ?",
          description="Pour une personne : ce qu'elle ferait maintenant envers elle (prendre la parole, la saluer, "
                      "prendre des nouvelles…), dans combien de temps en moyenne, et ce qui la retient. Lecture "
                      "seule : rien n'est déclenché.")
async def towards(ui: Any, request: Request) -> Any:
    values, notes = read_params(PERSON_PARAMS, request.query_params)
    wanted = str(values["personne"] or "")
    kernel = ui.kernel
    rows = kernel.arbiter.rows(kernel.mind.frame())
    people = sorted({r.target for r in rows if r.target not in ("", "none", "any") and ":" not in r.target})
    out: list[Any] = [Note(n, "warn") for n in notes]
    if not wanted:
        chips = tuple(Ref("local", "/inspecteur/decisions/envers", ui.names.who(h), (("personne", h),))
                      for h in people)
        out.append(Note("Choisis une personne (son nom ou son adresse) : la console montre les lignes de l'arbitre "
                        "qui la concernent, et celles qui visent « n'importe qui de présent ».", "info"))
        if chips:
            out.append(Table(("personne",), tuple((c,) for c in chips), title="Personnes dont une ligne existe"))
        return {"blocks": out, "filters": PERSON_PARAMS, "values": values}
    handles = set(ui.names.handles_named(wanted, ui.inspection.search))
    mine = [r for r in rows if r.target in handles]
    shared = [r for r in rows if r.target == "any"]
    if not handles:
        out.append(Note(f"Personne ne correspond à « {wanted[:80]} ».", "warn"))
        return {"blocks": out, "filters": PERSON_PARAMS, "values": values}
    who = ui.names.who(next(iter(sorted(handles))))
    live_ = [r for r in mine if r.hazard > 0 and not r.vetoes]
    total = sum(r.hazard for r in live_)
    best = max(mine, key=lambda r: r.score, default=None)
    if live_:
        top = max(live_, key=lambda r: r.hazard)
        mean_s = 1 / total if total > 0 else math.inf
        verdict = (f"Elle pourrait {_verb(top.kind)} {who} : à ce rythme, en moyenne dans "
                   f"{_delay(mean_s)} (si rien ne change d'ici là). La ligne la plus forte : "
                   f"{evidence_text(ui, top).splitlines()[0] if top.parts else names.kind(top.kind)}.")
        tone = "ok"
    elif best is not None and best.vetoes:
        verdict = f"Rien pour l'instant : {vetoes_text(ui, best).lower()} (veto)."
        tone = "warn"
    elif best is not None:
        verdict = (f"Rien pour l'instant : la ligne la plus forte reste sous son seuil (score "
                   f"{_signed(best.score)}).")
        tone = "muted"
    else:
        verdict = f"Rien ne la pousse vers {who} en ce moment : aucune ligne de l'arbitre ne la concerne."
        tone = "muted"
    out.append(Note(verdict, tone, title=f"Envers {who}"))
    out.append(Table(ARBITER_COLUMNS, arbiter_rows(ui, sorted(mine, key=lambda r: -r.score)),
                     title=f"Ses lignes envers {who}", empty="Aucune ligne ne la vise en propre."))
    if shared:
        out.append(Disclosure("Ce qui vise n'importe qui de présent", (
            Table(ARBITER_COLUMNS, arbiter_rows(ui, shared), title="Lignes sans cible précise"),)))
    return {"blocks": out, "filters": PERSON_PARAMS, "values": values}


def _verb(kind: str) -> str:
    return {"INITIATIVE": "prendre la parole envers", "REPLY": "répondre à", "MURMUR": "murmurer pour"}.get(
        kind, f"lancer « {names.kind(kind)} » envers")


def _delay(seconds: float) -> str:
    if not math.isfinite(seconds):
        return "un temps indéfini"
    if seconds < 90:
        return f"{num_fr(seconds, 0)} s"
    if seconds < 5400:
        return f"{num_fr(seconds / 60, 0)} min"
    if seconds < 2 * 86_400:
        return f"{num_fr(seconds / 3600, 1)} h"
    return f"{num_fr(seconds / 86_400, 1)} jours"


@TABS.tab("decisions.selections", title="Ses choix",
          description="Chaque initiative décidée, le tirage qui l'a acceptée, et les lignes au moment du choix.")
async def selections(ui: Any, request: Request) -> list[Any]:
    ctx = ui.inspection.context(request.query_params)
    chosen, pager = ctx.older(["kernel.selected"], SELECTIONS_PAGE)
    rows = []
    for e in chosen:
        d = e.data
        fired = frozenset(d.fired)
        rows.append(Row((When(e.at), ", ".join(_fired(ui, k) for k in d.fired) or "—", num_fr(d.draw, 3),
                         Text(f"{_rate(getattr(d, 'total', 0.0))} / {_rate(getattr(d, 'bound', 0.0))}", "num")
                         if getattr(d, "bound", 0.0) else "—",
                         getattr(d, "candidates", 0) or len(d.rows)), href=Ref("event", str(e.seq), ""),
                        detail=tuple(selection_detail(ui, d, fired))))
    return [Table((Column("quand", "fit"), "choisi", Column("tirage", "num"),
                   Column("Σ taux / borne (fois / h)", "num", hint="l'intensité totale et la borne de l'amincissement"),
                   Column("lignes", "num")), tuple(rows),
                  title="Ses dernières initiatives décidées", empty="Elle n'a encore rien décidé d'elle-même.",
                  pager=pager)]


def _fired(ui: Any, key: str) -> str:
    kind, _, target = key.partition(":")
    return ui.names.arbiter_row(kind, target)


def selection_detail(ui: Any, d: Any, fired: frozenset[str]) -> list[Any]:
    """Le détail d'un choix de l'arbitre : le tirage en clair, puis les lignes (la choisie en vert)."""
    out: list[Any] = []
    bound, total = getattr(d, "bound", 0.0), getattr(d, "total", 0.0)
    if bound and total:
        out.append(Note(f"Tirage {num_fr(d.draw, 3)} × borne {_rate(bound)} fois / h = {_rate(d.draw * bound)} fois / h, "
                        f"sous l'intensité totale de {_rate(total)} fois / h : l'occurrence est acceptée, et la "
                        "ligne est choisie au prorata de son taux.", "info"))
    out.append(Table(ARBITER_COLUMNS, arbiter_rows(ui, d.rows, fired=fired), title="Les lignes au moment du choix"))
    return out


EPISODE_PARAMS = (
    Param("sorte", "sorte", "select", tuple(KINDS.items())),
    Param("issue", "issue", "select", tuple((k, v[0]) for k, v in OUTCOMES.items())),
    Param("cible", "vers", "search", placeholder="un nom (Adrien) ou une adresse"),
)


@TABS.tab("decisions.episodes", title="Épisodes",
          description="Tout ce qu'elle a fait (répondre, prendre la parole, travailler, rêver…) et comment ça "
                      "s'est terminé.")
async def episodes(ui: Any, request: Request) -> Any:
    ctx = ui.inspection.context(request.query_params)
    values, notes = read_params(EPISODE_PARAMS, request.query_params)
    before = ctx.int_param("avant", 0) or None
    # « vers » : un nom tapé (« Adrien ») vise toutes ses adresses ; une adresse exacte, elle seule
    targets: set[str] | None = None
    if values["cible"]:
        targets = set(ui.names.handles_named(values["cible"], ui.inspection.search)) or {values["cible"]}
    where = ("kind", values["sorte"]) if values["sorte"] else ("outcome", values["issue"]) if values["issue"] else \
        ("target", next(iter(targets))) if targets is not None and len(targets) == 1 else None

    def matches(e: Any) -> bool:
        return (not values["sorte"] or e.data.kind == values["sorte"]) and \
            (not values["issue"] or e.data.outcome == values["issue"]) and \
            (targets is None or (e.data.target or "") in targets)

    # une page de filtrés : lire par lots jusqu'à la remplir (et un de plus), reprendre après le dernier montré
    shown: list[Any] = []
    cursor = before
    batch: list[Any] = []
    for _ in range(EPISODE_SCAN_BATCHES):
        batch = ctx.events([rt.EPISODE_ENDED], EPISODE_SCAN, where=where, before=cursor)
        for e in batch:
            if matches(e):
                shown.append(e)
                if len(shown) > EPISODES_PAGE:
                    break
        if len(shown) > EPISODES_PAGE or len(batch) < EPISODE_SCAN:
            break
        cursor = batch[-1].seq
    more = len(shown) > EPISODES_PAGE
    shown = shown[:EPISODES_PAGE]
    rows = tuple(episode_row(ui, e) for e in shown)
    stopped = not more and len(batch) == EPISODE_SCAN
    older = shown[-1].seq if more else cursor if stopped else None
    if older:
        pager = Pager(older=(("avant", str(older)),))
    elif not before:
        pager = Pager(param="avant", size=max(1, len(shown)), total=len(shown))
    else:
        pager = Pager(param="avant")
    now = ui.now()
    sampled = ctx.events([rt.EPISODE_ENDED], 1000)
    recent = [e for e in sampled if matches(e)]
    per_day: Counter[str] = Counter()
    stamps: dict[str, int] = {}
    for e in recent:
        if now - e.at > 14 * DAY:
            continue
        day = datetime.fromtimestamp(e.at / US, ui.tz).strftime("%Y-%m-%d")
        per_day[day] += 1
        stamps[day] = min(stamps.get(day, e.at), e.at)
    chart = Chart((Series("épisodes", tuple((stamps[d], float(n)) for d, n in sorted(per_day.items())), 1),),
                  kind="bars", title="Épisodes par jour (14 jours)", table=False, since=now - 14 * DAY,
                  until=now) if per_day else None
    counts = Counter(e.data.outcome for e in recent if now - e.at <= DAY)
    stats = Stats(tuple(Stat(names.outcome(k)[0], n, "dernières 24 h", names.outcome(k)[1])
                        for k, n in counts.most_common()))
    out: list[Any] = [Note(n, "warn") for n in notes]
    if values["cible"] and targets == {values["cible"]} and not ui.names.handles_named(values["cible"],
                                                                                        ui.inspection.search):
        out.append(Note(f"Personne ne s'appelle « {values['cible'][:80]} » : filtre sur cette adresse exacte.", "info"))
    if stopped:
        out.append(Note("La recherche continue dans les épisodes plus anciens : utilise « Plus anciens ».", "info"))
    out.append(Table((Column("quand", "fit"), "épisode", "vers", "issue", "détail"), rows, title="Épisodes",
                     empty="Aucun épisode ne correspond." if where or targets else "Aucun épisode encore.",
                     pager=pager, filters=("sorte", "issue", "cible")))
    activity = ([stats] if counts else []) + ([chart] if chart else [])
    if len(sampled) == 1000:
        activity.append(Note("Indicateurs calculés sur les 1 000 derniers épisodes, avec les filtres actuels. "
                             "Le tableau permet de parcourir tout l'historique.", "info"))
    if activity:
        out.append(Disclosure("Activité correspondant aux filtres", tuple(activity)))
    return {"blocks": out, "filters": EPISODE_PARAMS, "values": values}


@TABS.tab("decisions.echeances", title="Échéances",
          description="Quand chaque processus tournera la prochaine fois.")
async def schedule(ui: Any, request: Request) -> list[Any]:
    kernel = ui.kernel
    sched = kernel.scheduler
    frame = kernel.mind.frame()
    rows = []
    for spec in sched.specs:
        due: Any = call(sched.instances[spec.name].next_due, frame.root.slices.get(spec.owner), frame,
                        sched.last_run(spec.name), label=f"échéance de {spec.name}")
        nd = None if isinstance(due, Failed) else due
        failing = sched.consecutive.get(spec.name, 0)
        rows.append((nd if nd is not None else 1 << 62, Row((
            Text(ui.names.process(spec.name), hint=spec.name), ui.names.faculty(spec.owner),
            Text(names.lane(spec.lane), hint=spec.lane), When(nd) if nd else Text("rien de prévu", "muted"),
            When(sched.last_run(spec.name) or 0) if sched.last_run(spec.name) else "—",
            sched.runs.get(spec.name, 0), Badge(f"{failing} d'affilée", "danger") if failing else "—",
            Text(spec.name, "mono")),
            tone="danger" if failing >= 3 else "muted" if nd is None else "")))
    rows.sort(key=lambda x: x[0])
    running = set(sched.running())
    return [Stats((Stat("Processus", len(sched.specs)),
                   Stat("En cours", len(running), ", ".join(ui.names.process(p) for p in sorted(running)))),),
            Table(("processus", "faculté", "voie", "prochaine fois", "dernière fois", Column("passages", "num"),
                   "échecs", Column("nom technique", detail=True)), tuple(r for _, r in rows),
                  title="Ce qui tournera, et quand")]
