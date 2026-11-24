"""Ses partages (ADR 0188) : ce qu'elle partage — ses boîtes, ses comptes Teams, ses services, ses agendas (ADR 0309)
— avec qui et à quel niveau ; ce qu'on lui partage ; les personnes à qui elle peut partager. À ne pas confondre avec la faculté ``shares``
(``faculties/shares``), les fichiers que Mika envoie à qui elle parle.

Seul le propriétaire partage, et seulement avec une personne qui a un compte — jamais un salon, une inconnue, « tout
le monde ». Une boîte ou un compte Teams partagé est rangé avec sa ressource et journalisé avec ses paramètres
(``shares``) : sa règle s'étend à la personne, au niveau donné (lire ; lire et préparer ; s'en servir). Un service
partagé reçoit une ligne d'accès pour la personne (ADR 0192) — lire : ses outils qui lisent ; s'en servir : aussi ceux
qui agissent, sur sa demande à elle ; retirer le partage retire la ligne. Un agenda partagé est rangé avec son agenda
(``Settings.share_calendar``) et journalisé avec les paramètres du plugin ``agenda`` ; son tableau de droits reçoit ou
perd la ligne de la personne.

Tous se lisent ici, dans les réglages (``every_share``) : Réglages › Droits › Partages les montre tous ; Paramètres ›
Partages (``list_shares``) et l'onglet Comptes de la fiche d'une personne y lisent ce qu'une personne donne et ce
qu'elle reçoit, triés une fois par ``given_and_received`` (la règle « à elle » de ``vocab.ownership.holds``). Une
seule écriture range celui d'une boîte ou d'un compte Teams (``write_share``) : celle de son propriétaire, et celle de
l'opérateur qui le retire dans Réglages › Droits › Partages (ADR 0210) — seul le propriétaire le donne, jamais la
console.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from starlette.routing import Route

from mika.adapters.mail.config import MailAccount, MailConfig
from mika.adapters.teams import TeamsAccount
from mika.app.me import agenda as agenda_me
from mika.app.me import mail as mail_me
from mika.app.me import mcp as mcp_me
from mika.app.me import teams as teams_me
from mika.app.me.api import Call, Denied, MeApiBase, missing, person_of, refused
from mika.app.me.common import settings_of
from mika.contracts import identity as identity_c
from mika.plugins import agenda as agenda_p
from mika.plugins import email as email_p
from mika.plugins import teams as teams_p
from mika.ports.agenda import split_calendar_key, system_person
from mika.runtime.operations import audit
from mika.vocab.access import PERSON, SHARE_PREPARE, SHARE_USE, SHARES
from mika.vocab.ownership import OWNED, holds

#: ce qui se partage
KINDS = ("mail", "teams", "mcp", "agenda")
LEVELS = tuple(level for level, _label in SHARES)


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


def service_shares(spec: Any) -> dict[str, str]:
    """Les partages d'un service, par personne (« personne:<clé> ») : leur niveau, lu par la règle de ``mcp.shared``."""
    return {who: level for who, (level, _line) in mcp_me.shared(spec).items()}


def every_share(settings: Any, names: Mapping[str, str] | None = None) -> list[Shared]:
    """Tous les partages, ressource par ressource : ceux rangés avec chaque boîte et chaque compte Teams, puis les
    lignes de chaque service qui a un propriétaire, puis ceux de chaque agenda (``names`` : leur nom, tel que la base
    de l'agenda le dit ; sinon sa clé courte) — ce que chaque personne lit sous « Partagé avec toi »."""
    out: list[Shared] = []
    for kind, accounts in (("mail", settings.email().accounts), ("teams", settings.teams().accounts)):
        for key, spec in sorted(accounts.items()):
            out += [Shared(kind, key, spec.label or key, spec.owner, who[len(PERSON):], level)
                    for who, level in sorted(spec.shares.items())]
    for name, spec in sorted(settings.mcp().servers.items()):
        if spec.owner:
            out += [Shared("mcp", name, name, spec.owner, who[len(PERSON):], level)
                    for who, level in sorted(service_shares(spec).items())]
    for account, spec in sorted(settings.agenda().accounts.items()):
        holder = PERSON + system_person(account) if system_person(account) else spec.owner
        for local, setting in sorted(spec.calendars.items()):
            calendar = f"{account}~{local}"
            out += [Shared("agenda", calendar, (names or {}).get(calendar) or local, holder, who[len(PERSON):], level)
                    for who, level in sorted(setting.shares.items())]
    return out


