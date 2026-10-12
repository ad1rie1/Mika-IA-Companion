"""Les vues d'inspection du soi : l'estime (maintenant, vers où elle va, sa
courbe), le récit d'elle-même, la persona et le tempérament ; ses nuits
(journaux, rêves). Et la mesure de l'estime, échantillonnée pour les courbes.

Lecture seule, bornée ; un texte effacé par l'oubli se montre comme tel.
"""

from __future__ import annotations

from collections.abc import Sequence

from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import self_ as c
from mika.faculties.self.esteem import ACHIEVED, HEARD, IGNORED, PROMISE, STUCK, doubt_cause, esteem
from mika.faculties.self.faculty import SELF, SelfState
from mika.faculties.self.interests import fresh_leads, glow, level
from mika.faculties.self.knobs import SelfParams, params
from mika.faculties.self.lines import KNOWN_LINES
from mika.faculties.self.model import (
    FINISHED,
    FINISHING,
    FORESIGHT,
    KEPT,
    PROMISES,
    SLIPPED,
    STRUGGLED,
    knows,
)
from mika.faculties.self.narrative import changes_since
from mika.faculties.self.night import lived_day, told_day
from mika.faculties.self.records import Dream, Journal, Mark
from mika.kernel import forms
from mika.kernel.clock import DAY, HOUR
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    Badge,
    Block,
    Cell,
    Chart,
    Column,
    Entry,
    Fields,
    InspectContext,
    Meter,
    Note,
    Pager,
    Prose,
    Ref,
    Row,
    Series,
    Stat,
    Stats,
    Table,
    Text,
    Timeline,
    When,
    num_fr,
    pct_fr,
)
from mika.vocab import temperament as T
from mika.vocab.affect import emotion_cell
from mika.vocab.interests import ASLEEP, PERSONA, PRESENT, VIVID, subject_of
from mika.vocab.people import named_label

FORGOTTEN = "(oublié)"
CLAMP = 200
#: la chronologie montre les plus récentes ; toutes ses nuits se lisent par pages
RECENT = 14
#: l'aperçu en tête de page (le reste se lit dans l'historique paginé, dessous)
PREVIEW = 4
PAGE = 14
#: la courbe de l'estime
CURVE_DAYS = 7

TEMPERAMENT_FR = {
    "reactivity": ("réactivité", "à quel point un mot la touche : masse, amortissement, gain des impulsions"),
    "resilience": ("résilience", "les constantes de temps de l'humeur et des postures, la guérison des rancunes"),
    "contagion": ("contagion", "ce que ses relations font à son humeur générale (0 = cloisonnée)"),
    "optimism": ("optimisme", "la valence du repos, les seuils d'ennui et de détresse"),
    "sociability": ("sociabilité", "l'horizon du besoin social, le rythme des relances"),
    "curiosity": ("curiosité", "l'horizon de la curiosité, le seuil d'ouverture d'une exploration"),
    "perseverance": ("persévérance", "le budget de séances, la demi-vie de l'envie, les échecs avant blocage"),
    "chronotype": ("chronotype", "le décalage du rythme circadien (0 = lève-tôt, 1 = oiseau de nuit)"),
}
DREAM_FR = {c.NIGHTMARE: "cauchemar", c.PLEASANT: "doux", c.MELANCHOLIC: "mélancolique", c.ASSOCIATIVE: "étrange",
            c.MUNDANE: "banal"}
DREAM_TONE = {c.NIGHTMARE: "danger", c.PLEASANT: "ok", c.MELANCHOLIC: "warn", c.ASSOCIATIVE: "info",
              c.MUNDANE: "muted"}
CAUSE_FR = {IGNORED: "une initiative restée sans réponse", HEARD: "une réponse après des initiatives ignorées",
            ACHIEVED: "quelque chose mené à bout", STUCK: "un blocage", PROMISE: "une promesse non tenue",
            c.THANKED: "un merci", c.COMPLIMENTED: "un compliment", c.INSULTED: "une insulte",
            c.APOLOGIZED: "des excuses"}


