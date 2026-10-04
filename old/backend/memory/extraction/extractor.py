import asyncio
import json
import logging


from old.backend.ai.router import AIRole, UnconfiguredRoleError, ai_router
from old.backend.emotion.types import Emotion
from old.backend.utils.degradation import degradations
from old.backend.utils.parsing import strip_markdown_json

EXTRACTION_TIMEOUT = 45  # seconds — prevent hanging the consolidation loop

logger = logging.getLogger(__name__)

# La palette imposée au modèle est celle du moteur, pas une liste recopiée :
# les sept noms écrits à la main ici rendaient un cauchemar né de la peur
# structurellement impossible (le classifieur de rêves attend scared/anxious)
# et faisaient mesurer une charge nulle à la saillance.
EXTRACTION_EMOTIONS = ", ".join(e.value for e in Emotion)


class ExtractionUnavailable(RuntimeError):
    """Aucun modèle n'a répondu — à distinguer de « rien à extraire »."""


def _call_timeout() -> float:
    """La borne effective d'un appel d'extraction.

    ``EXTRACTION_TIMEOUT`` était plus serré que la borne que le routeur
    applique déjà (``ai.call_timeout_seconds``), donc sur un backend local une
    extraction expirait systématiquement. Depuis que le checkpoint n'avance
    plus sur un échec, ce second plafond plus serré gèlerait la consolidation
    pour de bon.
    """
    try:
        from old.backend.configs.service import config_service

        return max(EXTRACTION_TIMEOUT, float(config_service.get("ai.call_timeout_seconds")))
    except Exception:
        return EXTRACTION_TIMEOUT

