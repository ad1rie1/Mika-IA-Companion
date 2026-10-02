"""Exécuter une action d'opérateur déclarée par une faculté (``@f.action``).

Le chemin est unique et générique : valider le formulaire (erreurs en
français, champ par champ), vérifier que l'action est offerte, l'exécuter,
vérifier qu'elle n'émet que ce qu'elle a déclaré, ajouter ses brouillons au
journal avec l'origine « extérieure » sous sa garde, dédoublonnés par un
jeton de formulaire (un double envoi ne refait rien), puis journaliser
l'audit ``runtime.operated``. Rien ici ne nomme une faculté.
"""

from __future__ import annotations

import functools
import inspect as pyinspect
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any
from weakref import WeakKeyDictionary

from pydantic import ValidationError

from mika.contracts import runtime as rt
from mika.kernel import forms
from mika.kernel.events import Origin
from mika.kernel.faculty import ActionSpec
from mika.kernel.guards import Superseded
from mika.kernel.inspect import Ref, describe_error
from mika.kernel.operate import ActionContext, Done, Refused
from mika.runtime import decisions
from mika.runtime.boundary import Failed, acall, call

if TYPE_CHECKING:
    from mika.runtime.bootstrap import Kernel

#: le champ où l'on retape la clé d'un objet avant une action irréversible
RETYPE_FIELD = "_confirmer"
#: les valeurs fixées par la page (une app, une vue…), repostées telles quelles
FIXED_FIELD = "_fixes"


@dataclass(frozen=True, slots=True)
class Outcome:
    ok: bool
    message: str
    tone: str = "ok"
    #: un message par champ : le formulaire est remontré (400)
    errors: Mapping[str, str] = field(default_factory=dict)
    seqs: tuple[int, ...] = ()
    deduped: bool = False
    go: Ref | None = None
    show: tuple[Any, ...] = ()
    #: rien n'a abouti (une panne, la situation a changé) : le jeton du formulaire est rendu, le renvoyer réessaie
    retry: bool = False


def _wants_ports(fn: Any) -> bool:
    """Des champs qui dépendent du monde (les boîtes d'un compte, ses dossiers) : la
    fonction déclare un paramètre ``ports`` et les reçoit, en lecture."""
    try:
        return "ports" in pyinspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


def offered(kernel: Kernel, spec: ActionSpec, subject: str) -> bool:
    if spec.available is None:
        return True
    frame = kernel.mind.frame()
    fn = functools.partial(spec.available, ports=kernel.ports) if _wants_ports(spec.available) else spec.available
    got = call(fn, frame.state(spec.owner), frame, subject, label=f"action {spec.key} offerte ?")
    return got is True


def fixed_values(form: Mapping[str, Sequence[str]]) -> dict[str, str]:
    return {k: str((form.get(k) or [""])[-1])[:500] for k in (form.get(FIXED_FIELD) or [])[:20]
            if k and not k.startswith("_")}


def initial_values(kernel: Kernel, spec: ActionSpec, subject: str) -> dict[str, Any]:
    """Les valeurs de départ d'un formulaire, lues dans l'état (``ActionSpec.initial``, qui reçoit
    ``ports=`` s'il le déclare : un texte gardé hors de la tranche) ; rien si l'action n'en déclare
    pas ou si la lecture échoue."""
    if spec.initial is None:
        return {}
    frame = kernel.mind.frame()
    fn = functools.partial(spec.initial, ports=kernel.ports) if _wants_ports(spec.initial) else spec.initial
    got = call(fn, frame.state(spec.owner), frame, subject, label=f"valeurs de {spec.key}")
    return dict(got) if isinstance(got, Mapping) else {}


def dynamic_fields(kernel: Kernel, spec: ActionSpec, subject: str, fixed: Mapping[str, str]) -> tuple[Any, ...]:
    frame = kernel.mind.frame()
    fn = functools.partial(spec.fields, ports=kernel.ports) if _wants_ports(spec.fields) else spec.fields
    got = call(fn, frame.state(spec.owner), frame, subject, dict(fixed), label=f"champs de {spec.key}")
    return () if isinstance(got, Failed) or got is None else tuple(got)


