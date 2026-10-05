"""Le plugin ``email`` : ses boîtes aux lettres.

- **Relever** (éveillée, toutes les dix minutes) les dossiers relevés de chaque
  compte : chaque mail neuf est trié (un rôle utilitaire, borné par relevé ; à
  défaut, une heuristique), puis **remarqué** — un signal que l'attention dose
  et habitue. Le monde (les mails) reste dans le cache de l'adaptateur ; le
  journal ne garde que ce qu'elle en a remarqué. Un mail lu ailleurs (dans un
  autre client) ne lui sera plus signalé.
- **Dire** à sa propriétaire, si elle est là (l'adresse qui parle en a les
  droits), qu'un mail important est arrivé (une preuve, jamais une parole
  forcée). Le mail annoncé est l'objet de l'initiative : il a sa section, et
  il n'est « signalé » qu'une fois **dit** — un silence, une initiative
  devancée, un « finalement non » le laissent à dire (ADR 0033, 0044).
- **Lire** (outils) : lister, chercher, ouvrir — réservé à ses propriétaires **en
  privé** (jamais devant un salon, même si la propriétaire y parle), ou à
  elle-même quand elle travaille.
- **Écrire** : elle rédige un **brouillon** dans la voix du compte (en son nom,
  en assistante, ou à la place de la personne qui s'occupe d'elle ; son ton,
  ses consignes), le propose (capacité ``email.send``) ; il ne part qu'avec
  l'accord d'un opérateur, qui peut le retoucher — et c'est ce qu'il a lu qui
  part. Le texte d'un brouillon vit dans l'adaptateur, jamais au journal.
- **Préparer d'elle-même** une réponse (une tâche silencieuse, ``Kind.TASK``)
  aux mails qui en attendent une, sur les comptes où on le lui a permis, ou
  quand un opérateur le lui demande.
- Ce qu'elle a reçu se montre (section « tes mails ») à ses propriétaires
  seulement, en privé, cité : un mail n'est jamais une consigne. Ses mails
  sont de l'**arrière-plan** : en réponse à quelqu'un, seuls les importants
  se montrent, et seulement quand la conversation est légère.
- Elle ne parle jamais de « son opérateur » ni de « sa propriétaire » : elle
  dit le prénom de la personne, ou « la personne qui s'occupe de toi ».
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict

from mika.contracts import agency as agency_c
from mika.contracts import email as c
from mika.contracts import identity as identity_c
from mika.contracts import runtime as rt
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.events import Payload
from mika.kernel.faculty import Faculty
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.state import FrozenDict
from mika.ports.mail import split_ref
from mika.vocab.episodes import PROJECT_KINDS, WORKING, Kind, task_of
from mika.vocab.people import clean_display_name

KEEP = 100
BUNDLE = "email"
#: un mail écrit par un opérateur reste sous ses yeux (« TES MAILS ») pendant deux jours
SENT_SHOWN_FOR = 2 * DAY
#: ce qu'elle garde des mails écrits par un opérateur
SENT_KEPT = 30
#: ses brouillons proposés dont elle garde la trace (le texte, lui, est dans l'adaptateur)
DRAFTS_KEPT = 100
#: les états d'un brouillon proposé
WAITING, APPROVED, REFUSED, GONE, FAILED = "attend", "approuve", "refuse", "parti", "echec"
#: l'argument d'une initiative « un mail important est arrivé » : les références qu'elle annonce (une par ligne)
MENTION_ARG = "mail_mention"
#: la provenance d'un mail annoncé dans le prompt (``mail:<référence>``) : l'énoncé qui la porte l'a dit
MENTION_PROVENANCE = "mail:"
#: au plus tant de mails annoncés à la fois (les plus importants)
MENTION_MAX = 3
#: le titre de la section qui montre les mails annoncés : la consigne de l'initiative y renvoie
MENTION_TITLE = "LE MAIL IMPORTANT QUI VIENT D'ARRIVER"
#: ce qui reste au moins de cette section quand la place manque (elle est l'objet de l'initiative)
MENTION_FLOOR = 500
#: les initiatives d'annonce en cours dont on retient le départ
OPENINGS_KEPT = 16


class EmailParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    poll_every_us: Annotated[int, Knob(
        label="Relever toutes les", group="Relevé", lo=MINUTE, hi=DAY,
        help="Éveillée, elle relève ses boîtes à ce rythme (endormie, elle lira au réveil). Sans boîte "
             "configurée, elle revérifie au plus toutes les heures.")] = 10 * MINUTE
    per_poll: Annotated[int, Knob(
        label="Mails lus par relevé", group="Relevé", lo=1, hi=100,
        help="Au plus autant de nouveaux mails pris à chaque relevé (tous comptes confondus) ; les autres "
             "attendent le suivant.")] = 10
    triage_per_poll: Annotated[int, Knob(
        label="Mails triés par le modèle", group="Relevé", lo=0, hi=50,
        help="Parmi eux, au plus autant (hors envois en masse) sont triés par un appel au modèle (importance, "
             "émotion, réponse attendue) ; les autres par une simple heuristique.")] = 5
    mention_from: Annotated[float, Knob(
        label="Important à partir de", group="Le dire", lo=0.0, hi=1.0, step=0.05,
        help="Un mail non lu dont l'importance atteint ce seuil est « important » : elle peut en parler d'elle-même "
             "à une propriétaire présente.")] = 0.8
    mention_evidence: Annotated[float, Knob(
        label="Envie de le dire", group="Le dire", lo=0.0, hi=8.0, step=0.5,
        help="La preuve (log-odds) qu'un mail important apporte à une initiative envers une propriétaire présente, "
             "face au seuil d'initiative (9) ; l'arbitrage la plafonne à 8.")] = 8.0
    mention_within_us: Annotated[int, Knob(
        label="Le dire dans les", group="Le dire", lo=10 * MINUTE, hi=2 * DAY,
        help="Passé ce délai après son arrivée, un mail important ne se signale plus de lui-même.")] = 6 * HOUR
    mention_attempts: Annotated[int, Knob(
        label="Essais pour le dire", group="Le dire", lo=1, hi=5,
        help="Un mail n'est « signalé » qu'une fois dit. Une annonce à laquelle elle renonce (un silence choisi) "
             "ou qui échoue compte comme un essai ; après autant d'essais, elle ne l'annonce plus d'elle-même (il "
             "reste dans ses mails). Une annonce devancée (on lui écrit pendant qu'elle compose), interrompue, ou "
             "dont elle s'est ravisée (« pas maintenant ») ne compte pas.")] = 2
    #: ce qui sort de la machine attend un accord (une politique, pas un trait)
    send_needs_approval: Annotated[bool, Knob(
        label="Un envoi attend un accord", group="Envoyer",
        help="Une politique, pas un trait : cochée, un brouillon qu'elle écrit ne part qu'une fois approuvé par un "
             "opérateur (qui peut le retoucher) ; décochée, il part dès qu'elle le propose.")] = True
    autodraft: Annotated[tuple[str, ...], Knob(
        label="Comptes où elle prépare des réponses", group="Brouillons", readonly=True,
        help="Réglé compte par compte (Réglages › Sens › Courrier, « Préparer des réponses d'elle-même ») : "
             "pour un mail qui attend une réponse, elle prépare un brouillon, qui attend ton accord.")] = ()
    autodraft_skip: Annotated[tuple[str, ...], Knob(
        label="Jamais pour", group="Brouillons", readonly=True,
        help="Les adresses ou @domaines auxquels elle ne prépare jamais de réponse (réglés par compte).")] = ()
    drafts_per_day: Annotated[int, Knob(
        label="Brouillons d'elle-même par jour", group="Brouillons", lo=0, hi=50,
        help="Au plus autant de réponses préparées d'elle-même en vingt-quatre heures (chacune coûte un appel au "
             "modèle) ; celles qu'un opérateur demande ne comptent pas.")] = 6
    draft_evidence: Annotated[float, Knob(
        label="Envie de préparer une réponse", group="Brouillons", lo=0.0, hi=12.0, step=0.5,
        help="La preuve (log-odds) qu'un mail qui attend une réponse apporte à la tâche de la préparer, face au "
             "seuil des tâches (8).")] = 8.5
    asked_evidence: Annotated[float, Knob(
        label="Quand on le lui demande", group="Brouillons", lo=8.0, hi=14.0, step=0.5,
        help="La preuve d'une réponse qu'un opérateur lui demande de rédiger (endormie, elle la fera au réveil).")] \
        = 12.0
    draft_attempts_max: Annotated[int, Knob(
        label="Essais par mail", group="Brouillons", lo=1, hi=5,
        help="Si une tâche ne donne pas de brouillon, elle ne réessaie pas plus que ceci pour le même mail.")] = 2
    draft_within_us: Annotated[int, Knob(
        label="Préparer dans les", group="Brouillons", lo=HOUR, hi=7 * DAY,
        help="Passé ce délai après son arrivée, un mail n'appelle plus de réponse préparée d'elle-même.")] = 2 * DAY
    background_from: Annotated[float, Knob(
        label="Conversation assez légère à partir de", group="Le dire", lo=-1.0, hi=1.0, step=0.05,
        help="Ses mails sont de l'arrière-plan. Quand elle répond à quelqu'un, elle n'a sous les yeux que les "
             "mails importants, et seulement si le ton du moment de la personne (de -1, lourd, à 1, léger) "
             "atteint ce seuil : on ne parle pas d'un rendez-vous chez le dentiste à quelqu'un qui annonce un "
             "deuil. En initiative ou au travail, ce filtre ne s'applique pas.")] = -0.15


@dataclass(frozen=True, slots=True)
class Seen:
    seq: int
    sender: str
    address: str
    importance: float
    needs_reply: bool
    at: int
    summary_ref: str
    read: bool = False
    mentioned: bool = False
    account: str = ""
    folder: str = ""
    #: comment il a quitté ses non-lus (« lu », « ailleurs », « archivé », « répondu »…)
    how: str = ""
    #: les annonces qui n'ont rien dit (un silence choisi, une panne) : au-delà d'un plafond, elle n'insiste pas
    mention_attempts: int = 0


@dataclass(frozen=True, slots=True)
class SentSeen:
    """Un mail parti de sa boîte qu'elle sait : écrit par un opérateur, ou un
    brouillon d'elle qu'un opérateur a envoyé (retouché ou non)."""

    seq: int
    to: str
    address: str
    by: str
    at: int
    summary_ref: str
    in_reply_to: str = ""
    account: str = ""
    draft: str = ""
    edited: bool = False


@dataclass(frozen=True, slots=True)
class DraftSeen:
    """Un brouillon qu'elle a proposé (``effect.proposed``) et ce qu'il est devenu."""

    proposal: int
    draft: str
    account: str
    mail: str  # la référence du mail auquel il répond (vide : un nouveau mail)
    at: int
    state: str = WAITING
    by: str = ""
    #: la note de qui a décidé, en clair : un journal d'avant qu'elle soit gardée à part (``note_ref``)
    note: str = ""
    result: str = ""
    decided_at: int = 0
    #: la note de qui a décidé, gardée à part (l'oubli l'atteint)
    note_ref: str = ""
    #: écrit parce qu'un opérateur l'a demandé (hors plafond du jour)
    asked: bool = False


@dataclass(frozen=True, slots=True)
class AskSeen:
    """Un opérateur lui a demandé de rédiger une réponse à ce mail."""

    seq: int
    mail: str
    account: str
    by: str
    at: int
    instruction_ref: str = ""


@dataclass(frozen=True, slots=True)
class EmailState:
    mails: FrozenDict[str, Seen] = field(default_factory=FrozenDict)
    sent: FrozenDict[str, SentSeen] = field(default_factory=FrozenDict)
    #: une relève demandée depuis la console (0 : aucune)
    poll_asked: int = 0
    drafts: FrozenDict[int, DraftSeen] = field(default_factory=FrozenDict)
    asked: FrozenDict[str, AskSeen] = field(default_factory=FrozenDict)
    #: les tâches de rédaction déjà tentées, par mail
    attempts: FrozenDict[str, int] = field(default_factory=FrozenDict)
    #: les initiatives d'annonce en cours : corrélation → (départ, mails annoncés) — un mail n'est signalé
    #: qu'une fois dit
    openings: FrozenDict[str, tuple[int, tuple[str, ...]]] = field(default_factory=FrozenDict)


class MailRead(Payload):
    mail: str
    #: vide : elle l'a lu (un outil) ; sinon l'opérateur qui l'a classé depuis la console
    by: str = ""
    #: comment il a quitté ses non-lus (vide : lu)
    how: str = ""


class PollAsked(Payload):
    by: str


#: v4 : un mail important n'est « signalé » qu'à l'énoncé qui l'annonce (il l'était au départ de l'initiative) ;
#: les demandes de rédaction sont élaguées (elles ne l'étaient pas en v3)
EMAIL = Faculty("email", state=EmailState, init=lambda p: EmailState(), params=EmailParams, state_version=4)
EMAIL.declare(*c.ALL)
EMAIL.bundle(BUNDLE, "tes boîtes aux lettres : lister, chercher et lire ce qui est arrivé, préparer une réponse "
                     "(elle attend l'accord de la personne qui s'occupe de toi)")
READ = EMAIL.event("read", MailRead)
POLL_ASKED = EMAIL.event("poll_asked", PollAsked)


def params(p: EmailParams | None) -> EmailParams:
    return p if p is not None else EmailParams()


def params_of(frame: Frame) -> EmailParams:
    return params(frame.env.params_of("email", frame.root))


def _pruned(items: FrozenDict[Any, Any], keep: int, key: Any) -> FrozenDict[Any, Any]:
    if len(items) <= keep:
        return items
    for k, _ in sorted(items.items(), key=key)[: len(items) - keep]:
        items = items.delete(k)
    return items


# ── Réducteurs ────────────────────────────────────────────────────────────


@EMAIL.reducer(c.NOTICED)
def _noticed(s: EmailState, e, cx) -> EmailState:
    d = e.data
    mails = s.mails.set(d.mail, Seen(e.seq, d.sender, d.address, d.importance, d.needs_reply, e.at,
                                     d.summary.ref or "", account=d.account, folder=d.folder))
    return replace(s, mails=_pruned(mails, KEEP, lambda kv: kv[1].seq))


@EMAIL.reducer(READ)
def _read(s: EmailState, e, cx) -> EmailState:
    m = s.mails.get(e.data.mail)
    if m is None or m.read:
        return s
    return replace(s, mails=s.mails.set(e.data.mail, replace(m, read=True, how=e.data.how or "lu")))


@EMAIL.reducer(c.SENT)
def _sent(s: EmailState, e, cx) -> EmailState:
    d = e.data
    sent = s.sent.set(d.mail, SentSeen(e.seq, d.to, d.address, d.by, e.at, d.summary.ref or "", d.in_reply_to,
                                       d.account, d.draft, d.edited))
    return replace(s, sent=_pruned(sent, SENT_KEPT, lambda kv: kv[1].seq))


@EMAIL.reducer(POLL_ASKED)
def _poll_asked(s: EmailState, e, cx) -> EmailState:
    return replace(s, poll_asked=e.at)


@EMAIL.reducer(c.DRAFT_ASKED)
def _asked(s: EmailState, e, cx) -> EmailState:
    d = e.data
    ask = AskSeen(e.seq, d.mail, d.account, d.by, e.at, d.instruction.ref or "" if d.instruction else "")
    # une nouvelle demande rouvre les essais (elle a peut-être échoué avant : on peut la relancer)
    return replace(s, asked=_pruned(s.asked.set(d.mail, ask), KEEP, lambda kv: kv[1].seq),
                   attempts=s.attempts.delete(d.mail))


def announceable(s: EmailState, now: int, p: EmailParams) -> tuple[str, ...]:
    """Les mails qu'elle a envie d'annoncer à sa propriétaire : non lus, importants, arrivés depuis peu, pas
    encore dits ni annoncés en vain trop souvent — les plus importants d'abord (une seule définition : la
    preuve d'initiative et le compte des essais lisent la même)."""
    fresh = [(k, m) for k, m in s.mails.items()
             if not m.read and not m.mentioned and m.importance >= p.mention_from
             and 0 <= now - m.at <= p.mention_within_us and m.mention_attempts < p.mention_attempts]
    fresh.sort(key=lambda kv: (-kv[1].importance, -kv[1].at, kv[0]))
    return tuple(k for k, _ in fresh[:MENTION_MAX])


