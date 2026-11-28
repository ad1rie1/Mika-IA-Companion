"""Ce qui change ce que montrent les écrans de tous les jours (ADR 0308) : les sujets de la trame ``changed`` et ce
qu'une base tenue à côté du journal dit de chacune de ses écritures.

Les **sujets** (``TOPICS``) sont ceux du contrat (``docs/protocole-moi.md``, § 2 bis) : chacun dit quelle route se
relit, et sa clé (``KEYS``) ce qui y a changé — absente, tout le domaine. Le service qui les pousse est
``app/me/changes.py`` ; il traduit aussi le journal.

Une **base tenue à côté** (le courrier relevé, le cache de Teams, l'annuaire) prévient de chacune de ses écritures, une
fois validée, par un ``Change`` : le sujet qu'elle touche, les comptes (une boîte, un compte Teams) ou les sources de
l'annuaire, et ce qu'elle sait nommer (des conversations). Elle ne sait rien de qui regarde : le service filtre, par
les règles de l'API par personne. Deux sujets ne sont qu'au cache de Teams (``TEAMS_DRAFTS``, ``OUTBOX``) : le service
les traduit en sujets du contrat, et la boîte d'envoi réveille aussi la connexion en direct de l'extension. L'agenda
(ADR 0309) dit le sien (``AGENDA`` : ses comptes, ses agendas), que l'API de l'agenda (son lot 4) a fait entrer dans
le contrat.
"""

from __future__ import annotations

from dataclasses import dataclass

#: les sujets de la trame ``changed``, dans l'ordre du contrat
ME = "me"
MAIL = "mail"
MAIL_DRAFTS = "mail.drafts"
MAIL_WORK = "mail.work"
TEAMS = "teams"
TEAMS_REPLIES = "teams.replies"
TEAMS_WORK = "teams.work"
PHONE = "phone"
PHONE_POSITION = "phone.position"
PHONE_PHONES = "phone.phones"
CONTACTS = "contacts"
AGENDA = "agenda"
PROJECTS = "projects"
TRIPS = "trips"
SETTINGS = "settings"
TOPICS = (ME, MAIL, MAIL_DRAFTS, MAIL_WORK, TEAMS, TEAMS_REPLIES, TEAMS_WORK, PHONE, PHONE_POSITION, PHONE_PHONES,
          CONTACTS, AGENDA, PROJECTS, TRIPS, SETTINGS)
#: la clé de chaque sujet qui en a une : ce qu'elle nomme (les autres disent tout leur domaine)
KEYS = {MAIL: "boxes", MAIL_DRAFTS: "boxes", MAIL_WORK: "refs", TEAMS: "conversations", TEAMS_WORK: "conversations",
        PHONE: "conversations", AGENDA: "calendars", PROJECTS: "projects"}

#: ce que seul le cache de Teams dit : un brouillon (son texte, son état) ; la boîte d'envoi de l'extension
TEAMS_DRAFTS = "teams.drafts"
OUTBOX = "teams.outbox"


@dataclass(frozen=True, slots=True)
class Change:
    """Une écriture validée d'une base tenue à côté du journal : son sujet ; les comptes qu'elle touche (des boîtes,
    des comptes Teams — vide : elle ne sait pas lesquels) ; ce qu'elle y nomme (des conversations ``compte~id`` —
    vide : tout le compte) ; pour l'annuaire, les sources touchées (``(source, compte)``)."""

    topic: str
    accounts: tuple[str, ...] = ()
    keys: tuple[str, ...] = ()
    places: tuple[tuple[str, str], ...] = ()
