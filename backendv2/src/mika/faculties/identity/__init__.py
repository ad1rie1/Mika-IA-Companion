"""``identity`` : qui est derrière chaque adresse, et ce que ça ouvre.

- Une adresse parle **pour elle-même** : sur un transport qui prouve le
  compte (session, message privé d'un compte extérieur), elle est sûre de sa
  continuité ; sur un transport qui ne prouve rien (navigateur sans compte),
  de rien.
- Quelqu'un peut **dire être** une autre personne qu'elle connaît (« moi c'est
  Alice », sur un nouveau compte) : c'est une revendication, notée, qui
  n'ouvre rien. Elle devient une **liaison** quand ce que l'adresse dit
  recoupe ce que seule Alice pouvait savoir — sur deux messages espacés, pas
  celui où elle se présente, dont un avec un détail rare (``corroboration``,
  ``reading``) —, ou quand un opérateur les relie. Une affirmation seule ne
  franchit jamais la barre. Une liaison par recoupement reste « à confirmer » :
  le fil verbatim des autres adresses lui reste fermé jusque-là.
- Une **phrase banale** ne délie ni ne renomme : se donner un autre nom sur une
  adresse liée ou nommée est une revendication, rien de plus.
- Un **démenti** (« je ne suis pas Alice ») s'applique tout de suite ; il ne
  compte que contre un nom sous lequel elle connaît la personne.
- Les **droits d'une propriétaire** tiennent à l'adresse qui parle
  (``SPEAKS_AS_OWNER``), jamais dans un salon public.
- Le modèle ne peut que **douter** ou **oublier** une liaison (outils) :
  jamais faire monter la confiance.

Dans le doute, tout se ferme (ADR 0012, 0035).
"""

from mika.faculties.identity import actions, inspect, reading, tools  # noqa: F401 — contributions
from mika.faculties.identity.faculty import (
    IDENTITY,
    Claim,
    Handle,
    IdentityParams,
    IdentityState,
    _apply,
    handles_of,
    known_as,
    resolve_target,
    view_of,
)
from mika.faculties.identity.prompt import acquaintance, audience_for, describe
from mika.faculties.identity.reading import _candidates

__all__ = [
    "IDENTITY", "Claim", "Handle", "IdentityParams", "IdentityState", "_apply", "_candidates", "acquaintance",
    "audience_for", "describe", "handles_of", "known_as", "resolve_target", "view_of",
]
