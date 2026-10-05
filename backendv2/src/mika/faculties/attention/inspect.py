"""Les vues d'inspection de l'attention : ses pensées vivantes (telles qu'elle
les lit à l'instant, demi-vie comprise), ce qu'elle a remarqué (habituation
et dosage compris), ce qu'elle attend ; et l'onglet « Pensées » de la fiche
d'une personne.

Lecture seule, bornée ; une pensée dont l'oubli a effacé le texte se montre
comme telle.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from mika.contracts import attention as c
from mika.contracts import identity as identity_c
from mika.faculties.attention.faculty import ATTENTION, AttentionState, due_at, habituation, params, unseen
from mika.faculties.attention.watch import met
from mika.kernel.clock import HOUR, MINUTE
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    Badge,
    Block,
    Cell,
    Column,
    Fields,
    InspectContext,
    Meter,
    Note,
    Pager,
    Prose,
    Ref,
    Row,
    Stat,
    Stats,
    Table,
    Text,
    When,
    num_fr,
)
from mika.vocab.affect import emotion_cell
from mika.vocab.privacy import Sensitivity

FORGOTTEN = "(oublié)"
CLAMP = 160
#: une page de l'historique (pensées nées, signaux remarqués, attentes closes)
HISTORY = 25

ORIGIN_FR = {c.EXCHANGE: "un échange", c.REVISION: "une croyance révisée", c.MISSING: "un manque",
             c.BLOCKED: "un but bloqué", c.SIGNAL: "un signal", c.CONCERN: "une inquiétude",
             c.PROMISE: "une promesse non tenue", c.UNANSWERED: "une initiative sans réponse",
             c.ALONE: "personne ne lui écrit", c.REMORSE: "elle a été dure avec quelqu'un"}
EXPECTED_FR = {c.REPLY: "sa réponse", c.RETURN: "son retour", c.PROMISE: "tenir sa promesse"}
SENSITIVITY_FR = {int(Sensitivity.NONE): "rien d'autrui", int(Sensitivity.ANODYNE): "anodin",
                  int(Sensitivity.PERSONAL): "personnel", int(Sensitivity.CONFIDENCE): "confidence"}


def number(value: float) -> str:
    return num_fr(value, 2)


def _p(frame: Frame) -> Any:
    return params(frame.env.params_of("attention", frame.root))


def _name(frame: Frame, key: str) -> str:
    return key[5:].title() if key.startswith("name:") else (frame.get(identity_c.IDENTITY(key)).name or key)


def person_ref(frame: Frame, key: str, tab: str = "pensees_personne") -> Cell:
    """Un lien vers la fiche d'une personne qu'elle connaît ; sinon son nom."""
    if key.startswith("name:") or not frame.get(identity_c.IDENTITY(key)).known:
        return Text(_name(frame, key), hint="connue seulement de nom")
    return Ref.subject("person", key, _name(frame, key), tab)


def about_cell(frame: Frame, about: Sequence[str]) -> Cell:
    if not about:
        return Text("personne", kind="muted")
    if len(about) == 1:
        return person_ref(frame, about[0])
    return Text(", ".join(_name(frame, a) for a in about), hint="plusieurs personnes : voir le détail")


def person_keys(frame: Frame, key: str) -> set[str]:
    """Toutes les clés sous lesquelles cette personne peut figurer."""
    person = frame.get(identity_c.PERSON(key)) or key
    return {key, person, *frame.get(identity_c.HANDLES(person)), *frame.get(identity_c.HANDLES(key))}


def _text(texts: dict[str, str], ref: str) -> Text:
    return Text(texts[ref], clamp=CLAMP) if ref in texts else Text(FORGOTTEN, kind="muted")


def _page(ctx: InspectContext, types: Sequence[Any], size: int) -> tuple[list[Any], Pager]:
    """Une page de l'historique (du plus récent au plus ancien) : on en lit une
    de plus pour savoir s'il reste plus ancien — « plus anciens » ne mène
    jamais à une page vide."""
    events = list(ctx.events(list(types), size + 1, before=_before(ctx)))
    page = events[:size]
    if len(events) > size:
        return page, Pager(param="avant", size=size, older=(("avant", str(page[-1].seq)),))
    return page, Pager(param="avant", size=size)


def _before(ctx: InspectContext) -> int | None:
    n = ctx.int_param("avant", 0)
    return n if n > 0 else None


# ── Pensées ───────────────────────────────────────────────────────────────


def _thought_rows(s: AttentionState, frame: Frame, ctx: InspectContext,
                  keep: set[str] | None = None) -> tuple[Row, ...]:
    p = _p(frame)
    thoughts = [t for t in frame.get(c.THOUGHTS) if keep is None or keep & set(t.about)]
    texts = ctx.store.content([t.text_ref for t in thoughts if t.text_ref])
    rows = []
    for t in thoughts:
        kept = s.thoughts.get(t.id)
        detail: list[Block] = [
            Fields((
                ("l'événement", Ref("event", str(t.id), f"n° {t.id}")),
                ("née de", ORIGIN_FR.get(t.origin, t.origin)),
                *(("concerne", person_ref(frame, a)) for a in t.about),
                ("sensibilité", SENSITIVITY_FR.get(t.sensitivity, str(t.sensitivity))),
                ("intensité à la dernière ravivée", number(kept.intensity) if kept is not None else "—"),
                ("s'éteint", f"sous {number(p.fade_below)} (demi-vie {num_fr(p.half_life_us / HOUR)} h)"),
                ("outils qui vont avec", t.bundle or "aucun"),
            ), title="Détail"),
            Prose(texts.get(t.text_ref) or FORGOTTEN, title="En entier"),
        ]
        rows.append(Row((
            Ref("event", str(t.id), f"#{t.id}"),
            _text(texts, t.text_ref),
            emotion_cell(t.emotion, t.intensity),
            Meter(t.intensity, number(t.intensity)),
            ORIGIN_FR.get(t.origin, t.origin),
            about_cell(frame, t.about),
            When(t.born_at),
            When(kept.touched_at) if kept is not None else None,
        ), detail=tuple(detail), tone="muted" if t.text_ref not in texts else ""))
    return tuple(rows)


THOUGHT_COLUMNS = (Column("n°", "fit", detail=True), Column("pensée"), Column("couleur"),
                   Column("intensité", hint="ce qu'il en reste à l'instant (demi-vie)"), Column("née de", detail=True),
                   Column("concerne"), Column("née", "fit"), Column("ravivée", "fit", detail=True))


def _history(frame: Frame, ctx: InspectContext) -> Table:
    alive = {t.id for t in frame.get(c.THOUGHTS)}
    events, pager = _page(ctx, [c.THOUGHT_BORN], HISTORY)
    rows = []
    for e in events:
        d = e.data
        text = d.text.text
        rows.append(Row((
            Ref("event", str(e.seq), f"#{e.seq}"),
            Text(text, clamp=CLAMP) if text else Text(FORGOTTEN, kind="muted"),
            emotion_cell(d.emotion, d.intensity),
            ORIGIN_FR.get(d.origin, d.origin),
            about_cell(frame, d.about),
            When(e.at),
            Badge("vivante", "info") if e.seq in alive else Badge("éteinte", "muted"),
        ), detail=(Prose(text or FORGOTTEN, title="En entier"),) if text and len(text) > CLAMP else ()))
    return Table((Column("n°", "fit", detail=True), Column("pensée"), Column("couleur à la naissance", detail=True), Column("née de", detail=True),
                  Column("concerne"), Column("née", "fit"), Column("maintenant", "fit")), tuple(rows),
                 title="Toutes ses pensées, de la plus récente à la plus ancienne",
                 empty="plus rien avant" if _before(ctx) else "pas encore de pensée", pager=pager)


@ATTENTION.inspect("pensees", title="Pensées", section="pensees", order=10,
                   description="Ce qui lui trotte dans la tête : née d'un échange qui l'a marquée, d'une croyance "
                               "révisée, d'un manque, d'un but bloqué ou d'un signal ; ça s'estompe, ça revient, "
                               "ça s'allège quand elle en parle.")
def _inspect_thoughts(s: AttentionState, frame: Frame, ctx: InspectContext) -> list[Block]:
    p = _p(frame)
    rows = _thought_rows(s, frame, ctx)
    stats = Stats((
        Stat("Pensées vivantes", len(rows), f"au plus {p.max_thoughts}"),
        Stat("Pensées à écrire", len(s.pending), "nées, pas encore formulées", "info" if s.pending else ""),
        Stat("Initiatives sans réponse", s.ignored, "d'affilée, toutes personnes", "warn" if s.ignored >= 2 else ""),
        Stat("Y a repensé", When(s.dwelt_at) if s.dwelt_at else "jamais", f"au plus toutes les "
             f"{p.dwell_every_us // MINUTE} min, dès {number(p.dwell_from)}"),
    ))
    live = Table(THOUGHT_COLUMNS, rows, title="Ce qui lui trotte dans la tête",
                 empty="rien ne lui trotte dans la tête")
    rules = Fields((
        ("demi-vie d'une pensée", f"{num_fr(p.half_life_us / HOUR)} h ; s'éteint sous {number(p.fade_below)}"),
        ("un échange qui marque", f"émotion déclarée ≥ {number(p.marking_intensity)}, ou valence ≤ "
                                  f"{number(p.marking_valence)} ; au plus {p.exchange_cap} à la fois"),
        ("dernière nuit digérée", s.digested_night or "—"),
    ), title="Comment elles vivent")
    return [stats, live, _history(frame, ctx), rules]


# ── Remarqué ──────────────────────────────────────────────────────────────


def _dosed(emotion: str, intensity: float) -> Cell:
    return emotion_cell(emotion, intensity) if emotion and intensity > 0 else Text("rien", kind="muted")


def _recent(s: AttentionState, ctx: InspectContext) -> Table:
    heard = list(reversed(s.heard))  # borné par l'état ; le rendu pagine
    noticed = {e.data.signal: e.data for e in ctx.events([c.NOTICED], max(1, len(heard)))}
    rows = []
    for h in heard:
        d = noticed.get(h.signal)
        rows.append((
            When(h.at),
            Ref("event", str(h.signal), h.source) if h.signal else h.source,
            h.kind,
            Meter(h.pertinence, number(h.pertinence)),
            Meter(h.weight, number(h.weight)),
            Meter(h.pertinence * h.weight, number(h.pertinence * h.weight)),
            _dosed(d.emotion if d is not None else "", h.intensity),
        ))
    return Table((Column("quand", "fit"), Column("source"), Column("sorte"), Column("pertinence annoncée"),
                  Column("poids (habituation)", hint="× facteur par répétition de la même source et sorte, "
                                                     "jamais sous le plancher"),
                  Column("pertinence retenue"), Column("émotion dosée")), tuple(rows),
                 title="Remarqué ces dernières minutes", empty="rien de remarqué ces dernières minutes")


def _waiting(s: AttentionState, frame: Frame, ctx: InspectContext) -> Table:
    p = _p(frame)
    texts = ctx.store.content([x.summary_ref for x in s.signals if x.summary_ref])
    rows = []
    for x in reversed(s.signals):
        weight, _room = habituation(s, x.source, x.kind, frame.now, p)
        rows.append((When(x.at), Ref("event", str(x.seq), x.source), x.kind, _text(texts, x.summary_ref),
                     Meter(x.pertinence, number(x.pertinence)),
                     Meter(x.pertinence * weight, number(x.pertinence * weight))))
    return Table((Column("signalé", "fit"), Column("source"), Column("sorte"), Column("résumé"),
                  Column("pertinence annoncée"), Column("retenue si remarqué maintenant")), tuple(rows),
                 title="Signalé, pas encore remarqué", empty="rien en attente")


def _noticed_history(ctx: InspectContext) -> Table:
    events, pager = _page(ctx, [c.NOTICED], HISTORY)
    rows = tuple((When(e.at), Ref("event", str(e.data.signal), e.data.source), e.data.kind,
                  Meter(e.data.weight, number(e.data.weight)), _dosed(e.data.emotion, e.data.intensity))
                 for e in events)
    return Table((Column("quand", "fit"), Column("source"), Column("sorte"), Column("poids (habituation)"),
                  Column("émotion dosée")), rows, title="Tout ce qu'elle a remarqué",
                 empty="plus rien avant" if _before(ctx) else "rien de remarqué pour l'instant",
                 pager=pager)


@ATTENTION.inspect("remarque", title="Remarqué", section="pensees", order=20,
                   description="Ce que ses sens et ses sources lui signalent (courrier, flux, caméra, apps) : la "
                               "même source qui se répète se remarque de moins en moins, et une source ne lui fait "
                               "jamais plus qu'une petite émotion en quelques minutes.")
def _inspect_noticed(s: AttentionState, frame: Frame, ctx: InspectContext) -> list[Block]:
    p = _p(frame)
    rules = Fields((
        ("habituation", f"× {number(p.habituation_factor)} par répétition en {p.habituation_window_us // MINUTE} "
                        f"min, jamais sous {number(p.habituation_floor)}"),
        ("dosage", f"au plus {number(p.dose_cap)} d'émotion par source dans cette fenêtre"),
        ("une pensée naît d'un signal", f"à partir d'une pertinence retenue de {number(p.signal_thought_from)}"),
    ), title="Comment elle remarque")
    blocks: list[Block] = [_recent(s, ctx)]
    if s.signals:
        blocks.append(_waiting(s, frame, ctx))
    return [*blocks, _noticed_history(ctx), rules]


# ── Attentes ──────────────────────────────────────────────────────────────


def _expectation_rows(s: AttentionState, frame: Frame, keep: set[str] | None = None) -> tuple[tuple[Cell, ...], ...]:
    done = set(met(s, frame))
    p = _p(frame)
    rows: list[tuple[Cell, ...]] = []
    ordered = sorted(s.expectations.items(), key=lambda kv: (kv[1].since, kv[0]))
    for key, x in [kv for kv in ordered if keep is None or kv[1].person in keep]:
        when = due_at(x, s.exchanges.get(x.person), p)
        if key in done:
            status = Badge("comblée (pas encore constatée)", "ok")
        elif when is not None and when <= frame.now:
            status = Badge("échue (pas encore constatée)", "warn")
        elif unseen(x, s.exchanges.get(x.person)):
            status = Badge("pas encore lue : l'attente ne court pas", "info")
        else:
            status = Badge("en cours", "info")
        rows.append((EXPECTED_FR.get(x.kind, x.kind), person_ref(frame, x.person), When(x.since),
                     When(when) if when is not None else Text("sans échéance", kind="muted"), status))
    late = sorted(s.late.items(), key=lambda kv: (kv[1].since, kv[0]))
    for person, x in [kv for kv in late if keep is None or kv[0] in keep]:
        if f"late:{person}" in done:
            status = Badge("venue en retard (pas encore constatée)", "ok")
        elif x.until > frame.now:
            status = Badge("manquée — une réponse tardive compte encore", "danger")
        else:
            status = Badge("manquée — trop tard pour compter", "muted")
        rows.append((EXPECTED_FR[c.REPLY], person_ref(frame, person), When(x.since), When(x.until), status))
    return tuple(rows)


EXPECTATION_COLUMNS = (Column("elle attend"), Column("de"), Column("depuis", "fit"), Column("échéance", "fit"),
                       Column("état"))


def _closed(frame: Frame, ctx: InspectContext, events: Sequence[Any]) -> tuple[tuple[Cell, ...], ...]:
    return tuple((When(e.at), EXPECTED_FR.get(e.data.kind, e.data.kind), person_ref(frame, e.data.person),
                  When(e.data.since),
                  Badge("comblée", "ok") if e.type.name == c.EXPECTATION_MET.name else Badge("déçue", "danger"),
                  Ref("event", str(e.seq), f"n° {e.seq}")) for e in events)


CLOSED_COLUMNS = (Column("quand", "fit"), Column("elle attendait"), Column("de"), Column("depuis", "fit"),
                  Column("issue", "fit"), Column("événement", "fit"))


@ATTENTION.inspect("attentes", title="Attentes", section="pensees", order=30,
                   description="Ce qu'elle attend de quelqu'un : une réponse quand elle a écrit d'elle-même, un "
                               "retour quand quelqu'un lui manque. Une attente se comble ou se dément.")
def _inspect_expectations(s: AttentionState, frame: Frame, ctx: InspectContext) -> list[Block]:
    p = _p(frame)
    rows = _expectation_rows(s, frame)
    stats = Stats((
        Stat("En cours", len(s.expectations)),
        Stat("Réponses en retard", len(s.late), "une réponse tardive compte encore (trois fois le délai)",
             "warn" if s.late else ""),
        Stat("Initiatives sans réponse", s.ignored, "d'affilée", "warn" if s.ignored >= 2 else ""),
        Stat("Délai d'une réponse", f"{p.reply_window_us // MINUTE} min",
             f"{p.reply_window_message_us // MINUTE} min par message"),
    ))
    events, pager = _page(ctx, [c.EXPECTATION_MET, c.EXPECTATION_MISSED], HISTORY)
    return [stats, Table(EXPECTATION_COLUMNS, rows, title="Ce qu'elle attend", empty="elle n'attend rien de personne"),
            Table(CLOSED_COLUMNS, _closed(frame, ctx, events), title="Attentes closes",
                  empty="plus rien avant" if _before(ctx) else "aucune attente close pour l'instant",
                  pager=pager)]


# ── La fiche d'une personne ───────────────────────────────────────────────


def _thread(s: AttentionState, frame: Frame, key: str) -> Fields | None:
    """Le fil avec la personne, vu de son côté à elle : ce qui la retient de lui
    réécrire (ADR 0033) se lit ici."""
    ex = s.exchanges.get(frame.get(identity_c.PERSON(key)) or key)
    if ex is None:
        return None
    waiting = ("oui, une question" if ex.asked else "oui") if ex.unanswered else "non"
    if ex.seen_at:
        seen: Cell = When(ex.seen_at)
    elif 0 < ex.seen_upto < ex.initiative_seq:
        seen = "pas encore"
    else:
        seen = Text("on ne le sait pas", kind="muted")
    return Fields((
        ("la personne lui a écrit", When(ex.last_in) if ex.last_in else Text("pas encore", kind="muted")),
        ("elle lui a écrit", When(ex.last_out) if ex.last_out else Text("pas encore", kind="muted")),
        ("elle attend sa réponse (elle a écrit en dernier)", waiting),
        ("ses initiatives depuis, sans réponse", str(ex.initiatives)),
        ("dont le délai attendu est passé", str(ex.ignored)),
        ("elle a ressenti ce silence", "oui" if ex.felt else "non"),
        ("la personne a lu sa dernière initiative", seen),
    ), title="Le fil avec cette personne", columns=2,
        hints=(("ses initiatives depuis, sans réponse", "Après une, plus d'initiative ordinaire tant que la personne "
                "n'a pas écrit — sauf une relance douce, bien plus tard, vers une personne amie ou proche ; après deux, plus rien."),
               ("la personne a lu sa dernière initiative", "Ce que dit son application (« Lui dire quand j'ai lu »), "
                "par messagerie : pas encore lue, elle ne compte pas comme ignorée.")))

#: le type d'objet « personne » (déclaré par l'identité) : l'onglet se range sur sa fiche
PERSON_KIND = "person"


@ATTENTION.inspect("pensees_personne", title="Pensées", subject=PERSON_KIND, hidden=not PERSON_KIND, order=80,
                   description="Ce qui lui trotte dans la tête à propos de cette personne, et ce qu'elle en attend.")
def _person(s: AttentionState, frame: Frame, ctx: InspectContext) -> list[Block]:
    if not ctx.subject:
        return [Note("Choisissez une personne : cet onglet se lit sur sa fiche.", tone="muted")]
    keys = person_keys(frame, ctx.subject)
    before = _before(ctx)
    merged: list[Any] = []
    for key in sorted(keys):  # une lecture par adresse, fusionnées : une page de 25, un curseur commun
        merged += ctx.events([c.EXPECTATION_MET, c.EXPECTATION_MISSED], HISTORY + 1, where=("person", key),
                             before=before)
    merged = sorted({e.seq: e for e in merged}.values(), key=lambda e: -e.seq)
    closed = merged[:HISTORY]
    more = len(merged) > HISTORY
    thread = _thread(s, frame, ctx.subject)
    return [
        *((thread,) if thread is not None else ()),
        Table(THOUGHT_COLUMNS, _thought_rows(s, frame, ctx, keys), title="Ce qui lui trotte dans la tête à son sujet",
              empty="rien ne lui trotte dans la tête à son sujet"),
        Table(EXPECTATION_COLUMNS, _expectation_rows(s, frame, keys), title="Ce qu'elle en attend",
              empty="elle n'attend rien de cette personne"),
        Table(CLOSED_COLUMNS, _closed(frame, ctx, closed), title="Attentes closes",
              empty="plus rien avant" if before else "aucune attente close",
              pager=Pager(param="avant", older=(("avant", str(closed[-1].seq)),) if more and closed else ())
              if more or before else None),
    ]
