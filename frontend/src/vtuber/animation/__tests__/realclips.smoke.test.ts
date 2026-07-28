/**
 * Smoke test over the REAL user-downloaded Mixamo FBX files in
 * public/animations/ (they are not committed — Mixamo requires an Adobe
 * account — so the whole suite skips itself when none are present).
 *
 * Runs the actual FBXLoader.parse + retargetMixamoClip pipeline on every
 * manifest entry with a stub VRM: validates prefix detection, clip
 * presence, track mapping and hips scale on the true assets. The only
 * thing it can't check is how the motion LOOKS — that's Alt+M.
 */
import * as fs from "node:fs";
import * as path from "node:path";
import * as THREE from "three";
import { FBXLoader } from "three/addons/loaders/FBXLoader.js";
import { describe, expect, it } from "vitest";
import type { VRM } from "@pixiv/three-vrm";
import type { AnimationManifest } from "../../../types";
import { retargetMixamoClip } from "../mixamoRetarget";

const PUBLIC_DIR = path.resolve(__dirname, "../../../../public");
const MANIFEST_PATH = path.join(PUBLIC_DIR, "animations/manifest.json");

function loadManifestEntries(): Array<[string, { url: string }]> {
  if (!fs.existsSync(MANIFEST_PATH)) return [];
  const manifest = JSON.parse(
    fs.readFileSync(MANIFEST_PATH, "utf-8")
  ) as AnimationManifest;
  return Object.entries(manifest.clips).filter(([, entry]) =>
    fs.existsSync(path.join(PUBLIC_DIR, entry.url))
  );
}

function stubVrm(): VRM {
  const nodes = new Map<string, THREE.Object3D>();
  return {
    meta: { metaVersion: "0" },
    humanoid: {
      getNormalizedBoneNode(bone: string) {
        let node = nodes.get(bone);
        if (!node) {
          node = new THREE.Object3D();
          node.name = `Normalized_${bone}`;
          nodes.set(bone, node);
        }
        return node;
      },
      normalizedRestPose: { hips: { position: [0, 0.75, 0] } },
    },
  } as unknown as VRM;
}

const entries = loadManifestEntries();

describe.skipIf(entries.length === 0)("real Mixamo downloads retarget cleanly", () => {
  const loader = new FBXLoader();
  const vrm = stubVrm();

  it.each(entries.map(([name, entry]) => [name, entry.url] as const))(
    "%s (%s)",
    (name, url) => {
      const buf = fs.readFileSync(path.join(PUBLIC_DIR, url));
      const asset = loader.parse(
        buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength),
        ""
      ) as THREE.Group;

      const { clip, report } = retargetMixamoClip(asset, vrm, name);

      // A real Mixamo skeleton animates the full body: hips + spine
      // chain + limbs. Fewer than 15 mapped tracks means the rig or the
      // prefix was not recognized.
      expect(report.mappedTracks).toBeGreaterThan(15);
      expect(report.duration).toBeGreaterThan(0.3);
      expect(report.hipsScaleSuspicious).toBe(false);
      expect(clip.tracks.some((t) => t.name === "Normalized_hips.quaternion")).toBe(true);
      for (const track of clip.tracks) {
        expect(track.values.every((v) => Number.isFinite(v))).toBe(true);
      }
    }
  );

  it("every manifest entry has its file on disk (no partial install)", () => {
    const manifest = JSON.parse(
      fs.readFileSync(MANIFEST_PATH, "utf-8")
    ) as AnimationManifest;
    const missing = Object.entries(manifest.clips)
      .filter(([, e]) => !fs.existsSync(path.join(PUBLIC_DIR, e.url)))
      .map(([n]) => n);
    expect(missing).toEqual([]);
  });
});
