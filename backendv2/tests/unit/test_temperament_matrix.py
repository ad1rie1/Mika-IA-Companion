"""Sa matrice de personnalité (ADR 0100) : des curseurs en familles, des profils préremplis, ce qui se dit au modèle.

- chaque curseur pilote quelque chose — un paramètre d'une faculté, ou ce qui se dit au modèle ;
- au milieu, chaque dérivation redonne exactement la valeur d'avant la matrice : une vie existante ne change pas ;
- les profils posent tous les curseurs de caractère (jamais tout à fait 0 ni 1), gardent le chronotype, se
  reconnaissent ; Mika est livrée « Réfléchie » ;
- son tempérament se dit au modèle en tendances, jamais en chiffres ; au milieu partout, rien ;
- une cible par famille : la rancune dure, les scrupules font naître le remords, l'anxiété fait revenir les pensées,
  l'empathie inquiète, l'impulsivité fait déborder et reprendre la parole plus tôt, le biais négatif fait peser le
  mauvais, l'expressivité se voit, cloisonnée elle reste de marbre devant ce que les autres lui font vivre.
"""

from __future__ import annotations

import re
from dataclasses import replace
from types import SimpleNamespace as NS

import pytest

from mika.app.composition import faculties
from mika.contracts import attention as attention_c
from mika.contracts import self_ as self_c
from mika.contracts import social as social_c
from mika.faculties.affect import AffectState, _feel, face_reading
from mika.faculties.affect import physics as ph
from mika.faculties.affect.params import derive as affect_derive
from mika.faculties.agency import derive as agency_derive
from mika.faculties.attention.faculty import _met_felt, _missed_felt
from mika.faculties.attention.faculty import derive as attention_derive
from mika.faculties.body import derive as body_derive
from mika.faculties.needs import _reunited_felt
from mika.faculties.needs import derive as needs_derive
from mika.faculties.others.faculty import derive as others_derive
from mika.faculties.self.character import told
from mika.faculties.self.esteem import esteem
from mika.faculties.self.faculty import SelfState
from mika.faculties.self.knobs import derive as self_derive
from mika.faculties.social.faculty import derive as social_derive
from mika.faculties.social.reciprocity import _one_sided_felt
from mika.kernel import forms
from mika.kernel.clock import DAY, MINUTE
from mika.runtime import params
from mika.vocab import affect as A
from mika.vocab import circadian
from mika.vocab import temperament as T
from mika.vocab.affect import Appraisal, Declared, Emotion
from mika.vocab.phrasebook import phrase
from tests.fixtures.mika import PARIS, SHIPPED, at_paris

T0 = at_paris(2026, 9, 28, 15, 0)
#: ce qui ne se calcule pas, mais se dit au modèle (rien ne lui montre encore les autres relations de ses proches,
#: et le sens de son masque est une façon de parler)
TOLD_ONLY = frozenset({"jealousy", "mask"})
#: les curseurs nés avec la matrice (les huit d'avant ont gardé leur sens)
NEW = frozenset(T.SLIDERS) - {"reactivity", "resilience", "contagion", "optimism", "sociability", "curiosity",
                              "perseverance", "chronotype"}
#: les archétypes que la matrice doit savoir produire (y compris les extrêmes)
ARCHETYPES = ("reflechie", "calme", "anxieuse", "nerveuse", "solaire", "rancuniere", "de_marbre", "colerique",
              "depressive", "tsundere", "kuudere", "dandere", "yandere", "psychopathe", "sociopathe", "narcissique",
              "dependante")


def _t(**values: float) -> T.Temperament:
    return T.Temperament(**values)


def _cw() -> ph.Clockwork:
    return ph.Clockwork(PARIS, circadian.DEFAULT)


# ── la matrice ────────────────────────────────────────────────────────────


def test_every_slider_drives_something_or_is_told():
    """Un curseur sans effet serait un mensonge de la console : il pilote un paramètre quelque part, ou il se dit au
    modèle (et alors il a ses deux phrases)."""
    moved = params.influences([f for f in faculties() if f.params is not None], T.Temperament())
    idle = {s for s, where in moved.items() if not where}
    assert idle == set(TOLD_ONLY), f"curseurs sans effet : {sorted(idle - TOLD_ONLY)}"
    for slider in T.PERSONALITY:
        assert phrase(f"self.temperament.trait.{slider}.low") and phrase(f"self.temperament.trait.{slider}.high")


