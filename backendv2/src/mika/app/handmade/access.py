"""Ce que partagent les tableaux de lignes d'accès dessinés (ADR 0131, 0133) — d'un service (``servers.py``), d'un
projet (``projects.py``) — et la page « Droits » (``rights.py``) : les personnes qu'une ligne peut nommer, et ses
sources à cocher."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from mika.contracts import identity as identity_c
from mika.faculties.identity.faculty import known_as
from mika.faculties.identity.inspect import people as people_of
from mika.inspector.ui import UI
from mika.vocab.access import PERSON, SOURCE_WORDS, SOURCES, who_words
from mika.vocab.people import ACCOUNT_PREFIX


def people_with_accounts(ui: UI) -> list[dict[str, str]]:
    """Les personnes qu'une ligne peut nommer : celles qui ont un compte (seules à pouvoir être authentifiées), par
    leur nom — jamais une propriétaire, que sa source à elle (« Toi ») désigne déjà."""
    frame = ui.kernel.mind.frame()
    try:
        s = frame.state("identity")
    except KeyError:
        return []
    out = [{"key": person, "name": known_as(s, person)} for person, handles in people_of(s, frame).items()
           if any(str(h).startswith(ACCOUNT_PREFIX) for h in (*handles, person))
           and not frame.get(identity_c.IS_OWNER(person))]
    return sorted(out, key=lambda p: p["name"].casefold())


def who_choices(who: Sequence[str], people: Sequence[dict[str, str]], name: Callable[[str], str]) -> dict[str, Any]:
    """Les cases « qui » d'une ligne : ses sources, puis les personnes qui ont un compte ; une personne qu'elle coche
    et qui n'a plus de compte reste là, cochée, pour qu'on puisse la décocher. Chaque case porte aussi son mot dans
    ``who_words`` (``word``), que la console recompose quand on coche."""
    got = set(who)
    boxes = [{"value": k, "label": label, "word": SOURCE_WORDS[k], "on": k in got} for k, label in SOURCES]
    listed = {PERSON + p["key"] for p in people}
    boxes += [{"value": PERSON + p["key"], "label": p["name"], "word": p["name"], "on": PERSON + p["key"] in got}
              for p in people]
    boxes += [{"value": w, "label": name(w[len(PERSON):]), "word": name(w[len(PERSON):]), "on": True}
              for w in sorted(got) if w.startswith(PERSON) and w not in listed]
    return {"boxes": boxes, "said": who_words(who, name) if who else "Personne"}
