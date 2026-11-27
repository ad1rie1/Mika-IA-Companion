"""Le port de l'annuaire (ADR 0298) : tous ceux qu'elle connaît, même sans leur avoir parlé — les personnes qu'elle lit
(un auteur Teams, un correspondant d'une boîte) et les organisations.

« Journaliser l'esprit, pas le monde » : les contacts vivent dans leur base (``contacts``), hors du journal, comme le
monde de Teams et du courrier. La faculté ``identity`` reste celle de qui lui parle ; un contact peut y être relié
(``person`` : elle lui parle aussi), sans que ses identifiants deviennent des moyens de communication de l'identité.

- **Un identifiant, un contact** : une sorte (``TEAMS_ID``, ``EMAIL``, ``PHONE``, ``DOMAIN``, ``COMPANY``,
  ``TENANT``) et une valeur normalisée (``normalized`` : un identifiant Teams sous sa forme canonique, quelle que soit
  celle reçue). Deux observations du même identifiant vont au même contact : c'est la preuve qui réunit (même adresse,
  même compte Microsoft). Un même nom seul ne réunit jamais : il se propose (``suggestions``).
- **Le juge des rapprochements** (ADR 0304) : ce qui pourrait être la même personne sans rien qui le prouve
  (``likenesses``) est jugé par le modèle ; son avis sur chaque paire (``Judgement``) vaut sur l'empreinte des deux
  fiches (``bases``, ``pair_basis``). Sûr de la même personne, il les réunit (``unite``, gardé : ``Joined``) ; sûr de
  deux, elles ne se proposent plus ; sinon elles se proposent avec son avis. Ses appels (``JudgeCall``) bornent son
  coût.
- **Un profil Teams** dit d'une personne son e-mail, ses numéros, son poste, son service et son entreprise :
  une observation peut ainsi aller au contact d'un autre identifiant (``joins``) — l'e-mail le prouve (``proof`` : deux
  contacts qui le portent se réunissent, sauf reliés à deux personnes différentes de l'identité), un numéro non (un
  standard se partage : déjà à quelqu'un d'autre, il reste où il est). L'entreprise (``COMPANY``) nomme
  l'organisation de la personne : celle de son domaine si elle n'a pas encore de nom à elle, sinon une organisation
  de ce nom, retrouvée par lui.
- **Où elle le voit** : une *vue* (``Sighting``) est un identifiant vu dans une source (``TEAMS``, ``MAIL``,
  ``PHONE_SOURCE``, ``TOLD``) sous un compte (la clé du compte Teams, de la boîte ; pour le téléphone, la personne
  dont c'est le téléphone ; pour ce qu'on lui raconte, la personne qui le lui a raconté) — combien de fois, la
  première et la dernière fois, le nom qu'il y porte, et pour le téléphone ses conversations (``Thread``). À qui est
  un contact se lit à la lecture, sur le propriétaire du compte de ses vues (``visible_sources`` ; ``person_accounts``
  pour les comptes qui sont des personnes) : jamais rangé avec lui.
- **Le téléphone** : un expéditeur WhatsApp ou SMS est un identifiant ``PHONE_APP`` (``<appli>:<empreinte>``,
  l'empreinte de sa clé ``phone:<empreinte>:<nom>`` : un contact renommé reste le même) ; un expéditeur que le
  téléphone ne nomme que par son numéro (``number_in_name``) est aussi ce numéro (``PHONE``), une preuve. Un numéro
  se range en E.164 quand c'est un numéro français sans ambiguïté (``06…`` → ``+336…``) : celui d'un profil Teams et
  celui du téléphone se retrouvent.
- **Ce qu'on lui raconte** : une personne dont on lui parle (une clé ``name:<portée>:<nom>`` de sa mémoire)
  est un identifiant ``TOLD_NAME`` ; un même prénom, d'un côté sans nom de famille, se propose aussi (plus faible).
- **Les organisations** : un domaine de courrier (hors des webmails publics, ``PUBLIC_DOMAINS``) fait une
  organisation (``ORG``), nommée d'après lui tant qu'on ne lui en sait pas mieux ; une personne de ce domaine y est
  rattachée (``org``), et une adresse générique (``noreply@``, ``support@``…, ``generic_address``) y est rangée, sans
  jamais faire une personne.
- **L'oubli** atteint ce cache (``forget``) : ``contact:<id>``, ``teams:<identifiant>``, ``mail:<adresse>``,
  ``phone:<empreinte>:<nom>`` (un expéditeur du téléphone), ``name:…`` (une personne dont on lui a parlé), ou la clé
  d'une personne de l'identité (ses contacts reliés, et ce que son téléphone et ses récits avaient apporté) ; chaque
  identifiant oublié laisse une empreinte et l'instant de l'oubli : ce qui le revoit, daté d'avant, ne le ramène pas.
- **Ce qu'elle en sait** : des faits courts (``Note``) qu'un portrait (le rôle ``portrait``) tire de ses
  derniers messages, rangés sous la vue (source, compte) d'où ils viennent : visibles de qui voit cette vue, repris
  au portrait suivant de la même vue, qui reçoit ses faits d'avant et rend la fiche entière (ADR 0303) ; oubliables
  un à un — un fait oublié laisse son empreinte (``note_print`` : ses mots, réduits à des empreintes), et le même fait
  reformulé ne se réapprend pas (``relearned``). Chaque passage est gardé (``Portrait``) : les plafonds par jour et
  « assez de nouveau depuis le dernier » se lisent sur eux.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from mika.ports.paging import Page, fold_text
from mika.ports.phone import APPS as PHONE_APPS
from mika.ports.teams import person_key
from mika.vocab.access import PERSON, SELF, SHARE_READ, reaches
from mika.vocab.ownership import holds

# ── les sortes d'identifiants ──
#: l'identifiant Teams d'une personne (son MRI, ``8:orgid:<guid>`` en minuscules, quelle que soit la forme reçue :
#: ``person_key``)
TEAMS_ID = "teams"
EMAIL = "email"
PHONE = "phone"
#: le domaine de courrier d'une organisation
DOMAIN = "domain"
#: le nom d'une entreprise (replié, ``normalized``) : l'organisation qu'un profil Teams donne à sa personne
COMPANY = "company"
#: l'organisation Teams (le locataire) d'une organisation : gardée seulement quand elle porte le nom de son entreprise
#: (un compte peut être celui d'un prestataire hébergé chez une autre)
TENANT = "tenant"
#: un expéditeur sur le téléphone de quelqu'un : ``<appli>:<empreinte>`` (``phone_app_value``) — l'empreinte de sa clé
#: ``phone:<empreinte>:<nom>`` (ADR 0120), sans le nom : un contact renommé sur le téléphone reste le même
PHONE_APP = "phone_app"
#: une personne dont on lui a parlé : la clé de sa mémoire, ``name:<portée>:<nom replié>`` (``faculties.memory``)
TOLD_NAME = "told"
KINDS = (TEAMS_ID, EMAIL, PHONE, DOMAIN, COMPANY, TENANT, PHONE_APP, TOLD_NAME)
#: les identifiants d'une organisation (jamais d'une personne)
ORG_KINDS = (DOMAIN, COMPANY, TENANT)
#: les identifiants qui ne sont pas des moyens de la joindre : une clé du téléphone, un nom raconté (leur valeur ne se
#: montre pas, ne se cherche pas, ne nomme pas une fiche)
OPAQUE_KINDS = (PHONE_APP, TOLD_NAME)

# ── les sources ──
TEAMS, MAIL = "teams", "mail"
#: les expéditeurs du téléphone d'une personne (le compte : sa clé) ; ce qu'une personne lui raconte (le compte : sa
#: clé, ``SELF`` pour ce qu'elle tient d'elle-même)
PHONE_SOURCE, TOLD = "phone", "told"
SOURCES = (TEAMS, MAIL, PHONE_SOURCE, TOLD)
#: les sources dont les comptes sont des personnes (``person_accounts``)
PERSON_SOURCES = (PHONE_SOURCE, TOLD)

# ── le téléphone ──
#: les familles d'applis du téléphone : ce que la console dit (« WhatsApp · 3 », « SMS · 1 »)
WHATSAPP, SMS = "whatsapp", "sms"
APP_FAMILY = {"whatsapp": WHATSAPP, "whatsapp_business": WHATSAPP, "messages": SMS, "samsung_messages": SMS}
#: la clé d'un expéditeur du téléphone (``contracts.phone.contact_key``), la clé d'un nom raconté (``memory``)
PHONE_PREFIX, NAME_PREFIX = "phone:", "name:"
#: un nom d'expéditeur qui n'est qu'un numéro (chiffres, blancs, points, tirets, parenthèses, « + » en tête)
_NUMBER_NAME = re.compile(r"\+?[\d\s.\-()/  ]+")

# ── les sortes de contacts ──
PERSON_KIND, ORG = "person", "org"

#: le sujet (au sens de l'oubli) d'un contact
CONTACT_PREFIX = "contact:"
#: les sujets que l'annuaire reconnaît aussi : une personne connue par Teams, un correspondant
TEAMS_PREFIX, MAIL_PREFIX = "teams:", "mail:"

#: les webmails publics : leur domaine ne dit rien de l'organisation de qui écrit
PUBLIC_DOMAINS = frozenset({
    "gmail.com", "googlemail.com", "outlook.com", "outlook.fr", "hotmail.com", "hotmail.fr", "live.com", "live.fr",
    "msn.com", "yahoo.com", "yahoo.fr", "ymail.com", "icloud.com", "me.com", "mac.com", "proton.me",
    "protonmail.com", "protonmail.ch", "pm.me", "laposte.net", "orange.fr", "wanadoo.fr", "free.fr", "sfr.fr",
    "neuf.fr", "bbox.fr", "numericable.fr", "aliceadsl.fr", "club-internet.fr", "gmx.fr", "gmx.com", "gmx.de",
    "gmx.net", "aol.com", "aol.fr", "yandex.com", "yandex.ru", "mail.com", "zoho.com", "tutanota.com",
    "tuta.io", "fastmail.com", "hey.com", "web.de", "libero.it", "mail.ru", "qq.com", "163.com",
})
#: les parties locales d'une adresse générique (sans casse, « . » et « _ » lus « - ») : elle est à l'organisation
GENERIC_LOCALS = frozenset({
    "noreply", "no-reply", "donotreply", "do-not-reply", "ne-pas-repondre", "nepasrepondre", "ne-repondez-pas",
    "support", "contact", "contacts", "info", "infos", "information", "informations", "newsletter", "newsletters",
    "news", "notification", "notifications", "notify", "alert", "alerts", "alerte", "alertes", "facturation",
    "factures", "facture", "billing", "invoice", "invoices", "bonjour", "hello", "admin", "administration",
    "postmaster", "mailer-daemon", "webmaster", "abuse", "security", "privacy", "dpo", "service-client",
    "serviceclient", "service-clients", "clients", "client", "sales", "commercial", "marketing", "team", "equipe",
    "accueil", "secretariat", "compta", "comptabilite", "help", "aide", "bounce", "bounces", "reply", "communication",
    "presse", "press", "office", "jobs", "recrutement", "careers", "rh", "hr", "mail", "email", "courrier",
})
#: le début d'une adresse générique (``noreply-1234@``, ``notifications+abc@``)
GENERIC_STARTS = ("noreply", "no-reply", "donotreply", "do-not-reply", "ne-pas-repondre", "nepasrepondre",
                  "notification", "newsletter", "bounce", "mailer-daemon")
#: les suffixes publics en deux parties qu'on reconnaît (le domaine d'une organisation garde alors trois parties)
_TWO_PART_SUFFIXES = frozenset({
    "co.uk", "org.uk", "ac.uk", "gov.uk", "ltd.uk", "plc.uk", "me.uk", "com.au", "net.au", "org.au", "edu.au",
    "gov.au", "co.nz", "org.nz", "co.jp", "ne.jp", "or.jp", "ac.jp", "co.za", "org.za", "com.br", "com.mx",
    "com.ar", "com.cn", "com.tr", "co.in", "co.il", "co.kr", "gouv.fr", "asso.fr", "nom.fr", "presse.fr", "tm.fr",
    "com.fr", "gouv.qc.ca", "qc.ca", "com.sg", "com.hk", "com.tw", "co.id", "com.my", "com.ph",
})
#: les domaines d'hébergement partagés : le domaine par défaut d'un locataire Microsoft (``lumen.onmicrosoft.com``),
#: ses sites — une adresse de ces domaines ne dit rien de l'organisation de qui écrit (deux entreprises sans domaine à
#: elles s'y retrouveraient) : ni organisation, ni nom d'organisation
HOSTED_DOMAINS = frozenset({"onmicrosoft.com", "onmicrosoft.de", "onmschina.cn", "sharepoint.com"})
#: la marque d'un invité dans un nom de connexion Microsoft (``x_gmail.com#ext#@hote.onmicrosoft.com``) : ce n'est pas
#: une adresse qu'on lui connaît
GUEST_MARK = "#ext#"
_SPACES = re.compile(r"\s+")


def normalized(kind: str, value: str) -> str:
    """La valeur d'un identifiant telle qu'elle se range et se compare : un identifiant Teams sous sa forme comparable
    (``ports.teams.person_key`` : ``8:orgid:<uuid>`` quelle que soit la forme reçue, ADR 0304) ; une adresse, un domaine
    en minuscules et sans blancs autour ; un numéro en E.164 quand on le peut (``e164``), sinon sans ce qui n'est ni
    chiffre ni « + » en tête ; un nom d'entreprise ou d'organisation Teams replié (casse et accents ignorés, blancs
    repliés), s'il a au moins deux lettres ou chiffres. Vide : rien à ranger (une adresse sans « @ », un numéro sans
    chiffre, « - » pour entreprise, une clé du téléphone sans « : »)."""
    raw = (value or "").strip()
    if kind == TEAMS_ID:
        return person_key(raw)
    if kind == PHONE:
        return e164(raw)
    if kind in (COMPANY, TENANT):
        folded = " ".join(fold_text(raw).split())
        return folded if sum(c.isalnum() for c in folded) >= 2 else ""
    raw = raw.lower()
    if kind == EMAIL:  # un nom de connexion d'invité (« #ext# ») n'est pas une adresse
        return raw if "@" in raw.strip("@") and not _SPACES.search(raw) and GUEST_MARK not in raw else ""
    if kind == DOMAIN:
        return raw.strip(".") if "." in raw and not _SPACES.search(raw) else ""
    if kind == PHONE_APP:
        return raw if ":" in raw.strip(":") and not _SPACES.search(raw) else ""
    return raw


def e164(number: str) -> str:
    """Un numéro tel qu'il se range : ses chiffres, avec « + » en tête s'il en avait un ou commençait par « 00 » (le
    préfixe international) ; un numéro français national (dix chiffres, ``0`` puis autre chose que ``0``) devient
    ``+33…`` sans son zéro, et le « (0) » d'un ``+33 (0)6…`` part. Ce qui ne se lit pas ainsi reste ses chiffres (un
    numéro court, un numéro étranger écrit sans indicatif). Vide sans chiffre."""
    raw = (number or "").strip()
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return ""
    plus = raw.startswith("+")
    if not plus and digits.startswith("00") and len(digits) > 4:
        plus, digits = True, digits[2:]
    if plus:
        if digits.startswith("330") and len(digits) == 12:
            digits = "33" + digits[3:]
        return "+" + digits
    if len(digits) == 10 and digits[0] == "0" and digits[1] != "0":
        return "+33" + digits[1:]
    return digits


def number_in_name(name: str) -> str:
    """Le numéro d'un expéditeur que le téléphone ne nomme que par lui (« +33 6 12 34 56 78 », « 06.12.34.56.78 » : un
    contact absent du carnet), rangé (``e164``) ; vide pour un nom (au moins une lettre) ou trop peu de chiffres."""
    raw = " ".join((name or "").split())
    if not raw or not _NUMBER_NAME.fullmatch(raw):
        return ""
    digits = sum(c.isdigit() for c in raw)
    return e164(raw) if 6 <= digits <= 15 else ""


def sender_digest(key: str) -> str:
    """L'empreinte d'une clé d'expéditeur du téléphone (``phone:<empreinte>:<nom>`` → ``<empreinte>``) ; vide sinon."""
    if not (key or "").startswith(PHONE_PREFIX):
        return ""
    parts = key.split(":", 2)
    digest = parts[1].strip().lower() if len(parts) >= 2 else ""
    return digest if digest and digest.isalnum() else ""


