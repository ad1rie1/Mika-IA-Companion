"""La boucle d'outils — un seul corps, un adaptateur par famille d'API.

Quatre boucles quasi identiques vivaient dans ``claude.py``,
``_openai_tools.py``, ``ollama_provider.py`` et ``gemini_provider.py`` :
même squelette (appeler le modèle, lire ses appels d'outils, exécuter les
handlers, renvoyer les résultats, recommencer), et les correctifs de boucle
se faisaient en trois ou quatre exemplaires — ou en un seul, et les autres
dérivaient (la troncature ``max_tokens`` n'existait que chez Claude ; le tour
``tool`` d'Ollama a perdu son nom pendant des mois). Ce module est le corps
unique ; ce qui diffère d'une API à l'autre tient dans un adaptateur.

**Ce qui est ici, une fois pour toutes** — l'itération bornée par
``max_turns``, le décodage des arguments (un dict déjà décodé ou une chaîne
JSON), l'appel du handler avec ses trois issues (outil inconnu, arguments
illisibles, handler qui lève — aucune ne remonte, toutes reviennent au
modèle), la liste des outils réellement appelés, le rejeu d'une réponse
coupée en plein appel d'outil avec un plafond doublé (borné par
``TOOL_CALL_CAP_CEILING``, sinon ``TRUNCATED_TOOL_CALL_MARKER``), le texte
de repli quand la boucle s'épuise, et la fermeture (relevé d'usage) dans un
``finally`` — une boucle annulée à l'itération six compte ses six
itérations.

**Ce que l'adaptateur apporte** — le fil de messages dans la forme native,
la sérialisation des déclarations d'outils (triées par nom chez Claude pour
un préfixe stable), la requête elle-même (avec ses reprises de paramètres :
``_create_message`` chez Claude, ``create_chat_completion`` et son
``ParamMemo`` côté OpenAI/GLM, ``_chat`` et son retry ``think`` chez
Ollama), la lecture d'une réponse en ``Reponse``, le rejeu du tour
assistant dans le fil, la forme du résultat d'outil (bloc ``tool_result``
avec ``is_error`` et point de cache mobile chez Claude, tour ``tool`` par
appel côté OpenAI/Ollama, ``function_response`` chez Gemini) et le relevé
d'usage.

Ajouter un provider = une classe courte héritant de ``AdaptateurOutils``
(quatre méthodes, ``clore`` en option) + une classe provider qui construit
le fil et appelle ``executer_la_boucle``. Voir ``_openai_tools.py`` pour
l'adaptateur le plus court.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Plafond du second essai quand une réponse est tronquée en plein appel
# d'outil. Doubler sans borne finirait au-delà de ce que le SDK Anthropic
# accepte hors streaming — son garde-fou de délai se déclenche vers 21 000
# jetons de sortie.
TOOL_CALL_CAP_CEILING = 16384
# Ce que le texte rendu porte quand même le second essai n'a pas suffi :
# l'appel n'a pas eu lieu, et le dire vaut mieux qu'une réponse qui s'arrête
# net comme si le modèle avait fini.
TRUNCATED_TOOL_CALL_MARKER = "[réponse tronquée avant l'appel d'outil]"
# Boucle épuisée sans qu'aucun texte n'ait été produit.
MAX_TURNS_MARKER = "[max_turns atteint avant réponse finale]"


@dataclass
class AppelOutil:
    """Un appel d'outil tel que le modèle l'a émis, dans un vocabulaire commun.

    ``arguments`` est soit un dict déjà décodé (Claude, Gemini, Ollama), soit
    la chaîne JSON brute (OpenAI) : c'est la boucle qui décode, pour que
    « arguments illisibles » soit une issue traitée une seule fois.
    """

    name: str
    arguments: Any
    id: str | None = None


@dataclass
class Reponse:
    """Ce que la boucle lit d'une réponse, quelle que soit l'API.

    ``texte`` — la part de la réponse à rendre à l'appelant. L'adaptateur
    décide de ce qui compte : chez Claude les blocs texte accompagnant un
    ``tool_use`` font partie de la réponse ; côté OpenAI/Ollama/Gemini le
    ``content`` d'un tour porteur d'appels est du brouillon et n'est pas
    rendu (seule la réponse finale l'est).
    ``coupee_en_plein_appel`` — la sortie a heurté le plafond de jetons avec
    un appel d'outil entamé : la boucle rejoue l'itération une fois.
    ``terminee`` — le modèle dit avoir fini (fin de tour, refus) : la boucle
    s'arrête même si des appels figurent dans la réponse.
    """

    texte: str = ""
    appels: list[AppelOutil] = field(default_factory=list)
    coupee_en_plein_appel: bool = False
    terminee: bool = False


@dataclass
class Issue:
    """L'issue d'un appel d'outil, à rendre au modèle.

    ``genre`` : ``ok`` (le handler a répondu, ``resultat`` porte sa réponse),
    ``inconnu`` (aucun outil de ce nom), ``arguments`` (JSON illisible),
    ``exception`` (le handler a levé). Hors ``ok``, ``erreur`` porte le
    message. Un handler qui répond MCP-style ``isError`` n'a pas levé — il
    est ``ok`` avec ``en_echec()`` vrai.
    """

    appel: AppelOutil
    genre: str = "ok"
    resultat: Any = None
    erreur: str | None = None

    def en_echec(self) -> bool:
        if self.erreur is not None:
            return True
        # Les handlers du repo parlent MCP et signalent l'échec en camelCase
        # (``isError``) ; on accepte aussi le snake_case par tolérance.
        return isinstance(self.resultat, dict) and bool(
            self.resultat.get("isError") or self.resultat.get("is_error")
        )


class AdaptateurOutils:
    """Ce qu'une famille d'API fournit à la boucle. Une instance par tour.

    L'adaptateur possède le fil de messages (il l'a construit dans sa forme
    native et y empile les allers-retours), la sérialisation des outils et
    l'accès au client. La boucle ne voit que ces cinq méthodes.
    """

    #: Nom lisible dans les journaux (« Claude », « OpenAI », « GLM »…).
    LABEL = "?"

    async def appeler(self, max_tokens: int):
        """Une requête au modèle sur le fil courant ; renvoie la réponse brute.

        ``max_tokens`` est le plafond de *cette* requête : il double une fois
        quand la précédente a été coupée en plein appel d'outil.
        """
        raise NotImplementedError

    def lire(self, brut) -> Reponse:
        """Traduit une réponse brute en ``Reponse``."""
        raise NotImplementedError

    def rejouer_le_tour(self, brut, reponse: Reponse) -> None:
        """Ajoute au fil le tour assistant qui a émis les appels."""
        raise NotImplementedError

    def rendre_les_resultats(self, issues: list[Issue]) -> None:
        """Ajoute au fil les résultats des appels, dans la forme native."""
        raise NotImplementedError

    def clore(self) -> None:
        """Fin de boucle, réussie ou non (``finally``). Relevé d'usage, etc."""


