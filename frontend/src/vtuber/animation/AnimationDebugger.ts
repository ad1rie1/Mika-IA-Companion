import * as THREE from "three";
import {
  EMOTION_NAMES,
  SLEEP_PHASES,
  type EmotionName,
  type SleepPhase,
} from "../../types";
import type { AnimationSystem } from "./AnimationSystem";

export interface AnimationDebuggerDeps {
  system: AnimationSystem;
  scene: THREE.Scene;
  /** The raw VRM scene, for the skeleton helper. */
  avatarScene: THREE.Object3D | null;
  /** Full sleep fan-out (animation + environment + wake stamp), so a
   * forced phase behaves exactly like a backend-driven one. */
  applySleepPhase: (phase: SleepPhase) => void;
  /** Full emotion fan-out (face + body + UI). */
  applyEmotion: (emotion: EmotionName, intensity: number) => void;
}

/**
 * Dev-only manual QA hooks — the empirical validation layer. The axis
 * conventions of this rig have burned every analytical guess so far;
 * cycling every clip on the live model (Alt+M) is the only reliable
 * retarget check.
 *
 *   Alt+M  cycle loaded clips (pins scheduling)   Alt+O  resume auto
 *   Alt+K  toggle skeleton helper                 Alt+J  retarget report
 *   Alt+S  cycle sleep phases                     Alt+T  toggle talking
 *   Alt+E  cycle the 29 emotions at 0.9           Alt+G  cycle gestures
 *   Alt+D  toggle the debug panel
 */
export class AnimationDebugger {
  private deps: AnimationDebuggerDeps;
  private toast: HTMLDivElement | null = null;
  private toastTimer: number | null = null;
  private skeletonHelper: THREE.SkeletonHelper | null = null;
  private sleepIndex = 0;
  private emotionIndex = -1;
  private gestureIndex = -1;
  private talking = false;
  private panel: HTMLDivElement | null = null;
  private panelTimer: number | null = null;

  constructor(deps: AnimationDebuggerDeps) {
    this.deps = deps;
    document.addEventListener("keydown", this.onKeyDown);
    if (new URLSearchParams(window.location.search).has("animdebug")) {
      this.togglePanel();
    }
  }

  private onKeyDown = (e: KeyboardEvent) => {
    if (!e.altKey || e.ctrlKey || e.metaKey) return;
    const k = e.key.toLowerCase();
    const { system } = this.deps;

    if (k === "m") {
      e.preventDefault();
      this.showToast(`Clip: ${system.debugCycleClip()} (Alt+O = auto)`);
    } else if (k === "o") {
      e.preventDefault();
      system.debugResume();
      this.showToast("Clips: auto");
    } else if (k === "k") {
      e.preventDefault();
      this.toggleSkeleton();
    } else if (k === "j") {
      e.preventDefault();
      console.table(
        system.getRetargetReports().map((r) => ({
          clip: r.clipName,
          duration: r.duration.toFixed(2),
          mapped: r.mappedTracks,
          fingersStripped: r.strippedFingerTracks,
          dropped: r.droppedTracks.length,
          hipsScale: r.hipsPositionScale?.toFixed(5) ?? "—",
          suspicious: r.hipsScaleSuspicious,
        }))
      );
      this.showToast("Rapport retarget → console");
    } else if (k === "s") {
      e.preventDefault();
      this.sleepIndex = (this.sleepIndex + 1) % SLEEP_PHASES.length;
      const phase = SLEEP_PHASES[this.sleepIndex];
      this.deps.applySleepPhase(phase);
      this.showToast(`Sommeil: ${phase}`);
    } else if (k === "e") {
      e.preventDefault();
      this.emotionIndex = (this.emotionIndex + 1) % EMOTION_NAMES.length;
      const emotion = EMOTION_NAMES[this.emotionIndex];
      this.deps.applyEmotion(emotion, 0.9);
      this.showToast(`Émotion: ${emotion} @0.9`);
    } else if (k === "t") {
      e.preventDefault();
      this.talking = !this.talking;
      system.setSpeaking(this.talking);
      this.showToast(`Talking: ${this.talking ? "on" : "off"}`);
    } else if (k === "g") {
      e.preventDefault();
      const gestures = system.library.byCategory("gesture");
      if (gestures.length === 0) {
        this.showToast("Aucun geste chargé");
        return;
      }
      this.gestureIndex = (this.gestureIndex + 1) % gestures.length;
      const name = gestures[this.gestureIndex].name;
      system.playGesture(name);
      this.showToast(`Geste: ${name}`);
    } else if (k === "d") {
      e.preventDefault();
      this.togglePanel();
    }
  };

