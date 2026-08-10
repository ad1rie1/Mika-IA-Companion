"""Le personnage, lu dans le registre de configuration.

``personality.yaml`` n'existe plus. Il portait le nom, la description, le ton,
les traits, les manies, les valeurs, les tics de langage, les salutations et le
profil circadien ; tout cela se règle maintenant dans le tableau de bord
(Configuration → Personnalité). Le tempérament était déjà parti le premier, et
pour la même raison, écrite alors dans le fichier lui-même : deux endroits où
déclarer une valeur, ce sont deux valeurs qui finissent par diverger.

Rien n'est perdu au passage — les défauts déclarés dans
``config/personality_schema.py`` reproduisent mot pour mot ce que le fichier
contenait, et un test l'épingle. Un clone neuf obtient la même Mika ; une
installation qui avait personnalisé son YAML retrouve son texte dans l'écran, à
l'endroit où il se modifie désormais.

L'objet ``personality`` reste un singleton importé partout et son interface ne
bouge pas : les appelants font ``personality.name``, ``personality.traits``.
Ce qui change, c'est que chaque accès relit la configuration. C'est voulu et
peu coûteux (``config_service`` mémoïse), et c'est ce qui rend le rechargement
à chaud honnête : une modification s'applique au tour suivant, sans redémarrage.
"""
from emotion.circadian import CircadianProfile, profile_from_yaml
from emotion.types import Emotion
from emotion.state import Temperament, load_temperament

#: Les phases telles que le schéma les nomme.
_PHASES = ("morning", "afternoon", "evening", "night")

#: Les trois textes qui n'ont pas le droit d'être vides, et ce qu'on sert
#: quand ils le sont.
#:
#: Deux ratés mènent ici et un seul repli les couvre : le registre hors
#: d'atteinte (import avant ``migrate``, base verrouillée) et le champ vidé
#: depuis le formulaire. Le prompt met le nom juste après « Tu es » — ce n'est
#: donc pas une préférence, c'est ce qui reste prononçable.
#:
#: Nommé plutôt qu'écrit dans chaque accesseur pour que le test de cohérence
#: des défauts puisse le lire : ces valeurs doivent rester égales au ``default``
#: du ``ConfigItem`` correspondant, sinon renommer le personnage dans le schéma
#: laisserait « Mika » revenir par la porte du champ vidé.
TEXTES_OBLIGATOIRES = {
    "name": "Mika",
    "language": "fr",
    "greeting": "Hey ! Bienvenue bienvenue ~ Posez-vous, faites comme chez "
                "vous. Alors, quoi de beau aujourd'hui ?",
}