def phone_app_value(app: str, key: str) -> str:
    """L'identifiant d'un expéditeur du téléphone : ``<appli>:<empreinte>`` (vide sans empreinte ni appli)."""
    digest = sender_digest(key)
    app = (app or "").strip().lower()
    return f"{app}:{digest}" if digest and app else ""


def phone_app_values(key: str) -> tuple[str, ...]:
    """Les identifiants possibles d'une clé d'expéditeur, une par appli du téléphone (l'oubli ne sait pas laquelle)."""
    digest = sender_digest(key)
    return tuple(f"{app}:{digest}" for app in sorted(PHONE_APPS)) if digest else ()


def app_family(value: str) -> str:
    """La famille d'appli d'un identifiant du téléphone (``WHATSAPP``, ``SMS``) ; vide pour une autre."""
    return APP_FAMILY.get((value or "").split(":", 1)[0], "")


def person_accounts(places: Iterable[tuple[str, str]]) -> dict[tuple[str, str], str]:
    """Le propriétaire des comptes qui sont des personnes (``PERSON_SOURCES``) : le téléphone de quelqu'un, ce que
    quelqu'un lui a raconté — ``personne:<clé>`` ; ce qu'elle tient d'elle-même (``SELF``) est à tout le monde. À
    joindre aux comptes des ports ``teams`` et ``mail`` pour ``visible_sources``."""
    return {(source, account): SELF if account == SELF else PERSON + account
            for source, account in places if source in PERSON_SOURCES and account}


