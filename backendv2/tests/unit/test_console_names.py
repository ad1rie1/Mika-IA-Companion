"""Lire la console en français (CON-28, CON-29) et paginer juste (CON-25, CON-26).

Ce qu'un opérateur lit : des nombres à la française (« 0,42 », « 42 % »,
« 0,0034 $ », « 0 échec », « 2 échecs »), des jours (« mer. 1 oct. »), des
erreurs qui disent ce qui ne va pas (« fichier introuvable : x ») — jamais un
``repr`` Python —, et des listes qui n'annoncent pas une page de plus quand il
n'y en a pas.
"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from mika.adapters.imaging.models import ListingFailed as ImageListingFailed
from mika.adapters.llm.claude_code import ClaudeCodeError
from mika.adapters.llm.config import BackendSpec, LLMConfig
from mika.adapters.llm.gateway import UnconfiguredRole
from mika.adapters.llm.models import ListingFailed
from mika.adapters.mail.imap import ImapError
from mika.adapters.store_sql.store import StoreSealed
from mika.app import console
from mika.app.composition import arbitration, faculties, policies
from mika.inspector import names
from mika.inspector.catalog import Labels
from mika.kernel import forms
from mika.kernel import inspect as kernel_inspect
from mika.kernel.episode import Outcome
from mika.kernel.faculty import NIGHT_LANE, PROCESS_LANES
from mika.kernel.inspect import (
    INT_MAX,
    InspectContext,
    agree,
    cursor_page,
    int_query,
    money_fr,
    num_fr,
    pct_fr,
    plural,
    short_day_fr,
)
from mika.kernel.registry import Registry
from mika.ports.errors import OUTSIDE, describe_error
from mika.ports.llm import MissingPersona
from mika.runtime.state import RUNTIME
from mika.vocab.episodes import OUTCOME_WORDS, Kind, Role, outcome_words

NNBSP = " "


def test_numbers_read_the_french_way():
    assert num_fr(0.42) == "0,42" and num_fr(-0.5, 2, signed=True) == "−0,50"
    assert num_fr(0.22, 2, signed=True) == "+0,22" and num_fr(0.0, 2, signed=True) == "0,00"
    assert num_fr(12345) == f"12{NNBSP}345" and num_fr(4.0, 1) == "4,0"
    assert num_fr(0.00001234) == "0,000012"  # jamais d'exposant
    assert num_fr(float("nan")) == "—" and num_fr(None) == "—"
    assert pct_fr(0.423) == f"42{NNBSP}%" and money_fr(0.0034) == f"0,0034{NNBSP}$"
    assert money_fr(1.254) == f"1,25{NNBSP}$"
    # un jour se passe entier (une date, ou l'instant d'une page), pas en quatre morceaux : le jour de la semaine
    # se lit dans la date (le 1er octobre 2025 est un mercredi, le 1er octobre 2026 un jeudi)
    assert short_day_fr(date(2025, 10, 1)) == "mer. 1 oct." and short_day_fr(date(2026, 10, 1)) == "jeu. 1 oct."
    assert short_day_fr(datetime(2025, 10, 1, 23)) == "mer. 1 oct."
    assert short_day_fr(date(2025, 10, 1), with_year=True) == "mer. 1 oct. 2025"
    # contre-exemple : le format anglais n'apparaît jamais
    assert "." not in num_fr(3.14159) and "0.000 $" not in money_fr(0.0)


@pytest.mark.parametrize("n, counted, bare", [
    (0, "0 échec", "échec"), (1, "1 échec", "échec"), (2, "2 échecs", "échecs"), (-1, "−1 échec", "échec"),
    (1200, f"1{NNBSP}200 échecs", "échecs"),
])
def test_plural_says_the_count_and_agree_only_the_word(n, counted, bare):
    # le singulier jusqu'à 1 ; le compte écrit comme tout nombre de la console (``num_fr`` : milliers à l'espace
    # fine, « − » pour le signe) ; ``agree`` pour un indice dont le nombre est déjà dit à côté (la valeur d'un
    # badge à l'accueil : « 3 · Courrier › Réception · mails importants pas encore lus », pas « … · 3 mails … »)
    assert plural(n, "échec", "échecs") == counted
    assert agree(n, "échec", "échecs") == bare


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
    # une panne du magasin, gardée en texte ou levée, se dit par les ports
    assert describe_error("StoreSealed: écriture après la fermeture") == \
        "magasin fermé : écriture après la fermeture"
    assert describe_error(StoreSealed()) == "magasin fermé"


def test_the_kernel_alone_knows_no_adapter_failure():
    # le noyau ne dit que les erreurs de Python et la sienne ; celles du monde extérieur lui viennent des ports
    assert kernel_inspect.describe_error("UnconfiguredRole: aucun modèle associé au rôle « reply »") == \
        "UnconfiguredRole: aucun modèle associé au rôle « reply »"
    assert kernel_inspect.describe_error("UnconfiguredRole('aucun modèle pour « extract »')") == \
        "UnconfiguredRole('aucun modèle pour « extract »')"
    assert kernel_inspect.describe_error("StoreSealed()") == "StoreSealed()"
    assert kernel_inspect.describe_error(StoreSealed()) == "erreur inattendue (StoreSealed)"
    assert kernel_inspect.describe_error(TimeoutError()) == "délai dépassé"
    for name, meaning in OUTSIDE.items():
        assert meaning not in kernel_inspect.describe_error(f"{name}: x")
        assert describe_error(f"{name}: x") == f"{meaning} : x"


def test_outside_names_real_failures_of_the_adapters_and_ports():
    raised = (UnconfiguredRole, MissingPersona, StoreSealed, ListingFailed, ImageListingFailed, ClaudeCodeError,
              ImapError)
    assert {kind.__name__ for kind in raised} == set(OUTSIDE)
    assert describe_error(UnconfiguredRole("reply")) == \
        "aucun modèle configuré : aucun modèle associé au rôle « reply »"


def test_every_kind_and_role_has_a_french_name():
    assert all(names.kind(k) != k and names.kind(k).islower() for k in Kind)
    assert names.kind("JOB") == "exécution impersonnelle" and names.kind("TASK") == "tâche silencieuse"
    assert all(names.role(r) != str(r) for r in Role)
    # deux issues ne portent jamais le même nom (« interrompu » deux fois rendait le filtre ambigu)
    labels = [label for label, _ in OUTCOME_WORDS.values()]
    assert len(labels) == len(set(labels))


def test_every_episode_kind_can_really_run():
    # une sorte sans politique n'existe que dans les libellés : la nuit écrit son journal et ses rêves par des rôles
    assert set(Kind) == set(policies())


def test_an_episode_that_went_well_has_spoken_only_if_it_was_speech():
    # une réponse menée à bien « a parlé » ; une tâche, un travail de projet sont « terminés »
    assert outcome_words("done", Kind.REPLY)[0] == "a parlé" and outcome_words("done", Kind.INITIATIVE)[0] == "a parlé"
    assert outcome_words("done", Kind.MURMUR) == ("a parlé", "ok")
    assert outcome_words("done", Kind.TASK)[0] == "terminé" and outcome_words("done", Kind.WORK)[0] == "terminé"
    assert outcome_words("done", Kind.STEP)[0] == "terminé" and outcome_words("done")[0] == "terminé"
    # contre-exemple : une réponse qui s'est tue ne « parle » pas
    assert outcome_words("abstained", Kind.REPLY)[0] == "s'est tue"


def test_every_outcome_is_said_with_the_words_of_the_episodes_page():
    """L'issue d'un épisode se dit une fois, pour toute la console : la page Épisodes, l'accueil, et les onglets d'un
    but ou d'un projet, que les facultés dessinent : « délai dépassé » dans l'onglet d'un but, « trop long » sur la
    page Épisodes, pour le même épisode (audit K5-06)."""
    assert set(OUTCOME_WORDS) == set(Outcome)
    assert {o: outcome_words(o) for o in Outcome} == {
        Outcome.DONE: ("terminé", "ok"), Outcome.ABSTAINED: ("s'est tue", "muted"),
        Outcome.SUPERSEDED: ("supplanté", "warn"), Outcome.TIMEOUT: ("trop long", "danger"),
        Outcome.FAILED: ("échec", "danger"), Outcome.PREEMPTED: ("a cédé la place", "warn"),
        Outcome.INTERRUPTED: ("interrompu par un arrêt", "warn"), Outcome.CANCELLED: ("annulé", "muted"),
    }
    # une issue que la table ne connaît pas se dit telle quelle, sans ton ; rien du tout, un tiret
    assert outcome_words("expired", Kind.REPLY) == ("expired", "") and outcome_words(None) == ("—", "")
    # la table ne vit plus dans l'inspecteur : un seul endroit, que les facultés lisent aussi
    assert not hasattr(names, "OUTCOMES") and not hasattr(names, "outcome")


def test_a_process_lane_is_named_only_when_it_says_something():
    """La voie d'un processus ne bornait rien hors de la nuit : la console ne la nomme que là (« nuit (une à la
    fois) »). Sans voie, rien ; une voie inconnue, que le registre refuse, se montrerait telle quelle."""
    assert names.process_lane(NIGHT_LANE) == "nuit (une à la fois)"
    assert names.process_lane("") == ""
    assert names.process_lane("ailleurs") == "ailleurs"
    assert set(names.PROCESS_LANE_LABELS) == set(PROCESS_LANES)  # chaque voie permise a son nom, et rien d'autre
    # les voies des épisodes gardent le leur ; l'arbitre n'en déclare plus
    assert names.lane("background") == "fond" and "arbitre" not in names.LANES


def _capabilities(**described: str) -> SimpleNamespace:
    specs = {name.replace("_", "."): SimpleNamespace(description=said) for name, said in described.items()}
    return SimpleNamespace(registry=SimpleNamespace(capabilities=specs))


def test_a_capability_has_a_short_name_and_keeps_its_sentence():
    shown = names.Names(_capabilities(a_push="Envoyer l'atelier vers son dépôt (git push)."),
                        Labels(capabilities={"a.push": "Push git"}))
    assert shown.capability_short("a.push") == "Push git"
    assert shown.capability_phrase("a.push") == "Envoyer l'atelier vers son dépôt"
    assert shown.capability("a.push") == "Envoyer l'atelier vers son dépôt (git push)."


def test_a_capability_without_a_short_name_reads_by_its_sentence():
    shown = names.Names(_capabilities(a_new="Faire autre chose (après accord)."), Labels())
    assert shown.capability_short("a.new") == "Faire autre chose"
    # contre-exemple : une capacité inconnue reste lisible, jamais un trou
    assert shown.capability_short("b.autre_geste")


def test_every_capability_of_the_composition_has_a_short_name():
    declared = set(Registry([RUNTIME, *faculties()], arbitration=arbitration()).capabilities)
    assert declared == set(console.CAPABILITY_LABELS)
    assert all(len(short) <= 20 for short in console.CAPABILITY_LABELS.values())  # tient sur une ligne de la file


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
    assert set(refs) == {"routes.reply", "routes.murmur"}
    assert refs["routes.reply"] == "Rôles · répondre (voix)"
    renamed = {k if k != "a" else "local": v for k, v in flat["backends"].items()}
    changes, touched = forms.rename_references(LLMConfig, {**flat, "backends": renamed}, "backends", "a", "local")
    new, errors = forms.validate(LLMConfig, cfg, {"backends": renamed, **changes})
    assert not errors and new is not None
    assert new.routes == {"reply": "local", "extract": "b", "murmur": "local"}
    assert "fallback" not in new.backends["b"].model_dump() and len(touched) == 2
    # contre-exemple : ce qui ne le désignait pas ne bouge pas
    assert dict(forms.references(LLMConfig, flat, "backends", "zzz")) == {}


def test_record_names_follow_one_rule():
    assert forms.RECORD_NAME.fullmatch("local-gemma") and forms.RECORD_NAME.fullmatch("Élodie_2")
    for bad in ("<b>x</b> / ? &", "-x", "a b", "", "x" * 61):
        assert not forms.RECORD_NAME.fullmatch(bad), bad
