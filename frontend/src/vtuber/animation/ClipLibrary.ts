import * as THREE from "three";
import { FBXLoader } from "three/addons/loaders/FBXLoader.js";
import type { VRM } from "@pixiv/three-vrm";
import type {
  AnimationManifest,
  ClipCategory,
  ClipManifestEntry,
  SleepPhase,
} from "../../types";
import { retargetMixamoClip, type RetargetReport } from "./mixamoRetarget";

export const REST_CLIP_NAME = "__rest__";

// Default per-phase slowdown when the manifest has no explicit sleep block.
const SLEEP_TIMESCALE_DEFAULT: Record<Exclude<SleepPhase, "awake">, number> = {
  light_sleep: 1.0,
  rem: 0.85,
  deep_sleep: 0.6,
};

const LOAD_CONCURRENCY = 3;

export interface LoadedClip {
  name: string;
  clip: THREE.AnimationClip;
  meta: ClipManifestEntry;
  report: RetargetReport | null;
}

/** Free the throwaway FBX scene graph once tracks are extracted. */
function disposeFbxAsset(asset: THREE.Group): void {
  asset.traverse((obj) => {
    const mesh = obj as THREE.Mesh;
    if (mesh.isMesh) {
      mesh.geometry?.dispose();
      const materials = Array.isArray(mesh.material)
        ? mesh.material
        : [mesh.material];
      for (const mat of materials) {
        if (!mat) continue;
        for (const value of Object.values(mat)) {
          if (value instanceof THREE.Texture) value.dispose();
        }
        mat.dispose();
      }
    }
  });
}

/**
 * Manifest-driven Mixamo clip store. Lifecycle:
 *   prepare(vrm)              — synchronous; builds the always-available
 *                               synthetic rest clip (A-pose) so the state
 *                               machine can start before any download
 *   loadManifest(url, hooks)  — fetches manifest.json, loads the first
 *                               idle clip with priority (she's alive in
 *                               ~1s), streams the rest with a small
 *                               concurrency cap; a corrupt file never
 *                               sinks the batch
 */
export class ClipLibrary {
  manifest: AnimationManifest | null = null;
  readonly reports: RetargetReport[] = [];

  private vrm: VRM | null = null;
  private fbx = new FBXLoader();
  private clips = new Map<string, LoadedClip>();
  private restLoadedClip: LoadedClip | null = null;
  private failed: Array<{ name: string; url: string; reason: string }> = [];

  get restLoaded(): LoadedClip {
    if (!this.restLoadedClip) {
      throw new Error("ClipLibrary.prepare(vrm) must be called first");
    }
    return this.restLoadedClip;
  }

  prepare(vrm: VRM): void {
    this.vrm = vrm;
    this.restLoadedClip = {
      name: REST_CLIP_NAME,
      clip: buildRestClip(vrm),
      meta: {
        url: "",
        category: "idle",
        loop: true,
        hands: ["relaxed", "relaxed"],
      },
      report: null,
    };
  }

  async loadManifest(
    url: string,
    hooks: {
      onClipLoaded?: (loaded: LoadedClip) => void;
      onProgress?: (done: number, total: number, name: string) => void;
    } = {}
  ): Promise<void> {
    if (!this.vrm) throw new Error("ClipLibrary.prepare(vrm) must be called first");

    let manifest: AnimationManifest;
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      manifest = (await res.json()) as AnimationManifest;
    } catch (e) {
      console.warn(
        `ClipLibrary: no animation manifest at ${url} (${e}). ` +
          "Mika runs on the synthetic rest pose — drop Mixamo FBX files in " +
          "frontend/public/animations/ (see the README there) to bring her to life."
      );
      return;
    }

    const entries = Object.entries(manifest.clips ?? {}).filter(
      ([name, entry]) => {
        const ok =
          entry &&
          typeof entry.url === "string" &&
          entry.url.length > 0 &&
          ["idle", "talk", "gesture", "sleep", "locomotion"].includes(
            entry.category
          );
        if (!ok) console.warn(`ClipLibrary: manifest entry "${name}" invalid, skipped`);
        return ok;
      }
    );
    this.manifest = manifest;

    const total = entries.length;
    let done = 0;
    const finish = (name: string) => {
      done++;
      hooks.onProgress?.(done, total, name);
    };

    // Priority phase: the first idle clip alone — the moment it lands the
    // state machine swaps the rest pose for a living idle.
    const priorityIndex = entries.findIndex(([, e]) => e.category === "idle");
    if (priorityIndex >= 0) {
      const [name, entry] = entries.splice(priorityIndex, 1)[0];
      await this.loadOne(name, entry, hooks.onClipLoaded);
      finish(name);
    }

    // Streaming phase: bounded concurrency, allSettled semantics.
    const queue = [...entries];
    const worker = async () => {
      for (;;) {
        const next = queue.shift();
        if (!next) return;
        await this.loadOne(next[0], next[1], hooks.onClipLoaded);
        finish(next[0]);
      }
    };
    await Promise.all(
      Array.from({ length: Math.min(LOAD_CONCURRENCY, queue.length) }, worker)
    );