def subject_aliases(identifiers: Iterable[tuple[str, str]],
                    subjects: Callable[[str], Iterable[str]] | None = None) -> tuple[str, ...]:
    """Les sujets (au sens de l'oubli) que portent ces identifiants (sorte, valeur) : ``teams:<identifiant>``,
    ``mail:<adresse>``, les noms sous lesquels on lui en a parlé (``name:…``) et, si ``subjects`` les retrouve dans le
    journal (le port ``store``), ses clés d'expéditeur du téléphone (``phone:<empreinte>:<nom>``) — ce que Teams, le
    courrier, le téléphone et sa mémoire gardent sous eux."""
    prefix = {TEAMS_ID: TEAMS_PREFIX, EMAIL: MAIL_PREFIX}
    out: list[str] = []
    for kind, value in identifiers:
        if kind in prefix:
            out.append(f"{prefix[kind]}{value}")
        elif kind == TOLD_NAME:
            out.append(value)
        elif kind == PHONE_APP and subjects is not None:
            digest = sender_digest(PHONE_PREFIX + value.split(":", 1)[-1] + ":")
            out += list(subjects(f"{PHONE_PREFIX}{digest}:")) if digest else []
    return tuple(dict.fromkeys(a for a in out if a))


def mail_domain(address: str) -> str:
    """Le domaine d'une adresse, en minuscules (vide sans « @ »)."""
    _, at, domain = (address or "").strip().lower().rpartition("@")
    return domain.strip(".") if at else ""


