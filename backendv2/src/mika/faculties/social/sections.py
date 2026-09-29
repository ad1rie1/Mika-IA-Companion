"""Ce que ``social`` met dans le prompt.

- **Ce que tu sais de cette personne** : son profil et votre rythme — sa
  fiche, donc seulement quand elle est ouverte (jamais en public, jamais
  sous la barre de certitude).
- **Ce que tu perçois de son état** : une lecture du ton de son message
  (majuscules, ponctuation, mots, longueur) — un indice, pas un verdict.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from mika.contracts import identity as identity_c
from mika.contracts import social as c
from mika.contracts import transcript as transcript_c
from mika.faculties.social.faculty import SOCIAL, SocialState
from mika.faculties.social.profile import describe_level
from mika.kernel.clock import DAY
from mika.kernel.faculty import Zone
from mika.kernel.frame import Frame
from mika.kernel.prompt import SectionBody
from mika.vocab.episodes import CONVERSATIONAL, Kind
from mika.vocab.privacy import Sensitivity
from mika.vocab.words import fold

_HEAVY = ("triste", "marre", "fatigue", "epuise", "deprime", "pleure", "seul", "seule", "angoisse", "peur", "mal",
          "nul", "horrible", "deteste", "galere", "ras le bol", "craque", "vide")
_BRIGHT = ("trop bien", "genial", "content", "contente", "hate", "youpi", "super", "trop cool", "heureux",
           "heureuse", "incroyable", "adore", "mdr", "haha", "lol")
_WARM_EMOJI = frozenset("😀😃😄😁😆😊🙂😍🥰😘❤💕💖✨🎉👍😂🤣")
_SAD_EMOJI = frozenset("😢😭😞😔😟🙁☹💔😩😫")
_ANGRY_EMOJI = frozenset("😠😡🤬👿")


def read_tone(text: str) -> list[str]:
    """Des indices lus dans la forme d'un message. Vide le plus souvent."""
    cues: list[str] = []
    stripped = text.strip()
    if not stripped:
        return cues
    letters = [ch for ch in stripped if ch.isalpha()]
    if len(letters) >= 8 and sum(ch.isupper() for ch in letters) / len(letters) > 0.7:
        cues.append("écrit en majuscules : il ou elle s'emballe, ou crie")
    if "!!" in stripped:
        cues.append("beaucoup de points d'exclamation : de l'enthousiasme, ou de l'agacement")
    if stripped.count("...") + stripped.count("…") >= 2:
        cues.append("des points de suspension : une hésitation, ou quelque chose de lourd")
    words = stripped.split()
    if len(words) <= 2 and not stripped.endswith("?"):
        cues.append("un message très court")
    low = fold(stripped)
    if any(re.search(rf"\b{re.escape(w)}\b", low) for w in _HEAVY):
        cues.append("des mots lourds")
    elif any(re.search(rf"\b{re.escape(w)}\b", low) for w in _BRIGHT):
        cues.append("de l'entrain")
    chars = set(stripped)
    if chars & _SAD_EMOJI:
        cues.append("un émoji triste")
    elif chars & _ANGRY_EMOJI:
        cues.append("un émoji fâché")
    elif chars & _WARM_EMOJI:
        cues.append("un émoji joyeux")
    return cues


@SOCIAL.enricher("tone", episodes=[Kind.REPLY], deadline_ms=500)
async def _tone(s: SocialState, frame: Frame, ports: Mapping[str, Any]) -> tuple[str, ...] | None:
    store = ports.get("store")
    ep = frame.episode
    reply_to = ep.attrs.get("reply_to") if ep is not None else None
    if store is None or reply_to is None:
        return None
    rows = store.query_mind(f"SELECT text FROM {transcript_c.THREAD_TABLE} WHERE id=?", (reply_to,))
    return tuple(read_tone(str(rows[0][0]))) if rows else None


@SOCIAL.section("their_state", zone=Zone.VOLATILE, episodes=[Kind.REPLY], after=["who"], trim_rank=40,
                title="CE QUE TU PERÇOIS DE SON ÉTAT")
def _their_state(s: SocialState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    cues = enrich.get("tone")
    if not cues:
        return None
    return SectionBody("Dans son message : " + " ; ".join(cues) + ". C'est un indice, pas une certitude.")


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
