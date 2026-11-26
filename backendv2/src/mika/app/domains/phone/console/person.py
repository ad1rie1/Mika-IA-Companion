"""La part du téléphone dans la fiche d'une personne (ADR 0310) : l'onglet Son téléphone (ADR 0120, 0123), ses
conversations et les réponses qu'elle a proposées. Les mêmes morceaux que Ses sens › Messages du téléphone
(``app/domains/senses/console/tabs.py``), restreints à cette personne.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from markupsafe import Markup

from mika.app.domains.domain import PersonPart
from mika.app.domains.senses.console.tabs import (
    conversation_of,
    offers_of,
    reader_of,
    slice_of,
)
from mika.app.handmade import Look
from mika.inspector.ui import UI, env
from mika.kernel.clock import DAY
from mika.plugins.phone.inspect import PER_THREAD, threads


def phone_tab(ui: UI, key: str, blocks: Sequence[Any], query: Mapping[str, str],
              forms: Mapping[str, Any] | None = None) -> Markup | None:
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


#: sa part de la fiche d'une personne (ADR 0310)
PERSON_PART = PersonPart(
    # ce que son téléphone lui a montré (seulement s'il en a dit quelque chose)
    tabs={"telephone": phone_tab})