def number(value: float) -> str:
    return num_fr(value, 2)


def signed(value: float, digits: int = 2) -> str:
    return num_fr(value, digits, signed=True)


def clip(text: str, n: int = CLAMP) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def feeling(name: str) -> str:
    cell = emotion_cell(name)
    return cell if isinstance(cell, str) else cell.text


def names(frame: Frame, keys: Sequence[str]) -> str:
    out = [named_label(k).title() if k.startswith("name:") else (frame.get(identity_c.IDENTITY(k)).name or k) for k in keys]
    return ", ".join(out) or "personne"


def _p(frame: Frame) -> SelfParams:
    return params(frame.env.params_of("self", frame.root))


# ── L'estime, mesurée ─────────────────────────────────────────────────────


@SELF.series("estime", label="Estime", lo=0, hi=1)
def _esteem_series(s: SelfState, frame: Frame) -> float:
    return round(esteem(s, frame.now, _p(frame)), 4)


def _word(value: float, p: SelfParams) -> tuple[str, str]:
    if value < p.doubt_below:
        return "elle doute un peu d'elle", "warn"
    if value > p.assured_above:
        return "sûre d'elle", "ok"
    return "ni doute ni assurance", ""


def _trend(s: SelfState, value: float) -> str:
    if not s.esteem_at:
        return "au repos : jamais bousculée"
    if abs(value - 0.5) < 0.005:
        return "revenue au repos"
    return "remonte vers 0,50" if value < 0.5 else "redescend vers 0,50"


# ── Soi ───────────────────────────────────────────────────────────────────


def _esteem(s: SelfState, frame: Frame, ctx: InspectContext) -> list[Block]:
    p = _p(frame)
    now = esteem(s, frame.now, p)
    word, tone = _word(now, p)
    since = frame.now - CURVE_DAYS * DAY
    points = tuple(ctx.series("self.estime", since))
    curve = Chart((Series("Estime", points, 1),), title=f"L'estime sur {CURVE_DAYS} jours", y=(0.0, 1.0),
                  zero=0.5, since=since, until=frame.now,
                  empty="pas encore de mesure (une toutes les dix minutes)")
    lived = s.souvenirs - s.narrated_souvenirs
    stats = Stats((
        Stat("Estime", Meter(now, number(now), tone), f"{word} · {_trend(s, now)}", tone,
             trend=Chart((Series("Estime", points, 1),), kind="spark", y=(0.0, 1.0)) if points else None),
        Stat("Au dernier coup", number(s.esteem) if s.esteem_at else "—",
             f"le {ctx.when(s.esteem_at)}" if s.esteem_at else "jamais bousculée"),
        Stat("Son récit", When(s.narrated_at) if s.narrated_at else "jamais",
             f"{lived} souvenir(s) vécu(s) depuis"),
        Stat("La persona", s.revisions, "révision(s)"),
    ))
    rules = Fields((
        ("demi-vie du retour au repos", f"{num_fr(p.esteem_half_life_us / HOUR)} h"),
        ("bornes", f"{number(p.esteem_min)} – {number(p.esteem_max)}"),
        ("elle doute sous", number(p.doubt_below)),
        ("sûre d'elle au-dessus de", number(p.assured_above)),
        ("ce qui la bouscule", f"une initiative ignorée {signed(p.ignored_knock)}, une réponse qui rompt la série "
                               f"{signed(p.heard_again_knock)}, un but bloqué {signed(p.stuck_knock)}, une promesse "
                               f"non tenue {signed(p.broken_promise_knock)}"),
        ("ce qu'elle mène à bout", f"{number(p.achieved_base)} à {number(p.achieved_base + p.achieved_effort)} "
                                   f"selon l'effort (plein à {p.achieved_full_steps} séances, s'il est prouvé), "
                                   f"au plus {number(p.achieved_daily_cap)} par jour"),
        ("ce qu'on lui dit d'elle", f"un merci ou un compliment {signed(p.thanked_knock, 3)}, une insulte qui la vise "
                                    f"{signed(p.insulted_knock, 3)} (une amitié : en entier ; une connaissance : × "
                                    f"{number(p.acquaintance_weight)} ; pas encore de lien : × "
                                    f"{number(p.stranger_weight)}), au plus {number(p.social_daily_cap)} par "
                                    "personne et par jour"),
        ("des excuses", f"lui rendent {pct_fr(p.apology_mend)} de ce que les mots de cette personne lui avaient "
                        "coûté ce jour-là — une fois par jour, et seulement s'il y avait de quoi pardonner"),
        ("une rêverie", "n'est pas une réussite : elle ne la relève pas"),
    ), title="L'estime", columns=2)
    knocks = Table((Column("quand", "fit"), Column("pourquoi"), Column("coup", "fit")),
                   tuple((When(k.at), CAUSE_FR.get(k.cause, k.cause), signed(k.delta, 3))
                         for k in reversed(s.knocks)),
                   title="Les derniers coups", empty="jamais bousculée")
    cause = doubt_cause(s, frame.now, p) if now < p.doubt_below else ""
    blocks: list[Block] = [stats, curve, rules, knocks]
    if cause:
        blocks.insert(1, Note(f"Elle doute un peu d'elle : {cause}.", tone="warn"))
    return blocks


