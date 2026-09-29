"""``identity`` : qui est derrière chaque poignée, et ce que ça ouvre.

- Une poignée parle **pour elle-même** : sur un transport qui prouve le
  compte (session, message privé Telegram), elle est sûre de sa continuité ;
  sur un transport qui ne prouve rien (navigateur sans compte), de rien.
- Quelqu'un peut **dire être** une autre personne qu'elle connaît (« moi c'est
  Alice », sur un nouveau compte) : c'est une revendication, notée, qui
  n'ouvre rien. Elle devient une **liaison** quand ce que la poignée dit
  recoupe ce que seule Alice pouvait savoir (``corroboration``), ou quand un
  opérateur les relie. Une affirmation seule ne franchit jamais la barre.
- Un **démenti** (« je ne suis pas Alice ») s'applique tout de suite ; il ne
  compte que contre un nom sous lequel elle connaît la personne.
- Le modèle ne peut que **douter** ou **oublier** une liaison (outils) :
  jamais faire monter la confiance.

Dans le doute, tout se ferme.
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
