"""Ce que ``social`` met dans le prompt.

- **Ce que tu sais de cette personne** : son profil et votre rythme — sa
  fiche, donc seulement quand elle est ouverte (jamais en public, jamais
  sous la barre de certitude). Le profil ne se nourrit que de ce que la
  personne a dit elle-même (``profile``) ; ce qu'il dit d'autres gens, elle
  l'a raconté elle-même : la section se mesure au niveau « témoin ».

Quand ils se sont parlé pour la dernière fois est dit dans « QUI TU AS EN
FACE » (``identity``). Ce que tu perçois de son état (le ton de son message,
et ce qui tranche avec son ton habituel) est tenu par ``others``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from mika.contracts import identity as identity_c
from mika.contracts import social as c
from mika.faculties.social.faculty import SOCIAL, Profile, SocialState
from mika.faculties.social.profile import describe_level, lines_of, register
from mika.kernel.faculty import Zone
from mika.kernel.frame import Frame
from mika.kernel.prompt import SectionBody, readable
from mika.vocab.episodes import CONVERSATIONAL
from mika.vocab.people import is_identifiable
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


@SOCIAL.section("about_person", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, after=["who"], before=["stance"],
                trim_rank=65, title="CE QUE TU SAIS DE CETTE PERSONNE",
                reads=[identity_c.PERSON, identity_c.IDENTITY, c.CONTACT, c.CLOSENESS])
def _about(s: SocialState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    aud, ep = frame.audience, frame.episode
    if aud is None or ep is None or not ep.target or not aud.private_ok:
        return None  # sa fiche : jamais en public, jamais sous la barre
    person = frame.get(identity_c.PERSON(ep.target))
    level = frame.get(c.CLOSENESS(person))
    reading = frame.get(c.CONTACT(person))
    name = frame.get(identity_c.IDENTITY(person)).name or frame.get(identity_c.IDENTITY(ep.target)).name
    who = f"« {name} »" if name else "cette personne"
    lines = [describe_level(level, name)]
    profile = s.profiles.get(person)
    if profile is not None:
        summary, tone, interests, sensitive = profile_parts(profile, enrich.get("profile_text") or {})
        if summary:
            lines.append(summary)
        if tone:
            lines.append(f"Comment lui parler : {tone}")
        if interests:
            lines.append("Ce qui l'intéresse : " + ", ".join(interests) + ".")
        if sensitive:
            lines.append(f"Sujets délicats avec {who} : " + ", ".join(sensitive) + ".")
    if reading.days >= 3 and reading.measured:
        n = round(reading.rhythm_days)
        lines.append(f"Vous vous parlez à peu près {'tous les jours' if n <= 1 else f'tous les {n} jours'}.")
    if reading.one_sided:
        lines.append("Ces derniers temps, c'est presque toujours toi qui écris la première ; ça te pèse un peu.")
    if len(lines) == 1 and level == c.STRANGER:
        return None
    # sa propre fiche : ce qu'elle dit d'autres gens, la personne l'a raconté elle-même (témoin)
    return SectionBody("\n".join(lines), level=int(Sensitivity.PERSONAL), witness=True)


@SOCIAL.section("register", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, after=["who"], before=["about_person"],
                trim_rank=70, title="LE TON ENTRE VOUS", reads=[identity_c.PERSON, c.CLOSENESS])
def _register(s: SocialState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """Comment être avec la personne en face, selon ce qui vous lie — taquine avec qui elle connaît, pas avec une
    inconnue. Rien de la fiche : juste une manière d'être, dite même quand la fiche est fermée."""
    ep = frame.episode
    if ep is None or not ep.target or not is_identifiable(ep.target):
        return None
    return SectionBody(register(frame.get(c.CLOSENESS(frame.get(identity_c.PERSON(ep.target))))))


@SOCIAL.enricher("profile_text", episodes=CONVERSATIONAL, deadline_ms=500)
async def _profile_text(s: SocialState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, str] | None:
    store = ports.get("store")
    ep, aud = frame.episode, frame.audience
    if store is None or ep is None or not ep.target or aud is None or not aud.private_ok:
        return None
    profile = s.profiles.get(frame.get(identity_c.PERSON(ep.target)))
    refs = refs_of(profile) if profile is not None else []
    return store.content(refs) if refs else None


# ── Outil : relire sa fiche de la personne en face (même porte que la section) ──

SOCIAL.bundle("social", "relire qui t'écrit et ce que tu sais de cette personne, si ton état ne le dit pas déjà")


class NoArgs(BaseModel):
    pass


@SOCIAL.tool("social_about", description="Relire ce que tu sais de la personne à qui tu parles (ce qu'elle aime, "
             "ce qui la touche, où vous en êtes) — seulement si « CE QUE TU SAIS DE CETTE PERSONNE » manque à ton "
             "état : sinon, c'est déjà sous tes yeux.", args=NoArgs, bundle="social", episodes=CONVERSATIONAL)
async def social_about(args: NoArgs, ctx: Any) -> str:
    aud = ctx.frame.audience
    if aud is None or not aud.private_ok:
        return "Tu ne peux pas relire de fiche sur cette personne ici."
    enrich = {"profile_text": await _profile_text(ctx.state, ctx.frame, ctx.ports) or {}}
    return readable(_about(ctx.state, ctx.frame, enrich), aud) or "Tu ne sais encore presque rien de cette personne."
