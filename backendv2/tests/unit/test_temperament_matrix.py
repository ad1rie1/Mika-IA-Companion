"""Sa matrice de personnalité (ADR 0100) : des curseurs en familles, des profils préremplis, ce qui se dit au modèle.

- chaque curseur pilote un paramètre d'une faculté (et se dit au modèle) ; sa réaction et sa défense aussi ;
- au milieu, chaque dérivation redonne exactement la valeur d'avant la matrice : une vie existante ne change pas ;
- les profils posent tous les curseurs de caractère (jamais tout à fait 0 ni 1), gardent le chronotype, se
  reconnaissent ; leurs précisions vont et viennent avec eux, celles de l'opératrice restent ; Mika est livrée
  « Réfléchie » ;
- son tempérament se dit au modèle trait par trait, chacun avec sa mesure (« 90 % ») et sa phrase ;
- une cible par famille : la rancune dure, les scrupules font naître le remords, l'anxiété fait revenir les pensées,
  l'empathie inquiète, l'impulsivité fait déborder et reprendre la parole plus tôt, le biais négatif fait peser le
  mauvais, l'expressivité se voit, cloisonnée elle reste de marbre devant ce que les autres lui font vivre ; blessée,
  sa réaction pèse et la relation refroidit ; touchée, son visage se défend ; son masque règle ce que voient une
  inconnue et une proche ; sa jalousie pèse.
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


def test_every_slider_drives_something_and_is_told():
    """Un curseur sans effet serait un mensonge de la console : chacun pilote un paramètre quelque part — et se dit au
    modèle (il a ses deux phrases)."""
    moved = params.influences([f for f in faculties() if f.params is not None], T.Temperament())
    idle = {s for s, where in moved.items() if not where}
    assert idle == set(), f"curseurs sans effet : {sorted(idle)}"
    for slider in T.SLIDERS:
        assert phrase(f"self.temperament.trait.{slider}.low") and phrase(f"self.temperament.trait.{slider}.high")
        assert phrase(f"self.temperament.name.{slider}")


def test_inquisitiveness_asks_about_their_day_sooner_the_higher_without_a_cutoff():
    """L'intérêt pour les autres (ADR 0137, sans coupure depuis l'ADR 0150) : jamais tout en bas (24 h), puis de plus
    en plus tôt — passé 23 h au plus bas que permet la console, 21 h au milieu —, jusqu'à midi au plus haut."""
    hours = [social_derive(_t(inquisitiveness=x)).their_day_from_h for x in (0.0, T.LOWEST, 0.5, 0.6, 0.8, T.HIGHEST)]
    assert hours[0] == 24.0 and hours[2] == 21.0
    assert 24.0 > hours[1] > 23.0 and hours[1] > hours[2] > hours[3] > hours[4] > hours[5] == 12.0
    assert social_derive(_t(inquisitiveness=1.0)).their_day_from_h == 12.0


def test_her_reaction_and_her_defense_drive_the_affect_too():
    """Sa réaction et sa défense ne sont pas que des mots : chacune règle l'affect (et se dit au modèle)."""
    for key, _label in T.REACTIONS:
        assert affect_derive(_t(reaction=key)).reaction == key
        if key:
            assert phrase(f"self.temperament.trait.reaction.{key}")
    for key, _label in T.DEFENSES:
        assert affect_derive(_t(defense=key)).defense == key
        if key:
            assert phrase(f"self.temperament.trait.defense.{key}")
    assert set(ph.REACTION_FAMILIES) | {ph.WITHDRAWAL} == {k for k, _l in T.REACTIONS if k}
    assert set(ph.DEFENSE_FACE) == {k for k, _l in T.DEFENSES if k}


def test_at_the_middle_every_new_slider_gives_back_the_values_from_before():
    """Au milieu, ce que pilote un curseur né avec la matrice vaut exactement le défaut d'avant elle : un journal
    existant se rejoue tel quel, et Mika ne change pas tant qu'on n'y touche pas. (Les deux coupures retirées par
    l'ADR 0150 ont déplacé le défaut avec le milieu : 0,15 de jalousie, « sa journée » à 21 h.)"""
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


def _line(t: T.Temperament, slider: str) -> str:
    """La ligne d'un trait dans ce qu'on lui dit."""
    name = phrase(f"self.temperament.name.{slider}") + " : "
    return next(line for line in told(t) if line.startswith(f"- {name}"))