def parse_args(spec: ActionSpec, form: Mapping[str, Sequence[str]], kernel: Kernel | None = None,
               subject: str = "") -> tuple[Any, dict[str, str]]:
    """Le modèle d'arguments validé (ou, pour des champs dynamiques, un dictionnaire),
    ou les erreurs par champ."""
    if spec.fields is not None and kernel is not None:
        fixed = fixed_values(form)
        fields = dynamic_fields(kernel, spec, subject, fixed)
        values, errors = forms.parse(fields, {k: list(v) for k, v in form.items()}, current={})
        errors = {**errors, **forms.within(fields, values)}
        return (None, errors) if errors else ({**fixed, **values}, {})
    fields = forms.describe(spec.args)
    values, errors = forms.parse(fields, {k: list(v) for k, v in form.items()}, current={})
    if errors:
        return None, errors
    fixed = fixed_values(form)
    values.update({f.path: fixed[f.path] for f in fields if f.kind == "hidden" and f.path in fixed})
    try:
        return spec.args.model_validate(forms.nest(values)), {}
    except ValidationError as exc:
        return None, forms.errors_fr(exc)


async def perform(kernel: Kernel, key: str, form: Mapping[str, Sequence[str]], *, by: str, subject: str = "",
                  nonce: str = "") -> Outcome:
    registry = kernel.registry
    spec: ActionSpec | None = registry.actions.get(key)
    if spec is None:
        return Outcome(False, "Action inconnue.", "danger")
    if spec.subject and not subject:
        return Outcome(False, "Cette action porte sur un objet précis.", "danger")
    if not offered(kernel, spec, subject):
        return Outcome(False, "Cette action n'est pas possible en ce moment.", "warn")
    if spec.retype and str((form.get(RETYPE_FIELD) or [""])[-1]).strip() != subject:
        return Outcome(False, "Confirmation manquante.", "danger",
                       errors={RETYPE_FIELD: f"Retape « {subject} » pour confirmer."})
    args, errors = parse_args(spec, form, kernel, subject)
    if errors:
        return Outcome(False, "Le formulaire a des erreurs.", "danger", errors=errors)
    if nonce and not _reserve(kernel, nonce):
        # un double envoi : l'action a pu agir hors du journal (une app rechargée,
        # une version précédente) — elle ne s'exécute pas deux fois, ni en même temps
        return Outcome(True, "Ce formulaire a déjà été envoyé : rien de plus n'a été fait.", "info", deduped=True)
    consumed = False
    try:
        outcome = await _perform(kernel, spec, args, by=by, subject=subject, nonce=nonce)
        # le jeton ne sert qu'une fois quand l'action a abouti ou a été refusée ; un échec (une panne, la
        # situation qui a changé) le rend : renvoyer le même formulaire réessaie au lieu de répondre « déjà envoyé »
        consumed = not outcome.retry
    finally:
        if nonce:
            _settle(kernel, nonce, consumed=consumed)
    return outcome


