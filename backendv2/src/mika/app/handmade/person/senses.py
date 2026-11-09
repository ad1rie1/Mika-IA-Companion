"""La fiche d'une personne › Son téléphone et Sa position, dessinées (ADR 0119, 0120, 0123) : ses conversations et les
réponses qu'elle a proposées ; sa dernière position, téléphone par téléphone, et son journal. Les mêmes morceaux que les
pages de Connexions extérieures (``tabs/senses.py``), restreints à cette personne.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from markupsafe import Markup

from mika.app.handmade import Look
from mika.app.handmade.tabs.senses import conversation_of, fix_of, offers_of, reader_of, said_of, slice_of
from mika.inspector.pages.subjects import fiche_url
from mika.inspector.ui import UI, env
from mika.kernel.clock import DAY
from mika.plugins.location.inspect import by_person
from mika.plugins.phone.inspect import PER_THREAD, threads


def phone_tab(ui: UI, key: str, blocks: Sequence[Any], query: Mapping[str, str]) -> Markup | None:
    """La fiche d'une personne › Son téléphone : ses conversations, les réponses qu'elle a proposées."""
    look = Look.of(ui, DAY)
    s = slice_of(look, "phone")
    if s is None:
        return None
    convs = threads([m for m in s.messages.values() if m.person == key])
    offers = sorted((o for o in s.offers.values() if o.person == key), key=lambda o: -o.seq)[:60]
    text = reader_of(look, [m for t in convs for m in t[:PER_THREAD]], offers)
    return Markup(env.get_template("handmade/person/tabs/telephone.html").render(
        conversations=[conversation_of(look, t, text, look.name(key)) for t in convs], offers=offers_of(look, offers, text),
        name=look.name(key)))


def position_tab(ui: UI, key: str, blocks: Sequence[Any], query: Mapping[str, str]) -> Markup | None:
    """La fiche d'une personne › Sa position : sa dernière position, téléphone par téléphone, et son journal."""
    look = Look.of(ui, DAY)
    s = slice_of(look, "location")
    if s is None:
        return None
    fixes = by_person(s).get(key, [])
    texts = look.texts([r for f in fixes for r in (f.coords_ref, f.label_ref)])
    said = said_of(look, query, key, fiche_url("person", key, "position"))
    return Markup(env.get_template("handmade/person/tabs/position.html").render(
        fixes=[fix_of(look, f, texts) for f in fixes], said=said, name=look.name(key)))
