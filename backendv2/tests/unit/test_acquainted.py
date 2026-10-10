"""Les gens qu'on nomme : une amie dont elle ne sait encore rien, nommée par un autre, reste quelqu'un qu'elle connaît.

Sonde réelle du 2026-10-10 : Bob dit « je bosse avec Carol chez Ubisoft » ; Carol est son amie et lui a écrit le matin
même, mais elle n'a aucune note sur elle — le rappel ne la trouvait donc nulle part, et Mika répondait « Carol, je ne
lui ai jamais parlé ». Elle sait maintenant qu'elle connaît quelqu'un de ce nom, peut-être pas la même personne, et
peut demander de qui on parle — sans rien dire de ce qu'elle en sait.
"""

from __future__ import annotations

from mika.contracts import social as social_c
from mika.faculties.memory.faculty import MemoryState
from mika.faculties.memory.recall import Recall, _acquainted, _recall, acquainted
from tests.unit.test_knowledge_coherence import NAMES, Frame, Store, ask

ALICE, BOB, CAROL, INES = "user_2", "user_3", "user_4", "user_5"


class Circle(Frame):
    """Son cercle : Carol, une amie ; Inès, une proche ; d'autres noms au besoin."""

    def __init__(self, *args, circle=(CAROL, INES), names=None, **kw):
        super().__init__(*args, **kw)
        self.circle, self.names = circle, {**NAMES, **(names or {})}

    def get(self, key):
        if key.name == "social.circle":
            return self.circle
        if key.name == "identity.identity":
            return type("V", (), {"name": self.names.get(key.arg, key.arg)})()
        if key.name == "social.closeness":
            return {CAROL: social_c.FRIEND, INES: social_c.CLOSE}.get(key.arg, social_c.STRANGER)
        return super().get(key)


def test_a_friend_named_by_someone_else_is_someone_she_knows():
    frame = Circle()
    assert acquainted(frame, "au fait je bosse avec Carol chez Ubisoft", BOB) == [("Carol", 1, social_c.FRIEND)]
    assert acquainted(frame, "tu connais Inès ?", BOB) == [("Inès", 1, social_c.CLOSE)]
    assert acquainted(frame, "c'est Carol, au fait", CAROL) == []  # elle-même, en face : rien à signaler
    assert acquainted(frame, "Léo m'a parlé de toi", BOB) == []  # pas de son cercle
    namesake = Circle(circle=(CAROL, "user_8"), names={"user_8": "Mika Durand"})
    assert acquainted(namesake, "salut Mika", BOB) == []  # son nom à elle : on s'adresse à elle, pas à son amie
    twins = Circle(circle=(CAROL, "user_9"), names={"user_9": "Carol Martin"})
    assert acquainted(twins, "je bosse avec Carol", BOB) == [("Carol", 2, "")]  # deux Carol : laquelle ?


def test_the_section_says_she_knows_and_nothing_about_them():
    body = _acquainted(MemoryState(), Circle(), {"recall": Recall(acquainted=[("Carol", 1, social_c.FRIEND)])})
    text = body.content
    assert "« Carol » : tu connais quelqu'un de ce nom, qui fait partie de tes amis" in text
    assert "peut-être pas la même personne" in text and "Ne dis pas que tu ne connais personne de ce nom" in text
    two = _acquainted(MemoryState(), Circle(), {"recall": Recall(acquainted=[("Carol", 2, "")])}).content
    assert "tu connais plusieurs personnes de ce nom" in two
    assert _acquainted(MemoryState(), Circle(), {"recall": Recall()}) is None


async def test_the_recall_finds_her_without_any_note_about_her():
    db = Store()
    ask(db, "au fait je bosse avec Carol chez Ubisoft")
    frame = Circle()
    frame.episode.target = BOB
    recall = await _recall(MemoryState(), frame, {"store": db, "vectors": None})
    assert recall.acquainted == [("Carol", 1, social_c.FRIEND)]
    assert recall.beliefs == [] and recall.souvenirs == []  # rien d'elle : seulement qu'elle la connaît
    db.conn.close()
