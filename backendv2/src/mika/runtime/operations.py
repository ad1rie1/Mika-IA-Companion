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
from mika.kernel.inspect import Ref
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
    if nonce and not _first_use(kernel, nonce):
        # un double envoi : l'action a pu agir hors du journal (une app rechargée,
        # une version précédente) — elle ne s'exécute pas deux fois
        return Outcome(True, "Ce formulaire a déjà été envoyé : rien de plus n'a été fait.", "info", deduped=True)

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
        return Outcome(False, f"L'action a échoué : {got.error!r}"[:400], "danger")
    done: Done = got if isinstance(got, Done) else Done(message=str(got or ""))
    stray = sorted({d.type.name for d in done.drafts} - spec.emits)
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
            commit = await mind.append(keyed, emitter=spec.owner, correlation=correlation, origin=Origin.EXTERNAL,
                                       guard=done.guard)
        except Superseded:
            await _audit(kernel, spec, by, subject, (), "superseded", correlation, nonce)
            return Outcome(False, "La situation a changé depuis l'ouverture de la page : rien n'a été fait.", "warn")
        seqs, deduped = tuple(commit.seqs), bool(commit.deduped)
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
    if deduped:
        return Outcome(True, "Déjà fait.", "info", seqs=seqs, deduped=True, go=done.go)
    await _audit(kernel, spec, by, subject, seqs, "done", correlation, nonce)
    return Outcome(True, done.message or "Fait.", done.tone, seqs=seqs, go=done.go, show=done.show)


#: les jetons de formulaire déjà servis, par noyau (le journal garde les autres : leur audit)
_USED: WeakKeyDictionary[Any, OrderedDict[str, None]] = WeakKeyDictionary()
USED_KEPT = 4096


def _first_use(kernel: Kernel, nonce: str) -> bool:
    """Vrai la première fois qu'un jeton sert ; ensuite (même en cours d'exécution,
    même après un redémarrage : l'audit porte le jeton) il ne sert plus."""
    used = _USED.setdefault(kernel, OrderedDict())
    if nonce in used or kernel.mind.store.find_dedupe(rt.OPERATED.name, f"op:{nonce}:audit") is not None:
        return False
    used[nonce] = None
    while len(used) > USED_KEPT:
        used.popitem(last=False)
    return True


async def _audit(kernel: Kernel, spec: ActionSpec, by: str, subject: str, seqs: tuple[int, ...], outcome: str,
                 correlation: str, nonce: str) -> None:
    draft = rt.OPERATED.draft(action=spec.key, by=by, subject_kind=spec.subject, subject=subject, seqs=seqs,
                              outcome=outcome, dedupe_key=f"op:{nonce}:audit" if nonce else None)
    await kernel.mind.append([draft], emitter="runtime", correlation=correlation, origin=Origin.EXTERNAL)


async def audit(kernel: Kernel, action: str, *, by: str, subject_kind: str = "", subject: str = "",
                seqs: tuple[int, ...] = (), outcome: str = "done") -> None:
    """L'audit d'une opération que la console fait elle-même (oubli, réglages…)."""
    draft = rt.OPERATED.draft(action=action, by=by, subject_kind=subject_kind, subject=subject, seqs=seqs,
                              outcome=outcome)
    await kernel.mind.append([draft], emitter="runtime", correlation=f"opérateur:{action}", origin=Origin.EXTERNAL)