    if (this.failed.length > 0) {
      console.warn(
        `ClipLibrary: ${this.failed.length}/${total} clip(s) missing or invalid ` +
          "(pools shrink, gestures degrade to face-only):\n" +
          this.failed.map((f) => `  - ${f.name} (${f.url}): ${f.reason}`).join("\n") +
          "\nSee frontend/public/animations/README.md for the download list."
      );
    }
    const suspicious = this.reports.filter((r) => r.hipsScaleSuspicious);
    for (const r of suspicious) {
      console.warn(
        `ClipLibrary: "${r.clipName}" hipsPositionScale=${r.hipsPositionScale?.toFixed(5)} ` +
          "outside the expected [0.004, 0.02] range — the avatar may float or sink."
      );
    }
  }

  private async loadOne(
    name: string,
    entry: ClipManifestEntry,
    onLoaded?: (loaded: LoadedClip) => void
  ): Promise<void> {
    try {
      const asset = await this.fbx.loadAsync(encodeURI(entry.url));
      try {
        const { clip, report } = retargetMixamoClip(asset, this.vrm!, name, {
          stripFingers: true,
          stripRootXZ: entry.stripRootXZ === true,
        });
        const loaded: LoadedClip = { name, clip, meta: entry, report };
        this.clips.set(name, loaded);
        this.reports.push(report);
        onLoaded?.(loaded);
      } finally {
        disposeFbxAsset(asset);
      }
    } catch (e) {
      this.failed.push({ name, url: entry.url, reason: String(e) });
    }
  }

  get(name: string): LoadedClip | null {
    if (name === REST_CLIP_NAME) return this.restLoaded;
    return this.clips.get(name) ?? null;
  }

  has(name: string): boolean {
    return name === REST_CLIP_NAME || this.clips.has(name);
  }

  byCategory(category: ClipCategory): LoadedClip[] {
    return [...this.clips.values()].filter((c) => c.meta.category === category);
  }

  listNames(): string[] {
    return [...this.clips.keys()];
  }

  /** Which clip + timeScale to play for a sleep phase. Falls back:
   * manifest.sleep entry → first sleep-category clip → first idle clip
   * → synthetic rest. */
  sleepConfig(phase: Exclude<SleepPhase, "awake">): {
    loaded: LoadedClip;
    timeScale: number;
  } {
    const entry = this.manifest?.sleep?.[phase];
    if (entry) {
      const loaded = this.get(entry.clip);
      if (loaded) {
        return {
          loaded,
          timeScale: entry.timeScale ?? SLEEP_TIMESCALE_DEFAULT[phase],
        };
      }
    }
    const fallback =
      this.byCategory("sleep")[0] ?? this.byCategory("idle")[0] ?? this.restLoaded;
    return { loaded: fallback, timeScale: SLEEP_TIMESCALE_DEFAULT[phase] };
  }
}

// ~66° down from horizontal: relaxed A-pose, arms along the body — the
// same values the old VTuberModel.applyRestPose wrote.
const REST_ARM_POSE = [
  ["leftUpperArm", 1.15],
  ["rightUpperArm", -1.15],
  ["leftLowerArm", 0.1],
  ["rightLowerArm", -0.1],
] as const;

const _restEuler = new THREE.Euler();
const _restQuat = new THREE.Quaternion();

/**
 * Write the A-pose arm quaternions directly onto the normalized bones.
 * AnimationSystem calls this every frame right after resetNormalizedPose
 * and BEFORE the mixer, for two reasons: (1) the mixer's per-binding
 * "original state" — the pose it blends toward whenever active weights
 * sum below 1 (fade-ins from nothing, interrupted crossfades) — is
 * captured from the node values at first activation, and it must be the
 * A-pose, never the bind T-pose; (2) bones no clip tracks keep a sane
 * arms-down stance instead of the T-pose.
 */
export function applyRestPose(vrm: VRM): void {
  for (const [bone, z] of REST_ARM_POSE) {
    const node = vrm.humanoid?.getNormalizedBoneNode(bone);
    if (!node) continue;
    node.quaternion.setFromEuler(_restEuler.set(0, 0, z));
  }
}

/** Synthetic 1-keyframe A-pose clip on the normalized bones. Always
 * available, so "no assets downloaded yet" is just another clip to
 * crossfade with, not a special code path. */
export function buildRestClip(vrm: VRM): THREE.AnimationClip {
  const tracks: THREE.KeyframeTrack[] = [];

  for (const [bone, z] of REST_ARM_POSE) {
    const node = vrm.humanoid?.getNormalizedBoneNode(bone);
    if (!node) continue;
    _restQuat.setFromEuler(_restEuler.set(0, 0, z));
    tracks.push(
      new THREE.QuaternionKeyframeTrack(
        `${node.name}.quaternion`,
        [0],
        [_restQuat.x, _restQuat.y, _restQuat.z, _restQuat.w]
      )
    );
  }

  return new THREE.AnimationClip(REST_CLIP_NAME, 1, tracks);
}
