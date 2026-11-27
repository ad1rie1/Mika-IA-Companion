"""Ce qu'une personne a des agendas, dans son espace (ADR 0309, lot 4 ; 0310) : la base de l'API de l'agenda
(``api.py``, ``account_settings.py``), de ses partages (``sharing.py``) et du direct (``live.py``). Ce module n'importe
jamais ``api.py`` : c'est lui qui le lit.

**Ses agendas** (``mine``) : les siens — son compte du système ``moi:<sa clé>`` (« Mon agenda » né au besoin), un
compte branché à son nom, ou « à toi » si elle est une de ses propriétaires (la règle de ``vocab.ownership``,
ADR 0185) —, puis ceux qu'on lui partage, à leur niveau (``plugins/agenda/actions.py::level_of``) ; masqué par son
propriétaire, ou sous un compte décoché, un agenda partagé ne l'est plus. ``opened_calendar`` est la porte des routes
d'un agenda : un agenda qui n'est pas à elle est introuvable (404) ; ``owned_calendar`` réserve un geste à son
propriétaire (403, ``ONLY_OWNER``) ; un compte d'une autre n'existe pas (``must_own_account``).

**Ce qu'elle peut y faire** : s'en servir (``can_use`` : le sien, ou un partage « s'en servir »), y écrire d'ici
(``can_write`` : un agenda que son fournisseur laisse écrire, sous un compte actif), y répondre aux invitations
(``answers_reach`` : son fournisseur transmet-il la réponse ? sinon, pourquoi elle ne répond pas d'ici :
``NO_ANSWER_*``). Un agenda se montre à elle par ``calendar_json``, avec ce qu'elle peut en faire (``can``).

**Pour le direct et les partages** : les agendas qu'on lui partage et ses comptes (``seen_calendars``), à qui est un
agenda (``holder_person``), le nom de chaque agenda (``calendar_names``). Et la réponse d'une action de l'agenda qui a
fait quelque chose, avec ce qu'elle a fait (``done_with_made``), que les routes d'``api.py`` et
d'``account_settings.py`` rendent.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from mika.adapters.agenda import AgendaConfig
from mika.app.domains.agenda.settings import AgendaSettings
from mika.app.me.api import Call, Denied, done, missing
from mika.app.me.common import millis, settings_of
from mika.contracts import identity as identity_c
from mika.plugins.agenda import owner, params_of, reminder
from mika.plugins.agenda.actions import account_level, level_of
from mika.ports.agenda import (
    ICAL,
    KIND_WORDS,
    SYSTEM,
    Alert,
    Calendar,
    split_calendar_key,
    system_account,
    system_person,
)
from mika.vocab.access import PERSON, SHARE_USE, reaches
from mika.vocab.ownership import OWNED

ONLY_OWNER = "Seul son propriétaire règle cet agenda."


# ── à qui ──


def agenda_ports(call: Call) -> tuple[Any, Any]:
    store, providers = call.port("agenda"), call.port("agenda_providers")
    if store is None or providers is None:
        raise Denied(503, "L'agenda n'est pas branché sur ce serveur.")
    return store, providers


def mine(call: Call) -> dict[str, tuple[Calendar, str]]:
    """Ses agendas, par clé : l'agenda et son niveau — les siens (« Mon agenda » né au besoin), puis ceux qu'on lui
    partage."""
    store, providers = agenda_ports(call)
    system = getattr(providers, "system", None)
    if system is not None:
        system.ensure(system_account(call.me.person))
    p, frame = params_of(call.frame), call.frame
    out: dict[str, tuple[Calendar, str]] = {}
    for cal in store.calendars():
        level = level_of(p, frame, call.me.person, cal.key)
        if level:
            out[cal.key] = (cal, level)
    return out


def opened_calendar(call: Call, key: str) -> tuple[Calendar, str]:
    found = mine(call).get(key)
    if found is None:
        raise missing()
    return found


def owned_calendar(call: Call, key: str) -> Calendar:
    cal, level = opened_calendar(call, key)
    if level != OWNED:
        raise Denied(403, ONLY_OWNER)
    return cal


def can_use(level: str) -> bool:
    return level == OWNED or reaches(level, SHARE_USE)


def agenda_settings(call: Call) -> AgendaSettings:
    """Ses réglages (ses comptes, leurs connexions ; l'application Google du serveur est au cadre,
    ``app/connections.py``) ; 503 s'ils ne sont pas branchés."""
    found: AgendaSettings = settings_of(call).of(AgendaSettings)
    return found


