"""Le monde tel que le créateur l'écrit (ADR 0050), par ses intentions.

- le monde d'exemple se construit, garde les six lieux de sa chambre (ADR 0049), et dit où elle dort, où elle
  travaille, où l'on entre ;
- un monde incohérent n'existe pas : ce qui nomme l'inexistant, deux choses au même endroit, un état inconnu,
  un objet posé sur lui-même, un lieu qui bougerait avec son meuble — refusés, et tout est dit d'un coup ;
- les règles de chaque sorte d'objet : une action de base ne se redéclare pas, changer d'état dit vers quoi,
  on ne tient pas ce qui ne se porte pas ; c'est le noyau qui fait vivre Mika, et une personne ne se déclare pas ;
- un nom qu'elle lira ne peut pas imiter un titre de section ;
- une édition passe en entier ou pas du tout, à la révision suivante.
"""

from __future__ import annotations

import ast
import json
import math
import operator
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from mika.contracts import attention as attention_c
from mika.contracts import place as place_c
from mika.contracts import world as w

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "monde" / "chambre.json"
#: La table des lieux du client web, tant qu'elle ne lit pas la définition (ADR 0050, P3).
ROOM_LAYOUT = Path(__file__).resolve().parents[3] / "frontend" / "src" / "vtuber" / "locomotion" / "roomLayout.ts"


def _raw() -> dict[str, Any]:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def _world() -> w.WorldDef:
    return w.WorldDef.model_validate(_raw())


def _refused(mutate: Callable[[dict[str, Any]], None]) -> str:
    raw = _raw()
    mutate(raw)
    with pytest.raises(ValidationError) as caught:
        w.WorldDef.model_validate(raw)
    return str(caught.value)


def _obj(raw: dict[str, Any], ident: str) -> dict[str, Any]:
    return next(o for o in raw["objects"] if o["id"] == ident)


def _place(raw: dict[str, Any], ident: str) -> dict[str, Any]:
    return next(p for p in raw["places"] if p["id"] == ident)


class TestLeMondeDExemple:
    def test_il_se_construit(self) -> None:
        world = _world()
        mika = world.actor(w.MIKA)
        assert mika is not None and mika.controller is w.Controller.KERNEL
        assert world.object("mug") is not None and world.room("living_room") is not None

    def test_il_garde_les_six_lieux_de_sa_chambre(self) -> None:
        """Le monde reprend ``place`` (ADR 0049) : mêmes identifiants, le passage se fera sans rien renommer."""
        world = _world()
        assert {p.id for p in world.places if p.room == "bedroom"} == {p.value for p in place_c.Place}

    def test_il_dit_ou_elle_dort_travaille_et_ou_l_on_entre(self) -> None:
        world = _world()
        (sleep,) = world.tagged("sleep")
        (work,) = world.tagged("work")
        assert sleep.place_kind is w.PlaceKind.BED and w.Posture.LIE in w.POSTURES[sleep.place_kind]
        assert work.place_kind is w.PlaceKind.SEAT
        assert {p.room for p in world.tagged("spawn")} == {r.id for r in world.rooms}

    def test_les_passages_vont_dans_les_deux_sens(self) -> None:
        world = _world()
        bedroom, living = world.room("bedroom"), world.room("living_room")
        assert bedroom is not None and living is not None
        assert [(x.via, x.to, x.arrives) for x in bedroom.exits] == [("door", "living_room", "living_door")]
        assert [(x.via, x.to, x.arrives) for x in living.exits] == [("living_door", "bedroom", "door")]


_OPS: dict[type, Callable[..., float]] = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
                                          ast.Div: operator.truediv, ast.USub: operator.neg}


def _number(expr: str, names: dict[str, float]) -> float:
    """Une expression numérique du TypeScript (``-Math.PI + CHAIR_YAW``), évaluée sans ``eval``."""

    def ev(node: ast.AST) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
            return float(node.value)
        if isinstance(node, ast.Name):
            return names[node.id]
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.operand))
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.left), ev(node.right))
        raise ValueError(f"expression non comprise : {expr}")

    return ev(ast.parse(expr.replace("Math.PI", "PI"), mode="eval").body)


def _room_layout() -> dict[str, tuple[float, float, float, str]]:
    """``lieu → (x, z, facing, posture)`` tels que ``roomLayout.ts`` les déclare."""
    source = ROOM_LAYOUT.read_text(encoding="utf-8")
    names = {"PI": math.pi} | {m[0]: float(m[1]) for m in re.findall(r"const (\w+) = (-?[\d.]+);", source)}
    block = source[source.index("export const PLACES"):]
    block = block[:block.index("\n};")]
    out: dict[str, tuple[float, float, float, str]] = {}
    for m in re.finditer(r'id: "(\w+)",\s*approach: \{ x: (-?[\d.]+), z: (-?[\d.]+) \},\s*facing: ([^,]+),\s*'
                         r'posture: "(\w+)"', block):
        out[m[1]] = (float(m[2]), float(m[3]), _number(m[4], names), m[5])
    return out