def _narrative(s: SelfState, frame: Frame, ctx: InspectContext) -> list[Block]:
    p = _p(frame)
    facts = Fields((
        ("écrit", When(s.narrated_at) if s.narrated_at else "jamais"),
        ("ce qui a changé depuis", f"{num_fr(changes_since(s, frame, p))} (il en faut {num_fr(p.narrative_min_changes)} "
                                   f"pour le réécrire, au plus une fois toutes les "
                                   f"{num_fr(p.narrative_every_us / HOUR)} h)"),
        ("dont", f"{s.souvenirs - s.narrated_souvenirs} souvenir(s) ({p.narrative_min_souvenirs} valent un "
                 f"changement), {s.self_beliefs - s.narrated_self_beliefs} note(s) sur elle qui la définissent, "
                 f"{s.changes - s.narrated_changes} changement(s) d'avis, {s.lived - s.narrated_lived} moment(s) "
                 "vécu(s) à travers quelqu'un ; ce qu'elle sait d'elle et ce qui la passionne comptent double"),
        ("en ce moment", "réécriture attendue : une de ses sources a changé" if s.narrative_stale else "à jour"),
    ), title="Son récit d'elle-même")
    if not s.narrative_ref:
        return [facts, Note("Elle ne s'est pas encore racontée.", tone="muted")]
    text = ctx.store.content([s.narrative_ref]).get(s.narrative_ref)
    return [facts, Prose(text if text else FORGOTTEN, title="« Je suis quelqu'un qui… »")]


#: Sa nature, telle que la console la dit (les choix du champ de la persona).
NATURE_FR = {c.AI: "une IA qui le sait", c.EMBODIED: "une personne (incarnée)"}


def _lines(values: Sequence[str]) -> Cell:
    return Text(" · ".join(values), clamp=CLAMP) if values else Text("—", kind="muted")


