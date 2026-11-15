"""Comment des noms deviennent des clés de personne (la consolidation, côté modèle).

Le modèle désigne les gens de la conversation par leur jeton (« Alice [P1] »,
``conversation.py``). Un nom qui n'en a pas se résout d'abord dans la
conversation, puis parmi toutes les personnes qu'elle connaît quand un seul
porte ce nom ; sinon c'est une personne connue de nom seulement
(``name:…``, liée à la conversation où on l'a nommée). Elle-même n'est pas une
personne « concernée » (c'est sa propre vie) : les noms par lesquels le modèle
la désigne sont ceux du contrat (``extraction.self_names``).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from mika.faculties.memory.conversation import Speaker
from mika.faculties.memory.extraction import SELF_NAMES, TOKEN, self_names
from mika.kernel.codec import digest
from mika.ports.sql import HANDLE_MAX, fit
from mika.vocab.people import fold
from mika.vocab.words import WORD


def mention_scope(conversation: str) -> str:
    """La portée d'une mention inconnue (``name:<portée>:<nom>``) : la conversation où on l'a nommée."""
    return digest(conversation)[:16]


#: ``name:<portée>:<nom>`` — une mention liée à la conversation où elle a été faite
_SCOPED = re.compile(r"^name:([0-9a-f]{16}):")


def scope_of(key: str) -> str | None:
    """La portée d'une clé de mention, ``None`` pour une clé d'avant les portées (ou une personne)."""
    m = _SCOPED.match(key)
    return m.group(1) if m else None


@dataclass(frozen=True, slots=True)
class People:
    """Comment des noms deviennent des clés : les jetons de la conversation,
    puis ses prénoms (s'ils ne sont qu'à une personne), puis l'annuaire de
    tous ceux qu'elle connaît — un nom complet qu'une seule porte, ou un
    prénom qu'une seule porte parmi celles qu'elle a vues dans un salon avec
    quelqu'un de la conversation (``near``). Un prénom seul, sinon, reste une
    mention (``name:<portée>:<prénom>``) : la nouvelle collègue « Alice » de Bob
    n'est pas l'Alice qu'elle connaît. L'identité la *présume* (un fait
    révisable, jamais une liaison : ADR 0075)."""

    tokens: Mapping[str, str] = field(default_factory=dict)
    local: Mapping[str, str] = field(default_factory=dict)
    directory: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    #: comment le modèle la désigne, elle (``self_names`` : son nom compris)
    me: frozenset[str] = SELF_NAMES
    #: son prénom seul (replié) : elle, sauf si quelqu'un de la conversation ou de l'annuaire le porte aussi
    first: str = ""
    scope: str = ""
    #: celles qu'elle a vues dans un salon avec quelqu'un de la conversation : leur prénom seul les désigne
    near: frozenset[str] = frozenset()

    @classmethod
    def of(cls, speakers: Sequence[Speaker], directory: Mapping[str, tuple[str, ...]], her: str = "",
           scope: str = "", near: Sequence[str] = ()) -> People:
        """``her`` : son nom (celui de sa persona) — le modèle qui la nomme parle d'elle, pas de quelqu'un."""
        tokens = {s.token.lower(): s.person for s in speakers}
        named: dict[str, set[str]] = {}
        for s in speakers:
            folded = " ".join(fold(s.name).split())
            for key in {folded, *folded.split()[:1]}:
                if key:
                    named.setdefault(key, set()).add(s.person)
        local = {k: next(iter(v)) for k, v in named.items() if len(v) == 1}
        folded_her = " ".join(fold(her).split())
        first = folded_her.split()[0] if " " in folded_her else ""
        me = (self_names(her) - {first}) if her else SELF_NAMES
        return cls(tokens, local, directory, me, first,
                   mention_scope(scope or "|".join(sorted(s.person for s in speakers))), frozenset(near))

    def one(self, raw: str) -> str | None:
        """Une clé, ou ``None`` pour elle-même ou rien."""
        text = str(raw)
        m = TOKEN.search(text)
        if m and f"p{m.group(1)}" in self.tokens:
            return self.tokens[f"p{m.group(1)}"]
        folded = " ".join(fold(TOKEN.sub(" ", text)).split())
        if not folded or folded in self.me:
            return None
        key = self.local.get(folded)
        found: tuple[str, ...] = ()
        if key is None:
            found = self.directory.get(folded) or ()
            # un nom complet, ou quelqu'un que la conversation connaît : vu en salon avec l'un de ses locuteurs, ou
            # l'un d'eux sous une autre de ses adresses (« Robert » sur Telegram, « Bob » ici)
            if len(found) == 1 and (" " in folded or found[0] in self.near or found[0] in self.tokens.values()):
                key = found[0]
        if key is None and folded == self.first and len(found) != 1:
            return None  # son prénom seul, que personne d'autre de connu ne porte : c'est elle
        # une mention inconnue devient une clé (``memory_about``…) : un « nom » démesuré y est ramené à sa borne
        return key or fit(f"name:{self.scope}:{folded}", HANDLE_MAX)

    def resolve(self, names: Sequence[str]) -> tuple[str, ...]:
        return tuple(sorted({k for n in names if (k := self.one(n)) is not None}))

    def names_someone(self, text: str) -> bool:
        """Le texte nomme-t-il quelqu'un d'autre qu'elle : un locuteur de la conversation, ou une personne qu'elle
        connaît (son nom ou son prénom) ? « Alice est comptable à Lyon », tiré de sa propre réplique (« je sais que tu
        es comptable à Lyon »), n'est pas une note sur elle : la ranger ainsi la rendait dicible à tous (sonde réelle
        du 2026-10-09)."""
        said = " ".join(WORD.findall(fold(TOKEN.sub(" ", str(text)))))
        if not said:
            return False
        for key in (*self.local, *self.directory):
            if len(key) >= 3 and key not in self.me and key != self.first \
                    and re.search(rf"(?<!\w){re.escape(key)}(?!\w)", said):
                return True
        return False
