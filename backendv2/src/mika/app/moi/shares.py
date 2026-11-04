"""Ses partages (ADR 0188) : ce qu'elle partage — ses boîtes, ses comptes Teams, ses services — avec qui et à quel
niveau ; ce qu'on lui partage ; les personnes à qui elle peut partager.

Seul le propriétaire partage, et seulement avec une personne qui a un compte — jamais un salon, une inconnue, « tout
le monde ». Une boîte ou un compte Teams partagé est rangé avec sa ressource et journalisé avec ses paramètres
(``shares``) : sa règle s'étend à la personne, au niveau donné (lire ; lire et préparer ; s'en servir). Un service
partagé reçoit une ligne d'accès pour la personne (ADR 0192) — lire : ses outils qui lisent ; s'en servir : aussi ceux
qui agissent, sur sa demande à elle ; retirer le partage retire la ligne.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError
from starlette.routing import Route

from mika.adapters.mail.config import MailAccount, MailConfig
from mika.adapters.teams import TeamsAccount
from mika.app.moi import Call, Denied, MeApi, missing, person_of
from mika.app.moi import mail as mail_moi
from mika.app.moi import mcp as mcp_moi
from mika.app.moi import teams as teams_moi
from mika.contracts import identity as identity_c
from mika.plugins import email as email_p
from mika.plugins import teams as teams_p
from mika.runtime.operations import audit
from mika.vocab.access import PERSON, SHARE_PREPARE, SHARE_READ, SHARE_USE, SHARES

#: ce qui se partage
KINDS = ("mail", "teams", "mcp")
LEVELS = tuple(level for level, _label in SHARES)


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
                if level == mail_moi.OWN:
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


async def _share_mail(call: Call, settings: Any, key: str, person: str, level: str) -> None:
    mail_moi.owned(call, key)
    cfg = settings.email()
    spec = cfg.accounts.get(key)
    if spec is None:
        raise missing()
    _not_hers_already(call, spec.owner, person, level)
    who = PERSON + person
    shares = {k: v for k, v in spec.shares.items() if k != who} | ({who: level} if level else {})
    try:
        await settings.save_email(MailConfig(accounts={**cfg.accounts, key: MailAccount.model_validate(
            {**spec.model_dump(), "shares": shares})}))
    except ValidationError as exc:
        raise Denied(400, str(exc).splitlines()[-1][:300]) from None


async def _share_teams(call: Call, settings: Any, key: str, person: str, level: str) -> None:
    teams_moi.owned(call, key)
    cfg = settings.teams()
    spec = cfg.accounts.get(key)
    if spec is None:
        raise missing()
    _not_hers_already(call, spec.owner, person, level)
    who = PERSON + person
    shares = {k: v for k, v in spec.shares.items() if k != who} | ({who: level} if level else {})
    account = TeamsAccount.model_validate({**spec.model_dump(), "shares": shares})
    await settings.save_teams(cfg.model_copy(update={"accounts": {**cfg.accounts, key: account}}))


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
        # relus puis réécrits d'un seul tenant (``Settings.writing``), avec ce qui en dérive (``shares``, rejournalisé :
        # sa règle s'étend) — un partage retiré ailleurs entre-temps ne revient pas
        async with settings.writing:
            await (_share_mail if kind == "mail" else _share_teams)(call, settings, key, person, level)
            if call.api.reconfigure is not None:
                await call.api.reconfigure()
    else:
        spec_m = mcp_moi.mine(call).get(key)
        if spec_m is None:
            other = settings.mcp().servers.get(key)
            if other is not None and other.owner and PERSON + call.me.person in _mcp_shares(other, other.owner):
                raise Denied(403, "Seul son propriétaire partage ce service.")  # comme une boîte qu'on te partage
            raise missing()
        if level == SHARE_PREPARE:
            raise Denied(400, "Un service se partage pour lire ou pour s'en servir.")
        lines = [a.model_dump() for a in spec_m.access if tuple(a.who) != (who,)]
        if level:
            line = {"who": [who], "read": "seule", "act": "carte" if level == SHARE_USE else "non", "keep": "prive"}
            lines.insert(1 if lines else 0, line)  # juste après la sienne : la première qui la désigne décide
        port = call.port("mcp")
        if port is None:
            raise Denied(503, "Les services ne sont pas branchés.")
        await port.settle(key, {"access": lines})  # ses réglages, relus et réécrits sous ``Settings.writing``
    await audit(call.kernel, "moi.partage", by=call.me.handle, subject_kind=kind, subject=key)
    said = "Partage retiré." if not level else f"Partagé avec {_name(call, person)} ({dict(SHARES)[level].lower()})."
    return {"ok": True, "message": said}


def routes(api: MeApi) -> list[Route]:
    r = api.route
    return [r("/people", list_people), r("/shares", list_shares), r("/shares/set", set_share, write=True)]
