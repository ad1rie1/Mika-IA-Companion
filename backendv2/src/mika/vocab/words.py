"""Les mots qui portent un sujet — pour comparer des phrases sans modèle.

Repli de la casse et des accents, mots vides retirés : « tu te souviens de
ce que je t'ai dit pour samedi » ne garde que « samedi ». Sert à l'index de
hachage (simulateur, tests), à la corroboration d'une identité et à la
lecture du ton.
"""

from __future__ import annotations

import re
import unicodedata

WORD = re.compile(r"[a-z0-9]+")

#: Repliés, sans accents.
STOPWORDS = frozenset("""
les des une uns aux que qui quoi dont pour par sur sous dans avec sans chez entre vers mais donc car pas plus moins
tres trop bien tout tous toute toutes cette ces son sa ses mon ma mes ton ta tes leur leurs notre nos votre vos
est sont suis etais etait ete etre avoir avais avait ont fait faire dit dire dis vais vas va aller peu peut peux
elle elles lui ils nous vous moi toi ceux celle cela ceci comme quand alors aussi encore deja meme autre autres
quelque chose rien oui non bon bah ben hein ouais cest jai tai quil quelle souviens rappelles rappelle sais
""".split())
#: Les mots de la conversation elle-même (« je t'avais parlé la dernière
#: fois ») : ils ne prouvent pas qu'on connaît un sujet.
CHATTER = frozenset("""
avez avons parle parler parles parlais dernier derniere fois jour jours mois semaine semaines mika salut coucou
merci truc trucs genre vraiment juste toujours jamais maintenant aujourd hier demain
""".split())


def fold(text: str) -> str:
    """Casse et accents repliés."""
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


def words(text: str, *, min_len: int = 3) -> list[str]:
    """Les mots d'un texte qui disent quelque chose, dans l'ordre."""
    return [w for w in WORD.findall(fold(text)) if len(w) >= min_len and w not in STOPWORDS and w not in CHATTER]


def stems(text: str, *, min_len: int = 4, width: int = 6) -> set[str]:
    """Des radicaux grossiers (les ``width`` premières lettres) : « rechute »
    ≈ « rechuté », « mariage » ≈ « mariages »."""
    return {w[:width] for w in words(text, min_len=min_len)}
