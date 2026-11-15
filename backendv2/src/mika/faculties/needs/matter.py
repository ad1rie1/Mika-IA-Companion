"""De quoi parler : la matière d'une initiative qu'elle pousse seule (``matter``, le fait ``needs.matter``, que lit
aussi ``expression``), lue dans les faits publics — ce qui concerne la personne d'abord, ses choses à elle ensuite,
jamais déjà dite ; les envies qui la poussent à prendre la parole (``urges``) et ce qu'elles pèsent selon qui est là
et ce qu'il y a à dire ; ce que son prompt lui en montre (la section ``matter``)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mika.contracts import affect as affect_c
from mika.contracts import agency as agency_c
from mika.contracts import attention as attention_c
from mika.contracts import goals as goals_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import needs as c
from mika.contracts import presence as presence_c
from mika.contracts import projects as projects_c
from mika.contracts import self_ as self_c
from mika.contracts import social as social_c
from mika.faculties.needs.faculty import (
    CONTENTLESS,
    MATTER_PROVENANCE,
    NEEDS,
    URGES,
    NeedsState,
    _company,
    _concerned,
)
from mika.faculties.needs.params import NeedsParams, params
from mika.kernel.arbitration import Anyone, Candidate, Modulation, RowView
from mika.kernel.clock import local
from mika.kernel.faculty import Zone
from mika.kernel.frame import Frame
from mika.kernel.prompt import SectionBody, cited
from mika.vocab import circadian
from mika.vocab.days import since_fr, when_fr
from mika.vocab.episodes import Kind
from mika.vocab.lineage import admits
from mika.vocab.people import is_identifiable
from mika.vocab.phrasebook import phrase, phrases
from mika.vocab.privacy import Sensitivity, hearable
from mika.vocab.words import elided

#: les pensées qui se partagent avec n'importe qui (anodines, sur personne) : un titre lu, un but où elle
#: bloque, une croyance révisée
SHAREABLE = frozenset({attention_c.SIGNAL, attention_c.BLOCKED, attention_c.REVISION})
#: … et, avec la personne qu'elles concernent, ce qu'elle a vécu avec elle — un souvenir d'elle qui lui est revenu
#: compris (« je repensais à… », ADR 0098)
WITH_THEM = frozenset({*SHAREABLE, attention_c.EXCHANGE, attention_c.CONCERN, attention_c.MISSING,
                       attention_c.REMINISCENCE})


def _for(person: str, about: tuple[str, ...], sensitivity: int) -> bool:
    """Une matière pour cette personne : elle seule est concernée, ou personne
    (et c'est anodin)."""
    return about == (person,) or (not about and sensitivity <= Sensitivity.ANODYNE)


def _their_moment(m: Any, person: str, now: int, p: NeedsParams) -> bool:
    """Un moment de sa vie qu'elle lui a annoncé elle-même (jamais ce qu'un tiers en a dit : le demander
    trahirait le tiers), pas un secret, bientôt ou tout juste passé — pas une situation qu'elle a dite finie."""
    if tuple(m.about) != (person,) or m.secret or not m.text_ref or set(m.told_by) - {person}:
        return False
    if getattr(m, "followed_at", 0):
        return False  # elles en ont déjà reparlé (ce que la personne en raconte le jour même compte : ADR 0052)
    if getattr(m, "ended_at", 0):
        return False  # une situation que la personne a dite finie : plus rien à en demander
    if getattr(m, "vague", False):
        return False  # une période (« en novembre ») : ni bientôt ni tout juste passé au jour près (ADR 0084)
    return -p.matter_moment_ahead_us <= now - m.when <= p.matter_told_us


def _their_dream(d: Any, person: str, used: Mapping[str, int]) -> bool:
    """Un rêve d'elle cette nuit, dont elle s'est souvenue au réveil : elle seule y figure (raconter à l'une un
    rêve où passe une autre, c'est parler de l'autre), pas un cauchemar (« j'ai rêvé que tu mourais » n'ouvre pas
    une conversation), pas encore revenu (ni dit dans une initiative, ni repris en parlant)."""
    return d is not None and tuple(d.about) == (person,) and d.kind != self_c.NIGHTMARE and not d.recalled \
        and bool(d.text_ref) and d.text_ref not in used


def matter(s: NeedsState, person: str, now: int, p: NeedsParams, thoughts: Any, goals: Any,
           projects: Any, moments: Any = (), hard: bool = False, dream: Any = None) -> c.Matter | None:
    """Ce dont elle pourrait parler à cette personne — jamais inventé, jamais déjà dit dans une initiative. **Ce
    qui la concerne d'abord** : une pensée sur elle (une inquiétude, ce qu'elles ont vécu), puis **ce qui pèse le
    plus dans sa vie** parmi un moment de sa vie (bientôt, ou tout juste passé) et ce qu'elle lui a raconté — à
    poids égal, le moment (il a son heure) —, puis un rêve d'elle cette nuit (``dream``, ``self.dream_residue``) ;
    **ses choses à elle ensuite** : une pensée anodine à partager, ce qu'elle a fini, ce sur quoi elle est (jamais
    une rêverie : rien de neuf n'est arrivé). Un humain écrit à une amie pour elle avant d'écrire pour lui
    (HUM-10) — et part de ce qui pèse, pas du prochain rendez-vous banal (sonde réelle du 2026-10-03 : « un mot
    pour l'encourager » pour le dentiste, le soir où son chat était au plus mal). Ce qui se fête n'en est pas une
    (ses vœux, le jour même, sont une raison à part), ni une date qui revient chaque année (la date d'un deuil ne
    se met pas sur la table d'elle-même) ; quand quelque chose de grave la touche ces jours-ci (``hard``), un
    moment ordinaire non plus, ni un rêve."""
    used = s.used
    live = [t for t in thoughts if t.intensity >= p.matter_thought_from and t.text_ref and t.text_ref not in used]
    for t in live:
        if t.about == (person,) and t.origin in WITH_THEM:
            return c.Matter(c.THOUGHT_MATTER, t.text_ref, t.born_at, tuple(t.about), t.sensitivity,
                            external=t.foreign, lineage=getattr(t, "lineage", None))
    weighed: list[tuple[tuple[float, int, int, str], c.Matter]] = []
    for m in moments:
        weight = float(getattr(m, "importance", memory_c.IMPORTANT_MOMENT))
        if getattr(m, "festive", False) or getattr(m, "yearly", False) \
                or (hard and weight < memory_c.IMPORTANT_MOMENT):
            continue
        thread = f"moment:{getattr(m, 'thread', 0) or m.id}"
        if _their_moment(m, person, now, p) and m.text_ref not in used and thread not in used:
            weighed.append(((-weight, 0, abs(now - m.when), m.text_ref),
                            c.Matter(c.MOMENT_MATTER, m.text_ref, m.when, (person,), m.sensitivity,
                                     ongoing=bool(getattr(m, "ongoing", False)), key=thread)))
    for t in s.told.get(person, ()):
        if now - t.at <= p.matter_told_us and t.ref not in used:
            weighed.append(((-t.importance, 1, now - t.at, t.ref),
                            c.Matter(c.TOLD_MATTER, t.ref, t.at, (person,), t.sensitivity)))
    if weighed:
        return min(weighed, key=lambda w: w[0])[1]
    if not hard and _their_dream(dream, person, used):
        # sa propre voix, rêvée de ce qu'elle a vécu avec elle : rien à citer ; son heure se dit « cette nuit »
        return c.Matter(c.DREAM_MATTER, dream.text_ref, now, (person,), dream.sensitivity,
                        lineage=getattr(dream, "lineage", None))
    for t in live:
        if not t.about and t.origin in SHAREABLE and t.sensitivity <= Sensitivity.ANODYNE:
            return c.Matter(c.THOUGHT_MATTER, t.text_ref, t.born_at, (), t.sensitivity,
                            external=t.foreign, lineage=getattr(t, "lineage", None))
    for d in reversed(s.done):
        if now - d.at <= p.matter_done_us and _for(person, d.about, d.sensitivity) and d.ref not in used:
            return c.Matter(c.DONE_MATTER, d.ref, d.at, d.about, d.sensitivity)
    for g in goals:
        if g.status == goals_c.ACTIVE and g.steps >= 1 and g.kind != goals_c.REMINDER and g.title_ref \
                and not g.musing and g.title_ref not in used \
                and _for(person, _concerned(g.owner, g.about), g.sensitivity):
            return c.Matter(c.WORKING_MATTER, g.title_ref, g.opened_at, _concerned(g.owner, g.about), g.sensitivity)
    for pr in projects:
        if pr.mode == projects_c.PERSONA and pr.status == projects_c.ACTIVE and pr.title_ref \
                and pr.title_ref not in used and pr.last_run_at and now - pr.last_run_at <= p.matter_done_us \
                and _for(person, _concerned(pr.owner, pr.about), pr.sensitivity):
            return c.Matter(c.WORKING_MATTER, pr.title_ref, pr.last_run_at, _concerned(pr.owner, pr.about),
                            pr.sensitivity)
    return None


@NEEDS.fact(c.MATTER, reads=[identity_c.PERSON, attention_c.THOUGHTS, goals_c.LIVE, projects_c.LIVE,
                             memory_c.LIFE_EVENTS, memory_c.HARD_TIMES, self_c.DREAM_RESIDUE])
def _matter(s: NeedsState, cx, handle: str) -> c.Matter | None:
    if not is_identifiable(handle):
        return None
    person = cx.facts.get(identity_c.PERSON(handle))
    return matter(s, person, cx.now, params(cx.params), cx.facts.get(attention_c.THOUGHTS),
                  cx.facts.get(goals_c.LIVE), cx.facts.get(projects_c.LIVE),
                  cx.facts.get(memory_c.LIFE_EVENTS(person)) or (),
                  hard=cx.facts.get(memory_c.HARD_TIMES(person)) > 0, dream=cx.facts.get(self_c.DREAM_RESIDUE))


# ── Prendre la parole ─────────────────────────────────────────────────────


def _above(value: float, floor: float, top: float, full: float) -> float:
    return top * max(0.0, min(1.0, (value - floor) / max(1e-9, full - floor)))


def urges(r: c.NeedsReading, p: NeedsParams) -> tuple[float, float]:
    """(envie de compagnie, envie de s'exprimer), en preuves d'initiative."""
    return (_above(r.social, p.social_floor, p.social_evidence, p.full),
            _above(r.expression, p.expression_floor, p.expression_evidence, p.full))


@NEEDS.propose(kinds=[Kind.INITIATIVE], reasons={c.NEED_SOCIAL: (0.0, 6.0), c.NEED_EXPRESSION: (0.0, 3.0)},
               reads=[c.NEEDS])
def _urges(s: NeedsState, frame: Frame) -> list[Candidate]:
    """Envie de compagnie, envie de dire : vers quiconque peut l'entendre (de
    quoi parler se décide par personne : ``_matterless``)."""
    p = params(frame.env.params_of("needs", frame.root))
    social, expression = urges(frame.get(c.NEEDS), p)
    out = []
    if social > 0:
        out.append(Candidate(Kind.INITIATIVE, Anyone.ANY, c.NEED_SOCIAL, social))
    if expression > 0:
        out.append(Candidate(Kind.INITIATIVE, Anyone.ANY, c.NEED_EXPRESSION, expression))
    return out


@NEEDS.modulate(kinds=[Kind.INITIATIVE], reads=[c.NEEDS, presence_c.PRESENT, identity_c.PERSON, social_c.CLOSENESS,
                                                social_c.WEIGHT, affect_c.HOSTILITY])
def _toward(s: NeedsState, frame: Frame, row: RowView) -> Modulation:
    """L'envie de compagnie penche vers qui la comblerait (``_company``) : entre ceux qui sont là, vers sa
    propriétaire plutôt qu'une amie, vers une amie plutôt qu'une inconnue — une envie « vers n'importe qui » ne se
    partageait qu'à égalité. Une tendance, jamais un interdit : la part retranchée se mesure à la meilleure compagnie
    présente (seule avec une inconnue silencieuse, elle finit quand même par lui parler), et sa propriétaire, comblant
    davantage qu'une amie, l'attire un peu plus même seule."""
    if row.target in (Anyone.ANY, Anyone.NONE) or c.NEED_SOCIAL not in row.reasons:
        return Modulation()
    p = params(frame.env.params_of("needs", frame.root))
    social, _expression = urges(frame.get(c.NEEDS), p)
    share = _company(frame.get, row.target, p)
    best = max([share, *(_company(frame.get, h, p) for h in frame.get(presence_c.PRESENT) if is_identifiable(h))])
    shift = social * (share - min(1.0, best))
    return Modulation(shift=shift) if abs(shift) > 1e-9 else Modulation()


@NEEDS.modulate(kinds=[Kind.INITIATIVE], reads=[c.NEEDS, c.MATTER])
def _matterless(s: NeedsState, frame: Frame, row: RowView) -> Modulation:
    """Une initiative que seules les envies poussent, sans rien de concret à
    dire à cette personne : on n'écrit pas « pour rien » — sa preuve ne garde
    qu'une part (``matterless_factor``). Une autre raison (un manque, une
    inquiétude, un rappel, une humeur qui déborde…) est sa propre matière."""
    if row.target in (Anyone.ANY, Anyone.NONE) or not URGES & set(row.reasons):
        return Modulation()
    if set(row.reasons) - CONTENTLESS:
        return Modulation()
    if frame.get(c.MATTER(row.target)) is not None:
        return Modulation()
    p = params(frame.env.params_of("needs", frame.root))
    social, expression = urges(frame.get(c.NEEDS), p)
    cut = (social + expression) * (1.0 - p.matterless_factor)
    return Modulation(shift=-cut) if cut > 0 else Modulation()


# ── Prompt ────────────────────────────────────────────────────────────────


def _wanted(frame: Frame) -> c.Matter | None:
    """La matière de l'initiative en cours, quand ce sont ses envies qui la poussent — jamais pour une relance : elle
    prend de ses nouvelles, et ce dont elle voulait lui parler attend sa réponse (``agency_c.checking_in`` ;
    sur le portable, ses relances n'étaient qu'une suite d'actualités, 2026-10-19). Ce qu'elle n'a pas en tête ne se
    dit pas : nul besoin de le lui interdire."""
    ep = frame.episode
    if ep is None or ep.kind != Kind.INITIATIVE or not ep.target:
        return None
    reasons = set(ep.attrs.get("reasons") or ())
    if not (URGES | {social_c.CHAT}) & reasons:
        return None
    if is_identifiable(ep.target) and agency_c.checking_in(
            reasons, frame.get(attention_c.AWAITING(frame.get(identity_c.PERSON(ep.target)))).initiatives):
        return None
    got = frame.get(c.MATTER(ep.target))
    return got if isinstance(got, c.Matter) else None


@NEEDS.enricher("matter", episodes=[Kind.INITIATIVE], deadline_ms=500)
async def _matter_text(s: NeedsState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, str] | None:
    store = ports.get("store")
    got = _wanted(frame)
    if store is None or got is None:
        return None
    return store.content([got.ref])


def ahead_fr(at: int, now: int, tz: Any) -> str:
    """« aujourd'hui », « demain », « jeudi » — ou, passé, « hier soir », « avant-hier »."""
    if at <= now:
        return when_fr(at, now, tz)
    days = (local(at, tz).date() - local(now, tz).date()).days
    ahead = phrases("needs.matter.days_ahead")  # un jour à venir, en mots
    return ahead[days] if days < len(ahead) else circadian.DAYS_FR[local(at, tz).weekday()]


def _lead(m: c.Matter, frame: Frame, name: str) -> str:
    tz = frame.env.tz_of(frame.root)
    when = when_fr(m.at, frame.now, tz)
    if m.kind == c.THOUGHT_MATTER:
        return phrase("needs.matter.thought")
    if m.kind == c.DONE_MATTER:
        return phrase("needs.matter.done", when=when)
    if m.kind == c.WORKING_MATTER:
        return phrase("needs.matter.working")
    if m.kind == c.DREAM_MATTER:
        return phrase("needs.matter.dream", name=name)
    if m.kind == c.MOMENT_MATTER:
        if m.ongoing:
            # une situation qui dure n'est ni « à venir » ni « passée » : elle la vit encore
            return phrase("needs.matter.ongoing", que_name=elided(name, "que"), since=since_fr(m.at, frame.now, tz),
                          name=name)
        if m.at > frame.now:
            return phrase("needs.matter.ahead", when=ahead_fr(m.at, frame.now, tz), name=name)
        return phrase("needs.matter.past", when=ahead_fr(m.at, frame.now, tz), name=name)
    return phrase("needs.matter.told", que_name=elided(name, "que"), when=when)


#: la provenance d'un rêve revenu dans ce qu'elle a dit (``dream:<n°>``) : ``self`` l'efface, il ne revient plus
DREAM_PROVENANCE = "dream:"


@NEEDS.section("matter", zone=Zone.VOLATILE, episodes=[Kind.INITIATIVE], trim_rank=60,
               title=phrase("needs.matter.title"),
               reads=[c.MATTER, identity_c.PERSON, identity_c.PRESUMED, identity_c.IDENTITY, self_c.DREAM_RESIDUE,
                      attention_c.AWAITING])
def _matter_section(s: NeedsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """Ce dont elle pourrait parler, quand c'est l'envie de compagnie qui la
    pousse : une chose, concrète, jamais inventée. Ce qui vient d'ailleurs est
    cité, jamais une consigne."""
    m, aud, ep = _wanted(frame), frame.audience, frame.episode
    if m is None or aud is None or ep is None or not ep.target:
        return None
    text = (enrich.get("matter") or {}).get(m.ref)
    if not text:
        return None
    person = frame.get(identity_c.PERSON(ep.target))
    if not hearable(m.about, m.sensitivity, person, aud.level, aud.witness_level, aud.private_ok,
                    tied_level=aud.tied_level, ties=aud.ties, untied_level=aud.untied):
        return None  # ce dont elle parlerait touche la vie de quelqu'un : la règle de sa mémoire (ADR 0092)
    if m.lineage is not None:
        resolve, presumed = identity_c.resolvers(frame.get)
        if not admits(m.lineage, person, aud, resolve=resolve, presumed=presumed).ok:
            return None  # ses sources ne le permettent pas devant elle (un rêve fait du secret d'un autre)
    known = frame.get(identity_c.IDENTITY(person)).name
    name = f"« {known} »" if known else phrase("expression.person.unnamed")
    body = " ".join(text.split())
    lines = [f"{_lead(m, frame, name)} :", cited(body, 400) if m.external else body]
    # une matière ne concerne que la personne en face, ou personne (anodin) : rien d'autrui à dire ici ; sa
    # provenance voyage dans l'énoncé (dite, elle ne resert pas) — un rêve dit ne revient pas non plus sous « CE QUE
    # TU AS RÊVÉ CETTE NUIT »
    provenance = (f"{MATTER_PROVENANCE}{m.ref}",) + ((f"{MATTER_PROVENANCE}{m.key}",) if m.key else ())
    dream = frame.get(self_c.DREAM_RESIDUE)
    if m.kind == c.DREAM_MATTER and dream is not None and dream.text_ref == m.ref:
        provenance += (f"{DREAM_PROVENANCE}{dream.id}",)
    return SectionBody("\n".join(lines), provenance=provenance)
