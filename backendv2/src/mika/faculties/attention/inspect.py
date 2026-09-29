"""La vue d'inspection de l'attention : ses pensées vivantes (telles qu'elle
les lit à l'instant, demi-vie comprise), ce qu'elle attend, et ce qu'elle a
remarqué récemment (après habituation).

Lecture seule, bornée ; une pensée dont l'oubli a effacé le texte se montre
comme telle.
"""

from __future__ import annotations

from mika.contracts import attention as c
from mika.contracts import identity as identity_c
from mika.faculties.attention.faculty import ATTENTION, AttentionState, habituation, params
from mika.faculties.attention.watch import met
from mika.kernel.clock import HOUR, MINUTE
from mika.kernel.frame import Frame
from mika.kernel.inspect import Block, Cell, Fields, InspectContext, Ref, Table
from mika.vocab import affect as A

SHOWN = 32
TEXT_MAX = 300
FORGOTTEN = "(oublié)"

ORIGIN_FR = {c.EXCHANGE: "un échange", c.REVISION: "une croyance révisée", c.MISSING: "un manque",
             c.BLOCKED: "un but bloqué", c.SIGNAL: "un signal"}
EXPECTED_FR = {c.REPLY: "sa réponse", c.RETURN: "son retour"}


def number(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def clip(text: str, n: int = TEXT_MAX) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def feeling(name: str) -> str:
    e = A.emotion_of(name)
    return A.FR.get(e, name) if e is not None else (name or "—")


def names(frame: Frame, keys: tuple[str, ...]) -> str:
    out = [k[5:].title() if k.startswith("name:") else (frame.get(identity_c.IDENTITY(k)).name or k) for k in keys]
    return ", ".join(out) or "personne"


def _thoughts(s: AttentionState, frame: Frame, ctx: InspectContext) -> Table:
    thoughts = frame.get(c.THOUGHTS)[:SHOWN]
    texts = ctx.store.content([t.text_ref for t in thoughts if t.text_ref])
    rows = []
    for t in thoughts:
        kept = s.thoughts.get(t.id)
        rows.append((
            Ref("event", str(t.id), f"#{t.id}"),
            clip(texts[t.text_ref]) if t.text_ref in texts else FORGOTTEN,
            feeling(t.emotion),
            number(t.intensity),
            ORIGIN_FR.get(t.origin, t.origin),
            names(frame, t.about),
            t.bundle or "—",
            ctx.when(t.born_at),
            ctx.when(kept.touched_at) if kept is not None else "—",
        ))
    return Table(("n°", "pensée", "couleur", "intensité", "née de", "concerne", "outils", "née le", "ravivée le"),
                 tuple(rows), title="Ce qui lui trotte dans la tête", empty="rien ne lui trotte dans la tête")


def _expectations(s: AttentionState, frame: Frame, ctx: InspectContext) -> Table:
    done = set(met(s, frame))
    rows: list[tuple[Cell, ...]] = []
    for key, x in sorted(s.expectations.items(), key=lambda kv: (kv[1].since, kv[0]))[:SHOWN]:
        if key in done:
            status = "comblée (pas encore constatée)"
        elif x.deadline is not None and x.deadline <= frame.now:
            status = "échue (pas encore constatée)"
        else:
            status = "en cours"
        rows.append((EXPECTED_FR.get(x.kind, x.kind), names(frame, (x.person,)), ctx.when(x.since),
                     ctx.when(x.deadline) if x.deadline is not None else "sans échéance", status))
    for person, since in sorted(s.late.items(), key=lambda kv: (kv[1], kv[0]))[:SHOWN]:
        status = "venue en retard (pas encore constatée)" if f"late:{person}" in done else \
            "manquée — une réponse tardive compte encore"
        rows.append((EXPECTED_FR[c.REPLY], names(frame, (person,)), ctx.when(since), "passée", status))
    return Table(("elle attend", "de", "depuis", "échéance", "état"), tuple(rows), title="Ce qu'elle attend",
                 empty="elle n'attend rien de personne")


def _noticed(s: AttentionState, ctx: InspectContext) -> Table:
    rows = tuple((
        ctx.when(h.at),
        Ref("event", str(h.signal), h.source) if h.signal else h.source,
        h.kind,
        number(h.pertinence),
        number(h.weight),
        number(h.pertinence * h.weight),
        number(h.intensity) if h.intensity else "rien",
    ) for h in reversed(s.heard[-SHOWN:]))
    return Table(("quand", "source", "sorte", "pertinence annoncée", "poids (habituation)", "pertinence retenue",
                  "émotion dosée"), rows, title="Ce qu'elle a remarqué récemment",
                 empty="rien de remarqué ces dernières minutes")


def _waiting(s: AttentionState, frame: Frame, ctx: InspectContext) -> Table:
    p = params(frame.env.params_of("attention", frame.root))
    texts = ctx.store.content([x.summary_ref for x in s.signals if x.summary_ref])
    rows = []
    for x in reversed(s.signals[-SHOWN:]):
        weight, _room = habituation(s, x.source, x.kind, frame.now, p)
        summary = clip(texts[x.summary_ref], 160) if x.summary_ref in texts else FORGOTTEN
        rows.append((ctx.when(x.at), Ref("event", str(x.seq), x.source), x.kind, summary, number(x.pertinence),
                     number(x.pertinence * weight)))
    return Table(("signalé le", "source", "sorte", "résumé", "pertinence annoncée", "retenue si remarqué maintenant"),
                 tuple(rows), title="Signalé, pas encore remarqué", empty="rien en attente")


@ATTENTION.inspect("pensees", title="Pensées")
def _inspect(s: AttentionState, frame: Frame, ctx: InspectContext) -> list[Block]:
    p = params(frame.env.params_of("attention", frame.root))
    summary = Fields((
        ("pensées gardées", len(s.thoughts)),
        ("pensées à écrire", len(s.pending)),
        ("initiatives sans réponse d'affilée", s.ignored),
        ("y a repensé pour la dernière fois", ctx.when(s.dwelt_at) if s.dwelt_at else "jamais"),
        ("dernière nuit digérée", s.digested_night or "—"),
        ("demi-vie d'une pensée", f"{p.half_life_us / HOUR:g} h ; s'éteint sous {number(p.fade_below)}"),
        ("habituation", f"× {number(p.habituation_factor)} par répétition en {p.habituation_window_us // MINUTE} min, "
                        f"jamais sous {number(p.habituation_floor)} ; une pensée naît d'un signal "
                        f"à partir de {number(p.signal_thought_from)}"),
    ), title="En bref")
    blocks: list[Block] = [summary, _thoughts(s, frame, ctx), _expectations(s, frame, ctx), _noticed(s, ctx)]
    if s.signals:
        blocks.append(_waiting(s, frame, ctx))
    return blocks
