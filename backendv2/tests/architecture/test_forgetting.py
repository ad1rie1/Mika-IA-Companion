"""Une politique : tout texte gardé dit qui il concerne.

``mika forget <personne>`` efface les contenus dont cette personne est un
sujet. Un événement qui porte du texte libre sans déclarer de sujet échappe
donc à l'oubli — c'est ainsi que les résumés de pas, les notes de carnet, les
effets proposés et son récit d'elle-même gardaient les mots d'une personne
oubliée. Seuls les événements du monde (un titre de flux, un appareil, une
app) en sont dispensés, chacun avec sa raison.
"""

from __future__ import annotations

from mika.app.composition import faculties
from mika.kernel.registry import Registry
from mika.runtime.state import RUNTIME

#: du texte qui vient du monde, pas d'une personne — et pourquoi
WORLD = {
    "rss.noticed": "un titre d'article : public",
    "sensors.sensed": "un appareil (une sonnette) : pas une personne identifiée",
    "forge.signaled": "une app forgée : elle ne reçoit jamais une conversation",
    "camera.seen": "une image décrite : personne n'y est identifié ; réservée aux propriétaires",
}


def test_every_kept_text_names_who_it_concerns():
    registry = Registry([RUNTIME, *faculties()])
    missing = sorted(t.name for t in registry.events.all() if t.content_fields and not t.subject_fields
                     and t.name not in WORLD)
    assert missing == [], f"du texte sans sujet échappe à l'oubli : {missing}"


def test_the_world_exemptions_are_real_events():
    registry = Registry([RUNTIME, *faculties()])
    names = {t.name for t in registry.events.all()}
    assert set(WORLD) <= names


def test_declared_subjects_are_fields_of_the_payload():
    """Un sujet mal orthographié ne nommerait personne : le texte échapperait à l'oubli."""
    registry = Registry([RUNTIME, *faculties()])
    wrong = sorted((t.name, f) for t in registry.events.all() for f in t.subject_fields
                   if f not in t.payload.model_fields)
    assert wrong == [], f"sujets qui ne sont pas des champs : {wrong}"


#: Les champs textuels des événements de la mémoire qui ne sont pas des contenus : des clés de
#: personne, des états, des noms — jamais des mots de quelqu'un (ceux-là sont des ``Content``, qui
#: déclarent leurs sujets ; un nouveau champ de texte libre doit en être un).
MEMORY_KEYS = {"origin", "source", "call_id", "status", "by", "model", "night", "to", "emotion", "about", "told_by",
               "heard_by"}


def test_memory_keeps_no_free_text_outside_its_contents():
    registry = Registry([RUNTIME, *faculties()])
    loose = sorted(f"{t.name}.{name}" for t in registry.events.all() if t.owner == "memory"
                   for name, field in t.payload.model_fields.items()
                   if name not in t.content_fields and "str" in str(field.annotation) and name not in MEMORY_KEYS)
    assert loose == [], f"du texte hors d'un contenu : {loose}"


def test_what_someone_confided_is_forgotten_with_them():
    """Ce que Bob a confié sur Alice porte Bob parmi ses sujets : l'oublier l'efface."""
    registry = Registry([RUNTIME, *faculties()])
    kept = {t.name: t for t in registry.events.all() if t.owner == "memory" and t.content_fields}
    missing = sorted(n for n, t in kept.items() if "told_by" in t.payload.model_fields
                     and "told_by" not in t.subject_fields)
    assert missing == [], missing
