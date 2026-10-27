"""Ce qu'un outil exige de qui est en face, il le déclare (ADR 0148), par ses intentions.

- un outil dont le gestionnaire refuse selon qui est en face, au-delà de ce que le plafond dit déjà, déclare cette
  condition (``ToolSpec.when``) : même quand une ligne de sa famille l'ouvre à tout le monde, les messages du
  téléphone ne sont offerts qu'à la personne dont c'est le téléphone, une position qu'en tête-à-tête à quelqu'un
  qui a un compte — jamais dans un salon, jamais à une inconnue ;
- l'offre et le gestionnaire jugent par la même fonction ;
- dessiner, qui agit, n'en a pas besoin : le plafond le garde déjà d'un salon et d'une inconnue (ADR 0134) ;
- la page « Droits » montre la condition d'un outil réservé : réservé et gardé à la fois.
"""

from __future__ import annotations

from types import SimpleNamespace

from mika.app.composition import policies
from mika.app.handmade.rights import fixed_tools
from mika.faculties.identity import audience_for
from mika.kernel.registry import ArbitrationPolicy
from mika.kernel.rights import Rights
from mika.plugins.location import offered as located
from mika.plugins.phone import offered as phoned
from mika.ports.llm import LLMResponse
from mika.runtime.pipeline import EpisodeRequest
from mika.runtime.tools import offer
from mika.sim.clock import run_virtual
from mika.vocab.access import ALONE, EVERYONE, Table, ToolRule
from mika.vocab.canals import Canals
from mika.vocab.episodes import Kind
from tests.fixtures.mika import boot, build, connect

GUARDED = ("location_where", "phone_draft", "phone_messages")
WATCHED = (*GUARDED, "draw")


def test_a_line_that_opens_a_tool_to_everyone_does_not_lift_its_condition(tmp_path):
    kernel, clock, _llm, _ = build(tmp_path, lambda req: LLMResponse("D'accord."), arbitration=ArbitrationPolicy())

    async def main():
        await boot(kernel)
        try:
            await connect(kernel, "user_1", "Adrien", operator=True)
            await connect(kernel, "user_2", "Béa")
            await connect(kernel, "web_inconnu", "Zoé", authenticated=False)
            frame = kernel.mind.frame()
            tools = kernel.registry.tools
            # un opérateur a ouvert ces familles à tout le monde, pour lire comme pour agir
            everyone = Table[ToolRule](lines=(ToolRule(who=(EVERYONE,), read=ALONE, act=ALONE, keep="public"),),
                                       default=ToolRule())
            rights = Rights(canals=Canals(), families={tools[n].bundle: everyone for n in WATCHED})
            policy = policies()[Kind.REPLY]
            out = {}
            for name, target, room in (("toi", "user_1", None), ("compte", "user_2", None),
                                       ("salon", "user_1", "salon"), ("inconnue", "web_inconnu", None)):
                aud = audience_for(frame, EpisodeRequest(kind=Kind.REPLY, target=target, room=room))
                out[name] = sorted(n for n in offer(tools, policy, Kind.REPLY, aud, rights=rights) if n in WATCHED)
            shown = fixed_tools(SimpleNamespace(kernel=kernel, names=SimpleNamespace(bundle=lambda key: key)))
            return out, tools, shown
        finally:
            await kernel.stop()

    out, tools, shown = run_virtual(clock, main)
    assert out == {"toi": sorted(WATCHED), "compte": ["draw", "location_where"], "salon": [], "inconnue": []}
    # l'offre et le gestionnaire : la même fonction
    assert tools["location_where"].when is located
    assert tools["phone_messages"].when is tools["phone_draft"].when is phoned
    assert tools["draw"].when is None and tools["draw"].rule  # le plafond le garde ; la console dit le reste
    # la page « Droits » : réservés, et gardés par leur condition
    reserved = {n for _family, names in shown["reserved"] for n in names}
    guarded = {n for _why, names in shown["guarded"] for n in names}
    assert set(GUARDED) <= reserved & guarded