  private toggleSkeleton(): void {
    if (this.skeletonHelper) {
      this.deps.scene.remove(this.skeletonHelper);
      this.skeletonHelper.dispose();
      this.skeletonHelper = null;
      this.showToast("Squelette: off");
      return;
    }
    if (!this.deps.avatarScene) {
      this.showToast("Pas de modèle chargé");
      return;
    }
    this.skeletonHelper = new THREE.SkeletonHelper(this.deps.avatarScene);
    this.deps.scene.add(this.skeletonHelper);
    this.showToast("Squelette: on");
  }

  showToast(text: string): void {
    if (!this.toast) {
      this.toast = document.createElement("div");
      this.toast.style.cssText =
        "position:fixed;bottom:16px;left:16px;z-index:9999;" +
        "background:rgba(20,20,30,.85);color:#fff;padding:6px 12px;" +
        "border-radius:8px;font:13px monospace;pointer-events:none;" +
        "transition:opacity .3s";
      document.body.appendChild(this.toast);
    }
    this.toast.textContent = text;
    this.toast.style.opacity = "1";
    if (this.toastTimer !== null) window.clearTimeout(this.toastTimer);
    this.toastTimer = window.setTimeout(() => {
      if (this.toast) this.toast.style.opacity = "0";
    }, 2000);
  }

  private togglePanel(): void {
    if (this.panel) {
      if (this.panelTimer !== null) window.clearInterval(this.panelTimer);
      this.panelTimer = null;
      this.panel.remove();
      this.panel = null;
      return;
    }
    this.panel = document.createElement("div");
    this.panel.style.cssText =
      "position:fixed;top:60px;left:16px;z-index:9998;max-height:70vh;" +
      "overflow:auto;background:rgba(15,15,25,.92);color:#dde;padding:10px 14px;" +
      "border-radius:10px;font:12px monospace;min-width:230px";
    document.body.appendChild(this.panel);
    const render = () => {
      if (!this.panel) return;
      const s = this.deps.system.getDebugState();
      const clips = this.deps.system.listClips();
      this.panel.innerHTML =
        `<b>Animation</b> (Alt+D ferme)<br>` +
        `état: <b>${s.state}</b><br>` +
        `clip: ${s.clip ?? "—"} (${s.clipTime.toFixed(1)}/${s.clipDuration.toFixed(1)}s)<br>` +
        `sommeil: ${s.sleepPhase} · émotion: ${s.emotion}@${s.intensity.toFixed(2)}<br>` +
        `talking: ${s.speaking} · clips: ${s.clipCount}<br>` +
        `<hr style="border-color:#334">` +
        clips
          .map(
            (name) =>
              `<button data-clip="${name}" style="margin:1px;padding:2px 6px;` +
              `background:#223;color:#cde;border:1px solid #446;border-radius:5px;` +
              `cursor:pointer;font:11px monospace">${name}</button>`
          )
          .join("") +
        `<br><button data-resume="1" style="margin-top:6px;padding:2px 8px;` +
        `background:#243324;color:#cec;border:1px solid #464;border-radius:5px;` +
        `cursor:pointer;font:11px monospace">reprendre auto</button>`;
    };
    this.panel.addEventListener("click", (e) => {
      const target = e.target as HTMLElement;
      const clip = target.getAttribute("data-clip");
      if (clip) {
        this.deps.system.playGesture(clip);
        this.showToast(`Play: ${clip}`);
      } else if (target.getAttribute("data-resume")) {
        this.deps.system.debugResume();
        this.showToast("Clips: auto");
      }
    });
    render();
    this.panelTimer = window.setInterval(render, 300);
  }
}