def test_every_trait_is_told_with_its_measure_and_its_sentence():
    """Tous ses traits, chacun avec sa mesure (« 90 % ») : le modèle dose d'après elle. La phrase du bas à 40 % ou
    moins, du haut à 60 % ou plus, « comme la plupart des gens » entre les deux ; très marqué, il le dit. Les seuls
    chiffres sont des mesures."""
    middle = phrase("self.temperament.middle")
    neutral = told(T.Temperament())
    for slider in T.SLIDERS:
        assert _line(T.Temperament(), slider).endswith(f": 50 % — {middle}")
    assert sum(1 for line in neutral if line.startswith("- ")) == len(T.SLIDERS) + 3  # humeur, réaction, défense
    reflechie = SHIPPED.temperament
    marked = phrase("self.temperament.marked")
    introspection = phrase("self.temperament.trait.introspection.high")
    assert _line(reflechie, "introspection").endswith(f": 90 % — {introspection[0].lower()}{introspection[1:]} {marked}")
    assert ": 40 % — " in _line(reflechie, "contagion") and middle not in _line(reflechie, "contagion")
    assert ": 20 % — " in _line(reflechie, "impulsivity")
    # la mesure suit le curseur : 75 % ne se lit pas comme 95 %
    assert ": 75 % — " in _line(T.Temperament(grudge=0.75), "grudge")
    assert ": 95 % — " in _line(T.Temperament(grudge=0.95), "grudge") and marked in _line(T.Temperament(grudge=0.95),
                                                                                             "grudge")
    tsundere = told(T.apply_profile(T.Temperament(), "tsundere"))
    assert "- " + phrase("self.temperament.trait.defense.attack") in tsundere
    assert "- " + phrase("self.temperament.trait.reaction.none") in neutral
    assert "- " + phrase("self.temperament.background", feeling="contente") in neutral
    for key in T.PROFILES:  # les seuls chiffres sont des mesures
        assert not any(re.search(r"\d", re.sub(r"\b\d{1,3} %", "", line))
                       for line in told(T.apply_profile(T.Temperament(), key)))


def test_what_the_writer_of_her_character_reads_and_what_her_persona_carries():
    """Le modèle qui écrit son caractère (ADR 0139) lit ses traits famille par famille, chacun avec sa mesure et sa
    phrase ; le texte qu'il écrit entre dans sa persona, complète comme compacte, partout où elle est injectée
    (répondre, murmurer, travailler, son journal, ses rêves, son récit) : elle a le même caractère partout. Aucune
    mesure, aucun bloc ne lui parvient autrement."""
    from mika.faculties.self.character import request_for  # noqa: PLC0415
    from mika.faculties.self.persona import render  # noqa: PLC0415

    shy = self_c.PersonaDoc(name="Mika", temperament=T.apply_profile(T.Temperament(), "dandere"))
    request = request_for(shy, "essai#0")
    assert request.role == "character" and "Mika" in request.system_stable
    shown = request.messages[-1].content
    for family in ("feel", "show", "act", "others", "self", "body"):
        assert phrase(f"self.temperament.family.{family}") in shown
    high = phrase("self.temperament.trait.shyness.high")
    assert f"{high[0].lower()}{high[1:]}" in shown and " : 90 % — " in shown
    written = "Tu es timide avec qui tu ne connais pas, et tu t'ouvres à mesure que tu fais confiance."
    for depth in ("full", "compact"):
        with_it, without = render(shy, depth, character=written), render(shy, depth)
        assert phrase("self.character.frame", text=written) in with_it
        assert "%" not in without and "Ton caractère" not in without and "Timidité" not in without


def test_a_note_follows_its_trait_and_never_replaces_it():
    """Une précision par trait (« tu t'énerves quand on t'appelle poulet ») : à la suite de la phrase de son trait,
    même au milieu ; un trait inconnu ou un roman sont refusés ; un profil ne l'efface pas."""
    t = T.Temperament(reactivity=0.8, notes={"reactivity": "tu t'énerves quand on t'appelle « poulet ».",
                                             "grudge": "  tu pardonnes tout à ceux qui te font rire  "})
    high = phrase("self.temperament.trait.reactivity.high")
    assert _line(t, "reactivity").endswith(
        f"{high[0].lower()}{high[1:]} " + phrase("self.temperament.precisely",
                                                 note="tu t'énerves quand on t'appelle « poulet »"))
    assert _line(t, "grudge").endswith(phrase("self.temperament.middle") + " " + phrase(
        "self.temperament.precisely", note="tu pardonnes tout à ceux qui te font rire"))
    assert T.apply_profile(t, "calme").notes == t.notes
    assert {k for k, _ in T.NOTE_KEYS} == {*T.PERSONALITY, "reaction", "defense"}
    with pytest.raises(ValueError):
        T.Temperament(notes={"inconnu": "x"})
    with pytest.raises(ValueError):
        T.Temperament(notes={"grudge": "x" * (T.NOTE_MAX + 1)})
    assert T.Temperament(notes={"grudge": "   "}).notes == {}


