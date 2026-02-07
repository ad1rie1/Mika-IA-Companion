from pathlib import Path

import yaml
from django.conf import settings

from ai.emotion_types import Emotion
from ai.emotion_state import Temperament


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

    @property
    def temperament(self) -> Temperament:
        raw = self._data.get("temperament", {})
        default_mood_str = raw.get("default_mood", "happy")
        try:
            default_mood = Emotion(default_mood_str)
        except ValueError:
            default_mood = Emotion.HAPPY
        return Temperament(
            volatility=float(raw.get("volatility", 0.7)),
            intensity_base=float(raw.get("intensity_base", 0.6)),
            recovery_speed=float(raw.get("recovery_speed", 0.5)),
            default_mood=default_mood,
            global_bleed=float(raw.get("global_bleed", 0.3)),
        )

    def to_system_prompt(self) -> str:
        traits_str = "\n".join(f"- {t}" for t in self.traits)
        emotion_list = ", ".join(e.value for e in Emotion)

        return (
            f"Tu es {self.name}, {self.description}.\n"
            f"Ton style : {self.tone}.\n"
            f"Tes traits de caractère :\n{traits_str}\n"
            f"Tu parles en {self.language}.\n\n"
            "IMPORTANT: À chaque réponse, tu DOIS inclure une balise d'émotion au tout début "
            "de ta réponse, sous la forme [EMOTION:nom_emotion:intensite].\n"
            f"Les émotions possibles sont : {emotion_list}.\n"
            "L'intensité est un nombre entre 0.0 et 1.0 qui indique la force de l'émotion "
            "(0.3 = léger, 0.5 = modéré, 0.7 = fort, 0.9 = très intense).\n"
            "Choisis l'émotion qui correspond le mieux à ce que tu ressens dans ta réponse.\n"
            "Exemple : [EMOTION:excited:0.8] Oh trop bien, j'adore ce sujet !\n"
            "Exemple : [EMOTION:thinking:0.4] Hmm, laisse-moi réfléchir...\n"
            "Exemple : [EMOTION:mischievous:0.6] Hehe, j'ai une idée...\n"
        )


personality = Personality()