async def _perform(kernel: Kernel, spec: ActionSpec, args: Any, *, by: str, subject: str, nonce: str) -> Outcome:
    mind = kernel.mind
    frame = mind.frame()
    ctx = ActionContext(by=by, subject=subject, now=mind.clock.now(), ports=kernel.ports,
                        store=kernel.ports.get("store"))
    got: Any = call(spec.fn, frame.state(spec.owner), frame, args, ctx, label=f"action {spec.key}")
    if not isinstance(got, Failed) and pyinspect.isawaitable(got):
        pending = got
        got = await acall(lambda: pending, label=f"action {spec.key}")
    correlation = f"opérateur:{spec.key}:{nonce or mind.ids.new(ctx.now)}"
    if isinstance(got, Failed):
        if isinstance(got.error, Refused):
            await _audit(kernel, spec, by, subject, (), "refused", correlation, nonce)
            return Outcome(False, got.error.message, "warn", errors=got.error.fields)
        await _audit(kernel, spec, by, subject, (), "failed", correlation, nonce)
        return Outcome(False, f"L'action a échoué : {describe_error(got.error)}"[:400], "danger", retry=True)
    done: Done = got if isinstance(got, Done) else Done(message=str(got or ""))
    # la suite est vérifiée avant le premier ajout (sur des numéros fictifs) : rien ne s'écrit à moitié pour un
    # type non déclaré
    probe = call(lambda: list(done.then(tuple(range(1, len(done.drafts) + 1)))) if done.then is not None else [],
                 label=f"suite de {spec.key}")
    planned = [] if isinstance(probe, Failed) else probe
    stray = sorted({d.type.name for d in [*done.drafts, *planned]} - spec.emits)
    if stray:
        await _audit(kernel, spec, by, subject, (), "refused", correlation, nonce)
        return Outcome(False, f"Action refusée : elle émettrait {', '.join(stray)} sans l'avoir déclaré.", "danger")

    resolutions = []
    for d in done.decide:  # ses propres propositions seulement, telles qu'elles ont été lues
        got_ = await decisions.prepare(mind, kernel.ports, d.proposal, d.approved, by=by, note=d.note, seen=d.seen,
                                       owner=spec.owner)
        if got_.draft is None:
            await _audit(kernel, spec, by, subject, (), "refused", correlation, nonce)
            return Outcome(False, got_.message, "warn")
        resolutions.append((d.proposal, got_.draft))

    seqs: tuple[int, ...] = ()
    deduped = False
    if done.drafts:
        keyed = [replace(d, dedupe_key=d.dedupe_key or f"op:{nonce}:{i}") if nonce else d
                 for i, d in enumerate(done.drafts)]
        try:
            # la garde vérifie ce que l'action a lu (``basis`` : le moment où elle l'a lu), pas la tête contre
            # elle-même : un état changé entre la lecture et l'ajout supplante l'action
            commit = await mind.append(keyed, emitter=spec.owner, correlation=correlation, origin=Origin.EXTERNAL,
                                       basis=frame.root, guard=done.guard)
        except Superseded:
            await _audit(kernel, spec, by, subject, (), "superseded", correlation, nonce)
            return Outcome(False, "La situation a changé depuis l'ouverture de la page : rien n'a été fait.", "warn",
                           retry=True)
        seqs, deduped = tuple(commit.seqs), bool(commit.deduped)
        if done.then is not None and seqs:
            # même après un dédoublonnage (un renvoi après une panne) : ses clés rendent la suite rejouable
            more = await _follow(mind, spec, done, seqs, correlation, nonce)
            if isinstance(more, Failed):
                await _audit(kernel, spec, by, subject, seqs, "failed", correlation, nonce)
                go = Ref.subject(done.go_created, str(seqs[0]), "") if done.go_created else done.go
                return Outcome(False, "C'est créé, mais la suite n'a pas pu s'écrire : renvoie ce formulaire, ou "
                               "complète depuis sa fiche.", "warn", seqs=seqs, go=go, retry=True)
            seqs += more
    for proposal, draft in resolutions:
        keyed_ = replace(draft, dedupe_key=f"décision:{proposal}")
        try:
            decided = await mind.append([keyed_], emitter=rt.OWNER, correlation=correlation, origin=Origin.EXTERNAL,
                                        guard=decisions.still_pending(proposal))
        except Superseded:
            await _audit(kernel, spec, by, subject, seqs, "superseded", correlation, nonce)
            return Outcome(False, decisions.MESSAGES[decisions.UNKNOWN], "warn")
        if decided.deduped:
            await _audit(kernel, spec, by, subject, seqs, "superseded", correlation, nonce)
            return Outcome(False, decisions.MESSAGES[decisions.UNKNOWN], "warn")
        seqs += tuple(decided.seqs)
    go = done.go
    if go is None and done.go_created and seqs:
        go = Ref.subject(done.go_created, str(seqs[0]), "")
    if deduped:
        return Outcome(True, "Déjà fait.", "info", seqs=seqs, deduped=True, go=go)
    await _audit(kernel, spec, by, subject, seqs, "done", correlation, nonce)
    return Outcome(True, done.message or "Fait.", done.tone, seqs=seqs, go=go, show=done.show)