def _persona(s: SelfState) -> list[Block]:
    doc = s.persona
    t = doc.temperament
    persona = Fields((
        ("nom", doc.name),
        ("nature", NATURE_FR.get(doc.nature, doc.nature)),
        ("description", Text(doc.description, clamp=CLAMP) if doc.description else Text("—", kind="muted")),
        ("ton", doc.tone or "—"),
        ("langue", doc.language),
        ("fuseau", doc.timezone),
        ("traits", _lines(doc.traits)),
        ("manies", _lines(doc.quirks)),
        ("fragilités", _lines(doc.vulnerabilities)),
        ("valeurs", _lines(doc.values)),
        ("centres d'intérêt", _lines(doc.interests)),
        ("façons de parler", _lines(doc.speech)),
        ("salutations (seuls leurs premiers mots lui sont montrés)", _lines(doc.greetings)),
        ("sa vie, à sa façon", _lines(doc.life)),
        ("ses goûts et ses avis", _lines(doc.tastes)),
        ("ce qui est vrai d'elle", _lines(doc.facts)),
    ), title="La persona", columns=2)
    rows: list[tuple[Cell, ...]] = []
    knobs = {f.path: f for f in forms.describe(type(t))}
    for name in T.SLIDERS:
        knob = knobs.get(name)
        label, drives = TEMPERAMENT_FR.get(name, ((knob.label if knob else name).lower(),
                                                  knob.help if knob else "—"))
        value = float(getattr(t, name))
        rows.append((label, Meter(value, number(value)), Text(drives, kind="muted", clamp=CLAMP)))
    rows.append(("humeur de fond", emotion_cell(t.background), Text("l'humeur vers laquelle son repos penche et "
                                                                     "avec laquelle elle résonne", kind="muted")))
    key = T.profile_of(t)
    temperament = Table((Column("curseur"), Column("valeur"), Column("ce qu'il pilote")), tuple(rows),
                        title="Le tempérament (0,5 = comme la plupart des gens) — profil : "
                              + (T.PROFILES[key].label if key else "ajusté à la main"))
    labels = dict(T.NOTE_KEYS)
    character = Fields((
        ("quand on la blesse", dict(T.REACTIONS).get(t.reaction, t.reaction) or Text("—", kind="muted")),
        ("quand on la touche", dict(T.DEFENSES).get(t.defense, t.defense) or Text("—", kind="muted")),
        *((f"précision · {labels.get(k, k).lower()}", Text(note, clamp=CLAMP)) for k, note in sorted(t.notes.items())),
    ), title="Quand on la blesse, quand on la touche", columns=2)
    return [persona, temperament, character]


@SELF.inspect("soi", title="Estime et récit", section="vie", order=50,
              description="Son estime d'elle-même (lente, elle revient vers 0,5), le récit qu'elle fait d'elle, "
                          "sa persona et son tempérament.")
def _inspect_self(s: SelfState, frame: Frame, ctx: InspectContext) -> list[Block]:
    return [*_esteem(s, frame, ctx), *_narrative(s, frame, ctx), *_persona(s)]


# ── Qui elle devient (ADR 0088) ───────────────────────────────────────────

#: les sortes de notes sur elle, telles que la console les dit
SELF_KIND_FR = {"preference": "un goût", "opinion": "un avis", "claim": "un fait de sa vie",
                "hypothesis": "une hypothèse", "prediction": "un pronostic"}
SHOWN = 30


def _count(marks: Sequence[Mark], domain: str, outcome: str) -> int:
    return sum(1 for m in marks if m.domain == domain and m.outcome == outcome)


def _said(known: Sequence[str], *codes: str) -> Cell:
    lines = [KNOWN_LINES[k]() for k in codes if k in known]
    return Text(" ".join(lines)) if lines else Text("rien : pas de tendance nette", kind="muted")


