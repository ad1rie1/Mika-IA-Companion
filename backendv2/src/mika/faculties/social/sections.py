"""Ce que ``social`` met dans le prompt.

- **Ce que tu sais de cette personne** : son profil et votre rythme — sa
  fiche, donc seulement quand elle est ouverte (jamais en public, jamais
  sous la barre de certitude). Le profil ne se nourrit que de ce que la
  personne a dit elle-même (``profile``) ; ce qu'il dit d'autres gens, elle
  l'a raconté elle-même : la section se mesure au niveau « témoin ».

- **Le ton entre vous** : la manière d'être selon ce qui vous lie — et, avec
  une amie ou une proche, en privé, ce qui n'appartient qu'à vous (comment elle
  t'appelle, le surnom que tu lui donnes, vos blagues : ``memory``, colonne
  ``between_us``, ADR 0055). Jamais avec une inconnue, jamais en public.

Quand ils se sont parlé pour la dernière fois est dit dans « QUI TU AS EN
FACE » (``identity``). Ce que tu perçois de son état (le ton de son message,
et ce qui tranche avec son ton habituel) est tenu par ``others``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import social as c
from mika.faculties.social.faculty import SOCIAL, THEM, Profile, SocialState, contact_of, params
from mika.faculties.social.profile import describe_level, lines_of, register
from mika.kernel.faculty import Zone
from mika.kernel.frame import Frame
from mika.kernel.prompt import SectionBody, readable
from mika.vocab.episodes import CONVERSATIONAL
from mika.vocab.people import is_identifiable
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import Sensitivity


def profile_parts(profile: Profile, texts: Mapping[str, str]) -> tuple[str | None, str, tuple[str, ...],
                                                                         tuple[str, ...]]:
    """(portrait, ton, intérêts, sujets délicats) — gardés à part (ou en clair, pour
    un profil d'avant la version 2). Un texte oublié se tait."""
    summary = texts.get(profile.summary_ref) if profile.summary_ref else None
    tone = (texts.get(profile.tone_ref) or "") if profile.tone_ref else profile.tone
    interests = lines_of(texts.get(profile.interests_ref)) if profile.interests_ref else profile.interests
    sensitive = lines_of(texts.get(profile.sensitive_ref)) if profile.sensitive_ref else profile.sensitive
    return summary, tone, tuple(interests), tuple(sensitive)


def refs_of(profile: Profile) -> list[str]:
    return [r for r in (profile.summary_ref, profile.tone_ref, profile.interests_ref, profile.sensitive_ref) if r]


def _they_opened(s: SocialState, frame: Frame, person: str) -> bool:
    """La conversation en cours, c'est la personne qui l'a ouverte (la dernière ouverture comptée est la sienne, le
    jour où elle a commencé) : lui souffler que ça lui pèse, c'est l'accueillir d'un reproche au moment même où elle
    fait le pas."""
    gap = params(frame.env.params_of("social", frame.root)).conversation_gap_us
    ct = contact_of(s, person, frame.get(identity_c.HANDLES(person)))
    if ct is None or not ct.starts or frame.now - ct.last_activity >= gap:
        return False  # pas de conversation en cours : ce qu'elle va écrire en ouvrira une
    return ct.starts[-1] == (frame.local(ct.since).date().toordinal(), THEM)


@SOCIAL.section("about_person", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, after=["who"], before=["stance"],
                trim_rank=65, title=phrase("social.about.title"),
                reads=[identity_c.PERSON, identity_c.IDENTITY, identity_c.HANDLES, c.CONTACT, c.CLOSENESS,
                       memory_c.HARD_TIMES])
def _about(s: SocialState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    aud, ep = frame.audience, frame.episode
    if aud is None or ep is None or not ep.target or not aud.private_ok:
        return None  # sa fiche : jamais en public, jamais sous la barre
    person = frame.get(identity_c.PERSON(ep.target))
    level = frame.get(c.CLOSENESS(person))
    reading = frame.get(c.CONTACT(person))
    name = frame.get(identity_c.IDENTITY(person)).name or frame.get(identity_c.IDENTITY(ep.target)).name
    who = f"« {name} »" if name else phrase("social.about.someone")
    lines = [describe_level(level, name)]
    profile = s.profiles.get(person)
    if profile is not None:
        summary, tone, interests, sensitive = profile_parts(profile, enrich.get("profile_text") or {})
        if summary:
            lines.append(summary)
        if tone:
            lines.append(phrase("social.about.tone", tone=tone))
        if interests:
            lines.append(phrase("social.about.interests", interests=", ".join(interests)))
        if sensitive:
            lines.append(phrase("social.about.sensitive", who=who, topics=", ".join(sensitive)))
    if reading.days >= 3 and reading.measured:
        n = round(reading.rhythm_days)
        lines.append(phrase("social.about.rhythm_daily") if n <= 1 else phrase("social.about.rhythm_days", days=n))
    # ni pendant ses jours durs (on ne tient pas de comptes), ni quand la personne vient d'écrire la première
    if reading.one_sided and not frame.get(memory_c.HARD_TIMES(person)) and not _they_opened(s, frame, person):
        lines.append(phrase("social.about.one_sided"))
    if len(lines) == 1 and level == c.STRANGER:
        return None
    # sa propre fiche : ce qu'elle dit d'autres gens, la personne l'a raconté elle-même (témoin)
    return SectionBody("\n".join(lines), level=int(Sensitivity.PERSONAL), witness=True)


#: ses notes sont à la première personne (« Sam m'appelle « Mikachu » ») ; l'état qu'on lui montre lui parle à la
#: deuxième — mêler les deux faisait répondre un modèle à la place de Sam (« merci Mikachu ! », sonde du 2026-10-03)
_TO_YOU = ((re.compile(r"\bm'(?=appell|surnomm)"), "t'"), (re.compile(r"\bme (?=surnomm|dit|traite)"), "te "),
           (re.compile(r"\bmoi\b"), "toi"), (re.compile(r"\bnotre\b"), "votre"), (re.compile(r"\bnos\b"), "vos"))


def to_you(text: str) -> str:
    """Une note d'elle (« Sam m'appelle « Mikachu » »), dite à elle (« Sam t'appelle « Mikachu » »)."""
    for pattern, repl in _TO_YOU:
        text = pattern.sub(repl, text)
    return text


@SOCIAL.section("register", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, after=["who"], before=["about_person"],
                trim_rank=70, title=phrase("social.register.title"), reads=[identity_c.PERSON, c.CLOSENESS])
def _register(s: SocialState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """Comment être avec la personne en face, selon ce qui vous lie — taquine avec qui elle connaît, pas avec une
    inconnue. Rien de la fiche : juste une manière d'être, dite même quand la fiche est fermée."""
    ep, aud = frame.episode, frame.audience
    if ep is None or not ep.target or not is_identifiable(ep.target):
        return None
    level = frame.get(c.CLOSENESS(frame.get(identity_c.PERSON(ep.target))))
    lines = [register(level)]
    ours = enrich.get("between_us") or ()
    if ours and aud is not None and aud.private_ok and level in (c.FRIEND, c.CLOSE):
        lines += [phrase("social.register.ours"),
                  *(f"- {to_you(text)}" for _i, text in ours)]
        return SectionBody("\n".join(lines), provenance=tuple(f"memory:{i}" for i, _t in ours))
    return SectionBody("\n".join(lines))


@SOCIAL.enricher("profile_text", episodes=CONVERSATIONAL, deadline_ms=500)
async def _profile_text(s: SocialState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, str] | None:
    store = ports.get("store")
    ep, aud = frame.episode, frame.audience
    if store is None or ep is None or not ep.target or aud is None or not aud.private_ok:
        return None
    profile = s.profiles.get(frame.get(identity_c.PERSON(ep.target)))
    refs = refs_of(profile) if profile is not None else []
    return store.content(refs) if refs else None


#: ce qui n'appartient qu'à vous, montré au plus
BETWEEN_SHOWN = 4


def between_us(store: Any, frame: Frame, person: str) -> tuple[tuple[int, str], ...]:
    """Ce qui n'appartient qu'à elle et à cette personne (``memory`` : un surnom, leur blague) — de première main :
    ce que la personne lui en a dit, ou ce qu'elle-même en a dit, jamais ce qu'un tiers en raconte."""
    handles = sorted({person, *frame.get(identity_c.HANDLES(person))})
    where = " OR ".join("about LIKE ?" for _ in handles)
    rows = store.query_mind(
        f"SELECT id, text, told_by FROM {memory_c.ITEMS_TABLE} WHERE kind=? AND status='active' AND between_us=1 "
        f"AND ({where}) ORDER BY importance DESC, id DESC LIMIT ?",
        (memory_c.BELIEF, *(f'%"{h}"%' for h in handles), BETWEEN_SHOWN * 2))
    out = []
    for i, text, told_by in rows:
        try:
            tellers = set(json.loads(told_by or "[]"))
        except ValueError:
            continue
        if text and tellers <= set(handles):
            out.append((int(i), str(text)))
    return tuple(out[:BETWEEN_SHOWN])


@SOCIAL.enricher("between_us", episodes=CONVERSATIONAL, deadline_ms=500)
async def _between_us(s: SocialState, frame: Frame, ports: Mapping[str, Any]) -> tuple[tuple[int, str], ...] | None:
    """Avec une amie ou une proche, en privé : ce qui n'appartient qu'à vous."""
    store = ports.get("store")
    ep, aud = frame.episode, frame.audience
    if store is None or ep is None or not ep.target or aud is None or not aud.private_ok:
        return None
    person = frame.get(identity_c.PERSON(ep.target))
    if not is_identifiable(person) or frame.get(c.CLOSENESS(person)) not in (c.FRIEND, c.CLOSE):
        return None
    return between_us(store, frame, person) or None


# ── Outil : relire sa fiche de la personne en face (même porte que la section) ──

SOCIAL.bundle("social", phrase("social.tools.bundle"))


class NoArgs(BaseModel):
    pass


@SOCIAL.tool("social_about", description=phrase("social.tools.about.description"), args=NoArgs, bundle="social",
             episodes=CONVERSATIONAL)
async def social_about(args: NoArgs, ctx: Any) -> str:
    aud = ctx.frame.audience
    if aud is None or not aud.private_ok:
        return phrase("social.tools.about.closed")
    enrich = {"profile_text": await _profile_text(ctx.state, ctx.frame, ctx.ports) or {}}
    return readable(_about(ctx.state, ctx.frame, enrich), aud) or phrase("social.tools.about.empty")
