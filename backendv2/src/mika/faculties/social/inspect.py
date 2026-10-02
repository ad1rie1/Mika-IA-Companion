"""Ce que ``social`` montre à un opérateur : ses liens, un par personne, et
l'onglet « Lien » de la fiche d'une personne.

Lecture seule. La proximité et le rythme sont ceux que la faculté lit (faits
``CLOSENESS`` et ``CONTACT``) ; un profil dont le texte a été oublié
s'affiche comme oublié. La seule écriture — fixer la proximité — est une
action d'opérateur (``actions.py``), posée en place sur l'onglet.
"""

from __future__ import annotations

from mika.contracts import identity as identity_c
from mika.contracts import social as c
from mika.faculties.social.faculty import SOCIAL, SocialParams, SocialState, params
from mika.faculties.social.profile import lines_of
from mika.faculties.social.sections import refs_of
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    ActionSlot,
    Badge,
    Block,
    Cell,
    Column,
    Fields,
    InspectContext,
    Meter,
    Note,
    Param,
    Prose,
    Ref,
    Row,
    Stat,
    Stats,
    Table,
    Text,
    When,
    paginate,
)
from mika.vocab.people import fold, is_identifiable

#: Au plus tant de personnes par page ; un résumé replié au-delà de tant de caractères.
PAGE = 50
SUMMARY_CHARS = 300
#: La proximité « automatique » (vécue) dans les formulaires : aucune déclaration.
AUTO = "auto"

#: Sans genre imposé : la console parle aussi d'Adrien.
CLOSENESS_FR = {c.STRANGER: "pas encore de lien", c.ACQUAINTANCE: "connaissance", c.FRIEND: "amitié",
                c.CLOSE: "proche"}
CLOSENESS_TONE = {c.STRANGER: "muted", c.ACQUAINTANCE: "", c.FRIEND: "info", c.CLOSE: "ok"}
FORGOTTEN = "(oublié)"


def _known(s: SocialState) -> set[str]:
    return {*s.contacts.keys(), *s.profiles.keys(), *s.declared.keys(), *s.greeted.keys()}


def _name(frame: Frame, person: str) -> str:
    if person.startswith("name:"):
        return person[5:].title()
    return frame.get(identity_c.IDENTITY(person)).name or person


def _ref(frame: Frame, person: str, tab: str = "") -> Ref:
    return Ref.subject("person", person, _name(frame, person), tab)


def _closeness_text(s: SocialState, frame: Frame, person: str) -> str:
    level = frame.get(c.CLOSENESS(person))
    text = CLOSENESS_FR.get(level, level)
    if person in s.declared:
        return f"{text} (déclarée)"
    return f"{text} (vécue, plancher « propriétaire »)" if frame.get(identity_c.IS_OWNER(person)) else f"{text} (vécue)"


def _closeness(s: SocialState, frame: Frame, person: str) -> Badge:
    return Badge(_closeness_text(s, frame, person), CLOSENESS_TONE.get(frame.get(c.CLOSENESS(person)), ""))


def _rhythm(reading: c.ContactReading) -> str:
    n = round(reading.rhythm_days)
    every = "tous les jours" if n <= 1 else f"tous les {n} jours"
    return f"{every} — {'mesuré' if reading.measured else 'repli selon la proximité'}"