def org_domain(domain: str) -> str:
    """Le domaine d'une organisation, d'après celui d'une adresse : ses deux dernières parties (``news.edf.fr`` →
    ``edf.fr``), trois derrière un suffixe public en deux parties (``impots.gouv.fr``, ``bbc.co.uk``) ; vide pour un
    webmail public (``PUBLIC_DOMAINS``), un domaine d'hébergement partagé (``HOSTED_DOMAINS`` et ses sous-domaines :
    ``lumen.onmicrosoft.com``) ou un domaine sans point."""
    parts = [p for p in (domain or "").strip().lower().strip(".").split(".") if p]
    if len(parts) < 2:
        return ""
    whole = ".".join(parts)
    if any(whole == h or whole.endswith("." + h) for h in HOSTED_DOMAINS):
        return ""
    keep = 3 if len(parts) >= 3 and ".".join(parts[-2:]) in _TWO_PART_SUFFIXES else 2
    if keep == 3 and len(parts) >= 4 and ".".join(parts[-3:]) in _TWO_PART_SUFFIXES:
        keep = 4
    found = ".".join(parts[-keep:])
    return "" if found in PUBLIC_DOMAINS or ".".join(parts) in PUBLIC_DOMAINS else found


def generic_address(address: str) -> bool:
    """Une adresse générique (``noreply@``, ``support@``, ``facturation@``…) : celle d'une organisation, jamais d'une
    personne. Lue sur sa partie locale, sans casse, sans ce qui suit un « + », « . » et « _ » lus « - »."""
    local = (address or "").strip().lower().rpartition("@")[0].split("+", 1)[0]
    local = local.replace(".", "-").replace("_", "-")
    return bool(local) and (local in GENERIC_LOCALS or local.startswith(GENERIC_STARTS))


def account_person(owner: str, owners: Sequence[str]) -> str:
    """La personne de l'identité à qui est un compte (sa clé), quand elle est une seule : ``personne:<clé>`` ; un
    compte « à toi » (vide) quand elle n'a qu'une propriétaire ; sinon personne (``elle``, plusieurs propriétaires)."""
    if owner.startswith(PERSON):
        return owner[len(PERSON):]
    if not owner and len(owners) == 1:
        return owners[0]
    return ""


def visible_sources(person: str, *, owners: Collection[str], accounts: Mapping[tuple[str, str], str],
                    shares: Mapping[tuple[str, str], Mapping[str, str]] | None = None) -> frozenset[tuple[str, str]]:
    """Les (source, compte) dont une personne (``person`` : sa clé) voit les contacts : un compte à elle — à son nom, ou
    « à toi » si elle est une des propriétaires (``owners``, ``vocab.ownership.holds``) —, un compte qu'on lui partage
    (au moins en lecture), et tout compte qui n'est à personne (``elle``) : ce qu'elle a lu ne se dit qu'à qui la
    source appartient, ce qui ne vient du compte de personne à tout le monde (ADR 0298). ``accounts`` : le propriétaire
    de chaque compte (vide, ``elle``, ``personne:<clé>``) ; un compte absent n'est vu de personne."""
    who = PERSON + person if person else ""
    is_owner = bool(person) and person in set(owners)
    out = set()
    for pair, owner in accounts.items():
        given = (shares or {}).get(pair, {})
        if owner == SELF or (who and holds(owner, who, owner=is_owner)) or (who and reaches(given.get(who, ""),
                                                                                             SHARE_READ)):
            out.add(pair)
    return frozenset(out)


