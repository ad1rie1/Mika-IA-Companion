"""Ce qu'un opérateur peut faire des identités depuis la console : relier une
adresse à une personne, confirmer une liaison par recoupement, la délier,
verser une preuve au registre.

Chaque action rend des brouillons d'événements d'``identity`` (le moteur les
journalise comme venant de l'extérieur, avec l'audit qui nomme l'opérateur),
sous garde : la liaison que l'opérateur a vue n'a pas changé entre-temps. Une
action qui change la confiance annonce son issue — qui sera reconnue, qui en
recevra les droits de propriétaire — et demande qu'on la confirme. Une session
authentifiée prouve déjà qui écrit : on ne la relie à personne. Un refus se dit
champ par champ. Rien ici ne touche à sa mémoire.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from mika.contracts import identity as c
from mika.faculties.identity.faculty import (
    IDENTITY,
    Handle,
    IdentityState,
    _apply,
    _params,
    _root,
    denial_target,
    known_as,
    owner_person,
    view_of,
)
from mika.faculties.identity.inspect import certainty_fr, people
from mika.kernel.events import Content
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard
from mika.kernel.operate import ActionContext, Done, Refused
from mika.vocab import privacy
from mika.vocab.people import clean_display_name, fold, is_ephemeral, is_identifiable, is_internal, same_name

#: Les preuves qu'un opérateur peut verser (celles que le réducteur sait peser).
OPERATOR_EVIDENCE = (
    (c.VOUCHED, "je m'en porte garant (appuie sa revendication)"),
    (c.CONTRADICTED, "j'en doute (contredit sa liaison ou sa revendication)"),
    (c.DENIED, "ce n'est pas cette personne (démenti d'un nom)"),
)
NOTE_MAX = 200
CONFIRM_HELP = ("Exigé quand l'action change qui elle reconnaît ici : ce que la personne lui a confié s'ouvre (ou se "
                "referme), et parfois ses droits de propriétaire.")


def _handle(s: IdentityState, key: str) -> Handle | None:
    return s.handles.get(key) if key and not is_internal(key) else None


def _seen(handle: str) -> Guard:
    """L'opération ne vaut que si l'adresse est toujours dans l'état où l'opérateur l'a vue
    (sa personne, sa liaison, sa revendication, son nom)."""
    return Guard("adresse inchangée", reads=(c.PERSON(handle), c.IDENTITY(handle)))


def _declared(frame: Frame) -> frozenset[str]:
    return frozenset(_params(frame.env.params_of("identity", frame.root)).owners)


def _rights(s: IdentityState, frame: Frame, handle: str, h: Handle, person: str) -> str:
    """Ce qu'une liaison d'opérateur vers ``person`` donnerait de droits à qui écrit d'ici."""
    if not owner_person(s, person, _declared(frame)):
        return ""
    if h.trust is privacy.ChannelTrust.ACCOUNT:
        return (f" {known_as(s, person)} est propriétaire : qui écrit d'ici en recevra les droits (forge, caméra, "
                "courrier, projets…), hors des salons publics.")
    return (f" {known_as(s, person)} est propriétaire, mais rien ne prouve qui écrit d'ici : cette adresse n'en "
            "recevra pas les droits.")


# ── Relier ────────────────────────────────────────────────────────────────


class LinkArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    person: Annotated[str, Field(min_length=1, max_length=80), Knob(
        label="Personne", subject="person", advanced=False,
        help="Sa clé (user_7, tg_42…) ou le nom sous lequel elle la connaît.")]
    confirmed: Annotated[bool, Knob(label="Je confirme", advanced=False, help=CONFIRM_HELP)] = False


