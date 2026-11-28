"""Le texte d'une réponse : silence, redite, passages à l'abri, premiers paragraphes.

Des règles pures sur ce qu'elle allait dire, sans rien de l'épisode :

- ``is_silence`` : elle a choisi de se taire (la balise ``[SILENCE]`` sous toutes ses formes, ou le seul mot) ;
- ``repeats_last`` : elle allait redire son dernier message du fil qu'on lui a montré ;
- ``shield`` et ``unshield`` : ce qu'une réponse en Markdown garde tel quel à travers les analyseurs (ses blocs de
  code, son code en ligne, l'indentation de ses lignes) ;
- ``first_paragraphs`` : les premiers paragraphes d'un texte.

Qui les lit : le pipeline d'épisode (``runtime/pipeline.py``), sur sa réponse ; la seconde passe
(``runtime/second_pass.py``), qui écarte une récriture qui ne rend qu'un silence ; le simulateur
(``sim/llm/persona.py``), dont la doublure varie sa formule plutôt que de redire son dernier message.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Sequence

from mika.kernel.prompt import CONTEXT_FOOTER
from mika.ports.llm import LLMRequest

#: la balise de silence, où qu'elle soit (crochets, casse et espaces indifférents) : sans ambiguïté
_SILENCE_TAG = re.compile(r"\[\s*silence\s*\]", re.IGNORECASE)
#: ce qui habille un mot seul : emphase markdown, guillemets, ponctuation finale
_DRESSING = "*_`~«»\"“”„‟'’ \t\r\n"
_BARE_SILENCE = re.compile(r"[(\[]?\s*silence\s*[)\]]?", re.IGNORECASE)


def is_silence(text: str) -> bool:
    """Elle a choisi de se taire : la balise ``[SILENCE]`` sous toutes ses formes réelles (``[silence]``,
    ``[SILENCE].``, ``**[SILENCE]**``, « [SILENCE] », ``[SILENCE] (un commentaire)``, une phrase suivie de
    ``[SILENCE]``), ou le seul mot *silence*, nu ou entre parenthèses (``SILENCE``, ``(silence)``). Jamais
    un vrai message qui contient le mot (« le silence de la nuit me plaît »)."""
    if _SILENCE_TAG.search(text):
        return True
    bare = text.strip(_DRESSING).rstrip(".!?…:;,").strip(_DRESSING)
    return bool(_BARE_SILENCE.fullmatch(bare))


#: les balises (``[EMOTION: happy 0.5]``, que le fil montré au modèle garde ; ``[SIGH]``, ``[PAUSE:500]``) et la
#: ponctuation ne font pas une autre phrase
_VOICE_TOKEN = re.compile(r"\[[^\[\]\n]{1,40}\]")
_NOT_WORDS = re.compile(r"[^\w]+")
#: en deçà (en caractères), un petit mot (« d'accord ») : il se redit
REPEAT_MIN_CHARS = 30
#: une réponse à quelques mots seulement (« re », « hey ») …
SHORT_WORDS = 2
#: … qui ressemble à ce point à son dernier message en est une redite
NEAR_RATIO = 0.85


def _plain(text: str) -> str:
    return " ".join(_NOT_WORDS.sub(" ", _VOICE_TOKEN.sub(" ", text).lower()).split())


def repeats_last(text: str, req: LLMRequest) -> bool:
    """Elle allait redire, mot pour mot, son dernier message du fil qu'on lui a montré (sonde réelle du
    2026-10-03 : à « re », la même phrase que son initiative d'une minute plus tôt, à l'identique). Une personne ne
    se répète pas ainsi : mieux vaut se taire."""
    last = next((m.content for m in reversed(req.messages) if m.role == "assistant" and m.content.strip()), "")
    mine, before = _plain(text), _plain(last)
    if min(len(mine), len(before)) < REPEAT_MIN_CHARS:
        return False  # « d'accord », « haha ok » : un petit mot se redit sans qu'on se répète
    if mine == before:
        return True  # à l'identique (à la ponctuation et aux balises près)
    # presque la même phrase, quand la personne n'a dit que deux mots (« re », « hey ») : la sonde du 2026-10-03,
    # « joyeux anniversaire pour tes 30 ans… » à son initiative, puis « joyeux anniv' pour tes 30 ans… » à « hey ».
    # Ailleurs, une variante (« numéro 3 », « numéro 4 ») n'est pas une redite : « CE QUE TU TE RÉPÈTES » s'en charge
    heard = _plain(_current_message(req))
    return 0 < len(heard.split()) <= SHORT_WORDS and difflib.SequenceMatcher(None, mine, before).ratio() >= NEAR_RATIO


def _current_message(req: LLMRequest) -> str:
    """Ce que la personne vient d'écrire : la fin du dernier tour (après l'état interne, s'il y est)."""
    last = req.messages[-1].content if req.messages and req.messages[-1].role == "user" else ""
    return last.rsplit(CONTEXT_FOOTER, 1)[-1]


#: ce qu'une réponse en Markdown garde tel quel (``EpisodeMode.markdown``) : un bloc de code (fermé ou non), du code
#: en ligne, l'indentation d'une ligne — les analyseurs rangent une parole de chat (espaces resserrés, indentation
#: ôtée, ``[ARR]`` pris pour un jeton)
_SHIELDED = re.compile(r"```.*?(?:```|\Z)|`[^`\n]+`|^[ \t]{2,}(?=\S)", re.DOTALL | re.MULTILINE)
_SHIELD = re.compile("\ue000(\\d+)\ue001")


def shield(text: str) -> tuple[str, list[str]]:
    """Le texte où chaque passage à garder tel quel est remplacé par un repère (des caractères à usage privé), et
    ces passages dans l'ordre."""
    kept: list[str] = []

    def keep(m: re.Match[str]) -> str:
        kept.append(m.group(0))
        return f"\ue000{len(kept) - 1}\ue001"

    return _SHIELDED.sub(keep, text), kept


def unshield(text: str, kept: Sequence[str]) -> str:
    """Les passages gardés remis à leur repère (un repère inconnu se retire)."""
    return _SHIELD.sub(lambda m: kept[int(m.group(1))] if int(m.group(1)) < len(kept) else "", text)


def first_paragraphs(text: str, n: int) -> str:
    """Les ``n`` premiers paragraphes d'un texte (séparés par une ligne vide)."""
    kept = [part.strip() for part in re.split(r"\n\s*\n", text.strip()) if part.strip()]
    return "\n\n".join(kept[:n])