@dataclass(frozen=True, slots=True)
class Observation:
    """Un identifiant vu dans une source, sous un compte : ``count`` fois (0 : le compte le désigne lui-même, ``own``),
    de ``first`` à ``last`` (µs, l'heure de la source), sous ce nom. Une observation datée d'avant l'oubli de son
    identifiant (``last`` au plus l'instant de l'oubli) ne le ramène pas."""

    kind: str
    value: str
    source: str
    account: str
    name: str = ""
    count: int = 1
    first: int = 0
    last: int = 0
    #: la personne du compte même (son identifiant Teams, l'adresse de la boîte) : ses comptes la désignent d'office
    own: bool = False
    #: ce qu'un profil Teams dit de son poste et de son service (vides : rien de dit — jamais un effacement)
    title: str = ""
    department: str = ""
    #: l'identifiant (sorte, valeur) dont cette observation dit la personne : elle va à son contact — un profil Teams
    #: dit l'e-mail et les numéros de sa personne, son entreprise et l'organisation Teams de son compte. Cet
    #: identifiant inconnu (oublié, ou refusé dans la même écriture), l'observation n'est pas rangée
    joins: tuple[str, str] = ()
    #: ``joins`` est une preuve (l'e-mail d'un profil) : déjà à un autre contact, l'identifiant réunit les deux
    #: (``merge`` ; jamais deux contacts reliés à deux personnes différentes de l'identité) ; sinon (un numéro), déjà
    #: à un autre contact, l'observation n'est pas rangée
    proof: bool = False
    #: les identifiants (sorte, valeur) que la même source prouve être cette personne (l'e-mail d'un profil, vu sur
    #: son identifiant Teams) : l'un d'eux oublié depuis (``last`` au plus l'instant de l'oubli), elle n'est pas
    #: rangée non plus — un profil d'avant l'oubli ne ramène pas la personne par un autre de ses identifiants
    same: tuple[tuple[str, str], ...] = ()
    #: une conversation où elle le voit (le téléphone : la clé opaque de la conversation), son titre (un groupe) — ses
    #: ``count`` messages s'y comptent aussi (``Thread``)
    thread: str = ""
    thread_title: str = ""
    group: bool = False
    #: l'entreprise qu'un profil Teams dit de sa personne, sur son identifiant Teams (vide : rien de dit) : ce qui prouve,
    #: pour qui voit cette vue, qu'elle est de cette organisation
    company: str = ""


@dataclass(frozen=True, slots=True)
class Thread:
    """Une conversation où elle voit un identifiant (une conversation du téléphone) : sa clé opaque, son titre (le nom
    d'un groupe, vide pour un tête-à-tête), combien de messages, la première et la dernière fois."""

    key: str
    title: str = ""
    group: bool = False
    count: int = 0
    first: int = 0
    last: int = 0


@dataclass(frozen=True, slots=True)
class Sighting:
    """Où elle voit un identifiant : une source, un compte, combien, quand, sous quel nom ; ses conversations (le
    téléphone), les plus récentes d'abord."""

    source: str
    account: str
    count: int
    first: int
    last: int
    name: str = ""
    own: bool = False
    threads: tuple[Thread, ...] = ()


@dataclass(frozen=True, slots=True)
class Identifier:
    id: int
    kind: str
    value: str
    #: une adresse générique rangée à son organisation
    generic: bool = False
    sightings: tuple[Sighting, ...] = ()


@dataclass(frozen=True, slots=True)
class ContactRef:
    id: int
    kind: str
    name: str


@dataclass(frozen=True, slots=True)
class ContactLine:
    """Un contact dans une page de l'annuaire : ce qu'en voit qui la demande (ses vues visibles seulement)."""

    id: int
    kind: str
    name: str
    #: son organisation (0 : aucune) et son nom
    org: int = 0
    org_name: str = ""
    #: la personne de l'identité à qui il est relié (vide : aucune)
    person: str = ""
    #: combien de fois elle l'a vu, la dernière fois (µs), les sources — dans ce qui est visible
    seen: int = 0
    last: int = 0
    sources: tuple[str, ...] = ()
    #: ses identifiants visibles : (sorte, valeur)
    identifiers: tuple[tuple[str, str], ...] = ()
    #: son poste et son service, d'après le dernier profil Teams visible qui les dit
    title: str = ""
    department: str = ""
    #: où elle le voit, dans ce qui est visible : (source, compte, combien de fois) — une adresse générique comptée par
    #: le domaine de son organisation (0 ici) ; à qui il est se lit sur le propriétaire de ces comptes (ADR 0298)
    places: tuple[tuple[str, str, int], ...] = ()
    #: une organisation : combien de ses personnes sont visibles
    members: int = 0
    #: combien de fois elle le voit dans chaque famille d'appli du téléphone (``WHATSAPP``, ``SMS``), dans ce qui est
    #: visible : la console dit « WhatsApp · 3 » plutôt que « Téléphone · 3 »
    apps: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True, slots=True)
class ContactSheet:
    """La fiche d'un contact : ses identifiants et où elle les voit, ses noms, son organisation, ses membres (une
    organisation), la personne de l'identité à qui il est relié — dans ce qui est visible."""

    id: int
    kind: str
    name: str
    person: str = ""
    org: ContactRef | None = None
    members: tuple[ContactRef, ...] = ()
    identifiers: tuple[Identifier, ...] = ()
    names: tuple[str, ...] = ()
    created: int = 0
    #: son poste et son service, d'après le dernier profil Teams visible qui les dit
    title: str = ""
    department: str = ""


@dataclass(frozen=True, slots=True)
class Suggestion:
    """Deux contacts qui pourraient être la même personne, sans rien qui le prouve : à valider — sauf ce que le juge
    (ADR 0304) a tranché sûrement, réuni d'office ou mis à part."""

    a: ContactRef
    b: ContactRef
    #: ``same_name`` (le même nom complet), ``initial`` (« G. Rousseau » et « Gilles Rousseau ») ou, plus faible,
    #: ``first_name`` (« Léa », dont on lui a parlé ou vue sur un téléphone, et « Léa Martin » : le même prénom, d'un
    #: côté sans nom de famille) ; ``words`` : des mots rares de leurs noms en commun, que seul le juge propose
    reason: str
    #: ce que le juge en a dit (``SAME``, ``APART`` ; vide : pas encore jugée, ou rien de lisible) et pourquoi, en ses
    #: mots — jamais sûr ici : ce qui l'est s'est fait d'office
    verdict: str = ""
    why: str = ""


# ── le juge des rapprochements (ADR 0304) ──
#: ce qu'il dit d'une paire : la même personne, deux personnes ; « » : rien de lisible (la paire attend du nouveau)
SAME, APART = "same", "apart"
#: un nom des fiches se dit au juge, au plus (caractères) ; sa raison, au plus
REASON_MAX = 300


