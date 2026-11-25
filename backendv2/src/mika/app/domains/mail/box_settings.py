"""Les réglages d'une boîte, pour qui est connecté (ADR 0187, 0310) : l'ajouter, la régler, la tester, la connecter à
Microsoft (ADR 0166), la retirer — ses routes, que ``api.py`` ajoute aux siennes.

Une boîte qu'une personne branche est à elle (ADR 0185) : à son nom (``personne:<clé>``), ou « à toi » si elle est une
de ses propriétaires — jamais à quelqu'un d'autre ; la partager est une délégation (ADR 0188), pas un changement de
propriétaire. Une boîte qui n'est pas à elle n'existe pas ici. Ses secrets ne repartent jamais : un mot de passe laissé
vide reste celui qui est gardé, tant que sa connexion ne change pas ; une boîte Microsoft ne joint que les serveurs de
Microsoft. Ce qui se dérive d'une boîte (à qui, active, la règle de son canal) est rejournalisé aussitôt
(``reconfigure``), comme depuis la console. Le cadre de ces réglages est dans ``app/me/settings.py`` : son compte,
comment part ce qu'elle prépare (la règle de son canal, ADR 0207), et les aides qu'une boîte et un compte Teams se
partagent.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError
from starlette.routing import Route

from mika.adapters.mail.config import MICROSOFT, MailAccount, MailConfig
from mika.app.domains.mail import api as mail_me
from mika.app.me import settings as settings_me
from mika.app.me.api import Call, Denied, MeApiBase, done, form, missing, refused
from mika.app.me.common import own_room, settings_of
from mika.app.me.hosts import public_only
from mika.kernel import forms
from mika.ports.mail import ACCOUNT_KEY
from mika.runtime.operations import audit
from mika.vocab.access import MAIL

#: ce qu'une personne règle d'une boîte (``owner`` n'y est pas : une boîte reste à qui l'a branchée)
MAIL_FIELDS = ("label", "address", "enabled", "auth", "imap_host", "imap_port", "imap_ssl", "user", "password",
               "folders", "sync_all", "keep_all", "since_days", "oauth_client_id", "oauth_tenant", "smtp_host", "smtp_port",
               "smtp_security", "smtp_user", "smtp_password", "save_sent", "voice", "display_name", "sender_name",
               "tone", "instructions", "signature", "triage_instructions")
#: ses secrets : jamais rendus, laissés vides ils restent
MAIL_SECRETS = ("password", "smtp_password")
#: la connexion d'une boîte : quand elle change, ses secrets se redonnent (ils ne partent jamais vers un autre hôte)
IMAP_CONNECTION = ("auth", "imap_host", "imap_port", "imap_ssl", "user", "oauth_client_id", "oauth_tenant")
SMTP_CONNECTION = ("smtp_host", "smtp_port", "smtp_security", "smtp_user")
#: les serveurs qu'une boîte fait joindre
HOSTS = ("imap_host", "smtp_host")
#: ce qui vise chacun : changer son port ou sa sécurité, c'est viser un autre service de cet hôte
TARGETS = {"imap_host": ("imap_host", "imap_port", "imap_ssl"),
           "smtp_host": ("smtp_host", "smtp_port", "smtp_security")}
#: les serveurs de Microsoft : le seul endroit où le jeton d'une boîte Microsoft se présente (ADR 0166)
MICROSOFT_HOSTS = (".office365.com", ".outlook.com")
#: ce que dit un serveur refusé à une boîte Microsoft
NOT_MICROSOFT = "un serveur de Microsoft (outlook.office365.com, smtp.office365.com…)"


def _traces(call: Call) -> set[str]:
    """Les clés de boîte dont sa vie garde une trace (ses mails remarqués, ses envois, ses brouillons, ses demandes)."""
    s = mail_me.state(call)
    return {*(m.account for m in s.mails.values()), *(x.account for x in s.sent.values()),
            *(d.account for d in s.drafts.values()), *(a.account for a in s.asked.values())}


def _microsoft_host(host: str) -> bool:
    name = host.strip().rstrip(".").lower()
    return any(name.endswith(suffix) for suffix in MICROSOFT_HOSTS)


def _changed(before: Any, values: dict[str, Any], fields: tuple[str, ...]) -> bool:
    return any(f in values and str(values[f]) != str(getattr(before, f)) for f in fields)


def _box_settings(key: str, a: MailAccount) -> dict[str, Any]:
    values = {f: getattr(a, f) for f in MAIL_FIELDS if f not in MAIL_SECRETS}
    values["folders"] = list(a.folders)
    return {"box": key, "values": values, "secrets": {f: bool(getattr(a, f)) for f in MAIL_SECRETS},
            "ready": a.ready, "can_send": a.can_send, "microsoft": a.microsoft}


async def box_get(call: Call) -> dict[str, Any]:
    key = call.arg("box", limit=40)
    mail_me.owned(call, key)
    found = settings_of(call).named("mail").email().accounts.get(key)
    if found is None:
        raise missing()
    got = _box_settings(key, found)
    port = call.port("mail")
    signin = port.signin(key) if port is not None and found.microsoft else None
    got["signin"] = {"state": signin.state, "code": signin.code, "url": signin.url, "until": signin.until // 1000,
                     "error": signin.error} if signin is not None else None
    got["rules"] = settings_me._rules_json(call, f"{MAIL}:{key}")
    return got


def _kept_secrets(before: MailAccount, values: dict[str, Any]) -> None:
    """Un secret laissé vide reste — sauf si sa connexion change : il ne part jamais vers un autre serveur. L'envoi
    laissé sans mot de passe se sert de celui de la lecture (``smtp_password or password``) : changer le serveur
    d'envoi le redemande aussi, à moins de le redonner pour lire dans le même envoi. Une connexion qu'on retire (son
    serveur vidé : une boîte qui ne fait que lire) ne redemande rien : rien ne part plus."""
    given = {s for s in MAIL_SECRETS if values.get(s)}
    microsoft = values.get("auth", before.auth) == MICROSOFT
    for secret, connection, host in (("password", IMAP_CONNECTION, "imap_host"),
                                     ("smtp_password", SMTP_CONNECTION, "smtp_host")):
        if secret in given:
            continue
        if not str(values.get(host, getattr(before, host)) or "").strip():
            values[secret] = getattr(before, secret)  # plus de serveur (une boîte qui ne fait que lire) : il reste
            continue
        # ce qui partirait vers cette connexion : son secret, ou pour l'envoi sans le sien, celui de la lecture
        outgoing = getattr(before, secret) or (secret == "smtp_password" and "password" not in given
                                                and before.password)
        if outgoing and _changed(before, values, connection):
            if microsoft:
                values[secret] = ""  # une boîte Microsoft n'a pas de mot de passe (lire ni envoyer) : il part
                continue
            raise Denied(400, "La connexion a changé : redonne le mot de passe.",
                         {secret: "à redonner pour cette connexion"})
        values[secret] = getattr(before, secret)


async def box_save(call: Call) -> dict[str, Any]:
    """Créer une boîte (sans ``box``), ou régler une des siennes. Elle est à qui la branche ; ses secrets laissés
    vides restent, tant que sa connexion ne change pas. Une création redite avec la même clé d'envoi ne refait
    rien."""
    if call.arg("box", limit=40):
        return await _box_save(call)
    return await call.once(lambda: _box_save(call))


async def _box_save(call: Call) -> dict[str, Any]:
    settings = settings_of(call)
    cfg = settings.named("mail").email()
    values = settings_me._values(call, MAIL_FIELDS)
    key = call.arg("box", limit=40)
    before: MailAccount | None = None
    if key:
        mail_me.owned(call, key)
        if key not in cfg.accounts:
            raise missing()
        before = cfg.accounts[key]
        _kept_secrets(before, values)
        merged = {**before.model_dump(), **values, "owner": before.owner, "shares": before.shares}
        hosts = {host: merged.get(host) for host, parts in TARGETS.items() if _changed(before, values, parts)}
        # une boîte Microsoft ne présente son jeton qu'aux serveurs de Microsoft : à vérifier quand ils changent, ou
        # quand elle le devient
        microsoft = hosts if before.microsoft else {f: merged.get(f) for f in HOSTS}
    else:
        own_room(call, sum(1 for a in cfg.accounts.values() if a.owner == settings_me._owner_for(call)))
        key = settings_me._slug(str(values.get("label") or values.get("address") or ""),
                                set(cfg.accounts) | _traces(call), ACCOUNT_KEY)
        merged = {**values, "owner": settings_me._owner_for(call)}
        hosts = microsoft = {f: merged.get(f) for f in HOSTS}
    await public_only(call, hosts)
    if merged.get("auth") == MICROSOFT:
        bad = {f: NOT_MICROSOFT for f, host in microsoft.items() if host and not _microsoft_host(str(host))}
        if bad:
            raise Denied(400, "Une boîte Microsoft ne joint que les serveurs de Microsoft : son jeton ne se présente "
                              "nulle part ailleurs.", bad)
    bounds = forms.within(forms.describe(MailAccount), merged)  # les bornes de la console (un port, une fenêtre)
    if bounds:
        raise Denied(400, "Le formulaire a des erreurs.", bounds)
    try:
        account = MailAccount.model_validate(merged)
    except ValidationError as exc:
        raise refused(exc) from None
    # relues puis réécrites d'un seul tenant : ce qu'une autre personne vient d'enregistrer reste (les serveurs, plus
    # longs à vérifier, l'ont été avant)
    async with settings.writing:
        cfg = settings.named("mail").email()
        if before is not None:
            if key not in cfg.accounts:
                raise missing()
            if cfg.accounts[key] != before:
                raise Denied(409, "Cette boîte vient d'être réglée ailleurs : rouvre-la, puis recommence.")
        else:
            own_room(call, sum(1 for a in cfg.accounts.values() if a.owner == settings_me._owner_for(call)))
            if key in cfg.accounts:
                key = settings_me._slug(str(values.get("label") or values.get("address") or ""),
                                set(cfg.accounts) | _traces(call), ACCOUNT_KEY)
        try:
            new = MailConfig(accounts={**cfg.accounts, key: account})
        except ValidationError as exc:
            raise refused(exc) from None
        await settings.named("mail").save_email(new)
        await settings_me._rejournal(call)
    await audit(call.kernel, "moi.boite", by=call.me.handle, subject_kind="compte", subject=key)
    return {"ok": True, "message": "Boîte enregistrée.", "box": key, "ready": account.ready}


async def box_remove(call: Call) -> dict[str, Any]:
    """Retirer une de ses boîtes : elle n'est plus relevée ; ce qu'elle en a appris reste dans sa vie."""
    settings = settings_of(call)
    key = call.arg("box", limit=40)
    mail_me.owned(call, key)
    async with settings.writing:
        cfg = settings.named("mail").email()
        if key not in cfg.accounts:
            raise missing()
        await settings.named("mail").save_email(MailConfig(accounts={k: a for k, a in cfg.accounts.items() if k != key}))
        await settings_me._rejournal(call)
    await audit(call.kernel, "moi.boite_retiree", by=call.me.handle, subject_kind="compte", subject=key)
    return {"ok": True, "message": "Boîte retirée."}


async def box_test(call: Call) -> dict[str, Any]:
    key = call.arg("box", limit=40)
    mail_me.owned(call, key)
    call.probe()
    return done(await call.act("email.tester", form(), subject=key))


async def box_microsoft(call: Call) -> dict[str, Any]:
    """Connecter une boîte Microsoft (ADR 0166) : un code à entrer chez Microsoft ; ``GET …/mail/box`` dit ensuite
    où en est la connexion."""
    key = call.arg("box", limit=40)
    mail_me.owned(call, key)
    return done(await call.act("email.microsoft", form(), subject=key))


def routes(api: MeApiBase) -> list[Route]:
    r = api.route
    return [r("/mail/box", box_get), r("/mail/box/save", box_save, write=True),
            r("/mail/box/remove", box_remove, write=True), r("/mail/box/test", box_test, write=True),
            r("/mail/box/microsoft", box_microsoft, write=True)]
