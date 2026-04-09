import { VRM } from "@pixiv/three-vrm";

export class AnimationMixer {
  private vrm: VRM | null = null;
  private blinkTimer = 0;
  private blinkInterval = 3 + Math.random() * 2;
  private isBlinking = false;
  private blinkProgress = 0;

  private breatheTimer = 0;
  private isSpeaking = false;

  setVRM(vrm: VRM) {
    this.vrm = vrm;
  }

  setSpeaking(speaking: boolean) {
    this.isSpeaking = speaking;
  }

  getIsSpeaking(): boolean {
    return this.isSpeaking;
  }

  update(delta: number) {
    if (!this.vrm) return;

    this.updateBlink(delta);
    this.updateBreathe(delta);
    // Lip sync is now handled by LipSyncController
  }

  private updateBlink(delta: number) {
    if (!this.vrm?.expressionManager) return;

    this.blinkTimer += delta;

    if (!this.isBlinking && this.blinkTimer >= this.blinkInterval) {
      this.isBlinking = true;
      this.blinkProgress = 0;
      this.blinkTimer = 0;
      this.blinkInterval = 2.5 + Math.random() * 3;
    }

    if (this.isBlinking) {
      this.blinkProgress += delta * 8;
      // Blink curve: quick close, slower open
      let blinkValue: number;
      if (this.blinkProgress < 0.5) {
        blinkValue = this.blinkProgress * 2;
      } else if (this.blinkProgress < 1.0) {
        blinkValue = 1 - (this.blinkProgress - 0.5) * 2;
      } else {
        blinkValue = 0;
        this.isBlinking = false;
      }
      this.vrm.expressionManager.setValue("blink", blinkValue);
    }
  }

  private updateBreathe(delta: number) {
    if (!this.vrm?.humanoid) return;

    this.breatheTimer += delta;
    // Subtle breathing motion on the spine
    const spine = this.vrm.humanoid.getNormalizedBoneNode("spine");
    if (spine) {
      const breatheAmount = Math.sin(this.breatheTimer * 1.5) * 0.005;
      spine.rotation.x = breatheAmount;
    }
  }
}