@dataclass(frozen=True, slots=True)
class Likeness:
    """Deux personnes de l'annuaire qui pourraient être la même, à soumettre au juge : une règle de nom (``same_name``,
    ``initial``, ``first_name`` : celles des suggestions) ou ``words`` (des mots rares de leurs noms en commun, quelle
    que soit leur forme — « Kévin Massol » et « Kévin MASSOL-EXT ») ; ``strength`` les range, la plus forte d'abord."""

    a: int
    b: int
    rule: str
    strength: int


@dataclass(frozen=True, slots=True)
class Judgement:
    """Ce que le juge a dit d'une paire (``a`` < ``b``) : ``verdict`` (``SAME``, ``APART``, « » : rien de lisible),
    s'il en est sûr, pourquoi, sur quoi (``basis`` : l'empreinte de ce qu'il a vu des deux fiches, ``pair_basis`` —
    une fiche qui change se rejuge), quand, par quel appel."""

    a: int
    b: int
    verdict: str
    sure: bool = False
    reason: str = ""
    basis: str = ""
    at: int = 0
    call_id: str = ""


@dataclass(frozen=True, slots=True)
class Joined:
    """Une réunion faite d'office par le juge : la fiche gardée (son numéro d'aujourd'hui), son nom et celui de la
    fiche qui l'a rejointe au moment de la réunion, pourquoi, quand, par quel appel — de quoi la défaire (« Détacher »)."""

    keep: int
    kept: str
    gone: str
    reason: str = ""
    at: int = 0
    call_id: str = ""


@dataclass(frozen=True, slots=True)
class JudgeCall:
    """Un appel du juge : quand, lequel, combien de fiches il a vues, si sa réponse se lisait — les plafonds par jour
    se comptent sur eux."""

    at: int
    call_id: str
    cards: int = 0
    ok: bool = True


def pair_basis(a: str, b: str) -> str:
    """L'empreinte d'une paire à juger, d'après celles de ses deux fiches (``ContactsPort.bases``), dans n'importe quel
    ordre : la même tant qu'aucune ne change."""
    first, second = sorted((a or "", b or ""))
    return hashlib.sha256(f"pair\n{first}\n{second}".encode()).hexdigest()[:32]


# ── ce qu'elle en sait, à partir de ce qu'elle lit : ses faits, ses portraits ──
#: la sorte d'un fait tiré de ses messages : son rôle, un de ses sujets, avec quelle équipe elle travaille (sans nommer
#: personne), ce qu'elle attend ; sa façon d'être et d'écrire (``manner``), ce qu'il y a entre elle et la personne du
#: compte (``bond``, ADR 0303)
NOTE_KINDS = ("role", "topic", "relation", "expectation", "manner", "bond", "other")
#: un fait, au plus (caractères)
NOTE_MAX = 160
#: les faits d'une vue, au plus : la fiche qu'un portrait rend entière (ADR 0303)
NOTES_MAX = 12
#: deux faits dont les mots se recouvrent à ce point sont le même (un fait oublié ne se réapprend pas reformulé)
SAME_NOTE = 0.6


@dataclass(frozen=True, slots=True)
class Note:
    """Un fait qu'elle tire de ce qu'un contact écrit (``portrait``), gardé avec lui, sous la vue (source, compte) d'où
    il vient — visible de qui voit cette vue. ``confidence`` : sa confiance, de 0 à 1 ; ``ref`` : le message qui le
    fonde (la référence de sa source : un message Teams, un mail, ``p<seq>`` du téléphone), ``place`` : où il était
    (la conversation, l'objet du mail, venus d'ailleurs), ``said_at`` : sa date ; ``at`` : quand elle l'a appris ;
    ``call_id`` : l'appel du modèle qui l'a écrit."""

    id: int
    contact: int
    source: str
    account: str
    text: str
    kind: str = "other"
    confidence: float = 0.5
    ref: str = ""
    place: str = ""
    said_at: int = 0
    at: int = 0
    call_id: str = ""


@dataclass(frozen=True, slots=True)
class Portrait:
    """Un passage du portrait sur une vue d'un contact : quand, jusqu'à quel message il a lu (``upto`` : la date du
    plus récent), combien de messages, s'il a gardé des faits (``ok`` faux : une réponse illisible, ou rien de sûr —
    les faits d'avant restent) et l'appel du modèle."""

    contact: int
    source: str
    account: str
    at: int
    upto: int = 0
    read: int = 0
    ok: bool = True
    call_id: str = ""


def note_words(text: str) -> frozenset[str]:
    """Les mots d'un fait qui le disent (repliés, quatre lettres au moins) : ce que deux faits comparent."""
    return frozenset(w for w in re.findall(r"[a-z0-9]+", fold_text(text)) if len(w) >= 4)


def note_print(text: str) -> str:
    """L'empreinte d'un fait oublié (jamais son texte) : ses mots, chacun réduit à une courte empreinte, triés et
    joints — de quoi reconnaître le même fait reformulé, sans pouvoir le relire. Elle ne dépend pas de son contact :
    réuni à un autre, ce qu'on lui a fait oublier le suit."""
    return " ".join(sorted(hashlib.sha256(f"note\n{w}".encode()).hexdigest()[:10] for w in note_words(text)))


def relearned(text: str, prints: Iterable[str]) -> bool:
    """Ce fait est-il l'un de ceux qu'on lui a fait oublier (``prints`` : leurs empreintes, ``note_print``) ? Leurs
    mots se recouvrent au moins à ``SAME_NOTE`` (sur le plus court des deux) ; un fait sans mot qui compte, non."""
    mine = set(note_print(text).split())
    if not mine:
        return False
    for found in prints:
        theirs = set(found.split())
        if theirs and len(mine & theirs) / min(len(mine), len(theirs)) >= SAME_NOTE:
            return True
    return False