def _knowing(s: SelfState, frame: Frame) -> Table:
    p = _p(frame)
    recent = [m for m in s.record if m.at >= frame.now - p.know_window_us]
    seen = [m.value for m in s.record if m.domain == FORESIGHT and m.at >= frame.now - p.foresight_window_us]
    known = knows(s.record, frame.now, p)
    days = num_fr(p.know_window_us / DAY)
    gap = f", écart moyen {number(sum(seen) / len(seen))}" if seen else ""
    rows = (
        ("tenir parole", f"{_count(recent, PROMISES, KEPT)} tenue(s), {_count(recent, PROMISES, SLIPPED)} laissée(s) "
                         f"filer, sur {days} j",
         Text(f"« tient parole » dès {p.know_kept_from} tenues sans aucune laissée filer ; « laisse filer » dès "
              f"{p.know_slipped_from}, et plus que de tenues", kind="muted"),
         _said(known, c.PROMISES_KEPT, c.PROMISES_SLIP)),
        ("mener au bout", f"{_count(recent, FINISHING, FINISHED)} abouti(s), {_count(recent, FINISHING, STRUGGLED)} "
                          f"bloqué(s), sur {days} j",
         Text(f"« mène au bout » dès {p.know_done_from} aboutis pour au plus moitié de blocages ; « bloque » dès "
              f"{p.know_stuck_from}, et plus que d'aboutis", kind="muted"),
         _said(known, c.FINISHING_DONE, c.FINISHING_STRUGGLE)),
        ("voir venir", f"{len(seen)} moment(s){gap}, sur {num_fr(p.foresight_window_us / DAY)} j",
         Text(f"au moins {p.foresight_min} moments ; « juste » sous {number(p.foresight_right_below)}, « à côté » "
              f"dès {number(p.foresight_off_above)} (dates officielles et issues inconnues exclues)", kind="muted"),
         _said(known, c.FORESIGHT_RIGHT, c.FORESIGHT_OFF)),
    )
    return Table((Column("ce qu'elle sait d'elle"), Column("ses marques"), Column("les seuils"),
                  Column("ce que son prompt en dit")), rows,
                 title="Tenir parole, mener au bout, voir venir (des tendances : son estime n'en dépend pas)")


def _changes(frame: Frame, ctx: InspectContext) -> Table:
    rows = ctx.store.query_mind(
        f"SELECT was, was_text, text, knowledge_kind, secret, changed_at FROM {memory_c.SELF_CHANGES_VIEW} "
        f"ORDER BY changed_at DESC LIMIT {SHOWN}")
    return Table((Column("avant"), Column("maintenant"), Column("sorte"), Column("quand")), tuple(
        (Text(clip(was_text)), Text(clip(text)) if not secret else Badge("à taire", tone="warn"),
         SELF_KIND_FR.get(kind, kind), When(at)) for _was, was_text, text, kind, secret, at in rows),
        title="Ses changements d'avis sur elle-même", empty="Elle n'a pas encore changé d'avis sur elle-même.")


def _defining(frame: Frame, ctx: InspectContext) -> Table:
    rows = ctx.store.query_mind(
        f"SELECT text, knowledge_kind, born_at, secret FROM {memory_c.KNOWLEDGE_VIEW} "
        f"WHERE kind=? AND about_self >= 2 ORDER BY born_at DESC LIMIT {SHOWN}", (memory_c.BELIEF,))
    return Table((Column("ce qui la définit"), Column("sorte"), Column("depuis")), tuple(
        (Text(clip(text)) if not secret else Badge("à taire", tone="warn"), SELF_KIND_FR.get(kind, kind),
         When(at)) for text, kind, at, secret in rows),
        title="Ses goûts, ses avis, ce qui est vrai de sa vie (ce qu'elle a dit d'elle, qui tient des mois)",
        empty="Elle n'a encore rien dit d'elle qui la définisse.")


LEVEL_FR = {VIVID: ("vif", "ok"), PRESENT: ("présent", ""), ASLEEP: ("endormi", "muted")}


