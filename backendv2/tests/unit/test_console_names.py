"""Lire la console en français (CON-28, CON-29) et paginer juste (CON-25, CON-26).

Ce qu'un opérateur lit : des nombres à la française (« 0,42 », « 42 % »,
« 0,0034 $ »), des jours (« mer. 1 oct. »), des erreurs qui disent ce qui ne va
pas (« fichier introuvable : x ») — jamais un ``repr`` Python —, et des listes
qui n'annoncent pas une page de plus quand il n'y en a pas.
"""

from __future__ import annotations

from types import SimpleNamespace

from mika.adapters.llm.config import BackendSpec, LLMConfig
from mika.inspector import names
from mika.kernel import forms
from mika.kernel.inspect import (
    INT_MAX,
    InspectContext,
    cursor_page,
    day_fr,
    describe_error,
    int_query,
    money_fr,
    num_fr,
    pct_fr,
)
from mika.vocab.episodes import Kind, Role

NNBSP = " "


def test_numbers_read_the_french_way():
    assert num_fr(0.42) == "0,42" and num_fr(-0.5, 2, signed=True) == "−0,50"
    assert num_fr(0.22, 2, signed=True) == "+0,22" and num_fr(0.0, 2, signed=True) == "0,00"
    assert num_fr(12345) == f"12{NNBSP}345" and num_fr(4.0, 1) == "4,0"
    assert num_fr(0.00001234) == "0,000012"  # jamais d'exposant
    assert num_fr(float("nan")) == "—" and num_fr(None) == "—"
    assert pct_fr(0.423) == f"42{NNBSP}%" and money_fr(0.0034) == f"0,0034{NNBSP}$"
    assert money_fr(1.254) == f"1,25{NNBSP}$"
    assert day_fr(2026, 10, 1, 2) == "mer. 1 oct." and day_fr(2026, 10, 1, 2, with_year=True).endswith("2026")
    # contre-exemple : le format anglais n'apparaît jamais
    assert "." not in num_fr(3.14159) and "0.000 $" not in money_fr(0.0)


def test_errors_say_what_is_wrong_never_a_python_repr():
    assert describe_error(FileNotFoundError(2, "Aucun fichier", "notes.md")) == \
        "fichier introuvable : Aucun fichier : notes.md"
    assert describe_error(TimeoutError()) == "délai dépassé"
    assert describe_error(KeyError("user_9")) == "élément introuvable : user_9"
    assert describe_error("UnconfiguredRole: aucun modèle associé au rôle « reply »") == \
        "aucun modèle configuré : aucun modèle associé au rôle « reply »"
    assert names.detail("TimeoutError()") == "délai dépassé"
    # un repr gardé en texte (la dernière erreur d'un effet, d'un processus) se lit pareil, où qu'on le montre
    assert describe_error("UnconfiguredRole('aucun modèle pour « extract »')") == \
        "aucun modèle configuré : aucun modèle pour « extract »"
    assert describe_error("Rien(vu)") == "Rien(vu)"  # pas un nom d'erreur connu : laissé tel quel
    assert describe_error(RuntimeError("Weird")) == "erreur : Weird"
    # un texte français qui n'est pas une erreur Python reste tel quel
    assert describe_error("Note : rien à faire") == "Note : rien à faire"
    for shown in (describe_error(ValueError("x")), names.detail("ValueError('x')")):
        assert "ValueError" not in shown and "(" not in shown


def test_every_kind_and_role_has_a_french_name():
    assert all(names.kind(k) != k and names.kind(k).islower() for k in Kind)
    assert names.kind("JOB") == "exécution impersonnelle" and names.kind("TASK") == "tâche silencieuse"
    assert all(names.role(r) != str(r) for r in Role)
    # deux issues ne portent jamais le même nom (« interrompu » deux fois rendait le filtre ambigu)
    labels = [label for label, _ in names.OUTCOMES.values()]
    assert len(labels) == len(set(labels))


def test_an_episode_that_went_well_has_spoken_only_if_it_was_speech():
    # une réponse menée à bien « a parlé » ; un journal, un rêve, un travail de projet sont « terminés »
    assert names.outcome("done", Kind.REPLY)[0] == "a parlé" and names.outcome("done", Kind.INITIATIVE)[0] == "a parlé"
    assert names.outcome("done", Kind.JOURNAL)[0] == "terminé" and names.outcome("done", Kind.WORK)[0] == "terminé"
    # contre-exemple : une réponse qui s'est tue ne « parle » pas
    assert names.outcome("abstained", Kind.REPLY)[0] == "s'est tue"


def test_query_integers_are_bounded_for_sqlite():
    assert int_query("99999999999999999999999") == INT_MAX
    assert int_query("-5") == 0 and int_query("abc", 7) == 7 and int_query(None, 3) == 3
    ctx = InspectContext(store=None, ports={}, params={"avant": "99999999999999999999999", "page": "1e9",
                                                          "taille": "-3"})
    assert ctx.int_param("avant") == INT_MAX
    pager = ctx.pager("page", size=50)
    assert pager.offset <= INT_MAX  # même la page la plus lointaine tient dans SQLite


def test_a_cursor_page_reads_one_more_to_know_if_there_is_a_next():
    rows = [SimpleNamespace(seq=n) for n in range(100, 0, -1)]
    # exactement une page : pas de « plus anciens » vers une page vide, et le total est connu
    exact, pager = cursor_page(rows[:25], 25)
    assert len(exact) == 25 and not pager.older and pager.total == 25
    # une de plus : la suite existe, le curseur est la dernière montrée
    more, pager = cursor_page(rows[:26], 25)
    assert len(more) == 25 and pager.older == (("avant", "76"),) and pager.total is None
    # plus loin dans l'historique, sans suite : on ne sait plus le total
    last, pager = cursor_page(rows[:3], 25, current=40)
    assert len(last) == 3 and not pager.older and pager.total is None


def test_renaming_a_provider_names_everything_that_points_to_it():
    cfg = LLMConfig(backends={"a": BackendSpec(kind="ollama", model="m"),
                              "b": BackendSpec(kind="ollama", model="m", fallback="a")},
                    routes={"reply": "a", "extract": "b", "murmur": "a"})
    flat = forms.flatten(cfg)
    refs = dict(forms.references(LLMConfig, flat, "backends", "a"))
    assert set(refs) == {"routes.reply", "routes.murmur", "backends.b.fallback"}
    assert refs["routes.reply"] == "Rôles · répondre (voix)"
    renamed = {k if k != "a" else "local": v for k, v in flat["backends"].items()}
    changes, touched = forms.rename_references(LLMConfig, {**flat, "backends": renamed}, "backends", "a", "local")
    new, errors = forms.validate(LLMConfig, cfg, {"backends": renamed, **changes})
    assert not errors and new is not None
    assert new.routes == {"reply": "local", "extract": "b", "murmur": "local"}
    assert new.backends["b"].fallback == "local" and len(touched) == 3
    # contre-exemple : ce qui ne le désignait pas ne bouge pas
    assert dict(forms.references(LLMConfig, flat, "backends", "zzz")) == {}


def test_record_names_follow_one_rule():
    assert forms.RECORD_NAME.fullmatch("local-gemma") and forms.RECORD_NAME.fullmatch("Élodie_2")
    for bad in ("<b>x</b> / ? &", "-x", "a b", "", "x" * 61):
        assert not forms.RECORD_NAME.fullmatch(bad), bad
