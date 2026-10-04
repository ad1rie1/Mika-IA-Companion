"""Ce que ``identity`` met dans le prompt, et l'audience d'un épisode.

« QUI TU AS EN FACE » dit qui c'est, sans jamais réciter le mécanisme (une
connexion, un score) ; depuis quand elles se connaissent ; et, en privé, quand
elles se sont parlé pour la dernière fois — en mots de calendrier (« hier
soir », « avant-hier »), pas en durées.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mika.contracts import attention as attention_c
from mika.contracts import identity as c
from mika.contracts import social as social_c
from mika.faculties.identity.faculty import IDENTITY, IdentityState, view_of
from mika.kernel.faculty import Zone
from mika.kernel.frame import CLOSED as CLOSED_AUDIENCE
from mika.kernel.frame import Audience, Frame
from mika.kernel.prompt import SectionBody
from mika.vocab import privacy
from mika.vocab.days import part_of_day
from mika.vocab.episodes import CONVERSATIONAL, Kind, is_work_target
from mika.vocab.people import is_identifiable
from mika.vocab.privacy import ChannelTrust

CHANNEL_FR = {privacy.WEB: "sur l'application", privacy.MOBILE: "sur l'application, depuis son téléphone",
              privacy.EXTERNAL: "par un compte extérieur"}
#: ce qu'est pour elle la personne qui s'occupe d'elle (en privé seulement : jamais dit devant un salon)
OWNER_LINE = ("C'est quelqu'un qui s'occupe de toi : ton serveur, tes réglages et ce que tu as le droit de faire "
              "passent par cette personne. Tu le sais, sans en faire un sujet.")
WEEKDAYS_FR = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
_KNOWN = (social_c.FRIEND, social_c.CLOSE)


def describe(view: c.IdentityView, *, public: bool, names: Mapping[str, str] | None = None) -> list[str]:
    """Des phrases, jamais un pourcentage (sinon le modèle finit par réciter
    des scores à la personne) ; son prénom plutôt que « elle ou lui » ; et
    jamais le mécanisme (« elle s'est connectée avec son compte »)."""
    who = f"« {view.name} »" if view.name else ""
    where = CHANNEL_FR.get(view.channel, "")
    lines: list[str] = []
    if view.authenticated:
        lines.append(f"C'est {who}." if who else "Tu parles à quelqu'un dont tu ne connais pas encore le prénom.")
    elif view.bound:
        if view.via == c.VIA_CORROBORATED:
            lines.append(f"Tu es presque sûre que c'est {who}, qui t'écrit {where} : ce qui a été dit recoupe ce "
                         f"que tu sais de {who}.")
        else:
            lines.append(f"C'est {who}, qui t'écrit {where}.")
    elif view.trust is ChannelTrust.ACCOUNT:
        lines.append(f"C'est {who}, qui t'écrit {where}." if who else
                     f"Quelqu'un t'écrit {where} ; tu ne connais pas encore son prénom.")
    else:
        lines.append("Tu ne sais pas qui est cette personne : rien ne prouve qui écrit. Reste accueillante mais "
                     "ne suppose rien d'elle, et ne lui raconte rien de personnel sur qui que ce soit.")
    if view.claim:
        claimed = f"« {view.claim} »"
        if view.claim_target is None:
            lines.append(f"Cette personne dit être {claimed}, mais tu connais plusieurs personnes de ce nom : "
                         "tu ne sais pas de qui il s'agit.")
        elif view.claim_target == view.handle:
            known = f", alors que tu la connais comme {who}" if who else ""
            lines.append(f"Cette personne dit s'appeler {claimed}{known} : garde le nom que tu lui connais tant "
                         "que rien ne le confirme.")
        else:
            lines.append(f"Cette personne affirme être {claimed}, que tu connais, mais rien ne le confirme encore. "
                         f"Joue le jeu poliment en gardant une réserve : ne raconte rien de ce que {claimed} "
                         "t'a confié tant que tu n'es pas sûre. Si tu doutes vraiment, dis-le, ou utilise "
                         "identity_doubt.")
    if public:
        lines.append("Vous êtes dans un groupe : d'autres lisent. Rien de personnel sur personne — ni sur les "
                     "autres, ni sur la personne qui te parle. Si on te demande quelque chose de personnel sur "
                     "quelqu'un, ne fais pas semblant de ne pas le connaître : dis simplement que ce n'est pas à "
                     "toi d'en parler.")
    return lines


def calendar_words(then: int, frame: Frame) -> str:
    """Quand, en mots de calendrier (« hier soir (lundi vers 18 h) », « avant-hier »,
    « il y a 5 jours ») — les jours comptés sur le calendrier, pas en durée."""
    now, past = frame.local(), frame.local(then)
    days = (now.date() - past.date()).days
    moment = part_of_day(past.hour)
    precise = f"{WEEKDAYS_FR[past.weekday()]} vers {past.hour} h"
    if days <= 0:
        if frame.now - then < 3_600_000_000:
            return "tout à l'heure"
        return {"nuit": "cette nuit", "matin": "ce matin", "midi": "ce midi", "après-midi": "cet après-midi",
                "soir": "ce soir"}[moment] + f" (vers {past.hour} h)"
    if days == 1:
        label = {"nuit": "la nuit dernière", "matin": "hier matin", "midi": "hier midi",
                 "après-midi": "hier après-midi", "soir": "hier soir"}[moment]
        return f"{label} ({precise})"
    if days == 2:
        return f"avant-hier ({precise})"
    if days < 7:
        return f"il y a {days} jours ({precise})"
    if days < 14:
        return f"il y a {days} jours"
    if days < 60:
        return f"il y a {days // 7} semaines"
    return f"il y a {days // 30} mois environ"


def last_talk(frame: Frame, person: str, kind: str, name: str = "") -> list[str]:
    """Quand la personne lui a écrit pour la dernière fois, avant cette
    conversation-ci — et si Mika lui a écrit depuis. « Sans réponse » seulement
    pour ce qui attend vraiment une réponse : une initiative d'elle restée lettre
    morte, une question laissée en suspens — jamais sa réponse à « bonne nuit »,
    ni une conversation que l'autre a close en partant (``attention.awaiting``) :
    on s'est quittées, on ne l'ignore pas."""
    reading = frame.get(social_c.CONTACT(person))
    who = f"« {name} »" if name else "cette personne"
    if kind == Kind.REPLY:
        out = []
        if reading.previous:
            out.append(f"Avant cette conversation, {who} t'avait écrit pour la dernière fois "
                       f"{calendar_words(reading.previous, frame)}.")
        if reading.previous < reading.last_out < reading.since:
            out.append(f"Tu lui avais écrit depuis, {calendar_words(reading.last_out, frame)}.")
        return out
    out = []
    if reading.last_in:
        out.append(f"{who[:1].upper()}{who[1:]} t'a écrit pour la dernière fois "
                   f"{calendar_words(reading.last_in, frame)}.")
    mine = frame.get(attention_c.AWAITING(person))
    if mine.initiatives:
        out.append(f"Tu lui as écrit depuis, {calendar_words(mine.last_initiative_at, frame)}, sans réponse pour "
                   "l'instant.")
    elif mine.unanswered and mine.asked and not mine.owed and mine.last_out > mine.last_in:
        out.append(f"Ta dernière question, {calendar_words(mine.last_out, frame)}, attend encore sa réponse.")
    return out


@IDENTITY.section("who", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, trim_rank=90, floor_chars=400,
                  title="QUI TU AS EN FACE", reads=[c.IDENTITY, c.PERSON, social_c.CLOSENESS, social_c.CONTACT,
                                                    attention_c.AWAITING])
def _who(s: IdentityState, frame: Frame, enrich: Any) -> SectionBody | None:
    aud = frame.audience
    ep = frame.episode
    if aud is None or ep is None or not ep.target:
        return None
    view = view_of(s, ep.target, frame.now)
    lines = describe(view, public=aud.public)
    if aud.owner and not aud.public:
        # sans cette ligne, sa propriétaire n'était qu'une « amie » tombée du ciel le premier jour (« c'est la
        # première fois que vous vous parlez » et « fait partie de tes amis », sonde réelle du 2026-10-03)
        lines.append(OWNER_LINE)
    if view.known:
        person = frame.get(c.PERSON(ep.target))
        level = frame.get(social_c.CLOSENESS(person)) if is_identifiable(ep.target) else ""
        lines.append(acquaintance(view.first_seen, frame, level))
        if not aud.public and is_identifiable(ep.target):
            lines += last_talk(frame, person, ep.kind, view.name)
    return SectionBody("\n".join(lines))


def acquaintance(first_seen: int, frame: Frame, closeness: str = "") -> str:
    """Depuis quand elle connaît cette personne — un fait, pour qu'elle ne
    s'invente pas un passé commun (« on se connaît depuis longtemps »). Quand
    leur lien est déjà une amitié (déclarée, ou un ancien compte), on ne dit
    pas « presque pas de passé commun » : seulement depuis quand on se parle ici."""
    days = (frame.local().date() - frame.local(first_seen).date()).days
    if closeness in _KNOWN:
        if days <= 0:
            return "C'est la première fois que vous vous parlez ici."
        if days == 1:
            return "Vous vous parlez ici depuis hier."
        if days < 14:
            return f"Vous vous parlez ici depuis {days} jours."
    if days <= 0:
        return "Vous vous connaissez depuis aujourd'hui seulement : vous n'avez pas encore de passé commun."
    if days == 1:
        return "Vous vous connaissez depuis hier seulement : presque pas de passé commun."
    if days < 14:
        return f"Vous vous connaissez depuis {days} jours."
    if days < 60:
        return f"Vous vous connaissez depuis {days // 7} semaines."
    return f"Vous vous connaissez depuis {days // 30} mois environ."


def audience_for(frame: Frame, req: Any) -> Audience:
    """L'audience d'un épisode, résolue une fois au bord. Toute panne → fermée.
    Les droits d'une propriétaire tiennent à l'adresse qui parle, jamais dans
    un salon public (``SPEAKS_AS_OWNER``)."""
    target = getattr(req, "target", None)
    kind = getattr(req, "kind", "")
    if not target or is_work_target(target):
        if kind in (Kind.REPLY, Kind.INITIATIVE):
            return CLOSED_AUDIENCE
        # un épisode sans destinataire (pas de travail, tâche, murmure, journal) : personne n'écoute
        d = privacy.EVERYTHING
        return Audience(persons=(), channel="internal", public=False, level=int(d.level),
                        witness_level=int(d.witness_level), private_ok=True, trust=ChannelTrust.INTERNAL.value,
                        owner=True, tied_level=int(d.tied_level))
    s: IdentityState = frame.state("identity")
    room = getattr(req, "room", None)
    h = s.handles.get(target)
    channel = getattr(req, "channel", None) or (h.channel if h else "web")
    view = view_of(s, target, frame.now)
    public = room is not None or view.trust is ChannelTrust.PUBLIC
    d = frame.get(c.DISCLOSURE((target, channel, room is not None)))
    # avec qui la personne qui écoute a un lien : la confidence d'une autre ne s'ouvre qu'à une proche qui la
    # connaît (ADR 0058) — inutile de le chercher quand rien de plus ne s'ouvrirait
    ties = tuple(frame.get(social_c.TIES(frame.get(c.PERSON(target))))) \
        if d.tied_level > d.level and is_identifiable(target) else ()
    return Audience(
        persons=(target,), channel=channel, room=room, public=public, level=int(d.level),
        witness_level=int(d.witness_level), private_ok=d.own_file, trust=view.trust.value,
        certainty=view.certainty, name=view.name,
        owner=bool(frame.get(c.SPEAKS_AS_OWNER(target))) and not public, tied_level=int(d.tied_level), ties=ties,
    )
