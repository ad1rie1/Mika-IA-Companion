"""Ce qu'``identity`` montre à un opérateur : les personnes et leurs poignées,
ce que chacune prouve, et pourquoi elle ouvre ce qu'elle ouvre.

Deux types d'objets ont leur fiche : la **personne** (sa clé ; une poignée
reliée y renvoie) et la **poignée**. Lecture seule. Le verdict est celui que
la faculté applique (les faits ``IDENTITY`` et ``DISCLOSURE``) ;
l'explication le déroule pas à pas avec les mêmes barres (``vocab.privacy``),
sans jamais le recalculer autrement.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from mika.contracts import affect as affect_c
from mika.contracts import identity as c
from mika.contracts import memory as memory_c
from mika.contracts import runtime as rt
from mika.contracts import social as social_c
from mika.contracts import transcript as transcript_c
from mika.faculties.identity.faculty import (
    IDENTITY,
    Handle,
    IdentityState,
    _first_seen,
    _params,
    _root,
    handles_of,
    known_as,
    view_of,
)
from mika.kernel.events import Event
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    Badge,
    Block,
    Cell,
    Column,
    Fields,
    Found,
    Head,
    InspectContext,
    Meter,
    Note,
    Pager,
    Param,
    Ref,
    Row,
    Section,
    Stat,
    Stats,
    Table,
    Text,
    When,
    paginate,
)
from mika.vocab import privacy
from mika.vocab.people import fold, is_identifiable, is_internal
from mika.vocab.privacy import ChannelTrust, Disclosure, Sensitivity

#: Au plus tant de lignes au registre des preuves par page, tant de lignes par page d'une liste.
MAX_LEDGER = 50
PAGE = 50
#: la page d'un tableau de poignées (une fiche n'en montre qu'un)
HANDLES_PAGE = "page_poignees"
#: Une personne connue seulement de nom (``name:alice``) : pas de poignée.
NAMED = "name:"

TRUST_FR = {
    ChannelTrust.AUTHENTICATED: "authentifiée (session vérifiée)",
    ChannelTrust.ACCOUNT: "compte (le même compte revient)",
    ChannelTrust.PUBLIC: "publique (rien ne prouve qui écrit)",
    ChannelTrust.INTERNAL: "interne (pas une personne)",
}
TRUST_SHORT = {ChannelTrust.AUTHENTICATED: "authentifiée", ChannelTrust.ACCOUNT: "compte",
               ChannelTrust.PUBLIC: "publique", ChannelTrust.INTERNAL: "interne"}
TRUST_TONE = {ChannelTrust.AUTHENTICATED: "ok", ChannelTrust.ACCOUNT: "info", ChannelTrust.PUBLIC: "warn",
              ChannelTrust.INTERNAL: "muted"}
_TRUST_RANK = {ChannelTrust.INTERNAL: 0, ChannelTrust.PUBLIC: 1, ChannelTrust.ACCOUNT: 2,
               ChannelTrust.AUTHENTICATED: 3}
CERTAINTY_FR = {"unknown": "inconnue", "suspected": "soupçonnée", "claimed": "affirmée",
                "corroborated": "recoupée", "bound": "liée", "verified": "vérifiée"}
LEVEL_FR = {Sensitivity.NONE: "rien sur autrui", Sensitivity.ANODYNE: "anodin", Sensitivity.PERSONAL: "personnel",
            Sensitivity.CONFIDENCE: "confidences"}
LEVEL_TONE = {Sensitivity.NONE: "muted", Sensitivity.ANODYNE: "muted", Sensitivity.PERSONAL: "info",
              Sensitivity.CONFIDENCE: "ok"}
CLOSENESS_FR = {social_c.STRANGER: "une inconnue", social_c.ACQUAINTANCE: "une connaissance",
                social_c.FRIEND: "une amie", social_c.CLOSE: "une proche"}
EVIDENCE_FR = {"self_declared": "affirmation", c.SHARED_MEMORY: "souvenir partagé recoupé", c.DENIED: "démenti",
               c.CONTRADICTED: "contredit", c.REVOKED: "liaison oubliée", c.VOUCHED: "un opérateur s'en porte garant",
               "passive_inference": "indice passif", "authenticated": "session authentifiée"}
VIA_FR = {"corroborated": "recoupement", "operator": "opérateur", "vouched": "garantie d'un opérateur"}
BY_FR = {"kernel": "le noyau", "tool": "elle (outil)", "operator": "un opérateur"}


def number(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def certainty_fr(value: float) -> str:
    return f"{number(value)} ({CERTAINTY_FR.get(privacy.certainty_name(value), '?')})"


def disclosure_fr(d: Disclosure) -> str:
    return f"{LEVEL_FR.get(d.level, '?')} · sa fiche {'ouverte' if d.own_file else 'fermée'}"


def person_ref(s: IdentityState, person: str, tab: str = "") -> Ref:
    return Ref.subject("person", person, known_as(s, person), tab)


def handle_ref(handle: str, text: str = "", tab: str = "") -> Ref:
    return Ref.subject("handle", handle, text or handle, tab)


def _stance(frame: Frame, handle: str, person: str) -> tuple[str, float]:
    """Proximité et chaleur, lues comme le fait ``DISCLOSURE`` (rien pour une
    poignée jetable)."""
    if not is_identifiable(handle):
        return "", 0.0
    return frame.get(social_c.CLOSENESS(person)), frame.get(affect_c.WARMTH(person))


def _disclosures(frame: Frame, handle: str, h: Handle) -> tuple[Disclosure, Disclosure]:
    return (frame.get(c.DISCLOSURE((handle, h.channel, False))),
            frame.get(c.DISCLOSURE((handle, h.channel, True))))


def _declared_owners(frame: Frame) -> tuple[str, ...]:
    return _params(frame.env.params_of("identity", frame.root)).owners


def people(s: IdentityState, frame: Frame) -> dict[str, tuple[str, ...]]:
    """Chaque personne connue et ses poignées (une propriétaire déclarée qui
    n'a jamais écrit est une personne sans poignée)."""
    out: dict[str, list[str]] = {}
    for key, h in s.handles.items():
        out.setdefault(h.person or key, []).append(key)
    for key in _declared_owners(frame):
        out.setdefault(_root(s, key), [])
    return {p: tuple(sorted(hs)) for p, hs in out.items()}


def principal(s: IdentityState, person: str) -> str | None:
    """Sa poignée principale : celle dont le canal prouve le plus (puis elle-même,
    puis la plus ancienne)."""
    known = [k for k in handles_of(s, person) if k in s.handles]
    if not known:
        return None
    return max(known, key=lambda k: (_TRUST_RANK[s.handles[k].trust], k == person, -s.handles[k].first_seen, k))


def _last_from(frame: Frame, handles: Sequence[str]) -> int:
    return max((frame.get(transcript_c.LAST_FROM(k)) for k in handles), default=0)


def _like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _named_exists(ctx: InspectContext, key: str) -> bool:
    """Une personne connue seulement de nom existe si la mémoire en parle."""
    if len(key) <= len(NAMED) or ctx.store is None:
        return False
    rows = ctx.store.query_mind(f"SELECT 1 FROM {memory_c.ITEMS_TABLE} WHERE about LIKE ? ESCAPE '\\' LIMIT 1",
                                (f'%"{_like(key)}"%',))
    return bool(rows)


def canonical(s: IdentityState, frame: Frame, ctx: InspectContext, key: str) -> str | None:
    """La clé de personne d'une clé ou d'une poignée ; ``None`` si inconnue."""
    key = key.strip()
    if not key or is_internal(key):
        return None
    if key.startswith(NAMED):
        return key if _named_exists(ctx, key) else None
    person = frame.get(c.PERSON(key))
    return person if person in people(s, frame) else None


def _why_owner(s: IdentityState, frame: Frame, person: str) -> str:
    owners = set(_declared_owners(frame))
    for k in handles_of(s, person) or (person,):
        h = s.handles.get(k)
        if h is not None and h.authenticated and h.operator:
            return f"opératrice authentifiée ({k})"
        if k in owners:
            return f"déclarée propriétaire ({k})"
    return ""


def _closeness_fr(frame: Frame, person: str) -> str:
    if not is_identifiable(person):
        return "—"
    return CLOSENESS_FR.get(frame.get(social_c.CLOSENESS(person)), "une inconnue")


def _when(ctx: InspectContext, at: int, never: str = "jamais") -> str:
    return ctx.when(at) if at else never


# ── Les fiches : en-têtes et recherche ────────────────────────────────────


@IDENTITY.subject("person", label="Personne", plural="Personnes", forgettable=True, icon="☺")
def _person_head(s: IdentityState, frame: Frame, ctx: InspectContext, key: str) -> Head | None:
    person = canonical(s, frame, ctx, key)
    if person is None:
        return None
    if person.startswith(NAMED):
        return Head(person, known_as(s, person),
                    "Connue seulement de nom : on lui a parlé d'elle, elle ne lui a jamais écrit.",
                    badges=(Badge("de nom seulement", "muted"),))
    handles = handles_of(s, person)
    main = principal(s, person)
    owner = frame.get(c.IS_OWNER(person))
    first = _first_seen(s, person, 0)
    relation = _closeness_fr(frame, person)
    if not is_identifiable(person):
        subtitle = "Une connexion de passage : rien de durable ne s'y attache."
    else:
        subtitle = relation[:1].upper() + relation[1:]
        subtitle += ", et sa propriétaire" if owner else ""
        subtitle += f" — connue depuis {ctx.when(first)}" if first else ""
    badges: list[Badge] = []
    if owner:
        badges.append(Badge("propriétaire", "info"))
    badges.append(Badge(f"liée · {len(handles)} poignées", "ok") if len(handles) > 1 else Badge("non liée", "muted"))
    facts: list[tuple[str, Cell]] = [("poignées", len(handles))]
    if main is not None:
        h = s.handles[main]
        view = view_of(s, main, frame.now)
        private, _public = _disclosures(frame, main, h)
        badges.append(Badge(f"en privé : {LEVEL_FR.get(private.level, '?')}", LEVEL_TONE.get(private.level, "")))
        facts += [("canal principal", f"{h.channel or '—'} · {TRUST_SHORT[h.trust]}"),
                  ("certitude", certainty_fr(view.certainty))]
    if not is_identifiable(person):
        badges.append(Badge("jetable", "muted"))
    facts += [("proximité", relation), ("vue pour la première fois", _when(ctx, first, "—")),
              ("dernier message reçu", _when(ctx, _last_from(frame, handles)))]
    return Head(person, known_as(s, person), subtitle, tuple(badges), tuple(facts[:6]), handles)


@IDENTITY.search("person")
def _search_people(s: IdentityState, frame: Frame, ctx: InspectContext, text: str, limit: int) -> list[Found]:
    q = fold(text)
    found: list[tuple[int, str, Found]] = []
    for person, handles in people(s, frame).items():
        name = known_as(s, person)
        if q and q not in fold(name) and q not in fold(person) and not any(q in fold(k) for k in handles):
            continue
        shown = ", ".join(handles[:3]) + ("…" if len(handles) > 3 else "")
        found.append((_last_from(frame, handles), person, Found(person, name, shown or "aucune poignée")))
    found.sort(key=lambda x: (-x[0], x[1]))
    return [f for _last, _key, f in found[:limit]]


@IDENTITY.subject("handle", label="Poignée", plural="Poignées", icon="◎")
def _handle_head(s: IdentityState, frame: Frame, ctx: InspectContext, key: str) -> Head | None:
    h = s.handles.get(key.strip())
    if h is None:
        return None
    handle = key.strip()
    view = view_of(s, handle, frame.now)
    if view.bound:
        subtitle = f"Parle pour {known_as(s, view.person)} (liée par {VIA_FR.get(h.via, h.via or '?')})."
    else:
        subtitle = f"Parle pour elle-même{f' — « {view.name} »' if view.name else ''}."
    badges = [Badge(TRUST_SHORT[h.trust], TRUST_TONE[h.trust]),
              Badge(f"certitude {certainty_fr(view.certainty)}",
                    "ok" if view.certainty >= privacy.POLICY.private_threshold else "muted"),
              Badge("liée", "ok") if view.bound else Badge("non liée", "muted")]
    if view.claim:
        badges.append(Badge(f"revendique « {view.claim} »", "warn"))
    if frame.get(c.IS_OWNER(view.person)):
        badges.append(Badge("propriétaire", "info"))
    if not is_identifiable(handle):
        badges.append(Badge("jetable", "muted"))
    facts: tuple[tuple[str, Cell], ...] = (
        ("canal", h.channel or "—"), ("nom", view.name or "—"),
        ("parle pour", person_ref(s, view.person) if view.bound else "elle-même"),
        ("vue pour la première fois", _when(ctx, h.first_seen, "—")),
        ("dernier message reçu", _when(ctx, frame.get(transcript_c.LAST_FROM(handle)))),
        ("joignable d'elle-même", "oui (conversation privée)" if h.push else "non"),
    )
    return Head(handle, handle, subtitle, tuple(badges), facts)


@IDENTITY.search("handle")
def _search_handles(s: IdentityState, frame: Frame, ctx: InspectContext, text: str, limit: int) -> list[Found]:
    q = fold(text)
    ordered = sorted(s.handles.items(), key=lambda kv: (-kv[1].first_seen, kv[0]))
    out: list[Found] = []
    for key, h in ordered:
        if q and q not in fold(key) and q not in fold(h.name):
            continue
        out.append(Found(key, key, f"{h.name or '—'} · {h.channel or '—'} · {TRUST_SHORT[h.trust]}"))
        if len(out) >= limit:
            break
    return out


# ── Le verdict ────────────────────────────────────────────────────────────


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


def _opens(frame: Frame, handle: str, h: Handle, view: c.IdentityView) -> Table:
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
    return Table(("audience", "sur autrui", "pourquoi", "si elle ou il est concerné", "sa propre fiche"),
                 tuple(rows), title="Ce que ça ouvre")


def _verdict(frame: Frame, handle: str, h: Handle, view: c.IdentityView) -> list[Block]:
    return [Table(("étape", "valeur", "pourquoi"), tuple(_steps(h, view.certainty)), title="Le verdict, pas à pas"),
            _opens(frame, handle, h, view)]


def _handle_fields(s: IdentityState, frame: Frame, handle: str, h: Handle, view: c.IdentityView) -> Fields:
    owner = frame.get(c.IS_OWNER(view.person))
    why = _why_owner(s, frame, view.person)
    return Fields((
        ("poignée", Text(handle, "mono")), ("nom", view.name or "—"), ("canal", h.channel or "—"),
        ("confiance du canal", TRUST_FR.get(h.trust, str(h.trust))),
        ("vue pour la première fois", When(h.first_seen) if h.first_seen else "—"),
        ("connue depuis (toutes poignées)", When(view.first_seen) if view.first_seen else "—"),
        ("compte authentifié", "oui" if h.authenticated else "non"),
        ("joignable d'elle-même", "oui (conversation privée)" if h.push else "non"),
        ("parle pour", person_ref(s, view.person) if view.bound
         else Ref.subject("person", handle, "elle-même (sa fiche)")),
        ("propriétaire", f"oui — {why or 'par une autre de ses poignées'}" if owner else "non"),
        ("jetable", "non" if is_identifiable(handle) else "oui : aucune mémoire durable ne s'y attache"),
    ), title="La poignée", columns=2)


def _used(mark: str) -> str:
    if mark.startswith("item:"):
        return f"élément de mémoire n°{mark[5:]}"
    return EVIDENCE_FR.get(mark, mark)


def _claim(s: IdentityState, h: Handle, view: c.IdentityView, ctx: InspectContext) -> list[Block]:
    claim = h.claim
    if claim is None:
        return [Note("Aucune revendication en attente.", tone="muted")]
    target: Cell = person_ref(s, claim.target) if claim.target else "plusieurs personnes portent ce nom"
    certainty = privacy.effective(claim.certainty, h.trust)
    bar = privacy.POLICY.private_threshold
    ttl = privacy.POLICY.pending_claim_ttl_days * 86_400_000_000
    blocks: list[Block] = [Fields((
        ("nom revendiqué", f"« {claim.name} »"), ("personne visée", target),
        ("certitude de la revendication", certainty_fr(certainty)),
        ("vers la barre", Meter(certainty / bar if bar else 0.0, f"{number(certainty)} / {number(bar)}",
                                "ok" if certainty >= bar else "")),
        ("preuves déjà comptées", ", ".join(_used(u) for u in claim.used) or "—"),
        ("depuis", When(claim.at)),
        ("s'éteint", When(claim.at + ttl) if view.claim else "déjà éteinte"),
        ("état", "active" if view.claim else "éteinte (jamais confirmée à temps)"),
    ), title="Revendication en cours", columns=2)]
    if view.claim and claim.target:
        missing = max(0.0, bar - certainty)
        blocks.append(Note(
            f"Il manque {number(missing)} pour atteindre la barre. Ce qui peut la confirmer : un souvenir partagé "
            f"que seule {known_as(s, claim.target)} pouvait connaître (+{number(privacy.EVIDENCE[c.SHARED_MEMORY])}), "
            f"un opérateur qui s'en porte garant (+{number(privacy.EVIDENCE[c.VOUCHED])}), ou qui relie directement "
            f"cette poignée (certitude {number(privacy.BOUND)}). Le plafond du canal reste "
            f"{number(privacy.CEILINGS[h.trust])}.", title="Pour la confirmer"))
    return blocks


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


_KIND_TONE = {"revendication": "warn", "preuve": "info", "liaison": "ok"}


def _ledger(s: IdentityState, handle: str, ctx: InspectContext) -> Block:
    """Le registre des raisons de croire (ou de ne plus croire), relu au
    journal : ces événements ne portent aucun contenu, rien n'y est oublié.
    L'opérateur qui a agi est lu dans l'audit de la console."""
    if ctx.journal is None:
        return Note("Le magasin n'est pas disponible : le registre des preuves ne peut pas être relu.", tone="muted")
    before = ctx.int_param("avant", 0) or None
    found = ctx.events((c.CLAIMED, c.EVIDENCE, c.LINKED), MAX_LEDGER, where=("handle", handle), before=before)
    operators: dict[int, str] = {}
    if any(str(getattr(e.data, "by", "")) == "operator" for e in found):
        for op in ctx.events((rt.OPERATED,), 200, where=("subject", handle)):
            for seq in op.data.seqs:
                operators[int(seq)] = str(op.data.by)
    rows = []
    for e in found:
        label, detail = _describe_event(e, s)
        by = str(getattr(e.data, "by", ""))
        who = BY_FR.get(by, by) or "le noyau"
        if e.seq in operators:
            who = f"{who} ({operators[e.seq]})"
        message = getattr(e.data, "message", None)
        rows.append(Row((Ref("event", str(e.seq), str(e.seq)), When(e.at), Badge(label, _KIND_TONE.get(label, "")),
                         detail, who, Ref("event", str(message), f"message {message}") if message is not None
                         else "—")))
    pager = Pager(older=(("avant", str(found[-1].seq)),)) if len(found) == MAX_LEDGER else None
    return Table((Column("n°", "fit"), Column("quand", "fit"), "sorte", "détail", "par", "message"), tuple(rows),
                 title="Registre des preuves (les plus récentes d'abord)", pager=pager,
                 empty="aucune revendication, preuve ni liaison")


def _handles_table(s: IdentityState, frame: Frame, ctx: InspectContext, handles: Sequence[str], *, title: str,
                   empty: str) -> Table:
    """Ces poignées, toutes, par pages."""
    page, pager = paginate([k for k in handles if k in s.handles], ctx.pager(HANDLES_PAGE, size=PAGE))
    rows = []
    for k in page:
        o = s.handles[k]
        view = view_of(s, k, frame.now)
        rows.append(Row((handle_ref(k), o.name or "—", o.channel or "—", Badge(TRUST_SHORT[o.trust], TRUST_TONE[o.trust]),
                         certainty_fr(view.certainty), "elle-même" if not o.person else VIA_FR.get(o.via, o.via or "?"),
                         f"« {view.claim} »" if view.claim else "—",
                         When(o.first_seen) if o.first_seen else "—",
                         When(last) if (last := frame.get(transcript_c.LAST_FROM(k))) else "jamais"),
                        href=handle_ref(k)))
    return Table(("poignée", "nom", "canal", "confiance", "certitude", "liée par", "revendique",
                  "vue pour la première fois", "dernier message"), tuple(rows), title=title, empty=empty,
                 pager=pager)


# ── Fiche d'une personne ──────────────────────────────────────────────────


def _person_of(s: IdentityState, frame: Frame, ctx: InspectContext) -> tuple[str | None, list[Block]]:
    key = ctx.subject or ctx.param("person")
    if not key:
        return None, [Note("Ouvre la fiche d'une personne : Personnes, puis la personne.", tone="muted")]
    person = canonical(s, frame, ctx, key)
    if person is None:
        return None, [Note(f"Personne inconnue : « {key} ».", tone="muted")]
    return person, []


@IDENTITY.inspect("synthese", title="Synthèse", subject="person", order=10,
                  description="Qui c'est, à quel point elle en est sûre, et ce qu'elle peut lui dire.")
def _synthesis(s: IdentityState, frame: Frame, ctx: InspectContext) -> list[Block]:
    person, blocks = _person_of(s, frame, ctx)
    if person is None:
        return blocks
    if person.startswith(NAMED):
        return [Note("Connue seulement de nom : quelqu'un lui a parlé d'elle, mais elle ne lui a jamais écrit. "
                     "Ce qu'elle en sait est dans sa mémoire.", tone="muted"),
                Fields((("nom", known_as(s, person)), ("clé", Text(person, "mono"))))]
    handles = handles_of(s, person)
    owner = frame.get(c.IS_OWNER(person))
    why = _why_owner(s, frame, person)
    reachable = frame.get(c.REACHABLE(person))
    first = _first_seen(s, person, 0)
    blocks.append(Fields((
        ("nom", known_as(s, person)), ("clé de personne", Text(person, "mono")),
        ("propriétaire", f"oui — {why}" if owner and why else "oui" if owner else "non"),
        ("connue depuis", When(first) if first else "—"),
        ("proximité", _closeness_fr(frame, person)),
        ("joignable d'elle-même", ", ".join(reachable) if reachable
         else "non : il faut qu'elle ou il écrive le premier"),
    ), title="Qui", columns=2))
    main = principal(s, person)
    if main is None:
        blocks.append(Note("Aucune poignée connue : déclarée propriétaire, elle ou il n'a encore jamais écrit.",
                           tone="muted"))
        return blocks
    h = s.handles[main]
    view = view_of(s, main, frame.now)
    blocks.append(Section("Ce qu'elle peut lui dire", (
        Fields((("poignée principale", handle_ref(main)), ("canal", f"{h.channel or '—'} · {TRUST_FR[h.trust]}"),
                ("certitude effective", certainty_fr(view.certainty)),
                ("barre de divulgation", number(privacy.POLICY.private_threshold))), columns=2),
        _opens(frame, main, h, view),
    ), description="Sur sa poignée principale (celle dont le canal prouve le plus). Chaque poignée a son verdict "
                   "pas à pas sur sa fiche."))
    # la liste des poignées vit dans l'onglet « Poignées » : ici, un renvoi (pas deux fois la même table)
    blocks.append(Fields((("ses poignées", Ref.subject("person", person, f"{len(handles)} poignée(s) : voir l'onglet "
                                                                          "Poignées", "poignees")),),
                         title="Ses poignées"))
    return blocks


@IDENTITY.inspect("poignees", title="Poignées", subject="person", order=20,
                  description="Les poignées qui parlent pour cette personne, et comment elles ont été reliées.")
def _person_handles(s: IdentityState, frame: Frame, ctx: InspectContext) -> list[Block]:
    person, blocks = _person_of(s, frame, ctx)
    if person is None:
        return blocks
    handles = handles_of(s, person)
    bound = sum(1 for k in handles if s.handles[k].person)
    blocks += [
        Stats((Stat("poignées", len(handles)), Stat("reliées à elle", bound, "par recoupement ou par un opérateur"),
               Stat("revendications en attente", sum(1 for k in handles if view_of(s, k, frame.now).claim)))),
        _handles_table(s, frame, ctx, handles, title="Ses poignées", empty="aucune poignée connue"),
        Note(f"Pour relier une autre poignée à cette personne : ouvre la fiche de la poignée, puis « Relier », "
             f"et indique « {person} ».", tone="muted"),
    ]
    return blocks


# ── Fiche d'une poignée ───────────────────────────────────────────────────


def _handle_of(s: IdentityState, ctx: InspectContext) -> tuple[str, Handle | None, list[Block]]:
    handle = ctx.subject or ctx.param("handle")
    if not handle:
        return "", None, [Note("Ouvre la fiche d'une poignée : Identités, puis la poignée.", tone="muted")]
    h = s.handles.get(handle)
    if h is None:
        return handle, None, [Note(f"Poignée inconnue : « {handle} ». Elle n'a jamais été vue.", tone="muted")]
    return handle, h, []


@IDENTITY.inspect("verdict", title="Verdict", subject="handle", subject_param="handle", order=10,
                  description="Pourquoi cette poignée ouvre ce qu'elle ouvre, pas à pas.")
def _handle_verdict(s: IdentityState, frame: Frame, ctx: InspectContext) -> list[Block]:
    handle, h, blocks = _handle_of(s, ctx)
    if h is None:
        return blocks
    view = view_of(s, handle, frame.now)
    return [_handle_fields(s, frame, handle, h, view), *_verdict(frame, handle, h, view)]


@IDENTITY.inspect("revendication", title="Revendication", subject="handle", subject_param="handle", order=20,
                  description="Qui elle dit être, et ce qui manque pour le croire.")
def _handle_claim(s: IdentityState, frame: Frame, ctx: InspectContext) -> list[Block]:
    handle, h, blocks = _handle_of(s, ctx)
    if h is None:
        return blocks
    if h.authenticated:
        return [Note("Une session authentifiée prouve déjà qui écrit : aucune revendication n'y compte.",
                     tone="muted")]
    return _claim(s, h, view_of(s, handle, frame.now), ctx)


@IDENTITY.inspect("preuves", title="Preuves", subject="handle", subject_param="handle", order=30,
                  description="Chaque raison de croire, ou de ne plus croire.")
def _handle_evidence(s: IdentityState, frame: Frame, ctx: InspectContext) -> list[Block]:
    handle, h, blocks = _handle_of(s, ctx)
    if h is None:
        return blocks
    return [_ledger(s, handle, ctx)]


@IDENTITY.inspect("autres", title="Autres poignées", subject="handle", subject_param="handle", order=40,
                  description="Les autres poignées de la même personne.")
def _handle_others(s: IdentityState, frame: Frame, ctx: InspectContext) -> list[Block]:
    handle, h, blocks = _handle_of(s, ctx)
    if h is None:
        return blocks
    view = view_of(s, handle, frame.now)
    others = [k for k in handles_of(s, view.person) if k != handle]
    return [Fields((("personne", person_ref(s, view.person)),)),
            _handles_table(s, frame, ctx, others, title=f"Les autres poignées de {known_as(s, view.person)}",
                           empty="aucune autre poignée ne parle pour cette personne")]


# ── Les destinations ──────────────────────────────────────────────────────

SEARCH = Param("q", "nom ou poignée", placeholder="Alice, tg_42…")
TRUSTS = Param("confiance", "confiance du canal", kind="select",
               choices=tuple((t.value, TRUST_SHORT[t]) for t in ChannelTrust if t is not ChannelTrust.INTERNAL))


@IDENTITY.inspect("personnes", title="Personnes", section="personnes", order=10, params=[SEARCH],
                  description="Les gens qu'elle connaît ; une ligne mène à la fiche de la personne.")
def _people(s: IdentityState, frame: Frame, ctx: InspectContext) -> list[Block]:
    q = fold(str(ctx.value("q") or ""))
    everyone = people(s, frame)
    matched = []
    for person, handles in everyone.items():
        name = known_as(s, person)
        if q and q not in fold(name) and q not in fold(person) and not any(q in fold(k) for k in handles):
            continue
        matched.append((_last_from(frame, handles), person, handles))
    matched.sort(key=lambda x: (-x[0], x[1]))
    page, pager = paginate(matched, ctx.pager(size=PAGE))
    rows = []
    for last, person, handles in page:
        main = principal(s, person)
        h = s.handles.get(main) if main else None
        view = view_of(s, main, frame.now) if main else None
        closeness = frame.get(social_c.CLOSENESS(person)) if is_identifiable(person) else ""
        rows.append(Row((
            person_ref(s, person), len(handles),
            Badge(TRUST_SHORT[h.trust], TRUST_TONE[h.trust]) if h else "—",
            certainty_fr(view.certainty) if view else "—",
            Badge(CLOSENESS_FR.get(closeness, "—"), "info" if closeness in (social_c.FRIEND, social_c.CLOSE) else "")
            if closeness else "—",
            Badge("propriétaire", "info") if frame.get(c.IS_OWNER(person)) else "",
            When(last) if last else "jamais",
            When(first) if (first := _first_seen(s, person, 0)) else "—",
        ), href=person_ref(s, person)))
    return [
        Stats((Stat("personnes", len(everyone)),
               Stat("propriétaires", len(frame.get(c.OWNERS))),
               Stat("reliées à plusieurs poignées", sum(1 for hs in everyone.values() if len(hs) > 1)))),
        Table(("personne", Column("poignées", "num"), "canal principal", "certitude", "proximité", "propriétaire",
               "dernier message reçu", "vue pour la première fois"), tuple(rows), title="Personnes", pager=pager,
              filters=("q",),
              empty=f"personne ne correspond à « {ctx.value('q')} »" if q else "personne pour l'instant"),
    ]


@IDENTITY.inspect("annuaire", title="Poignées", section="identites", order=10, params=[SEARCH, TRUSTS],
                  description="Chaque poignée vue, ce qu'elle prouve et ce qu'elle ouvre ; une ligne mène à sa fiche.")
def _directory(s: IdentityState, frame: Frame, ctx: InspectContext) -> list[Block]:
    q = fold(str(ctx.value("q") or ""))
    trust = str(ctx.value("confiance") or "")
    ordered = sorted(s.handles.items(), key=lambda kv: (-kv[1].first_seen, kv[0]))
    matched = [(k, h) for k, h in ordered
               if (not q or q in fold(k) or q in fold(h.name)) and (not trust or h.trust.value == trust)]
    page, pager = paginate(matched, ctx.pager(size=PAGE))
    rows = []
    for handle, h in page:
        view = view_of(s, handle, frame.now)
        private, public = _disclosures(frame, handle, h)
        rows.append(Row((
            handle_ref(handle), view.name or "—", h.channel or "—", Badge(TRUST_FR[h.trust], TRUST_TONE[h.trust]),
            certainty_fr(view.certainty), person_ref(s, view.person) if view.bound else "elle-même",
            "oui" if frame.get(c.IS_OWNER(view.person)) else "non",
            f"« {view.claim} »" if view.claim else "—", disclosure_fr(private), disclosure_fr(public),
            When(h.first_seen) if h.first_seen else "—",
        ), href=handle_ref(handle)))
    owners = ", ".join(known_as(s, p) for p in frame.get(c.OWNERS)) or "aucun"
    return [
        Stats((Stat("poignées connues", len(s.handles)),
               Stat("liées à une autre personne", sum(1 for h in s.handles.values() if h.person)),
               Stat("revendications en attente", len(pending_claims(s, frame.now)),
                    href=Ref.view("identity", "revendications", "revendications")),
               Stat("propriétaires", owners),
               Stat("barre de divulgation", number(privacy.POLICY.private_threshold),
                    href=Ref.view("identity", "politique", "politique")))),
        Table(("poignée", "nom", "canal", "confiance du canal", "certitude", "parle pour", "propriétaire",
               "revendique", "divulgation en privé", "divulgation en public", "vue pour la première fois"),
              tuple(rows), title="Poignées", pager=pager, filters=("q", "confiance"),
              empty="aucune poignée ne correspond" if q or trust else "aucune poignée vue pour l'instant"),
    ]


def pending_claims(s: IdentityState, now: int) -> list[tuple[str, Handle]]:
    """Les revendications en attente (pas encore éteintes), de la plus récente à la plus ancienne."""
    out = [(k, h) for k, h in s.handles.items() if h.claim is not None and view_of(s, k, now).claim]
    return sorted(out, key=lambda kv: (-(kv[1].claim.at if kv[1].claim else 0), kv[0]))


def _claims_badge(s: IdentityState, frame: Frame) -> int:
    return len(pending_claims(s, frame.now))


@IDENTITY.inspect("revendications", title="Revendications", section="identites", order=20, badge=_claims_badge,
                  description="Qui dit être quelqu'un d'autre, sans preuve encore : à confirmer, garantir ou "
                              "démentir depuis la fiche de la poignée.")
def _claims(s: IdentityState, frame: Frame, ctx: InspectContext) -> list[Block]:
    pending = pending_claims(s, frame.now)
    page, pager = paginate(pending, ctx.pager(size=PAGE))
    bar = privacy.POLICY.private_threshold
    ttl = privacy.POLICY.pending_claim_ttl_days * 86_400_000_000
    rows = []
    for handle, h in page:
        claim = h.claim
        if claim is None:
            continue
        certainty = privacy.effective(claim.certainty, h.trust)
        rows.append(Row((
            handle_ref(handle, tab="revendication"), f"« {claim.name} »",
            person_ref(s, claim.target) if claim.target else Text("plusieurs personnes portent ce nom", "muted"),
            Badge(TRUST_SHORT[h.trust], TRUST_TONE[h.trust]),
            Meter(certainty / bar if bar else 0.0, f"{number(certainty)} / {number(bar)}"),
            ", ".join(_used(u) for u in claim.used) or "—", When(claim.at), When(claim.at + ttl),
        ), href=handle_ref(handle, tab="revendication")))
    return [Table(("poignée", "nom revendiqué", "vise", "canal", "vers la barre", "preuves comptées", "depuis",
                   "s'éteint"), tuple(rows), title="Revendications en attente", pager=pager,
                  empty="aucune revendication en attente"),
            Note(f"Une affirmation seule ne franchit jamais la barre ({number(bar)}) ; une revendication jamais "
                 f"confirmée s'éteint au bout de {privacy.POLICY.pending_claim_ttl_days} jours.", tone="muted")]


def _opens_at_best(trust: ChannelTrust) -> str:
    """Au mieux, sur ce canal (au plafond, une proche, en privé)."""
    ceiling = privacy.CEILINGS[trust]
    level = privacy.disclosable(ceiling, trust, closeness=social_c.CLOSE, witness=True)
    own = "peut s'ouvrir" if privacy.may_disclose_private(ceiling, trust) else "jamais ouverte"
    return f"{LEVEL_FR.get(level, '?')} · sa fiche {own}"


@IDENTITY.inspect("politique", title="Politique", section="identites", order=30,
                  description="Les barres que la faculté applique : lues dans la politique, jamais recopiées.")
def _policy(s: IdentityState, frame: Frame, ctx: InspectContext) -> list[Block]:
    pol = privacy.POLICY
    channels = tuple((Badge(TRUST_SHORT[t], TRUST_TONE[t]), TRUST_FR[t], number(privacy.FLOORS[t]),
                      number(privacy.CEILINGS[t]), _opens_at_best(t)) for t in ChannelTrust)
    levels = tuple((CERTAINTY_FR.get(name, name), number(value),
                    "atteint la barre" if value >= pol.private_threshold else "sous la barre")
                   for name, value in privacy.CERTAINTY_NAMES)
    weights = tuple((EVIDENCE_FR.get(kind, kind), Text(kind, "mono"), f"+{number(w)}", "pour")
                    for kind, w in pol.evidence.items()) + \
        tuple((EVIDENCE_FR.get(kind, kind), Text(kind, "mono"), number(w), "contre")
              for kind, w in pol.counter_evidence.items())
    ranks = tuple((CLOSENESS_FR.get(k, k), Text(k, "mono"), rank) for k, rank in privacy.CLOSENESS_RANK.items())
    problem = pol.check()
    owners = _declared_owners(frame)
    return [
        Table(("confiance", "ce que prouve le canal", "plancher", "plafond", "au mieux"), channels,
              title="Les canaux",
              caption="Le plancher relève la certitude, le plafond la borne : aucune conversation ne rend une "
                      "affirmation faite en public aussi sûre qu'une connexion."),
        Fields((("barre de divulgation (personnel sur autrui, sa propre fiche)", number(pol.private_threshold)),
                ("confidences (proche, en privé)", number(pol.confidence_threshold)),
                ("chaleur qui ouvre le personnel sans amitié", number(pol.warmth_min)),
                ("une revendication s'éteint après", f"{pol.pending_claim_ttl_days} jours")),
               title="Les barres", columns=2),
        Table(("degré", "certitude", "barre"), levels, title="Les degrés de certitude"),
        Table(("preuve", "clé", Column("poids", "num"), "sens"), weights, title="Le poids des preuves",
              caption="Une même sorte de preuve ne compte qu'une fois par revendication."),
        Table(("proximité", "clé", Column("rang", "num")), ranks, title="Les rangs de proximité"),
        Note("Calibration vérifiée : une affirmation seule reste sous la barre, affirmation et souvenir partagé "
             "l'atteignent." if problem is None else f"Calibration fausse : {problem}.",
             tone="ok" if problem is None else "danger", title="Calibration"),
        Fields((("déclarés dans les réglages", ", ".join(owners) or "aucun"),
                ("en vigueur (opératrices comprises)", ", ".join(known_as(s, p) for p in frame.get(c.OWNERS))
                 or "aucun")), title="Propriétaires"),
    ]


@IDENTITY.inspect("personne", title="Une poignée (ancienne page)", hidden=True, params=[("handle", "poignée")])
def _legacy_person(s: IdentityState, frame: Frame, ctx: InspectContext) -> list[Block]:
    """L'ancienne page d'une poignée : ses liens mènent désormais aux fiches."""
    handle, h, blocks = _handle_of(s, ctx)
    if h is None:
        if not handle:
            return [Note("Choisissez une poignée dans la liste des poignées (paramètre « handle »).")]
        return blocks
    view = view_of(s, handle, frame.now)
    return [Fields((("fiche de la poignée", handle_ref(handle)), ("fiche de la personne", person_ref(s, view.person))),
                   title="Cette page vit désormais sur les fiches"),
            _handle_fields(s, frame, handle, h, view), *_verdict(frame, handle, h, view),
            *_claim(s, h, view, ctx),
            _handles_table(s, frame, ctx, [k for k in handles_of(s, view.person) if k != handle],
                           title=f"Les autres poignées de {known_as(s, view.person)}",
                           empty="aucune autre poignée ne parle pour cette personne"),
            _ledger(s, handle, ctx)]
