"""Les vues des facultés se lisent en français, et nomment les gens (ADR 0042, reste du lot WP10).

Le parcours de la console trouvait plus de deux cents « +0.05 » (humeur, postures), des « 8.0 h »
(besoins), « « Bea » (user_2) » partout dans l'humeur et « en répondant · user_1 » dans l'onglet
Affect d'une personne. Les nombres passent par les formateurs du noyau (``num_fr``, ``pct_fr`` :
« +0,05 », « 8 h », « 42 % ») ; une personne se lit par son nom, sa clé reste au survol ou dans
le lien de sa fiche. Le détail technique (« mono ») garde ses clés.
"""

from __future__ import annotations

import asyncio
import dataclasses
import re
from typing import Any

from mika.kernel.inspect import Text
from mika.ports.llm import LLMResponse
from mika.runtime.inspection import Inspection
from mika.sim.clock import run_virtual
from tests.fixtures.mika import boot, build, connect, said

#: un nombre à décimale avec un point (« +0.05 », « 4.0 h ») : jamais dans une vue en français
POINT_DECIMAL = re.compile(r"(?<![\w.])[+−-]?\d+\.\d+(?![\w.])")
#: « « Bea » (user_2) » : un nom suivi de sa clé technique
NAME_AND_KEY = re.compile(r"» \((?:user|tg|web|anon)_")
#: « en répondant · user_1 » : une clé d'adresse donnée en clair
BARE_HANDLE = re.compile(r"(?:^|[ ·,(])(?:user|tg|web)_\d+(?:$|[ ·,)])")
#: là où l'adresse est l'information elle-même : la liste des adresses d'une personne, les connexions
#: vivantes, et le fil (par quelle adresse chaque message, chaque conversation est arrivé)
ADDRESS_VIEWS = frozenset({"identity/adresses", "presence/presents", "transcript/messages", "transcript/echanges"})


def _strings(value: Any, out: list[str]) -> None:
    """Tout le texte qu'un bloc montre, sauf le détail technique (« mono ») et les survols."""
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, Text):
        if value.kind != "mono":
            out.append(value.text)
            out.append(value.secondary)
    elif dataclasses.is_dataclass(value) and not isinstance(value, type):
        for f in dataclasses.fields(value):
            if f.name in ("hint", "key", "href", "kind", "tone", "subject", "name", "owner", "param", "older",
                          "newer", "value"):
                continue
            _strings(getattr(value, f.name), out)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _strings(v, out)


def test_faculty_views_say_numbers_in_french_and_name_people(tmp_path):
    kernel, clock, _, _ = build(tmp_path, lambda req: LLMResponse("Oh, bonne nouvelle ! [EMOTION:happy:0.7]"))

    async def scenario():
        await boot(kernel)
        await connect(kernel, "user_2", "Bea")
        for text in ("salut Mika !", "j'ai eu mon permis aujourd'hui", "merci, t'es adorable"):
            await (await kernel.perceive(said("user_2", text))).reply
            await asyncio.sleep(90)
        await asyncio.sleep(1800)
        ins = Inspection(kernel)
        shown: dict[str, list[Any]] = {}
        for spec in ins.views():
            key = f"{spec.owner}/{spec.name}"
            if spec.subject == "person":
                shown[key] = await ins.arun(spec, {}, subject="user_2")
            elif spec.subject:
                continue
            else:
                shown[key] = await ins.arun(spec, {})
        await kernel.stop()
        return shown

    shown = run_virtual(clock, scenario)
    assert {"affect/humeur", "affect/postures", "needs/needs"} <= set(shown)
    problems: dict[str, list[str]] = {}
    for key, blocks in shown.items():
        texts: list[str] = []
        _strings(blocks, texts)
        keys_ok = key in ADDRESS_VIEWS
        bad = [t for t in texts if t and (POINT_DECIMAL.search(t) or (not keys_ok and (
            NAME_AND_KEY.search(t) or BARE_HANDLE.search(t))))]
        if bad:
            problems[key] = bad[:5]
    assert not problems, problems
    every = []
    for blocks in shown.values():
        _strings(blocks, every)
    assert any("Bea" in t for t in every)  # elle est nommée
    assert any(re.search(r"[+−]0,\d\d", t) for t in every)  # et les nombres signés sont à la française
