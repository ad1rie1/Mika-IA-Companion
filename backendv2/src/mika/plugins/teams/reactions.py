"""Les réactions d'un message Teams (ADR 0300), telles qu'elle les lit derrière son texte : le tri, le message auquel
elle prépare une réponse, ses outils de lecture.

Elle les voit quand elle lit le message ; une réaction ne déclenche jamais rien — ni remarque, ni tri, ni réponse :
l'adaptateur range un message dont seules les réactions changent comme un message connu, sans rien journaliser, et
elle les lit la prochaine fois que le message l'est. Ses mots sont dans ``persona/voix.yaml`` (``teams.reactions``) ;
l'emoji vient de la clé de Teams (``ports.teams.emoji_of``), les noms de Teams : choisis par d'autres, rendus inertes.
"""

from __future__ import annotations

from collections.abc import Sequence

from mika.ports.preprocess import inert
from mika.ports.teams import Reaction, emoji_of
from mika.vocab.phrasebook import phrase

#: les réactions dites par message, au plus ; les noms dits par réaction, au plus (les autres se comptent)
SHOWN, NAMES_SHOWN = 8, 5


def reactions_said(reactions: Sequence[Reaction], me: str) -> str:
    """Ce qu'elle lit des réactions d'un message, derrière son texte (« (réactions : 👍 Gilles, Sophie ; ❤️ toi) ») ;
    ``me`` : comment se dit la personne du compte là où elle lit (la sienne se dit ainsi, jamais par un nom). Vide sans
    réaction."""
    parts = []
    for r in reactions[:SHOWN]:
        emoji = emoji_of(r.key) or inert(r.key, 40)
        names = [inert(n, 40) for n in r.names if n][:NAMES_SHOWN]
        who = [*names, *([me] if r.mine and me else [])]
        others = r.count - len(names) - (1 if r.mine and me else 0)
        if not who:
            parts.append(phrase("teams.reactions.count", emoji=emoji, count=r.count))
            continue
        listed = phrase("teams.reactions.names_sep").join(who)
        if others > 0:
            listed = phrase("teams.reactions.more", names=listed, count=others)
        parts.append(phrase("teams.reactions.one", emoji=emoji, who=listed))
    return phrase("teams.reactions.line", list=phrase("teams.reactions.sep").join(parts)) if parts else ""
