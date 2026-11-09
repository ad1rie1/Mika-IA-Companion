"""Ses partages (ADR 0188) : ce qu'elle partage — ses boîtes, ses comptes Teams, ses services — avec qui et à quel
niveau ; ce qu'on lui partage ; les personnes à qui elle peut partager.

Seul le propriétaire partage, et seulement avec une personne qui a un compte — jamais un salon, une inconnue, « tout
le monde ». Une boîte ou un compte Teams partagé est rangé avec sa ressource et journalisé avec ses paramètres
(``shares``) : sa règle s'étend à la personne, au niveau donné (lire ; lire et préparer ; s'en servir). Un service
partagé reçoit une ligne d'accès pour la personne (ADR 0192) — lire : ses outils qui lisent ; s'en servir : aussi ceux
qui agissent, sur sa demande à elle ; retirer le partage retire la ligne.

Tous se lisent ici (``every_share``), et une seule écriture range celui d'une boîte ou d'un compte Teams
(``write_share``) : celle de son propriétaire, et celle de l'opérateur qui le retire dans Réglages › Droits › Partages
(ADR 0210) — seul le propriétaire le donne, jamais la console.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from starlette.routing import Route

from mika.adapters.mail.config import MailAccount, MailConfig
from mika.adapters.teams import TeamsAccount
from mika.app.moi import mail as mail_moi
from mika.app.moi import mcp as mcp_moi
from mika.app.moi import teams as teams_moi
from mika.app.moi.api import Call, Denied, MeApiBase, missing, person_of, refused
from mika.app.moi.common import OWN
from mika.contracts import identity as identity_c
from mika.plugins import email as email_p
from mika.plugins import teams as teams_p
from mika.runtime.operations import audit
from mika.vocab.access import PERSON, SHARE_PREPARE, SHARE_READ, SHARE_USE, SHARES

#: ce qui se partage
KINDS = ("mail", "teams", "mcp")
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


def _mcp_level(line: Any) -> str:
    return SHARE_USE if line.act != "non" else SHARE_READ


def _mcp_shares(spec: Any, owner: str) -> dict[str, str]:
    """Les partages d'un service : ses lignes d'une seule personne, autre que son propriétaire."""
    return {line.who[0]: _mcp_level(line) for line in spec.access
            if len(line.who) == 1 and line.who[0].startswith(PERSON) and line.who[0] != owner}


def every_share(settings: Any) -> list[Shared]:
    """Tous les partages, ressource par ressource : ceux rangés avec chaque boîte et chaque compte Teams, puis les
    lignes de chaque service qui a un propriétaire — ce que chaque personne lit sous « Partagé avec toi »."""
    out: list[Shared] = []
    for kind, accounts in (("mail", settings.email().accounts), ("teams", settings.teams().accounts)):
        for key, spec in sorted(accounts.items()):
            out += [Shared(kind, key, spec.label or key, spec.owner, who[len(PERSON):], level)
                    for who, level in sorted(spec.shares.items())]
    for name, spec in sorted(settings.mcp().servers.items()):
        if spec.owner:
            out += [Shared("mcp", name, name, spec.owner, who[len(PERSON):], level)
                    for who, level in sorted(_mcp_shares(spec, spec.owner).items())]
    return out


def _not_hers_already(call: Call, owner: str, person: str, level: str) -> None:
    """Une ressource « à toi » (sans propriétaire nommé) est déjà à chacune de ses propriétaires : la leur partager
    ne leur donnerait rien, et un niveau plus bas les brimerait sur ce qui est à elles."""
    if level and not owner and person in set(call.frame.get(identity_c.OWNERS) or ()):
        raise Denied(400, "Elle est déjà à cette personne : c'est une de ses propriétaires.",
                     {"person": "déjà propriétaire"})


async def list_people(call: Call) -> dict[str, Any]:
    return {"items": people(call)}


async def list_shares(call: Call) -> dict[str, Any]:
    """Ce qu'elle partage (``given``), et ce qu'on lui partage (``received``)."""
    settings = call.api.settings
    given: list[dict[str, Any]] = []
    received: list[dict[str, Any]] = []
    mine = PERSON + call.me.person
    if settings is not None:
        mail_cfg, teams_cfg = settings.email(), settings.teams()
        for kind, found, cfg in (("mail", mail_moi.boxes(call), mail_cfg.accounts),
                                 ("teams", teams_moi.accounts(call), teams_cfg.accounts)):
            for key, (a, level) in found.items():
                spec = cfg.get(key)
                if spec is None:
                    continue
                if level == OWN:
                    given += [{"kind": kind, "key": key, "title": a.name, "person": p[len(PERSON):],
                               "name": _name(call, p[len(PERSON):]), "level": lv} for p, lv in sorted(spec.shares.items())]
                else:
                    received.append({"kind": kind, "key": key, "title": a.name, "level": level,
                                     "owner_name": email_p.approver_name(call.frame, key) if kind == "mail"
                                     else teams_p.writer_of(call.frame, key)})
        for name, spec in sorted(settings.mcp().servers.items()):
            if spec.owner == mine:
                given += [{"kind": "mcp", "key": name, "title": name, "person": p[len(PERSON):],
                           "name": _name(call, p[len(PERSON):]), "level": lv}
                          for p, lv in sorted(_mcp_shares(spec, mine).items())]
            elif spec.owner and mine in _mcp_shares(spec, spec.owner):
                received.append({"kind": "mcp", "key": name, "title": name,
                                 "level": _mcp_shares(spec, spec.owner)[mine],
                                 "owner_name": _name(call, spec.owner[len(PERSON):])})
    return {"given": given, "received": received}


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


async def set_share(call: Call) -> dict[str, Any]:
    """Partager une de ses ressources avec une personne, à un niveau ; un niveau vide retire le partage."""
    kind = call.arg("kind", limit=10)
    key = call.arg("key", limit=40)
    person = call.arg("person", limit=200)
    level = call.arg("level", limit=20)
    if kind not in KINDS:
        raise Denied(400, "« kind » : mail, teams ou mcp.")
    if level and level not in LEVELS:
        raise Denied(400, "« level » : lire, preparer ou servir (vide : retirer).")
    settings = call.api.settings
    if settings is None:
        raise Denied(503, "Les réglages ne sont pas branchés.")
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
    if kind in ("mail", "teams"):
        def hers(spec: Any) -> None:
            (mail_moi if kind == "mail" else teams_moi).owned(call, key)
            _not_hers_already(call, spec.owner, person, level)

        await write_share(settings, call.api.reconfigure, kind, key, person, level, hers)
    else:
        spec_m = mcp_moi.mine(call).get(key)
        if spec_m is None:
            other = settings.mcp().servers.get(key)
            if other is not None and other.owner and PERSON + call.me.person in _mcp_shares(other, other.owner):
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
