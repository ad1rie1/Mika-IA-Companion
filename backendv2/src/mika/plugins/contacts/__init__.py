"""Le plugin ``contacts`` : l'annuaire de tous ceux qu'elle connaît, même sans leur avoir parlé (ADR 0298).

- **Ce qu'il tire** : les auteurs des messages Teams de chaque compte (le port ``teams``) et les correspondants de
  chaque boîte (le port ``mail``), lus petit à petit dans leur ordre d'arrivée (``contacts.ingest``), rangés dans
  l'annuaire (le port ``contacts``, sa base à lui, hors du journal) : le monde, pas sa vie — rien ne s'écrit au
  journal, et une personne connue de loin n'est pas une interlocutrice (ni lien, ni initiative, ni droits).
- **Relier sur preuve** : l'identifiant Teams d'un compte (``self_id``) et l'adresse d'une boîte désignent la
  personne à qui est ce compte, quand elle est une seule (``ports.contacts.account_person``) ; leur contact lui est
  relié, sans jamais défaire un lien posé avant.
- **Les profils Teams** (``teams.profiles_since``) : l'e-mail d'un profil réunit la personne de Teams et celle du
  courrier ; son poste, son service, ses numéros et son entreprise (son organisation) rejoignent sa fiche.
- **Le téléphone** (lot 5) : les expéditeurs des messages WhatsApp et SMS (``phone.received`` : la tranche en garde
  les numéros, ``phone``, que la collecte relit par le port ``store``), contacts de la personne dont c'est le
  téléphone, chacun avec ses conversations.
- **Ce qu'on lui raconte** (lot 5) : chaque personne dont on lui a parlé (une clé ``name:…`` de sa mémoire, lue par sa
  porte : ``contracts.memory.KNOWLEDGE``), contact de qui le lui a raconté ; reliée à la personne que l'identité lui
  relie (``identity.name_bound`` : ``PERSON`` du nom), déliée quand le lien est défait.
- **Quand** : peu après qu'un message Teams, un mail ou un message du téléphone a été remarqué, ou qu'un nom a été
  relié (``heard``), et de toute façon à un rythme lent (ce que l'historique, ses propres messages ou sa mémoire
  apportent, qui ne se remarque pas) ; par lots bornés, et vite tant qu'il en reste.
- **Ce qu'elle en sait** (lot 6, ``contacts.portrait``) : pour une personne avec qui un compte échange vraiment (des
  messages dans les deux sens, dans la fenêtre de ``ContactsParams``), le rôle ``portrait`` relit ses derniers
  messages et en tire quelques faits courts, gardés avec le contact sous la vue d'où ils viennent ; des plafonds par
  jour bornent le coût. Pour le téléphone, la tranche garde où la personne a écrit elle-même (``replied``). Mika les
  consulte par ``contacts_lookup`` (``tools``), seulement en tête-à-tête et ce que la personne en face voit.
- **Le juge des rapprochements** (ADR 0304, ``contacts.match``) : deux fiches qui pourraient être la même personne
  sans identifiant qui le prouve sont soumises au rôle ``match`` avec ce que l'annuaire en sait ; ce dont il est sûr
  se fait d'office (réunies, ou plus proposées), le reste attend dans À valider avec son avis.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Annotated

from pydantic import BaseModel, ConfigDict

from mika.contracts import email as email_c
from mika.contracts import identity as identity_c
from mika.contracts import phone as phone_c
from mika.contracts import teams as teams_c
from mika.kernel.builtin import SUBJECT_FORGOTTEN
from mika.kernel.clock import DAY
from mika.kernel.faculty import Faculty
from mika.kernel.forms import Knob
from mika.kernel.state import FrozenDict

#: les noms reliés (ou déliés) dont elle garde la trace, au plus : les plus récents
NAMED_KEPT = 2000
#: les messages du téléphone qu'elle garde à relire, au plus (les plus récents : la collecte passe peu après chacun ;
#: au-delà, un passage manqué perd les plus anciens)
PHONE_KEPT = 5000
#: les conversations du téléphone où la personne a écrit elle-même, au plus (les plus récentes)
REPLIED_KEPT = 2000
#: le lot de ses outils (``contacts_lookup``) : sa famille dans Réglages › Droits
BUNDLE = "contacts"


class ContactsParams(BaseModel):
    """Ce qu'elle se forme de chacun à partir de ce qu'elle lit (ADR 0298, lot 6) : seulement avec qui un compte
    échange dans les deux sens, seulement ses derniers messages, des plafonds par jour."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    portraits: Annotated[bool, Knob(
        label="Se faire une idée de ses contacts", group="Ce qu'elle en sait",
        help="Pour une personne avec qui un compte échange vraiment (des messages dans les deux sens), elle relit "
             "ses derniers messages et en tire quelques faits courts (son rôle, ses sujets, ce qu'elle attend), un "
             "appel au modèle (rôle « portrait ») par compte. Coupé : plus aucun portrait ; ce qu'elle sait déjà "
             "reste.")] = True
    window_us: Annotated[int, Knob(
        label="Ne relire que les messages des", group="Ce qu'elle en sait", lo=DAY, hi=365 * DAY,
        help="Seuls les messages de cette période comptent, pour savoir qu'on échange et pour ce qu'elle relit : "
             "charger l'historique n'en fait relire que la fin.")] = 30 * DAY
    messages: Annotated[int, Knob(
        label="Messages relus par portrait", group="Ce qu'elle en sait", lo=5, hi=100,
        help="Au plus ses derniers messages dans la période, par compte.")] = 30
    chars: Annotated[int, Knob(
        label="Caractères relus par portrait", group="Ce qu'elle en sait", lo=1000, hi=20000, step=500,
        help="Au plus autant de texte de ses messages par appel (le plus récent d'abord) : ce qui borne le coût "
             "d'un portrait.")] = 6000
    history: Annotated[bool, Knob(
        label="Relire tout l'historique", group="Ce qu'elle en sait",
        help="Coupé (par défaut) : seulement les derniers messages de la période. Activé : sans période, ses "
             "messages de tout l'historique (les plus récents d'abord, jusqu'aux bornes ci-dessous) — plus cher.")] \
        = False
    history_messages: Annotated[int, Knob(
        label="Messages relus, tout l'historique", group="Ce qu'elle en sait", lo=30, hi=200,
        help="Avec « Relire tout l'historique » : au plus autant de ses messages par portrait.")] = 200
    history_chars: Annotated[int, Knob(
        label="Caractères relus, tout l'historique", group="Ce qu'elle en sait", lo=6000, hi=40000, step=1000,
        help="Avec « Relire tout l'historique » : au plus autant de texte par appel.")] = 20000
    refresh_after: Annotated[int, Knob(
        label="Refaire son portrait après", group="Ce qu'elle en sait", lo=1, hi=100,
        help="Nouveaux messages depuis son dernier portrait, par compte, avant qu'elle le refasse (il remplace "
             "le précédent).")] = 5
    first_after: Annotated[int, Knob(
        label="Premier portrait après", group="Ce qu'elle en sait", lo=1, hi=50,
        help="Messages de la personne dans la période avant un premier portrait (un message seul en dit peu).")] = 3
    contacts_per_day: Annotated[int, Knob(
        label="Contacts par jour", group="Ce qu'elle en sait", lo=0, hi=500,
        help="Au plus autant de contacts portraiturés en vingt-quatre heures.")] = 20
    calls_per_day: Annotated[int, Knob(
        label="Appels par jour", group="Ce qu'elle en sait", lo=0, hi=1000,
        help="Au plus autant d'appels au modèle en vingt-quatre heures (un par compte d'un contact ; ceux qui "
             "échouent comptent). Le coût se lit dans Système › Appels, rôle « portrait ».")] = 30
    per_run: Annotated[int, Knob(
        label="Portraits par passage", group="Ce qu'elle en sait", lo=1, hi=50,
        help="Au plus autant d'appels à chaque passage (toutes les heures, ou peu après un message) : la journée "
             "se répartit.")] = 5
    # le juge des rapprochements (ADR 0304)
    matching: Annotated[bool, Knob(
        label="Réunir ses contacts d'elle-même", group="Rapprochements",
        help="Deux fiches qui pourraient être la même personne (le même nom sous une autre forme, un invité de "
             "réunion, un nom qu'on lui a raconté) sont soumises au modèle (rôle « match ») avec tout ce que "
             "l'annuaire en sait : ce dont il est sûr se réunit d'office (et se défait par « Détacher »), ou n'est "
             "plus proposé ; le reste t'attend dans À valider › Rapprochements, avec son avis. Coupé : rien ne se "
             "réunit sans toi, sauf ce qu'un identifiant prouve.")] = True
    match_calls_per_day: Annotated[int, Knob(
        label="Appels du juge par jour", group="Rapprochements", lo=0, hi=500,
        help="Au plus autant d'appels au modèle en vingt-quatre heures (un par groupe de fiches qui se ressemblent ; "
             "ceux qui ne se lisent pas comptent). Le coût se lit dans Système › Appels, rôle « match ».")] = 40
    match_per_run: Annotated[int, Knob(
        label="Appels du juge par passage", group="Rapprochements", lo=1, hi=50,
        help="Au plus autant d'appels à chaque passage (toutes les heures, ou peu après un message).")] = 5


