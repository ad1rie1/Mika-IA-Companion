"""Damped harmonic oscillator in PAD space.

The emotional state of a person (or the global mood) is modeled as a
point-mass in 3D PAD space, attached by a spring to its "home" position
(the default mood) and subject to friction. Messages apply impulses.

Equation of motion (per component, continuous):
    m · d²x/dt² = -k · (x - home) - c · dx/dt + F_impulse

Integration uses semi-implicit Euler for stability at large dt:
    a  = (-k · (x - home) - c · v) / m
    v' = v + a · dt
    x' = x + v' · dt
"""
from __future__ import annotations

from dataclasses import dataclass, field

from emotion import pad
from emotion.pad import Vec3


@dataclass
class OscillatorParams:
    """Physical parameters derived from temperament.

    All values live in sensible ranges so the system stays stable for any
    temperament configuration.
    """
    mass: float = 1.0         # resistance to impulses; lower = more reactive
    stiffness: float = 0.3    # spring pull toward home; higher = faster recovery
    damping: float = 0.6      # friction on velocity; higher = less oscillation
    impulse_gain: float = 1.0 # scales incoming impulses

    def step(self, position: Vec3, velocity: Vec3, home: Vec3, dt: float) -> tuple[Vec3, Vec3]:
        """Advance one step. Returns (new_position, new_velocity)."""
        spring = pad.scale(pad.sub(home, position), self.stiffness)
        friction = pad.scale(velocity, -self.damping)
        accel = pad.scale(pad.add(spring, friction), 1.0 / max(0.01, self.mass))

        new_velocity = pad.add(velocity, pad.scale(accel, dt))
        new_position = pad.add(position, pad.scale(new_velocity, dt))

        # Keep position bounded to a reasonable envelope. Anchors sit inside
        # [-1, 1]³ ; we allow a small margin for velocity overshoot but cap
        # beyond that to prevent runaway states.
        new_position = pad.clamp_component(new_position, limit=1.2)
        return new_position, new_velocity


def apply_impulse(
    velocity: Vec3,
    position: Vec3,
    target: Vec3,
    params: OscillatorParams,
) -> Vec3:
    """Return new velocity after applying an impulse pulling toward `target`.

    The impulse is proportional to the distance to the target, scaled by
    the impulse gain and inverse mass. This makes strong, far-away targets
    produce larger kicks than nearby ones — which matches intuition.
    """
    delta = pad.sub(target, position)
    kick = pad.scale(delta, params.impulse_gain / max(0.01, params.mass))
    return pad.add(velocity, kick)


@dataclass
class OscillatorState:
    """In-memory dynamic state — position and velocity in PAD space."""
    position: Vec3 = field(default_factory=pad.zero)
    velocity: Vec3 = field(default_factory=pad.zero)

    def step(self, home: Vec3, params: OscillatorParams, dt: float) -> None:
        self.position, self.velocity = params.step(self.position, self.velocity, home, dt)

    def impulse_toward(self, target: Vec3, params: OscillatorParams) -> None:
        self.velocity = apply_impulse(self.velocity, self.position, target, params)
