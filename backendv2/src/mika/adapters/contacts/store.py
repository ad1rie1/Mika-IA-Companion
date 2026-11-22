"""L'annuaire (la base ``contacts``, déclarée dans ``models`` : SQLite pour les tests, MariaDB en service — ADR 0101,
0298) : les personnes et les organisations qu'elle connaît, leurs identifiants, et où elle les voit.

- **Un identifiant, un contact.** Une observation d'un identifiant connu s'ajoute à sa vue (même source, même compte) ;
  un identifiant inconnu fait son contact — une personne —, ou va à son organisation : une adresse générique d'un
  domaine d'organisation (``ports.contacts.generic_address``) n'est jamais une personne. Une adresse d'un domaine
  d'organisation (hors webmails publics) rattache sa personne à l'organisation de ce domaine, née au besoin et nommée
  d'après lui ; le domaine a ses vues (chaque observation d'une adresse de ce domaine), qui disent où on la voit.
- **Ce qui se recalcule** à chaque écriture qui touche un contact : son nom (le plus récent qu'on lui voit ; une
  organisation, son domaine) et ce qu'une recherche compare (``search``). Une page, une fiche lues pour quelqu'un
  (``visible``) ne disent que ce que ses vues visibles disent : le nom qu'il porte là, ces identifiants-là.
- **Réunir, séparer** : ``merge`` (une opératrice, ou une preuve) déplace identifiants, vues et membres ; ``detach``
  sépare un identifiant et écarte la paire des suggestions ; ``suggestions`` rapproche par le nom seul, sans jamais
  réunir.
- **Un profil Teams** (``Observation.joins``) : son e-mail et ses numéros vont au contact de sa personne ; l'e-mail
  déjà à un autre contact les réunit (``_prove`` : on garde celui qui a le plus d'histoire ; jamais deux contacts
  reliés à deux personnes différentes de l'identité), un numéro déjà à quelqu'un d'autre reste où il est. Son
  entreprise (``COMPANY``) nomme l'organisation de son domaine tant qu'elle n'a pas de nom à elle, et y ramène une
  organisation qui n'avait que ce nom ; sans organisation de domaine, la personne va à l'organisation de ce nom, née
  au besoin. Deux organisations à domaine ne se réunissent jamais par leur nom. L'organisation Teams (``TENANT``) se
  range à l'organisation de sa personne, à elle seule. Son poste et son service sont ceux de sa vue.
- **Le téléphone et ce qu'on lui raconte** (lot 5) : un expéditeur du téléphone (``PHONE_APP``) et un nom raconté
  (``TOLD_NAME``) sont des identifiants comme les autres, sans valeur à montrer ni à chercher (``OPAQUE_KINDS``) ; une
  vue du téléphone garde ses conversations (``threads`` : les plus récentes). Une fiche que le téléphone ne connaît
  que par un numéro (un expéditeur hors du carnet, sans nom) *est* ce numéro : le profil qui le dit la réunit à sa
  personne, d'où qu'elle arrive en premier (``_bare``) — un numéro ne réunit jamais deux fiches qui ont un nom.
- **L'oubli** efface le contact entier (ou la seule adresse générique d'une organisation) et garde, de chaque
  identifiant, l'empreinte et l'instant : une observation datée d'avant ne le ramène pas. Une organisation qui
  n'existait que par une personne oubliée part avec elle.
- **Ce qu'elle en sait** (lot 6) : les faits d'un portrait (``notes``) remplacent ceux de la même vue ; un fait oublié
  laisse l'empreinte de ses mots (``notes_forgotten``), et le même fait reformulé n'est plus gardé ; chaque passage
  est noté (``portraits``). Ils suivent le contact quand il est réuni à un autre, et partent avec lui, ou avec le
  compte d'où ils viennent.

Une seule connexion sous SQLite, partagée sous ``_lock`` ; une écriture est une session courte (``begin``), faite
hors de la boucle d'événements pour ce qui peut être long (``observe``, ``forget``).
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import threading
import time
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import String, and_, case, delete, exists, func, literal, or_, select, update
from sqlalchemy.orm import Session, aliased, sessionmaker

from mika.adapters.contacts.models import (
    ACCOUNT,
    PERSON,
    REF,
    VALUE,
    WORD,
    ContactRow,
    CursorRow,
    DismissedRow,
    ForgottenRow,
    IdentifierRow,
    NoteForgottenRow,
    NoteRow,
    PortraitRow,
    SightingRow,
    ThreadRow,
    fit,
)
from mika.adapters.database import Target, as_target
from mika.ports.contacts import (
    COMPANY,
    CONTACT_PREFIX,
    DOMAIN,
    EMAIL,
    KINDS,
    MAIL_PREFIX,
    NAME_PREFIX,
    OPAQUE_KINDS,
    ORG,
    ORG_KINDS,
    PERSON_KIND,
    PERSON_SOURCES,
    PHONE,
    PHONE_APP,
    PHONE_PREFIX,
    TEAMS_ID,
    TEAMS_PREFIX,
    TENANT,
    TOLD_NAME,
    ContactLine,
    ContactRef,
    ContactSheet,
    Identifier,
    Note,
    Observation,
    Portrait,
    Sighting,
    Suggestion,
    Thread,
    app_family,
    generic_address,
    mail_domain,
    normalized,
    note_print,
    org_domain,
    phone_app_values,
    relearned,
)
from mika.ports.paging import Page, fold_text, words_of
from mika.ports.sql import CONTACTS, insert_ignore, upsert

C, N, S, D, T = ContactRow, IdentifierRow, SightingRow, DismissedRow, ThreadRow
NT, NF, P = NoteRow, NoteForgottenRow, PortraitRow

#: un nom vu, au plus (caractères)
NAME_MAX = 200
#: une organisation montre au plus tant de membres sur sa fiche, parmi les premiers venus (ceux qu'on lit pour savoir
#: lesquels sont visibles)
MEMBERS_MAX = 200
MEMBERS_SCANNED = 2000
#: un même nom chez plus de tant de contacts ne se propose plus (un nom de service, pas une personne)
SAME_NAME_MAX = 20
#: une vue garde au plus tant de conversations (les plus récentes)
THREADS_MAX = 20
#: un prénom seul se propose s'il a au moins tant de lettres (« Jo » ne rapproche personne)
FIRST_NAME_MIN = 3
#: ce qui sépare les mots d'un nom comparé (``Rousseau, Gilles`` : deux mots)
_NAME_MARKS = str.maketrans({c: " " for c in ".,;:()[]{}\"'«»“”‘’/\\|_"})


def _now_us() -> int:
    return time.time_ns() // 1000


def _print(kind: str, value: str) -> str:
    """L'empreinte d'un identifiant oublié (jamais sa valeur)."""
    return hashlib.sha256(f"{kind}\n{value}".encode("utf-8", "surrogatepass")).hexdigest()


def clean_name(name: str) -> str:
    """Un nom vu, rangé : blancs repliés, sans guillemets autour, borné ; vide pour une adresse donnée comme nom."""
    found = " ".join((name or "").replace("\x00", " ").split()).strip("\"'“”«»‘’ ")
    return "" if "@" in found else found[:NAME_MAX]


def clean_role(text: str) -> str:
    """Un poste, un service : blancs repliés, borné."""
    return " ".join((text or "").replace("\x00", " ").split())[:NAME_MAX]


def name_words(name: str) -> list[str]:
    """Les mots d'un nom, comparés (repliés, sans ponctuation) : « ROUSSEAU, Gilles » → ``rousseau``, ``gilles``."""
    return fold_text(name).translate(_NAME_MARKS).split()


