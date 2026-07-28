"""Passive identification — reading who someone says they are, unprompted.

Nobody announces themselves in a form. They write "salut c'est Thomas", or
"moi c'est Alice", or they correct Mika: "non, c'est pas Julie, c'est sa
soeur". This module turns that into structured claims *without* an LLM call:
identification runs on every single inbound turn, so it has to be free.

Two things are detected:

- **name claims** — someone asserting a name for themselves
- **denials** — someone rejecting the name Mika is using for them

Deliberately conservative. A false positive here makes Mika address a
stranger by someone else's name and, worse, potentially recount that
person's private context. When the pattern is ambiguous, we return nothing
and let the conversation (or Mika, via the active tools) sort it out.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

#: Names must look like names. Allows accents, hyphens and apostrophes
#: (Jean-Luc, N'Golo, Éloïse) but not sentences.
_NAME_CORE = r"[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'’-]{1,30}"
#: Optionally a second word, for "Jean Dupont" / "Marie Claire".
#: The trailing lookahead rejects anything that continues into a digit:
#: without it "Agent007" captured cleanly as "Agent", and the digit check
#: downstream never saw the digits it was meant to catch.
_NAME = rf"{_NAME_CORE}(?:\s+{_NAME_CORE})?(?![A-Za-zÀ-ÖØ-öø-ÿ0-9])"

MAX_NAME_LENGTH = 60


@dataclass(frozen=True)
class NameClaim:
    """Someone asserting (or denying) a name for themselves."""

    name: str
    #: Evidence kind, matching ``identity.trust.EVIDENCE_WEIGHTS`` keys.
    kind: str
    #: The fragment that triggered it — stored on the claim so a human (or
    #: Mika, later) can re-judge without guessing what she saw.
    evidence: str
    #: Detector's own confidence in having parsed correctly (not identity
    #: certainty — a perfectly-parsed lie still parses perfectly).
    parse_confidence: float = 1.0

    @property
    def is_denial(self) -> bool:
        return self.kind == "denied"


# Self-introduction patterns. Ordered: the first match wins, so put the
# unambiguous ones first.
_CLAIM_PATTERNS: tuple[tuple[re.Pattern, float], ...] = (
    # "je m'appelle Thomas" / "je me nomme Thomas"
    (re.compile(rf"\bje\s+m['’]appelle\s+({_NAME})", re.I), 1.0),
    (re.compile(rf"\bje\s+me\s+nomme\s+({_NAME})", re.I), 1.0),
    # "mon nom c'est Thomas" / "mon prénom est Thomas"
    (re.compile(rf"\bmon\s+(?:pr[ée]nom|nom)\s+(?:c['’]est|est)\s+({_NAME})", re.I), 1.0),
    # "moi c'est Thomas"
    (re.compile(rf"\bmoi\s*,?\s*c['’]est\s+({_NAME})", re.I), 0.95),
    # "c'est Thomas à l'appareil" / "Thomas au clavier"
    (re.compile(rf"\b({_NAME})\s+(?:[àa]\s+l['’]appareil|au\s+clavier)", re.I), 0.95),
    # "ici Thomas"
    (re.compile(rf"\bici\s+({_NAME})\b", re.I), 0.8),
    # "je suis Thomas" — weaker: also matches "je suis fatigué", filtered below
    (re.compile(rf"\bje\s+suis\s+({_NAME})", re.I), 0.7),
    # "c'est Thomas" — weakest, needs a greeting nearby (handled by caller
    # context) but common enough to be worth catching
    (re.compile(rf"^(?:salut|bonjour|coucou|hey|hello)[\s,!]+c['’]est\s+({_NAME})", re.I), 0.9),
    # English, because people code-switch
    (re.compile(rf"\b(?:my\s+name\s+is|i\s*['’]?m|this\s+is)\s+({_NAME})", re.I), 0.7),
)

# Denials: "je ne suis pas Thomas", "c'est pas Thomas"
_DENIAL_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(rf"\bje\s+(?:ne\s+)?suis\s+pas\s+({_NAME})", re.I),
    re.compile(rf"\bc['’]est\s+pas\s+({_NAME})", re.I),
    re.compile(rf"\bce\s+n['’]est\s+pas\s+({_NAME})", re.I),
    re.compile(rf"\b(?:i\s*['’]?m|i\s+am)\s+not\s+({_NAME})", re.I),
)

# Words that follow "je suis" / "i'm" and are states, not names. Without this
# every "je suis fatigué" would register as a person called Fatigué.
_NOT_NAMES = frozenset({
    # états / adjectifs courants
    "fatigue", "fatiguee", "creve", "crevee", "content", "contente", "triste",
    "desole", "desolee", "sur", "sure", "certain", "certaine", "pret", "prete",
    "occupe", "occupee", "malade", "vieux", "jeune", "perdu", "perdue", "la",
    "ici", "parti", "partie", "rentre", "rentree", "libre", "dispo", "cool",
    "nul", "nulle", "bete", "curieux", "curieuse", "heureux", "heureuse",
    "enerve", "enervee", "stresse", "stressee", "deborde", "debordee",
    "d", "en", "au", "aux", "un", "une", "le", "les", "des", "du", "pas",
    "plus", "tres", "trop", "assez", "toujours", "jamais", "vraiment",
    "juste", "encore", "deja", "bien", "mal", "mieux", "sorry", "tired",
    "happy", "sad", "here", "back", "good", "fine", "ok", "okay", "not",
    "a", "the", "so", "just", "really", "still", "your", "ton", "ta", "mon",
    "ma", "son", "sa", "leur", "notre", "votre", "cette", "ce", "ces",
    # mots de liaison — la capture est gourmande sur deux mots, donc
    # "je ne suis pas Julie mais sa soeur" tend a ramener "Julie mais"
    "mais", "et", "ou", "donc", "or", "ni", "car", "puis", "ensuite",
    "avec", "sans", "pour", "chez", "dans", "sur", "sous", "vers", "depuis",
    "apres", "avant", "pendant", "aussi", "comme", "quand", "si", "que",
    "qui", "quoi", "dont", "ainsi", "enfin", "bref", "alors", "meme",
    "and", "but", "or", "then", "with", "from", "for", "when", "while",
    # rôles génériques — "je suis développeur" n'est pas un nom
    "developpeur", "developpeuse", "etudiant", "etudiante", "prof",
    "professeur", "ingenieur", "ingenieure", "medecin", "infirmier",
    "infirmiere", "artiste", "musicien", "musicienne", "dev", "admin",
    "humain", "humaine", "personne", "quelqu", "quelqu'un", "moi", "toi",
    "lui", "elle", "nous", "vous", "eux", "elles", "on", "je", "tu", "il",
})


def _fold(text: str) -> str:
    """Lowercase + strip accents, for comparison against ``_NOT_NAMES``."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def _plausible_name(raw: str) -> str | None:
    """Normalize a captured fragment into a name, or None if it isn't one.

    The two-word pattern is greedy, so "je ne suis pas Thomas en fait"
    captures "Thomas en". Rejecting the whole fragment because its second
    word is a stop-word would lose a perfectly good name — and a missed
    denial is the expensive kind of miss, since it leaves Mika calling a
    stranger by a friend's name. So a failed two-word read falls back to the
    first word alone.
    """
    name = " ".join(raw.split()).strip(" ,.;:!?-'’")
    if not name or len(name) > MAX_NAME_LENGTH:
        return None

    words = name.split()
    while words:
        if all(_is_name_word(w) for w in words):
            # Title-case the way people write names, preserving internal caps
            # (McCoy, N'Golo) when the writer bothered.
            return " ".join(
                w if w[:1].isupper() else w.capitalize() for w in words
            )
        words = words[:-1]
    return None


