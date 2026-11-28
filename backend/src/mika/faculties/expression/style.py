"""Comment elle écrit : la consigne de style (``style``, dans la partie stable de son prompt), « COMMENT TU ÉCRIS
ICI » (la section ``form``, ADR 0140), la consigne du mode pro qui prend la place de la consigne de style
(``pro_style``, ADR 0116), et « TA RÉPONSE », le dernier mot avant son message (la section ``answer``)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mika.faculties.expression.faculty import EXPRESSION, ExpressionState
from mika.kernel.faculty import Zone
from mika.kernel.frame import Frame
from mika.kernel.prompt import CONTEXT_FOOTER, CONTEXT_HEADER
from mika.vocab.affect import Emotion
from mika.vocab.episodes import CONVERSATIONAL, Kind, Tag
from mika.vocab.phrasebook import phrase


def style() -> str:
    """La consigne de style (``expression.style`` dans sa voix) : parler comme on parle, une échelle d'intensité, ce
    qu'est le bloc d'état interne — sa tête à elle, jamais citée."""
    return phrase("expression.style", names=", ".join(e.value for e in Emotion), header=CONTEXT_HEADER,
                  footer=CONTEXT_FOOTER)


@EXPRESSION.section("style", zone=Zone.STABLE, episodes=CONVERSATIONAL, tags=[Tag.AFFECTIVE], trim_rank=100)
def _style(s: ExpressionState, frame: Frame, enrich: Any) -> str:
    return style()


@EXPRESSION.section("form", zone=Zone.STABLE, episodes=CONVERSATIONAL, tags=[Tag.AFFECTIVE],
                    trim_rank=98, title=phrase("expression.form.title"))
def _form(s: ExpressionState, frame: Frame, enrich: Any) -> str | None:
    """« COMMENT TU ÉCRIS ICI » (ADR 0140) : les codes d'écriture de l'autrice du chat — la longueur, le registre,
    les émojis, la mise en forme —, dans le premier jet seulement quand aucune seconde passe ne suivra (le pipeline le
    dit dans l'épisode : ``form``). La forme n'a qu'une maison, l'autrice ; deux lecteurs, jamais les deux à la fois."""
    ep = frame.episode
    codes = str(ep.attrs.get("form") or "").strip() if ep is not None else ""
    return phrase("expression.form.codes", codes=codes) if codes else None


def pro_style() -> str:
    """La consigne du mode pro (``expression.pro`` dans sa voix, ADR 0116), à la place de sa consigne de style (coupée
    avec ses sections affectives) : un travail, fait avec ses outils, rendu à l'écran en Markdown, sans jetons de voix
    ni balises — et ce qu'est le bloc d'état interne."""
    return phrase("expression.pro", header=CONTEXT_HEADER, footer=CONTEXT_FOOTER)


@EXPRESSION.section("answer", zone=Zone.VOLATILE, episodes=[Kind.REPLY], tags=[Tag.CHAT], trim_rank=90,
                    title=phrase("expression.answer.title"))
def _answer(s: ExpressionState, frame: Frame, enrich: Mapping[str, Any]) -> str:
    """« TA RÉPONSE » : le dernier mot avant son message — réagir en personne, ni analyse, ni vérité générale, ni
    conseil qu'on ne demande pas, ni sa phrase reformulée. Banc de conversation du 2026-10-14 (Sonnet, jugé par Opus) :
    avec cette règle seulement dans la consigne de style, en tête du prompt, les conseils de coach revenaient. La même
    à chaque réponse (ADR 0154) : rien ne la choisit d'après les mots de la personne ; la mesure et la forme sont à
    l'autrice (« COMMENT TU ÉCRIS ICI », ADR 0140), ses redites à « CE QUE TU TE RÉPÈTES », ses questions à son
    caractère (ADR 0141)."""
    return phrase("expression.answer.react")
