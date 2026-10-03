"""Formulaires décrits par les modèles : describe, flatten/nest, parse, within,
validate, durées — et un ``Knob`` qui ne change rien à la validation."""

from __future__ import annotations

import enum
from typing import Annotated, Literal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from mika.adapters.llm.config import BackendSpec, LLMConfig
from mika.adapters.mail import MailAccount, MailConfig
from mika.contracts.self_ import PersonaDoc
from mika.kernel.forms import (
    UNBOUNDED_NOTE,
    FormField,
    Knob,
    PathConflict,
    as_text,
    describe,
    errors_fr,
    flatten,
    nest,
    parse,
    parse_duration,
    show_duration,
    validate,
    visible,
    within,
)
from mika.vocab.affect import Emotion
from mika.vocab.temperament import Temperament

MINUTE = 60_000_000
HOUR = 60 * MINUTE

# ── Modèles de test ───────────────────────────────────────────────────────


class Color(enum.Enum):
    RED = "red"
    BLUE = "blue"


class Inner(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)

    tau_h: Annotated[float, Knob(lo=0.5, hi=48)] = 4.0
    """Constante de temps de l'intérieur."""
    settle_us: Annotated[int, Knob(lo=0, hi=2 * HOUR, advanced=False)] = 15 * MINUTE
    enabled: bool = True
    fast: Annotated[bool, Knob(only=(("enabled", ("true",)),))] = False


