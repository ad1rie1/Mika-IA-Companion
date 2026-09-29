"""Ce que ``social`` montre à un opérateur : ses liens, un par personne.

Lecture seule. La proximité et le rythme sont ceux que la faculté lit (faits
``CLOSENESS`` et ``CONTACT``) ; un profil dont le texte a été oublié
s'affiche comme oublié.
"""

from __future__ import annotations

from typing import Any

from mika.contracts import identity as identity_c
from mika.contracts import social as c
from mika.faculties.social.faculty import SOCIAL, SocialState
from mika.kernel.frame import Frame
from mika.kernel.inspect import Block, Fields, InspectContext, Note, Ref, Table

#: Au plus tant de personnes listées ; un résumé coupé à tant de caractères.
MAX_PEOPLE = 200
SUMMARY_CHARS = 300

CLOSENESS_FR = {c.STRANGER: "une inconnue", c.ACQUAINTANCE: "une connaissance", c.FRIEND: "une amie",
                c.CLOSE: "une proche"}
FORGOTTEN = "(oublié)"


def _known(s: SocialState) -> set[str]:
    return {*s.contacts.keys(), *s.profiles.keys(), *s.declared.keys(), *s.greeted.keys()}


def _name(frame: Frame, person: str) -> str:
    if person.startswith("name:"):
        return person[5:].title()
    return frame.get(identity_c.IDENTITY(person)).name or person


def _ref(frame: Frame, person: str) -> Ref:
    return Ref("view", "identity/personne", _name(frame, person), (("handle", person),))


def _closeness(s: SocialState, frame: Frame, person: str) -> str:
    level = frame.get(c.CLOSENESS(person))
    text = CLOSENESS_FR.get(level, level)
    return f"{text} (déclarée)" if person in s.declared else f"{text} (vécue)"


def _rhythm(reading: c.ContactReading) -> str:
    n = round(reading.rhythm_days)
    every = "tous les jours" if n <= 1 else f"tous les {n} jours"
    return f"{every} — {'mesuré' if reading.measured else 'repli selon la proximité'}"


def _texts(s: SocialState, people: list[str], ctx: InspectContext) -> dict[str, str] | None:
    refs = [s.profiles[p].summary_ref for p in people if p in s.profiles and s.profiles[p].summary_ref]
    if ctx.store is None:
        return None
    return ctx.store.content(refs) if refs else {}


def _summary(s: SocialState, person: str, texts: dict[str, str] | None, limit: int | None) -> str:
    profile = s.profiles.get(person)
    if profile is None:
        return "pas encore de profil"
    if texts is None:
        return "(magasin indisponible)"
    text = texts.get(profile.summary_ref) if profile.summary_ref else None
    if text is None:
        return FORGOTTEN
    return text if limit is None or len(text) <= limit else text[:limit].rstrip() + "…"


def _ratio(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def _when(ctx: InspectContext, at: int, never: str = "jamais") -> str:
    return ctx.when(at) if at else never


def _detail(s: SocialState, frame: Frame, ctx: InspectContext, person: str) -> list[Block]:
    reading = frame.get(c.CONTACT(person))
    profile = s.profiles.get(person)
    texts = _texts(s, [person], ctx)
    blocks: list[Block] = [Fields((
        ("personne", _ref(frame, person)),
        ("proximité", _closeness(s, frame, person)),
        ("jours de contact", reading.days), ("messages reçus", reading.inbound),
        ("premier message reçu", _when(ctx, reading.first_in)),
        ("dernier message reçu", _when(ctx, reading.last_in)),
        ("dernier message envoyé", _when(ctx, reading.last_out)),
        ("rythme", _rhythm(reading)),
        ("silence ÷ rythme", _ratio(reading.silence_ratio)),
        ("ses initiatives sans réponse", reading.unanswered),
        ("dernière salutation", _when(ctx, s.greeted.get(person, 0))),
        ("éléments de mémoire la concernant", s.mentions.get(person, 0)),
    ), title="Le lien")]
    if profile is None:
        blocks.append(Note("Pas encore de profil : elle n'en sait pas assez pour s'en faire une idée.", tone="mut"))
    else:
        blocks.append(Fields((
            ("relu le", _when(ctx, profile.revised_at)),
            ("comment lui parler", profile.tone or "—"),
            ("ce qui l'intéresse", ", ".join(profile.interests) or "—"),
            ("sujets délicats", ", ".join(profile.sensitive) or "—"),
            ("mémoire relue jusqu'à l'élément", profile.upto),
        ), title="Ce qu'elle en pense"))
        blocks.append(Note(f"Ce qu'elle en sait : {_summary(s, person, texts, None)}"))
    return blocks


@SOCIAL.inspect("liens", title="Liens", params=[("person", "personne")])
def _links(s: SocialState, frame: Frame, ctx: InspectContext) -> list[Block]:
    person = ctx.param("person")
    if person:
        if person not in _known(s):
            return [Note(f"Aucun lien avec « {person} » pour l'instant.", tone="mut")]
        return _detail(s, frame, ctx, person)
    people = sorted(_known(s), key=lambda p: (-(s.contacts[p].last_in if p in s.contacts else 0), p))
    shown = people[:MAX_PEOPLE]
    texts = _texts(s, shown, ctx)
    rows: list[tuple[Any, ...]] = []
    for p in shown:
        reading = frame.get(c.CONTACT(p))
        rows.append((_ref(frame, p), _closeness(s, frame, p), _rhythm(reading), _when(ctx, reading.last_in),
                     _ratio(reading.silence_ratio), reading.unanswered,
                     _summary(s, p, texts, SUMMARY_CHARS),
                     Ref("view", "social/liens", "détail", (("person", p),))))
    missed = frame.get(c.MISSED)
    blocks: list[Block] = [
        Fields((("personnes", len(people)),
                ("qui lui manquent", ", ".join(f"{_name(frame, p)} (×{_ratio(r)})" for p, r in missed) or "personne"),
                ("dernier réconfort cherché", _when(ctx, s.comforted_at)))),
        Table(("personne", "proximité", "rythme", "dernier message reçu", "silence ÷ rythme",
               "initiatives sans réponse", "ce qu'elle en sait", ""), tuple(rows),
              empty="aucun lien pour l'instant"),
    ]
    if len(people) > MAX_PEOPLE:
        blocks.append(Note(f"Seules les {MAX_PEOPLE} personnes les plus récemment entendues sont listées "
                           f"(sur {len(people)}).", tone="mut"))
    return blocks