def _resolve(s: IdentityState, frame: Frame, text: str) -> str:
    """La personne que l'opérateur désigne : une clé connue (ou une adresse,
    ramenée à sa personne), sinon un nom qu'une seule personne porte."""
    text = text.strip()
    known = people(s, frame)
    if text in known or text in s.handles:
        person = _root(s, text)
    else:
        found = sorted(p for p in known if not p.startswith("name:") and same_name(text, known_as(s, p)))
        exact = [p for p in found if fold(known_as(s, p)) == fold(text)]
        found = exact if len(exact) == 1 else found
        if not found:
            raise Refused("Personne inconnue.", {"person": f"Aucune personne connue sous « {text} » (ni clé, ni nom)."})
        if len(found) > 1:
            listed = ", ".join(f"{known_as(s, p)} ({p})" for p in found[:5])
            raise Refused("Plusieurs personnes portent ce nom.",
                          {"person": f"Plusieurs personnes s'appellent ainsi : {listed}. Indique sa clé."})
        person = found[0]
    if is_internal(person) or is_ephemeral(person):
        raise Refused("Cette personne ne peut pas en porter d'autres.",
                      {"person": "Une connexion jetable ne peut pas porter une personne."})
    return person


def _can_link(s: IdentityState, frame: Frame, key: str) -> bool:
    h = _handle(s, key)
    return h is not None and is_identifiable(key) and not h.authenticated


@IDENTITY.action("relier", title="Relier à une personne", args=LinkArgs, emits=[c.LINKED], subject="handle",
                 description="Cette adresse parlera pour la personne choisie (certitude « liée ») : sa mémoire, "
                             "ses liens, sa fiche et son fil s'y attachent — et, sur un compte Telegram, les droits "
                             "d'une propriétaire. Jamais sur une session authentifiée : elle prouve déjà qui écrit.",
                 confirm="Relier cette adresse ? Elle recevra tout ce que la personne choisie lui a confié.",
                 available=_can_link, order=10)
def _link(s: IdentityState, frame: Frame, args: LinkArgs, ctx: ActionContext) -> Done:
    handle = ctx.subject
    h = _handle(s, handle)
    if h is None:
        raise Refused("Adresse inconnue.")
    if h.authenticated:
        raise Refused("Une session authentifiée prouve déjà qui écrit : on ne la relie à personne.")
    person = _resolve(s, frame, args.person)
    if person == handle:
        raise Refused("C'est elle-même.", {"person": "C'est déjà elle-même : choisis une autre personne."})
    if h.person == person and h.via == c.VIA_OPERATOR:
        raise Refused("Déjà reliée.", {"person": f"Cette adresse parle déjà pour {known_as(s, person)}."})
    followers = sorted(k for k, o in s.handles.items() if o.person == handle)
    if followers:
        raise Refused("D'autres adresses parlent pour elle.", {"person": (
            f"D'autres adresses parlent pour elle ({', '.join(followers[:5])}) : relie-les d'abord à "
            f"{known_as(s, person)}, ou délie-les.")})
    outcome = f"« {handle} » parlera pour {known_as(s, person)} : ce que cette personne lui a confié s'y ouvre." + \
        _rights(s, frame, handle, h, person)
    if not args.confirmed:
        raise Refused(f"À confirmer : {outcome}", {"confirmed": f"{outcome} Coche « Je confirme »."})
    done = f"« {handle} » parle désormais pour {known_as(s, person)}."
    if owner_person(s, person, _declared(frame)) and h.trust is privacy.ChannelTrust.ACCOUNT:
        done += " Qui écrit d'ici en a les droits de propriétaire."
    return Done(drafts=(c.LINKED.draft(handle=handle, person=person, by="operator"),), message=done,
                guard=_seen(handle))


# ── Confirmer une liaison par recoupement ─────────────────────────────────


class ConfirmArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed: Annotated[bool, Knob(label="Je confirme", advanced=False, help=CONFIRM_HELP)] = False


def _can_confirm(s: IdentityState, frame: Frame, key: str) -> bool:
    h = _handle(s, key)
    return h is not None and bool(h.person) and h.via not in c.CONFIRMED_VIA and not h.authenticated


@IDENTITY.action("confirmer", title="Confirmer la liaison", args=ConfirmArgs, emits=[c.LINKED], subject="handle",
                 description="Elle a reconnu cette personne par ce qu'elle seule savait ; tant qu'un opérateur ne "
                             "l'a pas confirmé, son fil des autres adresses lui reste fermé et elle ne lui écrit pas "
                             "d'elle-même par ici.",
                 confirm="Confirmer cette liaison ? Le fil de ses autres adresses s'y ouvre.",
                 available=_can_confirm, order=15)
