"""``self`` : la persona (un seul document pour toutes ses voix), le tempérament dont les autres facultés dérivent
leurs paramètres, l'estime de soi, le récit qu'elle fait d'elle-même et ses nuits.

Carte des modules (l'ordre de ses sections dans le prompt est celui de la composition, ``READING``) :

- ``faculty`` : l'état (``SelfState``), la faculté (``SELF``), le jour vécu ;
- ``knobs`` : ses réglages (``SelfParams``) ;
- ``records`` : ce que l'état garde (coups, efforts, actes, marques, intérêts, pistes, journaux, rêves) et les codes
  d'actes ;
- ``persona`` : le document de persona et son rendu (``load``, ``render``, ``persona_for``, le fait
  ``self.portrayed``) ;
- ``narrative`` : le récit « Je suis quelqu'un qui… », sur tout ce qu'elle sait d'elle (section ``narrative``) ;
- ``character`` : son caractère, écrit par le modèle d'après sa matrice et à côté de son portrait — un bloc de sa
  persona, partout où elle est injectée (ADR 0139, 0152) ;
- ``esteem`` : l'estime, ce que les autres lui disent d'elle, ses actes (section ``self_state``) ;
- ``model`` : ce qu'elle sait d'elle — tenir parole, mener au bout, voir venir, ses changements d'avis (section
  ``self_model``) ;
- ``interests`` : ce qui la passionne — ses centres d'intérêt vivants, ses pistes, sa réflexion de la nuit ;
- ``absence`` : les arrêts de son serveur, qu'elle n'a pas vécus (section ``absence``) ;
- ``greeting`` : le ton de ses bonjours (section ``greeting_tone``) ;
- ``night`` : la nuit — journal, rêves, réveil (sections ``yesterday``, ``dream``) ;
- ``inspect`` : ce que la console montre d'elle ;
- ``lines`` : ce qui se dit pareil dans le récit et dans son prompt (sans section ni réducteur) ;
- ``days`` : le calendrier vécu (ce qui la touche dans ce qu'on lui dit, le modèle le lit : ``esteem``, ADR 0093).
"""

from __future__ import annotations

# isort: off
from mika.faculties.self import narrative as _narrative  # noqa: F401
from mika.faculties.self import character as _character  # noqa: F401
from mika.faculties.self import esteem as _esteem  # noqa: F401
from mika.faculties.self import model as _model  # noqa: F401
from mika.faculties.self import interests as _interests  # noqa: F401
from mika.faculties.self import absence as _absence  # noqa: F401
from mika.faculties.self import greeting as _greeting  # noqa: F401
from mika.faculties.self import night as _night  # noqa: F401
from mika.faculties.self import inspect as _inspect  # noqa: F401
# isort: on
from mika.faculties.self.faculty import SELF, SelfState
from mika.faculties.self.knobs import SelfParams, params
from mika.faculties.self.persona import load, persona_for, render

__all__ = ["SELF", "SelfParams", "SelfState", "load", "params", "persona_for", "render"]
