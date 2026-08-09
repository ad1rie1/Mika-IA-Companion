"""Passe de préparation — le réflexe mental qui précède la réponse.

Avant de répondre, un petit modèle (rôle ``PREPARATION``) décide ce qu'il
faut aller rechercher dans la mémoire : quelles requêtes, dans quel étage
(souvenirs vécus, connaissances, échanges bruts passés), à propos de qui.
Il produit aussi une **note de focus** — une pensée pré-verbale courte qui
oriente la réponse.

Propriétés architecturales, dans l'ordre d'importance :

1. **Fail-open partout.** La passe est une amélioration, jamais une
   dépendance : rôle non mappé, timeout, JSON illisible → le tour part avec
   le rappel spéculatif actuel, strictement identique à avant.
2. **La réponse n'attend jamais la réflexion** au-delà de la deadline
   (``ai.preparation.deadline_ms``) — le plan tourne en parallèle du rappel
   spéculatif, mesuré depuis la création de la tâche.
3. **Skip-gate à coût nul** : le small talk ne déclenche rien.
4. Les tours de conscience ne passent pas ici (gate ``is_internal_person``) :
   les résumés d'observations *sont* déjà le plan (multi-requêtes du bridge).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field

from utils.degradation import degradations

logger = logging.getLogger(__name__)

# Types de rappel du menu fermé. Tout autre type renvoyé par le modèle est
# ignoré silencieusement (le plan reste utilisable).
RAPPEL_TYPES = ("souvenirs", "connaissances", "echanges_passes")

NOTE_MAX_CHARS = 200

# Lexique small-talk : messages qui ne méritent jamais une passe de
# préparation. Comparés en minuscules, ponctuation/emoji retirés.
_SMALL_TALK = {
    "salut", "coucou", "bonjour", "bonsoir", "hello", "yo", "hey",
    "ok", "oui", "non", "merci", "mdr", "lol", "ptdr", "haha", "hihi",
    "bonne nuit", "a plus", "à plus", "bye", "ciao",
    "ca va", "ça va", "et toi", "cool", "super", "top", "d'accord", "daccord",
}

_PUNCT_RE = re.compile(r"[^\w\sàâäéèêëîïôöùûüç'-]", re.UNICODE)
_WORD_RE = re.compile(r"\w", re.UNICODE)


@dataclass(frozen=True)
class Rappel:
    type: str
    query: str
    person: str = ""      # nom d'entité ou handle (echanges_passes)
    depuis: str = ""      # AAAA-MM-JJ optionnel
    jusqua: str = ""      # AAAA-MM-JJ optionnel


@dataclass(frozen=True)
class PreparationPlan:
    rappels: tuple[Rappel, ...] = ()
    note_de_focus: str = ""
    # À quel point CE tour est émotionnellement chargé (0..1). Monte les poids
    # émotion/humeur du re-ranking : quand la conversation touche à quelque
    # chose de fort, le rappel attend davantage aux souvenirs marquants —
    # exactement le réflexe humain. 0 = tour ordinaire (aucun effet).
    charge_emotionnelle: float = 0.0

    @property
    def memory_queries(self) -> list[str]:
        """Les requêtes destinées au rappel curé (souvenirs/connaissances)."""
        return [
            r.query for r in self.rappels
            if r.type in ("souvenirs", "connaissances") and r.query
        ]

    @property
    def exchange_rappels(self) -> list[Rappel]:
        return [r for r in self.rappels if r.type == "echanges_passes" and r.query]


# ── Skip-gate (0 LLM) ────────────────────────────────────────────


def should_prepare(message: str, person_id: str) -> bool:
    """Décide si le tour mérite une passe de préparation.

    Heuristique pure — chaque « non » économise un appel LLM et sa latence.
    """
    from identity.trust import is_internal_person

    if is_internal_person(person_id):
        return False

    text = (message or "").strip()
    if not _WORD_RE.search(text):
        return False  # emoji/ponctuation purs

    normalized = _PUNCT_RE.sub("", text.lower()).strip()
    if normalized in _SMALL_TALK:
        return False

    try:
        from configs.service import config_service
        min_chars = int(config_service.get("ai.preparation.min_chars"))
    except Exception:
        min_chars = 20
    if len(text) < min_chars and "?" not in text:
        return False

    # Rôle non mappé = passe désactivée (le défaut sain en local). Résolu
    # ici pour ne même pas créer la tâche.
    try:
        from ai.router import AIRole, UnconfiguredRoleError, ai_router
        ai_router.resolve(AIRole.PREPARATION)
    except UnconfiguredRoleError:
        return False
    except Exception as exc:
        degradations.record("preparation: resolution role", exc)
        return False
    return True


# ── L'appel de plan ──────────────────────────────────────────────

_SYSTEM_PROMPT = """Tu es le réflexe de préparation mentale de {name}. Avant qu'elle réponde, tu décides ce qu'il faut aller rechercher dans sa mémoire. Tu ne réponds JAMAIS au message. Tu renvoies UNIQUEMENT un objet JSON, rien d'autre.

