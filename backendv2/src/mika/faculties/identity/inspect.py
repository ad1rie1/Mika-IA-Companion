"""Ce qu'``identity`` montre à un opérateur : les personnes et leurs adresses,
ce que chacune prouve, et pourquoi elle ouvre ce qu'elle ouvre.

Deux types d'objets ont leur fiche : la **personne** (sa clé ; une adresse
reliée y renvoie) et l'**adresse**. Lecture seule. Le verdict est celui que
la faculté applique (les faits ``IDENTITY`` et ``DISCLOSURE``) ;
l'explication le déroule pas à pas avec les mêmes barres (``vocab.privacy``),
sans jamais le recalculer autrement.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
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
    _name_of,
    _params,
    _root,
    handles_of,
    known_as,
    proves_owner,
    view_of,
)
from mika.kernel.events import Event
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    ActionSlot,
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
    Toolbar,
    When,
    paginate,
)
from mika.vocab import privacy
from mika.vocab.people import fold, is_identifiable, is_internal
from mika.vocab.privacy import ChannelTrust, Disclosure, Sensitivity

#: Au plus tant de lignes au registre des preuves par page, tant de lignes par page d'une liste.
MAX_LEDGER = 50
PAGE = 50
#: la page d'un tableau d'adresses (une fiche n'en montre qu'un)
HANDLES_PAGE = "page_adresses"
#: Une personne connue seulement de nom (``name:alice``) : pas d'adresse.
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
#: Sans genre imposé : la console parle aussi d'Adrien.
CLOSENESS_FR = {social_c.STRANGER: "pas encore de lien", social_c.ACQUAINTANCE: "connaissance",
                social_c.FRIEND: "amitié", social_c.CLOSE: "proche"}
EVIDENCE_FR = {"self_declared": "affirmation", c.SHARED_MEMORY: "souvenir partagé recoupé (seconde preuve)",
               c.SHARED_HINT: "souvenir partagé recoupé (première preuve)", c.DENIED: "démenti",
               c.CONTRADICTED: "contredit", c.REVOKED: "liaison oubliée", c.VOUCHED: "un opérateur s'en porte garant",
               "passive_inference": "indice passif", "authenticated": "session authentifiée"}
VIA_FR = {c.VIA_CORROBORATED: "recoupement (pas encore confirmé)", c.VIA_OPERATOR: "opérateur",
          c.VIA_VOUCHED: "garantie d'un opérateur"}
BY_FR = {"kernel": "le noyau", "tool": "elle (outil)", "operator": "un opérateur"}
#: Un texte du registre que l'oubli a effacé.
FORGOTTEN = "(oublié)"


def number(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def certainty_fr(value: float, *, bound: bool = True) -> str:
    """Une certitude et son degré. Pour une adresse qui parle pour elle-même, le
    degré dit ce que prouve son canal — jamais « liée » : elle n'est liée à personne."""
    name = privacy.certainty_name(value)
    if not bound and name in ("bound", "corroborated"):
        return f"{number(value)} (sûre du compte)"
    return f"{number(value)} ({CERTAINTY_FR.get(name, '?')})"


def view_certainty(view: c.IdentityView) -> str:
    """La certitude d'une adresse, dite comme il faut selon qu'elle est liée ou non."""
    return certainty_fr(view.certainty, bound=view.bound)


def disclosure_fr(d: Disclosure) -> str:
    return f"{LEVEL_FR.get(d.level, '?')} · sa fiche {'ouverte' if d.own_file else 'fermée'}"


def person_ref(s: IdentityState, person: str, tab: str = "") -> Ref:
    return Ref.subject("person", person, known_as(s, person), tab)


def handle_ref(s: IdentityState, handle: str, tab: str = "") -> Ref:
    return Ref.subject("handle", handle, handle_label(s, handle), tab)


def _reach_fr(h: Handle) -> str:
    """Peut-elle lui écrire d'elle-même, quand la personne n'est pas là ?"""
    if not h.push:
        return "non"
    return "oui (l'application du téléphone)" if h.channel == privacy.MOBILE else "oui (conversation privée)"


def kind_of(h: Handle) -> str:
    """Par où, en mots (un compte, un compte extérieur, le web…) : jamais la clé brute."""
    if h.authenticated:
        kind = "compte opérateur" if h.operator else "compte"
        return f"{kind} · téléphone" if h.channel == privacy.MOBILE else kind
    return "compte extérieur" if h.channel == privacy.EXTERNAL else (h.channel or "inconnu")


def handle_label(s: IdentityState, key: str) -> str:
    """Une adresse telle qu'on la lit : le nom sous lequel elle la connaît, et par où
    (« adrien · compte »). La clé (``user_1``) ne change jamais, même quand le nom change :
    elle reste sur la fiche et en colonne de détail, pas en titre."""
    h = s.handles.get(key)
    if h is None:
        return key
    name = h.name or (known_as(s, h.person) if h.person else "")
    return f"{name} · {kind_of(h)}" if name else f"{kind_of(h)}, sans nom"


def _stance(frame: Frame, handle: str, person: str) -> tuple[str, float]:
    """Proximité et chaleur, lues comme le fait ``DISCLOSURE`` (rien pour une
    adresse jetable)."""
    if not is_identifiable(handle):
        return "", 0.0
    return frame.get(social_c.CLOSENESS(person)), frame.get(affect_c.WARMTH(person))


def _disclosures(frame: Frame, handle: str, h: Handle) -> tuple[Disclosure, Disclosure]:
    return (frame.get(c.DISCLOSURE((handle, h.channel, False))),
            frame.get(c.DISCLOSURE((handle, h.channel, True))))


def _declared_owners(frame: Frame) -> tuple[str, ...]:
    return _params(frame.env.params_of("identity", frame.root)).owners


def people(s: IdentityState, frame: Frame) -> dict[str, tuple[str, ...]]:
    """Chaque personne connue et ses adresses (une adresse déclarée propriétaire qui
    n'a jamais écrit est une personne sans adresse)."""
    out: dict[str, tuple[str, ...]] = dict(s.by_person.items())
    for key in _declared_owners(frame):
        out.setdefault(_root(s, key), ())
    return out


def principal(s: IdentityState, person: str) -> str | None:
    """Son adresse principale : celle dont le canal prouve le plus (puis elle-même,
    puis la plus ancienne)."""
    known = [k for k in handles_of(s, person) if k in s.handles]
    if not known:
        return None
    return max(known, key=lambda k: (_TRUST_RANK[s.handles[k].trust], k == person, -s.handles[k].first_seen, k))


