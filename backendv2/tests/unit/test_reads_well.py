"""Ce qu'elle lit se lit (ADR 0266) : une phrase assemblée par morceaux reste une phrase, une note d'elle se dit à
elle en entier ou reste la sienne, son humeur ne s'oppose pas à elle-même, et un lot vide ne s'offre pas.

Tous viennent du même prompt réel, celui du 19 novembre 2026 : « Ce que tu pourrais te fabriquer — … — que tu dis
ensuite à qui l'attend ou un projet à toi —, … », « toi le poney » dans une ligne qui disait ensuite « je l'ai
faite », « à peine soulagée, alors que normalement tu es plutôt contente », et un premier appel à des flux qu'elle ne
suit pas."""

from __future__ import annotations

from types import SimpleNamespace as NS

from mika.faculties.social.sections import to_you
from mika.kernel.frame import Audience
from mika.plugins.rss import RSS
from mika.runtime.tool_offer import NEEDS, acting, judge
from mika.vocab.phrasebook import phrase
from mika.vocab.rights import Rights

FRIEND = Audience(persons=("user_1",), public=False, level=1, witness_level=1, private_ok=True)


def test_the_assembled_sentence_about_her_means_reads_whatever_she_is_offered():
    both = acting([NS(name="forge_write"), NS(name="start_project")])
    assert "(une app à toi dans ta Forge" in both and "à qui l'attend ; ou un projet à toi), ne dis pas" in both
    assert "—" not in both.split("Ce que tu pourrais te fabriquer")[1].split("ne dis pas")[0]
    assert "(un projet à toi), ne dis pas" in acting([NS(name="start_project")])
    assert "à qui l'attend), ne dis pas" in acting([NS(name="forge_write")])
    assert "fabriquer" not in acting([NS(name="memory_search")])  # rien à se fabriquer : rien n'en est dit


def test_a_note_of_hers_is_told_to_her_whole_or_stays_hers():
    """Mêler « tu » et « je » faisait répondre un modèle à la place de l'autre (sonde du 2026-10-03) : ce que ses
    notes disent d'elle se dit à elle — mais une note qui garderait un « je » après coup reste entière, à elle."""
    assert to_you("Sam m'appelle « Mikachu »") == "Sam t'appelle « Mikachu »"
    assert to_you("Adrien me surnomme la pieuvre, c'est notre blague") == "Adrien te surnomme la pieuvre, c'est votre blague"
    assert to_you("On a une blague : lui le poney, moi la pieuvre") == "On a une blague : lui le poney, toi la pieuvre"
    kept = "On a une blague sur les yoyos : je l'ai faite sans faire exprès, et c'est moi qui la garde"
    assert to_you(kept) == kept
    assert to_you("Léa adore ma blague du jeudi") == "Léa adore ma blague du jeudi"
    # « jeudi », « même », « matin » ne sont pas des « je », « me », « ma »
    assert to_you("Jeudi matin, même Sam m'appelle Mimi") == "Jeudi matin, même Sam t'appelle Mimi"


def test_her_mood_is_said_without_opposing_two_moods_that_do_not_oppose():
    said = phrase("affect.mood_line.caused", intensity="à peine", feeling="soulagée", usual="contente")
    assert said == "Normalement tu es plutôt contente ; en ce moment, ton humeur générale est à peine soulagée."


def test_her_feed_tools_are_not_offered_while_she_follows_no_feed():
    """Le catalogue annonçait « les flux d'actualité » sans un seul flux suivi : son premier appel n'y trouvait rien."""
    tools = {t.name: t for t in RSS.tools}
    for name in ("rss_list", "rss_read"):
        none = judge(tools, tools[name], FRIEND, "REPLY", Rights(), ports={"feeds": NS(configured=lambda: False)})
        assert (none.offered, none.reason) == (False, NEEDS)
        assert judge(tools, tools[name], FRIEND, "REPLY", Rights(), ports={}).reason == NEEDS  # pas de port du tout
        some = judge(tools, tools[name], FRIEND, "REPLY", Rights(), ports={"feeds": NS(configured=lambda: True)})
        assert some.reason != NEEDS
