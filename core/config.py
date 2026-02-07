from pathlib import Path

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
    )

    anthropic_api_key: str = Field(description="Anthropic API key for Claude")
    telegram_token: str = Field(default="", description="Telegram bot token")
    vtuber_name: str = Field(default="Mika", description="VTuber character name")
    ws_port: int = Field(default=8765, description="WebSocket server port")
    api_port: int = Field(default=8000, description="FastAPI HTTP port")
    claude_model: str = Field(
        default="claude-sonnet-4-5-20250929", description="Claude model to use"
    )
    memory_short_term_limit: int = Field(
        default=20, description="Max messages in short-term memory"
    )
    db_path: str = Field(
        default=str(PROJECT_ROOT / "vtuber.db"), description="SQLite database path"
    )


class Personality:
    def __init__(self, path: Path | None = None):
        self.path = path or PROJECT_ROOT / "personality.yaml"
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


settings = Settings()
personality = Personality()