def _last_from(frame: Frame, handles: Sequence[str]) -> int:
    return max((frame.get(transcript_c.LAST_FROM(k)) for k in handles), default=0)


def _named_exists(ctx: InspectContext, key: str) -> bool:
    """Une personne connue seulement de nom existe si la mémoire en parle."""
    if len(key) <= len(NAMED) or ctx.store is None:
        return False
    rows = ctx.store.query_mind(f"SELECT 1 FROM {memory_c.ABOUT_TABLE} WHERE person=? LIMIT 1", (key,))
    return bool(rows)


def canonical(s: IdentityState, frame: Frame, ctx: InspectContext, key: str) -> str | None:
    """La clé de personne d'une clé ou d'une adresse ; ``None`` si inconnue."""
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
            return f"compte d'opérateur authentifié ({k})"
        if k in owners and (h is None or proves_owner(k, h, owners)):
            return f"adresse déclarée propriétaire ({k})"
    return ""


def name_aliases(s: IdentityState, person: str) -> tuple[str, ...]:
    """Les clés « connue seulement de nom » (``name:alice``) qui ne peuvent désigner
    qu'elle : un nom qu'aucune autre personne connue ne porte. Oublier la personne
    les oublie aussi ; un homonyme les garde (on ne sait pas de qui on parlait)."""
    names = {known_as(s, person)} | {s.handles[k].name for k in handles_of(s, person) if k in s.handles}
    others = [fold(known_as(s, p)) for p in s.by_person.keys() if p != person]
    out: set[str] = set()
    for name in names:
        folded = " ".join(fold(name).split())
        if not folded or folded.startswith(NAMED):
            continue
        first = folded.split()[0]
        # le nom complet : personne d'autre ne le porte (ni un prénom seul qui pourrait être lui)
        if not any(o == folded or o == first for o in others):
            out.add(f"{NAMED}{folded}")
        # le prénom : personne d'autre n'a ce prénom
        if not any(o.split()[:1] == [first] for o in others if o):
            out.add(f"{NAMED}{first}")
    # les noms qu'un opérateur lui a reliés (« l'Alice dont Bob parlait », c'était elle) : à elle, sans conteste
    out |= {k for k, p in s.names.items() if p == person}
    return tuple(sorted(out))


# ── Les noms qui attendent quelqu'un ──────────────────────────────────────

#: le paramètre de la fiche d'une personne qui y pose le formulaire « C'est la personne dont on lui a parlé »,
#: pré-rempli de ce nom (``?nom=name:carol``)
NAMING_PARAM = "nom"
#: l'action « Ce n'est pas elle » (``actions.py``)
DISMISS = "identity.ecarter_nom"
#: la borne haute des clés « connue seulement de nom » : ``name:`` ≤ clé < ``name;`` (l'index par personne de la
#: mémoire se lit par plage)
_NAMED_END = "name;"
#: ce qu'un nom rattache à une personne : souvenirs, croyances, moments de sa vie
NAMED_KINDS = (memory_c.SOUVENIR, memory_c.BELIEF, memory_c.EVENT)
_KINDS_FR = {memory_c.SOUVENIR: ("souvenir", "souvenirs"), memory_c.BELIEF: ("croyance", "croyances"),
             memory_c.EVENT: ("moment de sa vie", "moments de sa vie")}
_SENSITIVITY_FR = {Sensitivity.NONE: ("sans rien sur autrui", "sans rien sur autrui"),
                   Sensitivity.ANODYNE: ("anodin", "anodins"), Sensitivity.PERSONAL: ("personnel", "personnels"),
                   Sensitivity.CONFIDENCE: ("confidence", "confidences")}


@dataclass(frozen=True, slots=True)
class Waiting:
    """Un nom dont on lui a parlé, encore libre (``name:carol``), et une personne connue qui le porte."""

    name: str
    person: str
    #: les autres personnes connues qui le portent aussi
    homonyms: tuple[str, ...] = ()


def _worn(s: IdentityState) -> dict[str, list[tuple[str, tuple[str, ...]]]]:
    """Les noms que portent les personnes connues (le sien, ceux de ses adresses), repliés comme la mémoire forme
    ses clés, rangés par premier mot."""
    out: dict[str, list[tuple[str, tuple[str, ...]]]] = {}
    for person in s.by_person.keys():
        if person.startswith(NAMED) or not is_identifiable(person):
            continue
        names = {_name_of(s, person)} | {s.handles[k].name for k in handles_of(s, person) if k in s.handles}
        for words in sorted({tuple(fold(n).split()) for n in names if n}):
            if words:
                out.setdefault(words[0], []).append((person, words))
    return out


def bearers(s: IdentityState, key: str,
            worn: Mapping[str, list[tuple[str, tuple[str, ...]]]] | None = None) -> list[str]:
    """Les personnes connues qui portent ce nom : le nom complet, ou un prénom seul d'un côté (« Carol » et
    « Carol Dupont » s'accordent, « Carol Dupont » et « Carol Martin » non). Une suggestion, jamais une liaison :
    deux Carol ne se confondent pas d'elles-mêmes (ADR 0048)."""
    said = tuple(key[len(NAMED):].split()) if key.startswith(NAMED) else ()
    if not said:
        return []
    worn = _worn(s) if worn is None else worn
    return sorted({p for p, words in worn.get(said[0], ()) if words == said or len(words) == 1 or len(said) == 1})


def waiting_names(s: IdentityState, store: Any) -> list[Waiting]:
    """Les noms dont on lui a parlé, encore libres, qu'une personne connue porte : un couple par personne, sauf
    ceux qu'un opérateur a écartés ; les arrivées les plus récentes d'abord. Lu dans le magasin, en lecture seule
    (l'index par personne de la mémoire), jamais dans une autre faculté."""
    rows = store.query_mind(
        f"SELECT DISTINCT a.person FROM {memory_c.ABOUT_TABLE} a JOIN {memory_c.ITEMS_TABLE} i ON i.id = a.item "
        "WHERE a.person >= ? AND a.person < ? AND i.status='active' AND i.kind IN (?, ?, ?)",
        (NAMED, _NAMED_END, *NAMED_KINDS))
    free = sorted({str(k) for (k,) in rows} - set(s.names))
    if not free:
        return []
    worn = _worn(s)
    out: list[Waiting] = []
    for key in free:
        found = bearers(s, key, worn)
        gone = s.dismissed.get(key, ())
        out += [Waiting(key, p, tuple(o for o in found if o != p)) for p in found if p not in gone]
    out.sort(key=lambda w: (-_first_seen(s, w.person, 0), w.name, w.person))
    return out