def _confirm(s: IdentityState, frame: Frame, args: ConfirmArgs, ctx: ActionContext) -> Done:
    handle = ctx.subject
    h = _handle(s, handle)
    if h is None or not h.person or h.via in c.CONFIRMED_VIA:
        raise Refused("Aucune liaison à confirmer sur cette adresse.")
    outcome = (f"« {handle} » est bien {known_as(s, h.person)} : son fil des autres adresses s'y ouvre, et elle "
               "pourra lui écrire d'elle-même par ici." + _rights(s, frame, handle, h, h.person))
    if not args.confirmed:
        raise Refused(f"À confirmer : {outcome}", {"confirmed": f"{outcome} Coche « Je confirme »."})
    return Done(drafts=(c.LINKED.draft(handle=handle, person=h.person, by="operator"),),
                message=f"Liaison confirmée : « {handle} » parle pour {known_as(s, h.person)}.", guard=_seen(handle))


# ── Délier ────────────────────────────────────────────────────────────────


class NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _can_unlink(s: IdentityState, frame: Frame, key: str) -> bool:
    h = _handle(s, key)
    return h is not None and bool(h.person)


@IDENTITY.action("delier", title="Délier", args=NoArgs, emits=[c.LINKED], subject="handle",
                 description="Cette adresse ne parlera plus que pour elle-même ; sa revendication éventuelle "
                             "tombe aussi.",
                 confirm="Délier cette adresse ? Ce que la personne lui avait confié se referme (et ses droits de "
                         "propriétaire, s'il en avait).",
                 available=_can_unlink, order=20)
def _unlink(s: IdentityState, frame: Frame, args: NoArgs, ctx: ActionContext) -> Done:
    handle = ctx.subject
    h = _handle(s, handle)
    if h is None or not h.person:
        raise Refused("Cette adresse n'est reliée à personne d'autre qu'elle-même.")
    return Done(drafts=(c.LINKED.draft(handle=handle, person=None, by="operator"),),
                message=f"« {handle} » ne parle plus pour {known_as(s, h.person)}.", guard=_seen(handle))


# ── Verser une preuve ─────────────────────────────────────────────────────


class EvidenceArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Annotated[str, Knob(label="Preuve", choices=OPERATOR_EVIDENCE, advanced=False, order=10)] = c.VOUCHED
    name: Annotated[str, Field(max_length=40), Knob(
        label="Nom démenti", advanced=False, order=20, only=(("kind", (c.DENIED,)),),
        help="Le nom sous lequel elle la connaît, et qui n'est pas le sien.")] = ""
    note: Annotated[str, Field(max_length=NOTE_MAX), Knob(
        label="Raison", advanced=False, order=30,
        help="Quelques mots pour le registre. Gardée à part : l'oubli de la personne l'efface.")] = ""
    confirmed: Annotated[bool, Knob(label="Je confirme", advanced=False, order=40, help=CONFIRM_HELP)] = False

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, value: str) -> str:
        if value not in {k for k, _label in OPERATOR_EVIDENCE}:
            raise ValueError("preuve inconnue")
        return value


def _can_testify(s: IdentityState, frame: Frame, key: str) -> bool:
    h = _handle(s, key)
    return h is not None and not h.authenticated and bool(h.person or h.claim or h.name)


def _check(s: IdentityState, h: Handle, handle: str, args: EvidenceArgs, now: int) -> str:
    """Le nom démenti nettoyé ; refuse une preuve qui ne changerait rien."""
    view = view_of(s, handle, now)
    if args.kind == c.VOUCHED:
        claim = h.claim
        if not view.claim or claim is None or claim.target is None or claim.target == handle:
            raise Refused("Rien à garantir.", {"kind": "Aucune revendication en attente qui vise une personne "
                                                       "connue : rien à garantir."})
        if c.VOUCHED in claim.used:
            raise Refused("Déjà garantie.", {"kind": "Un opérateur s'en est déjà porté garant : une même preuve "
                                                     "ne compte qu'une fois."})
        return ""
    if args.kind == c.CONTRADICTED:
        if not (h.person or view.claim):
            raise Refused("Rien à contredire.", {"kind": "Elle ne dit être personne d'autre qu'elle-même : rien "
                                                         "à contredire."})
        return ""
    name = clean_display_name(args.name)
    if not name:
        raise Refused("Nom manquant.", {"name": "Indique le nom démenti."})
    names = [n for n in (h.name, h.claim.name if h.claim else "", known_as(s, h.person) if h.person else "") if n]
    if not any(same_name(name, n) for n in names):
        known = ", ".join(f"« {n} »" for n in names) or "aucun nom"
        raise Refused("Nom inconnu pour cette adresse.", {"name": (
            f"Elle ne connaît pas cette adresse sous ce nom ({known}) : un démenti n'y changerait rien.")})
    return name