def _passions(s: SelfState, frame: Frame, ctx: InspectContext) -> list[Block]:
    p = _p(frame)
    texts = ctx.store.content([i.label_ref for i in s.interests.values() if i.label_ref])
    rows: list[tuple[Cell, ...]] = []
    for i in sorted(s.interests.values(), key=lambda i: (-glow(i, frame.now, p), i.key)):
        g = glow(i, frame.now, p)
        word, tone = LEVEL_FR[level(g, p)]
        label = subject_of(i.line) if i.line else texts.get(i.label_ref) or FORGOTTEN
        origin = "sa persona" if i.origin == PERSONA else f"née le {frame.local(i.born_at):%d/%m}"
        rows.append((Text(clip(label)), origin, Badge(word, tone=tone), Meter(g, number(g)),
                     When(i.fed_at) if i.fed_at else "jamais", str(i.feeds)))
    table = Table((Column("sujet"), Column("d'où"), Column("niveau"), Column("vivacité"), Column("nourri"),
                   Column("fois")), tuple(rows), title="Ce qui la passionne",
                  empty="Aucun centre d'intérêt : sa persona n'en a pas encore.")
    leads = Fields((
        ("pistes en attente", f"{len(fresh_leads(s))} (sur {len(s.leads)} gardées ; il en faut {p.birth_min_leads} "
                              f"neuves sur {p.birth_min_days} journées pour qu'elle y réfléchisse la nuit)"),
        ("dernière réflexion", s.reflected_night or "jamais"),
        ("dernière naissance", When(s.last_birth_at) if s.last_birth_at else "jamais"),
    ), title="Ses pistes")
    return [table, leads]


@SELF.inspect("devenir", title="Qui elle devient", section="vie", order=55,
              description="Ce qu'elle sait d'elle (tenir parole, mener au bout, voir venir), ce qui la passionne, "
                          "ses changements d'avis sur elle-même, et ce qu'elle a dit d'elle qui la définit — à côté "
                          "de sa persona, qui ne bouge pas.")
def _inspect_becoming(s: SelfState, frame: Frame, ctx: InspectContext) -> list[Block]:
    return [_knowing(s, frame), *_passions(s, frame, ctx), _changes(frame, ctx), _defining(frame, ctx)]


# ── Nuits ─────────────────────────────────────────────────────────────────


def _remembered(d: Dream) -> str:
    if not d.remembered:
        return "oublié au réveil"
    return "souvenu au réveil, déjà raconté" if d.recalled else "souvenu au réveil"


def _dream_title(d: Dream) -> str:
    return f"Rêve {DREAM_FR.get(d.kind, d.kind)} de la nuit du {d.night}"


def _timeline(journals: Sequence[Journal], dreams: Sequence[Dream], frame: Frame, texts: dict[str, str]) -> Timeline:
    entries = [Entry(j.at, f"Journal du {j.day}", clip(texts[j.text_ref]) if j.text_ref in texts else FORGOTTEN,
                     meta=f"dominante : {feeling(j.dominant)} · concerne : {names(frame, j.about)}")
               for j in journals]
    entries += [Entry(d.at, _dream_title(d), clip(texts[d.text_ref]) if d.text_ref in texts else FORGOTTEN,
                      tone=DREAM_TONE.get(d.kind, ""), href=Ref("event", str(d.id), f"n° {d.id}"),
                      meta=f"vivacité {number(d.vividness)} · {_remembered(d)} · couleur : {feeling(d.emotion)}")
                for d in dreams]
    entries.sort(key=lambda e: -e.at)
    return Timeline(tuple(entries[:PREVIEW]), title="Ses dernières nuits, en bref",
                    empty="pas encore de nuit racontée")