class ContactsPort(Protocol):
    async def observe(self, observations: Sequence[Observation], *, cursors: Mapping[str, int] | None = None) -> int:
        """Range ces observations, dans leur ordre (chacune s'ajoute à la vue de son identifiant dans sa source et son
        compte ; un identifiant inconnu fait son contact, va à son organisation, ou au contact de ``joins``) et, dans
        la même écriture, avance ces curseurs (``set_cursor``) : un lot rangé l'est avec l'endroit où sa lecture s'est
        arrêtée. Rend combien ont été rangées (une observation d'un identifiant oublié depuis n'est pas rangée)."""
        ...

    def page(self, *, visible: Collection[tuple[str, str]] | None = None, q: str = "", kind: str | None = None,
             page: int = 1, size: int = 25, linked: bool | None = None, org: int = 0) -> Page[ContactLine]:
        """Une page de contacts, le dernier vu d'abord : ceux qui ont une vue dans ``visible`` (des (source, compte) ;
        ``None`` : tout, pour une opératrice) ; ``q`` cherché dans leurs noms et leurs identifiants (chaque mot, sans
        casse ni accents) ; ``kind`` : personnes ou organisations ; ``linked`` : seulement ceux qui sont reliés à une
        personne de l'identité (vrai), ou qui ne le sont pas (faux : connus de loin, et les organisations) ; ``org`` :
        seulement les personnes de cette organisation (ses membres, l'écran Contacts)."""
        ...

    def links(self) -> dict[str, tuple[int, ...]]:
        """Les contacts reliés à une personne de l'identité, par personne (sa clé) : ce que l'annuaire de la console
        ajoute à qui lui parle."""
        ...

    def sheet(self, contact_id: int, *, visible: Collection[tuple[str, str]] | None = None) -> ContactSheet | None:
        """Sa fiche, réduite à ce qui est visible ; ``None`` s'il n'existe pas ou que rien n'en est visible."""
        ...

    def contact_of(self, kind: str, value: str) -> int | None:
        """Le contact de cet identifiant (``None`` : inconnu)."""
        ...

    def link(self, contact_id: int, person: str | None, *, replace: bool = True) -> bool:
        """Relie une personne (pas une organisation) à une personne de l'identité (``None`` : la délie) ; ``replace``
        faux : seulement si elle ne l'est pas déjà. Rend si quelque chose a changé."""
        ...

    def merge(self, keep_id: int, other_id: int) -> bool:
        """Réunit ``other_id`` dans ``keep_id`` (deux contacts de la même sorte) : ses identifiants, ses vues, ses
        membres le suivent ; ``ValueError`` (en français) pour deux sortes différentes ou deux personnes reliées à
        deux personnes différentes. Rend faux si l'un n'existe pas."""
        ...

    def detach(self, identifier_id: int) -> int:
        """Sépare un identifiant de son contact : il fait un contact à lui, avec ses vues, que les suggestions ne
        rapprochent plus de l'autre. Rend le nouveau contact ; ``ValueError`` pour le dernier identifiant d'un contact
        ou le domaine d'une organisation, 0 pour un identifiant inconnu."""
        ...

    def dismiss(self, a: int, b: int) -> bool:
        """Ces deux contacts ne sont pas la même personne : les suggestions ne les rapprochent plus."""
        ...

    def suggestions(self, limit: int = 50) -> list[Suggestion]:
        """Les personnes qui se ressemblent par le nom (le même nom complet, ou une initiale et le même nom), sans
        identifiant commun, ni écartées (``dismiss``), ni reliées à deux personnes différentes — moins celles que le
        juge a mises à part sûrement, plus celles qu'il croit la même personne sans en être sûr (ADR 0304), avec ce
        qu'il en dit, celles-là d'abord. Un avis ne vaut que sur ce qu'il a vu : une fiche qui a changé depuis ne le
        porte plus."""
        ...

    # ── le juge des rapprochements (ADR 0304) ──
    def likenesses(self, limit: int = 2000) -> list[Likeness]:
        """Les paires de personnes à soumettre au juge, la plus forte d'abord : celles des suggestions, et celles qui
        ont des mots rares de leurs noms en commun — jamais deux fiches écartées par une opératrice, ni reliées à deux
        personnes différentes, ni un nom raconté face à quelqu'un qui lui parle (c'est l'identité qui les relie)."""
        ...

    def bases(self, ids: Collection[int]) -> dict[int, str]:
        """L'empreinte de chacune de ces fiches : sa sorte, la personne qui lui est reliée, son organisation, ses
        identifiants et ses noms vus — ce qui fait qu'un avis du juge vaut encore."""
        ...

    def judgements(self, pairs: Collection[tuple[int, int]] | None = None) -> list[Judgement]:
        """Ce que le juge a dit de ces paires (``None`` : de toutes), la dernière fois."""
        ...

    def judged(self, call: JudgeCall | None, verdicts: Sequence[Judgement]) -> int:
        """Un appel du juge et ce qu'il a dit de chaque paire, gardés (un avis remplace celui d'avant sur la même
        paire) ; ``call`` vide : des avis sans appel (une paire qu'on n'a pas pu lui montrer). Une paire dont une fiche
        n'existe plus (réunie ou oubliée pendant l'appel) n'est pas gardée. Rend combien d'avis."""
        ...

    def judge_calls(self, *, since: int = 0) -> list[JudgeCall]:
        """Les appels du juge depuis ``since``, le plus récent d'abord."""
        ...

    def unite(self, a: int, b: int, *, reason: str = "", call_id: str = "") -> int:
        """Le juge est sûr que ces deux personnes sont la même : réunies dans celle qui a le plus d'histoire, comme une
        preuve les réunirait (jamais deux fiches qu'une opératrice a séparées, ni reliées à deux personnes
        différentes, ni autre chose que deux personnes, ni une fiche qui porte un nom raconté, reliée à personne, face à
        une fiche reliée à quelqu'un qui lui parle), la réunion gardée (``joined`` ; « Détacher » l'en retire). Rend
        la fiche gardée, 0 si rien n'a changé."""
        ...

    def joined(self, *, since: int = 0, limit: int = 100) -> list[Joined]:
        """Les réunions faites d'office par le juge depuis ``since``, la plus récente d'abord."""
        ...

    def cursor(self, name: str) -> int:
        """Où s'est arrêtée la lecture ``name`` d'une source (0 : jamais lue)."""
        ...

    def set_cursor(self, name: str, value: int) -> None: ...

    def sources(self) -> list[tuple[str, str]]:
        """Les (source, compte) dont il garde des vues."""
        ...

    def drop_source(self, source: str, account: str) -> int:
        """Un compte supprimé : ses vues s'effacent, et ce qui n'était vu que par lui. Rend combien de lignes."""
        ...

    def reset_source(self, source: str) -> int:
        """Toutes les vues d'une source s'effacent (et leurs conversations), ses identifiants restent : la source va se
        relire en entier sous une règle nouvelle ; ``prune_unseen`` emporte ensuite ce qu'elle n'a pas revu. Rend
        combien de lignes."""
        ...

    def prune_unseen(self, kind: str) -> int:
        """Les identifiants de cette sorte qui n'ont plus aucune vue s'effacent, et un contact qui n'a plus rien. Rend
        combien de lignes."""
        ...

    def discard(self, kind: str, value: str) -> int:
        """Un identifiant qui n'aurait jamais dû être rangé (le sien à elle : elle n'est pas son propre contact) : il
        part avec ses vues, sans pierre tombale, et son contact s'il n'a plus rien. Rend combien de lignes."""
        ...

    def drop_places(self, contact_id: int, places: Collection[tuple[str, str]]) -> int:
        """Ce qu'un contact doit à ces (source, compte) s'efface : ses vues, ses conversations, ses faits et ses
        portraits de là ; un identifiant qui n'était vu que là part, avec sa pierre tombale — le reste du contact
        demeure (une personne qui oublie un contact croisé aussi ailleurs n'oublie que le sien). Rend combien de
        lignes."""
        ...

    def naming(self, texts: Sequence[str], *, but: int = 0) -> list[bool]:
        """Chacun de ces textes nomme-t-il une autre personne de l'annuaire que ``but`` (un de ses noms vus : un nom
        de plusieurs mots, ou un seul mot écrit avec sa majuscule) ? Un fait sur quelqu'un ne dit rien d'un tiers."""
        ...

    async def forget(self, subject: str) -> int:
        """Oublie un contact (``contact:<id>``), celui d'un identifiant (``teams:<identifiant>``, ``mail:<adresse>``,
        ``phone:<empreinte>:<nom>``, ``name:…`` : une personne entière ; une adresse générique seule, son organisation
        reste), ou, pour une personne de l'identité (sa clé), ses contacts reliés et ce que son téléphone et ses récits
        avaient apporté (ce qui n'était vu que là part). Chaque identifiant oublié garde l'empreinte de sa valeur et
        l'instant de l'oubli ; les faits d'un autre contact qui nommaient une personne oubliée partent aussi. Rend
        combien de lignes."""
        ...

    # ── ce qu'elle en sait : ses faits, ses portraits ──
    def notes(self, contact_id: int, *, visible: Collection[tuple[str, str]] | None = None) -> list[Note]:
        """Les faits qu'elle a tirés de ce qu'il écrit, ceux des vues ``visible`` (``None`` : tous, pour une
        opératrice), les plus sûrs d'abord."""
        ...

    def note(self, note_id: int) -> Note | None:
        """Un fait (``None`` : inconnu, ou oublié)."""
        ...

    def portrayed(self, portrait: Portrait, notes: Sequence[Note] | None) -> int:
        """Un passage du portrait sur une vue d'un contact (``portrait``), gardé ; ``notes`` : ses faits — la fiche
        entière qu'il rend, ce qui tenait encore repris (ADR 0303) —, qui **remplacent** ceux de la même vue (contact,
        source, compte) — sauf ceux qu'on lui a fait oublier
        (``relearned``) ; ``None`` : rien de lisible, les faits d'avant restent. Rend combien de faits gardés (rien
        pour un contact qui n'existe plus)."""
        ...

    def portraits(self, *, since: int = 0, contacts: Collection[int] | None = None) -> list[Portrait]:
        """Les passages du portrait depuis ``since`` (µs), de ces contacts (``None`` : tous), le plus récent d'abord."""
        ...

    def forget_note(self, note_id: int) -> Note | None:
        """Oublie un fait : il part, et son empreinte (``note_print``, jamais son texte) reste avec son contact — le
        même fait, reformulé, ne se réapprend pas. Rend le fait oublié (``None`` : inconnu)."""
        ...