def _visible(visible: Collection[tuple[str, str]] | None, on: Any = S) -> list[Any]:
    """La condition « une vue de ces (source, compte) » (``None`` : toutes), sur les vues ``on`` (un alias)."""
    if visible is None:
        return []
    pairs = sorted({(fit(s, WORD), fit(a, ACCOUNT)) for s, a in visible})
    return [or_(*(and_(on.source == s, on.account == a) for s, a in pairs))]


def _proof(visible: Collection[tuple[str, str]]) -> Any:
    """La condition « l'organisation de cette personne se prouve dans ces vues » (corrélée au contact ``C``) : une
    adresse visible du domaine de son organisation, ou un profil Teams visible qui dit son entreprise. Sans elle, qui
    voit l'organisation par un autre de ses membres n'apprend pas que cette personne en est (la preuve lue dans le
    compte d'une autre ne se dit pas)."""
    mine, seen, theirs = aliased(N), aliased(S), aliased(N)
    domain = and_(theirs.kind == DOMAIN, mine.kind == EMAIL,
                  or_(mine.value.like(literal("%@", String) + theirs.value),
                      mine.value.like(literal("%.", String) + theirs.value)))
    company = and_(theirs.kind == COMPANY, seen.company != "", seen.company == theirs.value)
    return exists().where(mine.contact == C.id, seen.identifier == mine.id, theirs.contact == C.org, C.org != 0,
                          *_visible(visible, seen), or_(domain, company))


