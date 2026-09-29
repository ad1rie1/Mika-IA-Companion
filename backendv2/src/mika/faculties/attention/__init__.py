"""``attention`` : ce qui lui trotte dans la tête (pensées), ce qu'elle
attend (réponses, retours). Voir ``contracts/attention.py``."""

from mika.faculties.attention import inspect, prompt, watch  # noqa: F401 — contributions
from mika.faculties.attention.faculty import ATTENTION, AttentionParams, AttentionState

__all__ = ["ATTENTION", "AttentionParams", "AttentionState"]
