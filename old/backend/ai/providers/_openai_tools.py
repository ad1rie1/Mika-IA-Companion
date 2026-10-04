"""Le côté OpenAI-compatible de la boucle d'outils.

``OpenAIProvider`` et ``GLMProvider`` parlent tous deux à une surface
``/chat/completions`` compatible OpenAI : même sérialisation des outils,
même ping/pong ``tool_calls`` → tour ``tool``, mêmes refus de paramètres. Ce
module porte ce qui leur est commun — la reprise mémorisée d'un 400
(``create_chat_completion`` + ``ParamMemo``), le fil de départ d'un
``ChatPrompt`` et l'adaptateur que la boucle générique
(``_tool_loop.executer_la_boucle``) pilote.

Le fil de départ arrive **déjà construit** : le préfixe stable en système,
de vrais tours d'historique, l'état du tour dans le dernier tour user. La
boucle n'ajoute qu'à la fin, donc ce préfixe reste identique octet pour
octet d'un aller-retour à l'autre — ce sur quoi les back-ends compatibles
OpenAI indexent leur cache de préfixe automatique.
"""

from __future__ import annotations

import logging

from old.backend.ai.providers._tool_loop import (
    AdaptateurOutils,
    AppelOutil,
    Issue,
    Reponse,
    contenu_json,
)
from old.backend.utils.degradation import degradations

logger = logging.getLogger(__name__)


class ParamMemo:
    """Ce que chaque modèle a refusé, mémorisé par instance de provider.

    Miroir de ``ClaudeProvider._create_message`` : un modèle de raisonnement
    (série o, gpt-5) refuse ``max_tokens`` en 400 — « use
    'max_completion_tokens' instead » — et refuse ``temperature`` hors de sa
    valeur par défaut. Sans reprise, chaque rôle mappé sur un tel modèle
    échouait à chaque appel ; sans mémo, chaque appel paierait la requête
    condamnée avant la bonne, et chaque itération de la boucle d'outils
    avec lui.
    """

    def __init__(self) -> None:
        #: modèle → nom du paramètre de plafond accepté (absent = ``max_tokens``)
        self.token_param: dict[str, str] = {}
        #: modèles dont le serveur a refusé ``temperature``
        self.no_temperature: set[str] = set()


def memo_for(owner) -> ParamMemo:
    """Le mémo de ce provider, créé à la demande.

    ``getattr`` défensif : des tests (et d'éventuels usages ad hoc)
    construisent le provider via ``__new__`` sans passer par ``__init__``.
    """
    memo = getattr(owner, "_param_memo", None)
    if memo is None:
        memo = ParamMemo()
        try:
            owner._param_memo = memo
        except Exception:  # noqa: BLE001 — un objet figé garde un mémo jetable
            pass
    return memo


async def create_chat_completion(
    client,
    memo: ParamMemo | None,
    *,
    model: str,
    messages: list[dict],
    max_tokens: int,
    temperature: float,
    **extra,
):
    """Un ``chat.completions.create``, paramètres de génération repris au 400.

    ``max_tokens`` reste le **premier** essai : les serveurs compatibles
    OpenAI tiers (Groq, vLLM, LM Studio, Zhipu) ne connaissent souvent que
    ce nom, et c'est le cas commun. Deux reprises au plus, une par
    paramètre, chacune mémorisée pour le modèle : ``max_tokens`` →
    ``max_completion_tokens`` quand le refus nomme le premier, ``temperature``
    retirée quand il la nomme. Toute autre erreur remonte intacte.
    """
    try:
        from openai import BadRequestError
    except ImportError:  # pragma: no cover — le provider n'existerait pas
        BadRequestError = ()  # type: ignore[assignment]

    memo = memo if memo is not None else ParamMemo()
    token_param = memo.token_param.get(model, "max_tokens")
    send_temperature = model not in memo.no_temperature
    renamed = False
    dropped = False

    while True:
        kwargs = {"model": model, "messages": messages, token_param: max_tokens}
        if send_temperature:
            kwargs["temperature"] = temperature
        kwargs.update(extra)
        try:
            return await client.chat.completions.create(**kwargs)
        except BadRequestError as exc:
            text = str(exc)
            if token_param == "max_tokens" and not renamed and "max_tokens" in text:
                renamed = True
                token_param = "max_completion_tokens"
                memo.token_param[model] = token_param
                logger.info(
                    "Le modèle %s refuse `max_tokens` — `max_completion_tokens` "
                    "mémorisé pour cette instance.", model,
                )
                continue
            if send_temperature and not dropped and "temperature" in text:
                dropped = True
                send_temperature = False
                memo.no_temperature.add(model)
                logger.info(
                    "Le modèle %s refuse `temperature` — mémorisé, plus "
                    "jamais envoyée pour cette instance.", model,
                )
                continue
            raise