def test_at_the_middle_every_new_slider_gives_back_the_values_from_before():
    """Au milieu, ce que pilote un curseur né avec la matrice vaut exactement le défaut d'avant elle : un journal
    existant se rejoue tel quel, et Mika ne change pas tant qu'on n'y touche pas."""
    for fac in faculties():
        if fac.derive is None or fac.params is None:
            continue
        moved = {path for slider, where in params.influence(fac, T.Temperament()).items() if slider in NEW
                 for path, _lo, _hi in where}
        middle, before = forms.flatten(fac.derive(T.Temperament(), None)), forms.flatten(fac.params())
        changed = {path: (before[path], middle[path]) for path in moved if middle[path] != before[path]}
        assert changed == {}, f"{fac.name} : {changed}"


# ── les profils ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("key", list(T.PROFILES))
def test_a_profile_sets_every_trait_within_bounds_and_keeps_the_rhythm(key):
    p = T.PROFILES[key]
    assert set(p.values) <= set(T.PERSONALITY)
    assert all(1 <= v <= 9 for v in p.values.values()), "jamais tout à fait 0 ni 10"
    assert p.reaction in dict(T.REACTIONS) and p.defense in dict(T.DEFENSES)
    owl = _t(chronotype=0.8, introspection=0.1)
    applied = T.apply_profile(owl, key)
    assert applied.chronotype == 0.8  # son rythme n'est pas son caractère
    assert all(T.LOWEST <= getattr(applied, s) <= T.HIGHEST for s in T.PERSONALITY)
    assert T.profile_of(applied) == key
    assert T.profile_of(applied.model_copy(update={"grudge": 0.55 if applied.grudge != 0.55 else 0.45})) == ""


def test_every_archetype_exists_and_they_differ():
    assert set(ARCHETYPES) <= set(T.PROFILES)
    applied = [T.apply_profile(T.Temperament(), k) for k in T.PROFILES]
    assert len({a.model_dump_json() for a in applied}) == len(applied)


def test_mika_ships_as_reflechie():
    assert T.DEFAULT_PROFILE == "reflechie" and T.profile_of(SHIPPED.temperament) == "reflechie"


# ── ce qui se dit au modèle ───────────────────────────────────────────────


def test_her_temperament_is_told_in_words_never_numbers():
    assert told(T.Temperament()) == []  # au milieu partout : rien à dire
    tsundere = told(T.apply_profile(T.Temperament(), "tsundere"))
    marked = phrase("self.temperament.marked")
    assert phrase("self.temperament.trait.mask.high") + " " + marked in tsundere  # 9 sur 9 : très marqué
    assert phrase("self.temperament.trait.defense.attack") in tsundere
    assert phrase("self.temperament.trait.empathy.high") in tsundere  # 7 sur 9 : net, sans plus
    reflechie = told(SHIPPED.temperament)
    assert phrase("self.temperament.trait.introspection.high") + " " + marked in reflechie
    assert phrase("self.temperament.trait.impulsivity.low") in reflechie
    for key in T.PROFILES:
        assert not any(re.search(r"\d", line) for line in told(T.apply_profile(T.Temperament(), key)))


def test_the_section_says_it_with_its_tail_and_nothing_at_the_middle():
    from mika.faculties.self.character import _temperament  # noqa: PLC0415 — la section, appelée telle quelle

    neutral = SelfState(persona=self_c.PersonaDoc(name="Mika"))
    assert _temperament(neutral, None, {}) is None
    shy = SelfState(persona=self_c.PersonaDoc(name="Mika", temperament=T.apply_profile(T.Temperament(), "dandere")))
    text = _temperament(shy, None, {})
    assert phrase("self.temperament.trait.shyness.high") in text and text.endswith(phrase("self.temperament.tail"))
    assert text.startswith(phrase("self.temperament.lead"))  # pour elle seule : elle ne le récite pas (banc)


