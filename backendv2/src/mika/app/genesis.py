"""Une vie importée (ADR 0070) : la couture par laquelle un pilote extérieur
lui donne, à l'instant courant, ce que ses archives disent d'elle — et le
préréglage qui coupe sa vie spontanée pendant qu'on rejoue ces archives.

**La couture.** Sur un noyau déjà démarré (souvent sur une horloge virtuelle
qui rejoue sa vie dans l'ordre), ``remember``, ``believe`` et ``note_event``
ajoutent à l'instant courant un souvenir, une croyance ou un moment de la vie
de quelqu'un, comme sa mémoire l'aurait fait : les mêmes événements
(``memory.remembered``, ``memory.believed``, ``memory.event_noted``), émis au
nom de ``memory``, avec ``origin=GENESIS`` — c'est l'exception, documentée, à
« écrit par sa voix ou dérivé des faits » : ce qu'elle tient de ses propres
archives, daté par l'horloge du rejeu. Tout passe par ``Mind.append`` (le
seul point d'écriture) : le dédoublonnage (la clé de l'appelant), la
validation, les réducteurs et les projections de sa mémoire, l'oubli. Chaque
texte déclare qui il concerne et qui l'a confié — des clés de personne
canoniques (une adresse, ou ``name:…`` pour qui n'est connu que de nom),
vérifiées ici : une clé mal formée est refusée, sinon ``forget`` ne
l'atteindrait jamais.

**Le préréglage « avance rapide ».** Pendant un rejeu, l'archive dit déjà ce
qu'elle a fait : ses initiatives ordinaires, ses rêveries et réflexions, ses
murmures, ses prises de nouvelles et relances ne doivent pas s'y ajouter.
``begin_fast_forward`` pose des surcharges de paramètres (``runtime/params.py``,
étage « surcharge »), journalisées comme toute configuration ; le rejeu les relit
telles quelles. ``end_fast_forward`` les lève : ses valeurs naturelles
(tempérament, réglages, surcharges de l'opératrice) reviennent.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from types import MappingProxyType
from typing import Any

from mika.app import composition
from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import self_ as self_c
from mika.kernel.events import Content, Draft, Origin
from mika.runtime import params
from mika.runtime.bootstrap import Kernel
from mika.vocab.affect import Emotion, emotion_of
from mika.vocab.people import ACCOUNT_PREFIX, EXTERNAL_PREFIX, clean_display_name, fold, is_identifiable
from mika.vocab.privacy import Sensitivity

#: qui émet ce qu'elle tient de ses archives : sa mémoire (le propriétaire des événements)
EMITTER = memory_c.OWNER
#: la marque d'un élément importé : son ``call_id`` (aucun appel de modèle ne l'a produit) et sa corrélation
ARCHIVE = "archive"
#: une personne connue seulement de nom, comme la mémoire la note
NAMED = "name:"
#: une adresse : ce par quoi quelqu'un lui écrit (``user_7``, ``web_…``, ``ext_…``)
_HANDLE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,127}$")
#: les adresses qui se reconnaissent à leur forme, même avant d'avoir écrit : un compte, un compte extérieur
_ACCOUNT = re.compile(rf"^{ACCOUNT_PREFIX}\d{{1,18}}$")
_EXTERNAL = re.compile(rf"^{EXTERNAL_PREFIX}[A-Za-z0-9_.:@+-]{{1,120}}$")
#: des adresses qui ne sont jamais des personnes (ses modules, sa propre tuyauterie)
_NOT_PEOPLE = ("module_", "conscience")
#: un souvenir, une croyance ou un moment se disent en quelques phrases
MAX_TEXT = 1200


class NotAPerson(ValueError):
    """Une clé de personne mal formée : refusée, sinon l'oubli ne l'atteindrait jamais."""


def named(name: str) -> str:
    """La clé de quelqu'un qu'elle ne connaît que de nom (« Alice Martin » → ``name:alice martin``), comme la
    mémoire et l'identité la forment."""
    return NAMED + " ".join(fold(clean_display_name(name)).split())


