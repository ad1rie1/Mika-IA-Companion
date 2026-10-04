"""Une politique, pour les gens (ADR 0035) : ce qu'``identity``, ``social`` et
``others`` gardent d'une personne en clair, dans l'enveloppe du journal, est
compté.

L'oubli efface les contenus d'un sujet ; une chaîne gardée en clair dans une
charge utile lui échappe. C'est ainsi que le ton, les intérêts et les sujets
délicats d'un profil, ou la note d'un opérateur au registre des preuves,
restaient au journal après « Oublier ». Chaque champ texte de leurs événements
est donc soit un ``Content`` (effaçable), soit une étiquette écrite par le code
(une clé, une sorte), soit un héritage d'avant la version qui l'a rangé à part —
chacun nommé ici avec sa raison. Un champ texte nouveau échoue tant qu'on ne l'a
pas rangé.
"""

from __future__ import annotations

import typing

from mika.app.composition import faculties
from mika.kernel.events import Content
from mika.kernel.registry import Registry
from mika.runtime.state import RUNTIME

OWNERS = ("identity", "social", "others")

#: les champs texte en clair permis, par événement, et pourquoi
PLAIN = {
    "identity.claimed": {
        "handle": "une adresse (une clé)",
        "name": "le nom revendiqué : l'identité en a besoin pour reconnaître (comme le nom d'affichage du transport)",
        "target": "une clé de personne",
    },
    "identity.evidence": {
        "handle": "une adresse", "kind": "une sorte de preuve (code)", "by": "qui l'a versée (code)",
        "denies": "ce que vise un démenti (code)", "about": "des clés de personnes",
        "legacy_name": "héritage : avant la version 2, le nom démenti était en clair",
        "legacy_note": "héritage : avant la version 2, la note était en clair",
    },
    "identity.linked": {"handle": "une adresse", "person": "une clé de personne", "by": "qui (code)"},
    "identity.registered": {"handle": "une adresse", "name": "le nom du compte (un réglage de la console)",
                            "messaging": "un nom de canal (``mobile``), jamais un texte sur la personne"},
    "identity.name_bound": {"name": "une clé de personne connue de nom (``name:alice``, celle de la mémoire)",
                            "person": "une clé de personne", "by": "qui (code)"},
    "social.profile_revised": {
        "person": "une clé de personne", "call_id": "un identifiant d'appel", "model": "un nom de modèle",
        "legacy_tone": "héritage : avant la version 2, le ton était en clair",
        "legacy_interests": "héritage : avant la version 2, les intérêts étaient en clair",
        "legacy_sensitive": "héritage : avant la version 2, les sujets délicats étaient en clair",
    },
    "social.closeness_set": {"person": "une clé de personne", "closeness": "un niveau (code)", "by": "qui"},
    "social.one_sided": {
        "source": "la source (code)", "kind": "une sorte (code)", "emotion": "une émotion (code)",
        "about": "des clés de personnes", "bundle": "un lot d'outils (code)",
    },
    "others.read": {
        "person": "une clé de personne", "handle": "une adresse",
        "cues": "des indices écrits par le code, jamais le texte du message",
        "contagion_emotion": "une émotion (code)",
    },
}


def _texts(annotation: typing.Any) -> bool:
    """Le type porte-t-il une chaîne (directement, dans un tuple, ou optionnelle) ?"""
    if annotation is str:
        return True
    return any(_texts(a) for a in typing.get_args(annotation))


def _contents(annotation: typing.Any) -> bool:
    if annotation is Content:
        return True
    return any(_contents(a) for a in typing.get_args(annotation))


def test_every_plain_text_of_people_is_accounted_for():
    registry = Registry([RUNTIME, *faculties()])
    unaccounted = []
    for t in registry.events.all():
        if t.owner not in OWNERS:
            continue
        hints = typing.get_type_hints(t.payload)
        for name, annotation in hints.items():
            if _contents(annotation):
                assert name in t.content_fields, f"{t.name}.{name} est un Content non déclaré comme tel"
                continue
            if _texts(annotation) and name not in PLAIN.get(t.name, {}):
                unaccounted.append(f"{t.name}.{name}")
    assert unaccounted == [], f"du texte en clair, que l'oubli n'atteint pas : {unaccounted}"


def test_the_profile_and_the_ledger_keep_their_words_apart():
    """Les deux trous de l'audit (MEM-6, CON-12) : rangés à part, et sujets à l'oubli."""
    registry = Registry([RUNTIME, *faculties()])
    profile = registry.events.get("social.profile_revised")
    evidence = registry.events.get("identity.evidence")
    assert {"summary", "tone", "interests", "sensitive"} <= profile.content_fields
    assert {"name", "note"} <= evidence.content_fields
    assert profile.subject_fields and {"handle", "about"} <= evidence.subject_fields


def test_the_allowances_name_real_fields():
    registry = Registry([RUNTIME, *faculties()])
    for name, fields in PLAIN.items():
        t = registry.events.get(name)
        assert set(fields) <= set(typing.get_type_hints(t.payload)), name