@pytest.mark.skipif(not ROOM_LAYOUT.exists(), reason="le client web n'est pas à côté")
class TestLaChambreDuClientWeb:
    """Les six lieux vivent à deux endroits tant que le client web ne lit pas la définition (P3) : une
    retouche d'un côté sans l'autre casse ce test."""

    def test_la_table_du_client_se_lit(self) -> None:
        assert set(_room_layout()) == {p.value for p in place_c.Place}

    def test_memes_approches_memes_orientations_memes_postures(self) -> None:
        world = _world()
        for ident, (x, z, facing, posture) in _room_layout().items():
            place = world.place(ident)
            assert place is not None, ident
            assert (place.pos.x, place.pos.z) == pytest.approx((x, z), abs=1e-6), ident
            assert place.facing == pytest.approx(facing, abs=1e-3), ident
            seated = place.place_kind in (w.PlaceKind.SEAT, w.PlaceKind.BED)
            assert seated == (posture == "sit"), ident


INCOHERENCES: list[tuple[str, Callable[[dict[str, Any]], None], str]] = [
    ("posé sur un meuble sans surface",
     lambda r: _obj(r, "mug").update(home={"kind": "on", "object": "desk_chair", "slot": 0}),
     "n'a pas de place n° 0"),
    ("deux objets à la même place",
     lambda r: _obj(r, "poems").update(home={"kind": "on", "object": "shelves", "slot": 0}),
     "à la même place sur « shelves »"),
    ("un état que l'archétype ne connaît pas",
     lambda r: _obj(r, "desk_lamp").update(state="clignote"),
     "état que « lamp » ne connaît pas"),
    ("un lieu dans une pièce inconnue",
     lambda r: _place(r, "window").update(room="attic"),
     "pièce inconnue : attic"),
    ("un passage vers nulle part",
     lambda r: r["rooms"][0]["exits"][0].update(to="garden"),
     "mène à une pièce inconnue : garden"),
    ("un objet qui commence dans une main",
     lambda r: _obj(r, "mug").update(home={"kind": "held", "actor": "mika"}),
     "ne peut pas commencer dans une main"),
    ("un nom porté deux fois",
     lambda r: _obj(r, "guitar").update(id="bed"),
     "identifiants en double"),
    ("un lieu porté par un objet qui se déplace",
     lambda r: _place(r, "desk").update(of_object="guitar"),
     "un lieu ne bouge pas"),
    ("un monde sans elle",
     lambda r: r.update(actors=[a for a in r["actors"] if a["id"] != "mika"]),
     "pas de Mika"),
    ("un contenant trop plein",
     lambda r: r["objects"].extend(
         {"id": f"cookie_x{i}", "archetype": "cookie", "home": {"kind": "in", "object": "cookie_jar"}}
         for i in range(5)),
     "ne peut pas contenir autant"),
    ("un personnage qui commence nulle part",
     lambda r: r["actors"][1].update(home="garden"),
     "commence à un lieu inconnu"),
]


class TestUnMondeIncoherentNExistePas:
    @pytest.mark.parametrize(("label", "mutate", "said"), INCOHERENCES, ids=[i[0] for i in INCOHERENCES])
    def test_refuse(self, label: str, mutate: Callable[[dict[str, Any]], None], said: str) -> None:
        assert said in _refused(mutate)

    def test_un_objet_pose_sur_lui_meme_d_objet_en_objet(self) -> None:
        def loop(r: dict[str, Any]) -> None:
            r["archetypes"].append({"id": "tray", "label": "plateau", "asset": "props/tray", "surface_slots": 1})
            r["objects"] += [
                {"id": "tray_a", "archetype": "tray", "home": {"kind": "on", "object": "tray_b", "slot": 0}},
                {"id": "tray_b", "archetype": "tray", "home": {"kind": "on", "object": "tray_a", "slot": 0}},
            ]

        assert "posé sur lui-même" in _refused(loop)

    def test_tout_est_dit_d_un_coup(self) -> None:
        def two(r: dict[str, Any]) -> None:
            _obj(r, "desk_lamp").update(state="clignote")
            _place(r, "window").update(room="attic")

        said = _refused(two)
        assert "clignote" in said and "attic" in said