async def executer_la_boucle(
    adaptateur: AdaptateurOutils,
    *,
    tools: list,
    max_tokens: int,
    max_turns: int,
) -> tuple[str, list[str]]:
    """Le corps de boucle. Renvoie ``(texte, noms des outils appelés)``.

    Un outil compte comme *appelé* quand son handler a été invoqué — qu'il
    ait répondu ou levé. Un nom inconnu ou des arguments illisibles
    reviennent au modèle comme une erreur sans figurer dans la liste : rien
    n'a été appelé.
    """
    handlers = {t.name: t.handler for t in tools}
    textes: list[str] = []
    appeles: list[str] = []
    cap = max_tokens
    cap_releve = False

    try:
        for _ in range(max_turns):
            brut = await adaptateur.appeler(cap)
            reponse = adaptateur.lire(brut)

            if (
                reponse.coupee_en_plein_appel
                and not cap_releve
                and cap < TOOL_CALL_CAP_CEILING
            ):
                # Tronquée en plein appel d'outil : l'appel est là, mais la
                # sortie s'est arrêtée avant sa fin. Sortir comme si le
                # modèle avait fini ferait disparaître l'appel sans un mot.
                # Cette itération est rejouée une fois avec un plafond doublé
                # (borné) ; le texte de l'essai tronqué n'est pas gardé.
                cap_releve = True
                cap = min(cap * 2, TOOL_CALL_CAP_CEILING)
                logger.warning(
                    "%s: réponse tronquée (max_tokens) en plein appel d'outil "
                    "— nouvel essai avec max_tokens=%d", adaptateur.LABEL, cap,
                )
                brut = await adaptateur.appeler(cap)
                reponse = adaptateur.lire(brut)

            if reponse.texte:
                textes.append(reponse.texte)

            if reponse.coupee_en_plein_appel:
                logger.warning(
                    "%s: appel d'outil encore tronqué à max_tokens=%d — "
                    "l'appel n'a pas eu lieu", adaptateur.LABEL, cap,
                )
                textes.append(TRUNCATED_TOOL_CALL_MARKER)
                break
            if reponse.terminee or not reponse.appels:
                break

            adaptateur.rejouer_le_tour(brut, reponse)

            issues: list[Issue] = []
            for appel in reponse.appels:
                issue = await _executer(handlers, appel, adaptateur.LABEL)
                if issue.genre in ("ok", "exception"):
                    appeles.append(appel.name)
                issues.append(issue)
            adaptateur.rendre_les_resultats(issues)
        else:
            logger.warning(
                "Boucle d'outils %s: max_turns=%d atteint sans réponse finale",
                adaptateur.LABEL, max_turns,
            )
            if not textes:
                textes.append(MAX_TURNS_MARKER)
    finally:
        adaptateur.clore()

    if appeles:
        logger.info("%s tools used in this turn: %s", adaptateur.LABEL, appeles)
    return "\n\n".join(textes), appeles


async def _executer(handlers: dict, appel: AppelOutil, label: str) -> Issue:
    """Un appel d'outil : aucune issue ne lève, toutes reviennent au modèle."""
    handler = handlers.get(appel.name)
    if handler is None:
        return Issue(appel, genre="inconnu", erreur=f"unknown tool '{appel.name}'")

    args = appel.arguments
    if isinstance(args, str):
        try:
            args = json.loads(args) if args else {}
        except json.JSONDecodeError as exc:
            return Issue(
                appel, genre="arguments", erreur=f"invalid JSON arguments: {exc}",
            )
    args = dict(args or {})

    logger.info("%s called tool: %s (input=%s)", label, appel.name, str(args)[:200])
    try:
        resultat = await handler(args)
    except Exception as exc:  # noqa: BLE001 — l'erreur retourne au modèle
        logger.warning("Tool '%s' handler raised: %s", appel.name, exc)
        return Issue(appel, genre="exception", erreur=str(exc))
    return Issue(appel, resultat=resultat)


def contenu_json(issue: Issue) -> str:
    """Le résultat d'un appel sérialisé en JSON — la forme OpenAI et Ollama.

    Une erreur voyage comme ``{"error": …}`` : le modèle la lit et se
    rattrape, au lieu qu'elle remonte et tue le tour.
    """
    if issue.erreur is not None:
        return json.dumps({"error": issue.erreur})
    try:
        return json.dumps(issue.resultat, ensure_ascii=False, default=str)
    except (TypeError, ValueError):  # ValueError : référence circulaire
        return json.dumps({"result": str(issue.resultat)})