def given_and_received(shares: Iterable[Shared], person: str, *, owner: bool) -> tuple[list[Shared], list[Shared]]:
    """Ce qu'une personne (sa clé) donne et ce qu'elle reçoit, dans l'ordre de ``shares`` : donnés, les partages d'une
    ressource à elle (à son nom, ou « à toi » si elle est une de ses propriétaires, ``owner``) ; reçus, ceux qui lui
    vont d'une ressource qui n'est pas à elle. Une ressource « à toi » partagée à une de ses propriétaires (un reste
    d'avant ``_not_hers_already``) est à elle : donnée, jamais reçue."""
    given: list[Shared] = []
    received: list[Shared] = []
    for s in shares:
        if holds(s.owner, PERSON + person, owner=owner):
            given.append(s)
        elif s.person == person:
            received.append(s)
    return given, received


def _not_hers_already(call: Call, owner: str, person: str, level: str) -> None:
    """Une ressource « à toi » (sans propriétaire nommé) est déjà à chacune de ses propriétaires : la leur partager
    ne leur donnerait rien, et un niveau plus bas les brimerait sur ce qui est à elles."""
    if level and not owner and person in set(call.frame.get(identity_c.OWNERS) or ()):
        raise Denied(400, "Elle est déjà à cette personne : c'est une de ses propriétaires.",
                     {"person": "déjà propriétaire"})


async def list_people(call: Call) -> dict[str, Any]:
    return {"items": people(call)}


def sharer(frame: Any, s: Shared, name: Callable[[str], str]) -> str:
    """Qui partage cette ressource, par son nom : qui décide d'une boîte, qui écrit d'un compte Teams, le propriétaire
    d'un service (``name`` : le nom d'une personne, par sa clé)."""
    if s.kind == "mail":
        return email_p.approver_name(frame, s.key)
    if s.kind == "teams":
        return teams_p.writer_of(frame, s.key)
    if s.kind == "agenda" and not s.owner:
        return identity_c.keepers(frame)
    return name(s.owner.removeprefix(PERSON))


async def list_shares(call: Call) -> dict[str, Any]:
    """Ce qu'elle partage (``given``), et ce qu'on lui partage (``received``), lus dans les réglages
    (``given_and_received``) : par sorte, ressource et personne."""
    settings = call.api.settings
    if settings is None:
        return {"given": [], "received": []}
    names = agenda_me.calendar_names(call.port("agenda"))
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
    """Le partage d'une boîte ou d'un compte Teams à cette personne, à ce niveau (vide : retiré). Relus puis réécrits
    d'un seul tenant (``Settings.writing``), avec ce qui en dérive (``shares``, rejournalisé : sa règle s'étend) : un
    partage retiré ailleurs entre-temps ne revient pas. ``check`` juge la fiche relue, sous le verrou : qui a le droit,
    c'est à qui appelle de le dire."""
    if kind == "agenda":
        await _write_calendar_share(settings, reconfigure, key, person, level, check)
        return
    async with settings.writing:
        cfg = settings.email() if kind == "mail" else settings.teams()
        spec = cfg.accounts.get(key)
        if spec is None:
            raise missing()
        if check is not None:
            check(spec)
        who = PERSON + person
        shares = {k: v for k, v in spec.shares.items() if k != who} | ({who: level} if level else {})
        try:
            if kind == "mail":
                await settings.save_email(MailConfig(accounts={**cfg.accounts, key: MailAccount.model_validate(
                    {**spec.model_dump(), "shares": shares})}))
            else:
                account = TeamsAccount.model_validate({**spec.model_dump(), "shares": shares})
                await settings.save_teams(cfg.model_copy(update={"accounts": {**cfg.accounts, key: account}}))
        except ValidationError as exc:
            raise refused(exc) from None
        if reconfigure is not None:
            await reconfigure()