async def _follow(mind: Any, spec: ActionSpec, done: Done, seqs: tuple[int, ...], correlation: str,
                  nonce: str) -> tuple[int, ...] | Failed:
    """La suite d'une action (``Done.then``), journalisée après ce qu'elle suit ; une panne est rendue, jamais levée."""
    assert done.then is not None
    follow = call(lambda: list(done.then(seqs)), label=f"suite de {spec.key}")  # type: ignore[misc]
    if isinstance(follow, Failed):
        return follow
    if not follow:
        return ()
    keyed = [replace(d, dedupe_key=d.dedupe_key or f"op:{nonce}:suite:{i}") if nonce else d
             for i, d in enumerate(follow)]
    more = await acall(lambda: mind.append(keyed, emitter=spec.owner, correlation=correlation,
                                           origin=Origin.EXTERNAL), label=f"suite de {spec.key}")
    return more if isinstance(more, Failed) else tuple(more.seqs)


#: les jetons de formulaire déjà servis, par noyau (le journal garde les autres : leur audit)
_USED: WeakKeyDictionary[Any, OrderedDict[str, None]] = WeakKeyDictionary()
#: ceux dont l'action s'exécute en ce moment (un double clic n'en lance pas deux)
_INFLIGHT: WeakKeyDictionary[Any, set[str]] = WeakKeyDictionary()
USED_KEPT = 4096
#: les issues qui rendent le jeton (rien n'a abouti : renvoyer le formulaire réessaie)
RETRYABLE = frozenset({"failed", "superseded"})


def _reserve(kernel: Kernel, nonce: str) -> bool:
    """Vrai si ce jeton peut servir maintenant : jamais servi (même après un redémarrage : l'audit
    d'une action aboutie ou refusée porte le jeton) et pas déjà en cours d'exécution."""
    used = _USED.setdefault(kernel, OrderedDict())
    inflight = _INFLIGHT.setdefault(kernel, set())
    if nonce in used or nonce in inflight \
            or kernel.mind.store.find_dedupe(rt.OPERATED.name, f"op:{nonce}:audit") is not None:
        return False
    inflight.add(nonce)
    return True


def _settle(kernel: Kernel, nonce: str, *, consumed: bool) -> None:
    """L'action est finie : son jeton est consommé (succès, refus) ou rendu (panne, situation changée)."""
    _INFLIGHT.setdefault(kernel, set()).discard(nonce)
    if not consumed:
        return
    used = _USED.setdefault(kernel, OrderedDict())
    used[nonce] = None
    while len(used) > USED_KEPT:
        used.popitem(last=False)


async def _audit(kernel: Kernel, spec: ActionSpec, by: str, subject: str, seqs: tuple[int, ...], outcome: str,
                 correlation: str, nonce: str) -> None:
    # l'audit d'une issue définitive porte le jeton (il ne resservira pas, même après un redémarrage) ;
    # celui d'une panne non : chaque essai se journalise, le suivant reste possible
    key = f"op:{nonce}:audit" if nonce and outcome not in RETRYABLE else None
    draft = rt.OPERATED.draft(action=spec.key, by=by, subject_kind=spec.subject, subject=subject, seqs=seqs,
                              outcome=outcome, dedupe_key=key)
    await kernel.mind.append([draft], emitter="runtime", correlation=correlation, origin=Origin.EXTERNAL)


async def audit(kernel: Kernel, action: str, *, by: str, subject_kind: str = "", subject: str = "",
                seqs: tuple[int, ...] = (), outcome: str = "done") -> None:
    """L'audit d'une opération que la console fait elle-même (oubli, réglages…)."""
    draft = rt.OPERATED.draft(action=action, by=by, subject_kind=subject_kind, subject=subject, seqs=seqs,
                              outcome=outcome)
    await kernel.mind.append([draft], emitter="runtime", correlation=f"opérateur:{action}", origin=Origin.EXTERNAL)
