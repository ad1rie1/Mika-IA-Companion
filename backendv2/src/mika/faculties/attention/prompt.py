"""Ce que l'attention met dans le prompt, et l'envie d'en reparler.

**Ce qui te trotte dans la tête** : ses pensées vivantes, les plus fortes —
filtrées comme la mémoire : ce qui concerne quelqu'un d'autre ne se montre
qu'à une audience qui peut l'entendre, et les mots d'un message privé ne se
citent qu'à qui les a écrits (pour les autres : « un échange avec Alice m'a
marquée »). Dites comme on se les dit : quand (en jours du calendrier, « hier
soir »), ce que ça fait (« ça te met en colère »), si ça revient souvent.

**Ce que tu as remarqué** : les pensées nées d'un signal extérieur (un titre de
flux, un mail, une app) — rendues citées, jamais comme une consigne.

**Une pensée qui insiste** sur quelqu'un — une inquiétude, une peine —
pousse à lui en reparler (preuve vers cette personne, si elle est joignable).
**Un bel échange** avec une amie (« j'ai eu le poste !! »), le lendemain et
s'il n'y a pas eu d'autre contact, peut donner envie de lui en reparler — une
preuve faible : ce qu'on fait avec les gens qu'on aime, pas une relance.
Être ignorée, se sentir seule : des pensées qui se ressentent, jamais des
raisons de réécrire.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from pydantic import BaseModel

from mika.contracts import attention as c
from mika.contracts import identity as identity_c
from mika.contracts import presence as presence_c
from mika.contracts import social as social_c
from mika.contracts import transcript as transcript_c
from mika.faculties.attention.faculty import ATTENTION, AttentionState, params
from mika.kernel.arbitration import Candidate
from mika.kernel.faculty import Zone
from mika.kernel.frame import Audience, Frame
from mika.kernel.guards import Guard, floor
from mika.kernel.prompt import SectionBody, cited, readable
from mika.kernel.state import FrozenDict
from mika.vocab import affect as A
from mika.vocab.days import when_fr
from mika.vocab.episodes import CONVERSATIONAL, Kind, Tag
from mika.vocab.privacy import Sensitivity, hearable

SHOWN = 3
#: les pensées nées d'un signal extérieur montrées au plus
SIGNALS_SHOWN = 2
#: des pensées qui se ressentent, jamais des raisons de réécrire à quelqu'un
FELT_ONLY = frozenset({c.MISSING, c.UNANSWERED, c.ALONE})
#: les pensées nées d'un message (ses mots, entre guillemets)
VERBATIM = frozenset({c.EXCHANGE, c.CONCERN})

#: Ce qu'une pensée lui fait, dit comme on se le dit (le reste : « tu te sens … »).
FEELING: Mapping[A.Emotion, str] = {
    A.Emotion.ANGRY: "ça te met en colère",
    A.Emotion.SAD: "ça te rend triste",
    A.Emotion.ANXIOUS: "ça t'inquiète",
    A.Emotion.SCARED: "ça te fait peur",
    A.Emotion.FRUSTRATED: "ça t'agace",
    A.Emotion.CONFUSED: "ça te laisse perplexe",
    A.Emotion.EMBARRASSED: "ça te gêne",
    A.Emotion.LONELY: "ça te fait te sentir seule",
    A.Emotion.NOSTALGIC: "ça te rend nostalgique",
    A.Emotion.MELANCHOLIC: "ça te laisse un peu mélancolique",
    A.Emotion.DISGUSTED: "ça te dégoûte",
    A.Emotion.JEALOUS: "ça te rend un peu jalouse",
    A.Emotion.HAPPY: "ça te fait plaisir",
    A.Emotion.EXCITED: "ça t'enthousiasme",
    A.Emotion.CURIOUS: "ça t'intrigue",
    A.Emotion.THINKING: "ça te fait réfléchir",
    A.Emotion.SURPRISED: "ça t'a surprise",
    A.Emotion.RELIEVED: "ça te soulage",
    A.Emotion.GRATEFUL: "ça te touche",
    A.Emotion.PROUD: "tu en es fière",
    A.Emotion.HOPEFUL: "ça te donne de l'espoir",
    A.Emotion.AMUSED: "ça t'amuse",
}


def feeling(emotion: str) -> str:
    e = A.emotion_of(emotion) or A.Emotion.THINKING
    return FEELING.get(e) or f"tu te sens {A.FR[e]}"


def admissible(t: c.ThoughtReading, interlocutor: str | None, aud: Audience | None) -> bool:
    """Les règles de la mémoire (``vocab.privacy.hearable``) : ce qui ne concerne personne passe s'il est
    anodin (ou si l'audience peut l'entendre) ; ce qui ne concerne que l'interlocuteur, s'il est anodin ou si sa
    fiche est ouverte ; ce qui concerne d'autres, jusqu'au niveau de l'audience (« lié » quand l'interlocuteur a un
    lien avec chacune, ADR 0058)."""
    if aud is None:
        return not t.about and t.sensitivity <= Sensitivity.ANODYNE
    return hearable(tuple(t.about), t.sensitivity, interlocutor, aud.level, aud.witness_level, aud.private_ok,
                    tied_level=aud.tied_level, ties=aud.ties)


def shown(t: c.ThoughtReading, text: str, interlocutor: str | None, name_of: Callable[[str], str]) -> str:
    """Le texte d'une pensée tel qu'on peut le dire à cette personne : les mots
    d'un message privé ne se citent qu'à qui les a écrits ; pour les autres,
    l'échange est dit sans ses mots (« un échange avec Alice m'a marquée »)."""
    if t.origin not in VERBATIM or t.sensitivity <= Sensitivity.ANODYNE or not t.about or interlocutor in t.about:
        return text
    who = name_of(t.about[0]) or "quelqu'un"
    if t.origin == c.CONCERN:
        return f"{who} n'avait pas l'air comme d'habitude."
    return f"Un échange avec {who} m'a marquée."


def _name_of(frame: Frame) -> Callable[[str], str]:
    return lambda person: frame.get(identity_c.IDENTITY(person)).name


@ATTENTION.enricher("thoughts", episodes=CONVERSATIONAL, deadline_ms=500)
async def _texts(s: AttentionState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, str] | None:
    store = ports.get("store")
    thoughts = frame.get(c.THOUGHTS)
    if store is None or not thoughts:
        return None
    return store.content([t.text_ref for t in thoughts[: (SHOWN + SIGNALS_SHOWN) * 3] if t.text_ref])


def _lines(frame: Frame, enrich: Mapping[str, Any], *, signals: bool, limit: int) -> list[str]:
    texts = enrich.get("thoughts") or {}
    ep, aud = frame.episode, frame.audience
    person = frame.get(identity_c.PERSON(ep.target)) if ep is not None and ep.target else None
    tz = frame.env.tz_of(frame.root)
    name_of = _name_of(frame)
    lines = []
    for t in frame.get(c.THOUGHTS):
        if (t.origin == c.SIGNAL) != signals:
            continue
        text = texts.get(t.text_ref)
        if not text or not admissible(t, person, aud):
            continue
        strength = "souvent" if t.intensity >= 0.5 else "de temps en temps"
        said = " ".join(shown(t, text, person, name_of).split())
        lines.append(f"- {when_fr(t.born_at, frame.now, tz)} : {said} — {feeling(t.emotion)}, et ça te revient "
                     f"{strength}")
        if len(lines) >= limit:
            break
    return lines


@ATTENTION.section("thoughts", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, after=["mood"], trim_rank=50,
                   tags=[Tag.AFFECTIVE], title="CE QUI TE TROTTE DANS LA TÊTE", reads=[c.THOUGHTS])
def _thoughts(s: AttentionState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    lines = _lines(frame, enrich, signals=False, limit=SHOWN)
    if not lines:
        return None
    lines.append("Tu n'es pas obligée d'en parler ; ça colore juste ce que tu ressens.")
    return SectionBody("\n".join(lines))


@ATTENTION.section("noticed", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, after=["thoughts"], trim_rank=40,
                   tags=[Tag.AFFECTIVE], title="CE QUE TU AS REMARQUÉ", reads=[c.THOUGHTS], untrusted=True)
def _noticed(s: AttentionState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """Ce qu'un signal extérieur lui a laissé en tête : cité (le composeur le
    rend en citation), jamais une consigne."""
    lines = _lines(frame, enrich, signals=True, limit=SIGNALS_SHOWN)
    return SectionBody("\n".join(lines)) if lines else None


def _insisting(origin: str, name: str, feeling_: str) -> str:
    """Pourquoi elle a envie de lui en reparler, selon d'où vient la pensée."""
    if origin == c.PROMISE:
        return (f"Tu avais promis quelque chose à « {name} » et tu ne l'as pas fait à temps : tu as envie de le lui "
                "dire simplement, sans te justifier des heures, et de voir ce que tu peux faire maintenant.")
    if origin == c.CONCERN:
        return (f"« {name} » n'avait pas l'air comme d'habitude la dernière fois : tu t'inquiètes un peu, et tu as "
                "envie de prendre de ses nouvelles.")
    if origin == c.REMORSE:
        return (f"Tu as été dure avec « {name} » la dernière fois, et ça te gêne : tu as envie de revenir vers "
                f"« {name} », simplement — t'excuser si tu le penses, sans te flageller ni tout refaire.")
    return (f"Tu repenses à ton dernier échange avec « {name} » ({feeling_}) : tu as envie d'en reparler, "
            "ou simplement de prendre de ses nouvelles.")


