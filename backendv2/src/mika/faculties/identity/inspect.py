"""Ce qu'``identity`` montre à un opérateur : chaque poignée, ce qu'elle
prouve, et pourquoi elle ouvre ce qu'elle ouvre.

Lecture seule. Le verdict est celui que la faculté applique (les faits
``IDENTITY`` et ``DISCLOSURE``) ; l'explication le déroule pas à pas avec les
mêmes barres (``vocab.privacy``), sans jamais le recalculer autrement.
"""

from __future__ import annotations

from typing import Any

from mika.contracts import affect as affect_c
from mika.contracts import identity as c
from mika.contracts import social as social_c
from mika.faculties.identity.faculty import (
    IDENTITY,
    Handle,
    IdentityState,
    _params,
    handles_of,
    known_as,
    view_of,
)
from mika.kernel.events import Event
from mika.kernel.frame import Frame
from mika.kernel.inspect import Block, Fields, InspectContext, Note, Ref, Table
from mika.vocab import privacy
from mika.vocab.people import is_identifiable
from mika.vocab.privacy import ChannelTrust, Disclosure, Sensitivity

#: Au plus tant de poignées listées, et tant de lignes au registre des preuves.
MAX_HANDLES = 200
MAX_LEDGER = 50

TRUST_FR = {
    ChannelTrust.AUTHENTICATED: "authentifiée (session vérifiée)",
    ChannelTrust.ACCOUNT: "compte (le même compte revient)",
    ChannelTrust.PUBLIC: "publique (rien ne prouve qui écrit)",
    ChannelTrust.INTERNAL: "interne (pas une personne)",
}
CERTAINTY_FR = {"unknown": "inconnue", "suspected": "soupçonnée", "claimed": "affirmée",
                "corroborated": "recoupée", "bound": "liée", "verified": "vérifiée"}
LEVEL_FR = {Sensitivity.NONE: "rien sur autrui", Sensitivity.ANODYNE: "anodin", Sensitivity.PERSONAL: "personnel",
            Sensitivity.CONFIDENCE: "confidences"}
CLOSENESS_FR = {social_c.STRANGER: "une inconnue", social_c.ACQUAINTANCE: "une connaissance",
                social_c.FRIEND: "une amie", social_c.CLOSE: "une proche"}
EVIDENCE_FR = {"self_declared": "affirmation", c.SHARED_MEMORY: "souvenir partagé recoupé", c.DENIED: "démenti",
               c.CONTRADICTED: "contredit", c.REVOKED: "liaison oubliée", "vouched": "quelqu'un s'en porte garant",
               "passive_inference": "indice passif"}
VIA_FR = {"corroborated": "recoupement", "operator": "opérateur"}
BY_FR = {"kernel": "le noyau", "tool": "elle (outil)", "operator": "un opérateur"}