class Personality:
    """Accesseurs de personnage, tous adossés au registre.

    Aucun état : pas de cache local, pas de ``load()``. Un cache ici serait un
    troisième endroit où la valeur existe, et il faudrait l'invalider à chaque
    écriture du tableau de bord — c'est exactement ce que fait déjà
    ``config_service``.
    """

    # ── Lecture ─────────────────────────────────────────────────

    @staticmethod
    def _txt(cle: str, repli: str = "") -> str:
        """Un texte du personnage, avec un repli qui couvre les DEUX ratés.

        Le registre peut être hors d'atteinte (import avant ``migrate``, base
        verrouillée) et le champ peut avoir été vidé depuis le formulaire. Les
        trois textes qui n'ont pas le droit d'être vides — le nom, la langue,
        la salutation — passent le même repli pour les deux cas, plutôt qu'un
        ``or "Mika"`` ajouté plus loin : ce serait une deuxième valeur
        déclarée, libre de diverger du défaut du schéma le jour où on renomme
        le personnage. Ici le repli vaut le ``default`` du ``ConfigItem``, et
        un test l'épingle.
        """
        from configs.runtime import cfg_str
        return cfg_str(f"personality.{cle}", repli).strip() or repli

    @staticmethod
    def _lignes(cle: str) -> list[str]:
        from configs.runtime import cfg_list
        return [str(v).strip() for v in cfg_list(f"personality.{cle}", []) if str(v).strip()]

    # ── Identité ────────────────────────────────────────────────

    @property
    def name(self) -> str:
        # Un nom vide ouvrirait le prompt sur « Tu es , … ». Le repli n'est pas
        # une préférence, c'est ce qui reste dicible.
        return self._txt("name", TEXTES_OBLIGATOIRES["name"])

    @property
    def description(self) -> str:
        return self._txt("description")

    @property
    def language(self) -> str:
        return self._txt("language", TEXTES_OBLIGATOIRES["language"])

    @property
    def greeting(self) -> str:
        return self._txt("greeting", TEXTES_OBLIGATOIRES["greeting"])

    @property
    def tone(self) -> dict:
        """Les trois tons, les vides retirés.

        Une clé absente du dictionnaire et une clé valant la chaîne vide ne se
        distinguent pas en aval : ``to_system_prompt`` teste la vérité de la
        valeur. On rend donc un dictionnaire sans entrée vide, pour qu'un ton
        effacé retire sa ligne du prompt au lieu d'en écrire une amputée.
        """
        out = {}
        for cle in ("default", "when_excited", "when_teasing"):
            valeur = self._txt(f"tone.{cle}")
            if valeur:
                out[cle] = valeur
        return out

    @property
    def mood_greetings(self) -> dict:
        out = {}
        for cle in ("energetic", "chill", "curious"):
            valeur = self._txt(f"mood_greetings.{cle}")
            if valeur:
                out[cle] = valeur
        return out

    # ── Caractère ───────────────────────────────────────────────

    @property
    def traits(self) -> list[str]:
        return self._lignes("core_traits")

    @property
    def quirks(self) -> list[str]:
        return self._lignes("quirks")

    @property
    def vulnerabilities(self) -> list[str]:
        return self._lignes("vulnerabilities")

    @property
    def values(self) -> list[str]:
        return self._lignes("values")

    @property
    def interests(self) -> list[str]:
        return self._lignes("interests")

    @property
    def speech_patterns(self) -> list[str]:
        return self._lignes("speech_patterns")

    # ── Rythme ──────────────────────────────────────────────────

    @property
    def circadian_profile(self) -> CircadianProfile:
        """Le profil circadien, recomposé depuis les huit réglages de phase.

        Passe par ``profile_from_yaml`` plutôt que de construire le dataclass
        ici : cette fonction sait déjà écarter une phase inconnue et une ancre
        qui n'est pas une émotion, et elle est testée pour ça. Le dictionnaire
        qu'on lui donne a la forme qu'avait le bloc YAML — c'est la seule chose
        qu'il reste de lui.
        """
        from config.personality_schema import PHASE_DEFAUTS
        from configs.runtime import cfg_float, cfg_int, cfg_str

        # Le repli vient du schéma, pas d'un littéral réécrit ici : une valeur
        # sentinelle serait pire qu'inutile — ``profile_from_yaml`` fait
        # ``int(h) % 24``, donc un « -1 » signifiant « lecture ratée » se
        # rangerait silencieusement à 23 h et décalerait toute la journée.
        return profile_from_yaml({
            "phase_hours": {
                p: cfg_int(f"personality.circadian.phase_hours.{p}",
                           PHASE_DEFAUTS[p][0], mini=0, maxi=23)
                for p in _PHASES
            },
            "phase_anchors": {
                p: cfg_str(f"personality.circadian.phase_anchors.{p}",
                           PHASE_DEFAUTS[p][1])
                for p in _PHASES
            },
            "energy_peak_hour": cfg_float(
                "personality.circadian.energy_peak_hour", 14.0),
            "energy_amplitude": cfg_float(
                "personality.circadian.energy_amplitude", 0.7),
            "energy_baseline": cfg_float(
                "personality.circadian.energy_baseline", 0.55),
        })

    @property
    def temperament(self) -> Temperament:
        """Le tempérament effectif — même registre, section Émotion.

        L'accesseur reste ici parce que c'est là que tous les appelants le
        cherchent, et parce que le tempérament reste conceptuellement une
        propriété du personnage : ce sont des curseurs, pas de la prose, d'où
        un écran séparé.
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
