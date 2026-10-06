"""Ce que l'affect montre à un opérateur : l'humeur, les postures, sa courbe,
et sur la fiche d'une personne, ce qu'elle ressent envers elle.

Lecture seule : les lectures sont celles des faits (mêmes fonctions, même
instant), les balises déclarées viennent du fil de conversation, les courbes
des séries mesurées toutes les dix minutes (``affect.valence``,
``affect.eveil``).
"""

from __future__ import annotations

from mika.contracts import affect as c
from mika.contracts import body as body_c
from mika.contracts import identity as identity_c
from mika.contracts import transcript as transcript_c
from mika.faculties.affect import (
    AFFECT,
    AffectState,
    _params,
    hostility,
    prose,
    regard,
    stance_reading,
)
from mika.faculties.affect import physics as ph
from mika.faculties.affect.params import AffectParams
from mika.kernel.clock import DAY
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    Block,
    Cell,
    Chart,
    Column,
    Disclosure,
    Entry,
    Fields,
    InspectContext,
    Meter,
    Note,
    Pager,
    Param,
    Ref,
    Row,
    Series,
    Stat,
    Stats,
    Swatch,
    Table,
    Text,
    Timeline,
    Vital,
    When,
    num_fr,
    paginate,
    pct_fr,
)
from mika.vocab import affect as A
from mika.vocab import privacy
from mika.vocab.episodes import Kind
from mika.vocab.people import is_identifiable

#: les postures par page (les plus récemment touchées d'abord)
STANCES_PAGE = 50
#: ses balises déclarées, par page (tout l'historique, du plus récent au plus ancien)
DECLARED_PAGE = 25
EXCERPT = 160

#: la période des courbes
PERIODS = (("24h", "24 h"), ("7j", "7 jours"))
_SPANS = {"24h": DAY, "7j": 7 * DAY}
PERIOD = Param("periode", "Période", kind="select", choices=PERIODS, default="24h")


def _vec(v: A.Vec3 | None) -> str:
    if v is None:
        return "—"
    return " · ".join(f"{axis} {num_fr(x, 2, signed=True)}" for axis, x in zip("PAD", v, strict=True))


def _feeling(emotion: A.Emotion, intensity: float) -> str:
    return f"{A.FR[emotion]} ({pct_fr(intensity)})"


def _swatch(emotion: A.Emotion, intensity: float | None = None) -> Swatch:
    return Swatch(A.FR[emotion], "emotion", emotion.value, intensity)


def _declared_cell(name: object, intensity: object) -> Cell:
    """Une balise lue dans le fil : sa pastille, ou le nom brut s'il n'est pas l'une des 29."""
    emotion = A.emotion_of(str(name))
    if emotion is None:
        return Text(str(name), kind="muted")
    return _swatch(emotion, float(intensity or 0.0))


def _name(frame: Frame, key: str) -> str:
    """Le nom qu'elle connaît à cette personne (sa clé reste au survol, ou dans le lien de sa fiche) ; une
    adresse sans nom se lit par sa clé."""
    return frame.get(identity_c.IDENTITY(key)).name or key


def _who_text(frame: Frame, handle: str) -> str:
    return _name(frame, frame.get(identity_c.PERSON(handle))) if handle else "personne en particulier"


def _who(frame: Frame, handle: str, tab: str = "") -> Cell:
    """La personne derrière une adresse, en lien vers sa fiche (si c'est une personne)."""
    person = frame.get(identity_c.PERSON(handle)) if handle else ""
    if not is_identifiable(person):
        return Text(_who_text(frame, handle), kind="muted", hint=handle)
    return Ref.subject("person", person, _name(frame, person), tab)


def _clockwork(frame: Frame) -> ph.Clockwork:
    return ph.Clockwork(frame.env.tz_of(frame.root), frame.get(body_c.RHYTHM))


def _p(frame: Frame) -> AffectParams:
    return _params(frame.env.params_of("affect", frame.root))


def _at_rest(m: c.MoodReading, p: AffectParams) -> bool:
    return A.distance(m.position, m.home) < p.rest_tolerance


def _span(ctx: InspectContext) -> int:
    return _SPANS.get(str(ctx.value(PERIOD.name) or ""), DAY)


# ── La barre de vitaux, les séries ────────────────────────────────────────


@AFFECT.vital("humeur", label="Humeur", order=10)
def _mood_vital(s: AffectState, frame: Frame) -> Vital:
    p = _p(frame)
    m = frame.get(c.MOOD)
    href = Ref.view("affect", "humeur", "Humeur")
    if _at_rest(m, p):
        return Vital("au repos", hint=f"son fond : {A.FR[p.background]}", href=href)
    return Vital(_feeling(m.felt, m.felt_intensity), ratio=m.felt_intensity, swatch=_swatch(m.felt, m.felt_intensity),
                 tone="warn" if m.overflow > p.overflow_floor else "", hint=prose.mood(m, p), href=href)