def number(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def certainty_fr(value: float) -> str:
    return f"{number(value)} ({CERTAINTY_FR.get(privacy.certainty_name(value), '?')})"


def disclosure_fr(d: Disclosure) -> str:
    return f"{LEVEL_FR.get(d.level, '?')} · sa fiche {'ouverte' if d.own_file else 'fermée'}"


def person_ref(handle: str, text: str | None = None) -> Ref:
    return Ref("view", "identity/personne", text or handle, (("handle", handle),))


def _stance(frame: Frame, handle: str, person: str) -> tuple[str, float]:
    """Proximité et chaleur, lues comme le fait ``DISCLOSURE`` (rien pour une
    poignée jetable)."""
    if not is_identifiable(handle):
        return "", 0.0
    return frame.get(social_c.CLOSENESS(person)), frame.get(affect_c.WARMTH(person))


def _disclosures(frame: Frame, handle: str, h: Handle) -> tuple[Disclosure, Disclosure]:
    return (frame.get(c.DISCLOSURE((handle, h.channel, False))),
            frame.get(c.DISCLOSURE((handle, h.channel, True))))


# ── Personnes ─────────────────────────────────────────────────────────────


@IDENTITY.inspect("personnes", title="Personnes")
def _people(s: IdentityState, frame: Frame, ctx: InspectContext) -> list[Block]:
    ordered = sorted(s.handles.items(), key=lambda kv: (-kv[1].first_seen, kv[0]))
    rows = []
    for handle, h in ordered[:MAX_HANDLES]:
        view = view_of(s, handle, frame.now)
        private, public = _disclosures(frame, handle, h)
        bound = person_ref(view.person, known_as(s, view.person)) if view.bound else "elle-même"
        rows.append((person_ref(handle), view.name or "—", h.channel or "—", TRUST_FR.get(h.trust, str(h.trust)),
                     certainty_fr(view.certainty), bound, "oui" if frame.get(c.IS_OWNER(view.person)) else "non",
                     f"« {view.claim} »" if view.claim else "—", disclosure_fr(private), disclosure_fr(public)))
    blocks: list[Block] = [
        Fields((("poignées connues", len(s.handles)),
                ("liées à une autre personne", sum(1 for h in s.handles.values() if h.person)),
                ("revendications en attente", sum(1 for h in s.handles.values() if h.claim is not None)),
                ("propriétaires", ", ".join(known_as(s, p) for p in frame.get(c.OWNERS)) or "aucun"),
                ("barre de divulgation", number(privacy.POLICY.private_threshold)))),
        Table(("poignée", "nom", "canal", "confiance du canal", "certitude", "parle pour", "propriétaire",
               "revendique", "divulgation en privé", "divulgation en public"), tuple(rows),
              empty="aucune poignée vue pour l'instant"),
    ]
    if len(ordered) > MAX_HANDLES:
        blocks.append(Note(f"Seules les {MAX_HANDLES} poignées les plus récentes sont listées "
                           f"(sur {len(ordered)}).", tone="mut"))
    return blocks


# ── Une personne ──────────────────────────────────────────────────────────


def _stored(h: Handle) -> tuple[float, str]:
    """Le point de départ du verdict, tel que la faculté le lit."""
    if h.authenticated:
        return privacy.VERIFIED, "session authentifiée : le compte est prouvé"
    if h.person:
        return h.certainty, f"liée par {VIA_FR.get(h.via, h.via or '?')}"
    if h.trust is ChannelTrust.ACCOUNT:
        return privacy.CEILINGS[h.trust], "elle parle pour elle-même, et un compte stable prouve sa continuité"
    return 0.0, "elle parle pour elle-même, mais rien ne prouve la continuité de qui écrit"


def _steps(h: Handle, effective: float) -> list[tuple[str, str, str]]:
    stored, why = _stored(h)
    floor, ceiling = privacy.FLOORS[h.trust], privacy.CEILINGS[h.trust]
    raised = max(stored, floor)
    capped = min(raised, ceiling)
    steps = [("certitude enregistrée", certainty_fr(stored), why),
             ("plancher du canal", number(floor),
              f"relevée de {number(stored)} à {number(raised)}" if raised > stored else "déjà au-dessus : inchangée"),
             ("plafond du canal", number(ceiling),
              f"le plafond mord : {number(raised)} ramenée à {number(capped)}" if capped < raised
              else "sous le plafond : inchangée"),
             ("certitude effective", certainty_fr(effective), "celle qui vaut sur ce canal")]
    if abs(capped - effective) > 1e-9:
        steps.append(("écart", number(capped), "le calcul pas à pas ne retombe pas sur la lecture de la faculté"))
    bar = privacy.POLICY.private_threshold
    steps.append(("barre de divulgation", number(bar),
                  "atteinte" if effective >= bar else "pas atteinte : rien de personnel sur autrui"))
    return steps


def why_level(certainty: float, trust: ChannelTrust, *, closeness: str, warmth: float, public: bool) -> str:
    """Pourquoi ce niveau — dans l'ordre des règles de ``privacy.disclosable``."""
    pol = privacy.POLICY
    if trust is ChannelTrust.INTERNAL:
        return "pas une personne : toute sa mémoire"
    if trust is ChannelTrust.PUBLIC:
        return "canal public : rien ne prouve qui écrit, donc jamais plus qu'anodin, à aucune certitude"
    if public:
        return "audience publique : d'autres lisent, donc jamais plus qu'anodin, à aucune certitude"
    if certainty < pol.private_threshold:
        return (f"certitude {number(certainty)} sous la barre ({number(pol.private_threshold)}) : "
                "anodin seulement")
    rank = privacy.closeness_rank(closeness)
    link = f"pour elle, {CLOSENESS_FR.get(closeness, closeness or 'une inconnue')} ; chaleur {number(warmth)}"
    if not (rank >= privacy.CLOSENESS_RANK[social_c.FRIEND] or warmth >= pol.warmth_min):
        return (f"aucun lien assez fort ({link}) : anodin — être amie, proche, ou une chaleur d'au moins "
                f"{number(pol.warmth_min)} ouvrirait le personnel")
    if certainty >= pol.confidence_threshold and rank >= privacy.CLOSENESS_RANK[social_c.CLOSE]:
        return f"proche et reconnue à au moins {number(pol.confidence_threshold)} ({link}) : jusqu'aux confidences"
    return (f"un lien ({link}) ouvre le personnel ; les confidences demandent une proche reconnue à au moins "
            f"{number(pol.confidence_threshold)}")


def why_file(certainty: float, trust: ChannelTrust, *, public: bool) -> str:
    if public or trust in (ChannelTrust.PUBLIC, ChannelTrust.INTERNAL):
        return "fermée : jamais en public, à aucune certitude"
    if trust is ChannelTrust.AUTHENTICATED:
        return "ouverte : la session prouve qui écrit"
    if certainty >= privacy.POLICY.private_threshold:
        return "ouverte : la certitude atteint la barre"
    return "fermée : la certitude n'atteint pas la barre"


def _verdict(frame: Frame, handle: str, h: Handle, view: c.IdentityView) -> list[Block]:
    closeness, warmth = _stance(frame, handle, view.person)
    private, public = _disclosures(frame, handle, h)
    rows = []
    for label, d, flag in (("en privé", private, False), ("en public", public, True)):
        # comme le fait : un canal public rend toute audience publique
        audience_public = flag or h.trust is ChannelTrust.PUBLIC
        rows.append((label, LEVEL_FR.get(d.level, "?"),
                     why_level(view.certainty, h.trust, closeness=closeness, warmth=warmth, public=audience_public),
                     LEVEL_FR.get(d.witness_level, "?"),
                     why_file(view.certainty, h.trust, public=audience_public)))
    return [
        Table(("étape", "valeur", "pourquoi"), tuple(_steps(h, view.certainty)), title="Le verdict, pas à pas"),
        Table(("audience", "sur autrui", "pourquoi", "si elle ou il est concerné", "sa propre fiche"), tuple(rows),
              title="Ce que ça ouvre"),
    ]


def _used(mark: str) -> str:
    if mark.startswith("item:"):
        return f"élément de mémoire n°{mark[5:]}"
    return EVIDENCE_FR.get(mark, mark)


def _claim(s: IdentityState, h: Handle, view: c.IdentityView, ctx: InspectContext) -> Block:
    claim = h.claim
    if claim is None:
        return Note("Aucune revendication en attente.", tone="mut")
    target: Any = person_ref(claim.target, known_as(s, claim.target)) if claim.target else \
        "plusieurs personnes portent ce nom"
    return Fields((("nom revendiqué", f"« {claim.name} »"), ("personne visée", target),
                   ("certitude de la revendication", certainty_fr(privacy.effective(claim.certainty, h.trust))),
                   ("preuves déjà comptées", ", ".join(_used(u) for u in claim.used) or "—"),
                   ("depuis", ctx.when(claim.at)),
                   ("état", "active" if view.claim else "éteinte (jamais confirmée à temps)")),
                  title="Revendication en cours")


def _describe_event(e: Event[Any], s: IdentityState) -> tuple[str, str]:
    data = e.data
    if e.type.name == c.CLAIMED.name:
        target = data.target
        if target is None:
            aim = "plusieurs personnes portent ce nom"
        elif target == data.handle:
            aim = "personne d'autre ne le porte : elle ou il se présente"
        else:
            aim = f"vise {known_as(s, str(target))}"
        where = " (en public)" if data.public else ""
        return "revendication", f"« {data.name} » — {aim}{where}"
    if e.type.name == c.EVIDENCE.name:
        kind = str(data.kind)
        weight = privacy.EVIDENCE.get(kind, privacy.COUNTER_EVIDENCE.get(kind, 0.0))
        detail = f"{EVIDENCE_FR.get(kind, kind)} ({'+' if weight >= 0 else ''}{number(weight)})"
        if data.name:
            detail += f" — nom « {data.name} »"
        if data.item is not None:
            detail += f" — élément de mémoire n°{data.item}"
        if data.note:
            detail += f" — {data.note}"
        return "preuve", detail
    person = data.person
    if person is None or person == data.handle:
        return "liaison", "déliée"
    return "liaison", f"reliée à {known_as(s, str(person))}"


def _ledger(s: IdentityState, handle: str, ctx: InspectContext) -> Block:
    """Le registre des raisons de croire (ou de ne plus croire), relu au
    journal : ces événements ne portent aucun contenu, rien n'y est oublié."""
    if ctx.journal is None:
        return Note("Le magasin n'est pas disponible : le registre des preuves ne peut pas être relu.", tone="mut")
    found = ctx.events((c.CLAIMED, c.EVIDENCE, c.LINKED), MAX_LEDGER, where=("handle", handle))
    rows = []
    for e in found:
        label, detail = _describe_event(e, s)
        by = str(getattr(e.data, "by", ""))
        message = getattr(e.data, "message", None)
        rows.append((Ref("event", str(e.seq), str(e.seq)), ctx.when(e.at), label, detail,
                     BY_FR.get(by, by) or "le noyau",
                     Ref("event", str(message), f"message {message}") if message is not None else "—"))
    return Table(("n°", "quand", "sorte", "détail", "par", "message"), tuple(rows),
                 title=f"Registre des preuves (au plus {MAX_LEDGER}, les plus récentes d'abord)",
                 empty="aucune revendication, preuve ni liaison")


@IDENTITY.inspect("personne", title="Une personne", params=[("handle", "poignée")])
def _person(s: IdentityState, frame: Frame, ctx: InspectContext) -> list[Block]:
    handle = ctx.param("handle")
    if not handle:
        return [Note("Choisissez une poignée dans la liste des personnes (paramètre « handle »).")]
    h = s.handles.get(handle)
    if h is None:
        return [Note(f"Poignée inconnue : « {handle} ». Elle n'a jamais été vue.", tone="mut")]
    view = view_of(s, handle, frame.now)
    owners = set(_params(frame.env.params_of("identity", frame.root)).owners)
    owner = frame.get(c.IS_OWNER(view.person))
    why_owner = ("opératrice authentifiée" if h.authenticated and h.operator
                 else "déclarée propriétaire" if handle in owners else "par une autre de ses poignées" if owner
                 else "")
    blocks: list[Block] = [Fields((
        ("poignée", handle), ("nom", view.name or "—"), ("canal", h.channel or "—"),
        ("confiance du canal", TRUST_FR.get(h.trust, str(h.trust))),
        ("vue pour la première fois", ctx.when(h.first_seen) if h.first_seen else "—"),
        ("connue depuis (toutes poignées)", ctx.when(view.first_seen) if view.first_seen else "—"),
        ("compte authentifié", "oui" if h.authenticated else "non"),
        ("joignable d'elle-même", "oui (conversation privée)" if h.push else "non"),
        ("parle pour", person_ref(view.person, known_as(s, view.person)) if view.bound else "elle-même"),
        ("propriétaire", f"oui — {why_owner}" if owner else "non"),
        ("jetable", "non" if is_identifiable(handle) else "oui : aucune mémoire durable ne s'y attache"),
    ), title="La poignée")]
    blocks += _verdict(frame, handle, h, view)
    blocks.append(_claim(s, h, view, ctx))
    others = [k for k in handles_of(s, view.person) if k != handle]
    rows = []
    for k in others[:MAX_HANDLES]:
        o = s.handles[k]
        rows.append((person_ref(k), o.channel or "—", TRUST_FR.get(o.trust, str(o.trust)),
                     "elle-même" if not o.person else VIA_FR.get(o.via, o.via or "?"),
                     certainty_fr(view_of(s, k, frame.now).certainty)))
    blocks.append(Table(("poignée", "canal", "confiance du canal", "liée par", "certitude"), tuple(rows),
                        title=f"Les autres poignées de {known_as(s, view.person)}",
                        empty="aucune autre poignée ne parle pour cette personne"))
    blocks.append(_ledger(s, handle, ctx))
    blocks.append(Fields((("ses liens", Ref("view", "social/liens", f"voir ses liens ({known_as(s, view.person)})",
                                            (("person", view.person),))),
                          ("son fil", Ref("view", "transcript/fil", "voir le fil de cette poignée",
                                          (("handle", handle),)))),
                         title="Ailleurs"))
    return blocks