class ContactsStore:
    """Le port ``contacts``."""

    def __init__(self, path: Path | Target, *, now: Callable[[], int] = _now_us) -> None:
        self._now = now
        self._lock = threading.RLock()
        target = as_target(path)
        target.ensure()
        self._engine = target.engine(shared=True)
        CONTACTS.create_all(self._engine)
        self._session = sessionmaker(self._engine, expire_on_commit=False)

    # ── ranger ce qu'elle voit ──
    async def observe(self, observations: Sequence[Observation], *, cursors: Mapping[str, int] | None = None) -> int:
        return await asyncio.to_thread(self.observe_now, list(observations), dict(cursors or {}))

    def observe_now(self, observations: Sequence[Observation], cursors: Mapping[str, int] | None = None) -> int:
        """``observe``, dans le fil qui l'appelle."""
        kept = 0
        touched: set[int] = set()
        with self._lock, self._session.begin() as s:
            for o in observations:
                kept += self._one(s, o, touched)
            for name, value in sorted((cursors or {}).items()):
                self._set_cursor(s, name, value)
            s.flush()
            for cid in sorted(touched):
                self._refresh(s, cid)
        return kept

    def _one(self, s: Session, o: Observation, touched: set[int]) -> int:
        kind = o.kind if o.kind in KINDS else ""
        value = fit(normalized(kind, o.value), VALUE) if kind else ""
        if not value or not o.source or not o.account or self._forgotten(s, kind, value, o.last):
            return 0
        if any(self._forgotten(s, k, fit(normalized(k, v), VALUE), o.last) for k, v in o.same if k in KINDS):
            return 0  # une source d'avant l'oubli d'un autre identifiant de la même personne
        source, account = fit(o.source, WORD), fit(o.account, ACCOUNT)
        person = 0
        if o.joins:  # ce que dit un profil de sa personne : sans elle (oubliée, refusée), rien
            person = self._person_of(s, *o.joins)
            if not person:
                return 0
            if kind in (COMPANY, TENANT):
                return self._org_fact(s, o, kind, value, (source, account), person, touched)
        ident = s.scalars(select(N).where(N.kind == kind, N.value == value)).first()
        if ident is not None and person and int(ident.contact) != person and not ident.generic:
            # déjà à un autre contact : l'e-mail d'un profil les prouve un (réunis) ; un numéro non (laissé) — sauf la
            # fiche que le téléphone ne connaît que par ce numéro : elle est ce numéro, donc cette personne. Refusée,
            # l'observation n'a rien créé (pas même l'organisation de son domaine)
            proved = o.proof or (kind == PHONE and self._bare(s, int(ident.contact)))
            if not proved or not self._prove(s, person, int(ident.contact), touched):
                return 0
            s.refresh(ident)
        domain = org_domain(mail_domain(value)) if kind == EMAIL else ""
        org = self._org(s, domain, o.last, touched) if domain else 0
        if ident is None:
            generic = bool(org) and generic_address(value)
            if generic:
                contact = org
            elif person:
                contact = person
            else:
                row = ContactRow(kind=ORG if kind in ORG_KINDS else PERSON_KIND, name="", org=org, person="",
                                 search="", created=self._now())
                s.add(row)
                s.flush()
                contact = row.id
            ident = IdentifierRow(contact=contact, kind=kind, value=value, generic=generic)
            s.add(ident)
            s.flush()
        if org and not ident.generic:
            # une personne qui n'avait pas encore son organisation (séparée, ou née d'un autre identifiant) la reçoit
            s.execute(update(C).where(C.id == ident.contact, C.kind == PERSON_KIND, C.org == 0).values(org=org))
        self._sight(s, ident.id, source, account, o)
        if o.thread:
            self._thread(s, int(ident.id), source, account, o)
        touched.add(ident.contact)
        if org:
            domain_id = s.scalar(select(N.id).where(N.kind == DOMAIN, N.value == fit(domain, VALUE)))
            if domain_id is not None:
                self._sight(s, int(domain_id), source, account,
                            Observation(DOMAIN, domain, o.source, o.account, "", o.count, o.first, o.last))
        return 1

    def _org(self, s: Session, domain: str, last: int, touched: set[int]) -> int:
        """L'organisation d'un domaine : la sienne, ou une neuve nommée d'après lui (0 : le domaine est oublié)."""
        value = fit(domain, VALUE)
        found = s.scalar(select(N.contact).where(N.kind == DOMAIN, N.value == value))
        if found is not None:
            touched.add(int(found))
            return int(found)
        if self._forgotten(s, DOMAIN, value, last):
            return 0
        row = ContactRow(kind=ORG, name=domain, org=0, person="", search="", created=self._now())
        s.add(row)
        s.flush()
        s.add(IdentifierRow(contact=row.id, kind=DOMAIN, value=value, generic=False))
        s.flush()
        touched.add(row.id)
        return row.id

    @staticmethod
    def _person_of(s: Session, kind: str, value: str) -> int:
        """Le contact (une personne) de cet identifiant ; 0 : inconnu, ou pas une personne."""
        found = fit(normalized(kind, value), VALUE) if kind in KINDS else ""
        if not found:
            return 0
        got = s.scalar(select(N.contact).join(C, C.id == N.contact)
                       .where(N.kind == kind, N.value == found, C.kind == PERSON_KIND))
        return int(got) if got is not None else 0

    @staticmethod
    def _bare(s: Session, contact: int) -> bool:
        """Une fiche que le téléphone ne connaît que par un numéro : une personne reliée à personne, sans autre
        identifiant qu'un numéro et des clés du téléphone, sans un nom vu (un expéditeur hors du carnet)."""
        row = s.get(C, contact)
        if row is None or row.kind != PERSON_KIND or row.person:
            return False
        kinds = set(s.scalars(select(N.kind).where(N.contact == contact)).all())
        if not kinds or not kinds <= {PHONE, PHONE_APP}:
            return False
        named = s.scalar(select(S.id).join(N, N.id == S.identifier)
                         .where(N.contact == contact, S.name != "").limit(1))
        return named is None

    @staticmethod
    def _has(s: Session, contact: int, kind: str) -> bool:
        return s.scalar(select(N.id).where(N.contact == contact, N.kind == kind).limit(1)) is not None

    def _prove(self, s: Session, a: int, b: int, touched: set[int]) -> int:
        """Deux personnes qu'un identifiant prouve être la même : réunies dans celle qui a le plus d'histoire (le plus
        de fois vue, puis la plus ancienne). Jamais deux contacts reliés à deux personnes différentes de l'identité,
        ni autre chose que deux personnes : rien ne change (0). Rend le contact gardé."""
        ra, rb = s.get(C, a), s.get(C, b)
        if ra is None or rb is None or ra.kind != PERSON_KIND or rb.kind != PERSON_KIND:
            return 0
        if ra.person and rb.person and ra.person != rb.person:
            return 0
        if s.get(D, (min(int(a), int(b)), max(int(a), int(b)))) is not None:
            return 0  # séparées par une opératrice (« Détacher », « Deux personnes différentes ») : une preuve n'y revient pas
        keep, other = sorted((ra, rb), key=lambda r: (-self._history(s, int(r.id)), int(r.id)))
        self._merge_in(s, keep, other)
        touched.discard(int(other.id))
        touched.add(int(keep.id))
        return int(keep.id)

    @staticmethod
    def _history(s: Session, contact: int) -> int:
        return int(s.scalar(select(func.coalesce(func.sum(S.count), 0)).select_from(S)
                            .join(N, N.id == S.identifier).where(N.contact == contact)) or 0)

    def _org_fact(self, s: Session, o: Observation, kind: str, value: str, place: tuple[str, str], person: int,
                  touched: set[int]) -> int:
        """L'entreprise (``COMPANY``) ou l'organisation Teams (``TENANT``) qu'un profil dit de sa personne
        (``person`` : son contact) — voir la tête du module. Rend 1 si elle est rangée."""
        row = s.get(C, person)
        if row is None:
            return 0
        ident = s.scalars(select(N).where(N.kind == kind, N.value == value)).first()
        holder = int(ident.contact) if ident is not None else 0
        if holder and getattr(s.get(C, holder), "kind", "") != ORG:
            return 0
        org = int(row.org or 0)
        if kind == TENANT:  # à l'organisation de sa personne, et à elle seule
            if not org or (holder and holder != org):
                return 0
            target = org
        elif org and self._has(s, org, DOMAIN):
            if holder and holder != org:
                if self._has(s, holder, DOMAIN):
                    return 0  # deux organisations à domaine du même nom : laissées à part
                # une organisation qui n'avait que ce nom (née d'une personne sans domaine) : ramenée à celle du domaine
                self._merge_in(s, s.get(C, org), s.get(C, holder))
                touched.discard(holder)
                s.refresh(ident)
            elif not holder and self._has(s, org, COMPANY):
                return 0  # elle a déjà son nom d'entreprise : un autre ne la renomme pas
            target = org
        else:
            if org and holder != org:
                return 0  # elle a déjà son organisation (une autre entreprise) : gardée
            target = holder or org
            if not target:
                new = ContactRow(kind=ORG, name="", org=0, person="", search="", created=self._now())
                s.add(new)
                s.flush()
                target = int(new.id)
            if not org:
                row.org = target
        if ident is None:
            ident = IdentifierRow(contact=target, kind=kind, value=value, generic=False)
            s.add(ident)
            s.flush()
        self._sight(s, int(ident.id), place[0], place[1], o)
        touched.update({target, person})
        return 1

    @staticmethod
    def _sight(s: Session, identifier: int, source: str, account: str, o: Observation) -> None:
        row = s.scalars(select(S).where(S.identifier == identifier, S.source == source, S.account == account)).first()
        name, title, department = clean_name(o.name), clean_role(o.title), clean_role(o.department)
        company = fit(normalized(COMPANY, o.company), VALUE) if o.company else ""
        if row is None:
            s.add(SightingRow(identifier=identifier, source=source, account=account, count=max(0, o.count),
                              first=o.first, last=o.last, name=name, fold=fold_text(name), own=o.own, title=title,
                              department=department, company=company))
            return
        row.count = (row.count or 0) + max(0, o.count)
        if o.first and (not row.first or o.first < row.first):
            row.first = o.first
        if o.last >= (row.last or 0):
            row.last = o.last
            row.name = name or row.name
            row.title = title or row.title or ""
            row.department = department or row.department or ""
            row.company = company or row.company or ""
        else:  # plus ancien : ne remplit que ce qui manque
            row.name = row.name or name
            row.title = row.title or title
            row.department = row.department or department
            row.company = row.company or company
        row.fold = fold_text(row.name or "")
        row.own = bool(row.own or o.own)

    @staticmethod
    def _thread(s: Session, identifier: int, source: str, account: str, o: Observation) -> None:
        """La conversation de cette observation, dans sa vue : ses messages comptés, son titre le plus récent ; la vue
        n'en garde que les plus récentes (``THREADS_MAX``)."""
        key = fit(o.thread.strip(), 64)
        row = s.scalars(select(T).where(T.identifier == identifier, T.source == source, T.account == account,
                                        T.thread == key)).first()
        title = clean_name(o.thread_title) if o.group else ""
        if row is None:
            s.add(ThreadRow(identifier=identifier, source=source, account=account, thread=key, title=title,
                            grouped=o.group, count=max(0, o.count), first=o.first, last=o.last))
            s.flush()
        else:
            row.count = (row.count or 0) + max(0, o.count)
            if o.first and (not row.first or o.first < row.first):
                row.first = o.first
            if o.last >= (row.last or 0):
                row.last, row.title = o.last, title or row.title or ""
            row.grouped = bool(row.grouped or o.group)
        stale = s.scalars(select(T.id).where(T.identifier == identifier, T.source == source, T.account == account)
                          .order_by(T.last.desc(), T.id.desc()).offset(THREADS_MAX)).all()
        if stale:
            s.execute(delete(T).where(T.id.in_(list(stale))))

    @staticmethod
    def _forgotten(s: Session, kind: str, value: str, last: int) -> bool:
        row = s.get(ForgottenRow, _print(kind, value))
        return row is not None and (last or 0) <= int(row.until or 0)

    def _refresh(self, s: Session, contact: int) -> None:
        """Son nom et ce qu'une recherche compare, d'après ses identifiants et ses vues ; un contact qui n'a plus
        d'identifiant part."""
        row = s.get(C, contact)
        if row is None:
            return
        idents = s.execute(select(N.id, N.kind, N.value, N.generic).where(N.contact == contact)
                           .order_by(N.id)).all()
        if not idents:
            self._drop_contacts(s, [contact])
            return
        seen = s.execute(select(S.identifier, S.name, S.title, S.department)
                         .where(S.identifier.in_([i.id for i in idents]))
                         .order_by(S.last.desc(), S.id.desc())).all()
        names = list(dict.fromkeys(r.name for r in seen if r.name))
        of = {i.id: (i.kind, bool(i.generic)) for i in idents}
        row.name = _name_of(row.kind, [(i.kind, i.value, i.generic) for i in idents],
                            [(*of[r.identifier], r.name) for r in seen])
        row.title, row.department = _role_of([(r.title or "", r.department or "") for r in seen])
        row.search = fold_text(" ".join([row.name, *names, *(i.value for i in idents if i.kind not in OPAQUE_KINDS)]))

    # ── lire ──
    def page(self, *, visible: Collection[tuple[str, str]] | None = None, q: str = "", kind: str | None = None,
             page: int = 1, size: int = 25, linked: bool | None = None, org: int = 0) -> Page[ContactLine]:
        if visible is not None and not visible:
            return Page((), 0, 1, max(1, min(100, size)))
        vis = _visible(visible)
        with self._lock, self._session() as s:
            # combien : une adresse générique est déjà comptée par le domaine de son organisation
            counted = func.sum(case((N.generic, 0), else_=S.count))
            seen = (select(N.contact.label("cid"), func.max(S.last).label("last"), counted.label("n"))
                    .select_from(S).join(N, N.id == S.identifier).where(*vis).group_by(N.contact).subquery("seen"))
            where: list[Any] = []
            if kind in (PERSON_KIND, ORG):
                where.append(C.kind == kind)
            if linked is not None:
                where.append(C.person != "" if linked else C.person == "")
            if org:
                where.append(C.org == int(org))
                if visible is not None:  # ses membres, pour qui voit la preuve qu'ils en sont
                    where.append(_proof(visible))
            for word in words_of(q):
                if visible is None:
                    where.append(func.instr(C.search, word) > 0)
                else:  # dans ce qui est visible seulement : un nom vu ailleurs, une adresse d'une autre boîte, non
                    where.append(exists().where(N.contact == C.id, S.identifier == N.id, *vis, or_(
                        and_(N.kind.notin_(OPAQUE_KINDS), func.instr(N.value, word) > 0),
                        func.instr(S.fold, word) > 0)))
            base = (select(C.id, C.kind, C.name, C.org, C.person, C.title, C.department, seen.c.last, seen.c.n)
                    .join(seen, seen.c.cid == C.id).where(*where))
            total = int(s.scalar(select(func.count()).select_from(base.subquery())) or 0)
            number, size, offset = Page.bounds(total, page, size)
            rows = s.execute(base.order_by(seen.c.last.desc(), C.id.desc()).limit(size).offset(offset)).all()
            details = self._details(s, [r.id for r in rows], vis)
            proven = self._proven(s, [int(r.id) for r in rows if r.org], visible)
            orgs = self._orgs(s, {int(r.org) for r in rows if r.org and int(r.id) in proven}, vis)
            members = self._members(s, [int(r.id) for r in rows if r.kind == ORG], visible)
        out = []
        for r in rows:
            got = details.get(r.id, _Seen())
            name = r.name if visible is None else _name_of(r.kind, got.idents, got.names) or r.name
            title, department = (r.title or "", r.department or "") if visible is None else _role_of(got.roles)
            org_name = orgs.get(int(r.org or 0), "") if int(r.id) in proven else ""
            out.append(ContactLine(r.id, r.kind, name, int(r.org) if org_name else 0, org_name, r.person or "",
                                   int(r.n or 0), int(r.last or 0), tuple(sorted(got.sources)),
                                   tuple((k, v) for k, v, g in got.idents if not g)
                                   + tuple((k, v) for k, v, g in got.idents if g), title, department,
                                   tuple((src, acc, n) for (src, acc), n in sorted(got.places.items())),
                                   members.get(int(r.id), 0), tuple(sorted(got.apps.items()))))
        return Page(tuple(out), total, number, size)

    @staticmethod
    def _members(s: Session, orgs: Sequence[int], visible: Collection[tuple[str, str]] | None) -> dict[int, int]:
        """Combien de personnes de ces organisations sont visibles, et visiblement de l'organisation (``_proof`` ;
        toutes sans condition)."""
        if not orgs:
            return {}
        query = select(C.org, func.count(C.id)).where(C.org.in_(list(orgs)), C.kind == PERSON_KIND)
        if visible is not None:
            query = query.where(_proof(visible))
        return {int(o): int(n) for o, n in s.execute(query.group_by(C.org)).all()}

    @staticmethod
    def _proven(s: Session, ids: Sequence[int], visible: Collection[tuple[str, str]] | None) -> set[int]:
        """Ceux de ces contacts dont l'organisation se prouve dans ces vues (``_proof`` ; tous sans condition)."""
        if not ids:
            return set()
        if visible is None:
            return {int(i) for i in ids}
        return {int(i) for i in s.scalars(select(C.id).where(C.id.in_(sorted(set(ids))), _proof(visible)))}

    def links(self) -> dict[str, tuple[int, ...]]:
        out: dict[str, list[int]] = {}
        with self._lock, self._session() as s:
            for cid, person in s.execute(select(C.id, C.person).where(C.person != "").order_by(C.person, C.id)):
                out.setdefault(person, []).append(int(cid))
        return {k: tuple(v) for k, v in out.items()}

    @staticmethod
    def _details(s: Session, ids: Sequence[int], vis: list[Any]) -> dict[int, _Seen]:
        """Pour ces contacts, ce qui est visible : leurs identifiants, leurs sources, les noms vus (le plus récent
        d'abord)."""
        out: dict[int, _Seen] = {}
        if not ids:
            return out
        rows = s.execute(select(N.contact, N.id, N.kind, N.value, N.generic, S.source, S.account, S.count, S.name,
                                S.title, S.department)
                         .join(S, S.identifier == N.id).where(N.contact.in_(list(ids)), *vis)
                         .order_by(N.contact, S.last.desc(), S.id.desc())).all()
        for r in rows:
            got = out.setdefault(int(r.contact), _Seen())
            if (r.kind, r.value, bool(r.generic)) not in got.idents:
                got.idents.append((r.kind, r.value, bool(r.generic)))
            got.sources.add(r.source)
            place = (r.source, r.account)  # une adresse générique est déjà comptée par le domaine de son organisation
            got.places[place] = got.places.get(place, 0) + (0 if r.generic else int(r.count or 0))
            family = app_family(r.value) if r.kind == PHONE_APP else ""
            if family:
                got.apps[family] = got.apps.get(family, 0) + int(r.count or 0)
            if r.name:
                got.names.append((r.kind, bool(r.generic), r.name))
            if r.title or r.department:
                got.roles.append((r.title or "", r.department or ""))
        return out

    def _orgs(self, s: Session, ids: Collection[int], vis: list[Any]) -> dict[int, str]:
        """Le nom de celles de ces organisations qui sont visibles, d'après ce qui l'est (le nom d'entreprise lu dans
        le Teams d'une autre ne se dit pas : son domaine, si)."""
        if not ids:
            return {}
        stored = {int(i): n for i, n in s.execute(select(C.id, C.name).where(C.id.in_(sorted(ids)), C.kind == ORG))}
        details = self._details(s, sorted(stored), vis)
        return {i: stored[i] if not vis else _name_of(ORG, got.idents, got.names) or stored[i]
                for i, got in details.items()}

    def sheet(self, contact_id: int, *, visible: Collection[tuple[str, str]] | None = None) -> ContactSheet | None:
        if visible is not None and not visible:
            return None
        vis = _visible(visible)
        with self._lock, self._session() as s:
            row = s.get(C, int(contact_id))
            if row is None:
                return None
            rows = s.execute(select(N.id, N.kind, N.value, N.generic, S.source, S.account, S.count, S.first, S.last,
                                    S.name, S.own, S.title, S.department)
                             .join(S, S.identifier == N.id).where(N.contact == row.id, *vis)
                             .order_by(N.id, S.last.desc(), S.id.desc())).all()
            if not rows:
                return None
            threads: dict[tuple[int, str, str], list[Thread]] = {}
            for t in s.execute(select(T).where(T.identifier.in_(sorted({int(r.id) for r in rows})))
                               .order_by(T.last.desc(), T.id.desc())).scalars():
                threads.setdefault((int(t.identifier), t.source, t.account), []).append(
                    Thread(t.thread, t.title or "", bool(t.grouped), int(t.count or 0), int(t.first or 0),
                           int(t.last or 0)))
            idents: dict[int, tuple[Any, list[Sighting]]] = {}
            for r in rows:
                idents.setdefault(int(r.id), (r, []))[1].append(
                    Sighting(r.source, r.account, int(r.count or 0), int(r.first or 0), int(r.last or 0), r.name or "",
                             bool(r.own), tuple(threads.get((int(r.id), r.source, r.account), ()))))
            org = None
            if row.org and self._proven(s, [int(row.id)], visible):
                named = self._orgs(s, {int(row.org)}, vis)
                if named:
                    org = ContactRef(int(row.org), ORG, named[int(row.org)])
            members: tuple[ContactRef, ...] = ()
            if row.kind == ORG:
                ids = s.scalars(select(C.id).where(C.org == row.id, C.kind == PERSON_KIND,
                                                   *([_proof(visible)] if visible is not None else []))
                                .order_by(C.id).limit(MEMBERS_SCANNED)).all()
                details = self._details(s, list(ids), vis)
                names = dict(s.execute(select(C.id, C.name).where(C.id.in_(list(details)))).all()) if details else {}
                members = tuple(ContactRef(cid, PERSON_KIND, names[cid] if visible is None
                                           else _name_of(PERSON_KIND, got.idents, got.names) or names[cid])
                                for cid, got in sorted(details.items()))[:MEMBERS_MAX]
        recent = sorted(rows, key=lambda r: -(r.last or 0))
        seen = [(r.kind, bool(r.generic), r.name) for r in recent if r.name]
        found = tuple(Identifier(i, r.kind, r.value, bool(r.generic), tuple(sights))
                      for i, (r, sights) in sorted(idents.items(), key=lambda kv: (kv[1][0].generic, kv[0])))
        name = row.name if visible is None else \
            _name_of(row.kind, [(i.kind, i.value, i.generic) for i in found], seen) or row.name
        title, department = (row.title or "", row.department or "") if visible is None else \
            _role_of([(r.title or "", r.department or "") for r in recent])
        return ContactSheet(row.id, row.kind, name, row.person or "", org, members, found,
                            tuple(dict.fromkeys(n for _, _, n in seen)), int(row.created or 0), title, department)

    def contact_of(self, kind: str, value: str) -> int | None:
        found = fit(normalized(kind, value), VALUE) if kind in KINDS else ""
        if not found:
            return None
        with self._lock, self._session() as s:
            got = s.scalar(select(N.contact).where(N.kind == kind, N.value == found))
        return int(got) if got is not None else None

    # ── ce qu'une opératrice (ou une preuve) décide ──
    def link(self, contact_id: int, person: str | None, *, replace: bool = True) -> bool:
        wanted = fit((person or "").strip(), PERSON)
        with self._lock, self._session.begin() as s:
            row = s.get(C, int(contact_id))
            if row is None or row.kind != PERSON_KIND or (row.person or "") == wanted:
                return False
            if row.person and not replace:
                return False
            row.person = wanted
        return True

    def merge(self, keep_id: int, other_id: int) -> bool:
        if int(keep_id) == int(other_id):
            return False
        with self._lock, self._session.begin() as s:
            keep, other = s.get(C, int(keep_id)), s.get(C, int(other_id))
            if keep is None or other is None:
                return False
            if keep.kind != other.kind:
                raise ValueError("une personne et une organisation ne se réunissent pas")
            if keep.person and other.person and keep.person != other.person:
                raise ValueError("ces deux contacts sont reliés à deux personnes différentes : délie l'un d'abord")
            self._merge_in(s, keep, other)
        return True

    def _merge_in(self, s: Session, keep: ContactRow, other: ContactRow) -> None:
        """``other`` réuni dans ``keep`` (deux contacts de la même sorte, déjà vérifiés) : ses identifiants, ses
        membres, son lien, son organisation, ses paires écartées (qui deviennent celles de ``keep``)."""
        s.execute(update(N).where(N.contact == other.id).values(contact=keep.id))
        s.execute(update(C).where(C.org == other.id).values(org=keep.id))
        for row in (NT, NF, P):  # ce qu'elle en sait, ce qu'elle en a oublié, ses portraits le suivent
            s.execute(update(row).where(row.contact == other.id).values(contact=keep.id))
        keep.person = keep.person or other.person or ""
        keep.org = keep.org or (other.org if other.org != keep.id else 0) or 0
        # ses paires écartées le suivent : réunie à une autre, une fiche qu'on a dite différente le reste
        for a, b in s.execute(select(D.a, D.b).where(or_(D.a == other.id, D.b == other.id))).all():
            peer = int(b) if int(a) == int(other.id) else int(a)
            if peer != int(keep.id):
                insert_ignore(s, D, {"a": min(peer, int(keep.id)), "b": max(peer, int(keep.id))})
        s.execute(delete(D).where(or_(D.a == other.id, D.b == other.id)))
        s.delete(other)
        s.flush()
        self._refresh(s, keep.id)

    def detach(self, identifier_id: int) -> int:
        with self._lock, self._session.begin() as s:
            ident = s.get(N, int(identifier_id))
            if ident is None:
                return 0
            if ident.kind == DOMAIN:
                raise ValueError("le domaine d'une organisation ne se sépare pas d'elle")
            if ident.kind in ORG_KINDS:
                raise ValueError("le nom d'entreprise et l'organisation Teams d'une organisation ne se séparent pas "
                                 "d'elle")
            left = int(s.scalar(select(func.count()).select_from(N).where(N.contact == ident.contact)) or 0)
            if left <= 1:
                raise ValueError("c'est le seul identifiant de ce contact : il n'y a rien à séparer")
            old = s.get(C, ident.contact)
            org = (old.id if old.kind == ORG else old.org) if old is not None else 0
            row = ContactRow(kind=PERSON_KIND, name="", org=org or 0, person="", search="", created=self._now())
            s.add(row)
            s.flush()
            ident.contact, ident.generic = row.id, False
            if old is not None:  # séparés : les suggestions ne les rapprochent plus
                insert_ignore(s, D, {"a": min(row.id, old.id), "b": max(row.id, old.id)})
            s.flush()
            self._refresh(s, row.id)
            if old is not None:
                self._refresh(s, old.id)
            return int(row.id)

    def dismiss(self, a: int, b: int) -> bool:
        a, b = sorted((int(a), int(b)))
        if a == b:
            return False
        with self._lock, self._session.begin() as s:
            return insert_ignore(s, D, {"a": a, "b": b}) > 0

    def suggestions(self, limit: int = 50) -> list[Suggestion]:
        with self._lock, self._session() as s:
            rows = s.execute(select(C.id, C.name, C.person).where(C.kind == PERSON_KIND).order_by(C.id)).all()
            dismissed = {(int(a), int(b)) for a, b in s.execute(select(D.a, D.b)).all()}
            # ceux qu'on nomme d'un prénom seul : une personne dont on lui a parlé, un expéditeur du téléphone
            informal = {int(c) for c in s.scalars(select(N.contact).where(N.kind.in_(OPAQUE_KINDS)).distinct())}
            # ceux qui ne sont qu'un nom raconté : face à une fiche reliée à une personne qui lui parle, c'est l'identité
            # qui décide (« C'est la personne dont on lui a parlé » : sa mémoire le saura), pas l'annuaire
            told_only = {int(c) for c in s.scalars(select(N.contact).where(N.kind == TOLD_NAME).distinct())} - {
                int(c) for c in s.scalars(select(N.contact).where(N.kind != TOLD_NAME).distinct())}
        refs = {int(r.id): (ContactRef(int(r.id), PERSON_KIND, r.name), r.person or "") for r in rows}
        full: dict[str, list[int]] = {}
        spelled: dict[tuple[str, str], list[int]] = {}
        initials: dict[tuple[str, str], list[int]] = {}
        #: un prénom seul (des fiches qu'on nomme ainsi) ; le prénom des noms complets
        alone: dict[str, list[int]] = {}
        firsts: dict[str, list[int]] = {}
        for r in rows:
            words = name_words(r.name)
            if not _lettered(r.name) or "@" in r.name:
                continue
            if len(words) == 1:
                if int(r.id) in informal and len(words[0]) >= FIRST_NAME_MIN:
                    alone.setdefault(words[0], []).append(int(r.id))
                continue
            if len(words) < 2:
                continue
            if len(words[0]) >= FIRST_NAME_MIN:
                firsts.setdefault(words[0], []).append(int(r.id))
            short = [w for w in words if len(w) == 1]
            if short:  # « G. Rousseau » : une initiale et un nom
                if len(words) == 2 and len(short) == 1:
                    initials.setdefault((short[0], next(w for w in words if len(w) > 1)), []).append(int(r.id))
                continue
            full.setdefault(" ".join(sorted(words)), []).append(int(r.id))
            for i, w in enumerate(words):
                for j, v in enumerate(words):
                    if i != j:
                        spelled.setdefault((w[0], v), []).append(int(r.id))
        pairs: dict[tuple[int, int], str] = {}
        for ids in full.values():
            if 1 < len(ids) <= SAME_NAME_MAX:
                for x, a in enumerate(ids):
                    for b in ids[x + 1:]:
                        pairs.setdefault((min(a, b), max(a, b)), "same_name")
        for key, ids in initials.items():
            whole = sorted(set(spelled.get(key, ())))
            if len(whole) > SAME_NAME_MAX:
                continue
            for a in ids:
                for b in whole:
                    if a != b:
                        pairs.setdefault((min(a, b), max(a, b)), "initial")
        for word, ids in alone.items():  # plus faible : le même prénom, d'un côté sans nom de famille
            others = sorted({*ids, *firsts.get(word, ())})
            if len(others) > SAME_NAME_MAX:
                continue
            for a in ids:
                for b in others:
                    if a != b:
                        pairs.setdefault((min(a, b), max(a, b)), "first_name")
        rank = {"same_name": 0, "initial": 1, "first_name": 2}
        out = []
        for (a, b), reason in sorted(pairs.items(), key=lambda kv: (rank.get(kv[1], 3), kv[0])):
            (ra, pa), (rb, pb) = refs[a], refs[b]
            if (a, b) in dismissed or (pa and pb and pa != pb) or (a in told_only and pb and not pa) \
                    or (b in told_only and pa and not pb):
                continue
            out.append(Suggestion(ra, rb, reason))
            if len(out) >= max(1, limit):
                break
        return out

    # ── les curseurs des sources ──
    def cursor(self, name: str) -> int:
        with self._lock, self._session() as s:
            got = s.scalar(select(CursorRow.value).where(CursorRow.name == fit(name, 64)))
        return int(got or 0)

    def set_cursor(self, name: str, value: int) -> None:
        with self._lock, self._session.begin() as s:
            self._set_cursor(s, name, value)

    @staticmethod
    def _set_cursor(s: Session, name: str, value: int) -> None:
        upsert(s, CursorRow, {"name": fit(name, 64), "value": max(0, int(value))}, keys=("name",))

    # ── ce qui s'efface ──
    def sources(self) -> list[tuple[str, str]]:
        with self._lock, self._session() as s:
            return [(a, b) for a, b in s.execute(select(S.source, S.account).distinct()
                                                 .order_by(S.source, S.account)).all()]

    def drop_source(self, source: str, account: str) -> int:
        with self._lock, self._session.begin() as s:
            return self._drop_source(s, source, account)

    def _drop_source(self, s: Session, source: str, account: str,
                     marks: list[tuple[str, str]] | None = None) -> int:
        """Les vues d'un compte s'effacent, et ce qui n'était vu que par lui (``marks`` : leurs empreintes à garder,
        pour un oubli)."""
        src, acc = fit(source, WORD), fit(account, ACCOUNT)
        idents = sorted({int(i) for i in s.scalars(select(S.identifier).where(S.source == src, S.account == acc))})
        n = int(s.execute(delete(S).where(S.source == src, S.account == acc)).rowcount or 0)
        n += int(s.execute(delete(T).where(T.source == src, T.account == acc)).rowcount or 0)
        # ce qu'elle a appris de ce compte part avec lui (ses faits, ses portraits)
        n += int(s.execute(delete(NT).where(NT.source == src, NT.account == acc)).rowcount or 0)
        n += int(s.execute(delete(P).where(P.source == src, P.account == acc)).rowcount or 0)
        if not idents:
            return n
        alone = s.execute(select(N.id, N.kind, N.value).where(
            N.id.in_(idents), ~exists().where(S.identifier == N.id))).all()
        contacts = sorted({int(c) for c in s.scalars(select(N.contact).where(N.id.in_(idents)))})
        if alone:
            if marks is not None:
                marks += [(r.kind, r.value) for r in alone]
            n += self._drop_identifiers(s, [int(r.id) for r in alone])
        s.flush()
        for cid in contacts:
            self._refresh(s, cid)
        return n

    def reset_source(self, source: str) -> int:
        src = fit(source, WORD)
        with self._lock, self._session.begin() as s:
            n = int(s.execute(delete(S).where(S.source == src)).rowcount or 0)
            return n + int(s.execute(delete(T).where(T.source == src)).rowcount or 0)

    def prune_unseen(self, kind: str) -> int:
        with self._lock, self._session.begin() as s:
            rows = s.execute(select(N.id, N.contact).where(N.kind == fit(kind, WORD),
                                                           ~exists().where(S.identifier == N.id))).all()
            n = self._drop_identifiers(s, [int(r.id) for r in rows])
            s.flush()
            for cid in sorted({int(r.contact) for r in rows}):
                n += self._settle(s, cid)
        return n

    def discard(self, kind: str, value: str) -> int:
        found = fit(normalized(kind, value), VALUE) if kind in KINDS else ""
        if not found:
            return 0
        with self._lock, self._session.begin() as s:
            ident = s.scalars(select(N).where(N.kind == kind, N.value == found)).first()
            if ident is None:
                return 0
            contact = int(ident.contact)
            n = self._drop_identifiers(s, [int(ident.id)])
            s.flush()
            return n + self._settle(s, contact)

    def drop_places(self, contact_id: int, places: Collection[tuple[str, str]]) -> int:
        pairs = sorted({(fit(src, WORD), fit(acc, ACCOUNT)) for src, acc in places})
        if not pairs:
            return 0
        with self._lock, self._session.begin() as s:
            row = s.get(C, int(contact_id))
            if row is None:
                return 0
            idents = [int(i) for i in s.scalars(select(N.id).where(N.contact == row.id))]
            n = 0
            for src, acc in pairs:
                at = [S.source == src, S.account == acc]
                n += int(s.execute(delete(S).where(S.identifier.in_(idents), *at)).rowcount or 0)
                n += int(s.execute(delete(T).where(T.identifier.in_(idents), T.source == src, T.account == acc))
                         .rowcount or 0)
                for table in (NT, P):  # ce qu'elle en a tiré de là
                    n += int(s.execute(delete(table).where(table.contact == row.id, table.source == src,
                                                           table.account == acc)).rowcount or 0)
            alone = s.execute(select(N.id, N.kind, N.value).where(N.contact == row.id,
                                                                  ~exists().where(S.identifier == N.id))).all()
            n += self._drop_identifiers(s, [int(r.id) for r in alone])
            until = self._now()
            for r in alone:  # ce qui ne se voyait que là : ce qui le reverrait daté d'avant ne le ramène pas
                upsert(s, ForgottenRow, {"digest": _print(r.kind, r.value), "until": until}, keys=("digest",))
            s.flush()
            return n + self._settle(s, int(row.id))

    def _settle(self, s: Session, contact: int) -> int:
        """Après qu'un contact a perdu des identifiants : son nom recalculé, ou, s'il n'a plus rien, parti — avec son
        organisation si elle n'existait que par lui. Rend combien de lignes en plus."""
        row = s.get(C, contact)
        if row is None:
            return 0
        org = int(row.org or 0)
        if s.scalar(select(N.id).where(N.contact == contact).limit(1)) is not None:
            self._refresh(s, contact)
            return 0
        n = self._drop_contacts(s, [contact])
        if org:
            s.flush()
            n += self._prune_org(s, org)
        return n

    def naming(self, texts: Sequence[str], *, but: int = 0) -> list[bool]:
        with self._lock, self._session() as s:
            names = {r for r in s.scalars(select(C.name).where(C.kind == PERSON_KIND, C.id != int(but), C.name != ""))}
            names |= {r for r in s.scalars(select(S.name).join(N, N.id == S.identifier).join(C, C.id == N.contact)
                                           .where(C.kind == PERSON_KIND, C.id != int(but), S.name != "").distinct())}
            own = {fold_text(n) for n in s.scalars(select(S.name).join(N, N.id == S.identifier)
                                                   .where(N.contact == int(but), S.name != ""))} if but else set()
            row = s.get(C, int(but)) if but else None
        if row is not None and row.name:
            own.add(fold_text(row.name))
        wanted = _name_index(n for n in names if fold_text(n) not in own)
        return [bool(_names_in(text, wanted)) for text in texts]

    async def forget(self, subject: str) -> int:
        return await asyncio.to_thread(self.forget_now, subject)

    def forget_now(self, subject: str) -> int:
        """``forget``, dans le fil qui l'appelle."""
        subject = (subject or "").strip()
        if not subject:
            return 0
        with self._lock, self._session.begin() as s:
            whole: set[int] = set()
            alone: set[int] = set()
            marks: list[tuple[str, str]] = []
            if subject.startswith(CONTACT_PREFIX):
                rest = subject[len(CONTACT_PREFIX):]
                if rest.isdigit():
                    whole.add(int(rest))
            elif subject.startswith((TEAMS_PREFIX, MAIL_PREFIX, PHONE_PREFIX, NAME_PREFIX)):
                if subject.startswith(PHONE_PREFIX):  # un expéditeur du téléphone : sa clé, quelle que soit l'appli
                    wanted = [(PHONE_APP, fit(v, VALUE)) for v in phone_app_values(subject)]
                else:
                    kind = TEAMS_ID if subject.startswith(TEAMS_PREFIX) else EMAIL \
                        if subject.startswith(MAIL_PREFIX) else TOLD_NAME
                    raw = subject if kind == TOLD_NAME else subject.split(":", 1)[1]
                    wanted = [(kind, fit(normalized(kind, raw), VALUE))]
                wanted = [(k, v) for k, v in wanted if v]
                if not wanted:
                    return 0
                marks += wanted  # même jamais vu : ce qui le reverrait daté d'avant ne le ramène pas
                for kind, value in wanted:
                    ident = s.scalars(select(N).where(N.kind == kind, N.value == value)).first()
                    if ident is None:
                        continue
                    owner = s.get(C, ident.contact)
                    if ident.generic or (owner is not None and owner.kind == ORG):
                        alone.add(int(ident.id))
                    else:
                        whole.add(int(ident.contact))
            else:  # la clé d'une personne de l'identité : ses contacts reliés, et ce que son téléphone et ses récits
                # avaient apporté (ce qui n'était vu que là part avec)
                whole |= {int(c) for c in s.scalars(select(C.id).where(C.person == fit(subject, PERSON)))}
            n = 0
            if not subject.startswith((CONTACT_PREFIX, TEAMS_PREFIX, MAIL_PREFIX, PHONE_PREFIX, NAME_PREFIX)):
                for source in PERSON_SOURCES:
                    n += self._drop_source(s, source, subject, marks)
            for cid in sorted(whole):
                n += self._forget_contact(s, cid, marks)
            if alone:
                rows = s.execute(select(N.id, N.kind, N.value, N.contact).where(N.id.in_(sorted(alone)))).all()
                marks += [(r.kind, r.value) for r in rows]
                n += self._drop_identifiers(s, [int(r.id) for r in rows])
                s.flush()
                for cid in sorted({int(r.contact) for r in rows}):
                    self._refresh(s, cid)
            until = self._now()
            for kind, value in dict.fromkeys(marks):
                upsert(s, ForgottenRow, {"digest": _print(kind, value), "until": until}, keys=("digest",))
        return n

    def _forget_contact(self, s: Session, contact: int, marks: list[tuple[str, str]]) -> int:
        """Un contact oublié entier : ses identifiants (marqués), ses vues ; ses membres perdent leur organisation ;
        son organisation part si elle n'existait que par lui."""
        row = s.get(C, contact)
        if row is None:
            return 0
        n = self._drop_notes_naming(s, contact) if row.kind == PERSON_KIND else 0
        rows = s.execute(select(N.id, N.kind, N.value).where(N.contact == contact)).all()
        marks += [(r.kind, r.value) for r in rows]
        n += self._drop_identifiers(s, [int(r.id) for r in rows])
        org = int(row.org or 0)
        n += self._drop_contacts(s, [contact])
        if org:
            s.flush()
            n += self._prune_org(s, org)
        return n

    @staticmethod
    def _drop_notes_naming(s: Session, contact: int) -> int:
        """Les faits d'autres contacts qui nomment cette personne (un de ses noms vus) : oubliée, elle ne se redit pas
        par eux. Rend combien de faits."""
        names = set(s.scalars(select(S.name).join(N, N.id == S.identifier).where(N.contact == contact, S.name != "")))
        row = s.get(C, contact)
        if row is not None and row.name:
            names.add(row.name)
        wanted = _name_index(names)
        if not wanted:
            return 0
        gone = [int(i) for i, text in s.execute(select(NT.id, NT.text).where(NT.contact != contact))
                if _names_in(text or "", wanted)]
        return int(s.execute(delete(NT).where(NT.id.in_(gone))).rowcount or 0) if gone else 0

    def _prune_org(self, s: Session, org: int) -> int:
        """Une organisation sans membre ni adresse générique part (elle n'existait que par ceux qui sont partis), avec
        son domaine, son nom d'entreprise, son organisation Teams."""
        if s.scalar(select(func.count()).select_from(C).where(C.org == org)):
            return 0
        if s.scalar(select(func.count()).select_from(N).where(N.contact == org, N.kind.notin_(ORG_KINDS))):
            return 0
        ids = [int(i) for i in s.scalars(select(N.id).where(N.contact == org))]
        return self._drop_identifiers(s, ids) + self._drop_contacts(s, [org])

    @staticmethod
    def _drop_identifiers(s: Session, ids: Iterable[int]) -> int:
        ids = sorted(set(ids))
        if not ids:
            return 0
        n = int(s.execute(delete(S).where(S.identifier.in_(ids))).rowcount or 0)
        n += int(s.execute(delete(T).where(T.identifier.in_(ids))).rowcount or 0)
        return n + int(s.execute(delete(N).where(N.id.in_(ids))).rowcount or 0)

    @staticmethod
    def _drop_contacts(s: Session, ids: Iterable[int]) -> int:
        """Des contacts sans identifiant : partis, leurs paires écartées avec eux, et ce qu'elle en savait ; leurs
        membres sans organisation."""
        ids = sorted(set(ids))
        if not ids:
            return 0
        s.execute(update(C).where(C.org.in_(ids)).values(org=0))
        s.execute(delete(D).where(or_(D.a.in_(ids), D.b.in_(ids))))
        n = 0
        for row in (NT, NF, P):  # ce qu'elle en savait, ses empreintes d'oubli, ses portraits : partis avec lui
            n += int(s.execute(delete(row).where(row.contact.in_(ids))).rowcount or 0)
        return n + int(s.execute(delete(C).where(C.id.in_(ids))).rowcount or 0)

    # ── ce qu'elle en sait (lot 6) ──
    def notes(self, contact_id: int, *, visible: Collection[tuple[str, str]] | None = None) -> list[Note]:
        if visible is not None and not visible:
            return []
        where = [NT.contact == int(contact_id)]
        if visible is not None:
            pairs = sorted({(fit(s, WORD), fit(a, ACCOUNT)) for s, a in visible})
            where.append(or_(*(and_(NT.source == s, NT.account == a) for s, a in pairs)))
        with self._lock, self._session() as s:
            rows = s.scalars(select(NT).where(*where).order_by(NT.confidence.desc(), NT.said_at.desc(),
                                                                NT.id)).all()
        return [_note(r) for r in rows]

    def note(self, note_id: int) -> Note | None:
        with self._lock, self._session() as s:
            row = s.get(NT, int(note_id))
            return _note(row) if row is not None else None

    def portrayed(self, portrait: Portrait, notes: Sequence[Note] | None) -> int:
        source, account = fit(portrait.source, WORD), fit(portrait.account, ACCOUNT)
        with self._lock, self._session.begin() as s:
            if s.get(C, int(portrait.contact)) is None:
                return 0  # oublié entre la lecture et la réponse : rien ne le ramène
            s.add(PortraitRow(contact=int(portrait.contact), source=source, account=account, at=int(portrait.at),
                              upto=int(portrait.upto), read=int(portrait.read), ok=notes is not None,
                              call_id=fit(portrait.call_id, REF)))
            if notes is None:
                return 0
            prints = list(s.scalars(select(NF.prints).where(NF.contact == int(portrait.contact))))
            s.execute(delete(NT).where(NT.contact == int(portrait.contact), NT.source == source,
                                       NT.account == account))
            kept = 0
            for n in notes:
                text = " ".join((n.text or "").split())
                if not text or relearned(text, prints):
                    continue
                s.add(NoteRow(contact=int(portrait.contact), source=source, account=account, text=text,
                              kind=fit(n.kind or "other", WORD),
                              confidence=max(0, min(100, round(float(n.confidence) * 100))),
                              ref=fit(n.ref, REF), place=n.place or "", said_at=int(n.said_at or 0),
                              at=int(n.at or portrait.at), call_id=fit(n.call_id or portrait.call_id, REF)))
                kept += 1
            return kept

    def portraits(self, *, since: int = 0, contacts: Collection[int] | None = None) -> list[Portrait]:
        where = [P.at >= int(since)] if since else []
        if contacts is not None:
            if not contacts:
                return []
            where.append(P.contact.in_(sorted({int(c) for c in contacts})))
        with self._lock, self._session() as s:
            rows = s.scalars(select(P).where(*where).order_by(P.at.desc(), P.id.desc())).all()
        return [Portrait(int(r.contact), r.source, r.account, int(r.at or 0), int(r.upto or 0), int(r.read or 0),
                         bool(r.ok), r.call_id or "") for r in rows]

    def forget_note(self, note_id: int) -> Note | None:
        with self._lock, self._session.begin() as s:
            row = s.get(NT, int(note_id))
            if row is None:
                return None
            gone = _note(row)
            printed = note_print(row.text or "")
            if printed:
                s.add(NoteForgottenRow(contact=int(row.contact), prints=printed, at=self._now()))
            s.delete(row)
        return gone

    def close(self) -> None:
        with self._lock:
            self._engine.dispose()


