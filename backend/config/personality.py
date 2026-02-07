from pathlib import Path

import yaml
from django.conf import settings


class Personality:
    def __init__(self, path: Path | None = None):
        self.path = path or settings.PERSONALITY_PATH
        self._data: dict = {}
        self.load()

    def load(self):
        if self.path.exists():
            with open(self.path, "r", encoding="utf-8") as f:
                self._data = yaml.safe_load(f) or {}

    @property
    def name(self) -> str:
        return self._data.get("name", "Mika")

    @property
    def description(self) -> str:
        return self._data.get("description", "")

    @property
    def tone(self) -> str:
        return self._data.get("tone", "")

    @property
    def traits(self) -> list[str]:
        return self._data.get("traits", [])

    @property
    def language(self) -> str:
        return self._data.get("language", "fr")

    @property
    def greeting(self) -> str:
        return self._data.get("greeting", "Salut !")

    def to_system_prompt(self) -> str:
        traits_str = "\n".join(f"- {t}" for t in self.traits)
        return (
            f"Tu es {self.name}, {self.description}.\n"
            f"Ton style : {self.tone}.\n"
            f"Tes traits de caractère :\n{traits_str}\n"
            f"Tu parles en {self.language}.\n\n"
            "IMPORTANT: À chaque réponse, tu DOIS inclure une balise d'émotion au tout début "
            "de ta réponse, sous la forme [EMOTION:nom_emotion]. "
            "Les émotions possibles sont : neutral, happy, sad, angry, surprised, thinking, love.\n"
            "Choisis l'émotion qui correspond le mieux à ce que tu ressens dans ta réponse.\n"
            "Exemple : [EMOTION:happy] Oh super, j'adore ce sujet !\n"
        )


personality = Personality()