def naming_ref(s: IdentityState, name: str, person: str, text: str = "") -> Ref:
    """La fiche de la personne, le formulaire « C'est la personne dont on lui a parlé » pré-rempli de ce nom."""
    return Ref("subject", f"person/{person}", text or known_as(s, person),
               (("onglet", "synthese"), (NAMING_PARAM, name)))


def _named_items(store: Any, keys: Sequence[str]) -> dict[str, list[tuple[str, int, bool, tuple[str, ...], int]]]:
    """Ce que sa mémoire garde sous ces noms, par nom : (sorte, sensibilité, secret, qui le lui a confié, quand)."""
    if not keys:
        return {}
    marks = ",".join("?" * len(keys))
    rows = store.query_mind(
        f"SELECT a.person, i.kind, i.sensitivity, i.secret, i.told_by, i.born_at FROM {memory_c.ABOUT_TABLE} a "
        f"JOIN {memory_c.ITEMS_TABLE} i ON i.id = a.item WHERE a.person IN ({marks}) AND i.status='active' "
        "AND i.kind IN (?, ?, ?)", (*keys, *NAMED_KINDS))
    out: dict[str, list[tuple[str, int, bool, tuple[str, ...], int]]] = {}
    for key, kind, sensitivity, secret, told_by, born_at in rows:
        try:
            told = tuple(str(h) for h in json.loads(told_by or "[]") if h)
        except (TypeError, ValueError):
            told = ()
        out.setdefault(str(key), []).append((str(kind), int(sensitivity), bool(secret), told, int(born_at)))
    return out


def _counted(n: int, words: tuple[str, str]) -> str:
    return f"{n} {words[0] if n == 1 else words[1]}"


def _told(s: IdentityState, ctx: InspectContext, items: Sequence[tuple[str, int, bool, tuple[str, ...], int]]) -> str:
    """Qui lui en a parlé, combien, depuis quand (« Alice, 3 éléments, depuis … »)."""
    by: dict[str, list[int]] = {}
    for _kind, _level, _secret, told, at in items:
        for who in {_root(s, h) for h in told} or {""}:
            by.setdefault(who, []).append(at)
    return " ; ".join(
        f"{known_as(s, who) if who else 'elle-même (vécu, observé)'}, {_counted(len(ats), ('élément', 'éléments'))}, "
        f"depuis {_when(ctx, min(ats))}" for who, ats in sorted(by.items(), key=lambda kv: (-len(kv[1]), kv[0]))) \
        or "—"


def _what(items: Sequence[tuple[str, int, bool, tuple[str, ...], int]]) -> str:
    kinds = Counter(item[0] for item in items)
    return " · ".join(_counted(kinds[k], _KINDS_FR[k]) for k in NAMED_KINDS if kinds[k]) or "—"


def _how_sensitive(items: Sequence[tuple[str, int, bool, tuple[str, ...], int]]) -> str:
    levels = Counter(item[1] for item in items)
    out = " · ".join(_counted(n, _SENSITIVITY_FR.get(level, (str(level), str(level))))
                     for level, n in sorted(levels.items()))
    secrets = sum(1 for item in items if item[2])
    if secrets:
        out += f" (dont {_counted(secrets, ('secret', 'secrets'))} : un secret ne quitte jamais son confident)"
    return out or "—"


def _also(s: IdentityState, key: str, others: Sequence[str]) -> str:
    """Les homonymes, dits pour qu'un opérateur choisisse en connaissance de cause."""
    gone = s.dismissed.get(key, ())
    listed = ", ".join(f"{known_as(s, o)} ({_where(s, handles_of(s, o))}{', écartée' if o in gone else ''})"
                       for o in others[:5])
    return (f"Une autre personne qu'elle connaît porte aussi ce nom : {listed}. Rien ne dit de laquelle on lui "
            "parlait : choisis toi-même, sur la fiche de la bonne.")


def _closeness_fr(frame: Frame, person: str) -> str:
    if not is_identifiable(person):
        return "—"
    return CLOSENESS_FR.get(frame.get(social_c.CLOSENESS(person)), CLOSENESS_FR[social_c.STRANGER])


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
        subtitle += " · propriétaire" if owner else ""
        subtitle += f" — connue depuis {ctx.when(first)}" if first else ""
    badges: list[Badge] = []
    if owner:
        badges.append(Badge("propriétaire", "info"))
    badges.append(Badge(f"liée · {len(handles)} adresses", "ok") if len(handles) > 1 else Badge("non liée", "muted"))
    facts: list[tuple[str, Cell]] = [("adresses", len(handles))]
    if main is not None:
        h = s.handles[main]
        view = view_of(s, main, frame.now)
        private, _public = _disclosures(frame, main, h)
        badges.append(Badge(f"en privé : {LEVEL_FR.get(private.level, '?')}", LEVEL_TONE.get(private.level, "")))
        facts += [("canal principal", f"{h.channel or '—'} · {TRUST_SHORT[h.trust]}"),
                  ("certitude", view_certainty(view))]
    if not is_identifiable(person):
        badges.append(Badge("jetable", "muted"))
    facts += [("proximité", relation), ("vue pour la première fois", _when(ctx, first, "—")),
              ("dernier message reçu", _when(ctx, _last_from(frame, handles)))]
    # ses adresses, et les noms qui ne désignent qu'elle : oublier la personne les oublie tous
    aliases = (*handles, *(n for n in name_aliases(s, person) if n not in handles))
    return Head(person, known_as(s, person), subtitle, tuple(badges), tuple(facts[:6]), aliases)


@IDENTITY.search("person")
def _search_people(s: IdentityState, frame: Frame, ctx: InspectContext, text: str, limit: int) -> list[Found]:
    q = fold(text)
    found: list[tuple[int, str, Found]] = []
    for person, handles in people(s, frame).items():
        name = known_as(s, person)
        if q and q not in fold(name) and q not in fold(person) and not any(q in fold(k) for k in handles):
            continue
        found.append((_last_from(frame, handles), person, Found(person, name, _where(s, handles))))
    found.sort(key=lambda x: (-x[0], x[1]))
    offset = max(0, ctx.int_param("_offset", 0))
    return [f for _last, _key, f in found[offset:offset + limit]]