def _unit(value: float) -> float:
    return max(-1.0, min(1.0, value))


@AFFECT.series("valence", label="Valence", lo=-1.0, hi=1.0)
def _valence(s: AffectState, frame: Frame) -> float:
    """Le plaisir de son humeur générale (sa position, repos compris)."""
    return _unit(frame.get(c.MOOD).position[0])


@AFFECT.series("eveil", label="Éveil", lo=-1.0, hi=1.0)
def _arousal(s: AffectState, frame: Frame) -> float:
    return _unit(frame.get(c.MOOD).position[1])


# ── Humeur ────────────────────────────────────────────────────────────────


#: une balise lue dans le fil : (n° du message, instant, adresse, émotion, intensité, sorte, texte)
Tag = tuple[int, int, str, str, float, str, str | None]


def _declared_rows(ctx: InspectContext, handles: tuple[str, ...] | None = None, limit: int = DECLARED_PAGE,
                   before: int | None = None) -> list[Tag]:
    """Ses balises, lues dans le fil (ce qu'elle a vraiment écrit), de la plus
    récente à la plus ancienne ; ``handles`` : envers ces adresses seulement ;
    ``before`` : avant ce message."""
    if ctx.store is None:
        return []
    where, args = "", ()
    if handles is not None:
        if not handles:
            return []
        where = f" AND person IN ({','.join('?' * len(handles))})"
        args = tuple(handles)
    if before:
        where += " AND id<?"
        args = (*args, before)
    rows = ctx.store.query_mind(
        f"SELECT id, at, person, emotion, emotion_intensity, kind, text FROM {transcript_c.THREAD_TABLE} "
        f"WHERE role='assistant' AND emotion IS NOT NULL{where} ORDER BY id DESC LIMIT ?", (*args, limit))
    return [(int(n), int(at), str(person or ""), str(name), float(intensity or 0.0), str(kind or ""), text)
            for n, at, person, name, intensity, kind, text in rows]


def _declared_page(ctx: InspectContext, handles: tuple[str, ...] | None = None) -> tuple[list[Tag], Pager]:
    """Une page de ses balises (``?avant=`` : la suite), et le curseur de la suivante."""
    found = _declared_rows(ctx, handles, DECLARED_PAGE + 1, ctx.int_param("avant", 0) or None)
    page = found[:DECLARED_PAGE]
    older = (("avant", str(page[-1][0])),) if len(found) > DECLARED_PAGE else ()
    return page, Pager(param="avant", size=DECLARED_PAGE, older=older)


def _how(kind: str) -> str:
    return "en répondant" if kind == Kind.REPLY else "d'elle-même"


def _excerpt(text: object) -> str:
    if text is None:
        return "(oublié)"
    value = str(text)
    return value if len(value) <= EXCERPT else value[:EXCERPT - 1] + "…"


@AFFECT.inspect("humeur", title="Humeur", section="vie", order=10, params=[PERIOD],
                description="Son humeur générale : ce qu'elle ressent, sa courbe, ses dernières balises.")
def _mood_view(s: AffectState, frame: Frame, ctx: InspectContext) -> list[Block]:
    p = _p(frame)
    m = frame.get(c.MOOD)  # la lecture du fait : la cause dite au bon temps
    rest = _at_rest(m, p)
    declared, pager = _declared_page(ctx)
    # la dernière balise, quelle que soit la page lue
    newest = declared[:1] if not ctx.int_param("avant", 0) else _declared_rows(ctx, limit=1)
    span = _span(ctx)
    since = frame.now - span
    points = tuple(ctx.series("affect.valence", since, frame.now))
    last: Cell = "aucune"
    last_sub = "elle n'a encore rien déclaré"
    if newest:
        _n, at, handle, name, intensity, _kind, _text = newest[0]
        last = _declared_cell(name, intensity)
        last_sub = f"{ctx.when(at)}, {_who_text(frame, handle)}"
    return [
        Stats((
            Stat("ressentie", "au repos" if rest else _swatch(m.felt, m.felt_intensity), sub="l'écart à son repos"),
            Stat("débordement", Meter(m.overflow, pct_fr(m.overflow),
                                      tone="warn" if m.overflow > p.overflow_floor else ""),
                 sub=f"pousse à parler au-delà de {pct_fr(p.overflow_floor)}",
                 tone="warn" if m.overflow > p.overflow_floor else ""),
            Stat("son fond", _swatch(p.background), sub="ce vers quoi elle revient"),
            Stat("dernière balise", last, sub=last_sub),
        ), title="Humeur générale"),
        Note(prose.mood(m, p)),
        Chart((Series("Valence", points, slot=1),), kind="line", title="Valence de son humeur", y=(-1.0, 1.0),
              zero=0.0, since=since, until=frame.now,
              empty="pas encore de mesure (une toutes les dix minutes) : la courbe se remplira"),
        Table(
            (Column("quand", "fit"), "à qui", "émotion déclarée", "comment"),
            tuple(Row((When(at), _who(frame, handle), _declared_cell(name, intensity), _how(kind)),
                      detail=(Note(_excerpt(text), title="ce qu'elle a dit"),))
                  for _n, at, handle, name, intensity, kind, text in declared),
            title="Dernières balises", empty="elle n'a encore rien déclaré", pager=pager),
        Disclosure("Détails", (Fields((
            ("ressentie (écart au repos)", "au repos" if rest else _feeling(m.felt, m.felt_intensity)),
            ("émotion du moment (ce qui déborde)", pct_fr(m.overflow)),
            ("fond de la journée", _vec(m.fond) if A.norm(m.fond) > 1e-3 else "aucun"),
            ("cause", prose.cause_line(m.cause, m.cause_person, ended=m.cause_over) or prose.unknown_cause()),
            ("lecture absolue (le visage)", _feeling(m.label, m.intensity)),
            ("position", _vec(m.position)),
            ("repos à cette heure", _vec(m.home)),
            ("dernière mise à jour", ctx.when(s.mood.at) if s.mood is not None else "jamais (au repos depuis toujours)"),
        )),)),
    ]