def test_a_profile_brings_its_notes_and_never_touches_hers():
    """Un profil pose ses précisions (ce qu'aucun curseur ne dit de l'archétype : la tsundere pique sans vouloir
    blesser) et retire celles d'un autre profil ; celles de l'opératrice restent, et sur un même trait la sienne prime.
    Elles se disent avec leur trait, comme les siennes."""
    mine = "tu pardonnes tout à ceux qui te font rire"
    tsundere = T.apply_profile(T.Temperament(notes={"grudge": mine}), "tsundere")
    assert tsundere.notes == {**T.PROFILES["tsundere"].notes, "grudge": mine}
    assert T.profile_of(tsundere) == "tsundere"
    assert _line(tsundere, "mask").endswith(phrase("self.temperament.precisely",
                                                   note=T.PROFILES["tsundere"].notes["mask"]))
    calm = T.apply_profile(tsundere, "calme")
    assert calm.notes == {"grudge": mine}  # la précision de la tsundere part avec elle
    rancuniere = T.apply_profile(calm, "rancuniere")
    assert "grudge" in T.PROFILES["rancuniere"].notes and rancuniere.notes == {"grudge": mine}
    assert T.profile_of(rancuniere) == "rancuniere"
    for p in T.PROFILES.values():  # écrites comme celles de l'opératrice : la validation les garde telles quelles
        assert T.Temperament(notes=dict(p.notes)).notes == dict(p.notes)


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
    # la rancune n'entre qu'une fois : venant de quelqu'un de moins proche, la même part de ce qu'auraient pardonné
    # les excuses d'une amie, rancunière ou non (dérivée deux fois, elle tombait au carré : 0,035 contre 0,19)
    assert affect_derive(held).apology_distant == affect_derive(forgiving).apology_distant


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
    fragile, sturdy, middle = (self_derive(_t(fragility=f)) for f in (0.9, 0.1, 0.5))
    assert fragile.disappointed_knock < sturdy.disappointed_knock < 0  # une déception pèse selon sa fragilité
    assert middle.insulted_knock < middle.disappointed_knock  # moins qu'une insulte, qui la vise (ADR 0107)


def test_her_owner_always_counts_more_than_a_close_friend():
    assert 1.0 <= social_derive(_t(devotion=0.0)).owner_weight < social_derive(T.Temperament()).owner_weight == 1.3 \
        < social_derive(_t(devotion=1.0)).owner_weight


def test_shyness_energy_attachment_and_stability():
    assert needs_derive(_t(shyness=0.9)).stranger_company < needs_derive(_t(shyness=0.1)).stranger_company
    assert body_derive(_t(energy=0.9)).tired_below < body_derive(_t(energy=0.1)).tired_below
    assert affect_derive(_t(attachment=0.9)).bond_step > affect_derive(_t(attachment=0.1)).bond_step
    assert affect_derive(_t(stability=0.1)).anchor_alpha > affect_derive(_t(stability=0.9)).anchor_alpha


# ── blessée, touchée, masquée, jalouse ────────────────────────────────────


def test_hurt_her_reaction_adds_to_what_she_said_and_never_erases_it():
    """Blessée et dite triste : la colérique a aussi de la colère (la moitié de sa tristesse), la peureuse de la peur ;
    se refermer, ou rien de particulier : rien ne change. Une colère déclarée pèse davantage chez la colérique."""
    sad = Declared(Emotion.SAD, 0.6)
    angry = dict(ph.reacting(sad, "anger", 1.5, 0.5).all)
    assert angry == {"sad": 0.6, "angry": 0.3}
    assert dict(ph.reacting(sad, "fear", 1.5, 0.5).all) == {"sad": 0.6, "scared": 0.3}
    assert ph.reacting(sad, "withdrawal", 1.5, 0.5) is sad and ph.reacting(sad, "", 1.5, 0.5) is sad
    assert ph.reacting(Declared(Emotion.ANGRY, 0.5), "anger", 1.5, 0.5).intensity == 0.75


