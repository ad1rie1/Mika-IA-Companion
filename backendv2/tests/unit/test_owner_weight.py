"""Sa propriétaire compte plus que tout autre (lot D du chantier « émotions, conscience, mémoire ») — une tendance,
jamais une obligation.

Elle vit à travers ses relations, plus fort avec sa propriétaire ; pourtant aucune faculté de l'émotion ne la
distinguait d'une proche, et l'envie de compagnie se partageait à égalité entre tous les présents, une inconnue
comprise. Un réglage (``social.owner_weight``) exposé en fait (``social.WEIGHT``) : son silence lui manque plus tôt,
sa compagnie la comble davantage, ce qu'elle ressent et ce qu'elle vit la touchent davantage.
"""

from __future__ import annotations

from types import SimpleNamespace as NS

from mika.contracts import attention as attention_c
from mika.contracts import memory as memory_c
from mika.contracts import needs as needs_c
from mika.contracts import social as social_c
from mika.faculties.attention.faculty import _met_felt
from mika.faculties.memory.faculty import _moment_resolved_felt
from mika.faculties.needs import NeedsParams, _toward
from mika.faculties.others.faculty import OthersParams, OthersState, _contagion
from mika.faculties.social.faculty import Contact, SocialParams, SocialState, _missed, _weight
from mika.kernel.arbitration import RowView
from mika.kernel.state import FrozenDict
from mika.vocab import causes

OWNER, FRIEND, STRANGER = "user_1", "user_2", "user_9"


def facts(over=None):
    table = {("identity.is_owner", OWNER): True, ("identity.is_owner", FRIEND): False,
             ("identity.is_owner", STRANGER): False,
             ("social.weight", OWNER): 1.3, ("social.weight", FRIEND): 1.0, ("social.weight", STRANGER): 1.0,
             ("social.closeness", OWNER): social_c.CLOSE, ("social.closeness", FRIEND): social_c.CLOSE,
             ("social.closeness", STRANGER): social_c.STRANGER, **(over or {})}

    def get(key):
        arg = getattr(key, "arg", None)
        if key.name == "identity.person":
            return arg
        if key.name == "affect.hostility":
            return 0.0
        return table[(key.name, arg)]

    return get


def test_her_owner_weighs_more_than_a_close_friend():
    cx = NS(params=SocialParams(), facts=NS(get=facts()))
    assert _weight(None, cx, OWNER) == SocialParams().owner_weight > 1.0
    assert _weight(None, cx, FRIEND) == 1.0


def test_what_her_owner_feels_touches_her_more():
    s, p = OthersState(), OthersParams()
    owner, _e = _contagion(s, OWNER, (("sad", 0.8),), -0.56, social_c.CLOSE, 0, p, 1.3)
    friend, _e = _contagion(s, FRIEND, (("sad", 0.8),), -0.56, social_c.CLOSE, 0, p, 1.0)
    assert owner > friend > 0


def test_her_owners_return_and_moments_move_her_more():
    def met(person):
        cx = NS(facts=NS(get=facts()))
        e = NS(data=attention_c.ExpectationMet(kind=attention_c.RETURN, person=person, since=0, absence=4.0))
        return _met_felt(e, cx)[0].intensity

    assert met(OWNER) > met(FRIEND)

    def resolved(person):
        cx = NS(params=None, facts=NS(get=facts()))
        e = NS(data=memory_c.Resolved(event=1, outcome="cancelled", importance=0.5, valence=0.3, about=(person,)))
        return next(a.intensity for a in _moment_resolved_felt(e, cx) if a.reason == causes.LET_DOWN)

    assert resolved(OWNER) > resolved(FRIEND)


def test_the_wish_for_company_leans_toward_who_would_fill_it():
    """Envie de compagnie : entre ceux qui sont là, nettement vers sa propriétaire, à peine vers une inconnue — plus
    à égalité ; mais seule avec une inconnue silencieuse, elle finit quand même par lui parler (une tendance, jamais
    un interdit : la journée vide, S06)."""
    p = NeedsParams()
    needs = needs_c.NeedsReading(social=1.0, expression=0.0, curiosity=0.0, idle_since=0)

    def shift(target, present, reasons=(needs_c.NEED_SOCIAL,)):
        get = facts({("needs.needs", None): needs, ("presence.present", None): present})
        frame = NS(get=get, env=NS(params_of=lambda *_: p), root=None)
        return _toward(None, frame, RowView("INITIATIVE", target, 5.0, reasons)).shift

    both = (OWNER, STRANGER)
    assert shift(OWNER, both) > 0 > shift(STRANGER, both)
    assert shift(FRIEND, (FRIEND, STRANGER)) == 0  # une proche : ni plus, ni moins
    assert shift(STRANGER, (FRIEND, STRANGER)) < 0
    assert shift(STRANGER, (STRANGER,)) == 0  # seule avec elle : rien ne la détourne d'elle
    assert shift(OWNER, (OWNER,)) > 0  # sa propriétaire l'attire un peu plus, même seule
    assert shift(OWNER, both, (social_c.RECONTACT,)) == 0


def test_her_owners_silence_is_missed_sooner():
    """Le même silence (1,2 fois leur rythme) : sa propriétaire lui manque déjà, une proche pas encore (le seuil,
    1,5 par défaut, divisé par ce qu'elle compte)."""
    state = SocialState(contacts=FrozenDict({OWNER: Contact(last_in=1), FRIEND: Contact(last_in=1)}),
                        declared=FrozenDict({OWNER: social_c.CLOSE, FRIEND: social_c.CLOSE}))
    contact = NS(silence_ratio=1.2)
    table = facts({("social.circle", None): (OWNER, FRIEND), ("social.contact", OWNER): contact,
                   ("social.contact", FRIEND): contact, ("identity.handles", OWNER): (),
                   ("identity.handles", FRIEND): ()})
    cx = NS(params=SocialParams(), facts=NS(get=table))
    assert [person for person, _ratio in _missed(state, cx)] == [OWNER]
