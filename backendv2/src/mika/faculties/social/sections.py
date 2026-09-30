"""Ce que ``social`` met dans le prompt.

- **Ce que tu sais de cette personne** : son profil et votre rythme — sa
  fiche, donc seulement quand elle est ouverte (jamais en public, jamais
  sous la barre de certitude).

Ce que tu perçois de son état (le ton de son message, et ce qui tranche avec
son ton habituel) est tenu par ``others``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from mika.contracts import identity as identity_c
from mika.contracts import social as c
from mika.faculties.social.faculty import SOCIAL, SocialState
from mika.faculties.social.profile import describe_level
from mika.kernel.clock import DAY
from mika.kernel.faculty import Zone
from mika.kernel.frame import Frame
from mika.kernel.prompt import SectionBody, readable
from mika.vocab.episodes import CONVERSATIONAL, Kind
from mika.vocab.privacy import Sensitivity


def _ago(then: int, now: int) -> str:
    days = (now - then) / DAY
    if days < 1:
        return "aujourd'hui"
    if days < 2:
        return "hier"
    return f"il y a {round(days)} jours"


@SOCIAL.section("about_person", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, after=["who"], before=["stance"],
                trim_rank=65, title="CE QUE TU SAIS DE CETTE PERSONNE",
                reads=[identity_c.PERSON, c.CONTACT, c.CLOSENESS])
def _about(s: SocialState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    aud, ep = frame.audience, frame.episode
    if aud is None or ep is None or not ep.target or not aud.private_ok:
        return None  # sa fiche : jamais en public, jamais sous la barre
    person = frame.get(identity_c.PERSON(ep.target))
    level = frame.get(c.CLOSENESS(person))
    reading = frame.get(c.CONTACT(person))
    lines = [f"Pour toi, c'est {describe_level(level)}."]
    profile = s.profiles.get(person)
    store_text = enrich.get("profile_text") or {}
    if profile is not None:
        summary = store_text.get(profile.summary_ref)
        if summary:
            lines.append(summary)
        if profile.tone:
            lines.append(f"Comment lui parler : {profile.tone}")
        if profile.interests:
            lines.append("Ce qui l'intéresse : " + ", ".join(profile.interests) + ".")
        if profile.sensitive:
            lines.append("Sujets délicats avec elle ou lui : " + ", ".join(profile.sensitive) + ".")
    if reading.days >= 3 and reading.measured:
        n = round(reading.rhythm_days)
        lines.append(f"Vous vous parlez à peu près {'tous les jours' if n <= 1 else f'tous les {n} jours'}.")
    if reading.last_in and ep.kind == Kind.INITIATIVE:
        lines.append(f"Son dernier message remonte à {_ago(reading.last_in, frame.now)}.")
    if len(lines) == 1 and level == c.STRANGER:
        return None
    return SectionBody("\n".join(lines), level=int(Sensitivity.NONE))


@SOCIAL.enricher("profile_text", episodes=CONVERSATIONAL, deadline_ms=500)
async def _profile_text(s: SocialState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, str] | None:
    store = ports.get("store")
    ep, aud = frame.episode, frame.audience
    if store is None or ep is None or not ep.target or aud is None or not aud.private_ok:
        return None
    profile = s.profiles.get(frame.get(identity_c.PERSON(ep.target)))
    if profile is None or not profile.summary_ref:
        return None
    return store.content([profile.summary_ref])


# ── Outil : relire sa fiche de la personne en face (même porte que la section) ──

SOCIAL.bundle("social", "relire ce que tu sais de la personne à qui tu parles")


class NoArgs(BaseModel):
    pass


@SOCIAL.tool("social_about", description="Relire ce que tu sais de la personne à qui tu parles (ce qu'elle aime, "
             "ce qui la touche, où vous en êtes).", args=NoArgs, bundle="social", episodes=CONVERSATIONAL)
async def social_about(args: NoArgs, ctx: Any) -> str:
    aud = ctx.frame.audience
    if aud is None or not aud.private_ok:
        return "Tu ne peux pas relire de fiche sur cette personne ici."
    enrich = {"profile_text": await _profile_text(ctx.state, ctx.frame, ctx.ports) or {}}
    return readable(_about(ctx.state, ctx.frame, enrich), aud) or "Tu ne sais encore presque rien de cette personne."