def test_a_note_says_what_sets_a_trait_off_even_at_the_middle():
    """Une précision par trait (« tu t'énerves quand on t'appelle poulet ») : dite avec le trait, ou seule quand le
    trait est au milieu ; un trait inconnu ou un roman sont refusés ; un profil ne l'efface pas."""
    t = T.Temperament(reactivity=0.8, notes={"reactivity": "tu t'énerves quand on t'appelle « poulet ».",
                                             "grudge": "  tu pardonnes tout à ceux qui te font rire  "})
    lines = told(t)
    assert lines[0] == phrase("self.temperament.trait.reactivity.high") + " " + phrase(
        "self.temperament.precisely", note="tu t'énerves quand on t'appelle « poulet »")
    assert phrase("self.temperament.particular", note="tu pardonnes tout à ceux qui te font rire") in lines
    assert T.apply_profile(t, "calme").notes == t.notes
    assert {k for k, _ in T.NOTE_KEYS} == {*T.PERSONALITY, "reaction", "defense"}
    with pytest.raises(ValueError):
        T.Temperament(notes={"inconnu": "x"})
    with pytest.raises(ValueError):
        T.Temperament(notes={"grudge": "x" * (T.NOTE_MAX + 1)})
    assert T.Temperament(notes={"grudge": "   "}).notes == {}


# ── une cible par famille ─────────────────────────────────────────────────


def _hostility_after(t: T.Temperament, days: float) -> float:
    p = affect_derive(t)
    ref = ph.reference(p, _cw())
    st = ph.new_stance(T0, p, _cw())
    for i in range(6):
        st = ph.fold(st, Declared(Emotion.ANGRY, 0.8), T0 + i * MINUTE, 1, ref, p)
    anchor = ph.heal(st.anchor, st.hostile, round(days * DAY), p)
    return ph.hostility_of(anchor, st.bond, 0, T0 + round(days * DAY), ref, p)


def test_a_grudge_lasts_and_apologies_weigh_less():
    """Six colères : une rancunière en veut encore la semaine d'après, une âme qui pardonne vite, à peine."""
    held, forgiving = _t(grudge=0.9), _t(grudge=0.1)
    assert _hostility_after(held, 7) > _hostility_after(T.Temperament(), 7) > _hostility_after(forgiving, 7)
    assert affect_derive(held).apology_heal < affect_derive(forgiving).apology_heal


def test_scruples_make_remorse_born_of_a_milder_harshness():
    """Une réplique fâchée à 0,6 : la scrupuleuse s'en veut, la sans-scrupules non."""
    assert attention_derive(_t(scruples=0.9)).remorse_from < 0.6 < attention_derive(_t(scruples=0.1)).remorse_from
    assert attention_derive(_t(scruples=0.9)).broken_promise_felt > attention_derive(_t(scruples=0.1)).broken_promise_felt


def test_anxiety_brings_thoughts_back_more_often_and_longer():
    anxious, serene = attention_derive(_t(anxiety=0.9)), attention_derive(_t(anxiety=0.1))
    assert anxious.dwell_every_us < serene.dwell_every_us
    assert anxious.dwell_factor > serene.dwell_factor and anxious.half_life_us > serene.half_life_us


def test_empathy_worries_sooner_and_more():
    warm, cold = others_derive(_t(empathy=0.9)), others_derive(_t(empathy=0.1))
    assert warm.worry_intensity > cold.worry_intensity
    assert warm.declared_concern_from < cold.declared_concern_from and warm.concern_drop < cold.concern_drop


def test_impulsivity_overflows_sooner_and_speaks_up_again_sooner():
    rash, patient = _t(impulsivity=0.9), _t(impulsivity=0.1)
    assert affect_derive(rash).overflow_floor < affect_derive(patient).overflow_floor
    assert agency_derive(rash).refractory_us < agency_derive(patient).refractory_us


def _moved(t: T.Temperament, emotion: Emotion) -> float:
    p = affect_derive(t)
    cx = NS(params=p, tz=PARIS, facts=NS(get=lambda key: circadian.DEFAULT), now=T0)
    s = _feel(AffectState(), (Appraisal(emotion, 0.4, reason="dream"),), NS(at=T0), cx)
    m = ph.advance_mood(s.mood, T0, p, _cw())
    return A.norm(m.gap)


