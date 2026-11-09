"""Ce que plusieurs rubriques de réglages partagent."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ValidationError

from mika.runtime.params import Parameters

if TYPE_CHECKING:
    from mika.app.server import Live


def parameters(live: Live) -> Parameters:
    return Parameters(live.kernel, temperament=lambda: live.persona().temperament, overrides=live.settings.overrides,
                      save_overrides=live.settings.save_overrides, inputs=live.inputs, apply=live.reconfigure)


def tolerant(cls: type[BaseModel], /, **data: Any) -> Any:
    """Une valeur enregistrée avant qu'une règle existe (un hôte « https://github.com/ ») s'affiche
    quand même, telle quelle : la page reste ouverte pour la corriger ; l'enregistrer la revalide."""
    try:
        return cls(**data)
    except ValidationError:
        return cls.model_construct(**data)
