"""Ce qu'``others`` montre à un opérateur : sur la fiche d'une personne, ce
qu'elle en devine — son ton habituel et du moment, ses délais de réponse, les
heures où elle répond, et les dernières lectures (surprises, inquiétudes).

Lecture seule ; les lectures viennent du journal (``ctx.events``).
"""

from __future__ import annotations

from mika.contracts import others as c
from mika.faculties.others.faculty import OTHERS, OthersState, band_of, params, receptivity
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
    Ref,
    Stat,
    Stats,
    Table,
    Text,
    When,
)
from mika.vocab.people import is_identifiable

BANDS_FR = {c.NIGHT: "la nuit (0 h – 6 h)", c.MORNING: "le matin (6 h – 12 h)",
            c.AFTERNOON: "l'après-midi (12 h – 18 h)", c.EVENING: "le soir (18 h – minuit)"}
CLASSES_FR = {c.SCREEN: "à l'écran", c.MESSAGE: "par messagerie"}
#: ses lectures, par page (tout l'historique se feuillette)
READS_PAGE = 25


def tone_words(valence: float) -> str:
    """Un ton en mots (la console, pas le prompt : le prompt ne dit jamais un nombre)."""
    if valence <= -0.5:
        return "lourd"
    if valence <= -0.15:
        return "plutôt sombre"
    if valence < 0.15:
        return "neutre"
    if valence < 0.5:
        return "plutôt léger"
    return "enjoué"


def _duration(us: int) -> str:
    if us < HOUR:
        return f"{max(1, round(us / MINUTE))} min"
    return f"{us / HOUR:.1f} h"


def _ratio(x: float) -> Meter:
    return Meter(x, f"{round(x * 100)} %")


@OTHERS.inspect("devine", title="Ce qu'elle devine", subject="person", order=35,
                description="Son ton habituel et du moment, ses délais de réponse, les heures où elle répond, et ce "
                            "qui l'a surprise ou inquiétée.")
def _guessed(s: OthersState, frame: Frame, ctx: InspectContext) -> list[Block]:
    person = ctx.subject
    if not person:
        return [Note("Ouvre la fiche d'une personne : Personnes, puis la personne.", tone="muted")]
    if not is_identifiable(person):
        return [Note("Une connexion de passage : elle n'en garde aucun modèle.", tone="muted")]
    p = params(frame.env.params_of("others", frame.root))
    r = frame.get(c.MIND(person))
    blocks: list[Block] = []
    if not r.observed:
        blocks.append(Note("Elle n'a encore lu aucun message de cette personne.", tone="muted"))
    else:
        tone = "warn" if abs(r.deviation) >= p.notable_deviation and r.confidence >= 1.0 else ""
        blocks.append(Stats((
            Stat("ton habituel", tone_words(r.usual_valence), f"valence {r.usual_valence:+.2f}"),
            Stat("en ce moment", tone_words(r.current_valence), f"écart {r.deviation:+.2f}", tone=tone),
            Stat("la connaît", _ratio(r.confidence), f"{r.observed} message(s) lu(s)"),
            Stat("dernier message lu", When(r.last_at) if r.last_at else Text("—", kind="muted")),
        )))
        if r.last_cues:
            blocks.append(Fields((("indices du dernier message", " ; ".join(r.last_cues)),)))
    delays = []
    for klass in (c.SCREEN, c.MESSAGE):
        samples = s.delays.get(f"{person}|{klass}", ())
        if samples:
            reading = frame.get(c.REPLY_DELAY((person, "telegram" if klass == c.MESSAGE else "web")))
            delays.append((CLASSES_FR[klass], reading.samples, _duration(reading.median_us),
                           _duration(max(samples))))
    blocks.append(Table((Column("canal"), Column("réponses mesurées", "num"), Column("délai habituel", "num"),
                         Column("le plus long", "num")), tuple(delays), title="Ses délais de réponse",
                        empty="aucune mesure : elle ne lui a encore jamais écrit d'elle-même"))
    now_band = band_of(frame.local().hour)
    rows: list[tuple[Cell, ...]] = []
    for band in c.BANDS:
        answered, missed, estimate, shift = receptivity(s, person, band, p)
        effect: Cell = (Badge(f"{shift:+.2f}", "ok" if shift > 0 else "warn") if shift else
                        Text("aucun", kind="muted"))
        rows.append((BANDS_FR[band] + (" — maintenant" if band == now_band else ""), f"{answered:g}", f"{missed:g}",
                     _ratio(estimate), effect))
    blocks.append(Table((Column("quand elle écrit"), Column("réponses", "num"), Column("sans réponse", "num"),
                         Column("chance d'une réponse"), Column("effet sur ses initiatives", "fit")), tuple(rows),
                        title="Les heures où elle répond",
                        caption="Chaque initiative comblée ou restée sans réponse, rangée au moment où elle l'a "
                                "écrite ; l'écart à l'a priori rend la suivante à cette heure plus ou moins probable."))
    before = ctx.int_param("avant", 0) or None
    got = ctx.events([c.READ], READS_PAGE + 1, where=("person", person), before=before)  # filtré par le journal
    reads, more = got[:READS_PAGE], len(got) > READS_PAGE
    blocks.append(Table(
        (Column("quand", "fit"), Column("ton lu"), Column("attendu"), Column("surprise", "num"), Column("état"),
         Column("message", "fit")),
        tuple((When(e.at), tone_words(e.data.valence), tone_words(e.data.expected), f"{e.data.surprise:.2f}",
               Badge("inquiète", "warn") if e.data.concern else
               (Badge("surprise", "info") if e.data.surprise >= p.surprise_from else Text("—", kind="muted")),
               Ref("event", str(e.data.message), f"n° {e.data.message}")) for e in reads),
        title="Ses lectures, de la plus récente", empty="plus rien avant" if before else "aucune lecture encore",
        pager=Pager(param="avant", older=(("avant", str(reads[-1].seq)),) if more and reads else ())
        if more or before else None))
    return blocks