@dataclass(frozen=True, slots=True)
class ContactsState:
    #: les messages Teams, les mails et les messages du téléphone remarqués, les noms reliés : la collecte a de quoi
    #: relire
    heard: int = 0
    #: chaque nom qu'un opérateur a relié à une personne, ou délié (``identity.name_bound``) → le numéro de la dernière
    #: décision : la collecte relie (ou délie) son contact, une fois par décision
    named: FrozenDict[str, int] = field(default_factory=FrozenDict)
    #: les numéros des derniers messages du téléphone écrits par quelqu'un d'autre que la personne (``phone.received``),
    #: dans l'ordre : la collecte relit ceux d'après son curseur
    phone: tuple[int, ...] = ()
    #: chaque conversation du téléphone où la personne a écrit elle-même (``<personne>|<appli>|<conversation>``) →
    #: l'heure de son dernier message : on y échange vraiment (le portrait, lot 6)
    replied: FrozenDict[str, int] = field(default_factory=FrozenDict)


def replied_key(recipient: str, app: str, thread: str) -> str:
    """La clé d'une conversation du téléphone de quelqu'un (``ContactsState.replied``)."""
    return f"{recipient}|{(app or '').strip().lower()}|{thread}"


def params(p: ContactsParams | None) -> ContactsParams:
    return p if p is not None else ContactsParams()


