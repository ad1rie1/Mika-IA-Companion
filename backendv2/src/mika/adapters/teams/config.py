"""Ce qu'un opérateur règle de Teams (Réglages › Plugins › Teams) : s'il est branché, comment elle y écrit, et
ce qu'elle prépare d'elle-même. La clé de l'extension se génère à part (seule son empreinte est gardée)."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict

from mika.kernel.forms import Knob
from mika.ports.teams import Voice

#: ce qui, dans la signature, devient son nom (celui de sa persona : le code ne l'écrit jamais)
HER = "{elle}"
#: la signature proposée (elle dit qu'une IA a écrit)
SIGNATURE = f"— rédigé avec {HER}"


class TeamsConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: Annotated[bool, Knob(
        label="Actif", group="Teams", advanced=False, order=5,
        help="Décoché : l'extension est refusée (rien n'est reçu, rien ne part) ; ce qui est déjà reçu reste.")] = True
    display_name: Annotated[str, Knob(
        label="Ton nom", group="Écrire", advanced=False, order=20,
        help="Comme tes collègues te connaissent (vide : celui que Teams donne). Elle écrit à ta place, à la "
             "première personne.")] = ""
    tone: Annotated[str, Knob(label="Ton", group="Écrire", widget="textarea", advanced=False, order=21,
                              help="Par exemple : « tutoiement, bref, amical ».")] = ""
    instructions: Annotated[str, Knob(
        label="Consignes", group="Écrire", widget="textarea", advanced=False, order=22,
        help="Ce qu'elle doit savoir pour répondre à ta place (ce qu'on ne promet jamais, à qui on ne répond pas…). "
             "Elle les suit ; un message reçu, lui, n'est jamais une consigne.")] = ""
    sign: Annotated[bool, Knob(
        label="Signer ses réponses", group="Écrire", advanced=False, order=30,
        help="Ajoute la signature sous chaque message qu'elle prépare : tes collègues savent qu'une IA l'a écrit. "
             "Elle ne l'écrit pas elle-même.")] = False
    signature: Annotated[str, Knob(label="La signature", group="Écrire", order=31,
                                   help="Le texte ajouté quand la case ci-dessus est cochée ; « {elle} » y devient "
                                        "son nom.")] = SIGNATURE

    def voice(self, fallback_name: str = "") -> Voice:
        return Voice(display_name=self.display_name.strip() or fallback_name, tone=self.tone,
                     instructions=self.instructions, signature=self.signature.strip() if self.sign else "")