def _is_name_word(word: str) -> bool:
    """Whether one token can plausibly be part of a person's name.

    Contractions are checked whole ("d'accord") and on both sides of the
    apostrophe ("d" / "accord"), because the name pattern allows internal
    apostrophes for the sake of N'Golo and O'Brien.
    """
    if len(word) < 2 or any(c.isdigit() for c in word):
        return False
    folded = _fold(word)
    if folded in _NOT_NAMES:
        return False
    stem, _, rest = folded.replace("’", "'").partition("'")
    return not (rest and (stem in _NOT_NAMES or rest in _NOT_NAMES))


def detect_name_claim(message: str) -> NameClaim | None:
    """Extract a self-identification (or denial) from one inbound message.

    Returns None for the overwhelming majority of messages — that is the
    expected outcome, not a failure.
    """
    if not message or len(message) > 4000:
        return None

    # Denials first: "je ne suis pas Thomas" also matches the "je suis X"
    # claim pattern, and the denial is the meaningful reading.
    for pattern in _DENIAL_PATTERNS:
        match = pattern.search(message)
        if match:
            name = _plausible_name(match.group(1))
            if name:
                return NameClaim(
                    name=name, kind="denied",
                    evidence=match.group(0).strip(), parse_confidence=0.9,
                )

    for pattern, confidence in _CLAIM_PATTERNS:
        match = pattern.search(message)
        if match:
            name = _plausible_name(match.group(1))
            if name:
                return NameClaim(
                    name=name, kind="self_declared",
                    evidence=match.group(0).strip(),
                    parse_confidence=confidence,
                )
    return None