def messages_from_chat_prompt(prompt) -> list[dict]:
    """Fil de départ pour un ``ChatPrompt``.

    Même rendu que ``complete_chat`` : le préfixe stable en système, puis de
    vrais tours ``{role, content}``. La boucle d'outils n'ajoute qu'à la fin,
    donc ce préfixe reste identique octet pour octet d'un aller-retour à
    l'autre — ce sur quoi les back-ends compatibles OpenAI indexent leur
    cache de préfixe automatique.
    """
    return [
        {"role": "system", "content": prompt.system_stable},
        *prompt.chat_messages(),
    ]


def _serialize_tools(tools: list) -> list[dict]:
    """Convert ``ModuleTool`` list → OpenAI ``tools`` parameter shape."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.to_json_schema(),
            },
        }
        for t in tools
    ]


class AdaptateurOpenAI(AdaptateurOutils):
    """La boucle d'outils vue par un endpoint compatible OpenAI.

    ``memo`` est celui du provider appelant : un paramètre refusé au premier
    tour ne doit pas être re-tenté à chaque itération de la boucle.
    """

    def __init__(
        self,
        client,
        memo: ParamMemo | None,
        *,
        label: str,
        messages: list[dict],
        model: str,
        tools: list,
        temperature: float,
    ) -> None:
        self.LABEL = label
        self._client = client
        self._memo = memo
        self._model = model
        self._temperature = temperature
        # Le fil appartient à l'appelant : la boucle y empile ses allers-retours.
        self.fil = list(messages)
        self._serialises = _serialize_tools(tools) if tools else None

    async def appeler(self, max_tokens: int):
        extra = {"tools": self._serialises} if self._serialises else {}
        response = await create_chat_completion(
            self._client, self._memo,
            model=self._model,
            messages=self.fil,
            max_tokens=max_tokens,
            temperature=self._temperature,
            **extra,
        )
        # Usage natif remonté au quota : de vrais chiffres, pas une
        # estimation en caractères.
        usage = getattr(response, "usage", None)
        if usage is not None:
            try:
                from old.backend.ai.quota import set_usage

                set_usage(
                    input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                    output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                )
            except Exception as exc:
                degradations.record(
                    "ai.providers._openai_tools.AdaptateurOpenAI.appeler usage", exc,
                )
        return response

    def lire(self, response) -> Reponse:
        msg = response.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None) or []
        if not tool_calls:
            return Reponse(texte=msg.content or "")
        # Le ``content`` d'un tour porteur d'appels est du brouillon : il est
        # rejoué au modèle, pas rendu à l'appelant.
        return Reponse(appels=[
            AppelOutil(
                name=tc.function.name, arguments=tc.function.arguments or "", id=tc.id,
            )
            for tc in tool_calls
        ])

    def rejouer_le_tour(self, response, reponse: Reponse) -> None:
        msg = response.choices[0].message
        self.fil.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in (getattr(msg, "tool_calls", None) or [])
            ],
        })

    def rendre_les_resultats(self, issues: list[Issue]) -> None:
        for issue in issues:
            self.fil.append({
                "role": "tool",
                "tool_call_id": issue.appel.id,
                "content": contenu_json(issue),
            })
