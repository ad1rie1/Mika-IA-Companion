"""Damped harmonic oscillator in PAD space.

The emotional state of a person (or the global mood) is modeled as a
point-mass in 3D PAD space, attached by a spring to its "home" position
(the default mood) and subject to friction.

A message does **not** push the mass: it moves the position directly, by a
fraction of what still separates it from the anchor it names (see
`apply_impulse`). The spring and the friction therefore only govern the
*return* — how long what just happened stays readable — and the only velocity
in the system is the one the spring itself produces.

Equation of motion (per component, continuous):
    m · d²x/dt² = -k · (x - home) - c · dx/dt

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
    mass: float = 1.0         # inertia of the return; lower = more reactive
    stiffness: float = 0.3    # spring pull toward home; higher = faster recovery
    damping: float = 0.6      # friction on velocity; sets the decay envelope
    # Share of the *remaining distance to the target* an impulse covers at
    # once, in ]0, 1]. Not a force: repeated impulses of the same sign move
    # the position further each time, and never past the target.
    impulse_gain: float = 1.0

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
    position: Vec3,
    target: Vec3,
    params: OscillatorParams,
) -> Vec3:
    """Return the new position after an impulse pulling toward `target`.

    A ratchet, not a kick. Injecting velocity instead would keep the position
    *travelling away* from home for minutes once the time constant is counted
    in minutes rather than seconds — an overshoot several scenario tests pin
    in the opposite direction — while leaving the position itself untouched at
    the instant every reader (prompt, snapshot, affect panel, gestures) looks
    at it. Bounded by construction: with a gain in ]0, 1] the position never
    goes past the target, so it never leaves the anchors' envelope.
    """
    gain = max(0.0, min(1.0, params.impulse_gain))
    delta = pad.sub(target, position)
    return pad.clamp_component(
        pad.add(position, pad.scale(delta, gain)), limit=1.2,
    )


# Look-ahead used to report where a state is heading rather than where it
# stands. One minute at one-second resolution: cheap, and long enough to cover
# the rise of any residual velocity the spring produces.
_PEAK_HORIZON_S = 60.0
_PEAK_DT = 1.0


def peak_projection(
    position: Vec3,
    velocity: Vec3,
    home: Vec3,
    params: OscillatorParams,
    *,
    horizon: float = _PEAK_HORIZON_S,
    dt: float = _PEAK_DT,
) -> Vec3:
    """Position of maximum distance to `home` over the next `horizon` seconds.

    Pure — integrates a copy forward and stops as soon as the state starts
    coming back. A state in plain relaxation is already at its peak, so the
    answer is then the current position.
    """
    best = position
    best_distance = pad.distance(position, home)
    remaining = horizon

    while remaining > 1e-6:
        step_dt = min(dt, remaining)
        position, velocity = params.step(position, velocity, home, step_dt)
        remaining -= step_dt

        travelled = pad.distance(position, home)
        if travelled <= best_distance:
            break
        best, best_distance = position, travelled

    return best


@dataclass
class OscillatorState:
    """In-memory dynamic state — position and velocity in PAD space."""
    position: Vec3 = field(default_factory=pad.zero)
    velocity: Vec3 = field(default_factory=pad.zero)

    def step(self, home: Vec3, params: OscillatorParams, dt: float) -> None:
        self.position, self.velocity = params.step(self.position, self.velocity, home, dt)

    def impulse_toward(self, target: Vec3, params: OscillatorParams) -> None:
        self.position = apply_impulse(self.position, target, params)
