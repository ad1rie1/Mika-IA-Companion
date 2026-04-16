"""Drives — intrinsic motivational states.

Unlike emotions (reactive, anchored in PAD space), drives are *needs*
that build up over time and push Mika to act even without external
stimulus. They model curiosity, social hunger, expressive urge, and
the need to rest.

Each drive has:
  - tension: how much pressure it exerts (0..1), grows with time
  - growth_rate: how quickly it builds when unsatisfied
  - decay_on_satisfy: how much tension drops when assouvi
  - weight: how strongly it contributes to the conscience decision score

The DriveEngine lives alongside EmotionEngine and feeds its state to
both the prompt (so Claude knows Mika *feels* a pull toward X) and
the scoring system (so tension contributes to "act vs wait").
"""
from drives.engine import drive_engine, DriveEngine  # noqa: F401
from drives.state import DriveState, DriveKind  # noqa: F401