Types de rappel disponibles (menu fermé, 0 à {max_rappels} rappels) :
- "souvenirs" : moments qu'elle a vécus (query = ce dont il faut se souvenir)
- "connaissances" : faits qu'elle a appris (query = le fait à vérifier)
- "echanges_passes" : ce qui s'est déjà dit dans les conversations (query ; optionnel : person = prénom ou identifiant de la personne concernée, depuis/jusqua en AAAA-MM-JJ)

"note_de_focus" : une pensée pré-verbale courte (max {note_max} caractères) qui oriente la réponse — ce que {name} devrait garder en tête. Chaîne vide si rien d'utile.

"charge_emotionnelle" : nombre entre 0 et 1 — à quel point ce message touche à quelque chose d'émotionnellement fort (deuil, dispute, aveu, grande joie...). 0 pour un échange ordinaire ou factuel. Élevé → {name} se souviendra d'abord de ce qui l'a marquée.

Un message qui ne fait référence à rien de passé ni à personne mérite un plan vide : {{"rappels":[],"note_de_focus":"","charge_emotionnelle":0}}.

Format STRICT :
{{"rappels":[{{"type":"...","query":"...","person":"","depuis":"","jusqua":""}}],"note_de_focus":"...","charge_emotionnelle":0}}"""


def _system_prompt(max_rappels: int) -> str:
    from config.personality import personality

    return _SYSTEM_PROMPT.format(
        name=getattr(personality, "name", "Mika"),
        max_rappels=max_rappels,
        note_max=NOTE_MAX_CHARS,
    )


def _user_prompt(message: str, history: list[dict], person_id: str) -> str:
    lines = ["DERNIERS ÉCHANGES :"]
    for m in (history or [])[-6:]:
        role = "Elle" if m.get("role") == "assistant" else "Lui"
        content = (m.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content[:300]}")
    lines.append("")
    lines.append(f"MESSAGE REÇU (de {person_id or 'inconnu'}) :")
    lines.append(message)
    return "\n".join(lines)


def _parse_plan(raw: str, max_rappels: int) -> PreparationPlan | None:
    """Parse tolérant : première structure JSON trouvée, types inconnus
    ignorés, note bornée. Tout échec → None (fail-open)."""
    from utils.parsing import strip_markdown_json

    text = strip_markdown_json(raw or "")
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    rappels: list[Rappel] = []
    for entry in data.get("rappels") or []:
        if not isinstance(entry, dict):
            continue
        rtype = str(entry.get("type") or "").strip()
        query = str(entry.get("query") or "").strip()
        if rtype not in RAPPEL_TYPES or not query:
            continue
        rappels.append(Rappel(
            type=rtype,
            query=query[:300],
            person=str(entry.get("person") or "").strip()[:100],
            depuis=str(entry.get("depuis") or "").strip()[:10],
            jusqua=str(entry.get("jusqua") or "").strip()[:10],
        ))
        if len(rappels) >= max_rappels:
            break

    note = str(data.get("note_de_focus") or "").strip()[:NOTE_MAX_CHARS]

    # Charge émotionnelle : tolérante (nombre ou chaîne numérique), bornée
    # [0,1]. Toute valeur illisible → 0.0 (tour ordinaire), jamais d'erreur.
    try:
        charge = float(data.get("charge_emotionnelle") or 0.0)
    except (TypeError, ValueError):
        charge = 0.0
    charge = max(0.0, min(1.0, charge))

    return PreparationPlan(
        rappels=tuple(rappels), note_de_focus=note, charge_emotionnelle=charge,
    )


async def prepare(
    message: str,
    history: list[dict],
    person_id: str,
    deadline_s: float,
) -> PreparationPlan | None:
    """Un appel du rôle PREPARATION → plan structuré, ou None (fail-open)."""
    from ai.router import AIRole, ai_router

    try:
        from configs.service import config_service
        max_rappels = int(config_service.get("ai.preparation.max_rappels"))
    except Exception:
        max_rappels = 3

    try:
        raw = await ai_router.complete(
            role=AIRole.PREPARATION,
            system_prompt=_system_prompt(max_rappels),
            user_prompt=_user_prompt(message, history, person_id),
            timeout=deadline_s,
            max_tokens=400,
        )
    except Exception as exc:
        degradations.record("preparation: appel du plan", exc)
        return None

    try:
        plan = _parse_plan(raw, max_rappels)
        if plan is None:
            raise ValueError(f"plan illisible: {(raw or '')[:120]}")
        return plan
    except ValueError as exc:
        degradations.record("preparation: parse du plan", exc)
        return None


# ── Exécution du plan ────────────────────────────────────────────

EXEC_BUDGET_S = 0.7


@dataclass
class PlanResults:
    memory_queries: list[str] = field(default_factory=list)
    exchange_hits: list = field(default_factory=list)


async def execute_plan(plan: PreparationPlan, person_id: str) -> PlanResults:
    """Exécute les intents du plan, borné par ``EXEC_BUDGET_S``.

    Les intents souvenirs/connaissances ne coûtent rien ici : leurs requêtes
    rejoignent le rappel multi-requêtes du retriever.

    Les intents ``echanges_passes`` interrogent l'étage épisodique, sous la
    MÊME politique « own identity only » que la voie chaude
    (``retriever._episodic_lane``). Le planificateur est bien un consommateur
    interne, mais sa SORTIE ne l'est pas : les chunks remontent mot pour mot
    dans le bloc mémoire du tour de conversation. Un `person` fourni par le
    petit modèle suffisait donc à faire lire à Bob le verbatim des DM de
    Thomas. Seul un appelant interne (la conscience) garde l'accès croisé.

    Timeout → partiels conservés.
    """
    from datetime import datetime

    from identity.trust import is_internal_person

    results = PlanResults(memory_queries=plan.memory_queries)
    exchange_rappels = plan.exchange_rappels
    if not exchange_rappels:
        return results

    from memory.episodic import api as episodic_api

    interne = is_internal_person(person_id)
    if interne:
        own_scope: list[str] = []
    else:
        from pipeline.context import own_handles

        own_scope = await own_handles(person_id)

    def _parse_date(s: str):
        try:
            return datetime.fromisoformat(s) if s else None
        except ValueError:
            return None

    async def _one(rappel: Rappel):
        kwargs = {
            "n": 3,
            "since": _parse_date(rappel.depuis),
            "until": _parse_date(rappel.jusqua),
        }
        if interne:
            return await episodic_api.search_exchanges(
                rappel.query, person=rappel.person or None, **kwargs,
            )
        if rappel.person:
            cible = await episodic_api.resolve_person_handles(rappel.person)
            if not set(cible) & set(own_scope):
                # La demande porte sur quelqu'un d'autre. On n'exécute pas :
                # `person=None` retomberait sur tout l'index, ce qui est la
                # même fuite sans même un nom à blâmer.
                logger.debug(
                    "Intent echanges hors perimetre ignore (cible=%s)",
                    rappel.person,
                )
                return []
        return await episodic_api.search_exchanges(
            rappel.query, handles=own_scope, **kwargs,
        )

    try:
        pages = await asyncio.wait_for(
            asyncio.gather(*[_one(r) for r in exchange_rappels],
                           return_exceptions=True),
            timeout=EXEC_BUDGET_S,
        )
    except asyncio.TimeoutError:
        degradations.record(
            "preparation: execution du plan", TimeoutError("budget dépassé"),
        )
        return results

    seen: set[str] = set()
    for page in pages:
        if isinstance(page, BaseException):
            try:
                raise page
            except BaseException as exc:  # noqa: BLE001 — comptabilisé, jamais fatal
                degradations.record("preparation: intent echanges", exc)
            continue
        for hit in page:
            if hit.chunk_id not in seen:
                seen.add(hit.chunk_id)
                results.exchange_hits.append(hit)
    return results
