"""L'assembleur ``extract`` : un élément sort une fois, dans la fenêtre de son dernier ancrage, traduit."""

from __future__ import annotations

import pytest

from twin.replay.assemble import ArchiveItems, assemble_extraction, tokens_of, window_seqs

WINDOW_1 = """Aujourd'hui : mardi 12 mars 2019, 14 h 30.
Conversation privée avec Julie Martin [P1].

Les messages :
— mardi 12 mars —
[#810] 14:05 Julie Martin [P1] : Je suis enceinte !!!
[#812] 14:06 Mika : QUOI ?? félicitations
"""
WINDOW_2 = """Aujourd'hui : mardi 12 mars 2019, 18 h 00.
Conversation privée avec Julie Martin [P1].

Les messages :
[#820] 17:55 Julie Martin [P1] : c'est pour septembre, garde-le pour toi
[#822] 17:56 Mika : promis, motus
"""

# l'archive : 100 (Julie), 101 (elle), 102 (Julie), 103 (elle) ; le noyau les a rangés sous 810, 812, 820, 822
ARCHIVE_OF_SEQ = {810: [100], 812: [101], 820: [102], 822: [103]}
NAMES = {"p2": "Julie Martin", "p7": "Paul Durand"}


def items() -> ArchiveItems:
    a = ArchiveItems()
    a.add_session({
        "souvenirs": [{"texte": "Julie m'a annoncé qu'elle était enceinte.", "personnes": ["p2"],
                       "messages": [100, 101], "importance": 4}],
        "evenements": [{"texte": "la naissance du bébé de Julie", "quand": "2019-09", "personnes": ["p2"],
                        "messages": [100, 102], "importance": 4, "secret": True}],  # à cheval : sort en fenêtre 2
        "croyances": [{"texte": "Paul est le parrain", "personnes": ["p7"], "messages": [103]},
                      {"texte": "J'adore les annonces surprises", "sur_elle": True, "genre": "gout", "messages": []}],
        "promesses": [{"texte": "garder le secret", "envers": "p2", "messages": [103]}],
    }, [100, 101, 102, 103])
    return a


def test_lecture_de_la_requete() -> None:
    assert tokens_of(WINDOW_1) == {"Julie Martin": "P1"}
    assert window_seqs(WINDOW_1) == [810, 812]


def test_un_element_sort_une_fois_dans_la_fenetre_de_son_dernier_ancrage() -> None:
    a = items()
    w1 = assemble_extraction(WINDOW_1, ARCHIVE_OF_SEQ, a, NAMES)
    w2 = assemble_extraction(WINDOW_2, ARCHIVE_OF_SEQ, a, NAMES)
    assert [s["texte"] for s in w1["souvenirs"]] == ["Julie m'a annoncé qu'elle était enceinte."]
    assert w1["souvenirs"][0]["messages"] == [810, 812]
    assert w1["souvenirs"][0]["personnes"] == ["Julie Martin [P1]"]
    assert w1["evenements"] == []  # son dernier ancrage est dans la fenêtre suivante
    assert len(w2["evenements"]) == 1 and w2["evenements"][0]["messages"] == [820]
    assert w2["evenements"][0]["quand"] == "2019-09-30" and not w2["evenements"][0].get("a_feter")
    assert w2["evenements"][0]["secret"] is True
    # quelqu'un qui n'est pas de la conversation : son nom, pas de jeton
    paul = next(c for c in w2["croyances"] if c["texte"].startswith("Paul"))
    assert paul["personnes"] == ["Paul Durand"]
    # sans ancre : rangé avec le dernier message de la séance
    assert any(c.get("sur_elle") for c in w2["croyances"])
    assert w2["promesses"][0]["envers"] == "Julie Martin [P1]"


def test_plafonds_du_moteur_les_plus_importants_d_abord() -> None:
    a = ArchiveItems()
    a.add_session({"souvenirs": [{"texte": f"souvenir {i}", "messages": [1], "importance": 1 + i % 4}
                                 for i in range(30)]}, [1])
    out = assemble_extraction("Les messages :\n[#5] 10:00 X [P1] : a\n", {5: [1]}, a, {})
    assert len(out["souvenirs"]) == 12
    importances = [s["importance"] for s in out["souvenirs"]]
    assert importances.count(4) == 7 and set(importances) == {3, 4}  # tous les « marquants », puis les « importants »


def test_le_resultat_est_lisible_par_le_moteur() -> None:
    extraction = pytest.importorskip("mika.faculties.memory.extraction")
    from mika.ports.llm import LLMResponse, ToolCall  # noqa: PLC0415

    args = assemble_extraction(WINDOW_2, ARCHIVE_OF_SEQ, items(), NAMES)
    parsed = extraction.parse(LLMResponse("", (ToolCall("t1", extraction.TOOL_NAME, args),), stop="tool_use"))
    assert parsed is not None
    assert len(parsed.evenements) == 1 and len(parsed.croyances) == 2 and len(parsed.promesses) == 1