def test_hurt_the_relation_cools_and_never_grows_tender():
    """Le constat G4 : triste envers qui la blesse, ce n'est pas être triste avec lui — l'ancre se refroidit autant
    qu'avec de la colère, sans attachement ; la même tristesse partagée, elle, rapproche."""
    p, ref = affect_derive(T.Temperament()), ph.reference(affect_derive(T.Temperament()), _cw())
    st = ph.Stance(ph.Osc(ref, ph.ZERO, T0))
    hurt_sad = ph.fold(st, Declared(Emotion.SAD, 0.7), T0, 1, ref, p, hurt=True)
    hurt_angry = ph.fold(st, Declared(Emotion.ANGRY, 0.7), T0, 1, ref, p, hurt=True)
    shared = ph.fold(st, Declared(Emotion.SAD, 0.7), T0, 1, ref, p)
    assert hurt_sad.bond == 0 and shared.bond > 0
    assert ph.regard_of(hurt_sad.anchor, 0, ref, p) < 0 < ph.regard_of(shared.anchor, shared.bond, ref, p)
    assert ph.regard_of(hurt_sad.anchor, 0, ref, p) <= ph.regard_of(hurt_angry.anchor, 0, ref, p) + 0.05
    mixed = ph.fold(st, Declared(Emotion.SAD, 0.6, (("sad", 0.6), ("angry", 0.3))), T0, 1, ref, p, hurt=True)
    assert mixed.hostile == 1 and hurt_sad.hostile == 0  # une colère nette, même seconde, compte


def test_touched_her_face_defends_itself_but_what_she_feels_stays():
    love = Declared(Emotion.LOVE, 0.6, (("love", 0.6), ("embarrassed", 0.3)))
    assert ph.defended(love, "attack") == [(Emotion.FRUSTRATED, 0.48), (Emotion.EMBARRASSED, 0.3)]
    assert ph.defended(love, "deny") == [(Emotion.LOVE, 0.15)]
    assert ph.defended(love, "admit") == [(Emotion.LOVE, 0.72)]
    assert ph.defended(love, "") == [] and ph.defended(Declared(Emotion.ANGRY, 0.6), "attack") == []
    assert ph.tender(love, 0.25) and not ph.tender(Declared(Emotion.SAD, 0.9), 0.25)


def test_the_mask_who_sees_what():
    """Au milieu, la même avec toutes ; la dandere en montre moins à une inconnue, la tsundere cache sa tendresse à
    une proche (pas sa colère) ; une connaissance, une amie : à mi-chemin."""
    from mika.faculties.affect import shown_factor

    def seen(mask, closeness, emotion):
        return shown_factor(affect_derive(_t(mask=mask)), closeness, False)(emotion)

    for closeness in ("stranger", "acquaintance", "friend", "close"):
        assert seen(0.5, closeness, Emotion.LOVE) == 1.0
    assert seen(0.1, "stranger", Emotion.LOVE) < seen(0.1, "acquaintance", Emotion.LOVE) < seen(0.1, "close",
                                                                                                Emotion.LOVE) == 1.0
    assert seen(0.9, "close", Emotion.LOVE) < seen(0.9, "friend", Emotion.LOVE) < seen(0.9, "stranger",
                                                                                         Emotion.LOVE) == 1.0
    assert seen(0.9, "close", Emotion.ANGRY) == 1.0
    assert shown_factor(affect_derive(T.Temperament()), "close", True)(Emotion.LOVE) < 1.0  # refermée


def test_jealousy_weighs_what_she_declares_and_its_sting_grows_without_a_cutoff():
    jealous = Declared(Emotion.JEALOUS, 0.4)
    assert ph.weighed(jealous, {Emotion.JEALOUS: affect_derive(T.Temperament()).jealous_weight}) is jealous
    assert ph.weighed(jealous, {Emotion.JEALOUS: affect_derive(_t(jealousy=0.9)).jealous_weight}).intensity > 0.4 \
        > ph.weighed(jealous, {Emotion.JEALOUS: affect_derive(_t(jealousy=0.1)).jealous_weight}).intensity
    # sans coupure (ADR 0150) : rien tout en bas, un peu au milieu, la piqûre tout en haut
    stings = [attention_derive(_t(jealousy=x)).envy_intensity for x in (0.0, T.LOWEST, 0.5, T.HIGHEST, 1.0)]
    assert stings[0] == 0.0 < stings[1] < stings[2] < stings[3] < stings[4] == 0.6
    assert attention_derive(T.Temperament()).envy_intensity == stings[2] == 0.15