# ── Postures ──────────────────────────────────────────────────────────────


def _warmth_cell(value: float) -> Meter:
    """La chaleur installée, signée : la jauge dit l'ampleur, le ton le sens."""
    return Meter(abs(value), num_fr(value, 2, signed=True),
                 tone="ok" if value > 0.05 else "danger" if value < -0.05 else "")


def _hostility_cell(value: float) -> Meter:
    return Meter(value, num_fr(value, 2), tone="danger" if value >= 0.3 else "warn" if value > 0.05 else "")


def _bond_cell(value: float) -> Meter:
    return Meter(value, num_fr(value, 2), tone="ok" if value >= 0.35 else "")


def _anchor_cell(r: c.StanceReading) -> Cell:
    if r.anchor is None:
        return Text("aucune", kind="muted")
    label, intensity = A.felt(r.anchor, r.reference)
    return _swatch(label, intensity)


def _stance_prose(frame: Frame, r: c.StanceReading, p: AffectParams) -> str:
    return prose.stance(r, p, name=frame.get(identity_c.IDENTITY(r.person)).name, now=frame.now)


def _stance_row(s: AffectState, frame: Frame, ctx: InspectContext, person: str, p: AffectParams,
                cw: ph.Clockwork) -> Row:
    stored = s.stances[person]
    r = stance_reading(s, person, frame.now, p, cw)
    last = A.Declared.decode(stored.declared)
    who = (Ref.subject("person", person, _name(frame, person), "affect") if is_identifiable(person)
           else Text(_name(frame, person), kind="muted", hint=person))
    detail = (
        Note(_stance_prose(frame, r, p) or "rien de particulier envers cette personne", title="ce qu'elle se dit"),
        Fields((
            ("installée", "oui (plusieurs tours concordants)" if r.anchored else "non"),
            ("ancre (depuis son repos moyen)", _vec(None if r.anchor is None else A.sub(r.anchor, r.reference))),
            ("jours de contact", str(stored.days)),
            ("méfiance jusqu'à", ctx.when(stored.wary_until) if stored.wary_until > frame.now else "—"),
            ("excuses (qui ont compté)", ctx.when(stored.apologized_at) if stored.apologized_at else "—"),
            ("position", _vec(r.position)),
            ("son repos envers elle", _vec(r.home)),
            ("dernier mouvement", ctx.when(stored.at) if stored.at else "—"),
        )),
    )
    return Row((
        who,
        Text("au repos", kind="muted") if r.at_rest else _swatch(r.felt, r.felt_intensity),
        _warmth_cell(regard(s, person, frame.now, p, cw)),
        _hostility_cell(hostility(s, person, frame.now, p, cw)),
        _bond_cell(r.bond),
        _anchor_cell(r),
        _swatch(last.emotion, last.intensity) if last else Text("—", kind="muted"),
        When(stored.declared_at) if stored.declared_at else Text("—", kind="muted"),
    ), href=who if isinstance(who, Ref) else None, detail=detail)


POSTURE_COLUMNS = (Column("personne"), Column("ressentie envers elle"),
                   Column("chaleur (−1…1)", hint="ce que ses échanges ont installé : > 0 chaleureux, < 0 froid"),
                   Column("hostilité", hint="un écart déplaisant et dominant, amorti par l'attachement : la rancune"),
                   Column("attachement", hint="ce qui l'attache à cette personne (0…1, jamais négatif)"),
                   Column("ancre", hint="ce qui s'est installé", detail=True), Column("dernière balise", detail=True),
                   Column("quand", "fit"))