def test_a_negativity_bias_makes_the_bad_weigh_more_than_the_good():
    """La même peine pèse plus sur une âme au biais négatif, la même joie porte plus une âme au biais positif (la
    tristesse et la joie ne sont pas à la même distance de son repos : on compare une émotion à elle-même)."""
    gloomy, middle, bright = _t(negativity=0.9), T.Temperament(), _t(negativity=0.1)
    assert _moved(gloomy, Emotion.SAD) > _moved(middle, Emotion.SAD) > _moved(bright, Emotion.SAD)
    assert _moved(gloomy, Emotion.HAPPY) < _moved(middle, Emotion.HAPPY) < _moved(bright, Emotion.HAPPY)


def test_expressiveness_shows_on_her_face():
    def shown(t: T.Temperament) -> float:
        p = affect_derive(t)
        st = replace(ph.new_stance(T0, p, _cw()), declared=Declared(Emotion.SAD, 0.6).encode(), declared_at=T0)
        return face_reading(AffectState(stances={"user_2": st}), "user_2", T0, p, _cw()).intensity

    assert shown(T.apply_profile(T.Temperament(), "kuudere")) < shown(T.Temperament()) == 0.6 \
        < shown(T.apply_profile(T.Temperament(), "solaire"))


def test_walled_off_she_stays_unmoved_by_what_others_make_her_live():
    """Cloisonnée (contagion au plus bas) : un retour, un message sans réponse, des retrouvailles, toujours elle qui
    écrit — elle le sait, ça ne l'ébranle pas ; au milieu, si (réponse 14 du questionnaire)."""
    lived = [*_met_felt(NS(data=attention_c.ExpectationMet(kind=attention_c.RETURN, person="user_2", since=0)),
                        NS(params=None, facts=NS(get=lambda key: 1.0 if key.name == social_c.WEIGHT.name
                                                 else social_c.FRIEND))),
             *_missed_felt(NS(data=attention_c.ExpectationMissed(kind=attention_c.REPLY, person="user_2", since=0)),
                           None),
             _reunited_felt(NS(data=NS(after="lonely", intensity=0.3)), None),
             *_one_sided_felt(NS(data=NS(about=("user_2",))), None)]
    assert all(a.relational for a in lived)
    for open_, expected in ((0.5, True), (0.0, False)):
        p = affect_derive(_t(contagion=open_))
        cx = NS(params=p, tz=PARIS, facts=NS(get=lambda key: circadian.DEFAULT), now=T0)
        s = _feel(AffectState(), tuple(a for a in lived if a.toward is None), NS(at=T0), cx)
        assert (s.mood is not None and A.norm(s.mood.gap) > 1e-6) is expected


def test_the_rest_of_her_self_regard_and_what_a_compliment_brings():
    sure, doubting = self_derive(_t(self_regard=0.9)), self_derive(_t(self_regard=0.1))
    assert esteem(SelfState(), T0, sure) > 0.5 > esteem(SelfState(), T0, doubting)
    assert self_derive(_t(admiration=0.9)).thanked_knock > self_derive(_t(admiration=0.1)).thanked_knock
    assert self_derive(_t(fragility=0.9)).insulted_knock < self_derive(_t(fragility=0.1)).insulted_knock


def test_her_owner_always_counts_more_than_a_close_friend():
    assert 1.0 <= social_derive(_t(devotion=0.0)).owner_weight < social_derive(T.Temperament()).owner_weight == 1.3 \
        < social_derive(_t(devotion=1.0)).owner_weight


def test_shyness_energy_attachment_and_stability():
    assert needs_derive(_t(shyness=0.9)).stranger_company < needs_derive(_t(shyness=0.1)).stranger_company
    assert body_derive(_t(energy=0.9)).tired_below < body_derive(_t(energy=0.1)).tired_below
    assert affect_derive(_t(attachment=0.9)).bond_step > affect_derive(_t(attachment=0.1)).bond_step
    assert affect_derive(_t(stability=0.1)).anchor_alpha > affect_derive(_t(stability=0.9)).anchor_alpha
