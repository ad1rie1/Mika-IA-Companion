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
from mika.contracts import self_ as self_c
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
from mika.vocab.phrasebook import family, phrase, phrases
from mika.vocab.privacy import ChannelTrust


def owner_line(frame: Frame) -> str:
    """Ce qu'est pour elle la personne qui s'occupe d'elle (en privé seulement : jamais dit devant un salon),
    selon sa nature : rien d'une machine si elle est incarnée (ADR 0070) — ni serveur ni réglages, quelqu'un sur
    qui elle peut compter."""
    if frame.get(self_c.PERSONA).nature == self_c.EMBODIED:
        return phrase("identity.owner.embodied")
    return phrase("identity.owner.ai")


_KNOWN = (social_c.FRIEND, social_c.CLOSE)
#: le moment de la journée (``vocab.days.part_of_day``) → sa clé dans ``identity.calendar.today`` / ``yesterday``
_MOMENT = {"nuit": "night", "matin": "morning", "midi": "noon", "après-midi": "afternoon", "soir": "evening"}


def describe(view: c.IdentityView, *, public: bool, names: Mapping[str, str] | None = None) -> list[str]:
    """Des phrases, jamais un pourcentage (sinon le modèle finit par réciter
    des scores à la personne) ; son prénom plutôt que « elle ou lui » ; et
    jamais le mécanisme (« elle s'est connectée avec son compte »)."""
    who = f"« {view.name} »" if view.name else ""
    where = family("identity.channel").get(view.channel, "")
    lines: list[str] = []
    if view.authenticated:
        lines.append(phrase("identity.who.authenticated", who=who) if who else
                     phrase("identity.who.authenticated_unnamed"))
    elif view.bound:
        if view.via == c.VIA_CORROBORATED:
            lines.append(phrase("identity.who.corroborated", who=who, where=where))
        else:
            lines.append(phrase("identity.who.bound", who=who, where=where))
    elif view.trust is ChannelTrust.ACCOUNT:
        lines.append(phrase("identity.who.bound", who=who, where=where) if who else
                     phrase("identity.who.account_unnamed", where=where))
    else:
        lines.append(phrase("identity.who.unknown"))
    if view.claim:
        claimed = f"« {view.claim} »"
        if view.claim_target is None:
            lines.append(phrase("identity.claim.ambiguous", claimed=claimed))
        elif view.claim_target == view.handle:
            known = phrase("identity.claim.known_as", who=who) if who else ""
            lines.append(phrase("identity.claim.renamed", known=known, claimed=claimed))
        else:
            lines.append(phrase("identity.claim.other", claimed=claimed))
    if public:
        lines.append(phrase("identity.who.public"))
    return lines


def calendar_words(then: int, frame: Frame) -> str:
    """Quand, en mots de calendrier (« hier soir (lundi vers 18 h) », « avant-hier »,
    « il y a 5 jours ») — les jours comptés sur le calendrier, pas en durée."""
    now, past = frame.local(), frame.local(then)
    days = (now.date() - past.date()).days
    moment = _MOMENT[part_of_day(past.hour)]
    precise = phrase("identity.calendar.precise", weekday=phrases("identity.calendar.weekdays")[past.weekday()],
                     hour=past.hour)
    if days <= 0:
        if frame.now - then < 3_600_000_000:
            return phrase("identity.calendar.just_now")
        return phrase("identity.calendar.today_at", moment=family("identity.calendar.today")[moment], hour=past.hour)
    if days == 1:
        return phrase("identity.calendar.yesterday_at", moment=family("identity.calendar.yesterday")[moment],
                      precise=precise)
    if days == 2:
        return phrase("identity.calendar.two_days", precise=precise)
    if days < 7:
        return phrase("identity.calendar.days_precise", days=days, precise=precise)
    if days < 14:
        return phrase("identity.calendar.days", days=days)
    if days < 60:
        return phrase("identity.calendar.weeks", weeks=days // 7)
    return phrase("identity.calendar.months", months=days // 30)


def last_talk(frame: Frame, person: str, kind: str, name: str = "") -> list[str]:
    """Quand la personne lui a écrit pour la dernière fois, avant cette
    conversation-ci — et si Mika lui a écrit depuis. « Sans réponse » seulement
    pour ce qui attend vraiment une réponse : une initiative d'elle restée lettre
    morte, une question laissée en suspens — jamais sa réponse à « bonne nuit »,
    ni une conversation que l'autre a close en partant (``attention.awaiting``) :
    on s'est quittées, on ne l'ignore pas. Quand l'application de la personne dit
    ce qu'elle a lu, si elle a vu cette initiative — un constat, jamais un
    reproche ; sinon, rien de plus qu'avant."""
    reading = frame.get(social_c.CONTACT(person))
    who = f"« {name} »" if name else phrase("identity.last.someone")
    if kind == Kind.REPLY:
        out = []
        if reading.previous:
            out.append(phrase("identity.last.before_reply", who=who, when=calendar_words(reading.previous, frame)))
        if reading.previous < reading.last_out < reading.since:
            wrote = calendar_words(reading.last_out, frame)
            # lu après qu'elle l'a écrit : c'est bien ce message-là (son application le dit)
            seen = frame.get(attention_c.AWAITING(person)).seen_at
            out.append(phrase("identity.last.wrote_since_read", when=wrote, who=who,
                              seen=calendar_words(seen, frame)) if seen >= reading.last_out
                       else phrase("identity.last.wrote_since", when=wrote))
        return out
    out = []
    if reading.last_in:
        out.append(phrase("identity.last.wrote_last", who=f"{who[:1].upper()}{who[1:]}",
                          when=calendar_words(reading.last_in, frame)))
    mine = frame.get(attention_c.AWAITING(person))
    if mine.initiatives:
        wrote = calendar_words(mine.last_initiative_at, frame)
        if mine.seen_at:
            out.append(phrase("identity.last.you_wrote_seen", when=wrote, who=who,
                              seen=calendar_words(mine.seen_at, frame)))
        elif mine.unseen:
            out.append(phrase("identity.last.you_wrote_unseen", when=wrote, who=who))
        else:
            out.append(phrase("identity.last.you_wrote", when=wrote))
    elif mine.unanswered and mine.asked and not mine.owed and mine.last_out > mine.last_in:
        out.append(phrase("identity.last.question_waits", when=calendar_words(mine.last_out, frame)))
    return out


@IDENTITY.section("who", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, trim_rank=90, floor_chars=400,
                  title=phrase("identity.who.title"), reads=[c.IDENTITY, c.PERSON, social_c.CLOSENESS, social_c.CONTACT,
                                                    attention_c.AWAITING, self_c.PERSONA])
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
        lines.append(owner_line(frame))
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
    pas « presque pas de passé commun » : seulement depuis quand on se parle ici. ``first_seen`` à 0 :
    jamais encore vue (un compte créé à l'avance) — pas de passé commun."""
    days = (frame.local().date() - frame.local(first_seen).date()).days if first_seen else 0
    if closeness in _KNOWN:
        if days <= 0:
            return phrase("identity.known.friend_first_day")
        if days == 1:
            return phrase("identity.known.friend_since_yesterday")
        if days < 14:
            return phrase("identity.known.friend_days", days=days)
    if days <= 0:
        return phrase("identity.known.today")
    if days == 1:
        return phrase("identity.known.yesterday")
    if days < 14:
        return phrase("identity.known.days", days=days)
    if days < 60:
        return phrase("identity.known.weeks", weeks=days // 7)
    return phrase("identity.known.months", months=days // 30)


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