def _where(s: IdentityState, handles: Sequence[str]) -> str:
    """Par où on la connaît, en mots (un compte, un compte extérieur…) : ce qui distingue deux homonymes sans
    montrer de clé brute."""
    words: list[str] = []
    for key in handles:
        h = s.handles.get(key)
        if h is None:
            continue
        word = kind_of(h)
        if word not in words:
            words.append(word)
    return " · ".join(words) or "déclarée (sans adresse vue)"


@IDENTITY.subject("handle", label="Adresse", plural="Adresses", icon="◎")
def _handle_head(s: IdentityState, frame: Frame, ctx: InspectContext, key: str) -> Head | None:
    h = s.handles.get(key.strip())
    if h is None:
        return None
    handle = key.strip()
    view = view_of(s, handle, frame.now)
    if view.bound:
        subtitle = f"Parle pour {known_as(s, view.person)} (liée par {VIA_FR.get(h.via, h.via or '?')})."
    elif view.name:
        subtitle = f"Parle pour {view.name}, et n'est reliée à personne d'autre."
    else:
        subtitle = "Reliée à personne : rien ne dit encore qui écrit d'ici."
    badges = [Badge(TRUST_SHORT[h.trust], TRUST_TONE[h.trust]),
              Badge(f"certitude {view_certainty(view)}",
                    "ok" if view.certainty >= privacy.POLICY.private_threshold else "muted"),
              Badge("liée", "ok") if view.bound else Badge("non liée", "muted")]
    if view.claim:
        badges.append(Badge(f"revendique « {view.claim} »", "warn"))
    if frame.get(c.SPEAKS_AS_OWNER(handle)):
        badges.append(Badge("droits de propriétaire", "info"))
    elif frame.get(c.IS_OWNER(view.person)):
        badges.append(Badge("propriétaire, sans ses droits ici", "warn"))
    if view.bound and view.via == c.VIA_CORROBORATED:
        badges.append(Badge("liaison à confirmer", "warn"))
    if not is_identifiable(handle):
        badges.append(Badge("jetable", "muted"))
    facts: tuple[tuple[str, Cell], ...] = (
        ("canal", h.channel or "—"), ("clé", Text(handle, "mono")),
        ("parle pour", person_ref(s, view.person)),
        ("vue pour la première fois", _when(ctx, h.first_seen, "—")),
        ("dernier message reçu", _when(ctx, frame.get(transcript_c.LAST_FROM(handle)))),
        ("joignable d'elle-même", _reach_fr(h)),
    )
    return Head(handle, handle_label(s, handle), subtitle, tuple(badges), facts)


@IDENTITY.search("handle")
def _search_handles(s: IdentityState, frame: Frame, ctx: InspectContext, text: str, limit: int) -> list[Found]:
    q = fold(text)
    ordered = sorted(s.handles.items(), key=lambda kv: (-kv[1].first_seen, kv[0]))
    out: list[Found] = []
    skip = max(0, ctx.int_param("_offset", 0))
    for key, h in ordered:
        if q and q not in fold(key) and q not in fold(h.name):
            continue
        if skip:
            skip -= 1
            continue
        out.append(Found(key, handle_label(s, key), f"{key} · {TRUST_SHORT[h.trust]}"))
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
        return privacy.CEILINGS[h.trust], "reliée à personne d'autre, et un compte stable prouve sa continuité"
    return 0.0, "reliée à personne d'autre, mais rien ne prouve la continuité de qui écrit"


def _steps(h: Handle, effective: float) -> list[tuple[str, str, str]]:
    stored, why = _stored(h)
    floor, ceiling = privacy.FLOORS[h.trust], privacy.CEILINGS[h.trust]
    raised = max(stored, floor)
    capped = min(raised, ceiling)
    bound = bool(h.person)
    steps = [("certitude enregistrée", certainty_fr(stored, bound=bound), why),
             ("plancher du canal", number(floor),
              f"relevée de {number(stored)} à {number(raised)}" if raised > stored else "déjà au-dessus : inchangée"),
             ("plafond du canal", number(ceiling),
              f"le plafond mord : {number(raised)} ramenée à {number(capped)}" if capped < raised
              else "sous le plafond : inchangée"),
             ("certitude effective", certainty_fr(effective, bound=bound), "celle qui vaut sur ce canal")]
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
    link = (f"pour elle, {CLOSENESS_FR.get(closeness, closeness or CLOSENESS_FR[social_c.STRANGER])} ; "
            f"chaleur {number(warmth)}")
    warm = warmth >= pol.warmth_min and rank >= privacy.CLOSENESS_RANK[social_c.ACQUAINTANCE]
    if not (rank >= privacy.CLOSENESS_RANK[social_c.FRIEND] or warm):
        return (f"aucun lien assez fort ({link}) : anodin — une amitié, un lien proche, ou une connaissance pour "
                f"qui elle a une chaleur d'au moins {number(pol.warmth_min)} ouvrirait le personnel")
    if certainty >= pol.confidence_threshold and rank >= privacy.CLOSENESS_RANK[social_c.CLOSE]:
        return (f"un lien proche, et une certitude d'au moins {number(pol.confidence_threshold)} ({link}) : le "
                "personnel sur autrui ; jusqu'aux confidences d'une personne qu'elle connaît (elles se sont parlé "
                "ensemble, ou cette personne l'a nommée) — être proche d'elle ne suffit pas")
    return (f"un lien ({link}) ouvre le personnel ; les confidences demandent un lien proche et une certitude d'au "
            f"moins {number(pol.confidence_threshold)}")


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
                     LEVEL_FR.get(d.witness_level, "?"), LEVEL_FR.get(d.tied_level, "?"),
                     why_file(view.certainty, h.trust, public=audience_public)))
    return Table(("audience", "sur autrui", "pourquoi", "si la personne est concernée",
                  "sur quelqu'un qu'elle connaît", "sa propre fiche"), tuple(rows), title="Ce que ça ouvre")


def _verdict(frame: Frame, handle: str, h: Handle, view: c.IdentityView) -> list[Block]:
    return [Table(("étape", "valeur", "pourquoi"), tuple(_steps(h, view.certainty)), title="Le verdict, pas à pas"),
            _opens(frame, handle, h, view)]