@AFFECT.inspect("postures", title="Postures", section="vie", order=20,
                description="Ce qu'elle ressent envers chacun, et ce que leurs échanges ont installé.")
def _stances_view(s: AffectState, frame: Frame, ctx: InspectContext) -> list[Block]:
    p = _p(frame)
    cw = _clockwork(frame)
    ordered = sorted(s.stances.items(), key=lambda kv: (-max(kv[1].declared_at, kv[1].at), kv[0]))
    page, pager = paginate(ordered, ctx.pager(size=STANCES_PAGE, total=len(ordered)))
    return [Table(POSTURE_COLUMNS, tuple(_stance_row(s, frame, ctx, person, p, cw) for person, _ in page),
                  title="Postures envers chacun", pager=pager,
                  empty="aucune posture : personne ne l'a encore touchée")]


# ── Sur la fiche d'une personne ───────────────────────────────────────────


#: le type d'objet « personne », déclaré par l'identité
PERSON_KIND = "person"


@AFFECT.inspect("affect", title="Affect", subject=PERSON_KIND, order=60,
                description="Ce qu'elle ressent envers cette personne, sur toutes ses adresses.")
def _person_view(s: AffectState, frame: Frame, ctx: InspectContext) -> list[Block]:
    person = ctx.subject
    if not person:
        return [Note("Cette vue se lit sur la fiche d'une personne.", tone="muted")]
    p = _p(frame)
    cw = _clockwork(frame)
    handles = tuple(sorted({person, *frame.get(identity_c.HANDLES(person))}))
    # la posture vit sous la clé de la personne ; une adresse liée après coup a pu en garder une à son nom
    keys = [person, *(h for h in handles if h != person and h in s.stances)]
    blocks: list[Block] = []
    for key in keys:
        if key not in s.stances:
            blocks.append(Note("Aucune posture envers cette personne : ses échanges ne l'ont pas encore touchée.",
                               tone="muted"))
            continue
        stored = s.stances[key]
        r = stance_reading(s, key, frame.now, p, cw)
        last = A.Declared.decode(stored.declared)
        warmth = regard(s, key, frame.now, p, cw)
        blocks += [
            Stats((
                Stat("ressentie", "au repos" if r.at_rest else _swatch(r.felt, r.felt_intensity),
                     sub="envers elle, à l'instant"),
                Stat("chaleur", _warmth_cell(warmth), sub="ce que leurs échanges ont installé (−1…1)"),
                Stat("hostilité", _hostility_cell(hostility(s, key, frame.now, p, cw)), sub="la rancune (0…1)"),
                Stat("attachement", _bond_cell(r.bond), sub="ce qui l'attache à elle (0…1)"),
                Stat("ancre", _anchor_cell(r),
                     sub=f"{stored.days} jour(s) de contact" if r.anchor is not None else ""),
                Stat("dernière balise", _swatch(last.emotion, last.intensity) if last else "—",
                     sub=ctx.when(stored.declared_at) if stored.declared_at else ""),
            ), title="Envers elle" if key == person else f"Envers l'adresse {key} (avant d'être reliée)"),
            Note(_stance_prose(frame, r, p) or "Rien de particulier envers cette personne."),
        ]
    tags, pager = _declared_page(ctx, handles)
    blocks.append(Timeline(tuple(_tag_entry(frame, *row[1:]) for row in tags), title="Ses dernières balises envers elle",
                           empty="elle ne lui a encore rien déclaré", pager=pager))
    return blocks


#: par où elle lui a parlé (une personne peut avoir plusieurs adresses)
CHANNEL_FR = {privacy.WEB: "sur le web", privacy.MOBILE: "sur son téléphone",
              privacy.EXTERNAL: "par un compte extérieur"}


def _where(frame: Frame, handle: str) -> str:
    channel = frame.get(identity_c.IDENTITY(handle)).channel if handle else ""
    return CHANNEL_FR.get(channel, f"par {channel}" if channel else "")


def _tag_entry(frame: Frame, at: int, handle: str, name: str, intensity: float, kind: str,
               text: str | None) -> Entry:
    """Une balise envers quelqu'un : l'émotion, ce qu'elle a dit, et par où (jamais la clé de l'adresse)."""
    meta = " · ".join(x for x in (_how(kind), _where(frame, handle)) if x)
    emotion = A.emotion_of(name)
    if emotion is None:
        return Entry(at, name, _excerpt(text), meta=meta)
    v = A.valence(emotion)
    return Entry(at, _feeling(emotion, intensity), _excerpt(text), tone="ok" if v >= 0.3 else "warn" if v <= -0.3 else "",
                 meta=meta)