def _ratio(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def _silence(reading: c.ContactReading, p: SocialParams) -> Cell:
    """Le silence rapporté à son rythme : la jauge est à moitié pleine au seuil
    où elle lui manque (une fois et demie son rythme, par défaut)."""
    if not reading.last_in:
        return Text("jamais écrit", "muted")
    full = 2 * p.recontact_factor
    missed = reading.silence_ratio >= p.recontact_factor
    return Meter(min(1.0, reading.silence_ratio / full) if full > 0 else 0.0, f"×{_ratio(reading.silence_ratio)}",
                 "warn" if missed else "")


def _texts(s: SocialState, people: list[str], ctx: InspectContext) -> dict[str, str] | None:
    refs = [r for p in people if p in s.profiles for r in refs_of(s.profiles[p])]
    if ctx.store is None:
        return None
    return ctx.store.content(refs) if refs else {}


def _part(ref: str, legacy: str, texts: dict[str, str] | None) -> str:
    """Un texte du profil : gardé à part (« (oublié) » s'il a été oublié), ou en clair (profil ancien)."""
    if not ref:
        return legacy or "—"
    if texts is None:
        return "(magasin indisponible)"
    return texts.get(ref) or FORGOTTEN


def _listed(ref: str, legacy: tuple[str, ...], texts: dict[str, str] | None) -> str:
    if not ref:
        return ", ".join(legacy) or "—"
    if texts is None:
        return "(magasin indisponible)"
    got = texts.get(ref)
    return ", ".join(lines_of(got)) if got is not None else FORGOTTEN


def _summary(s: SocialState, person: str, texts: dict[str, str] | None) -> str:
    profile = s.profiles.get(person)
    if profile is None:
        return "pas encore de profil"
    if texts is None:
        return "(magasin indisponible)"
    text = texts.get(profile.summary_ref) if profile.summary_ref else None
    return FORGOTTEN if text is None else text


def _when(at: int, never: str = "jamais") -> Cell:
    return When(at) if at else Text(never, "muted")


def settable(frame: Frame, person: str) -> bool:
    """Peut-on déclarer la proximité de cette clé ? Une personne durable, par sa
    clé canonique, qui a au moins une adresse."""
    if not is_identifiable(person) or person.startswith("name:"):
        return False
    return frame.get(identity_c.PERSON(person)) == person and bool(frame.get(identity_c.HANDLES(person)))


def _detail(s: SocialState, frame: Frame, ctx: InspectContext, person: str, *, on_fiche: bool = False) -> list[Block]:
    p = params(frame.env.params_of("social", frame.root))
    reading = frame.get(c.CONTACT(person))
    profile = s.profiles.get(person)
    texts = _texts(s, [person], ctx)
    missed = dict(frame.get(c.MISSED))
    blocks: list[Block] = [
        Stats((Stat("proximité", _closeness(s, frame, person),
                    "déclarée par un opérateur" if person in s.declared else "née de leur histoire"),
               Stat("rythme", _rhythm(reading)),
               Stat("silence ÷ rythme", _silence(reading, p), f"lui manque au-delà de ×{_ratio(p.recontact_factor)}",
                    tone="warn" if person in missed else ""),
               Stat("dernier message reçu", _when(reading.last_in)),
               Stat("ses initiatives sans réponse", reading.unanswered))),
        Fields((
            *((() if on_fiche else (("personne", _ref(frame, person)),))),  # sur sa fiche : pas de lien vers elle-même
            ("jours de contact", reading.days), ("messages reçus", reading.inbound),
            ("qui ouvre leurs conversations",
             f"elle {reading.her_starts} fois, la personne {reading.their_starts} fois"
             + (" — c'est presque toujours elle" if reading.one_sided else "")),
            ("premier message reçu", _when(reading.first_in)),
            ("dernier message envoyé", _when(reading.last_out)),
            ("dernière salutation", _when(s.greeted.get(person, 0))),
            ("éléments de mémoire la concernant", s.mentions.get(person, 0)),
            ("dernier réconfort cherché (auprès de quiconque)", _when(s.comforted_at)),
        ), title="Le lien", columns=2),
    ]
    if person in missed:
        blocks.append(Note(f"Elle lui manque : un silence de ×{_ratio(missed[person])} son rythme habituel.",
                           tone="warn"))
    if profile is None:
        blocks.append(Note("Pas encore de profil : elle n'en sait pas assez pour s'en faire une idée.", tone="muted"))
    else:
        blocks.append(Fields((
            ("relu le", _when(profile.revised_at)),
            ("comment lui parler", _part(profile.tone_ref, profile.tone, texts)),
            ("ce qui l'intéresse", _listed(profile.interests_ref, profile.interests, texts)),
            ("sujets délicats", _listed(profile.sensitive_ref, profile.sensitive, texts)),
            ("mémoire relue jusqu'à l'élément", profile.upto),
        ), title="Ce qu'elle en pense", columns=2))
        blocks.append(Prose(_summary(s, person, texts), title="Ce qu'elle en sait", clamp=1200))
    return blocks


@SOCIAL.inspect("lien", title="Lien", subject="person", order=30,
                description="Leur proximité, le rythme de leurs échanges, ce qu'elle en pense.")
def _link(s: SocialState, frame: Frame, ctx: InspectContext) -> list[Block]:
    person = ctx.subject
    if not person:
        return [Note("Ouvre la fiche d'une personne : Personnes, puis la personne.", tone="muted")]
    if not is_identifiable(person):
        return [Note("Une connexion de passage : aucun lien durable ne s'y attache.", tone="muted")]
    blocks: list[Block] = (_detail(s, frame, ctx, person, on_fiche=True) if person in _known(s) else
                           [Note("Aucun lien pour l'instant : cette personne ne lui a jamais écrit, et rien n'a été "
                                 "déclaré.", tone="muted")])
    if settable(frame, person):
        blocks.append(ActionSlot("social.proximite", initial=(("closeness", s.declared.get(person) or AUTO),),
                                 title="Fixer la proximité"))
    return blocks


SEARCH = Param("q", "nom", placeholder="Alice…")
LEVEL = Param("proximite", "proximité", kind="select", choices=tuple(CLOSENESS_FR.items()))
LEGACY = Param("person", "personne", kind="hidden")


@SOCIAL.inspect("liens", title="Liens", section="personnes", order=20, params=[SEARCH, LEVEL, LEGACY],
                description="Chaque lien : sa proximité, son rythme, le silence ; une ligne mène à la fiche.")
def _links(s: SocialState, frame: Frame, ctx: InspectContext) -> list[Block]:
    person = str(ctx.value("person") or "")
    if person:  # l'ancien lien vers le détail d'une personne
        if person not in _known(s):
            return [Note(f"Aucun lien avec « {person} » pour l'instant.", tone="muted")]
        return [Fields((("fiche", _ref(frame, person, "lien")),), title="Ce lien vit désormais sur la fiche"),
                *_detail(s, frame, ctx, person)]
    p = params(frame.env.params_of("social", frame.root))
    q, level = fold(str(ctx.value("q") or "")), str(ctx.value("proximite") or "")
    people = sorted(_known(s), key=lambda k: (-(s.contacts[k].last_in if k in s.contacts else 0), k))
    shown = [k for k in people if (not q or q in fold(_name(frame, k)) or q in fold(k))
             and (not level or frame.get(c.CLOSENESS(k)) == level)]
    page, pager = paginate(shown, ctx.pager(size=PAGE))
    texts = _texts(s, list(page), ctx)
    rows: list[Row] = []
    for k in page:
        reading = frame.get(c.CONTACT(k))
        rows.append(Row((_ref(frame, k), _closeness(s, frame, k), _rhythm(reading), _silence(reading, p),
                         _when(reading.last_in), reading.unanswered,
                         Text(_summary(s, k, texts), clamp=SUMMARY_CHARS)), href=_ref(frame, k, "lien")))
    missed = frame.get(c.MISSED)
    return [
        Stats((Stat("personnes", len(people)),
               Stat("qui lui manquent", len(missed),
                    (", ".join(f"{_name(frame, k)} (×{_ratio(r)})" for k, r in missed[:5])
                     + (f" et {len(missed) - 5} autre(s)" if len(missed) > 5 else "")) or "personne",
                    tone="warn" if missed else ""),
               Stat("dernier réconfort cherché", _when(s.comforted_at)))),
        Table(("personne", "proximité", Column("rythme", detail=True), Column("silence ÷ rythme", hint="la moitié de la jauge : elle "
                                                         "lui manque"), "dernier message reçu",
               Column("initiatives sans réponse", "num", detail=True), "ce qu'elle en sait"), tuple(rows), pager=pager,
              title="Liens", filters=("q", "proximite"),
              empty="aucun lien ne correspond" if q or level else "aucun lien pour l'instant"),
    ]
