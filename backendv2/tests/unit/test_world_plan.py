"""Ce qu'une action devient dans le monde (ADR 0050), par ses intentions — le planificateur pur, sur le monde
d'exemple (deux pièces, des objets qu'on porte, un chat).

- aller quelque part : en ligne droite dans la pièce, de passage en passage d'une pièce à l'autre, debout à un
  endroit où l'on se tient et assise sur une chaise ; un lieu plein ou sans passage est refusé ;
- les mains : on prend ce qui se porte et que personne ne tient, d'une main ou des deux ; on pose ce qu'on
  tient sur la première place libre, dans un contenant qui a de la place, ou par terre ;
- une action propre à un objet : seulement dans l'état où elle a un sens, et ce qu'il faut tenir se prend
  d'abord ;
- conclure revalide : ce qui était vrai au départ ne l'est peut-être plus (la tasse a été prise entre-temps) ;
- l'état vécu reste cohérent : ce qu'on tient se lit dans les objets, une édition renvoie chez soi ce qui
  n'a plus de sens.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mika.contracts import world as w
from mika.faculties.world import plan

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "monde" / "chambre.json"
T = plan.Timing()


@pytest.fixture
def world() -> tuple[w.WorldDef, dict[str, w.ActorState], dict[str, w.ObjectState]]:
    defn = w.WorldDef.model_validate_json(EXAMPLE.read_text(encoding="utf-8"))
    actors, objects = plan.genesis(defn)
    return defn, actors, objects


def _done(defn, actors, objects, steps, actor=w.MIKA):
    intent = plan.intent_of(actor, steps, 0, T, w.Cause(source=w.Source.MIKA, actor=actor), "i")
    outcome, reason, changes = plan.conclude(defn, actors, objects, intent)
    assert outcome is w.Outcome.DONE, reason
    return plan.apply(actors, objects, changes, intent.eta)


class _Expect:
    def __init__(self, code: w.Refusal) -> None:
        self.code = code

    def __enter__(self) -> None:
        return None

    def __exit__(self, kind, exc, tb) -> bool:
        assert kind is plan.Refused, f"attendu un refus {self.code}, rien n'a été refusé"
        assert exc.code is self.code, f"attendu {self.code}, reçu {exc.code} : {exc.message}"
        return True


class TestLeMondeAuDepart:
    def test_chacun_a_son_lieu_chaque_chose_a_sa_place(self, world) -> None:
        defn, actors, objects = world
        assert (actors[w.MIKA].place, actors[w.MIKA].posture) == ("center", w.Posture.STAND)
        assert (actors["npc:moka"].place, actors["npc:moka"].posture) == ("sofa", w.Posture.SIT)
        assert objects["desk_lamp"].state == "off" and objects["mug"].state == "full"
        assert all(a.holding == () for a in actors.values())


class TestAller:
    def test_dans_la_piece_en_ligne_droite_et_assise_sur_une_chaise(self, world) -> None:
        defn, actors, _ = world
        steps = plan.plan_go(defn, T, actors, w.MIKA, "desk")
        assert [(s.kind, s.to_place, s.posture) for s in steps] == [("walk", "desk", None), ("posture", None, w.Posture.SIT)]
        assert steps[0].duration_us > 0

    def test_d_une_piece_a_l_autre_par_les_passages(self, world) -> None:
        defn, actors, _ = world
        steps = plan.plan_go(defn, T, actors, w.MIKA, "sofa")
        assert [(s.kind, s.to_room, s.to_place) for s in steps if s.kind == "walk"] == [
            ("walk", "bedroom", "door"), ("walk", "living_room", "living_door"), ("walk", "living_room", "sofa")]
        assert steps[-1].posture is w.Posture.SIT

    def test_se_lever_avant_de_partir(self, world) -> None:
        defn, actors, objects = world
        actors, objects = _done(defn, actors, objects, plan.plan_go(defn, T, actors, w.MIKA, "desk"))
        steps = plan.plan_go(defn, T, actors, w.MIKA, "window")
        assert steps[0].kind == "posture" and steps[0].posture is w.Posture.STAND

    def test_deja_la_rien_a_faire(self, world) -> None:
        defn, actors, _ = world
        assert plan.plan_go(defn, T, actors, w.MIKA, "center") == []

    def test_s_allonger_seulement_sur_un_lit(self, world) -> None:
        defn, actors, _ = world
        assert plan.plan_go(defn, T, actors, w.MIKA, "bed", w.Posture.LIE)[-1].posture is w.Posture.LIE
        with _Expect(w.Refusal.WRONG_POSTURE):
            plan.plan_go(defn, T, actors, w.MIKA, "desk", w.Posture.LIE)

    def test_sans_passage(self, world) -> None:
        defn, actors, _ = world
        bedroom = defn.room("bedroom")
        cut = w.apply_changes(defn, [w.DefPut(item=bedroom.model_copy(update={"exits": ()}))])
        with _Expect(w.Refusal.UNREACHABLE):
            plan.plan_go(cut, T, actors, w.MIKA, "sofa")

    def test_un_lieu_plein(self, world) -> None:
        defn, actors, objects = world
        actors, objects = plan.apply(actors, objects, [w.ActorMoved(actor="npc:moka", room="bedroom", place="desk",
                                                                    posture=w.Posture.SIT)], 1)
        with _Expect(w.Refusal.OCCUPIED):
            plan.plan_go(defn, T, actors, w.MIKA, "desk")


class TestLesMains:
    def test_prendre_puis_poser_ailleurs(self, world) -> None:
        defn, actors, objects = world
        actors, objects = _done(defn, actors, objects, plan.plan_interact(defn, T, actors, objects, w.MIKA, "mug", "take"))
        assert actors[w.MIKA].holding == ("mug",) and actors[w.MIKA].place == "desk"
        steps = plan.plan_interact(defn, T, actors, objects, w.MIKA, "mug", "put", "shelves")
        actors, objects = _done(defn, actors, objects, steps)
        assert objects["mug"].location == w.On(object="shelves", slot=2)  # les places 0 et 1 ont leurs livres
        assert actors[w.MIKA].holding == () and actors[w.MIKA].place == "bookshelf"

    def test_les_mains_pleines(self, world) -> None:
        defn, actors, objects = world
        actors, objects = _done(defn, actors, objects, plan.plan_interact(defn, T, actors, objects, w.MIKA, "mug", "take"))
        with _Expect(w.Refusal.HANDS_FULL):
            plan.plan_interact(defn, T, actors, objects, w.MIKA, "guitar", "take")  # il faut les deux mains

    def test_ce_qui_ne_se_porte_pas(self, world) -> None:
        defn, actors, objects = world
        with _Expect(w.Refusal.NOT_PORTABLE):
            plan.plan_interact(defn, T, actors, objects, w.MIKA, "shelves", "take")

    def test_on_ne_prend_pas_ce_qu_un_autre_tient(self, world) -> None:
        defn, actors, objects = world
        actors, objects = plan.apply(actors, objects, [w.ObjectMoved(object="mug", to=w.Held(actor="npc:moka"))], 1)
        assert actors["npc:moka"].holding == ("mug",)
        with _Expect(w.Refusal.HELD_BY_OTHER):
            plan.plan_interact(defn, T, actors, objects, w.MIKA, "mug", "take")

    def test_on_ne_pose_que_ce_qu_on_tient(self, world) -> None:
        defn, actors, objects = world
        with _Expect(w.Refusal.NOT_HOLDING):
            plan.plan_interact(defn, T, actors, objects, w.MIKA, "mug", "put", "shelves")

    def test_un_contenant_plein(self, world) -> None:
        defn, actors, objects = world
        jar = defn.archetype("jar")
        tiny = w.apply_changes(defn, [w.DefPut(item=jar.model_copy(update={"container_slots": 2}))])
        actors, objects = plan.genesis(tiny)
        actors, objects = _done(tiny, actors, objects, plan.plan_interact(tiny, T, actors, objects, w.MIKA, "mug", "take"))
        with _Expect(w.Refusal.OCCUPIED):
            plan.plan_interact(tiny, T, actors, objects, w.MIKA, "mug", "put", "cookie_jar")

    def test_lacher_par_terre_la_ou_elle_est(self, world) -> None:
        defn, actors, objects = world
        actors, objects = _done(defn, actors, objects, plan.plan_interact(defn, T, actors, objects, w.MIKA, "mug", "take"))
        actors, objects = _done(defn, actors, objects, plan.plan_interact(defn, T, actors, objects, w.MIKA, "mug", "drop"))
        assert objects["mug"].location == w.InRoom(room="bedroom", near="desk")

    def test_donner_attend_qu_il_y_ait_quelqu_un(self, world) -> None:
        defn, actors, objects = world
        with _Expect(w.Refusal.UNKNOWN):
            plan.plan_interact(defn, T, actors, objects, w.MIKA, "mug", "give")


class TestCeQuOnFaitDesChoses:
    def test_dans_l_etat_ou_ca_a_un_sens(self, world) -> None:
        defn, actors, objects = world
        actors, objects = _done(defn, actors, objects,
                                plan.plan_interact(defn, T, actors, objects, w.MIKA, "desk_lamp", "allumer"))
        assert objects["desk_lamp"].state == "on"
        with _Expect(w.Refusal.WRONG_STATE):
            plan.plan_interact(defn, T, actors, objects, w.MIKA, "desk_lamp", "allumer")
        assert [i for i, _ in plan.actions_of(defn, objects, actors[w.MIKA], "desk_lamp")] == ["take", "eteindre"]

    def test_une_action_inventee_dit_ce_qui_se_peut(self, world) -> None:
        defn, actors, objects = world
        with pytest.raises(plan.Refused, match="allumer"):
            plan.plan_interact(defn, T, actors, objects, w.MIKA, "desk_lamp", "danser")

    def test_ce_qu_il_faut_tenir_se_prend_d_abord(self, world) -> None:
        defn, actors, objects = world
        steps = plan.plan_interact(defn, T, actors, objects, w.MIKA, "petit_prince", "lire")
        assert [(s.kind, s.action) for s in steps if s.kind == "act"] == [("act", "take"), ("act", "lire")]
        actors, objects = _done(defn, actors, objects, steps)
        me = actors[w.MIKA]
        assert me.holding == ("petit_prince",) and me.activity is not None and me.activity.name == "read"
        assert me.activity.until is None  # lire dure jusqu'à ce qu'on l'interrompe

    def test_une_occupation_a_une_chaise_s_y_fait_assise(self, world) -> None:
        defn, actors, objects = world
        steps = plan.plan_interact(defn, T, actors, objects, w.MIKA, "sketchbook", "dessiner")
        actors, _ = _done(defn, actors, objects, steps)
        assert (actors[w.MIKA].place, actors[w.MIKA].posture) == ("desk", w.Posture.SIT)

    def test_une_occupation_bornee_a_une_fin(self, world) -> None:
        defn, actors, objects = world
        steps = plan.plan_interact(defn, T, actors, objects, w.MIKA, "window_pane", "regarder_dehors")
        actors, _ = _done(defn, actors, objects, steps)
        activity = actors[w.MIKA].activity
        assert activity is not None and activity.until == activity.since + 60 * 1_000_000

    def test_manger_fait_disparaitre_et_libere_la_main(self, world) -> None:
        defn, actors, objects = world
        actors, objects = _done(defn, actors, objects,
                                plan.plan_interact(defn, T, actors, objects, w.MIKA, "cookie_1", "manger"))
        assert "cookie_1" not in objects and actors[w.MIKA].holding == ()


class TestConclureRevalide:
    def test_la_tasse_a_ete_prise_entre_temps(self, world) -> None:
        defn, actors, objects = world
        steps = plan.plan_interact(defn, T, actors, objects, w.MIKA, "mug", "take")
        actors, objects = plan.apply(actors, objects, [w.ObjectMoved(object="mug", to=w.Held(actor="npc:moka"))], 1)
        intent = plan.intent_of(w.MIKA, steps, 0, T, w.Cause(source=w.Source.MIKA), "i")
        outcome, reason, changes = plan.conclude(defn, actors, objects, intent)
        assert (outcome, reason) == (w.Outcome.FAILED, w.Refusal.HELD_BY_OTHER)
        assert changes == [w.ActorMoved(actor=w.MIKA, room="bedroom", place="desk", posture=w.Posture.STAND)]  # elle y est allée

    def test_la_place_a_ete_prise_entre_temps(self, world) -> None:
        defn, actors, objects = world
        actors, objects = _done(defn, actors, objects, plan.plan_interact(defn, T, actors, objects, w.MIKA, "mug", "take"))
        steps = plan.plan_interact(defn, T, actors, objects, w.MIKA, "mug", "put", "shelves")
        actors, objects = plan.apply(actors, objects, [w.ObjectMoved(object="cookie_jar", to=w.On(object="shelves",
                                                                                                     slot=2))], 1)
        intent = plan.intent_of(w.MIKA, steps, 0, T, w.Cause(source=w.Source.MIKA), "i")
        assert plan.conclude(defn, actors, objects, intent)[:2] == (w.Outcome.FAILED, w.Refusal.OCCUPIED)


class TestUnEtatCoherent:
    def test_ce_qu_on_tient_se_lit_dans_les_objets(self, world) -> None:
        defn, actors, objects = world
        actors, objects = plan.apply(actors, objects, [w.ObjectMoved(object="mug", to=w.Held(actor=w.MIKA))], 1)
        assert actors[w.MIKA].holding == ("mug",)
        actors, objects = plan.apply(actors, objects, [w.ObjectGone(object="mug")], 2)
        assert actors[w.MIKA].holding == ()

    def test_une_edition_renvoie_chez_soi_ce_qui_n_a_plus_de_sens(self, world) -> None:
        defn, actors, objects = world
        actors, objects = plan.apply(actors, objects, [w.ObjectMoved(object="mug", to=w.On(object="cookie_jar",
                                                                                             slot=0))], 1)
        edited = w.apply_changes(defn, [w.DefRemove(of=w.DefKind.OBJECT, id="poems")])
        actors2, objects2 = plan.reconcile(edited, actors, objects)
        assert "poems" not in objects2
        assert objects2["mug"].location == defn.object("mug").home  # le bocal n'a pas de surface : retour chez soi
        assert objects2["petit_prince"] == objects["petit_prince"]  # ce qui a un sens ne bouge pas