def _owner_here(s: IdentityState, frame: Frame, handle: str, h: Handle, person: str) -> str:
    """Les droits de propriétaire de qui écrit par cette adresse, et pourquoi (ou pourquoi pas)."""
    if not frame.get(c.IS_OWNER(person)):
        return "non"
    why = _why_owner(s, frame, person) or "par une autre de ses adresses"
    if frame.get(c.SPEAKS_AS_OWNER(handle)):
        how = "" if not h.person else " ; un opérateur a relié cette adresse"
        return f"oui — {why}{how} (jamais dans un salon public)"
    if h.trust not in (ChannelTrust.ACCOUNT, ChannelTrust.AUTHENTICATED):
        return f"la personne l'est ({why}), mais rien ne prouve qui écrit d'ici : pas ses droits"
    return (f"la personne l'est ({why}), mais cette adresse a été reliée par "
            f"{VIA_FR.get(h.via, h.via or '?')} : pas ses droits tant qu'un opérateur ne l'a pas reliée")


def _handle_fields(s: IdentityState, frame: Frame, handle: str, h: Handle, view: c.IdentityView) -> Fields:
    return Fields((
        ("clé", Text(handle, "mono")), ("nom", view.name or "—"), ("canal", h.channel or "—"),
        ("confiance du canal", TRUST_FR.get(h.trust, str(h.trust))),
        ("vue pour la première fois", When(h.first_seen) if h.first_seen else "—"),
        ("connue depuis (toutes adresses)", When(view.first_seen) if view.first_seen else "—"),
        ("compte authentifié", "oui" if h.authenticated else "non"),
        ("joignable d'elle-même", _reach_fr(h)),
        ("parle pour", person_ref(s, view.person)),
        ("droits de propriétaire", _owner_here(s, frame, handle, h, view.person)),
        ("jetable", "non" if is_identifiable(handle) else "oui : aucune mémoire durable ne s'y attache"),
    ), title="L'adresse", columns=2)


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
        ("premières preuves de recoupement",
         ", ".join(f"élément n°{x.item}{' (détail rare)' if x.rare else ''}" for x in claim.hints) or "aucune"),
        ("depuis", When(claim.at)),
        ("s'éteint", When(claim.at + ttl) if view.claim else "déjà éteinte"),
        ("état", "active" if view.claim else "éteinte (jamais confirmée à temps)"),
    ), title="Revendication en cours", columns=2)]
    if view.claim and claim.target and claim.target != view.handle:
        missing = max(0.0, bar - certainty)
        blocks.append(Note(
            f"Il manque {number(missing)} pour atteindre la barre. Ce qui peut la confirmer : ce que seule "
            f"{known_as(s, claim.target)} pouvait savoir, recoupé sur deux messages différents (jamais celui où "
            f"la personne se présente), dont un avec un détail rare — un nom propre, un nombre, une date "
            f"(+{number(privacy.EVIDENCE[c.SHARED_MEMORY])}) ; un opérateur qui s'en porte garant "
            f"(+{number(privacy.EVIDENCE[c.VOUCHED])}) ; ou qui relie directement cette adresse (certitude "
            f"{number(privacy.BOUND)}). Le plafond du canal reste {number(privacy.CEILINGS[h.trust])}. Une liaison "
            "par recoupement reste « à confirmer » : le fil des autres adresses lui reste fermé tant qu'un opérateur "
            "ne l'a pas confirmée.", title="Pour la confirmer"))
    elif view.claim and claim.target == view.handle:
        blocks.append(Note(f"Elle se donne un autre nom que celui sous lequel elle la connaît : rien ne change tant "
                           f"que rien ne le confirme (« {claim.name} » ne délie ni ne renomme cette adresse).",
                           tone="muted", title="Un autre nom"))
    return blocks


def _describe_event(e: Event[Any], s: IdentityState) -> tuple[str, str]:
    data = e.data
    if e.type.name == c.CLAIMED.name:
        target = data.target
        if target is None:
            aim = "plusieurs personnes portent ce nom"
        elif target == data.handle:
            aim = "personne d'autre ne le porte : la personne se présente"
        else:
            aim = f"vise {known_as(s, str(target))}"
        where = " (en public)" if data.public else ""
        return "revendication", f"« {data.name} » — {aim}{where}"
    if e.type.name == c.EVIDENCE.name:
        kind = str(data.kind)
        weight = privacy.EVIDENCE.get(kind, privacy.COUNTER_EVIDENCE.get(kind, 0.0))
        detail = f"{EVIDENCE_FR.get(kind, kind)} ({'+' if weight >= 0 else ''}{number(weight)})"
        name = _said(data.name, data.legacy_name)
        if name:
            detail += f" — nom « {name} »" if name != FORGOTTEN else f" — nom {FORGOTTEN}"
        if data.item is not None:
            detail += f" — élément de mémoire n°{data.item}" + (" (détail rare)" if data.rare else "")
        note = _said(data.note, data.legacy_note)
        if note:
            detail += f" — {note}"
        return "preuve", detail
    person = data.person
    if person is None or person == data.handle:
        return "liaison", "déliée"
    return "liaison", f"reliée à {known_as(s, str(person))}"


_KIND_TONE = {"revendication": "warn", "preuve": "info", "liaison": "ok"}


def _said(content: Any, legacy: str = "") -> str:
    """Un texte du registre : gardé à part (« (oublié) » une fois oublié), ou en clair
    pour une preuve d'avant la version 2."""
    if content is None:
        return legacy
    text = getattr(content, "text", None)
    return text if text is not None else FORGOTTEN


def _ledger(s: IdentityState, handle: str, ctx: InspectContext) -> Block:
    """Le registre des raisons de croire (ou de ne plus croire), relu au
    journal. Le nom démenti et la note sont gardés à part : oubliés, ils se
    lisent « (oublié) ». L'opérateur qui a agi est lu dans l'audit de la console.
    On lit une ligne de plus que la page : « plus anciens » n'est offert que s'il
    en reste vraiment."""
    if ctx.journal is None:
        return Note("Le magasin n'est pas disponible : le registre des preuves ne peut pas être relu.", tone="muted")
    before = ctx.int_param("avant", 0) or None
    found = ctx.events((c.CLAIMED, c.EVIDENCE, c.LINKED), MAX_LEDGER + 1, where=("handle", handle), before=before)
    more = len(found) > MAX_LEDGER
    found = found[:MAX_LEDGER]
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
    pager = Pager(older=(("avant", str(found[-1].seq)),)) if more else Pager()
    return Table((Column("n°", "fit"), Column("quand", "fit"), "sorte", "détail", "par", "message"), tuple(rows),
                 title="Registre des preuves (les plus récentes d'abord)", pager=pager,
                 empty="aucune revendication, preuve ni liaison")


