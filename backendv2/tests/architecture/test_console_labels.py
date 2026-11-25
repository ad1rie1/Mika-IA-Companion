"""Tout ce que la composition déclare, la console le nomme (ADR 0042).

Une section, une raison, un veto, un processus, un événement, un effet de la file de sortie, un
enrichisseur ou un port qu'un outil attend, qu'une faculté ajoute sans le nommer dans ``app/console.py``, se lit sous
une forme générique (« Liens · reciprocity », « step_origin » dans « Pourquoi a-t-elle dit
ça ? », « « imaging » n'est pas configuré ») : la promesse
de l'ADR 0042 ne tenait que par vigilance. Ce garde confronte le registre de la
composition réelle aux tables ; il échoue dès qu'une clé manque, ou qu'un libellé
nomme ce qui n'existe plus.

Les vetos ne sont pas déclarés au registre (une modulation les rend à la volée) :
ils sont lus dans le code, par l'AST, là où une modulation les pose — directement
(``Modulation(veto=c.ASLEEP)``) ou par une fonction du même module qui rend le veto
(``veto = harassing(…)`` : ce que ``harassing`` peut rendre).

Le murmure (``expression.why()``, ``expression.murmur.why`` dans sa voix) dit en clair ce qui la pousse à écrire : chaque
raison d'une initiative y a sa phrase, sauf celles qui ne sont pas un motif.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

from mika.app import console
from mika.app.composition import READING, arbitration, faculties
from mika.app.handmade.tabs.system import PROJECTIONS
from mika.contracts import agency as agency_c
from mika.contracts import body as body_c
from mika.contracts import camera as camera_c
from mika.contracts import email as email_c
from mika.contracts import rss as rss_c
from mika.contracts import social as social_c
from mika.contracts import teams as teams_c
from mika.faculties.expression import why
from mika.inspector.names import CONTENT_FIELDS, OTHER_EFFECTS
from mika.inspector.names import EVENTS as CONSOLE_EVENTS
from mika.kernel.registry import Registry
from mika.runtime.state import RUNTIME
from mika.vocab.episodes import Kind

SRC = Path(__file__).resolve().parents[2] / "src" / "mika"
#: ce qui pose des vetos : les facultés et les plugins (le noyau n'en pose pas)
VETO_ROOTS = (SRC / "faculties", SRC / "plugins")
#: des raisons d'initiative qui ne sont pas un motif à murmurer : pas de murmure avant une salutation (et
#: « quelqu'un de présent » l'accompagne), et se raviser est une retenue
NOT_A_MOTIVE = frozenset({social_c.GREETING, social_c.PRESENT_PERSON, agency_c.SECOND_THOUGHTS})


def _registry() -> Registry:
    return Registry([RUNTIME, *faculties()], arbitration=arbitration())


def _declared() -> dict[str, set[str]]:
    reg = _registry()
    out: dict[str, set[str]] = {"faculties": set(), "sections": set(), "reasons": set(), "processes": set(),
                                "events": set(), "initiative_reasons": set(), "enrichers": set()}
    for f in reg.faculties.values():
        out["faculties"].add(f.name)
        out["sections"] |= {s.key for s in f.sections}
        out["enrichers"] |= {s.key for s in f.enrichers}
        for p in f.proposers:
            out["reasons"] |= set(p.reasons)
            if Kind.INITIATIVE in p.kinds:
                out["initiative_reasons"] |= set(p.reasons)
        out["processes"] |= {p.name for p in f.processes}
        out["events"] |= {e.name for e in f.events.values()}
    return out


def _aliases(tree: ast.Module) -> dict[str, str]:
    """Les modules importés par alias (``from mika.contracts import agency as c`` → ``c`` : le module)."""
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("mika."):
            for a in node.names:
                out[a.asname or a.name] = f"{node.module}.{a.name}"
    return out


def _value(node: ast.AST, aliases: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in aliases:
        got = getattr(importlib.import_module(aliases[node.value.id]), node.attr, None)
        return got if isinstance(got, str) else None
    return None


def _vetoes() -> dict[str, str]:
    """Chaque veto que le code peut poser, et où (pour le message d'échec)."""
    found: dict[str, str] = {}
    for root in VETO_ROOTS:
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            aliases = _aliases(tree)
            functions = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
            for fn in functions.values():
                for call in (n for n in ast.walk(fn) if isinstance(n, ast.Call)):
                    for kw in call.keywords:
                        if kw.arg != "veto":
                            continue
                        candidates: list[ast.AST] = [kw.value]
                        if isinstance(kw.value, ast.Name):  # ``veto = harassing(…)`` : ce que la fonction rend
                            for assign in (n for n in ast.walk(fn) if isinstance(n, ast.Assign)):
                                if any(isinstance(t, ast.Name) and t.id == kw.value.id for t in assign.targets) \
                                        and isinstance(assign.value, ast.Call) \
                                        and isinstance(assign.value.func, ast.Name) \
                                        and assign.value.func.id in functions:
                                    callee = functions[assign.value.func.id]
                                    candidates += [r.value for r in ast.walk(callee)
                                                   if isinstance(r, ast.Return) and r.value is not None]
                        for c in candidates:
                            v = _value(c, aliases)
                            if v is not None:
                                found.setdefault(v, f"{path.relative_to(SRC)}:{getattr(c, 'lineno', 0)}")
    return found


def test_every_section_reason_process_event_and_faculty_is_named():
    """Les enrichisseurs aussi : sans libellé, l'onglet Prompt d'un épisode montrait leur clé (« their_last_words »)."""
    d = _declared()
    named_events = set(console.EVENT_LABELS) | set(CONSOLE_EVENTS)
    missing = {
        "sections": sorted(d["sections"] - set(console.SECTION_LABELS)),
        "raisons": sorted(d["reasons"] - set(console.REASON_LABELS)),
        "processus": sorted(d["processes"] - set(console.PROCESS_LABELS)),
        "événements": sorted(d["events"] - named_events),
        "facultés": sorted(d["faculties"] - set(console.FACULTY_LABELS)),
        "enrichisseurs": sorted(d["enrichers"] - set(console.ENRICHER_LABELS)),
    }
    assert not any(missing.values()), f"à nommer dans app/console.py : {missing}"
    # la vague en cours en a ajouté : nommés eux aussi
    assert {"habits"} <= set(console.SECTION_LABELS) and {"follow_up"} <= set(console.REASON_LABELS)


def test_every_projection_is_named_and_no_name_is_stale():
    """Santé générale montre chaque projection sous un nom en clair (``PROJECTIONS`` de ``app/handmade/tabs/system.py``) :
    sans lui, celle des fils de travail du mode pro se lisait « strands · v1 » (audit du 2026-11-05, C8-09). Les noms
    viennent de la composition, pas de la déclaration de la projection : un mot de console n'a rien à faire dans une
    faculté."""
    declared = set(Registry([RUNTIME, *faculties()], reading=READING).projectors)
    missing, stale = sorted(declared - set(PROJECTIONS)), sorted(set(PROJECTIONS) - declared)
    assert not missing, f"à nommer dans app/handmade/tabs/system.py (PROJECTIONS) : {missing}"
    assert not stale, f"noms sans objet dans app/handmade/tabs/system.py (PROJECTIONS) : {stale}"


def test_every_effect_of_the_outbox_is_named_and_no_name_is_stale():
    """Système › File de sortie, sa vue et la page d'un événement nomment chaque effet par les mots de la composition
    (``EFFECT_LABELS`` de ``app/console.py``, lus par ``Names.effect``). Ils étaient tenus à la main en deux endroits
    (la page dessinée et la vue), et la demande de pilotage acceptée (``projects:effect.executed``) n'en avait pas :
    elle tombait dans « Le reste » sous un nom générique (audit du 2026-11-05, C8-R3). Chaque effet du registre composé
    (« propriétaire:type », la clé des lignes de la file) a son nom, aucun nom ne vise un effet qui n'existe plus, et
    chaque famille est l'une de celles que la page range."""
    declared = {f"{s.owner}:{s.type.name}" for specs in _registry().effects.values() for s in specs}
    assert {"projects:effect.executed", "expression:episode.utterance"} <= declared  # le garde voit les facultés
    missing = sorted(declared - set(console.EFFECT_LABELS))
    stale = sorted(set(console.EFFECT_LABELS) - declared)
    assert not missing, f"effets à nommer dans app/console.py (EFFECT_LABELS) : {missing}"
    assert not stale, f"noms sans objet dans app/console.py (EFFECT_LABELS) : {stale}"
    families = [key for key, _title in console.EFFECT_FAMILIES]
    assert len(families) == len(set(families)) and OTHER_EFFECTS in families
    strays = {k: f for k, (f, _name, _what) in console.EFFECT_LABELS.items() if f not in families}
    assert not strays, f"familles inconnues de EFFECT_FAMILIES : {strays}"
    assert all(name and what for _f, name, what in console.EFFECT_LABELS.values())
    assert console.LABELS.effects is console.EFFECT_LABELS


def test_every_content_field_of_an_event_is_named_and_no_name_is_stale():
    """La page d'un événement titre ses textes par leur champ : sans libellé, elle montrait « text », « summary »,
    « coords » (C5-04). Les champs de contenu se nomment dans ``inspector/names.py`` (``CONTENT_FIELDS``) : ce sont
    des clés génériques, pas une faculté."""
    reg = _registry()
    declared = {f for fac in reg.faculties.values() for e in fac.events.values() for f in e.content_fields}
    missing, stale = sorted(declared - set(CONTENT_FIELDS)), sorted(set(CONTENT_FIELDS) - declared)
    assert not missing, f"à nommer dans inspector/names.py (CONTENT_FIELDS) : {missing}"
    assert not stale, f"libellés sans objet dans inspector/names.py (CONTENT_FIELDS) : {stale}"


def test_no_label_names_something_that_no_longer_exists():
    """Un libellé orphelin cache une clé renommée (la nouvelle, elle, se lit sous sa forme générique)."""
    d = _declared()
    stale = {
        "sections": sorted(set(console.SECTION_LABELS) - d["sections"]),
        "raisons": sorted(set(console.REASON_LABELS) - d["reasons"]),
        "processus": sorted(set(console.PROCESS_LABELS) - d["processes"]),
        "événements": sorted(set(console.EVENT_LABELS) - d["events"]),
        "enrichisseurs": sorted(set(console.ENRICHER_LABELS) - d["enrichers"]),
    }
    assert not any(stale.values()), f"libellés sans objet dans app/console.py : {stale}"


def test_every_port_a_tool_needs_is_named_with_its_settings_page():
    """La fiche d'un outil qui attend un port pas prêt disait « non — « imaging » n'est pas configuré » : la clé du
    port, sans dire où le régler (C6-04). Chaque port qu'un outil du registre composé déclare (``needs=``) a sa phrase
    et la page de réglages qui le règle dans ``app/console.py`` (``NEED_LABELS``) ; aucun libellé ne nomme un port
    qu'aucun outil n'attend plus."""
    declared = {spec.needs for spec in _registry().tools.values() if spec.needs}
    assert {"imaging", "maps"} <= declared  # le garde voit les outils des plugins
    missing, stale = sorted(declared - set(console.LABELS.needs)), sorted(set(console.LABELS.needs) - declared)
    assert not missing, f"ports à nommer dans app/console.py (NEED_LABELS) : {missing}"
    assert not stale, f"libellés sans objet dans app/console.py (NEED_LABELS) : {stale}"
    for port, (said, page) in console.LABELS.needs.items():
        # une phrase, pas la clé du port, et une page où le régler (qu'elle existe : tests/protocol/test_console_tools.py)
        assert said and port not in said and page, port


def test_the_kinds_of_signal_a_domain_emits_are_named_by_its_card():
    """La sorte d'un signal (un mail, un message Teams, un article, ce que voit la caméra) est dite en mots dans la
    fiche de son domaine (``labels["signals"]``), par sa valeur : si la constante de son contrat changeait, Ses
    pensées › Ce qu'elle remarque montrerait son nom brut."""
    kinds = (email_c.MAIL, email_c.SENT_KIND, teams_c.MESSAGE, teams_c.SENT_KIND, rss_c.ENTRY, camera_c.VIEW)
    assert not [k for k in kinds if k not in console.SIGNAL_LABELS]


def test_every_veto_the_code_can_set_is_named():
    vetoes = _vetoes()
    assert {body_c.ASLEEP, agency_c.UNANSWERED, agency_c.AWAITING_REPLY} <= set(vetoes)  # le garde voit loin
    missing = {v: where for v, where in vetoes.items() if v not in console.VETO_LABELS}
    assert not missing, f"vetos à nommer dans app/console.py (VETO_LABELS) : {missing}"


def test_the_murmur_says_why_for_every_motive_of_an_initiative():
    """« lui dire un mot » : le murmure d'une initiative dont le motif n'avait pas de phrase (« j'ai besoin de toi »
    pour un projet)."""
    motives = _declared()["initiative_reasons"] - NOT_A_MOTIVE
    assert motives, "aucune raison d'initiative lue"
    said = set(why())
    assert not sorted(motives - said), f"raisons sans phrase dans expression.murmur.why : {sorted(motives - said)}"