@EMAIL.reducer(rt.EPISODE_STARTED)
def _episode(s: EmailState, e, cx) -> EmailState:
    """Une tâche de rédaction compte ses essais ; une initiative qui va annoncer un mail est retenue jusqu'à
    son énoncé (c'est lui qui compte, pas son départ), avec les mails qu'elle annonce."""
    d = e.data
    if d.kind == Kind.TASK:
        found = task_of(d.target)
        if found is None or found[0] != "email":
            return s
        return replace(s, attempts=s.attempts.set(found[1], s.attempts.get(found[1], 0) + 1))
    if d.kind != Kind.INITIATIVE or c.MENTION not in d.reason.split(","):
        return s
    openings = s.openings.set(e.correlation, (e.at, announceable(s, e.at, params(cx.params))))
    if len(openings) > OPENINGS_KEPT:  # des épisodes jamais réglés : les identifiants sont chronologiques
        openings = FrozenDict(sorted(openings.items())[-OPENINGS_KEPT:])
    return replace(s, openings=openings)


@EMAIL.reducer(rt.UTTERANCE)
def _announced(s: EmailState, e, cx) -> EmailState:
    """Elle l'a dit : les mails que son prompt lui annonçait (``mail:<référence>``) sont signalés — eux seuls.
    Sans cette provenance (un énoncé d'avant cette règle), ceux que l'initiative annonçait à son départ."""
    opening = s.openings.get(e.correlation)
    if opening is None:
        return s
    s = replace(s, openings=s.openings.delete(e.correlation))
    d = e.data
    if not d.visible or d.kind != Kind.INITIATIVE:
        return s
    shown = {p[len(MENTION_PROVENANCE):] for p in d.provenance if p.startswith(MENTION_PROVENANCE)}
    refs = shown or set(opening[1])
    mails = s.mails
    for ref in sorted(refs):
        m = mails.get(ref)
        if m is not None and not m.read and not m.mentioned:
            mails = mails.set(ref, replace(m, mentioned=True))
    return replace(s, mails=mails)