def _handles_table(s: IdentityState, frame: Frame, ctx: InspectContext, handles: Sequence[str], *, title: str,
                   empty: str) -> Table:
    """Ces adresses, toutes, par pages."""
    page, pager = paginate([k for k in handles if k in s.handles], ctx.pager(HANDLES_PAGE, size=PAGE))
    rows = []
    for k in page:
        o = s.handles[k]
        view = view_of(s, k, frame.now)
        rows.append(Row((handle_ref(s, k), o.channel or "—", Badge(TRUST_SHORT[o.trust], TRUST_TONE[o.trust]),
                         view_certainty(view), "non liée" if not o.person else VIA_FR.get(o.via, o.via or "?"),
                         f"« {view.claim} »" if view.claim else "—",
                         When(o.first_seen) if o.first_seen else "—",
                         When(last) if (last := frame.get(transcript_c.LAST_FROM(k))) else "jamais",
                         Text(k, "mono")),
                        href=handle_ref(s, k)))
    return Table(("adresse", "canal", "confiance", Column("certitude", detail=True),
                  Column("liée par", detail=True), Column("revendique", detail=True),
                  Column("vue pour la première fois", detail=True), "dernier message", Column("clé", detail=True)),
                 tuple(rows), title=title, empty=empty, pager=pager)


# ── Fiche d'une personne ──────────────────────────────────────────────────


def _person_of(s: IdentityState, frame: Frame, ctx: InspectContext) -> tuple[str | None, list[Block]]:
    key = ctx.subject or ctx.param("person")
    if not key:
        return None, [Note("Ouvre la fiche d'une personne : Personnes, puis la personne.", tone="muted")]
    person = canonical(s, frame, ctx, key)
    if person is None:
        return None, [Note(f"Personne inconnue : « {key} ».", tone="muted")]
    return person, []


def _naming(s: IdentityState, ctx: InspectContext, person: str) -> list[Block]:
    """Venue d'une ligne « Noms qui attendent quelqu'un » (``?nom=name:carol``) : le formulaire « C'est la personne
    dont on lui a parlé », pré-rempli de ce nom, avec la même confirmation ; « Ce n'est pas elle » à côté."""
    key = ctx.param(NAMING_PARAM)
    if not key.startswith(NAMED) or not _named_exists(ctx, key):
        return []
    said = known_as(s, key)
    current = s.names.get(key)
    if current == person:
        return [Note(f"« {said} », dont on lui avait parlé, c'est {known_as(s, person)} : ce qu'on lui en a dit s'y "
                     "rattache.", tone="ok")]
    items: list[Block] = []
    if current:
        items.append(Note(f"« {said} » désigne aujourd'hui {known_as(s, current)} : le relier ici l'en détache.",
                          tone="warn"))
    others = [p for p in bearers(s, key) if p != person]
    if others:
        items.append(Note(_also(s, key, others), tone="warn"))
    dismissed = person in s.dismissed.get(key, ())
    if dismissed:
        items.append(Note("Un opérateur a dit que ce n'était pas elle : la console ne le propose plus. Le relier "
                          "reste possible.", tone="muted"))
    items.append(ActionSlot("identity.nommer", (("name", said),), title="C'est la personne dont on lui a parlé"))
    if not dismissed:
        items.append(Toolbar((ActionSlot(DISMISS, (("name", key), ("person", person)), title="Ce n'est pas elle",
                                         presentation="button"),), title="Sinon"))
    return [Section(f"« {said} », dont on lui a parlé", tuple(items), description=(
        f"Quelqu'un lui a parlé d'une « {said} » avant de connaître {known_as(s, person)}. Si c'est elle, ce qu'on lui "
        "en a dit s'y rattache — chacun garde qui le lui a confié, et ce qui ne se répète pas reste tu. Rien n'est "
        "relié tant que tu n'as pas confirmé."))]


def _bearing(s: IdentityState, key: str) -> list[Block]:
    """Sur la fiche d'un nom : la personne qu'un opérateur lui a reliée, ou celles qu'elle connaît qui le portent
    (une suggestion : la fiche de chacune permet de le relier)."""
    current = s.names.get(key)
    if current:
        return [Fields((("c'était", person_ref(s, current)),), title="Relié par un opérateur")]
    gone = s.dismissed.get(key, ())
    rows = []
    for p in bearers(s, key):
        first = _first_seen(s, p, 0)
        rows.append(Row((person_ref(s, p), _where(s, handles_of(s, p)), When(first) if first else "—",
                         Badge("écartée", "muted") if p in gone else Badge("à décider", "warn")),
                        href=naming_ref(s, key, p)))
    return [Table(("personne", "par où", "vue pour la première fois", "suggestion"), tuple(rows),
                  title="Qui porte ce nom", empty="personne qu'elle connaisse ne porte ce nom",
                  caption="Jamais relié d'une ressemblance de nom : une ligne mène à la fiche de la personne, où un "
                          "opérateur le relie (ou l'écarte).")]


@IDENTITY.inspect("synthese", title="Synthèse", subject="person", order=10,
                  description="Qui c'est, à quel point elle en est sûre, et ce qu'elle peut lui dire.")
def _synthesis(s: IdentityState, frame: Frame, ctx: InspectContext) -> list[Block]:
    person, blocks = _person_of(s, frame, ctx)
    if person is None:
        return blocks
    if person.startswith(NAMED):
        return [Note("Connue seulement de nom : quelqu'un lui a parlé d'elle, mais elle ne lui a jamais écrit. "
                     "Ce qu'elle en sait est dans sa mémoire.", tone="muted"),
                Fields((("nom", known_as(s, person)), ("clé", Text(person, "mono")))), *_bearing(s, person)]
    blocks += _naming(s, ctx, person)
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
         else "non : il faut que la personne écrive d'abord"),
    ), title="Qui", columns=2))
    main = principal(s, person)
    if main is None:
        blocks.append(Note("Aucune adresse connue : adresse déclarée propriétaire, qui n'a encore jamais écrit.",
                           tone="muted"))
        return blocks
    h = s.handles[main]
    view = view_of(s, main, frame.now)
    blocks.append(Section("Ce qu'elle peut lui dire", (
        Fields((("adresse principale", handle_ref(s, main)), ("canal", f"{h.channel or '—'} · {TRUST_FR[h.trust]}"),
                ("certitude effective", view_certainty(view)),
                ("barre de divulgation", number(privacy.POLICY.private_threshold))), columns=2),
        _opens(frame, main, h, view),
    ), description="Sur son adresse principale (celle dont le canal prouve le plus). Chaque adresse a son verdict "
                   "pas à pas sur sa fiche."))
    # la liste des adresses vit dans l'onglet « Adresses » : ici, un renvoi (pas deux fois la même table)
    blocks.append(Fields((("ses adresses", Ref.subject("person", person, f"{len(handles)} adresse(s) : voir l'onglet "
                                                                          "Adresses", "adresses")),),
                         title="Ses adresses"))
    return blocks