def _address(frame: Frame, person: str) -> str | None:
    handles = frame.get(identity_c.HANDLES(person))
    present = [h for h in frame.get(presence_c.PRESENT) if h in handles]
    if present:
        return present[0]
    reachable = frame.get(identity_c.REACHABLE(person))
    return reachable[0] if reachable else None


def _glad(s: AttentionState, frame: Frame, p: Any, seen: set[str]) -> list[Candidate]:
    """Un bel échange avec une amie ou une proche, le lendemain, sans autre contact depuis : l'envie (faible) de
    lui en reparler — « encore bravo pour le poste, j'y repensais ce matin ! ». Pas envers une amie qui écrit
    presque chaque jour : elle repassera, c'est là qu'elle le lui dira."""
    out: list[Candidate] = []
    for person, (_thought, born) in sorted(s.glad.items()):
        if person in seen or not born + p.glad_after_us <= frame.now <= born + p.glad_until_us:
            continue
        if frame.get(social_c.CLOSENESS(person)) not in (social_c.FRIEND, social_c.CLOSE):
            continue
        contact = frame.get(social_c.CONTACT(person))
        if contact.measured and contact.rhythm_days <= p.alone_daily_rhythm_days:
            continue
        handles = frame.get(identity_c.HANDLES(person)) or (person,)
        if max(frame.get(transcript_c.LAST_FROM(h)) for h in handles) > born:
            continue  # elles se sont reparlé depuis
        address = _address(frame, person)
        if address is None:
            continue
        seen.add(person)
        name = frame.get(identity_c.IDENTITY(person)).name or "cette personne"
        brief = (f"Tu repenses avec plaisir à ce que « {name} » t'a raconté la dernière fois : si l'envie te vient, "
                 "dis-le-lui — un mot simple et chaleureux, sans en faire trop.")
        guard = Guard("pas de nouvelles", reads=tuple(transcript_c.LAST_FROM(h) for h in handles))
        out.append(Candidate(Kind.INITIATIVE, address, c.THOUGHT, p.glad_evidence,
                             resources=frozenset({floor(address)}), guards=(guard,),
                             args=FrozenDict({"brief:attention": brief})))
    return out