def person_key(raw: str, known: Callable[[str], bool] = lambda handle: False) -> str:
    """Une clé de personne canonique, telle quelle — ou ``NotAPerson``. Soit ``name:…`` déjà replié (``named``) :
    quelqu'un qu'elle ne connaît que de nom ; soit une adresse : un compte (``user_7``), un compte extérieur
    (``ext_…``), ou une adresse qu'elle a déjà vue (``known``). Ni sa tuyauterie, ni une connexion jetable
    (``anon_…``), ni un prénom nu (« Alice » : c'est ``named("Alice")``)."""
    if not isinstance(raw, str) or not raw or raw != raw.strip():
        raise NotAPerson(f"clé de personne illisible : {raw!r}")
    if raw.startswith(NAMED):
        if raw == NAMED or named(raw[len(NAMED):]) != raw:
            raise NotAPerson(f"« {raw} » n'est pas une clé de nom canonique (attendu : « {named(raw[len(NAMED):])} »)")
        return raw
    if not _HANDLE.match(raw) or not is_identifiable(raw) or raw.startswith(_NOT_PEOPLE):
        raise NotAPerson(f"« {raw} » n'est pas l'adresse d'une personne")
    if not (_ACCOUNT.match(raw) or _EXTERNAL.match(raw) or known(raw)):
        raise NotAPerson(f"« {raw} » : une adresse qu'elle n'a jamais vue — quelqu'un qu'elle ne connaît que de nom "
                         f"s'écrit « {named(raw)} »")
    return raw


def _people(kernel: Kernel, keys: Iterable[str], what: str) -> tuple[str, ...]:
    if isinstance(keys, str):
        raise NotAPerson(f"{what} : une suite de clés, pas une chaîne (« {keys} »)")
    frame = kernel.mind.frame()
    return tuple(dict.fromkeys(person_key(k, lambda h: frame.get(identity_c.IDENTITY(h)).known) for k in keys))


def _text(text: str, level: int) -> Content:
    clean = " ".join(str(text).split())
    if not clean:
        raise ValueError("un texte vide ne se retient pas")
    if len(clean) > MAX_TEXT:
        raise ValueError(f"un texte de {len(clean)} caractères : au plus {MAX_TEXT} — un souvenir se dit en "
                         "quelques phrases")
    return Content.of(clean, level=level)


def _level(sensitivity: int | None, *, has_person: bool) -> int:
    """La sensibilité donnée, ou celle de la consolidation : personnel dès qu'une personne est en jeu."""
    if sensitivity is None:
        return int(Sensitivity.PERSONAL if has_person else Sensitivity.ANODYNE)
    return int(Sensitivity(int(sensitivity)))


def _unit(value: float, what: str) -> float:
    if not 0.0 <= float(value) <= 1.0:
        raise ValueError(f"{what} entre 0 et 1 : {value}")
    return float(value)


def _emotion(name: str | Emotion | None) -> str | None:
    if name is None or name == "":
        return None
    found = emotion_of(str(name.value if isinstance(name, Emotion) else name))
    if found is None:
        raise ValueError(f"émotion inconnue : « {name} » (l'une des 29)")
    return found.value


def _replaced(kernel: Kernel, item: int | None, kind: str) -> int | None:
    """Ce qu'un élément remplace doit exister dans sa mémoire, de la même sorte."""
    if item is None:
        return None
    rows = kernel.mind.store.query_mind(f"SELECT kind FROM {memory_c.ITEMS_TABLE} WHERE id=?", (int(item),))
    if not rows or rows[0][0] != kind:
        raise ValueError(f"rien à remplacer : l'élément n° {item} n'est pas une {kind} de sa mémoire")
    return int(item)


async def _append(kernel: Kernel, draft: Draft[Any], dedupe_key: str | None) -> int:
    correlation = f"{ARCHIVE}:{dedupe_key}" if dedupe_key else ARCHIVE
    commit = await kernel.mind.append([draft], emitter=EMITTER, correlation=correlation, origin=Origin.GENESIS)
    return commit.seqs[0]