@IDENTITY.inspect("adresses", title="Adresses", subject="person", order=20,
                  description="Les adresses qui parlent pour cette personne, et comment elles ont été reliées.")
def _person_handles(s: IdentityState, frame: Frame, ctx: InspectContext) -> list[Block]:
    person, blocks = _person_of(s, frame, ctx)
    if person is None:
        return blocks
    handles = handles_of(s, person)
    bound = sum(1 for k in handles if s.handles[k].person)
    blocks += [
        Stats((Stat("adresses", len(handles)), Stat("reliées à elle", bound, "par recoupement ou par un opérateur"),
               Stat("revendications en attente", sum(1 for k in handles if view_of(s, k, frame.now).claim)))),
        _handles_table(s, frame, ctx, handles, title="Ses adresses", empty="aucune adresse connue"),
        Note(f"Pour relier une autre adresse à cette personne : ouvre la fiche de l'adresse, puis « Relier », "
             f"et indique « {person} ».", tone="muted"),
    ]
    return blocks


# ── Fiche d'une adresse ───────────────────────────────────────────────────


def _handle_of(s: IdentityState, ctx: InspectContext) -> tuple[str, Handle | None, list[Block]]:
    handle = ctx.subject or ctx.param("handle")
    if not handle:
        return "", None, [Note("Ouvre la fiche d'une adresse : Identités, puis l'adresse.", tone="muted")]
    h = s.handles.get(handle)
    if h is None:
        return handle, None, [Note(f"Adresse inconnue : « {handle} ». Elle n'a jamais été vue.", tone="muted")]
    return handle, h, []


@IDENTITY.inspect("verdict", title="Verdict", subject="handle", subject_param="handle", order=10,
                  description="Pourquoi cette adresse ouvre ce qu'elle ouvre, pas à pas.")
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


@IDENTITY.inspect("autres", title="Autres adresses", subject="handle", subject_param="handle", order=40,
                  description="Les autres adresses de la même personne.")
def _handle_others(s: IdentityState, frame: Frame, ctx: InspectContext) -> list[Block]:
    handle, h, blocks = _handle_of(s, ctx)
    if h is None:
        return blocks
    view = view_of(s, handle, frame.now)
    others = [k for k in handles_of(s, view.person) if k != handle]
    return [Fields((("personne", person_ref(s, view.person)),)),
            _handles_table(s, frame, ctx, others, title=f"Les autres adresses de {known_as(s, view.person)}",
                           empty="aucune autre adresse ne parle pour cette personne")]


# ── Les destinations ──────────────────────────────────────────────────────

SEARCH = Param("q", "nom ou adresse", placeholder="Alice, user_7…")
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
            view_certainty(view) if view else "—",
            Badge(CLOSENESS_FR.get(closeness, "—"), "info" if closeness in (social_c.FRIEND, social_c.CLOSE) else "")
            if closeness else "—",
            Badge("propriétaire", "info") if frame.get(c.IS_OWNER(person)) else "",
            When(last) if last else "jamais",
            When(first) if (first := _first_seen(s, person, 0)) else "—",
        ), href=person_ref(s, person)))
    return [
        Stats((Stat("personnes", len(everyone)),
               Stat("propriétaires", len(frame.get(c.OWNERS))),
               Stat("reliées à plusieurs adresses", sum(1 for hs in everyone.values() if len(hs) > 1)))),
        Table(("personne", Column("adresses", "num"), Column("canal principal", detail=True), Column("certitude", detail=True),
               "proximité", "propriétaire", "dernier message reçu", Column("vue pour la première fois", detail=True)),
              tuple(rows), title="Personnes", pager=pager,
              filters=("q",),
              empty=f"personne ne correspond à « {ctx.value('q')} »" if q else "personne pour l'instant"),
    ]


@IDENTITY.inspect("annuaire", title="Adresses", section="identites", order=10, params=[SEARCH, TRUSTS],
                  description="Chaque adresse vue, ce qu'elle prouve et ce qu'elle ouvre ; une ligne mène à sa fiche.")
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
            handle_ref(s, handle), h.channel or "—", Badge(TRUST_FR[h.trust], TRUST_TONE[h.trust]),
            view_certainty(view), person_ref(s, view.person),
            "oui" if frame.get(c.IS_OWNER(view.person)) else "non",
            f"« {view.claim} »" if view.claim else "—", disclosure_fr(private), disclosure_fr(public),
            When(h.first_seen) if h.first_seen else "—", Text(handle, "mono"),
        ), href=handle_ref(s, handle)))
    owners = ", ".join(known_as(s, p) for p in frame.get(c.OWNERS)) or "aucun"
    return [
        Stats((Stat("adresses connues", len(s.handles)),
               Stat("liées à une autre personne", sum(1 for h in s.handles.values() if h.person)),
               Stat("revendications en attente", len(pending_claims(s, frame.now)),
                    href=Ref.view("identity", "revendications", "revendications")),
               Stat("propriétaires", owners),
               Stat("barre de divulgation", number(privacy.POLICY.private_threshold),
                    href=Ref.view("identity", "politique", "politique")))),
        Table(("adresse", "canal", "confiance du canal", Column("certitude", detail=True), "parle pour",
               Column("propriétaire", detail=True), "revendique", Column("divulgation en privé", detail=True),
               Column("divulgation en public", detail=True), Column("vue pour la première fois", detail=True),
               Column("clé", detail=True)),
              tuple(rows), title="Adresses", pager=pager, filters=("q", "confiance"),
              empty="aucune adresse ne correspond" if q or trust else "aucune adresse vue pour l'instant"),
    ]