class Row(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    weight: Annotated[float, Knob(lo=0, hi=1)] = 0.5


class Sample(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)

    ratio: Annotated[float, Knob(lo=0, hi=1, widget="slider", group="Réglages", help="Le rapport.")] = 0.5
    """Docstring ignorée : le Knob parle d'abord."""
    count: Annotated[int, Field(ge=0, le=10)] = 3
    step_by: Annotated[float, Field(gt=0, lt=5, multiple_of=0.5)] = 1.0
    free: float = 1.0
    """Un nombre sans bornes."""
    mode: Literal["a", "b"] = "a"
    color: Color = Color.RED
    mood: Annotated[Emotion, Knob(choices=(("happy", "contente"), ("sad", "triste")))] = Emotion.HAPPY
    notes: tuple[str, ...] = ()
    token: Annotated[str, Knob(secret=True)] = ""
    api_key: str = ""
    title: Annotated[str, Knob(label="Titre", advanced=False, order=1)] = "x"
    body: Annotated[str, Knob(widget="textarea")] = ""
    who: Annotated[str, Knob(widget="subject", subject="person")] = ""
    limit: float | None = Field(default=None, ge=0, le=100)
    inner: Inner = Inner(tau_h=6.0)
    rows: dict[str, Row] = Field(default_factory=dict)
    weights: Annotated[dict[str, Annotated[int, Knob(lo=0, hi=9)]], Knob(keys=(("a", "A"), ("b", "B")))] = Field(
        default_factory=dict)
    routes: Annotated[dict[str, str], Knob(choices_from="rows")] = Field(default_factory=dict)
    extra: dict[str, list[int]] = Field(default_factory=dict)
    data: Annotated[dict[str, list[int]], Knob(widget="yaml")] = Field(default_factory=dict)
    only_b: Annotated[bool, Knob(only=(("mode", ("b",)),))] = False

    @field_validator("body")
    @classmethod
    def _no_forbidden(cls, v: str) -> str:
        if "interdit" in v:
            raise ValueError("mot interdit")
        return v


def fields_by_path(model: type[BaseModel]) -> dict[str, FormField]:
    return {f.path: f for f in describe(model)}


def form(*rendered: str, **values) -> dict[str, list[str]]:
    """Une soumission : ``values`` avec des chemins où « __ » remplace « . »."""
    out: dict[str, list[str]] = {"_champs": list(rendered)}
    for key, value in values.items():
        out[key.replace("__", ".")] = value if isinstance(value, list) else [value]
    return out


# ── describe ──────────────────────────────────────────────────────────────


def test_kinds_are_inferred_from_annotations():
    kinds = {path: f.kind for path, f in fields_by_path(Sample).items()}
    assert kinds == {
        "ratio": "slider", "count": "int", "step_by": "float", "free": "float", "mode": "select",
        "color": "select", "mood": "select", "notes": "lines", "token": "secret", "api_key": "secret",
        "title": "text", "body": "textarea", "who": "subject", "limit": "float", "inner": "group",
        "inner.tau_h": "duration", "inner.settle_us": "duration", "inner.enabled": "bool", "inner.fast": "bool",
        "rows": "records", "weights": "mapping", "routes": "mapping", "extra": "yaml", "data": "yaml",
        "only_b": "bool",
    }


def test_order_follows_knob_then_declaration_and_groups_stay_together():
    paths = [f.path for f in describe(Sample)]
    assert paths[0] == "title"  # order=1 passe devant
    start = paths.index("inner")
    assert paths[start:start + 5] == ["inner", "inner.tau_h", "inner.settle_us", "inner.enabled", "inner.fast"]
    assert paths.index("ratio") < paths.index("count") < paths.index("inner") < paths.index("rows")


def test_labels_and_help():
    f = fields_by_path(Sample)
    assert f["title"].label == "Titre"
    assert f["step_by"].label == "Step by"
    assert f["inner.tau_h"].label == "Tau"  # l'unité de temps s'affiche à part
    assert f["inner.tau_h"].help == "Constante de temps de l'intérieur."  # docstring d'attribut
    assert f["ratio"].help == "Le rapport."  # le Knob l'emporte sur la docstring
    assert f["count"].help == ""


def test_bounds_from_knob_and_from_pydantic_metadata():
    f = fields_by_path(Sample)
    assert (f["ratio"].lo, f["ratio"].hi) == (0, 1)
    assert (f["count"].lo, f["count"].hi) == (0, 10)
    assert (f["step_by"].lo, f["step_by"].hi, f["step_by"].step) == (0, 5, 0.5)  # gt/lt/multiple_of
    assert (f["inner.settle_us"].lo, f["inner.settle_us"].hi) == (0, 2 * HOUR)
    assert all(not f[p].readonly for p in ("ratio", "count", "step_by", "inner.tau_h", "limit"))


def test_unbounded_number_is_readonly_and_says_why():
    free = fields_by_path(Sample)["free"]
    assert free.readonly
    assert free.help == f"Un nombre sans bornes. {UNBOUNDED_NOTE}"


def test_units_are_guessed_from_the_name_suffix():
    f = fields_by_path(Sample)
    assert (f["inner.tau_h"].unit, f["inner.settle_us"].unit) == ("h", "us")
    assert f["count"].unit == ""

    class Budget(BaseModel):
        reply_tokens: Annotated[int, Knob(lo=0, hi=100)] = 1
        context_tokens: Annotated[int, Knob(label="Contexte (jetons)", lo=0, hi=100)] = 1
        settle_s: Annotated[int, Knob(label="Délai (s)", lo=0, hi=100)] = 1

    b = fields_by_path(Budget)
    assert b["reply_tokens"].unit == "tokens"
    # un libellé qui porte déjà son unité ne reçoit pas une seconde unité devinée (« Contexte (jetons) (tokens) ») —
    # sauf une durée, dont l'unité sert à lire la valeur
    assert b["context_tokens"].unit == "" and fields_by_path(LLMConfig)["context_tokens"].unit == ""
    assert b["settle_s"].unit == "s"


def test_a_rate_per_hour_is_a_number_not_a_duration():
    """G-8 : « Le vide se creuse de, par heure » s'affichait « 3 min » (0,05 lu comme 0,05 h) et refusait « 0.1 »
    (« précisez l'unité »). Un débit (``…_per_h``, ``…_per_min``, ``…_per_s``) n'a pas d'unité de temps devinée ;
    contre-exemple : ``…_h`` reste une durée."""
    from mika.faculties.needs import NeedsParams

    class Rates(BaseModel):
        growth_per_h: Annotated[float, Knob(lo=0, hi=1)] = 0.05
        steps_per_min: Annotated[float, Knob(lo=0, hi=10)] = 1.0
        tau_h: Annotated[int, Knob(lo=0, hi=10 * HOUR)] = HOUR

    r = fields_by_path(Rates)
    assert (r["growth_per_h"].kind, r["growth_per_h"].unit) == ("float", "")
    assert (r["steps_per_min"].kind, r["steps_per_min"].unit) == ("float", "")
    assert (r["tau_h"].kind, r["tau_h"].unit) == ("duration", "h")
    empty = fields_by_path(NeedsParams)["empty_growth_per_h"]
    assert (empty.kind, empty.unit) == ("float", "")
    values, errors = parse([empty], form(empty.path, empty_growth_per_h="0.1"), current={empty.path: 0.05})
    assert not errors and values[empty.path] == 0.1


def test_select_choices_from_literal_enum_and_knob():
    f = fields_by_path(Sample)
    assert f["mode"].choices == (("a", "a"), ("b", "b"))
    assert f["color"].choices == (("red", "red"), ("blue", "blue"))
    assert f["mood"].choices == (("happy", "contente"), ("sad", "triste"))


def test_secrets_by_knob_and_by_name():
    f = fields_by_path(Sample)
    assert f["token"].secret and f["api_key"].secret
    assert not f["title"].secret


def test_nested_model_group_paths_defaults_and_inheritance():
    f = fields_by_path(Sample)
    assert f["inner"].label == "Inner" and f["inner"].default is None
    assert f["inner.tau_h"].group == "Inner"
    assert f["inner.tau_h"].default == 6.0  # la valeur par défaut du parent prime
    # un groupe sans Knob est avancé : ses champs aussi, même déclarés « non avancés »
    assert f["inner"].advanced and f["inner.settle_us"].advanced
    assert f["inner.fast"].only == (("inner.enabled", ("true",)),)  # chemin rebasé
    assert f["ratio"].group == "Réglages" and f["count"].group == ""
    assert not f["title"].advanced and f["count"].advanced  # sans Knob : avancé


def test_records_mapping_and_yaml():
    f = fields_by_path(Sample)
    assert [(i.path, i.kind) for i in f["rows"].item] == [("name", "text"), ("weight", "float")]
    assert f["rows"].item[0].required
    assert f["weights"].keys == (("a", "A"), ("b", "B"))
    assert (f["weights"].item[0].kind, f["weights"].item[0].lo, f["weights"].item[0].hi) == ("int", 0, 9)
    assert f["routes"].choices_from == "rows" and f["routes"].item[0].kind == "text"
    assert f["extra"].readonly and not f["data"].readonly


def test_nullable_and_required():
    f = fields_by_path(Sample)
    assert f["limit"].nullable and not f["count"].nullable
    assert not f["count"].required and fields_by_path(Row)["name"].required


def test_unknown_widget_is_refused():
    with pytest.raises(ValueError, match="widget inconnu"):
        Knob(widget="slidr")


def test_real_temperament():
    f = fields_by_path(Temperament)
    sliders = [p for p in f if p != "background"]
    assert len(sliders) == 8
    assert all((f[p].kind, f[p].lo, f[p].hi, f[p].readonly, f[p].advanced) == ("slider", 0.0, 1.0, False, False)
               for p in sliders)
    assert all(f[p].help and f[p].label != p for p in sliders)  # chaque curseur dit ce qu'il pilote
    assert f["background"].kind == "select" and len(f["background"].choices) == 29
    assert ("happy", "contente") in f["background"].choices


def test_real_persona():
    f = fields_by_path(PersonaDoc)
    assert f["traits"].kind == "lines" and f["name"].kind == "text"
    assert f["temperament"].kind == "group"
    assert f["temperament.reactivity"].group == "Tempérament" and f["temperament.reactivity"].lo == 0.0
    assert f["traits"].group == "Caractère" and not f["traits"].advanced


def test_real_llm_config():
    f = fields_by_path(LLMConfig)
    backends = {i.path: i for i in f["backends"].item}
    assert f["backends"].kind == "records"
    assert backends["kind"].kind == "select" and backends["kind"].required
    assert {v for v, _ in backends["kind"].choices} == {"claude", "claude_code", "openai", "ollama", "ollama_cloud"}
    assert backends["api_key"].kind == "secret"
    assert (backends["slots"].lo, backends["slots"].hi) == (0, 32)
    # bornée et documentée pour la console : modifiable, vide = celle du fournisseur
    assert not backends["temperature"].readonly and backends["temperature"].nullable
    assert (backends["temperature"].lo, backends["temperature"].hi) == (0.0, 2.0)
    assert backends["model"].loader == "models" and backends["api_key"].only_any
    # un champ ne se montre que s'il sert : la clé d'un service hébergé, ou de Claude Code sur une clé
    item = backends["api_key"]
    assert visible(item, {"kind": "claude"}) and visible(item, {"kind": "ollama_cloud"})
    assert not visible(item, {"kind": "ollama"})
    assert not visible(item, {"kind": "claude_code", "auth": "abonnement"})
    assert visible(item, {"kind": "claude_code", "auth": "cle_api"})
    # ce que le SDK ou la CLI savent déjà est rangé à part ; le repli se choisit parmi les autres
    assert backends["host"].advanced and backends["base_url"].advanced and backends["claude_bin"].advanced
    assert backends["fallback"].choices_from == "backends" and not backends["fallback"].advanced
    assert all(i.help for i in f["backends"].item), [i.path for i in f["backends"].item if not i.help]
    assert f["routes"].kind == "mapping"
    assert (f["context_tokens"].lo, f["context_tokens"].hi, f["context_tokens"].readonly) == (2000, 1_000_000, False)
    assert f["routes"].choices_from == "backends" and ("reply", "répondre (voix)") in f["routes"].keys


def test_real_mail_config():
    """Plusieurs comptes : une liste d'enregistrements, chacun avec ses secrets et sa voix."""
    accounts = fields_by_path(MailConfig)["accounts"]
    assert accounts.kind == "records"
    f = {i.path: i for i in accounts.item}
    assert f["password"].kind == "secret" and f["smtp_password"].kind == "secret"
    assert f["imap_ssl"].kind == "bool" and f["autodraft"].kind == "bool"
    # bornés pour la console : modifiables
    assert not f["imap_port"].readonly and (f["since_days"].lo, f["since_days"].hi) == (1, 60)
    assert {v for v, _ in f["smtp_security"].choices} == {"starttls", "ssl", "none"}
    assert {v for v, _ in f["voice"].choices} == {"elle", "assistante", "proprietaire"}
    assert f["tone"].kind == "textarea" and f["instructions"].kind == "textarea" and f["folders"].kind == "lines"


# ── flatten / nest ────────────────────────────────────────────────────────


@pytest.mark.parametrize("value", [
    Sample(),
    Sample(ratio=0.2, notes=("a", "b"), rows={"x": Row(name="x")}, weights={"a": 3}, inner=Inner(enabled=False),
           color=Color.BLUE, limit=4.0),
    PersonaDoc(traits=("curieuse",), temperament=Temperament(optimism=0.8, background=Emotion.SAD)),
    LLMConfig(backends={"main": BackendSpec(kind="claude", model="m", api_key="k")}, routes={"conversation": "main"}),
    MailConfig(accounts={"perso": MailAccount(imap_host="h", password="p", folders=("INBOX", "Pro"))}),
])
def test_flatten_nest_round_trip(value):
    flat = flatten(value)
    assert type(value).model_validate(nest(flat)) == value


def test_flatten_uses_dotted_paths_only_for_nested_models():
    flat = flatten(Sample(rows={"x": Row(name="x")}))
    assert flat["inner.tau_h"] == 6.0 and "inner" not in flat
    assert flat["rows"] == {"x": {"name": "x", "weight": 0.5}}  # un enregistrement reste une valeur
    assert flatten(PersonaDoc())["temperament.background"] == Emotion.HAPPY


def test_nest_merges_into_a_dict_value_without_mutating_it():
    rows = {"x": {"name": "x"}}
    nested = nest({"rows": rows, "rows.y": {"name": "y"}, "inner.tau_h": 2.0})
    assert nested == {"rows": {"x": {"name": "x"}, "y": {"name": "y"}}, "inner": {"tau_h": 2.0}}
    assert rows == {"x": {"name": "x"}}


def test_nest_refuses_contradictory_paths():
    with pytest.raises(PathConflict) as exc:
        nest({"count": 3, "count.x": 1})
    assert exc.value.path == "count.x"
    with pytest.raises(PathConflict):
        nest({"a..b": 1})


# ── parse ─────────────────────────────────────────────────────────────────

FIELDS = describe(Sample)
CURRENT = flatten(Sample(token="s3cret", rows={"main": Row(name="main")}))


def test_unchecked_box_is_false_only_when_rendered():
    values, errors = parse(FIELDS, form("inner.enabled"), current=CURRENT)
    assert values == {"inner.enabled": False} and errors == {}
    values, _ = parse(FIELDS, form("inner.enabled", inner__enabled="on"), current=CURRENT)
    assert values == {"inner.enabled": True}
    values, _ = parse(FIELDS, form(), current=CURRENT)  # pas affichée : pas touchée
    assert values == {}


def test_secret_blank_means_unchanged_and_effacer_clears():
    values, errors = parse(FIELDS, form("token", token=""), current=CURRENT)
    assert values == {} and errors == {}
    values, _ = parse(FIELDS, {**form("token", token=""), "_effacer": ["token"]}, current=CURRENT)
    assert values == {"token": ""}
    values, _ = parse(FIELDS, form("token", token="neuf"), current=CURRENT)
    assert values == {"token": "neuf"}


def test_numbers_accept_french_decimal_comma_and_thousands():
    values, errors = parse(FIELDS, form("ratio", "count", "step_by", ratio="0,25", count="7", step_by=" 1 000,5"),
                           current=CURRENT)
    assert errors == {} and values == {"ratio": 0.25, "count": 7, "step_by": 1000.5}
    _, errors = parse(FIELDS, form("count", "ratio", count="3,5", ratio="beaucoup"), current=CURRENT)
    assert errors == {"count": "doit être un nombre entier", "ratio": "doit être un nombre"}
    _, errors = parse(FIELDS, form("ratio", "count", ratio="nan", count=""), current=CURRENT)
    assert errors == {"ratio": "doit être un nombre fini", "count": "valeur requise"}


def test_blank_nullable_is_none():
    values, errors = parse(FIELDS, form("limit", limit=" "), current=CURRENT)
    assert values == {"limit": None} and errors == {}


def test_durations_are_read_in_the_field_unit():
    values, errors = parse(FIELDS, form("inner.settle_us", "inner.tau_h", inner__settle_us="1 h 30",
                                        inner__tau_h="18 h 12 min"), current=CURRENT)
    assert errors == {}
    assert values == {"inner.settle_us": 90 * MINUTE, "inner.tau_h": 18.2}
    assert isinstance(values["inner.settle_us"], int)
    _, errors = parse(FIELDS, form("inner.tau_h", inner__tau_h="bientôt"), current=CURRENT)
    assert errors["inner.tau_h"].startswith("durée illisible")


def test_lines_are_split_stripped_and_blank_dropped():
    values, _ = parse(FIELDS, form("notes", notes="  un  \r\n\n deux\n   \n"), current=CURRENT)
    assert values == {"notes": ("un", "deux")}


def test_select_must_be_a_choice():
    values, errors = parse(FIELDS, form("mode", "color", mode="b", color="green"), current=CURRENT)
    assert values == {"mode": "b"}
    assert errors == {"color": "choix inconnu : « green »"}
    _, errors = parse(FIELDS, form("mode", mode=""), current=CURRENT)
    assert errors == {"mode": "choisissez une valeur"}


def test_unrendered_and_readonly_fields_are_untouched():
    submitted = form("title", title="  Bonjour ", count="9", free="2", extra="{}")
    submitted["_champs"] += ["free", "extra", "rows", "inner"]
    values, errors = parse(FIELDS, submitted, current=CURRENT)
    assert values == {"title": "Bonjour"} and errors == {}  # count pas affiché, free/extra en lecture seule


def test_mapping_entries_come_as_path_dot_key():
    values, errors = parse(FIELDS, form("weights", weights__a="4", weights__b=""), current=CURRENT)
    assert values == {"weights": {"a": 4}} and errors == {}  # une clé vide est absente
    _, errors = parse(FIELDS, form("weights", weights__a="x"), current=CURRENT)
    assert errors == {"weights.a": "doit être un nombre entier"}


def test_mapping_values_chosen_from_another_dict_keys():
    values, errors = parse(FIELDS, form("routes", routes__conversation="main"), current=CURRENT)
    assert values == {"routes": {"conversation": "main"}} and errors == {}
    values, errors = parse(FIELDS, form("routes", routes__conversation="ailleurs"), current=CURRENT)
    assert values == {} and errors == {"routes.conversation": "choix inconnu : « ailleurs »"}


def test_hidden_field_is_not_written():
    # only_b n'est visible que si mode vaut « b » : sa case absente n'est pas un « non »
    values, _ = parse(FIELDS, form("only_b", "mode", mode="a"), current=CURRENT)
    assert values == {"mode": "a"}
    values, _ = parse(FIELDS, form("only_b", "mode", mode="b"), current=CURRENT)
    assert values == {"mode": "b", "only_b": False}
    values, _ = parse(FIELDS, form("inner.fast", inner__fast="on"), current=CURRENT)  # enabled vrai
    assert values == {"inner.fast": True}


def test_yaml_field_uses_the_given_loader():
    values, errors = parse(FIELDS, form("data", data='{"a": [1, 2]}'), current=CURRENT)
    assert values == {"data": {"a": [1, 2]}} and errors == {}
    _, errors = parse(FIELDS, form("data", data="a: ["), current=CURRENT)
    assert errors["data"].startswith("illisible")
    values, _ = parse(FIELDS, form("data", data="x"), current=CURRENT, load=lambda text: {text: []})
    assert values == {"data": {"x": []}}


@pytest.mark.parametrize("path, value", [
    ("ratio", 0.25), ("count", 7), ("title", "Salut"), ("mode", "b"), ("notes", ("un", "deux")),
    ("inner.settle_us", 90 * MINUTE), ("inner.tau_h", 18.2), ("inner.enabled", True), ("inner.enabled", False),
    ("limit", None), ("color", Color.BLUE), ("data", {"a": [1]}),
])
def test_as_text_then_parse_round_trips(path, value):
    f = fields_by_path(Sample)[path]
    text = as_text(f, value)
    submitted = form(path, **({path.replace(".", "__"): text} if text else {}))
    values, errors = parse(FIELDS, submitted, current=CURRENT)
    assert errors == {}
    expected = value.value if isinstance(value, enum.Enum) else value
    assert values[path] == expected


def test_a_secret_is_never_shown():
    assert as_text(fields_by_path(Sample)["token"], "s3cret") == ""


# ── within ────────────────────────────────────────────────────────────────


def test_within_checks_bounds_in_french():
    assert within(FIELDS, {"ratio": 0.5, "count": 10}) == {}
    assert within(FIELDS, {"ratio": 1.5, "count": -1, "inner.tau_h": 0.25}) == {
        "ratio": "doit être entre 0 et 1",
        "count": "doit être entre 0 et 10",
        "inner.tau_h": "doit être entre 30 min et 2 j",
    }
    lone = [f for f in describe(LLMConfig) if f.path == "context_tokens"]
    assert within(lone, {"context_tokens": 100}) == {"context_tokens": "doit être entre 2000 et 1000000"}


def test_within_checks_mapping_values_and_ignores_the_rest():
    assert within(FIELDS, {"weights": {"a": 12, "b": 3}}) == {"weights.a": "doit être entre 0 et 9"}
    assert within(FIELDS, {"title": "x", "limit": None, "unknown": 5}) == {}


def test_within_formats_french_decimals():
    field = fields_by_path(Inner)["tau_h"]
    assert within([field], {"tau_h": 100.0}) == {"tau_h": "doit être entre 30 min et 2 j"}
    bare = FormField(path="x", label="", help="", group="", kind="float", advanced=True, secret=False,
                     readonly=False, required=False, default=None, lo=0.5, hi=1.5, step=None, unit="",
                     choices=(), loader="", subject="", only=(), order=100)
    assert within([bare], {"x": 2}) == {"x": "doit être entre 0,5 et 1,5"}


# ── validate ──────────────────────────────────────────────────────────────


def test_validate_merges_dotted_changes():
    base = Sample()
    new, errors = validate(Sample, base, {"inner.tau_h": 2.0, "ratio": 0.1, "notes": ("a",)})
    assert errors == {}
    assert new == base.model_copy(update={"inner": Inner(tau_h=2.0), "ratio": 0.1, "notes": ("a",)})


def test_validate_adds_a_record_under_a_dict_field():
    cfg = LLMConfig(backends={"main": BackendSpec(kind="claude", model="m")})
    new, errors = validate(LLMConfig, cfg, {"backends.local": {"kind": "ollama", "model": "g"}})
    assert errors == {} and set(new.backends) == {"main", "local"}


def test_validate_reports_french_errors_by_path():
    new, errors = validate(Sample, Sample(), {
        "inner.nope": 1, "count": "beaucoup", "mode": "c", "limit": 500, "color": "green", "body": "c'est interdit",
    })
    assert new is None
    assert errors == {
        "inner.nope": "champ inconnu",
        "count": "doit être un nombre entier",
        "mode": "doit être l'une des valeurs : 'a', 'b'",
        "limit": "doit être inférieur ou égal à 100",
        "color": "doit être l'une des valeurs : 'red', 'blue'",
        "body": "valeur refusée : mot interdit",
    }


def test_validate_reports_path_conflicts():
    new, errors = validate(Sample, Sample(), {"count.x": 1})
    assert new is None and "count.x" in errors


def test_errors_fr_covers_common_types():
    class Strict(BaseModel):
        model_config = ConfigDict(extra="forbid")
        n: int = Field(ge=1)
        x: float = Field(gt=0, lt=1)
        s: str = Field(max_length=2)
        t: tuple[str, ...] = Field(default=(), max_length=1)
        req: str
        when: dict[str, int] = Field(default_factory=dict)

    with pytest.raises(ValidationError) as exc:
        Strict.model_validate({"n": 0, "x": 1.5, "s": "abc", "t": ("a", "b"), "when": {"k": "v"}, "zz": 1})
    assert errors_fr(exc.value) == {
        "n": "doit être supérieur ou égal à 1",
        "x": "doit être strictement inférieur à 1",
        "s": "trop long : 2 caractères au plus",
        "t": "trop long : 1 éléments au plus",
        "req": "valeur requise",
        "when.k": "doit être un nombre entier",
        "zz": "champ inconnu",
    }


def test_errors_fr_unknown_type_keeps_pydantic_message():
    class Dated(BaseModel):
        at: complex = 0j

    with pytest.raises(ValidationError) as exc:
        Dated.model_validate({"at": "pas un complexe"})
    message = errors_fr(exc.value)["at"]
    assert message.startswith("valeur invalide (") and exc.value.errors()[0]["msg"] in message


# ── Durées ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("text, us", [
    ("10 min", 10 * MINUTE), ("2 h", 2 * HOUR), ("90 s", 90_000_000), ("1 h 30", 90 * MINUTE),
    ("1.5h", 90 * MINUTE), ("1,5 h", 90 * MINUTE), ("250 ms", 250_000), ("3 j 2 h", 74 * HOUR),
    ("1h30m", 90 * MINUTE), ("2 min 30", 150_000_000), ("1 s 500", 1_500_000), ("12 µs", 12),
    ("0", 0), ("  45 secondes ", 45_000_000), ("1 H", HOUR), ("2 jours", 48 * HOUR),
])
def test_parse_duration(text, us):
    assert parse_duration(text) == us


