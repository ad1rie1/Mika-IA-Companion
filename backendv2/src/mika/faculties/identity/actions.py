"""Ce qu'un opérateur peut faire des identités depuis la console : relier une
poignée à une personne, la délier, verser une preuve au registre.

Chaque action rend des brouillons d'événements d'``identity`` (le moteur les
journalise comme venant de l'extérieur, avec l'audit qui nomme l'opérateur) ;
un refus se dit champ par champ. Rien ici ne touche à sa mémoire.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from mika.contracts import identity as c
from mika.faculties.identity.faculty import IDENTITY, Handle, IdentityState, _apply, _root, known_as, view_of
from mika.faculties.identity.inspect import certainty_fr, people
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
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


def _handle(s: IdentityState, key: str) -> Handle | None:
    return s.handles.get(key) if key and not is_internal(key) else None


# ── Relier ────────────────────────────────────────────────────────────────


class LinkArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    person: Annotated[str, Field(min_length=1, max_length=80), Knob(
        label="Personne", subject="person", advanced=False,
        help="Sa clé (user_7, tg_42…) ou le nom sous lequel elle la connaît.")]


def _resolve(s: IdentityState, frame: Frame, text: str) -> str:
    """La personne que l'opérateur désigne : une clé connue (ou une poignée,
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
    return _handle(s, key) is not None and is_identifiable(key)


@IDENTITY.action("relier", title="Relier à une personne", args=LinkArgs, emits=[c.LINKED], subject="handle",
                 description="Cette poignée parlera pour la personne choisie (certitude « liée ») : sa mémoire, "
                             "ses liens et sa fiche s'y attachent.",
                 available=_can_link, order=10)
def _link(s: IdentityState, frame: Frame, args: LinkArgs, ctx: ActionContext) -> Done:
    handle = ctx.subject
    h = _handle(s, handle)
    if h is None:
        raise Refused("Poignée inconnue.")
    person = _resolve(s, frame, args.person)
    if person == handle:
        raise Refused("C'est elle-même.", {"person": "C'est déjà elle-même : choisis une autre personne."})
    if h.person == person:
        raise Refused("Déjà reliée.", {"person": f"Cette poignée parle déjà pour {known_as(s, person)}."})
    followers = sorted(k for k, o in s.handles.items() if o.person == handle)
    if followers:
        raise Refused("D'autres poignées parlent pour elle.", {"person": (
            f"D'autres poignées parlent pour elle ({', '.join(followers[:5])}) : relie-les d'abord à "
            f"{known_as(s, person)}, ou délie-les.")})
    return Done(drafts=(c.LINKED.draft(handle=handle, person=person, by="operator"),),
                message=f"« {handle} » parle désormais pour {known_as(s, person)}.")


# ── Délier ────────────────────────────────────────────────────────────────


class NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _can_unlink(s: IdentityState, frame: Frame, key: str) -> bool:
    h = _handle(s, key)
    return h is not None and bool(h.person)


@IDENTITY.action("delier", title="Délier", args=NoArgs, emits=[c.LINKED], subject="handle",
                 description="Cette poignée ne parlera plus que pour elle-même ; sa revendication éventuelle "
                             "tombe aussi.",
                 confirm="Délier cette poignée ? Ce que la personne lui avait confié se referme.",
                 available=_can_unlink, order=20)
def _unlink(s: IdentityState, frame: Frame, args: NoArgs, ctx: ActionContext) -> Done:
    handle = ctx.subject
    h = _handle(s, handle)
    if h is None or not h.person:
        raise Refused("Cette poignée n'est reliée à personne d'autre qu'elle-même.")
    return Done(drafts=(c.LINKED.draft(handle=handle, person=None, by="operator"),),
                message=f"« {handle} » ne parle plus pour {known_as(s, h.person)}.")


# ── Verser une preuve ─────────────────────────────────────────────────────


class EvidenceArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Annotated[str, Knob(label="Preuve", choices=OPERATOR_EVIDENCE, advanced=False, order=10)] = c.VOUCHED
    name: Annotated[str, Field(max_length=40), Knob(
        label="Nom démenti", advanced=False, order=20, only=(("kind", (c.DENIED,)),),
        help="Le nom sous lequel elle la connaît, et qui n'est pas le sien.")] = ""
    note: Annotated[str, Field(max_length=NOTE_MAX), Knob(
        label="Raison", advanced=False, order=30,
        help="Quelques mots pour le registre. Rien de personnel : la raison reste au journal.")] = ""

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
        if not view.claim or claim is None or claim.target is None:
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
    names = [n for n in (h.name, h.claim.name if h.claim else "") if n]
    if not any(same_name(name, n) for n in names):
        known = ", ".join(f"« {n} »" for n in names) or "aucun nom"
        raise Refused("Nom inconnu pour cette poignée.", {"name": (
            f"Elle ne connaît pas cette poignée sous ce nom ({known}) : un démenti n'y changerait rien.")})
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


@IDENTITY.action("preuve", title="Verser une preuve", args=EvidenceArgs, emits=[c.EVIDENCE], subject="handle",
                 description="Une raison de croire ou de ne plus croire, pesée comme les autres : un opérateur "
                             "ne fait pas monter la confiance au-delà du plafond du canal.",
                 available=_can_testify, order=30)
def _testify(s: IdentityState, frame: Frame, args: EvidenceArgs, ctx: ActionContext) -> Done:
    handle = ctx.subject
    h = _handle(s, handle)
    if h is None:
        raise Refused("Poignée inconnue.")
    if h.authenticated:
        raise Refused("Une session authentifiée prouve déjà qui écrit : aucune preuve n'y change rien.")
    name = _check(s, h, handle, args, frame.now)
    draft = c.EVIDENCE.draft(handle=handle, kind=args.kind, name=name, by="operator",
                             note=" ".join(args.note.split())[:NOTE_MAX])
    after = _apply(h, SimpleNamespace(data=draft.data))
    return Done(drafts=(draft,), message=f"Preuve versée : {_outcome(s, h, after)}.")