def _history(s: SelfState, frame: Frame, ctx: InspectContext) -> Table:
    """Toutes ses nuits, lues dans le journal (la tranche n'en garde que les
    dernières) : par pages de quatorze, des plus récentes aux plus anciennes."""
    before = ctx.int_param("avant", 0) or None
    found = ctx.events([c.JOURNALED, c.DREAMT], PAGE + 1, before=before)  # un de plus : y a-t-il une suite ?
    events = found[:PAGE]
    remembered = {d.id: d.remembered for d in s.dreams}
    rows = []
    for e in events:
        d = e.data
        text = d.text.text
        cell = Text(text, clamp=CLAMP) if text else Text(FORGOTTEN, kind="muted")
        if e.type.name == c.DREAMT.name:
            back = remembered.get(e.seq)
            cells: tuple[Cell, ...] = (
                Ref("event", str(e.seq), f"#{e.seq}"), When(e.at),
                Badge(f"rêve {DREAM_FR.get(d.kind, d.kind)}", DREAM_TONE.get(d.kind, "")), d.night, cell,
                emotion_cell(d.emotion) if d.emotion else None, Meter(d.vividness, number(d.vividness)),
                Text("plus suivi", kind="muted") if back is None else Badge("oui", "info") if back
                else Badge("non", "muted"),
                names(frame, d.about))
        else:
            cells = (Ref("event", str(e.seq), f"#{e.seq}"), When(e.at), Badge("journal"), d.day, cell,
                     emotion_cell(d.dominant) if d.dominant else None, None, None, names(frame, d.about))
        detail: tuple[Block, ...] = (Prose(text or FORGOTTEN, title="En entier"),)
        told = getattr(d, "shareable", None)
        if told is not None and told.text:
            detail += (Prose(told.text, title="Ce qu'elle en raconterait à quelqu'un d'autre"),)
        rows.append(Row(cells, detail=detail))
    pager = Pager(param="avant", size=PAGE, older=(("avant", str(events[-1].seq)),)) if len(found) > PAGE \
        else Pager(param="avant", size=PAGE)
    return Table((Column("n°", "fit", detail=True), Column("écrit", "fit", detail=True), Column("sorte", "fit", role="badge"), Column("nuit", "fit"),
                  Column("texte", role="body"), Column("couleur", detail=True), Column("vivacité", detail=True), Column("souvenu au réveil", "fit"),
                  Column("concerne")), tuple(rows), title="Toutes ses nuits",
                 empty="plus rien avant" if before else "pas encore de nuit racontée", pager=pager, layout="list")


@SELF.inspect("nuits", title="Nuits", section="pensees", order=40,
              description="Le journal qu'elle écrit la nuit, un par journée vécue, ce qu'elle en raconte à n'importe "
                          "qui (rendu d'après les faits, sans modèle), et ses rêves (deux par nuit au plus) : ce qui "
                          "revient au réveil peut se dire le matin.")
def _inspect_nights(s: SelfState, frame: Frame, ctx: InspectContext) -> list[Block]:
    journals = [j for _, j in sorted(s.journals.items(), reverse=True)][:RECENT]
    dreams = sorted(s.dreams, key=lambda d: -d.id)[:RECENT]
    texts = ctx.store.content(sorted({r for r in (*(j.text_ref for j in journals), *(d.text_ref for d in dreams))
                                      if r}))
    blocks: list[Block] = []
    if ctx.int_param("avant", 0):  # en feuilletant l'historique, l'aperçu ne se répète pas
        return [_history(s, frame, ctx)]
    if journals:
        latest = journals[0]
        blocks.append(Prose(texts.get(latest.text_ref) or FORGOTTEN, title=f"Journal du {latest.day}, en entier", reading=True))
        told = ctx.store.content([latest.shareable_ref]).get(latest.shareable_ref) if latest.shareable_ref else None
        if told:
            blocks.append(Prose(told, title=f"Ce qu'elle en raconte à n'importe qui ({latest.day})", reading=True))
    # ce qu'elle dira de sa journée en cours, d'après les faits (sans modèle) : ce qui sera dit demain
    today = lived_day(frame)
    blocks.append(Prose(told_day(frame, ctx.store, s, today) or "—",
                        title=f"Sa journée en cours, telle qu'elle pourra la raconter ({today.isoformat()})", reading=True))
    return [*blocks, _timeline(journals, dreams, frame, texts), _history(s, frame, ctx)]