def _outcome(s: IdentityState, before: Handle, after: Handle) -> str:
    if before.person and not after.person:
        return f"la liaison avec {known_as(s, before.person)} est défaite"
    if after.person and after.person != before.person:
        return f"la revendication est confirmée : elle parle désormais pour {known_as(s, after.person)}"
    if before.person and after.certainty != before.certainty:
        return f"certitude de la liaison : {certainty_fr(before.certainty)} → {certainty_fr(after.certainty)}"
    if before.claim and after.claim is None:
        return "la revendication tombe"
    if before.claim and after.claim and after.claim.certainty != before.claim.certainty:
        low = privacy.effective(before.claim.certainty, before.trust)
        high = privacy.effective(after.claim.certainty, after.trust)
        return f"certitude de la revendication : {certainty_fr(low)} → {certainty_fr(high)}"
    if before.name and not after.name:
        return "elle ne lui prête plus ce nom"
    return "notée au registre"


def _heavy(s: IdentityState, before: Handle, after: Handle, handle: str) -> str:
    """L'issue d'une preuve qui change qui elle reconnaît ici, dite en clair (vide : rien de lourd)."""
    if after.person and after.person != before.person:
        return (f"« {handle} » sera liée à {known_as(s, after.person)} : ce que cette personne lui a confié "
                "s'y ouvrira (sans ses droits de propriétaire : seule « Relier » les donne).")
    if before.person and not after.person:
        return (f"« {handle} » ne parlera plus pour {known_as(s, before.person)} : ce que cette personne lui "
                "avait confié s'y refermera.")
    return ""


@IDENTITY.action("preuve", title="Verser une preuve", args=EvidenceArgs, emits=[c.EVIDENCE], subject="handle",
                 description="Une raison de croire ou de ne plus croire, pesée comme les autres : un opérateur "
                             "ne fait pas monter la confiance au-delà du plafond du canal.",
                 confirm="Verser cette preuve ? Elle peut relier cette adresse à quelqu'un, ou l'en délier.",
                 available=_can_testify, order=30)
def _testify(s: IdentityState, frame: Frame, args: EvidenceArgs, ctx: ActionContext) -> Done:
    handle = ctx.subject
    h = _handle(s, handle)
    if h is None:
        raise Refused("Adresse inconnue.")
    if h.authenticated:
        raise Refused("Une session authentifiée prouve déjà qui écrit : aucune preuve n'y change rien.")
    name = _check(s, h, handle, args, frame.now)
    note = " ".join(args.note.split())[:NOTE_MAX]
    denies = denial_target(h, name, frame.now, known_as(s, h.person) if h.person else "") \
        if args.kind == c.DENIED else ""
    about = tuple(p for p in (h.person, h.claim.target if h.claim else None) if p and p != handle)
    draft = c.EVIDENCE.draft(handle=handle, kind=args.kind, by="operator", denies=denies, about=about,
                             name=Content.of(name, level=int(privacy.Sensitivity.ANODYNE)) if name else None,
                             note=Content.of(note, level=int(privacy.Sensitivity.PERSONAL)) if note else None)
    after = _apply(h, SimpleNamespace(data=draft.data, at=frame.now))
    heavy = _heavy(s, h, after, handle)
    if heavy and not args.confirmed:
        raise Refused(f"À confirmer : {heavy}", {"confirmed": f"{heavy} Coche « Je confirme »."})
    return Done(drafts=(draft,), message=f"Preuve versée : {_outcome(s, h, after)}.", guard=_seen(handle))


