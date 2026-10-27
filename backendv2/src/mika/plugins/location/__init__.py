"""Le plugin ``location`` : où est la personne qui lui écrit, quand son téléphone le lui dit (ADR 0119).

- **Ce que le téléphone donne** : la personne l'a permis (un réglage coupé par défaut) et l'application est
  ouverte — jamais en fond. Ses coordonnées, le nom du lieu que le téléphone a trouvé, la précision, l'heure de la
  mesure (``location.located``, par le port) ; couper le réglage efface la dernière (``location.cleared``).
- **Ce n'est pas un signal** : elle ne le remarque pas, rien n'en naît (ni pensée, ni initiative), aucune section ne
  le lui montre. Elle le **regarde** (``location_where``) quand la conversation s'y prête, en tête-à-tête avec cette
  personne, et seulement la position de cette personne — jamais celle d'une autre, jamais en salon.
- **Un regard se voit** : l'outil rend la référence de la position regardée (``ToolResult.attach``), que son message
  emporte ; l'écran en fait une petite bulle (« elle a regardé où tu es »).
- **L'oubli** : coordonnées et lieu sont des contenus (l'adresse et la personne pour sujets) ; oublier la personne
  les efface, et sa position disparaît de la tranche.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from pydantic import BaseModel

from mika.contracts import identity as identity_c
from mika.contracts import location as c
from mika.kernel.builtin import SUBJECT_FORGOTTEN
from mika.kernel.clock import MINUTE
from mika.kernel.faculty import Faculty, ToolResult
from mika.kernel.frame import Frame
from mika.kernel.state import FrozenDict
from mika.ports.preprocess import inert
from mika.vocab.episodes import Kind, is_work_target
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import ChannelTrust

BUNDLE = "location"
#: le nom du lieu, au plus, tel qu'elle le lit
LABEL_MAX = 200


@dataclass(frozen=True, slots=True)
class Fix:
    """La dernière position d'une adresse : ses contenus par référence (une tranche ne voit jamais de texte)."""

    seq: int
    handle: str
    person: str
    coords_ref: str
    label_ref: str
    accuracy_m: int
    fixed_at: int


@dataclass(frozen=True, slots=True)
class LocationState:
    #: la dernière position, par adresse
    fixes: FrozenDict[str, Fix] = field(default_factory=FrozenDict)


LOCATION = Faculty("location", state=LocationState, init=lambda p: LocationState())
LOCATION.bundle(BUNDLE, phrase("location.bundle"))
LOCATION.declare(*c.ALL)


@LOCATION.reducer(c.LOCATED)
def _located(s: LocationState, e, cx) -> LocationState:
    d = e.data
    label_ref = (d.label.ref or "") if d.label is not None else ""
    fix = Fix(e.seq, d.handle, d.person, d.coords.ref or "", label_ref, max(0, int(d.accuracy_m)), int(d.fixed_at))
    return replace(s, fixes=s.fixes.set(d.handle, fix))


@LOCATION.reducer(c.CLEARED)
def _cleared(s: LocationState, e, cx) -> LocationState:
    return replace(s, fixes=s.fixes.delete(e.data.handle)) if e.data.handle in s.fixes else s


@LOCATION.reducer(SUBJECT_FORGOTTEN)
def _forgotten(s: LocationState, e, cx) -> LocationState:
    """Oublier une personne (ou une de ses adresses) efface sa position : ses contenus, déjà, par leurs sujets."""
    who = e.data.subject
    gone = [h for h, f in s.fixes.items() if who in (f.handle, f.person)]
    fixes = s.fixes
    for h in gone:
        fixes = fixes.delete(h)
    return replace(s, fixes=fixes) if gone else s


def known(s: LocationState | None, handle: str) -> bool:
    """Le téléphone de cette adresse lui a dit où elle était, et rien ne l'a effacé depuis."""
    return s is not None and handle in s.fixes


def last_for(s: LocationState | None, frame: Frame, target: str) -> Fix | None:
    """La dernière position de la personne qui écrit par ``target`` : celle de cette adresse, ou d'une autre adresse
    de la même personne (un téléphone et un navigateur liés) — jamais celle de quelqu'un d'autre."""
    if s is None or not s.fixes:
        return None
    person = frame.get(identity_c.PERSON(target)) or target
    mine = [f for f in s.fixes.values()
            if f.handle == target or (frame.get(identity_c.PERSON(f.handle)) or f.handle) == person]
    return max(mine, key=lambda f: (f.fixed_at, f.seq)) if mine else None


def offered(audience: Any) -> bool:
    """Seulement en tête-à-tête, avec quelqu'un qui a un compte : jamais dans un salon, jamais à un inconnu."""
    return bool(getattr(audience, "persons", ())) and not audience.public and not getattr(audience, "room", None) \
        and audience.trust == ChannelTrust.AUTHENTICATED.value


def _ago(us: int) -> str:
    minutes = max(1, us // MINUTE)
    if minutes < 120:
        return phrase("projects.duration.minutes", n=minutes)
    hours = minutes // 60
    return phrase("projects.duration.hours", n=hours) if hours < 48 else phrase("projects.duration.days", n=hours // 24)


def _coords(text: str) -> str:
    lat, _, lon = text.partition(",")
    return f"{lat.strip()}, {lon.strip()}" if lon else text


class WhereArgs(BaseModel):
    pass


@LOCATION.tool("location_where", description=phrase("location.tools.where.description"), args=WhereArgs,
               bundle=BUNDLE, episodes=[Kind.REPLY], max_calls_per_episode=2, owner_only=True, when=offered)
async def location_where(args: WhereArgs, ctx: Any) -> Any:
    frame: Frame = ctx.frame
    ep, aud = frame.episode, frame.audience
    target = ep.target if ep is not None else None
    if not target or is_work_target(target) or aud is None or not offered(aud) or target not in aud.persons:
        return ToolResult(ok=False, content=phrase("location.tools.where.not_here"))
    fix = last_for(ctx.state, frame, target)
    store = ctx.ports.get("store")
    texts = store.content([r for r in (fix.coords_ref, fix.label_ref) if r]) if fix is not None and store else {}
    coords = texts.get(fix.coords_ref) if fix is not None else None
    if fix is None or not coords:  # jamais dite, effacée, ou oubliée
        return ToolResult(content=phrase("location.tools.where.unknown"))
    label = inert(texts.get(fix.label_ref) or "", LABEL_MAX)
    accuracy = phrase("location.tools.where.accuracy", n=fix.accuracy_m) if fix.accuracy_m \
        else phrase("location.tools.where.accuracy_unknown")
    place = label or phrase("location.tools.where.unnamed")
    return ToolResult(content=phrase("location.tools.where.result", place=place, coords=_coords(coords),
                                     accuracy=accuracy, ago=_ago(frame.now - fix.fixed_at)),
                      attach=(c.note_ref(fix.seq),))


from mika.plugins.location import inspect as inspect  # noqa: E402 — s'enregistre sur LOCATION

__all__ = ["LOCATION", "Fix", "LocationState", "known", "last_for"]