CONTACTS = Faculty("contacts", state=ContactsState, init=lambda p: ContactsState(), params=ContactsParams,
                   state_version=2)


@CONTACTS.reducer(teams_c.NOTICED, email_c.NOTICED)
def _heard(s: ContactsState, e, cx) -> ContactsState:
    return replace(s, heard=s.heard + 1)


@CONTACTS.reducer(phone_c.RECEIVED)
def _phoned(s: ContactsState, e, cx) -> ContactsState:
    if e.data.own:
        key = replied_key(e.data.recipient, e.data.source, e.data.thread)
        replied = s.replied.set(key, max(s.replied.get(key, 0), int(e.data.sent_at or 0) or e.at))
        if len(replied) > REPLIED_KEPT:  # les plus récentes conversations (la carte est rangée par clé)
            replied = FrozenDict(sorted(replied.items(), key=lambda kv: kv[1])[-REPLIED_KEPT:])
        return replace(s, heard=s.heard + 1, replied=replied)
    if not e.data.sender:
        return replace(s, heard=s.heard + 1)
    return replace(s, heard=s.heard + 1, phone=(*s.phone, e.seq)[-PHONE_KEPT:])


@CONTACTS.reducer(identity_c.NAME_BOUND)
def _named(s: ContactsState, e, cx) -> ContactsState:
    named = s.named.set(e.data.name, e.seq)
    if len(named) > NAMED_KEPT:  # les plus récentes décisions (la carte est rangée par nom, pas par arrivée)
        named = FrozenDict(sorted(named.items(), key=lambda kv: kv[1])[-NAMED_KEPT:])
    return replace(s, heard=s.heard + 1, named=named)


@CONTACTS.reducer(SUBJECT_FORGOTTEN)
def _forgotten(s: ContactsState, e, cx) -> ContactsState:
    """Un nom oublié ne se relie plus (l'annuaire l'oublie par son port) ; une personne oubliée n'a plus de
    conversations du téléphone où elle a écrit."""
    who = e.data.subject
    if who in s.named:
        s = replace(s, named=s.named.delete(who))
    mine = [k for k in s.replied if k.startswith(f"{who}|")]
    if mine:
        replied = s.replied
        for k in mine:
            replied = replied.delete(k)
        s = replace(s, replied=replied)
    return s


from mika.plugins.contacts import ingest as ingest  # noqa: E402 — s'enregistre sur CONTACTS
from mika.plugins.contacts import inspect as inspect  # noqa: E402 — sa console : la fiche d'un contact, ses gestes
from mika.plugins.contacts import matching as matching  # noqa: E402 — le juge des rapprochements (ADR 0304)
from mika.plugins.contacts import portrait as portrait  # noqa: E402 — ce qu'elle en sait (lot 6)
from mika.plugins.contacts import tools as tools  # noqa: E402 — contacts_lookup

__all__ = ["BUNDLE", "CONTACTS", "ContactsParams", "ContactsState", "params", "replied_key"]