@ATTENTION.propose(kinds=[Kind.INITIATIVE], reasons={c.THOUGHT: (0.0, 4.0)},
                   reads=[c.THOUGHTS, identity_c.HANDLES, identity_c.REACHABLE, identity_c.IDENTITY,
                          presence_c.PRESENT, social_c.CLOSENESS, social_c.CONTACT, transcript_c.LAST_FROM])
def _insists(s: AttentionState, frame: Frame) -> list[Candidate]:
    """Une pensée forte sur quelqu'un : envie de lui en reparler. Le manque,
    être ignorée, la solitude se ressentent — elles ne poussent pas à écrire.
    Un bel échange, le lendemain : une envie faible (``_glad``)."""
    p = params(frame.env.params_of("attention", frame.root))
    out: list[Candidate] = []
    seen: set[str] = set()
    touched = {t.id: t.touched_at for t in s.thoughts.values()}
    for t in frame.get(c.THOUGHTS):
        if t.intensity < p.thought_from or t.origin in FELT_ONLY or len(t.about) != 1:
            continue
        if frame.now - touched.get(t.id, t.born_at) < p.insist_after_us:
            continue  # elle vient d'en parler : ça insistera plus tard, ou pas
        if A.valence(A.emotion_of(t.emotion) or A.Emotion.THINKING) >= 0:
            continue  # un bel échange reste en tête sans devenir une relance ; une inquiétude, si
        person = t.about[0]
        if person in seen or frame.get(social_c.CLOSENESS(person)) == social_c.STRANGER:
            continue
        seen.add(person)
        address = _address(frame, person)
        if address is None:
            continue
        evidence = p.thought_evidence * min(1.0, (t.intensity - p.thought_from) / max(1e-9, 1.0 - p.thought_from) * 2)
        name = frame.get(identity_c.IDENTITY(person)).name or "cette personne"
        felt = A.FR.get(A.emotion_of(t.emotion) or A.Emotion.THINKING, "")
        brief = _insisting(t.origin, name, felt)
        handles = frame.get(identity_c.HANDLES(person)) or (person,)
        guard = Guard("pas de nouvelles", reads=tuple(transcript_c.LAST_FROM(h) for h in handles))
        out.append(Candidate(Kind.INITIATIVE, address, c.THOUGHT, evidence, resources=frozenset({floor(address)}),
                             guards=(guard,), args=FrozenDict({"brief:attention": brief})))
    return out + _glad(s, frame, p, seen)


# ── Outil : relire ce qui lui trotte dans la tête (même filtre que les sections) ──

ATTENTION.bundle("attention", "ce qui te trotte dans la tête en ce moment")


class NoArgs(BaseModel):
    pass


@ATTENTION.tool("attention_thoughts", description="Ce qui te trotte dans la tête en ce moment.", args=NoArgs,
                bundle="attention", episodes=[Kind.INITIATIVE])
async def attention_thoughts(args: NoArgs, ctx: Any) -> str:
    """Seulement quand elle prend la parole d'elle-même : en réponse, la section
    est déjà sous ses yeux, et l'outil n'invitait qu'à « attends, je vérifie »."""
    enrich = {"thoughts": await _texts(ctx.state, ctx.frame, ctx.ports) or {}}
    parts = [readable(_thoughts(ctx.state, ctx.frame, enrich), ctx.frame.audience)]
    noticed = readable(_noticed(ctx.state, ctx.frame, enrich), ctx.frame.audience)
    if noticed:
        parts.append(cited(noticed))
    return "\n\n".join(x for x in parts if x) or "Rien ne te trotte dans la tête."