async def _write_calendar_share(settings: Any, reconfigure: Callable[[], Awaitable[Any]] | None, calendar: str,
                                person: str, level: str, check: Callable[[Any], None] | None) -> None:
    """Le partage d'un agenda à cette personne (vide : retiré), rangé avec l'agenda (``Settings.share_calendar`` : son
    tableau suit), relu puis réécrit sous ``Settings.writing`` ; ``check`` juge son réglage relu (``CalendarSetting``),
    sous le verrou."""
    account, local = split_calendar_key(calendar)
    async with settings.writing:
        found = settings.agenda().account(account) if account else None
        if found is None:
            raise missing()
        if check is not None:
            check(found.setting(local))
        try:
            await settings.share_calendar(calendar, PERSON + person, level or None)
        except (ValidationError, ValueError) as exc:
            raise refused(exc) from None
        if reconfigure is not None:
            await reconfigure()


async def set_share(call: Call) -> dict[str, Any]:
    """Partager une de ses ressources avec une personne, à un niveau ; un niveau vide retire le partage."""
    kind = call.arg("kind", limit=10)
    key = call.arg("key", limit=200 if kind == "agenda" else 40)
    person = call.arg("person", limit=200)
    level = call.arg("level", limit=20)
    if kind not in KINDS:
        raise Denied(400, "« kind » : mail, teams, mcp ou agenda.")
    if level and level not in LEVELS:
        raise Denied(400, "« level » : lire, preparer ou servir (vide : retirer).")
    settings = settings_of(call)
    who = PERSON + person
    if not person:
        raise Denied(400, "« person » : la personne avec qui tu partages.", {"person": "valeur requise"})
    if person == call.me.person:
        # ni un partage à soi, ni le retrait de sa propre ligne (un service qui ne servirait plus à personne)
        raise Denied(400, "C'est déjà à toi : on ne se partage rien.", {"person": "c'est toi"})
    # partager va à une personne qui a un compte actif ; retirer, à toute personne à qui la ressource est partagée
    # (un compte désactivé depuis, une adresse reliée ailleurs) : un partage se retire toujours d'un clic
    if level and person not in {p["person"] for p in people(call)}:
        raise Denied(400, "Un partage va à une personne qui a un compte (pas à toi).", {"person": "personne inconnue"})
    if kind == "agenda":
        cal, held_level = agenda_me.mine(call).get(key) or (None, "")
        if cal is None:
            raise missing()
        if held_level != OWNED:
            raise Denied(403, "Seul son propriétaire partage cet agenda.")  # comme une boîte qu'on te partage
        holder = agenda_me.holder_person(agenda_p.params_of(call.frame), key)

        def calendar_hers(spec: Any) -> None:
            _not_hers_already(call, holder, person, level)

        await write_share(settings, call.api.reconfigure, kind, key, person, level, calendar_hers)
    elif kind in ("mail", "teams"):
        def hers(spec: Any) -> None:
            (mail_me if kind == "mail" else teams_me).owned(call, key)
            _not_hers_already(call, spec.owner, person, level)

        await write_share(settings, call.api.reconfigure, kind, key, person, level, hers)
    else:
        spec_m = mcp_me.mine(call).get(key)
        if spec_m is None:
            other = settings.mcp().servers.get(key)
            if other is not None and other.owner and PERSON + call.me.person in service_shares(other):
                raise Denied(403, "Seul son propriétaire partage ce service.")  # comme une boîte qu'on te partage
            raise missing()
        if level == SHARE_PREPARE:
            raise Denied(400, "Un service se partage pour lire ou pour s'en servir.")
        def access(spec: Any) -> dict[str, Any]:
            # calculées sur la fiche relue sous ``Settings.writing`` : une ligne retirée ailleurs entre-temps ne
            # revient pas, une ligne ajoutée ailleurs reste
            lines = [a.model_dump() for a in spec.access if tuple(a.who) != (who,)]
            if level:
                line = {"who": [who], "read": "seule", "act": "carte" if level == SHARE_USE else "non",
                        "keep": "prive"}
                lines.insert(1 if lines else 0, line)  # juste après la sienne : la première qui la désigne décide
            return {"access": lines}

        port = call.port("mcp")
        if port is None:
            raise Denied(503, "Les services ne sont pas branchés.")
        await port.settle(key, access)
    await audit(call.kernel, "moi.partage", by=call.me.handle, **audited_share(kind, key, person))
    said = "Partage retiré." if not level else f"Partagé avec {_name(call, person)} ({dict(SHARES)[level].lower()})."
    return {"ok": True, "message": said}


def routes(api: MeApiBase) -> list[Route]:
    r = api.route
    return [r("/people", list_people), r("/shares", list_shares), r("/shares/set", set_share, write=True)]
