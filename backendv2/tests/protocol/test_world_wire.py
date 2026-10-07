"""Le protocole du monde (``mika.world/1``, ADR 0050) tel qu'un moteur le lit.

- chaque exemple de la spécification (``docs/protocole-monde.md``) se lit dans son sens, se réécrit à
  l'identique et respecte le schéma JSON publié — celui d'où un moteur génère ses types : la spécification ne
  peut pas vieillir sans qu'un test le dise ;
- les types C# que Unity en génère (``WorldProtocol.g.cs``) sont à jour ;
- chaque sorte de trame est illustrée ;
- une trame inconnue, un champ inconnu, une trame du mauvais sens : refusés ;
- chaque commande dit les rôles qu'elle exige et son débit ; constater est à l'hôte, éditer au créateur.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, get_args

import jsonschema
import pytest
from pydantic import ValidationError

from mika.adapters.world import protocol as p
from mika.contracts import world as w

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "docs" / "protocole-monde.md"
EXAMPLE = ROOT / "examples" / "monde" / "chambre.json"
GENERATOR = ROOT.parent / "frontend" / "Unity" / "tools" / "gen_world_protocol.py"
BLOCK = re.compile(r"```json (client|serveur)\n(.*?)```", re.S)
SIDES = {"client": p.CLIENT, "serveur": p.SERVER}


def _examples() -> list[tuple[str, str]]:
    return BLOCK.findall(SPEC.read_text(encoding="utf-8"))


def _types(frame_union: Any) -> set[str]:
    union = get_args(frame_union)[0]
    return {cls.model_fields["type"].default for cls in get_args(union)}


EXAMPLES = _examples()


def test_la_specification_a_ses_exemples() -> None:
    sides = [side for side, _ in EXAMPLES]
    assert sides.count("client") >= 15 and sides.count("serveur") >= 15


@pytest.mark.parametrize(("side", "body"), EXAMPLES, ids=[f"{i}-{s}" for i, (s, _) in enumerate(EXAMPLES)])
def test_chaque_exemple_se_lit_et_se_reecrit(side: str, body: str) -> None:
    frame = SIDES[side].validate_json(body)
    again = SIDES[side].validate_json(p.dump(frame))
    assert again == frame


@pytest.mark.parametrize(("side", "body"), EXAMPLES, ids=[f"{i}-{s}" for i, (s, _) in enumerate(EXAMPLES)])
def test_chaque_exemple_respecte_le_schema_publie(side: str, body: str) -> None:
    schema = p.json_schema()["client" if side == "client" else "server"]
    jsonschema.validate(json.loads(body), schema)


def test_les_types_generes_pour_unity_sont_a_jour() -> None:
    """Unity lit le fil avec des types générés depuis ce schéma. Un champ du contrat qu'ils ignorent est perdu à
    la lecture, puis effacé côté noyau au premier ``put`` du créateur, qui remplace l'élément entier."""
    if not GENERATOR.exists():
        pytest.skip("client Unity absent")
    out = subprocess.run([sys.executable, str(GENERATOR), "--check"], capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr


def test_chaque_sorte_de_trame_est_illustree() -> None:
    shown = {json.loads(body)["type"] for _, body in EXAMPLES}
    # la définition entière est l'exemple de ``examples/`` (voir le test suivant)
    assert _types(p.ClientFrame) <= shown
    assert _types(p.ServerFrame) - {"definition"} <= shown


def test_la_definition_entiere_passe_dans_une_trame() -> None:
    world = w.WorldDef.model_validate_json(EXAMPLE.read_text(encoding="utf-8"))
    frame = p.Definition(world=world)
    assert p.server_frame(p.dump(frame)) == frame
    jsonschema.validate(json.loads(p.dump(frame)), p.json_schema()["server"])


class TestCeQuiEstRefuse:
    def test_une_trame_inconnue(self) -> None:
        with pytest.raises(ValidationError):
            p.client_frame('{"type": "teleport", "cmd": "x", "to": "garden"}')

    def test_un_champ_inconnu(self) -> None:
        with pytest.raises(ValidationError):
            p.client_frame('{"type": "act", "cmd": "a-1", "action": "allumer", "object": "desk_lamp", "x": 1.0}')

    def test_une_trame_du_mauvais_sens(self) -> None:
        with pytest.raises(ValidationError):
            p.client_frame('{"type": "delta", "seq": 1, "at": 1, "cause": {"source": "host"}, "changes": []}')

    def test_des_valeurs_bornees(self) -> None:
        with pytest.raises(ValidationError):
            p.client_frame('{"type": "sync", "after": -1}')
        with pytest.raises(ValidationError):
            p.client_frame(json.dumps({"type": "moved", "cmd": "a b", "room": "bedroom"}))
        with pytest.raises(ValidationError):
            p.client_frame(json.dumps({"type": "moved", "cmd": "m-1", "room": "Chambre"}))

    def test_une_personne_ne_se_fait_pas_passer_pour_un_autre_acteur(self) -> None:
        """Le corps qu'une connexion pilote est celui que le noyau lui donne (``welcome.actor``) : aucune
        commande d'une joueuse ne nomme l'acteur qui agit."""
        for kind in ("act", "moved", "address", "answer", "pose"):
            cls = next(c for c in get_args(get_args(p.ClientFrame)[0]) if c.model_fields["type"].default == kind)
            assert "actor" not in cls.model_fields, kind


class TestRolesEtDebits:
    def test_chaque_commande_dit_ses_roles_et_son_debit(self) -> None:
        commands = _types(p.ClientFrame) - {"hello", "sync", "ping"}
        assert set(p.REQUIRES) == commands
        assert set(p.RATES) == _types(p.ClientFrame) - {"hello"}

    def test_constater_est_a_l_hote_editer_au_createur(self) -> None:
        assert p.REQUIRES["report"] == {p.Role.HOST}
        assert p.REQUIRES["edit"] == p.REQUIRES["describe"] == {p.Role.CREATOR}
        assert p.Role.CREATOR not in p.REQUIRES["act"]