def must_own_account(call: Call, key: str) -> None:
    """Un compte à elle (son compte du système, ou un compte branché à elle) ; un compte d'une autre n'existe pas."""
    if account_level(params_of(call.frame), call.frame, call.me.person, key) != OWNED:
        raise missing()
    if not system_person(key) and key not in agenda_settings(call).agenda().accounts:
        raise missing()


def person_name(call: Call, person: str) -> str:
    return identity_c.person_name(call.frame, person) or str(
        getattr(call.frame.get(identity_c.IDENTITY(person)), "name", "") or person)


def _owner_name(call: Call, account: str) -> str:
    holder = owner(params_of(call.frame), account)
    return person_name(call, holder[len(PERSON):]) if holder.startswith(PERSON) else identity_c.keepers(call.frame)


def account_kind(call: Call, account: str) -> str:
    if system_person(account):
        return SYSTEM
    p = params_of(call.frame)
    if account in p.kinds:
        return p.kinds[account]
    state = call.port("agenda").account(account) if call.port("agenda") is not None else None
    return state.kind if state is not None else ""


def can_write(call: Call, cal: Calendar, level: str) -> bool:
    """Peut-elle écrire dans cet agenda d'ici : le sien ou « s'en servir », un agenda que son fournisseur laisse
    écrire, sous un compte actif."""
    if not can_use(level) or not cal.writable:
        return False
    _store, providers = agenda_ports(call)
    conn = providers.connection(cal.account)
    provider = providers.of(conn.kind) if conn is not None else None
    return bool(conn is not None and provider is not None and conn.enabled
                and cal.account not in params_of(call.frame).accounts_off and provider.abilities(conn).write)


#: pourquoi elle ne répond pas d'ici à une invitation (une ligne sous ses boutons, que l'écran cache alors)
NO_ANSWER_SHARED = "Cet agenda t'est partagé sans t'en servir : seul son propriétaire répond à ses invitations."
NO_ANSWER_PRIVATE = "Cette invitation est privée : seul son propriétaire y répond."
NO_ANSWER_READ_ONLY = "Cet agenda ne s'écrit pas d'ici (en lecture seule, ou son compte est coupé) : réponds depuis " \
    "son application."
NO_ANSWER_TOLD = "Son serveur ne transmet pas les réponses aux invitations (pas de planification CalDAV) : réponds " \
    "depuis ta messagerie."


def answers_reach(call: Call, calendar: str) -> bool:
    """Une réponse d'ici atteint-elle l'organisatrice : le fournisseur de cet agenda la transmet-il (un serveur CalDAV
    sans planification, RFC 6638, ne la transmet pas ; avant de l'avoir découvert, on ne le sait pas) ?"""
    _store, providers = agenda_ports(call)
    conn = providers.connection(split_calendar_key(calendar)[0])
    provider = providers.of(conn.kind) if conn is not None else None
    return bool(conn is not None and provider is not None and provider.abilities(conn).invite)


def _setting(cfg: AgendaConfig, calendar: str) -> Any:
    account, local_ = split_calendar_key(calendar)
    found = cfg.account(account)
    return found.setting(local_) if found is not None else None


def alerts_json(alerts: Iterable[Alert]) -> list[dict[str, Any]]:
    """Des rappels du fournisseur : ``method`` (``notification``, ``email``) et ``minutes`` avant."""
    return [{"method": a.method, "minutes": a.minutes} for a in alerts]