# ── Un nom dont on lui a parlé : c'était elle ─────────────────────────────


class NameArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=60), Knob(
        label="Le nom sous lequel on lui en a parlé", advanced=False, order=10,
        help="Tel qu'on lui en parlait (« Alice », « Alice Martin ») : ce que les autres lui ont dit de « Alice » "
             "est désormais su d'elle — chacun garde qui le lui a confié, et ce qui ne se répète pas reste tu.")]
    confirmed: Annotated[bool, Knob(label="Je confirme", advanced=False, order=20, help=CONFIRM_HELP)] = False


def _named_key(name: str) -> str:
    """La clé « connue seulement de nom », comme la mémoire la forme (``name:alice martin``)."""
    return "name:" + " ".join(fold(clean_display_name(name)).split())


def _can_name(s: IdentityState, frame: Frame, key: str) -> bool:
    return is_identifiable(key) and not key.startswith("name:") and _root(s, key) == key


@IDENTITY.action("nommer", title="C'est la personne dont on lui a parlé", args=NameArgs, emits=[c.NAME_BOUND],
                 subject="person", available=_can_name, order=40,
                 description="Quelqu'un lui avait parlé d'une « Alice » qu'elle ne connaissait pas : c'était cette "
                             "personne. Ce qu'on lui a dit d'elle s'y rattache (chacun garde qui le lui a confié). "
                             "Jamais deviné d'une ressemblance de nom : deux Alice ne se confondent pas d'elles-mêmes.",
                 confirm="Relier ce nom à cette personne ?")
def _bind_name(s: IdentityState, frame: Frame, args: NameArgs, ctx: ActionContext) -> Done:
    person = ctx.subject
    key = _named_key(args.name)
    if key == "name:":
        raise Refused("Nom manquant.", {"name": "Indique le nom sous lequel on lui en a parlé."})
    current = s.names.get(key)
    if current == person:
        raise Refused("Déjà relié.", {"name": f"« {args.name} » désigne déjà {known_as(s, person)}."})
    taken = f" (il désignait jusqu'ici {known_as(s, current)})" if current else ""
    outcome = (f"Ce qu'on lui a dit de « {args.name} » sera su de {known_as(s, person)}{taken} — chacun garde qui "
               "le lui a confié.")
    if not args.confirmed:
        raise Refused(f"À confirmer : {outcome}", {"confirmed": f"{outcome} Coche « Je confirme »."})
    return Done(drafts=(c.NAME_BOUND.draft(name=key, person=person, by="operator"),),
                message=f"« {args.name} », c'était {known_as(s, person)}.",
                guard=Guard("nom inchangé", reads=(c.PERSON(key),)))


class UnnameArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=60), Knob(
        label="Le nom à détacher", advanced=False, order=10,
        help="Un nom qu'un opérateur lui avait relié : ce qu'on a dit sous ce nom ne la désigne plus.")]


def _can_unname(s: IdentityState, frame: Frame, key: str) -> bool:
    return any(p == key for p in s.names.values())


@IDENTITY.action("denommer", title="Détacher un nom", args=UnnameArgs, emits=[c.NAME_BOUND], subject="person",
                 available=_can_unname, order=41,
                 description="Ce n'était pas elle : ce qu'on avait dit sous ce nom redevient « quelqu'un dont on lui "
                             "a parlé ».")
def _unbind_name(s: IdentityState, frame: Frame, args: UnnameArgs, ctx: ActionContext) -> Done:
    key = _named_key(args.name)
    if s.names.get(key) != ctx.subject:
        bound = ", ".join(f"« {k[5:]} »" for k, p in sorted(s.names.items()) if p == ctx.subject) or "aucun"
        raise Refused("Nom inconnu.", {"name": f"Noms reliés à cette personne : {bound}."})
    return Done(drafts=(c.NAME_BOUND.draft(name=key, person=None, by="operator"),),
                message=f"« {args.name} » ne désigne plus {known_as(s, ctx.subject)}.",
                guard=Guard("nom inchangé", reads=(c.PERSON(key),)))
