"""Ses partages (ADR 0188) : ce qu'elle partage — ses boîtes, ses comptes Teams, ses services, ses agendas (ADR 0309)
— avec qui et à quel niveau ; ce qu'on lui partage ; les personnes à qui elle peut partager. À ne pas confondre avec la faculté ``shares``
(``faculties/shares``), les fichiers que Mika envoie à qui elle parle.

Seul le propriétaire partage, et seulement avec une personne qui a un compte — jamais un salon, une inconnue, « tout
le monde ». Chaque sorte de ressource est à un domaine, qui dit dans sa part (``SharingPart``, ADR 0310 : le
``sharing.py`` de son dossier) comment ses partages se rangent, se lisent et s'écrivent ; ce module les réunit, dans
l'ordre de ``KINDS``, et n'en connaît aucune. Il garde ce qui vaut pour toutes : qui reçoit (une personne qui a un
compte, pas soi, pas qui l'a déjà : ``not_hers_already``), à quel niveau, l'audit. Une sorte rangée dans les réglages
avec ses partages (une boîte, un compte Teams : leur fiche porte ``shares``) fait sa part par ``kept_in_settings``, en
ne disant que ce qui est à elle.

Tous se lisent ici, dans les réglages (``every_share``) : Réglages › Droits › Partages les montre tous ; Paramètres ›
Partages (``list_shares``) et l'onglet Comptes de la fiche d'une personne y lisent ce qu'une personne donne et ce
qu'elle reçoit, triés une fois par ``given_and_received`` (la règle « à elle » de ``vocab.ownership.holds``). Une
seule écriture range chaque partage (``write_share``, la ``write`` de sa part) : celle de son propriétaire, et celle
de l'opérateur qui le retire dans Réglages › Droits › Partages (ADR 0210) — seul le propriétaire le donne, jamais la
console.
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError
from starlette.routing import Route

from mika.app.domains import DOMAINS, SharingPart, part
from mika.app.me.api import Call, Denied, MeApiBase, either, missing, person_of, refused
from mika.app.me.common import settings_of
from mika.contracts import identity as identity_c
from mika.runtime.operations import audit
from mika.vocab.access import PERSON, SHARES
from mika.vocab.ownership import holds

#: ce qui se partage, dans l'ordre où les partages se lisent : une sorte par domaine, que sa part dit (``SharingPart``) ;
#: le refus d'une sorte inconnue les énumère dans cet ordre (``set_share``)
KINDS = ("mail", "teams", "mcp", "agenda")
LEVELS = tuple(level for level, _label in SHARES)
#: une clé fait au plus tant de caractères, sauf ce qu'en dit sa sorte (``SharingPart.key_limit``)
KEY_LIMIT = 40


@dataclass(frozen=True, slots=True)
class Shared:
    """Un partage : sa ressource (sa sorte, sa clé, son nom), son propriétaire tel qu'il est rangé (« personne:<clé> »,
    « elle », vide : toi), la personne qui le reçoit (sa clé) et son niveau."""

    kind: str
    key: str
    title: str
    owner: str
    person: str
    level: str


@functools.cache
def parts() -> dict[str, SharingPart]:
    """La part de chaque sorte, dans l'ordre de ``KINDS``. Lue à la demande, une fois : la part d'un domaine importe ce
    module (``Shared``, ``not_hers_already``), qui ne peut donc pas importer la sienne en naissant. Chaque sorte de
    ``KINDS`` a sa part, dite une fois."""
    found = [part(d.sharing, "SHARING") for d in DOMAINS if d.sharing is not None]
    by_kind = {p.kind: p for p in found}
    if set(by_kind) != set(KINDS) or len(by_kind) != len(found):
        raise ValueError("Partages : chaque sorte a sa part, dite une fois, et sa place dans KINDS — "
                         f"{sorted(set(KINDS) ^ set(by_kind))}")
    return {kind: by_kind[kind] for kind in KINDS}


def people(call: Call) -> list[dict[str, Any]]:
    """Les personnes à qui elle peut partager : chaque compte actif, sauf elle, par sa personne et son nom ; ``owner``
    : une de ses propriétaires, à qui ce qui est « à toi » est déjà."""
    frame, me = call.frame, call.me
    owners = set(frame.get(identity_c.OWNERS) or ())
    out: dict[str, str] = {}
    for a in call.api.accounts.all():
        if not a.active:
            continue
        person = person_of(frame, a.handle)
        if person != me.person:
            out.setdefault(person, a.display_name or person)
    return [{"person": k, "name": v, "owner": k in owners}
            for k, v in sorted(out.items(), key=lambda kv: kv[1].casefold())]


def _name(call: Call, person: str) -> str:
    view = call.frame.get(identity_c.IDENTITY(person))
    return getattr(view, "name", "") or person


def every_share(settings: Any, names: Mapping[str, str] | None = None) -> list[Shared]:
    """Tous les partages, sorte par sorte dans l'ordre de ``KINDS``, chacune ressource par ressource
    (``SharingPart.every``) ; ``names`` : le nom des ressources que les réglages ne tiennent pas (``resource_names`` :
    celui des agendas), sinon leur clé courte — ce que chaque personne lit sous « Partagé avec toi »."""
    out: list[Shared] = []
    for found in parts().values():
        out += found.every(settings, names)
    return out


def given_and_received(shares: Iterable[Shared], person: str, *, owner: bool) -> tuple[list[Shared], list[Shared]]:
    """Ce qu'une personne (sa clé) donne et ce qu'elle reçoit, dans l'ordre de ``shares`` : donnés, les partages d'une
    ressource à elle (à son nom, ou « à toi » si elle est une de ses propriétaires, ``owner``) ; reçus, ceux qui lui
    vont d'une ressource qui n'est pas à elle. Une ressource « à toi » partagée à une de ses propriétaires (un reste
    d'avant ``not_hers_already``) est à elle : donnée, jamais reçue."""
    given: list[Shared] = []
    received: list[Shared] = []
    for s in shares:
        if holds(s.owner, PERSON + person, owner=owner):
            given.append(s)
        elif s.person == person:
            received.append(s)
    return given, received


def not_hers_already(call: Call, owner: str, person: str, level: str) -> None:
    """Une ressource « à toi » (sans propriétaire nommé) est déjà à chacune de ses propriétaires : la leur partager
    ne leur donnerait rien, et un niveau plus bas les brimerait sur ce qui est à elles."""
    if level and not owner and person in set(call.frame.get(identity_c.OWNERS) or ()):
        raise Denied(400, "Elle est déjà à cette personne : c'est une de ses propriétaires.",
                     {"person": "déjà propriétaire"})


def kept_in_settings(kind: str, *, word: str, article: str, config: Callable[[Any], Any], account: type[BaseModel],
                     save: Callable[[Any, Any, dict[str, Any]], Awaitable[Any]], owned: Callable[[Call, str], Any],
                     sharer: Callable[..., str] | None = None) -> SharingPart:
    """La part des partages d'une sorte de ressource rangée dans les réglages avec ses partages (une boîte, un compte
    Teams) : chacune a sa fiche dans ``config(settings).accounts``, par sa clé, qui dit son nom (``label``), son
    propriétaire (``owner``) et ses partages (``shares`` : « personne:<clé> » → niveau), journalisés avec les
    paramètres de son plugin — sa règle s'étend à qui la reçoit. Sa sorte dit le reste : ses mots (``word``,
    ``article``), sa fiche revalidée (``account``, sa forme), ses fiches récrites (``save(settings, cfg, accounts)``,
    asynchrone : toutes, celle-ci changée), une ressource à qui demande (``owned(call, key)``, qui lève ``Denied``),
    qui la partage (``sharer`` ; ``None`` : son propriétaire)."""

    def every(settings: Any, names: Mapping[str, str] | None = None) -> list[Shared]:
        # ses partages, ressource par ressource : ceux rangés avec chacune
        out: list[Shared] = []
        for key, spec in sorted(config(settings).accounts.items()):
            out += [Shared(kind, key, spec.label or key, spec.owner, who[len(PERSON):], level)
                    for who, level in sorted(spec.shares.items())]
        return out

    async def share(call: Call, settings: Any, key: str, person: str, level: str) -> None:
        # son propriétaire partage une de ses ressources : elle est à lui, et pas déjà à cette personne — jugé sur sa
        # fiche relue sous le verrou des réglages
        def hers(spec: Any) -> None:
            owned(call, key)
            not_hers_already(call, spec.owner, person, level)

        await write(settings, call.api.reconfigure, key, person, level, hers)

    async def write(settings: Any, reconfigure: Callable[[], Awaitable[Any]] | None, key: str, person: str,
                    level: str, check: Callable[[Any], None] | None = None) -> None:
        # le partage d'une ressource à cette personne, à ce niveau (vide : retiré), relu puis réécrit d'un seul tenant
        # (``Settings.writing``), avec ce qui en dérive (``shares``, rejournalisé : sa règle s'étend) : un partage
        # retiré ailleurs entre-temps ne revient pas ; ``check`` juge la fiche relue, sous le verrou
        async with settings.writing:
            cfg = config(settings)
            spec = cfg.accounts.get(key)
            if spec is None:
                raise missing()
            if check is not None:
                check(spec)
            who = PERSON + person
            shares = {k: v for k, v in spec.shares.items() if k != who} | ({who: level} if level else {})
            try:
                await save(settings, cfg, {**cfg.accounts, key: account.model_validate(
                    {**spec.model_dump(), "shares": shares})})
            except ValidationError as exc:
                raise refused(exc) from None
            if reconfigure is not None:
                await reconfigure()

    return SharingPart(kind, every=every, share=share, write=write, sharer=sharer, word=word, article=article)


async def list_people(call: Call) -> dict[str, Any]:
    return {"items": people(call)}


def sharer(frame: Any, s: Shared, name: Callable[[str], str]) -> str:
    """Qui partage cette ressource, par son nom : ce qu'en dit sa sorte (``SharingPart.sharer`` : qui décide d'une
    boîte, qui écrit d'un compte Teams…), sinon son propriétaire (``name`` : le nom d'une personne, par sa clé)."""
    said = parts()[s.kind].sharer
    if said is not None:
        return said(frame, s, name)
    return name(s.owner.removeprefix(PERSON))


def resource_names(port: Callable[[str], Any]) -> dict[str, str]:
    """Le nom des ressources que les réglages ne tiennent pas (un agenda : sa base le dit), par leur clé : ce que chaque
    sorte en lit (``SharingPart.names`` ; ``port`` : un port du noyau, par son nom), avant ``every_share``."""
    return {key: title for found in parts().values() if found.names is not None
            for key, title in found.names(port).items()}


async def list_shares(call: Call) -> dict[str, Any]:
    """Ce qu'elle partage (``given``), et ce qu'on lui partage (``received``), lus dans les réglages
    (``given_and_received``) : par sorte, ressource et personne."""
    settings = call.api.settings
    if settings is None:
        return {"given": [], "received": []}
    names = resource_names(call.port)
    given, received = given_and_received(every_share(settings, names), call.me.person, owner=call.me.owner)
    return {"given": [{"kind": s.kind, "key": s.key, "title": s.title, "person": s.person,
                       "name": _name(call, s.person), "level": s.level} for s in given],
            "received": [{"kind": s.kind, "key": s.key, "title": s.title, "level": s.level,
                          "owner_name": sharer(call.frame, s, lambda p: _name(call, p))} for s in received]}


def audited_share(kind: str, key: str, person: str) -> dict[str, str]:
    """L'objet d'un geste sur un partage, celui du propriétaire comme celui de l'opérateur : le partage même, sa ressource
    et sa personne. Sa sorte n'est pas un sujet de la console : Gestes audités le dit en texte, sans lien. « mail » et
    « partage » en sont (un message, un fichier envoyé), et leurs fiches ne parlent pas d'un partage."""
    return {"subject_kind": "ressource_partagee", "subject": f"{kind}:{key}:{person}"}


async def write_share(settings: Any, reconfigure: Callable[[], Awaitable[Any]] | None, kind: str, key: str, person: str,
                      level: str, check: Callable[[Any], None] | None = None) -> None:
    """Le partage d'une ressource à cette personne, à ce niveau (vide : retiré), rangé par sa sorte
    (``SharingPart.write``) : relu puis réécrit d'un seul tenant (``Settings.writing``), avec ce qui en dérive — un
    partage retiré ailleurs entre-temps ne revient pas. ``check`` juge la fiche relue, sous le verrou : qui a le droit,
    c'est à qui appelle de le dire. Une sorte qui ne se range pas ainsi (un service, sur ses lignes d'accès) :
    introuvable."""
    found = parts().get(kind)
    if found is None or found.write is None:
        raise missing()
    await found.write(settings, reconfigure, key, person, level, check)


async def set_share(call: Call) -> dict[str, Any]:
    """Partager une de ses ressources avec une personne, à un niveau ; un niveau vide retire le partage. Ce qui vaut
    pour toutes les sortes se juge ici ; ce que la sienne vérifie, puis l'écriture, sont à sa part
    (``SharingPart.share``)."""
    kind = call.arg("kind", limit=10)
    found = parts().get(kind)
    key = call.arg("key", limit=found.key_limit if found is not None else KEY_LIMIT)
    person = call.arg("person", limit=200)
    level = call.arg("level", limit=20)
    if kind not in KINDS:
        raise Denied(400, f"« kind » : {either(KINDS)}.")
    if level and level not in LEVELS:
        raise Denied(400, "« level » : lire, preparer ou servir (vide : retirer).")
    settings = settings_of(call)
    if not person:
        raise Denied(400, "« person » : la personne avec qui tu partages.", {"person": "valeur requise"})
    if person == call.me.person:
        # ni un partage à soi, ni le retrait de sa propre ligne (un service qui ne servirait plus à personne)
        raise Denied(400, "C'est déjà à toi : on ne se partage rien.", {"person": "c'est toi"})
    # partager va à une personne qui a un compte actif ; retirer, à toute personne à qui la ressource est partagée
    # (un compte désactivé depuis, une adresse reliée ailleurs) : un partage se retire toujours d'un clic
    if level and person not in {p["person"] for p in people(call)}:
        raise Denied(400, "Un partage va à une personne qui a un compte (pas à toi).", {"person": "personne inconnue"})
    await parts()[kind].share(call, settings, key, person, level)
    await audit(call.kernel, "moi.partage", by=call.me.handle, **audited_share(kind, key, person))
    said = "Partage retiré." if not level else f"Partagé avec {_name(call, person)} ({dict(SHARES)[level].lower()})."
    return {"ok": True, "message": said}


def routes(api: MeApiBase) -> list[Route]:
    r = api.route
    return [r("/people", list_people), r("/shares", list_shares), r("/shares/set", set_share, write=True)]