@pytest.mark.parametrize("text, message", [
    ("", "durée vide"), ("-1 h", "négative"), ("10 lunes", "unité inconnue"), ("45", "précisez l'unité"),
    ("30 min 1 h", "désordre"), ("1 h 1 h", "répétées"), ("demain", "durée illisible"),
    ("1 h et 30", "durée illisible"), ("10 30 min", "précisez l'unité"),
])
def test_parse_duration_refuses_in_french(text, message):
    with pytest.raises(ValueError, match=message):
        parse_duration(text)


@pytest.mark.parametrize("us, text", [
    (90 * MINUTE, "1 h 30 min"), (45_000_000, "45 s"), (74 * HOUR, "3 j 2 h"), (0, "0 s"),
    (1_500_250, "1 s 500 ms 250 µs"), (-HOUR, "-1 h"),
])
def test_show_duration(us, text):
    assert show_duration(us) == text


@settings(max_examples=300, deadline=None)
@given(st.integers(min_value=0, max_value=10**15))
def test_show_then_parse_round_trips(us):
    assert parse_duration(show_duration(us)) == us


@settings(max_examples=200, deadline=None)
@given(st.lists(st.integers(min_value=0, max_value=999), min_size=6, max_size=6))
def test_parse_then_show_is_canonical(parts):
    names = ("j", "h", "min", "s", "ms", "µs")
    text = " ".join(f"{n} {u}" for n, u in zip(parts, names, strict=True))
    us = parse_duration(text)
    assert parse_duration(show_duration(us)) == us
    assert show_duration(parse_duration(show_duration(us))) == show_duration(us)


