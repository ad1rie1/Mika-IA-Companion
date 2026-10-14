import type * as THREE from "three";

/**
 * Make the mixer write every property it animates, this frame.
 *
 * three's PropertyMixer writes a bound property only when its mixed value
 * differs from the previous frame's (`PropertyMixer.apply` compares its two
 * accumulation buffers). AnimationSystem resets the normalized pose to rest
 * at the start of every frame (so overlays never accumulate and a track
 * missing from a clip falls back to rest): a value that does NOT change —
 * the still hips of a seated Unity-workshop clip, a bone the clip holds, a
 * one-shot paused on its last frame — was wiped by the reset and not written
 * again. The body then flickered frame by frame between the clip and the
 * rest pose (seated, then standing through the chair). Mixamo captures never
 * hold a value still, which hid it.
 *
 * Forgetting the previous frame's accumulation (NaN never equals anything)
 * makes the comparison fail, so every binding is written. It reads two of
 * the mixer's private fields (three r172: `_bindings`, `_accuIndex`); a
 * mixer without them is left as it is.
 */
export function forceMixerWrite(mixer: THREE.AnimationMixer): void {
  const m = mixer as unknown as {
    _bindings?: { buffer: { fill(value: number, start: number, end: number): unknown }; valueSize: number }[];
    _accuIndex?: number;
  };
  const bindings = m._bindings;
  const previous = m._accuIndex;
  if (!bindings || previous === undefined) return;
  // update() flips the index first: the region compared against is the current one.
  for (const b of bindings) {
    const from = b.valueSize + previous * b.valueSize;
    b.buffer.fill(NaN, from, from + b.valueSize);
  }
}