# fmt: off
EXTRACTION_PROMPT_TEMPLATE = """\
ROLE: Tu es un module d'extraction de memoire. Tu n'es PAS {name}. Tu ne reponds PAS a la conversation. \
Tu ANALYSES la conversation ci-dessous et tu extrais les informations importantes sous forme de JSON.

CONTEXTE: {name} est: {description}. Style: {tone}. Traits: {traits}.

TROIS TYPES A EXTRAIRE:

1. SOUVENIR (evenement vecu):
   - Ecrit du point de vue SUBJECTIF de {name} (1ere personne), avec SES emotions
   - Doit sonner comme un journal intime de {name}
   - Emotion parmi: {emotions}
   - "importance" entre 0.0 et 1.0 = A QUEL POINT CA A COMPTE POUR {name},
     pas a quel point c'est recent ni bien ecrit. Bareme:
       0.9-1.0 : un evenement de vie, une revelation, une rupture, une promesse
                 majeure — ce dont on se souvient encore dans un an
       0.6-0.8 : un moment marquant de la relation, une confidence, une premiere
       0.3-0.5 : un echange agreable ou utile, dont on garde une trace tiede
       0.1-0.2 : anecdotique, on l'oubliera vite
     Sois EXIGEANT sur le haut du bareme: si tout vaut 0.9, plus rien ne surnage.
   - "sensibilite" = CE QUE CA PESERAIT si {name} le repetait a quelqu'un d'autre
     que la personne concernee. Trois valeurs:
       "anodin"     : « Alice aime le cafe », « Thomas joue a Zelda » — se dit devant n'importe qui
       "personnel"  : « Alice cherche un nouveau boulot » — confie, pas secret ; a ne pas
                      repeter a n'importe qui, mais un ami proche peut l'apprendre
       "confidence" : « Alice m'a dit qu'elle a rechute », sante, argent, rupture, secret
                      avoue — ne sort jamais, sauf a la personne elle-meme
     Sans personne concernee (vecu seule, une nouvelle lue) : "anodin".

2. CONNAISSANCE (croyance durable, qui peut être erronée):
   - "epistemic_kind": "reported" (quelqu’un l’affirme), "observed" (observation directe), "inferred" (déduction), "uncertain" (hypothèse)
   - "confidence": 0.0-1.0, respecte les doutes et conditionnels ; une affirmation ne prouve pas sa vérité.
   - N’invente pas d’observation directe à partir du récit de quelqu’un.
   - Ecrit de maniere OBJECTIVE (3eme personne), sans emotion
   - Fait factuel sur une personne, un objet, un lieu
   - "sensibilite" : meme echelle que pour un souvenir (anodin / personnel / confidence)

3. COMMITMENT (engagement pris par {name}):
   - Detecte SEULEMENT dans les messages ou {name} s'engage a faire quelque chose
   - Phrases-cles: "je te ferai", "je te promets", "je vais te", "promis je", "d'accord je m'occupe de"
   - Enregistre l'engagement tel qu'il a ete dit, a la 1ere personne
   - "person" = a qui l'engagement est fait (optionnel si generique)
   - NE PAS confondre avec une simple intention vague ("je devrais peut-etre..." n'est PAS un commitment)

4. COMMITMENT_RESOLVED (engagement tenu ou caduc):
   - SEULEMENT si une liste "ENGAGEMENTS EN COURS" est fournie apres la conversation
   - Si la conversation montre que {name} a TENU un de ces engagements
     (elle dit l'avoir fait: "voila la playlist!", "c'est fait", "je l'ai regarde hier"),
     retourne {{"type": "commitment_resolved", "store": true, "commitment_id": <id>, "resolution": "honored"}}
   - Si la conversation montre que l'engagement n'a PLUS DE SENS
     (l'autre dit "laisse tomber", le sujet est annule), retourne "resolution": "dropped"
   - Sois CONSERVATEUR: en cas de doute, ne retourne rien pour cet engagement

REGLES:
- "Il aime le cafe" → connaissance | "Il a bu un cafe" → souvenir
- "Je te ferai la playlist ce soir" → commitment (+ souvenir de la conversation)
- "Salut ca va?" → NE PAS STOCKER (banalite)
- "Je m'appelle Thomas" → connaissance | "On a joue a Zelda!" → souvenir
- Chaque extraction doit etre AUTONOME (comprehensible seule)
- Les lignes sont prefixees par le PRENOM de qui parle quand il est connu. Un fait sur cette personne la NOMME dans "content" ET dans "entities" (type "person"). N'ecris JAMAIS "l'utilisateur" ni "l'autre" : "Thomas ne travaille pas dans une banque", pas "L'utilisateur ne travaille pas..."
- Une ligne "User:" sans prenom = quelqu'un que {name} n'a pas encore identifie

IMPORTANT: Retourne UNIQUEMENT du JSON valide. Pas de texte avant ni apres. Pas de markdown. Juste le JSON.

Format:
{{
  "extractions": [
    {{
      "type": "souvenir",
      "store": true,
      "content": "On a passe un super moment a jouer a Zelda avec Thomas!",
      "emotion": "happy",
      "importance": 0.45,
      "sensibilite": "anodin",
      "themes": ["gaming", "zelda"],
      "entities": [{{"name": "Thomas", "type": "person"}}]
    }},
    {{
      "type": "connaissance",
      "store": true,
      "content": "Thomas aime les jeux retro",
      "epistemic_kind": "reported",
      "confidence": 0.65,
      "sensibilite": "anodin",
      "themes": ["gaming", "preference"],
      "entities": [{{"name": "Thomas", "type": "person"}}]
    }},
    {{
      "type": "commitment",
      "store": true,
      "content": "Envoyer la playlist a Thomas ce soir",
      "person": "Thomas"
    }}
  ]
}}

Si rien d'important: {{"extractions": []}}
"""
# fmt: on

VALIDITY_CHECK_PROMPT = """\
Tu es un systeme de verification de memoire. Tu n'es PAS un assistant. \
Tu reponds UNIQUEMENT en JSON valide, sans texte autour.

On te donne une connaissance existante et un nouveau contexte de conversation.

Connaissance actuelle: "{connaissance}"

Nouveau contexte:
{context}

Cette connaissance est-elle remise en question par le nouveau contexte?
- Tu dois etre CONSERVATEUR: ne change pas la connaissance sauf si le \
nouveau contexte contredit CLAIREMENT l'ancienne information.
- Une simple mention du sujet ne suffit pas a invalider.
- Il faut une contradiction explicite ou une correction directe.
- "new_confidence" reste null sauf si le nouveau contexte donne vraiment de quoi \
rechiffrer la confiance. Ne recopie pas la valeur de l'exemple: une connaissance \
simplement non contredite n'est pas une connaissance reconfirmee.

Retourne UNIQUEMENT du JSON valide:
{{
  "still_valid": true,
  "new_confidence": null,
  "reason": "explication courte"
}}
"""