async def remember(kernel: Kernel, text: str, about: Iterable[str], *, sensitivity: int | None = None,
                   importance: float = 0.5, emotion: str | Emotion | None = None, told_by: Iterable[str] = (),
                   heard_by: Iterable[str] | None = None, secret: bool = False,
                   dedupe_key: str | None = None) -> int:
    """Un souvenir de ses archives, à la première personne, ajouté à l'instant courant. ``about`` : qui il
    concerne (vide : sa vie à elle) ; ``told_by`` : qui le lui a confié (vide : elle l'a vécu) ; ``heard_by`` :
    qui était là (par défaut : qui l'a confié). Rend son numéro (celui de l'élément déjà gardé sous la même
    ``dedupe_key``)."""
    about_, told = _people(kernel, about, "about"), _people(kernel, told_by, "told_by")
    heard = told if heard_by is None else _people(kernel, heard_by, "heard_by")
    level = _level(sensitivity, has_person=bool(about_ or told))
    draft = memory_c.REMEMBERED.draft(
        text=_text(text, level), about=about_, sensitivity=level, importance=_unit(importance, "importance"),
        emotion=_emotion(emotion), call_id=ARCHIVE, told_by=told, heard_by=heard, secret=bool(secret),
        dedupe_key=dedupe_key)
    return await _append(kernel, draft, dedupe_key)


async def believe(kernel: Kernel, text: str, about: Iterable[str], *, sensitivity: int | None = None,
                  importance: float = 0.5, confidence: float = 0.7, origin: str = memory_c.TOLD,
                  source: str | None = None, told_by: Iterable[str] = (), heard_by: Iterable[str] | None = None,
                  secret: bool = False, about_self: bool = False, durable: bool = False, between_us: bool = False,
                  replaces: int | None = None, dedupe_key: str | None = None) -> int:
    """Une croyance de ses archives : un fait sur quelqu'un (``about``), sur le monde (personne), ou sur elle
    (``about_self`` : ce qu'elle raconte d'elle ; ``durable`` : ce qui la définit, un goût, un avis, un fait de
    sa vie — tenu longtemps). ``source`` : qui l'a dit ; ``replaces`` : la croyance qu'elle remplace."""
    if origin not in (memory_c.TOLD, memory_c.OBSERVED, memory_c.INFERRED):
        raise ValueError(f"origine inconnue : « {origin} » (told, observed ou inferred)")
    about_, told = _people(kernel, about, "about"), _people(kernel, told_by, "told_by")
    mine = about_self or durable
    if mine and (about_ or told):
        raise ValueError("ce qu'elle dit d'elle-même ne concerne qu'elle : ni « about », ni « told_by »")
    heard = told if heard_by is None else _people(kernel, heard_by, "heard_by")
    level = int(Sensitivity.ANODYNE) if mine and sensitivity is None else \
        _level(sensitivity, has_person=bool(about_ or told))
    draft = memory_c.BELIEVED.draft(
        text=_text(text, level), about=about_, sensitivity=level, importance=_unit(importance, "importance"),
        confidence=_unit(confidence, "confiance"), origin=origin,
        source=_people(kernel, (source,), "source")[0] if source is not None else None,
        replaces=_replaced(kernel, replaces, memory_c.BELIEF), call_id=ARCHIVE, told_by=told, heard_by=heard,
        secret=bool(secret), about_self=mine, durable=bool(durable), between_us=bool(between_us),
        dedupe_key=dedupe_key)
    return await _append(kernel, draft, dedupe_key)


async def note_event(kernel: Kernel, text: str, about: Iterable[str], when: int, *, all_day: bool = True,
                     sensitivity: int | None = None, importance: float = memory_c.IMPORTANT_MOMENT,
                     festive: bool = False, ongoing: bool = False, told_by: Iterable[str] = (),
                     heard_by: Iterable[str] | None = None, secret: bool = False, replaces: int | None = None,
                     dedupe_key: str | None = None) -> int:
    """Un moment de la vie de quelqu'un (``about``, au moins une personne) noté d'après ses archives : à venir
    (``when``, en µs ; le jour seulement si ``all_day``), ou une situation en cours depuis ``when``
    (``ongoing``)."""
    about_, told = _people(kernel, about, "about"), _people(kernel, told_by, "told_by")
    if not about_:
        raise NotAPerson("un moment de la vie de quelqu'un dit de qui (« about » vide)")
    if int(when) <= 0:
        raise ValueError(f"un moment sans date : {when}")
    heard = told if heard_by is None else _people(kernel, heard_by, "heard_by")
    level = _level(sensitivity, has_person=True)
    draft = memory_c.EVENT_NOTED.draft(
        text=_text(text, level), when=int(when), about=about_, all_day=bool(all_day), sensitivity=level,
        told_by=told, heard_by=heard, secret=bool(secret), replaces=_replaced(kernel, replaces, memory_c.EVENT),
        call_id=ARCHIVE, ongoing=bool(ongoing), importance=_unit(importance, "importance"), festive=bool(festive),
        dedupe_key=dedupe_key)
    return await _append(kernel, draft, dedupe_key)