__all__ = [
    "APP_FAMILY", "COMPANY", "CONTACT_PREFIX", "DOMAIN", "EMAIL", "GENERIC_LOCALS", "GENERIC_STARTS", "GUEST_MARK",
    "HOSTED_DOMAINS", "KINDS", "MAIL",
    "MAIL_PREFIX", "NAME_PREFIX", "NOTES_MAX", "NOTE_KINDS", "NOTE_MAX", "OPAQUE_KINDS", "ORG", "ORG_KINDS",
    "PERSON_KIND", "PERSON_SOURCES", "PHONE", "PHONE_APP", "PHONE_PREFIX", "PHONE_SOURCE", "PUBLIC_DOMAINS",
    "APART", "REASON_MAX", "SAME", "SAME_NOTE", "SMS", "SOURCES", "TEAMS", "TEAMS_ID", "TEAMS_PREFIX", "TENANT", "TOLD",
    "TOLD_NAME", "WHATSAPP",
    "ContactLine", "ContactRef", "ContactSheet", "ContactsPort", "Identifier", "JudgeCall", "Joined", "Judgement",
    "Likeness", "Note", "Observation", "Portrait",
    "Sighting", "Suggestion", "Thread", "account_person", "app_family", "e164", "generic_address", "mail_domain",
    "normalized", "note_print", "note_words", "number_in_name", "org_domain", "pair_basis", "person_accounts",
    "phone_app_value", "phone_app_values", "relearned", "sender_digest", "subject_aliases", "visible_sources",
]