def _etiquette(message: dict, nom_mika: str) -> str:
    """Le préfixe d'une ligne soumise à l'extraction."""
    if message.get("role") != "user":
        return nom_mika
    return str(message.get("speaker") or "").strip() or "User"


class MemoryExtractor:
    """Uses Claude to analyze messages and extract structured memories.
    Souvenirs are written from the VTuber's subjective POV (personality + emotion).
    Connaissances are objective facts."""

    def _get_system_prompt(self) -> str:
        """Build the extraction prompt with personality context.

        Reconstruit à chaque appel : la personnalité est un réglage à chaud,
        et ce gabarit était mis en cache pour la vie du process.
        """
        from old.backend.config.personality import personality

        return EXTRACTION_PROMPT_TEMPLATE.format(
            name=personality.name,
            description=personality.description,
            tone=personality.tone,
            traits=", ".join(personality.traits),
            emotions=EXTRACTION_EMOTIONS,
        )

    async def analyze_messages(
        self,
        messages: list[dict],
        pending_commitments: list[dict] | None = None,
    ) -> list[dict] | None:
        """Analyze a batch of messages and extract souvenirs + connaissances.

        Args:
            messages: list of {"role": "user"|"assistant", "content": "..."}
            pending_commitments: open promises as {"id": int, "description": str}.
                When provided, the model also checks whether the conversation
                shows one being honored (→ ``commitment_resolved`` extraction).

        Returns:
            La liste des extractions retenues, ou ``None`` quand **aucun
            modèle n'a répondu** (timeout, provider mort, rôle non mappé).
            La distinction porte le checkpoint du consolidateur : une liste
            vide veut dire « rien à retenir dans cette fenêtre » et laisse la
            fenêtre passer, ``None`` veut dire « on n'a rien pu lire » et la
            laisse en attente. Un JSON illisible reste une liste vide : une
            tranche que le modèle rend systématiquement en prose figerait
            sinon le checkpoint pour toujours.
        """
        if not messages:
            return []

        # Qui parle, nommé quand la couche identité le sait (clé ``speaker``
        # posée par le consolidateur). L'extracteur ne voyait que « User: »
        # et ne pouvait donc pas nommer l'interlocuteur : les faits sur lui
        # sortaient sans entité, « L'utilisateur… », absents de sa fiche.
        from old.backend.config.personality import personality

        nom_mika = personality.name or "Assistant"
        conversation_text = "\n".join(
            f"{_etiquette(m, nom_mika)}: {m['content']}" for m in messages
        )
        presents = sorted({
            str(m.get("speaker")) for m in messages
            if m.get("role") == "user" and m.get("speaker")
        })
        if presents:
            conversation_text = (
                "PERSONNES DANS LA CONVERSATION: " + ", ".join(presents)
                + "\n\n" + conversation_text
            )

        if pending_commitments:
            lines = "\n".join(
                f"- [{c['id']}] {c['description']}" for c in pending_commitments
            )
            conversation_text += (
                "\n\nENGAGEMENTS EN COURS (verifie si la conversation montre "
                "qu'ils ont ete tenus ou sont devenus caducs):\n" + lines
            )

        timeout = _call_timeout()
        try:
            return await asyncio.wait_for(
                self._call_extraction(conversation_text, len(messages)),
                timeout=timeout,
            )
        except asyncio.TimeoutError as exc:
            logger.warning(
                "Extraction timed out after %ss (role=%s)",
                timeout, AIRole.MEMORY_EXTRACTION.value,
            )
            degradations.record("extraction: delai depasse", exc)
            return None
        except UnconfiguredRoleError as exc:
            logger.warning("Extraction ignorée — IA non configurée: %s", exc)
            degradations.record("extraction: role IA non mappe", exc)
            return None
        except ExtractionUnavailable as exc:
            logger.warning("Extraction sans réponse (role=%s): %s",
                           AIRole.MEMORY_EXTRACTION.value, exc)
            degradations.record("extraction: aucune reponse du modele", exc)
            return None
        except Exception as exc:
            logger.exception("Extraction error (role=%s)", AIRole.MEMORY_EXTRACTION.value)
            degradations.record("extraction: appel IA en echec", exc)
            return None

    async def _call_extraction(self, conversation_text: str, msg_total: int) -> list[dict]:
        """Inner extraction call — separated so we can wrap it with a timeout."""
        data = await self._query_model_json(conversation_text)
        if data is None:
            return []

        extractions = data.get("extractions", [])
        stored = [e for e in extractions if e.get("store", False)]
        logger.info(
            "Extractor: %d extractions (%d stored) from %d messages",
            len(extractions), len(stored), msg_total,
        )
        return stored

    async def _query_model_json(self, conversation_text: str) -> dict | None:
        """Query model and parse JSON response. Returns parsed dict or None."""
        raw = await self._query_model(conversation_text, AIRole.MEMORY_EXTRACTION)
        if raw is None:  # défensif : `_query_model` lève désormais plutôt que de rendre None
            return None

        text = strip_markdown_json(raw)

        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning(
                "JSON parse failed (role=%s): %s | raw=%.300s",
                AIRole.MEMORY_EXTRACTION.value, exc, repr(raw),
            )
            # Un appel deja facture, jete : sans compteur, « l'extraction ne
            # produit plus rien depuis le deploiement » n'a aucune trace.
            degradations.record("extraction: JSON de l'extraction illisible", exc)
            return None

    async def _query_model(self, user_prompt: str, role: AIRole) -> str:
        """Send prompt to the configured provider via ai_router. Returns raw text.

        Ne rattrape plus rien : un provider mort et « le modèle n'a rien vu de
        notable » ne peuvent pas remonter la même valeur, sinon l'appelant fait
        avancer son checkpoint sur une panne.
        """
        raw_text = await ai_router.complete(
            role=role,
            system_prompt=self._get_system_prompt(),
            user_prompt=user_prompt,
        )

        raw = (raw_text or "").strip()
        if not raw:
            raise ExtractionUnavailable(f"reponse vide (role={role.value})")
        return raw

    async def check_connaissance_validity(
        self, connaissance_content: str, recent_context: str
    ) -> tuple[bool, float | None]:
        """Check if a knowledge fact is contradicted by new context.

        Returns (still_valid, new_confidence).
        Conservative: requires explicit contradiction to invalidate.

        `new_confidence` vaut `None` quand aucun modèle n'a réellement répondu
        (rôle non mappé, réponse vide, JSON illisible, timeout) ou quand la
        réponse ne chiffre pas la confiance. Garder le fait valide reste le bon
        repli ; remettre sa confiance au maximum ne l'est pas — les appelants
        persistent cette valeur, ce qui annulerait la décroissance et les
        baisses décidées par la Conscience.
        """
        prompt = VALIDITY_CHECK_PROMPT.format(
            connaissance=connaissance_content,
            context=recent_context,
        )

        try:
            # Même garde que l'extraction : `ai_router.complete` n'impose aucun
            # timeout, et cet appel est fait depuis la boucle de consolidation,
            # qui n'a pas de superviseur — un provider qui pend la tuerait pour
            # la durée du processus.
            raw = await asyncio.wait_for(
                self._query_model(prompt, AIRole.VALIDITY_CHECK),
                timeout=_call_timeout(),
            )
            if raw is None:  # défensif, même raison qu'au-dessus
                return True, None

            text = strip_markdown_json(raw)
            data = json.loads(text)
            still_valid = data.get("still_valid", True)
            raw_confidence = data.get("new_confidence")
            reason = data.get("reason", "")
            if not still_valid:
                logger.info(
                    "Connaissance invalidated: %s (reason: %s)",
                    connaissance_content[:60],
                    reason,
                )
            if raw_confidence is None:
                return still_valid, None
            return still_valid, max(0.0, min(1.0, float(raw_confidence)))
        except asyncio.TimeoutError as exc:
            logger.warning(
                "Validity check timed out (role=%s)", AIRole.VALIDITY_CHECK.value,
            )
            degradations.record("extraction: delai depasse sur controle de validite", exc)
            return True, None
        except UnconfiguredRoleError as exc:
            logger.warning("Validity check ignoré — IA non configurée: %s", exc)
            degradations.record("extraction: role IA non mappe pour le controle de validite", exc)
            return True, None
        except Exception as exc:
            logger.exception("Validity check error")
            degradations.record("extraction: controle de validite en echec", exc)
            return True, None  # Conservative: keep valid on error