def pending_claims(s: IdentityState, now: int) -> list[tuple[str, Handle]]:
    """Les revendications en attente (pas encore éteintes), de la plus récente à la plus ancienne."""
    out = [(k, h) for k, h in s.handles.items() if h.claim is not None and view_of(s, k, now).claim]
    return sorted(out, key=lambda kv: (-(kv[1].claim.at if kv[1].claim else 0), kv[0]))


def _claims_badge(s: IdentityState, frame: Frame) -> int:
    return len(pending_claims(s, frame.now))


@IDENTITY.inspect("revendications", title="Revendications", section="identites", order=20, badge=_claims_badge,
                  description="Qui dit être quelqu'un d'autre, sans preuve encore : à confirmer, garantir ou "
                              "démentir depuis la fiche de l'adresse.")
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
            handle_ref(s, handle, tab="revendication"), f"« {claim.name} »",
            person_ref(s, claim.target) if claim.target else Text("plusieurs personnes portent ce nom", "muted"),
            Badge(TRUST_SHORT[h.trust], TRUST_TONE[h.trust]),
            Meter(certainty / bar if bar else 0.0, f"{number(certainty)} / {number(bar)}"),
            ", ".join(_used(u) for u in claim.used) or "—", When(claim.at), When(claim.at + ttl),
        ), href=handle_ref(s, handle, tab="revendication")))
    return [Table(("adresse", "nom revendiqué", "vise", "canal", "vers la barre", "preuves comptées", "depuis",
                   "s'éteint"), tuple(rows), title="Revendications en attente", pager=pager,
                  empty="aucune revendication en attente"),
            Note(f"Une affirmation seule ne franchit jamais la barre ({number(bar)}) ; une revendication jamais "
                 f"confirmée s'éteint au bout de {privacy.POLICY.pending_claim_ttl_days} jours.", tone="muted")]


def _names_badge(s: IdentityState, frame: Frame, ports: Mapping[str, Any]) -> tuple[int, str]:
    store = ports.get("store")
    if store is None:
        return 0, ""
    return len(waiting_names(s, store)), "nom(s) dont on lui a parlé que porte quelqu'un qu'elle connaît"


@IDENTITY.inspect("noms", title="Noms qui attendent quelqu'un", section="identites", order=25, badge=_names_badge,
                  description="On lui a parlé de quelqu'un avant de le connaître, et une personne qu'elle connaît "
                              "porte ce nom : à relier ou à écarter depuis la fiche de la personne. Rien n'est relié "
                              "d'une ressemblance de nom.")
def _waiting(s: IdentityState, frame: Frame, ctx: InspectContext) -> list[Block]:
    if ctx.store is None:
        return [Note("Le magasin n'est pas disponible : sa mémoire ne peut pas être relue.", tone="muted")]
    found = waiting_names(s, ctx.store)
    page, pager = paginate(found, ctx.pager(size=PAGE))
    items = _named_items(ctx.store, sorted({w.name for w in page}))
    rows = []
    for w in page:
        said, mine = known_as(s, w.name), items.get(w.name, [])
        first = _first_seen(s, w.person, 0)
        detail: list[Block] = [Note(_also(s, w.name, w.homonyms), tone="warn")] if w.homonyms else []
        detail += [Fields((("relier", naming_ref(s, w.name, w.person, f"la fiche de {known_as(s, w.person)}, le "
                                                                      "formulaire pré-rempli")),)),
                   Toolbar((ActionSlot(DISMISS, (("name", w.name), ("person", w.person)), title="Ce n'est pas elle",
                                       presentation="button"),),
                           title=f"« {said} » n'est pas {known_as(s, w.person)} ?")]
        rows.append(Row((
            f"« {said} »", _told(s, ctx, mine), _what(mine), _how_sensitive(mine), person_ref(s, w.person),
            _where(s, handles_of(s, w.person)), When(first) if first else "—",
            Badge("homonyme", "warn") if w.homonyms else "—",
        ), href=naming_ref(s, w.name, w.person), detail=tuple(detail)))
    return [
        Stats((Stat("noms qui attendent", len({w.name for w in found})),
               Stat("personnes proposées", len(found)),
               Stat("avec un homonyme", sum(1 for w in found if w.homonyms)))),
        Table(("nom dont on lui a parlé", "qui lui en a parlé", "ce qui attend", Column("sensibilité", detail=True),
               "personne qui le porte", Column("par où", detail=True), "vue pour la première fois", "homonyme"),
              tuple(rows), title="Noms qui attendent quelqu'un", pager=pager,
              empty="aucun nom dont on lui a parlé n'est porté par quelqu'un qu'elle connaît"),
        Note("Une ligne ne relie rien : elle mène à la fiche de la personne, où « C'est la personne dont on lui a "
             "parlé » est pré-rempli et demande ta confirmation. Ce qu'on lui en a dit s'y rattache alors — chacun "
             "garde qui le lui a confié. « Ce n'est pas elle » ne propose plus ce nom pour cette personne.",
             tone="muted"),
    ]


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
                ("en vigueur (comptes d'opérateur compris)", ", ".join(known_as(s, p) for p in frame.get(c.OWNERS))
                 or "aucun")), title="Propriétaires"),
    ]


@IDENTITY.inspect("personne", title="Une adresse (ancienne page)", hidden=True, params=[("handle", "adresse")])
def _legacy_person(s: IdentityState, frame: Frame, ctx: InspectContext) -> list[Block]:
    """L'ancienne page d'une adresse : ses liens mènent désormais aux fiches."""
    handle, h, blocks = _handle_of(s, ctx)
    if h is None:
        if not handle:
            return [Note("Choisissez une adresse dans la liste des adresses (paramètre « handle »).")]
        return blocks
    view = view_of(s, handle, frame.now)
    return [Fields((("fiche de l'adresse", handle_ref(s, handle)), ("fiche de la personne", person_ref(s, view.person))),
                   title="Cette page vit désormais sur les fiches"),
            _handle_fields(s, frame, handle, h, view), *_verdict(frame, handle, h, view),
            *_claim(s, h, view, ctx),
            _handles_table(s, frame, ctx, [k for k in handles_of(s, view.person) if k != handle],
                           title=f"Les autres adresses de {known_as(s, view.person)}",
                           empty="aucune autre adresse ne parle pour cette personne"),
            _ledger(s, handle, ctx)]