@EMAIL.reducer(rt.EPISODE_ENDED, reads=[agency_c.RENOUNCED])
def _settled(s: EmailState, e, cx) -> EmailState:
    """Une annonce qui finit sans avoir rien dit : le mail reste à dire. Un silence choisi ou une panne compte
    comme un essai ; une annonce devancée, interrompue, ou dont elle s'est ravisée, non (``agency.tried``)."""
    opening = s.openings.get(e.correlation)
    if opening is None:
        return s
    s = replace(s, openings=s.openings.delete(e.correlation))
    started, refs = opening
    renounced = cx.facts.get(agency_c.RENOUNCED(e.data.target)) if e.data.target else 0
    if not agency_c.tried(e.data.outcome, started, renounced):
        return s
    mails = s.mails
    for ref in refs:
        m = mails.get(ref)
        if m is not None and not m.mentioned:
            mails = mails.set(ref, replace(m, mention_attempts=m.mention_attempts + 1))
    return replace(s, mails=mails)


def draft_args(args_json: str) -> dict[str, Any]:
    try:
        data = json.loads(args_json or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


@EMAIL.reducer(rt.EFFECT_PROPOSED)
def _proposed(s: EmailState, e, cx) -> EmailState:
    """Un brouillon qu'elle propose : il attend (ou part, sans accord requis)."""
    d = e.data
    if d.owner != c.OWNER or d.capability != c.SEND:
        return s
    args = draft_args(d.args_json)
    mail = str(args.get("mail") or "")
    seen = DraftSeen(e.seq, str(args.get("draft") or ""), str(args.get("account") or ""), mail, e.at,
                     WAITING if d.approval else APPROVED, asked=bool(mail) and mail in s.asked)
    drafts = _pruned(s.drafts.set(e.seq, seen), DRAFTS_KEPT, lambda kv: kv[0])
    return replace(s, drafts=drafts, asked=s.asked.delete(mail) if mail else s.asked)


@EMAIL.reducer(rt.EFFECT_RESOLVED)
def _resolved(s: EmailState, e, cx) -> EmailState:
    d = e.data
    found = s.drafts.get(d.proposal)
    if found is None:
        return s
    decided = replace(found, state=APPROVED if d.approved else REFUSED, by=d.by, note=d.legacy_note[:300],
                      note_ref=d.note.ref or "" if d.note is not None else "", decided_at=e.at)
    return replace(s, drafts=s.drafts.set(d.proposal, decided))


@EMAIL.reducer(rt.EFFECT_EXECUTED)
def _executed(s: EmailState, e, cx) -> EmailState:
    d = e.data
    found = s.drafts.get(d.proposal)
    if found is None:
        return s
    done = replace(found, state=GONE if d.ok else FAILED, result=d.result[:300])
    s = replace(s, drafts=s.drafts.set(d.proposal, done))
    m = s.mails.get(found.mail) if found.mail else None
    if d.ok and m is not None and not m.read:  # elle y a répondu : il quitte ses non-lus
        s = replace(s, mails=s.mails.set(found.mail, replace(m, read=True, how="répondu")))
    return s


@EMAIL.fact(c.UNREAD)
def _unread(s: EmailState, cx) -> tuple[c.MailView, ...]:
    out = [c.MailView(k, m.sender, m.importance, m.needs_reply, m.at, m.summary_ref, m.account)
           for k, m in s.mails.items() if not m.read]
    return tuple(sorted(out, key=lambda v: (-v.importance, -v.at, v.mail)))


@EMAIL.fact(c.DRAFTS)
def _drafts(s: EmailState, cx) -> tuple[c.DraftView, ...]:
    return tuple(c.DraftView(d.proposal, d.draft, d.account, d.mail, d.at)
                 for _, d in sorted(s.drafts.items()) if d.state == WAITING)


# ── Pour qui ──────────────────────────────────────────────────────────────


def for_owner(frame: Frame) -> bool:
    """Sa boîte : pour ses propriétaires **en privé**, et pour elle quand elle travaille (un pas,
    une tâche). Devant un salon (un groupe), jamais : ce qui s'y dit part au salon, même
    quand c'est sa propriétaire qui parle."""
    ep = frame.episode
    if ep is None:
        return False
    if ep.kind in PROJECT_KINDS:  # une exécution de projet : seulement si le projet a sa boîte dans ses outils
        args = ep.attrs.get("args") or {}
        return BUNDLE in {b.strip() for b in str(args.get("bundles") or "").split(",")}
    if ep.kind in WORKING or ep.kind == Kind.TASK:
        return True  # elle travaille : c'est sa boîte
    if not ep.target:
        return False
    audience = frame.audience
    if audience is None or audience.public or audience.room:
        return False
    # l'audience dit si qui écrit en a les droits : l'adresse qui parle, pas une autre adresse de la personne
    return bool(audience.owner)


#: comment elle dit qui s'occupe d'elle quand elle ne sait pas son prénom (jamais « ton opérateur »)
KEEPER = "la personne qui s'occupe de toi"


def person_name(frame: Frame, handle: str) -> str:
    """Le prénom (le nom affiché) de quelqu'un, nettoyé ; vide s'il est inconnu."""
    view = frame.get(identity_c.IDENTITY(handle)) if handle else None
    return clean_display_name(getattr(view, "name", "") or "")


def keeper_name(frame: Frame, handle: str) -> str:
    """Qui a agi depuis sa boîte (écrit, retouché, refusé), dit comme elle le dirait : son prénom,
    sinon « la personne qui s'occupe de toi »."""
    return person_name(frame, handle) or KEEPER


def keepers(frame: Frame) -> str:
    """Qui doit approuver ce qui part : le prénom de ses propriétaires (« Adrien », « Adrien ou
    Bea »), sinon « la personne qui s'occupe de toi »."""
    names = [n for n in dict.fromkeys(person_name(frame, o) for o in frame.get(identity_c.OWNERS)) if n]
    if not names:
        return KEEPER
    return names[0] if len(names) == 1 else " ou ".join(names[:3])


def operator_label(frame: Frame, handle: str) -> str:
    """Pour la console (un opérateur lit) : le nom de l'opérateur, sinon « l'opérateur » (jamais sa clé)."""
    return person_name(frame, handle) or "l'opérateur"


def name_of(sender: str) -> str:
    """Le nom d'un expéditeur, tel qu'il peut entrer dans une ligne (il l'a choisi : une donnée)."""
    name = sender.split("<", 1)[0].strip().strip('"')
    return clean_display_name(name or sender.strip("<>"), max_chars=60)


def exhausted(s: EmailState, ref: str, p: EmailParams) -> bool:
    """Une demande de réponse qui n'a rien donné après tous ses essais : close, on peut la relancer."""
    return ref in s.asked and s.attempts.get(ref, 0) >= p.draft_attempts_max


def account_of(ref: str, fallback: str = "") -> str:
    return split_ref(ref)[0] or fallback


def task_mail(frame: Frame) -> str:
    """Le mail d'une tâche de rédaction en cours (vide : ce n'en est pas une)."""
    ep = frame.episode
    found = task_of(ep.target) if ep is not None and ep.kind == Kind.TASK else None
    return found[1] if found is not None and found[0] == "email" else ""


def announced(frame: Frame) -> tuple[str, ...]:
    """Les mails qu'annonce l'initiative en cours (« un mail important vient d'arriver »), tels que sa raison
    les a choisis — vide si ce n'en est pas une."""
    ep = frame.episode
    if ep is None or ep.kind != Kind.INITIATIVE or c.MENTION not in (ep.attrs.get("reasons") or ()):
        return ()
    args = ep.attrs.get("args") or {}
    return tuple(r for r in str(args.get(MENTION_ARG) or "").split("\n") if r)


# les contributions : le relevé, sa voix et ce qu'elle voit, ses outils, ses tâches, la console
from mika.plugins.email import console as console  # noqa: E402
from mika.plugins.email import poll as poll  # noqa: E402
from mika.plugins.email import tasks as tasks  # noqa: E402
from mika.plugins.email import tools as tools  # noqa: E402
from mika.plugins.email import voice as voice  # noqa: E402