class _Seen:
    """Ce qu'une lecture voit d'un contact : ses identifiants (sorte, valeur, générique), ses sources et ses comptes
    (combien de fois dans chacun), ses noms vus (sorte de l'identifiant, générique, nom), ses postes et services vus — le
    plus récent d'abord."""

    __slots__ = ("apps", "idents", "names", "places", "roles", "sources")

    def __init__(self) -> None:
        self.idents: list[tuple[str, str, bool]] = []
        self.sources: set[str] = set()
        #: combien de fois, par (source, compte)
        self.places: dict[tuple[str, str], int] = {}
        self.names: list[tuple[str, bool, str]] = []
        self.roles: list[tuple[str, str]] = []
        #: combien de fois, par famille d'appli du téléphone
        self.apps: dict[str, int] = {}


def _name_of(kind: str, idents: Sequence[tuple[str, str, bool]], names: Sequence[tuple[str, bool, str]]) -> str:
    """Le nom d'un contact (``names`` : sorte de l'identifiant, générique, nom — le plus récent d'abord) : une
    organisation, son nom d'entreprise le plus récent, sinon son domaine ; une personne, le plus récent qu'on lui voit
    (ceux d'une adresse générique ne comptent pas), sinon son premier identifiant."""
    if kind == ORG:
        found = next((n for k, _, n in names if n and k == COMPANY), "")
        return found or next((v for k, v, _ in idents if k == DOMAIN), idents[0][1] if idents else "")
    found = next((n for _, generic, n in names if n and not generic and _lettered(n)), "") or \
        next((n for _, generic, n in names if n and not generic), "")
    # sans nom vu : un identifiant qui se lit (une clé du téléphone, un nom raconté, non), sinon le premier
    return found or next((v for k, v, g in idents if not g and k not in OPAQUE_KINDS),
                         next((v for k, v, g in idents if not g), idents[0][1] if idents else ""))