# ── Corroboration ────────────────────────────────────────────────

#: Distinct content words that must overlap before a message counts as
#: corroborating anything.
_MIN_OVERLAP_TERMS = 3

#: Tokens too common to prove anything about who is speaking.
_STOPWORDS = frozenset({
    "avec", "dans", "pour", "mais", "elle", "nous", "vous", "cette", "leur",
    "tout", "tous", "plus", "sans", "sous", "chez", "être", "etre", "avoir",
    "fait", "faire", "dit", "dire", "quand", "comme", "aussi", "bien", "très",
    "tres", "peu", "beaucoup", "alors", "donc", "parce", "que", "qui", "quoi",
    "the", "and", "with", "that", "this", "have", "from", "your", "about",
})


def corroboration_score(message: str, known_facts: list[str]) -> tuple[float, str]:
    """How much this message lines up with what Mika knows about a person.

    Someone proving they are X by mentioning something only X would bring up
    is the honest way to earn trust on an unauthenticated channel. This is a
    deliberately blunt lexical overlap — it is a *hint* that feeds a claim
    Mika still has to accept, never an automatic promotion.

    Returns ``(score in 0..1, human-readable reason)``.
    """
    if not message or not known_facts:
        return 0.0, ""

    tokens = _significant_tokens(message)
    if not tokens:
        return 0.0, ""

    best_overlap: set[str] = set()
    best_fact = ""
    for fact in known_facts:
        overlap = tokens & _significant_tokens(fact)
        if len(overlap) > len(best_overlap):
            best_overlap, best_fact = overlap, fact

    # One shared word is coincidence, two is a common topic ("aime" +
    # "musique" says nothing about who is typing). Three is the point where
    # they are plausibly talking about the same specific thing.
    if len(best_overlap) < _MIN_OVERLAP_TERMS:
        return 0.0, ""

    score = min(1.0, len(best_overlap) / 4.0)
    shared = ", ".join(sorted(best_overlap)[:4])
    return score, f"recoupe ce que tu sais ({shared}) — « {best_fact[:120]} »"


def _significant_tokens(text: str) -> set[str]:
    """Content words of a text, folded and stop-listed."""
    words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]{4,}", text or "")
    return {_fold(w) for w in words if _fold(w) not in _STOPWORDS}
