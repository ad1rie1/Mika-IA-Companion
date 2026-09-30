"""Ce que ``identity`` met dans le prompt, et l'audience d'un épisode."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mika.contracts import identity as c
from mika.faculties.identity.faculty import IDENTITY, IdentityState, view_of
from mika.kernel.faculty import Zone
from mika.kernel.frame import CLOSED as CLOSED_AUDIENCE
from mika.kernel.frame import Audience, Frame
from mika.kernel.prompt import SectionBody
from mika.vocab import privacy
from mika.vocab.episodes import CONVERSATIONAL, Kind, is_work_target
from mika.vocab.privacy import ChannelTrust

CHANNEL_FR = {"web": "sur l'application", "telegram": "par Telegram"}


def describe(view: c.IdentityView, *, public: bool, names: Mapping[str, str] | None = None) -> list[str]:
    """Des phrases, jamais un pourcentage (sinon le modèle finit par réciter
    des scores à la personne)."""
    who = f"« {view.name} »" if view.name else ""
    where = CHANNEL_FR.get(view.channel, "")
    lines: list[str] = []
    if view.authenticated:
        lines.append(f"Tu sais avec certitude que tu parles à {who or 'cette personne'} : "
                     "la personne s'est connectée avec son compte.")
    elif view.bound:
        level = privacy.certainty_name(view.certainty)
        if level == "corroborated":
            lines.append(f"Tu penses vraiment que c'est {who} : ce qui a été dit recoupe ce que tu sais d'elle "
                         f"ou de lui (elle ou il t'écrit {where}).")
        else:
            lines.append(f"Tu reconnais {who} : ce contact ({where}) et la personne que tu connais ne font qu'un.")
    elif view.trust is ChannelTrust.ACCOUNT:
        lines.append(f"C'est {who}, qui t'écrit {where}." if who else
                     f"Quelqu'un t'écrit {where} ; tu ne connais pas encore son prénom.")
    else:
        lines.append("Tu ne sais pas qui est cette personne : rien ne prouve qui écrit. Reste accueillante mais "
                     "ne suppose rien d'elle, et ne lui raconte rien de personnel sur qui que ce soit.")
    if view.claim:
        claimed = f"« {view.claim} »"
        if view.claim_target is None:
            lines.append(f"Elle ou il dit être {claimed}, mais tu connais plusieurs personnes de ce nom : "
                         "tu ne sais pas de qui il s'agit.")
        else:
            lines.append(f"Elle ou il affirme être {claimed}, que tu connais, mais rien ne le confirme encore. "
                         f"Joue le jeu poliment en gardant une réserve : ne raconte rien de ce que {claimed} "
                         "t'a confié tant que tu n'es pas sûre. Si tu doutes vraiment, dis-le, ou utilise "
                         "identity_doubt.")
    if public:
        lines.append("Vous êtes dans un groupe : d'autres lisent. Rien de personnel sur personne — ni sur les "
                     "autres, ni sur elle ou lui. Si on te demande quelque chose de personnel sur quelqu'un, ne fais "
                     "pas semblant de ne pas le connaître : dis simplement que ce n'est pas à toi d'en parler.")
    return lines


@IDENTITY.section("who", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, trim_rank=90, floor_chars=400,
                  title="QUI TU AS EN FACE", reads=[c.IDENTITY])
def _who(s: IdentityState, frame: Frame, enrich: Any) -> SectionBody | None:
    aud = frame.audience
    ep = frame.episode
    if aud is None or ep is None or not ep.target:
        return None
    view = view_of(s, ep.target, frame.now)
    lines = describe(view, public=aud.public)
    if view.known:
        lines.append(acquaintance(view.first_seen, frame))
    return SectionBody("\n".join(lines))


def acquaintance(first_seen: int, frame: Frame) -> str:
    """Depuis quand elle connaît cette personne — un fait, pour qu'elle ne
    s'invente pas un passé commun (« on se connaît depuis longtemps »)."""
    days = (frame.local().date() - frame.local(first_seen).date()).days
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
    """L'audience d'un épisode, résolue une fois au bord. Toute panne → fermée."""
    target = getattr(req, "target", None)
    kind = getattr(req, "kind", "")
    if not target or is_work_target(target):
        if kind in (Kind.REPLY, Kind.INITIATIVE):
            return CLOSED_AUDIENCE
        # un épisode sans destinataire (pas de travail, tâche, murmure, journal) : personne n'écoute
        d = privacy.EVERYTHING
        return Audience(persons=(), channel="internal", public=False, level=int(d.level),
                        witness_level=int(d.witness_level), private_ok=True, trust=ChannelTrust.INTERNAL.value,
                        owner=True)
    s: IdentityState = frame.state("identity")
    room = getattr(req, "room", None)
    h = s.handles.get(target)
    channel = getattr(req, "channel", None) or (h.channel if h else "web")
    view = view_of(s, target, frame.now)
    public = room is not None or view.trust is ChannelTrust.PUBLIC
    d = frame.get(c.DISCLOSURE((target, channel, room is not None)))
    return Audience(
        persons=(target,), channel=channel, room=room, public=public, level=int(d.level),
        witness_level=int(d.witness_level), private_ok=d.own_file, trust=view.trust.value,
        certainty=view.certainty, name=view.name,
        owner=bool(frame.get(c.IS_OWNER(frame.get(c.PERSON(target))))),
    )


