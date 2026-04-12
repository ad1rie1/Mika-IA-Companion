"""Shared parsing utilities for JSON extraction from LLM responses."""

import re


def strip_markdown_json(raw: str) -> str:
    """Extract JSON from a response that may be wrapped in markdown code fences.

    Uses regex to find the JSON object, which is robust against
    backticks appearing inside JSON string values.
    """
    # Try to find JSON inside code fences first
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if match:
        return match.group(1)
    # Try to find a bare JSON object
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        return match.group(0)
    return raw