def _note(r: NoteRow) -> Note:
    return Note(int(r.id), int(r.contact), r.source, r.account, r.text or "", r.kind or "other",
                int(r.confidence or 0) / 100, r.ref or "", r.place or "", int(r.said_at or 0), int(r.at or 0),
                r.call_id or "")


def _lettered(name: str) -> bool:
    """Un nom qui a au moins une lettre (pas un numéro donné comme nom)."""
    return any(c.isalpha() for c in name)


#: les mots d'un texte, avec leur casse (un nom d'un seul mot ne se reconnaît qu'écrit avec sa majuscule)
_TEXT_WORDS = re.compile(r"[^\W\d_]+")


def _name_index(names: Iterable[str]) -> dict[str, list[tuple[str, ...]]]:
    """Des noms à reconnaître dans un texte, par leur premier mot replié : un nom de plusieurs mots, ou d'un seul mot
    d'au moins ``FIRST_NAME_MIN`` lettres (ni un numéro, ni une adresse)."""
    out: dict[str, list[tuple[str, ...]]] = {}
    for name in names:
        if not name or "@" in name or not _lettered(name):
            continue
        words = tuple(_TEXT_WORDS.findall(fold_text(name)))
        if not words or (len(words) == 1 and len(words[0]) < FIRST_NAME_MIN):
            continue
        out.setdefault(words[0], [])
        if words not in out[words[0]]:
            out[words[0]].append(words)
    return out


def _names_in(text: str, wanted: Mapping[str, Sequence[tuple[str, ...]]]) -> bool:
    """Ce texte nomme-t-il l'un de ces noms (``_name_index``) : ses mots à la suite ; un nom d'un seul mot, écrit avec
    sa majuscule (« il gère le support » ne nomme pas « Support »)."""
    raw = _TEXT_WORDS.findall(text or "")
    words = [fold_text(w) for w in raw]
    for i, w in enumerate(words):
        for name in wanted.get(w, ()):
            if len(name) == 1:
                if raw[i][:1].isupper():
                    return True
            elif tuple(words[i:i + len(name)]) == name:
                return True
    return False


def _role_of(roles: Sequence[tuple[str, str]]) -> tuple[str, str]:
    """Le poste et le service d'un contact : chacun le plus récent qu'on lui voit (``roles`` : le plus récent
    d'abord)."""
    return (next((t for t, _ in roles if t), ""), next((d for _, d in roles if d), ""))


__all__ = ["NAME_MAX", "ContactsStore", "clean_name", "clean_role", "name_words"]
