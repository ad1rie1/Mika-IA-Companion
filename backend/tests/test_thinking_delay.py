"""Tests for the adaptive "thinking delay" inserted before broadcast.

Pure function — no I/O, no DB. We assert the scaling behavior + the
shortcut paths (internal trigger = no delay, empty response = no delay).
"""
from __future__ import annotations

import random

import pytest

from pipeline.processor import _compute_thinking_delay


def test_empty_response_zero_delay():
    assert _compute_thinking_delay("", 0.5, "frontend") == 0.0


def test_whitespace_only_zero_delay():
    assert _compute_thinking_delay("   \n\t ", 0.5, "frontend") == 0.0


def test_internal_trigger_zero_delay():
    """Conscience-initiated speech shouldn't add a delay on top of its
    already deliberate cycle."""
    assert _compute_thinking_delay("long response here", 0.5, "conscience") == 0.0


def test_short_response_has_floor_delay():
    """Even a one-word reply gets a noticeable floor (no instant bot feel)."""
    random.seed(42)
    delay = _compute_thinking_delay("ouais", 0.5, "frontend")
    assert 0.25 <= delay <= 0.65


def test_long_response_adds_per_word():
    """Longer responses should take noticeably longer (up to the word cap)."""
    random.seed(42)
    short = _compute_thinking_delay("ouais", 0.5, "frontend")
    random.seed(42)
    long_text = " ".join(["mot"] * 100)
    long_delay = _compute_thinking_delay(long_text, 0.5, "frontend")
    assert long_delay > short


def test_delay_cap_is_two_seconds():
    """Even with pathological input, we cap at 2s — never make user wait."""
    random.seed(1)
    huge = " ".join(["mot"] * 5000)
    delay = _compute_thinking_delay(huge, 0.1, "frontend")  # very tired + huge
    assert delay <= 2.0


def test_tired_mika_takes_longer():
    """Low energy (< 0.3) should multiply the delay."""
    random.seed(100)
    normal = _compute_thinking_delay("une réponse normale de plusieurs mots", 0.5, "frontend")
    random.seed(100)
    tired = _compute_thinking_delay("une réponse normale de plusieurs mots", 0.15, "frontend")
    assert tired > normal


def test_energetic_mika_replies_faster():
    """High energy (> 0.75) should shorten the delay."""
    random.seed(100)
    normal = _compute_thinking_delay("une réponse normale de plusieurs mots", 0.5, "frontend")
    random.seed(100)
    energetic = _compute_thinking_delay("une réponse normale de plusieurs mots", 0.9, "frontend")
    assert energetic < normal


def test_delay_is_deterministic_under_seed():
    """Given the same seed + inputs, we produce the same delay."""
    random.seed(7)
    a = _compute_thinking_delay("bonjour à tous", 0.5, "frontend")
    random.seed(7)
    b = _compute_thinking_delay("bonjour à tous", 0.5, "frontend")
    assert a == b