# ── Le préréglage « avance rapide » ───────────────────────────────────────

#: Ce qu'une avance rapide coupe, par faculté et par chemin de paramètre (l'étage « surcharge ») : tout ce qu'elle
#: ferait d'elle-même pendant qu'on rejoue ce que l'archive dit qu'elle a fait.
FAST_FORWARD: Mapping[str, Mapping[str, Any]] = MappingProxyType({
    # aucune initiative ordinaire (prendre la parole, prévenir, relancer, raconter) : un plafond du jour à zéro
    "agency": MappingProxyType({"daily_cap": 0}),
    # n'entreprendre rien d'elle-même (ni réflexion, ni exploration), aucune rêverie, aucune séance de travail
    "goals": MappingProxyType({"live_self_max": 0, "musings_per_day": 0, "steps_per_hour": 0}),
    # n'ouvrir aucun projet à elle (l'outil le refuse)
    "projects": MappingProxyType({"live_self_max": 0}),
    # aucun murmure avant d'écrire
    "expression": MappingProxyType({"murmur_chance": 0.0, "murmur_charged_chance": 0.0}),
    # ni prise de nouvelles, ni « alors, cet entretien ? », ni vœux, ni encouragement la veille
    "others": MappingProxyType({"checkin_evidence_start": 0.0, "checkin_evidence": 0.0, "followup_evidence": 0.0,
                                "followup_minor_evidence": 0.0, "celebrate_evidence": 0.0, "cheer_evidence": 0.0}),
    # ni relance d'un manque, ni prise de nouvelles longtemps après, ni recherche de réconfort
    "social": MappingProxyType({"recontact_evidence": 0.0, "rekindle_evidence": 0.0, "comfort_evidence": 0.0}),
    # tenir une promesse au moment dit est dû (le plafond du jour ne l'arrête pas) : l'archive dit si elle l'a fait
    "memory": MappingProxyType({"keep_evidence": 0.0}),
})


def fast_forward_overrides(overrides: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    """Les surcharges données, et par-dessus elles celles de l'avance rapide."""
    out = {owner: dict(layer) for owner, layer in (overrides or {}).items()}
    for owner, layer in FAST_FORWARD.items():
        out[owner] = {**out.get(owner, {}), **layer}
    return out


def _persona(kernel: Kernel, doc: self_c.PersonaDoc | None) -> self_c.PersonaDoc:
    """La persona à garder : celle donnée, sinon celle en vigueur (rien de nouveau à journaliser)."""
    return doc if doc is not None else kernel.mind.root.slices["self"].persona


async def begin_fast_forward(kernel: Kernel, doc: self_c.PersonaDoc | None = None, *,
                             overrides: Mapping[str, Mapping[str, Any]] | None = None,
                             inputs: Mapping[str, Mapping[str, Any]] | None = None) -> bool:
    """Pose le préréglage, journalisé (``kernel.params_changed``) : ``overrides`` et ``inputs`` sont ceux de la
    configuration en cours (ceux que reçoit ``composition.configure``), que le préréglage complète. Une surcharge
    du préréglage refusée lève (un nom de paramètre qui n'existe plus ne doit pas laisser sa vie spontanée
    tourner en silence). Rend ``True`` si quelque chose a été journalisé."""
    persona = _persona(kernel, doc)
    layered = fast_forward_overrides(overrides)
    planned = params.plan(list(kernel.registry.faculties.values()), persona.temperament, layered, inputs)
    refused = {f"{owner}.{path}": why for owner, p in planned.items() for path, why in p.refused.items()
               if path in FAST_FORWARD.get(owner, {})}
    if refused:
        raise ValueError(f"préréglage « avance rapide » refusé : {refused}")
    return await composition.configure(kernel, persona, layered, inputs)


async def end_fast_forward(kernel: Kernel, doc: self_c.PersonaDoc | None = None, *,
                           overrides: Mapping[str, Mapping[str, Any]] | None = None,
                           inputs: Mapping[str, Mapping[str, Any]] | None = None) -> bool:
    """Lève le préréglage : la configuration d'avant (``overrides``, ``inputs``) est rejournalisée, ses valeurs
    naturelles reviennent. Rend ``True`` si quelque chose a été journalisé."""
    return await composition.configure(kernel, _persona(kernel, doc), overrides, inputs)
