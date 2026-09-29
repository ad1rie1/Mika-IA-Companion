"""Ce que l'affect montre à un opérateur : l'humeur, les postures.

Lecture seule : les lectures sont celles des faits (mêmes fonctions, même
instant), les balises déclarées viennent du fil de conversation.
"""

from __future__ import annotations

from mika.contracts import body as body_c
from mika.contracts import identity as identity_c
from mika.contracts import transcript as transcript_c
from mika.faculties.affect import (
    AFFECT,
    AffectState,
    _params,
    hostility,
    mood_reading,
    prose,
    regard,
    stance_reading,
)
from mika.faculties.affect import physics as ph
from mika.kernel.frame import Frame
from mika.kernel.inspect import Block, Fields, InspectContext, Note, Table
from mika.vocab import affect as A

#: au plus tant de postures (les plus récemment touchées d'abord)
STANCES_SHOWN = 100
#: les dernières balises déclarées
DECLARED_SHOWN = 10


def _vec(v: A.Vec3 | None) -> str:
    if v is None:
        return "—"
    return f"P {v[0]:+.2f} · A {v[1]:+.2f} · D {v[2]:+.2f}"


def _feeling(emotion: A.Emotion, intensity: float) -> str:
    return f"{A.FR[emotion]} ({intensity:.0%})"


def _who(frame: Frame, key: str) -> str:
    """Le nom qu'elle connaît à cette personne, et sa clé."""
    if not key:
        return "personne en particulier"
    name = frame.get(identity_c.IDENTITY(key)).name
    return f"« {name} » ({key})" if name else key


def _clockwork(frame: Frame) -> ph.Clockwork:
    return ph.Clockwork(frame.env.tz_of(frame.root), frame.get(body_c.RHYTHM))


def _declared_rows(frame: Frame, ctx: InspectContext) -> tuple[tuple[str, str, str, str], ...]:
    """Ses dernières balises, lues dans le fil (ce qu'elle a vraiment écrit)."""
    if ctx.store is None:
        return ()
    rows = ctx.store.query_mind(
        f"SELECT at, person, emotion, emotion_intensity, kind FROM {transcript_c.THREAD_TABLE} "
        "WHERE role='assistant' AND emotion IS NOT NULL ORDER BY id DESC LIMIT ?", (DECLARED_SHOWN,))
    out = []
    for at, person, name, intensity, kind in rows:
        emotion = A.emotion_of(str(name))
        label = A.FR[emotion] if emotion is not None else str(name)
        out.append((ctx.when(int(at)), _who(frame, str(person or "")), f"{label} ({float(intensity or 0):.0%})",
                    "en répondant" if kind == "REPLY" else "d'elle-même"))
    return tuple(out)


@AFFECT.inspect("humeur", title="Humeur")
def _mood_view(s: AffectState, frame: Frame, ctx: InspectContext) -> list[Block]:
    p = _params(frame.env.params_of("affect", frame.root))
    m = mood_reading(s, frame.now, p, _clockwork(frame))
    at_rest = A.distance(m.position, m.home) < p.rest_tolerance
    declared = _declared_rows(frame, ctx)
    return [
        Fields((
            ("ressentie (écart au repos)", "au repos" if at_rest else _feeling(m.felt, m.felt_intensity)),
            ("débordement", f"{m.overflow:.0%} (pousse à parler au-delà de {p.overflow_floor:.0%})"),
            ("lecture absolue (le visage)", _feeling(m.label, m.intensity)),
            ("position", _vec(m.position)),
            ("repos à cette heure", _vec(m.home)),
            ("son fond", A.FR[p.background]),
            ("dernière mise à jour", ctx.when(s.mood.at) if s.mood is not None else "jamais (au repos depuis toujours)"),
            ("dernière balise déclarée", f"{declared[0][2]} — {declared[0][0]}, {declared[0][1]}" if declared
             else "aucune"),
        ), title="Humeur générale"),
        Note(prose.mood(m, p)),
        Table(("quand", "à qui", "émotion déclarée", "comment"), declared, title="Dernières balises",
              empty="elle n'a encore rien déclaré"),
    ]


@AFFECT.inspect("postures", title="Postures")
def _stances_view(s: AffectState, frame: Frame, ctx: InspectContext) -> list[Block]:
    p = _params(frame.env.params_of("affect", frame.root))
    cw = _clockwork(frame)
    now = frame.now
    common = ph.common_home(now, p, cw)
    ordered = sorted(s.stances.items(), key=lambda kv: (-max(kv[1].declared_at, kv[1].osc.at), kv[0]))
    rows = []
    for person, stored in ordered[:STANCES_SHOWN]:
        r = stance_reading(s, person, now, p, cw)
        felt = "au repos" if r.at_rest else _feeling(r.felt, r.felt_intensity)
        if r.anchor is None:
            anchor = "aucune"
        else:
            label, intensity = A.felt(r.anchor, common)
            anchor = f"{_feeling(label, intensity)} — {_vec(r.anchor)}"
        last = A.Declared.decode(stored.declared)
        declared = f"{_feeling(last.emotion, last.intensity)}, {ctx.when(stored.declared_at)}" if last else "—"
        rows.append((
            _who(frame, person), felt, f"{regard(s, person, now, p, cw):+.2f}",
            f"{hostility(s, person, now, p, cw):.2f}", anchor, "oui" if r.anchored else "non", declared,
            prose.stance(r, common, p) or "—",
        ))
    blocks: list[Block] = [Table(
        ("personne", "ressentie envers elle", "chaleur (−1…1)", "hostilité", "ancre (ce qui s'est installé)",
         "ancrée", "dernière balise", "ce qu'elle se dit"),
        tuple(rows), title="Postures envers chacun", empty="aucune posture : personne ne l'a encore touchée")]
    if len(ordered) > STANCES_SHOWN:
        blocks.append(Note(f"{len(ordered) - STANCES_SHOWN} postures plus anciennes ne sont pas affichées.", tone="mut"))
    return blocks
