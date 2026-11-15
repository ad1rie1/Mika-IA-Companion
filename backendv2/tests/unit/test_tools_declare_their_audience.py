"""Ce qu'un outil exige de qui est en face, il le déclare (ADR 0148), par ses intentions.

- un outil dont le gestionnaire refuse selon qui est en face, au-delà de ce que le plafond dit déjà, déclare cette
  condition (``ToolSpec.when``) : même quand une ligne de sa famille l'ouvre à tout le monde, les messages du
  téléphone ne sont offerts qu'à la personne dont c'est le téléphone, une position qu'en tête-à-tête à quelqu'un
  qui a un compte — jamais dans un salon, jamais à une inconnue ;
- l'offre et le gestionnaire jugent par la même fonction ;
- dessiner, qui agit, n'en a pas besoin : le plafond le garde déjà d'un salon et d'une inconnue (ADR 0134) ;
- la page « Droits » montre la condition d'un outil réservé : réservé et gardé à la fois ;
- la colonne d'un outil dit ce qu'il ouvre (ADR 0226) : relire son journal lit, et une condition le garde d'une
  inconnue et d'un salon ; douter et défaire une liaison écrivent une preuve mais restent avec ce qui lit, pour servir
  là où une usurpation se tente. L'offre de ces trois outils ne change nulle part, Internet compris : par Internet,
  quelqu'un d'autre que toi compte comme une inconnue (rien ne prouve qui écrit), et la condition l'y ferme à son
  journal, comme le plafond le faisait.
"""

from __future__ import annotations

from types import SimpleNamespace

from mika.app.composition import policies
from mika.app.handmade.rights import fixed_tools
from mika.faculties.identity import audience_for
from mika.faculties.identity.tools import something_to_doubt
from mika.faculties.self.night import in_known_company
from mika.kernel.frame import Audience
from mika.kernel.registry import ArbitrationPolicy
from mika.plugins.location import offered as located
from mika.plugins.phone import offered as phoned
from mika.ports.llm import LLMResponse
from mika.runtime.pipeline import EpisodeRequest
from mika.runtime.tool_offer import offer
from mika.sim.clock import run_virtual
from mika.vocab.access import ALONE, EVERYONE, Table, ToolRule
from mika.vocab.canals import Canals
from mika.vocab.episodes import Kind
from mika.vocab.privacy import ChannelTrust
from mika.vocab.rights import Rights
from tests.fixtures.mika import boot, build, connect

GUARDED = ("location_where", "phone_draft", "phone_messages")
WATCHED = (*GUARDED, "draw")
DOUBTING = ("identity_doubt", "identity_forget_binding")
TOLD = ("self_journal", *DOUBTING)
#: un opérateur a ouvert ces familles à tout le monde, pour lire comme pour agir
EVERYONE_ALL = Table[ToolRule](lines=(ToolRule(who=(EVERYONE,), read=ALONE, act=ALONE, keep="public"),),
                               default=ToolRule())
SITUATIONS = (("toi", "user_1", None), ("compte", "user_2", None), ("salon", "user_1", "salon"),
              ("inconnue", "web_inconnu", None))


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


def test_her_journal_reads_and_doubting_stays_with_what_reads_without_changing_who_gets_them(tmp_path):
    kernel, clock, _llm, _ = build(tmp_path, lambda req: LLMResponse("D'accord."), arbitration=ArbitrationPolicy())

    async def main():
        await boot(kernel)
        try:
            await connect(kernel, "user_1", "Adrien", operator=True)
            await connect(kernel, "user_2", "Béa")
            await connect(kernel, "web_inconnu", "Zoé", authenticated=False)
            frame = kernel.mind.frame()
            tools = kernel.registry.tools
            policy = policies()[Kind.REPLY]
            vital = Rights(canals=Canals())
            opened = Rights(canals=Canals(), families={tools[n].bundle: EVERYONE_ALL for n in TOLD})
            out: dict[tuple[str, str], list[str]] = {}
            for rights_name, rights in (("vital", vital), ("ouvert", opened)):
                for name, target, room in SITUATIONS:
                    aud = audience_for(frame, EpisodeRequest(kind=Kind.REPLY, target=target, room=room))
                    out[rights_name, name] = sorted(n for n in offer(tools, policy, Kind.REPLY, aud, rights=rights)
                                                    if n in TOLD)
            # par Internet (le minimum vital du canal : à toi tout, aux autres un outil qui lit). Seule une session web
            # ou mobile prouve qui parle : un compte extérieur a la confiance « compte » (``channel_trust``), qu'un
            # opérateur l'ait relié à une personne (« reconnue ») ou non
            internet = {
                "toi": Audience(persons=("ext_1",), channel="external", public=False, owner=True, person="user_1",
                                trust=ChannelTrust.ACCOUNT.value),
                "reconnue": Audience(persons=("ext_2",), channel="external", public=False, owner=False,
                                     person="user_2", trust=ChannelTrust.ACCOUNT.value),
                "inconnue": Audience(persons=("ext_9",), channel="external", public=False,
                                     trust=ChannelTrust.ACCOUNT.value),
            }
            by_internet = {(rights_name, name): sorted(n for n in offer(tools, policy, Kind.REPLY, aud, rights=rights)
                                                       if n in TOLD)
                           for rights_name, rights in (("vital", vital), ("ouvert", opened))
                           for name, aud in internet.items()}
            shown = fixed_tools(SimpleNamespace(kernel=kernel, names=SimpleNamespace(bundle=lambda key: key)))
            return out, by_internet, tools, shown
        finally:
            await kernel.stop()

    out, by_internet, tools, shown = run_virtual(clock, main)
    # l'offre d'avant, inchangée : son journal devant toi et un compte, le doute là où il y a à douter
    for rights_name in ("vital", "ouvert"):
        assert {name: out[rights_name, name] for name, _t, _r in SITUATIONS} == {
            "toi": ["self_journal"], "compte": ["self_journal"], "salon": [], "inconnue": sorted(DOUBTING)}, rights_name
    # par Internet non plus, rien ne change : quelqu'un d'autre que toi y est une inconnue (rien ne prouve qui écrit),
    # même reliée à une personne ; sa condition lui ferme son journal, comme le plafond d'une action le faisait
    for rights_name in ("vital", "ouvert"):
        assert {name: by_internet[rights_name, name] for name in ("toi", "reconnue", "inconnue")} == {
            "toi": sorted(TOLD), "reconnue": sorted(DOUBTING), "inconnue": sorted(DOUBTING)}, rights_name
    # ce que chacun dit : son journal lit, gardé par sa condition ; douter reste avec ce qui lit
    journal = tools["self_journal"]
    assert journal.acts is False and journal.when is in_known_company
    assert not any(tools[n].acts for n in DOUBTING)
    assert tools["identity_doubt"].when is tools["identity_forget_binding"].when is something_to_doubt
    guarded = {n for _why, names in shown["guarded"] for n in names}
    assert {"self_journal", *DOUBTING} <= guarded