# ── Un Knob ne change rien au rejeu ───────────────────────────────────────


class Plain(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    x: float = 0.5
    n: int = Field(default=3, ge=0)
    names: tuple[str, ...] = ()
    inner: Inner = Inner()


class Knobbed(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    x: Annotated[float, Knob(lo=0, hi=1, widget="slider", label="X")] = 0.5
    n: Annotated[int, Field(ge=0), Knob(lo=1, hi=2)] = 3
    names: Annotated[tuple[str, ...], Knob(widget="lines")] = ()
    inner: Annotated[Inner, Knob(label="Intérieur", advanced=False)] = Inner()


@pytest.mark.parametrize("data", [
    {}, {"x": 5.0}, {"x": -3, "n": 99}, {"names": ["a", "b"]}, {"inner": {"tau_h": 1000}},
    {"n": -1}, {"x": "pas un nombre"}, {"extra": 1},
])
def test_knob_leaves_validation_and_dumps_unchanged(data):
    try:
        plain = Plain.model_validate(data)
    except ValidationError as exc:
        with pytest.raises(ValidationError) as other:
            Knobbed.model_validate(data)
        assert other.value.errors(include_url=False) == exc.errors(include_url=False)
        return
    knobbed = Knobbed.model_validate(data)
    assert knobbed.model_dump_json() == plain.model_dump_json()
    assert Knobbed.model_validate_json(plain.model_dump_json()) == knobbed


def test_knob_is_absent_from_the_json_schema():
    plain, knobbed = Plain.model_json_schema(), Knobbed.model_json_schema()
    plain.pop("title"), knobbed.pop("title")
    assert knobbed == plain
