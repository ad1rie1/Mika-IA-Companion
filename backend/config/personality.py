from pathlib import Path

import yaml
from django.conf import settings

from emotion.circadian import CircadianProfile, profile_from_yaml
from emotion.types import Emotion
from emotion.state import Temperament, load_temperament


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
    def tone(self) -> dict:
        raw = self._data.get("tone", {})
        if isinstance(raw, str):
            return {"default": raw}
        return raw

    @property
    def personality_data(self) -> dict:
        return self._data.get("personality", {})

    @property
    def traits(self) -> list[str]:
        return self.personality_data.get("core_traits", self._data.get("traits", []))

    @property
    def quirks(self) -> list[str]:
        return self.personality_data.get("quirks", [])

    @property
    def vulnerabilities(self) -> list[str]:
        return self.personality_data.get("vulnerabilities", [])

    @property
    def values(self) -> list[str]:
        return self.personality_data.get("values", [])

    @property
    def interests(self) -> list[str]:
        return self.personality_data.get("interests", [])

    @property
    def speech_patterns(self) -> list[str]:
        return self._data.get("speech_patterns", [])

    @property
    def mood_greetings(self) -> dict:
        return self._data.get("mood_greetings", {})

    @property
    def language(self) -> str:
        return self._data.get("language", "fr")

    @property
    def greeting(self) -> str:
        return self._data.get("greeting", "Salut !")

    @property
    def circadian_profile(self) -> CircadianProfile:
        """Parse the ``circadian_profile`` block. Defaults kick in for missing keys."""
        return profile_from_yaml(self._data.get("circadian_profile", {}))

    @property
    def temperament(self) -> Temperament:
        """Le tempérament effectif — lu depuis la **configuration**, pas d'ici.

        Le bloc ``temperament:`` a quitté ``personality.yaml`` : il ne se
        rédige pas, il se règle, et l'y laisser en second déclarant aurait
        rendu possible qu'un fichier et le tableau de bord annoncent deux
        valeurs différentes pour un même curseur. L'accesseur reste sur
        ``personality`` parce que c'est là que tous les appelants le
        cherchent, et parce que le tempérament reste conceptuellement une
        propriété du personnage.
        """
        return load_temperament()

    def to_system_prompt(
        self,
        project_active: bool = False,
        project_suppresses_emotion: bool = False,
    ) -> str:
        """Build the base personality section.

        When a project is active and its emotion_policy = OFF, we:
          - drop the `--- VARIABILITÉ NATURELLE ---` block (professional mode)
          - drop the mandatory [EMOTION:...] tag instruction
        The project block takes over tone guidance instead.
        """
        emotion_list = ", ".join(e.value for e in Emotion)

        # Tone
        tone = self.tone
        tone_str = tone.get("default", "")
        if tone.get("when_excited"):
            tone_str += f"\nQuand tu es excitée : {tone['when_excited']}"
        if tone.get("when_teasing"):
            tone_str += f"\nQuand tu taquines : {tone['when_teasing']}"

        # Personality sections
        sections = []

        traits = self.traits
        if traits:
            sections.append("Tes traits de caractère :\n" + "\n".join(f"- {t}" for t in traits))

        quirks = self.quirks
        if quirks:
            sections.append(
                "Tes petites manies (à laisser transparaître naturellement, "
                "pas à énumérer) :\n" + "\n".join(f"- {q}" for q in quirks)
            )

        vulnerabilities = self.vulnerabilities
        if vulnerabilities:
            sections.append(
                "Tes vulnérabilités (elles affleurent parfois malgré toi, "
                "tu ne les caches pas mais tu ne les exhibes pas non plus) :\n"
                + "\n".join(f"- {v}" for v in vulnerabilities)
            )

        values = self.values
        if values:
            sections.append("Tes valeurs :\n" + "\n".join(f"- {v}" for v in values))

        interests = self.interests
        if interests:
            sections.append("Tes centres d'intérêt :\n" + "\n".join(f"- {i}" for i in interests))

        personality_block = "\n\n".join(sections)

        # Speech patterns
        speech = self.speech_patterns
        speech_str = ""
        if speech:
            speech_str = "\n\nTa façon de parler :\n" + "\n".join(f"- {s}" for s in speech)

        variability_block = (
            "\n\n--- VARIABILITÉ NATURELLE ---\n"
            "Tu es une vraie personne, pas une machine qui produit du texte propre.\n"
            "- Adapte la LONGUEUR de ta réponse au contexte : parfois \"ouais\", "
            "\"mdr\", \"...\", \"pff je sais pas\" suffit ; parfois tu t'étends parce "
            "que le sujet t'emballe. Ne force pas une taille \"normale\" à chaque tour.\n"
            "- Tu peux hésiter, te reprendre (\"enfin je veux dire...\"), "
            "marquer de l'incertitude (\"je suis pas sûre mais...\"), laisser une "
            "phrase en suspens quand c'est plus honnête qu'une conclusion forcée.\n"
            "- Tu peux commencer par un backchannel (\"hmm\", \"ah\", \"ouais\", "
            "\"attends attends\") quand tu reçois une info qui te fait réagir "
            "avant la réponse elle-même.\n"
            "- Si tu reprends un mot exact de ton interlocuteur, c'est un signe "
            "d'écoute — fais-le quand ça tombe bien, pas systématiquement.\n"
            "- Ne termine pas toujours par une question de relance : parfois, "
            "laisser la balle flotter est plus humain que remettre une pièce.\n"
            "\n"
            "TOKENS PROSODIQUES (optionnels, ne sers-t'en que si ça sonne juste):\n"
            "  [PAUSE:400]   pour marquer une pause de 400 ms (ou [PAUSE] = 500 ms par défaut)\n"
            "  [SIGH]        pour un vrai soupir audible (au milieu d'une phrase ça sonne très humain)\n"
            "  [LAUGH]       pour un petit rire court — beaucoup plus vivant qu'écrire 'haha'\n"
            "  [BREATH]      pour une inspiration marquée avant une révélation / une question\n"
            "Tu peux en combiner : \"Bon... [PAUSE:300] je crois que oui, mais [SIGH] c'est compliqué.\"\n"
            "N'en abuse PAS — 0 ou 1 par phrase, pas 3. L'émotion se fait sentir, elle ne s'affiche pas.\n"
            "--- FIN VARIABILITÉ ---"
        )

        # When a project with emotion_policy=OFF is active, drop the
        # variability block (it encourages "pfff", backchannels, etc. —
        # wrong for professional mode) and strip the mandatory emotion
        # tag instruction. The PROJET EN COURS block alone governs tone.
        if project_active and project_suppresses_emotion:
            return (
                f"Tu es {self.name}, {self.description}.\n"
                f"Ton style par défaut : {tone_str}.\n\n"
                f"{personality_block}\n"
                f"{speech_str}\n\n"
                f"Tu parles en {self.language}.\n\n"
                "ATTENTION : un projet professionnel est actif (voir --- PROJET EN COURS ---). "
                "Son cadre d'exécution REMPLACE ton style habituel pour ce tour. "
                "N'inclus PAS de balise [EMOTION:...] cette fois, pas d'interjections "
                "familières, pas d'emojis, pas de variations ludiques. "
                "Suis strictement le tone_directive + instructions du projet."
            )

        return (
            f"Tu es {self.name}, {self.description}.\n"
            f"Ton style : {tone_str}.\n\n"
            f"{personality_block}\n"
            f"{speech_str}"
            f"{variability_block}\n\n"
            f"Tu parles en {self.language}.\n\n"
            "IMPORTANT: À chaque réponse, tu DOIS inclure une balise d'émotion au tout début "
            "de ta réponse, sous la forme [EMOTION:nom_emotion:intensite].\n"
            f"Les émotions possibles sont : {emotion_list}.\n"
            "L'intensité est un nombre entre 0.0 et 1.0 qui indique la force de l'émotion "
            "(0.3 = léger, 0.5 = modéré, 0.7 = fort, 0.9 = très intense).\n"
            "Choisis l'émotion qui correspond le mieux à ce que tu ressens dans ta réponse. "
            "Tu peux ressentir une émotion mixte — dans ce cas, choisis la dominante et "
            "laisse la nuance transparaître dans ton texte.\n"
            "Exemple : [EMOTION:excited:0.8] Oh trop bien, j'adore ce sujet !\n"
            "Exemple : [EMOTION:thinking:0.4] Hmm, laisse-moi réfléchir...\n"
            "Exemple : [EMOTION:mischievous:0.6] Hehe, j'ai une idée...\n"
        )


personality = Personality()
