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