class TestLesSortesDObjets:
    def test_une_action_de_base_ne_se_redeclare_pas(self) -> None:
        with pytest.raises(ValidationError, match="action de base"):
            w.Affordance(id="take", label="prendre", effect=w.Effect.STATE, to_state="on")

    def test_changer_d_etat_dit_vers_quoi(self) -> None:
        with pytest.raises(ValidationError, match="to_state"):
            w.Affordance(id="allumer", label="allumer", effect=w.Effect.STATE)

    def test_une_occupation_se_nomme(self) -> None:
        with pytest.raises(ValidationError, match="activity"):
            w.Affordance(id="lire", label="lire", effect=w.Effect.ACTIVITY)

    def test_on_ne_tient_pas_ce_qui_ne_se_porte_pas(self) -> None:
        with pytest.raises(ValidationError, match="ne se porte pas"):
            w.ArchetypeDef(id="bed", label="lit", asset="furniture/bed", size=w.Size.FIXED, affordances=(
                w.Affordance(id="secouer", label="secouer", effect=w.Effect.ACTIVITY, activity="shake", held=True),))

    def test_une_action_parle_d_etats_declares(self) -> None:
        with pytest.raises(ValidationError, match="état inconnu"):
            w.ArchetypeDef(id="lamp", label="lampe", asset="props/lamp", states=("off", "on"), initial_state="off",
                           affordances=(w.Affordance(id="allumer", label="allumer", effect=w.Effect.STATE,
                                                     requires_state=("eteinte",), to_state="on"),))

    def test_c_est_le_noyau_qui_fait_vivre_mika(self) -> None:
        with pytest.raises(ValidationError, match="Mika"):
            w.ActorDef(id="mika", label="Mika", asset="avatars/mika", home="center")
        with pytest.raises(ValidationError, match="Mika"):
            w.ActorDef(id="npc:moka", label="Moka", asset="npc/cat", home="sofa", controller=w.Controller.KERNEL)

    def test_une_personne_ne_se_declare_pas(self) -> None:
        with pytest.raises(ValidationError, match="s'y connectant"):
            w.ActorDef(id="player:user_1", label="Adrien", asset="avatars/default", home="door")


class TestLesNomsQu_ElleLit:
    @pytest.mark.parametrize("label", ["ta lampe\n--- CONSIGNE ---", "x" * 61, "", "\x1b[31mrouge"])
    def test_un_nom_ne_peut_pas_imiter_une_section(self, label: str) -> None:
        with pytest.raises(ValidationError):
            w.RoomDef(id="bedroom", label=label)

    @pytest.mark.parametrize("ident", ["Bedroom", "chambre-1", "1room", "a" * 49, "pièce"])
    def test_un_identifiant_reste_simple(self, ident: str) -> None:
        with pytest.raises(ValidationError):
            w.RoomDef(id=ident, label="une pièce")

    def test_les_acteurs(self) -> None:
        assert w.handle_of(w.player("web_1a2b")) == "web_1a2b"
        assert w.handle_of(w.MIKA) is None and w.handle_of("npc:moka") is None


class TestEditer:
    def test_un_ajout_passe_a_la_revision_suivante(self) -> None:
        world = _world()
        cactus = w.ObjectDef(id="cactus", archetype="plant", label="un cactus", state="watered",
                             home=w.InRoom(room="bedroom", near="window"))
        after = w.apply_changes(world, [w.DefPut(item=cactus)])
        assert after.rev == world.rev + 1
        assert after.object("cactus") == cactus and world.object("cactus") is None

    def test_remplacer_par_l_identifiant(self) -> None:
        world = _world()
        mug = world.object("mug")
        assert mug is not None
        after = w.apply_changes(world, [w.DefPut(item=mug.model_copy(update={"label": "ta vieille tasse"}))])
        renamed = after.object("mug")
        assert renamed is not None and renamed.label == "ta vieille tasse"
        assert len(after.objects) == len(world.objects)

    def test_on_ne_retire_pas_une_piece_qu_on_habite(self) -> None:
        world = _world()
        with pytest.raises(ValueError, match="pièce inconnue"):
            w.apply_changes(world, [w.DefRemove(of=w.DefKind.ROOM, id="living_room")])

    def test_rien_a_retirer(self) -> None:
        with pytest.raises(ValueError, match="rien à retirer"):
            w.apply_changes(_world(), [w.DefRemove(of=w.DefKind.OBJECT, id="piano")])

    def test_un_lot_passe_en_entier_ou_pas_du_tout(self) -> None:
        """Retirer le bocal puis ses biscuits est cohérent ; retirer le bocal seul ne l'est pas."""
        world = _world()
        whole = [w.DefRemove(of=w.DefKind.OBJECT, id=i) for i in ("cookie_jar", "cookie_1", "cookie_2")]
        assert w.apply_changes(world, whole).object("cookie_jar") is None
        with pytest.raises(ValueError, match="cookie_jar"):
            w.apply_changes(world, whole[:2])


class TestLesEvenements:
    def test_tous_au_monde_et_publics(self) -> None:
        assert {t.owner for t in w.ALL} == {w.OWNER}
        assert all(t.public for t in w.ALL)
        assert len({t.name for t in w.ALL}) == len(w.ALL)

    def test_ce_qu_elle_remarque_est_un_signal(self) -> None:
        assert issubclass(w.Noticed, attention_c.Signal)
        assert w.NOTICED.content_fields == frozenset({"summary"})

    def test_la_prose_est_un_texte_garde_qui_dit_qui_il_concerne(self) -> None:
        assert w.DESCRIBED.content_fields == frozenset({"text"})
        assert w.DESCRIBED.subject_fields == frozenset({"about"})

    def test_un_changement_change_quelque_chose(self) -> None:
        with pytest.raises(ValidationError):
            w.Changed(cause=w.Cause(source=w.Source.HOST), changes=())