def _abilities(call: Call, account: str) -> Any:
    _store, providers = agenda_ports(call)
    conn = providers.connection(account)
    provider = providers.of(conn.kind) if conn is not None else None
    return provider.abilities(conn) if provider is not None and conn is not None else None


def calendar_json(call: Call, cal: Calendar, level: str, cfg: AgendaConfig | None = None) -> dict[str, Any]:
    p = params_of(call.frame)
    kind = account_kind(call, cal.account)
    owned = level == OWNED
    setting = _setting(cfg, cal.key) if cfg is not None else None
    state = call.port("agenda").account(cal.account)
    writable = can_write(call, cal, level)
    abilities = _abilities(call, cal.account)
    out: dict[str, Any] = {
        "key": cal.key, "account": cal.account, "name": cal.name or split_calendar_key(cal.key)[1],
        "provider_name": cal.provider_name, "kind": kind,
        "kind_label": KIND_WORDS.get(kind, kind), "level": level, "owner_name": "" if owned else _owner_name(
            call, cal.account),
        "group": ("subscriptions" if kind == ICAL else "mine") if owned else "shared",
        "color": setting.color if setting is not None else "", "provider_color": cal.color, "primary": cal.primary,
        "hidden": cal.key in p.hidden, "enabled": cal.account not in p.accounts_off,
        "reminder": reminder(p, cal.key, kind), "reminder_set": p.reminders.get(cal.key, ""),
        "writable": writable, "read_only": not cal.writable,
        "can": {"write": writable, "respond": writable and bool(abilities is not None and abilities.invite),
                "settings": owned, "share": owned, "rights": owned,
                "remind": owned, "rename": owned},
        "synced_at": millis(cal.synced_at or (state.synced_at if state is not None else 0)),
        "provider_reminders": {"max": abilities.reminders if abilities is not None and cal.writable else 0,
                               "email": bool(abilities is not None and abilities.email_reminders),
                               "defaults": alerts_json(cal.reminders)},
    }
    if owned:
        out["error"] = state.error if state is not None else ""
        shares = setting.shares if setting is not None else p.shares.get(cal.key, {})
        out["shares"] = [{"person": who[len(PERSON):], "name": person_name(call, who[len(PERSON):]), "level": lv}
                         for who, lv in sorted(shares.items())]
    return out


# ── ce qu'une action a fait ──


def done_with_made(outcome: Any) -> dict[str, Any]:
    made = next((x for x in outcome.show if isinstance(x, dict)), None) if outcome.ok else None
    return done(outcome, **({"made": made} if made else {}))


# ── pour le direct et les partages ──


def seen_calendars(call: Call) -> tuple[frozenset[str], frozenset[str]]:
    """Ce que le direct lui fait relire (ADR 0308), sans base ni réglages : les agendas qu'on lui partage (tels que les
    paramètres journalisés les disent, encore ouverts) et ses comptes (son compte du système, ceux qui sont à elle) —
    tout agenda d'un compte à elle est à elle, même avant d'être dans les paramètres."""
    p, frame, person = params_of(call.frame), call.frame, call.me.person
    accounts = {system_account(person)} | {a for a in p.kinds if account_level(p, frame, person, a) == OWNED}
    shared = {c for c in p.shares if split_calendar_key(c)[0] not in accounts and level_of(p, frame, person, c)}
    return frozenset(shared), frozenset(accounts)


def is_hers(call: Call, calendar: str) -> bool:
    """Le direct : cet agenda la regarde-t-il (le sien, ou un partage encore ouvert) ?"""
    return bool(level_of(params_of(call.frame), call.frame, call.me.person, calendar))


def calendar_names(store: Any) -> dict[str, str]:
    """Le nom de chaque agenda connu de la base (ce que les partages montrent)."""
    return {c.key: c.name for c in store.calendars()} if store is not None else {}


def holder_person(p: Any, calendar: str) -> str:
    """À qui est un agenda, tel que les paramètres le disent (``personne:<clé>`` ; vide : à toi)."""
    return owner(p, split_calendar_key(calendar)[0])


