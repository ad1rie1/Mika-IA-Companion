"""Ce qu'une personne lui fait vivre la touche envers elle (lot E du chantier « émotions, conscience, mémoire »).

Avant : s'apercevoir que c'est toujours elle qui écrit, qu'un lien se refroidit, qu'une réponse ne vient pas, qu'elle
n'a pas tenu sa promesse, s'inquiéter pour une amie — tout cela ne touchait que son humeur générale ; sa posture envers
la personne restait au repos, et elle l'accueillait comme si de rien n'était. Et une personne parlée sous une adresse
puis reliée à son compte repartait d'une posture neuve : ce que leur relation avait installé (une rancune, de la
tendresse, des excuses) restait sous l'ancienne adresse, que plus rien ne lisait.

- les évaluations relationnelles visent aussi la personne (``toward``) ; la contagion, non : une amie furieuse contre
  son patron ne la met pas en colère contre elle ;
- une posture se lit toutes adresses réunies (``identity.HANDLES``), comme ``others.model_of`` ; des excuses
  pardonnent ce qu'elle gardait sous chacune.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace as NS

from mika.contracts import attention as attention_c
from mika.contracts import identity as identity_c
from mika.contracts import self_ as self_c
from mika.contracts import social as social_c
from mika.faculties.affect import AffectState, _apologized, _feel, hostility, regard, stance_reading
from mika.faculties.affect import physics as ph
from mika.faculties.affect.params import DEFAULT
from mika.faculties.attention.faculty import _missed_felt
from mika.faculties.others.faculty import OthersParams, _read_felt
from mika.faculties.social.bonds import _bond_felt
from mika.faculties.social.reciprocity import _one_sided_felt
from mika.kernel.clock import HOUR, MINUTE
from mika.kernel.state import FrozenDict
from mika.vocab import affect as A
from mika.vocab import circadian
from mika.vocab.affect import Appraisal, Emotion
from tests.fixtures.mika import PARIS, at_paris

T0 = at_paris(2026, 9, 28, 15, 0)


def _cw() -> ph.Clockwork:
    return ph.Clockwork(PARIS, circadian.DEFAULT)


def _cx(handles=(), closeness=social_c.FRIEND):
    def get(key):
        if key.name == identity_c.HANDLES.name:
            return handles
        if key.name == social_c.CLOSENESS.name:
            return closeness
        if key.name == "body.rhythm":
            return circadian.DEFAULT
        raise KeyError(key.name)

    return NS(params=DEFAULT, tz=PARIS, facts=NS(get=get), now=T0)


def _toward(appraisals) -> dict[str, tuple[Emotion, float]]:
    out = appraisals if isinstance(appraisals, list) else [appraisals]
    return {a.toward: (a.emotion, a.intensity) for a in out if a is not None and a.toward}


def test_what_a_person_makes_her_live_touches_her_toward_them():
    one_sided = _one_sided_felt(NS(data=NS(about=("user_2",))), None)
    assert _toward(one_sided)["user_2"][0] is Emotion.SAD
    cooling = _bond_felt(NS(data=NS(person="user_2", before=social_c.FRIEND, after=social_c.ACQUAINTANCE)), None)
    warming = _bond_felt(NS(data=NS(person="user_2", before=social_c.FRIEND, after=social_c.CLOSE)), None)
    assert _toward(cooling)["user_2"][0] is Emotion.MELANCHOLIC and _toward(warming)["user_2"][0] is Emotion.HAPPY
    unanswered = _missed_felt(NS(data=attention_c.ExpectationMissed(kind=attention_c.REPLY, person="user_2",
                                                                     since=0)), None)
    broken = _missed_felt(NS(data=attention_c.ExpectationMissed(kind=attention_c.PROMISE, person="user_2",
                                                                 since=0)), None)
    assert _toward(unanswered)["user_2"][0] is Emotion.SAD
    assert _toward(broken)["user_2"][0] is Emotion.EMBARRASSED
    # pour elle aussi : son humeur générale, comme avant
    assert all(any(a.toward is None for a in felt) for felt in (one_sided, cooling, unanswered, broken))


def test_worrying_for_a_friend_is_toward_her_but_catching_her_anger_is_not():
    p = OthersParams()
    worried = _read_felt(NS(data=NS(surprise=0.0, concern=True, concern_share=1.0, contagion=0.0,
                                    contagion_emotion="", person="user_2")), NS(params=p))
    assert _toward(worried) == {"user_2": (Emotion.ANXIOUS, p.worry_intensity)}
    # au cran de leur lien (ADR 0150) : une connaissance l'inquiète à moitié
    known = _read_felt(NS(data=NS(surprise=0.0, concern=True, concern_share=0.5, contagion=0.0,
                                  contagion_emotion="", person="user_2")), NS(params=p))
    assert _toward(known) == {"user_2": (Emotion.ANXIOUS, p.worry_intensity * 0.5)}
    angry = _read_felt(NS(data=NS(surprise=0.0, concern=False, contagion=0.2, contagion_emotion="angry",
                                  person="user_2")), NS(params=p))
    assert [a.emotion for a in angry] == [Emotion.ANGRY] and not _toward(angry)


def test_her_stance_toward_them_moves_with_it():
    """Une évaluation tournée vers la personne déplace sa posture envers elle — et seulement elle."""
    s = _feel(AffectState(), (Appraisal(Emotion.SAD, 0.3, toward="user_2", reason="sans réponse"),),
              NS(at=T0), _cx())
    r = stance_reading(s, "user_2", T0 + MINUTE, DEFAULT, _cw())
    assert not r.at_rest and r.felt in (Emotion.SAD, Emotion.LONELY, Emotion.MELANCHOLIC)
    assert stance_reading(s, "user_3", T0 + MINUTE, DEFAULT, _cw()).at_rest


def _grudge(at: int) -> ph.Stance:
    """Ce que des semaines de mots blessants ont installé sous une adresse."""
    st = ph.new_stance(at, DEFAULT, _cw())
    return replace(st, anchor=A.scale(A.sub(A.ANCHORS[Emotion.ANGRY], ph.reference(DEFAULT, _cw())), 0.5),
                   hostile=6, days=12, last_day=10, bond=0.1)


def _warm(at: int) -> ph.Stance:
    st = ph.new_stance(at, DEFAULT, _cw())
    return replace(st, anchor=A.scale(A.sub(A.ANCHORS[Emotion.LOVE], ph.reference(DEFAULT, _cw())), 0.4),
                   days=30, last_day=20, bond=0.6)


def test_a_linked_address_keeps_what_their_relation_installed():
    """Parlée d'abord sous une adresse (``ext_7``), puis reliée à son compte (``user_2``) : sa rancune, sa
    tendresse ne repartent pas de zéro — une posture se lit toutes adresses réunies."""
    now = T0 + HOUR
    s = AffectState(stances=FrozenDict({"ext_7": _grudge(T0), "user_2": ph.new_stance(T0, DEFAULT, _cw())}))
    alone = hostility(s, "user_2", now, DEFAULT, _cw())
    joined = hostility(s, "user_2", now, DEFAULT, _cw(), ("ext_7", "user_2"))
    assert alone == 0.0 and joined > 0.2
    assert regard(s, "user_2", now, DEFAULT, _cw(), ("ext_7",)) < 0.0
    assert stance_reading(s, "user_2", now, DEFAULT, _cw(), ("ext_7",)).anchor is not None
    # une adresse d'un jour pèse peu à côté de mois de conversations
    t = AffectState(stances=FrozenDict({"ext_7": replace(_grudge(T0), days=1, hostile=1, bond=0.0),
                                        "user_2": replace(_warm(T0), bond=0.0)}))
    assert regard(t, "user_2", now, DEFAULT, _cw(), ("ext_7",)) > 0.0
    u = AffectState(stances=FrozenDict({"ext_7": replace(_grudge(T0), days=30, bond=0.0),
                                        "user_2": replace(_warm(T0), days=1, bond=0.0)}))
    assert regard(u, "user_2", now, DEFAULT, _cw(), ("ext_7",)) < 0.0


def test_apologies_heal_what_she_kept_under_each_address():
    s = AffectState(stances=FrozenDict({"ext_7": _grudge(T0)}))
    before = hostility(s, "user_2", T0 + MINUTE, DEFAULT, _cw(), ("ext_7",))
    e = NS(at=T0 + MINUTE, data=NS(kind=self_c.APOLOGIZED, person="user_2"))
    healed = _apologized(s, e, _cx(handles=("ext_7",), closeness=social_c.FRIEND))
    assert hostility(healed, "user_2", T0 + MINUTE, DEFAULT, _cw(), ("ext_7",)) < before
