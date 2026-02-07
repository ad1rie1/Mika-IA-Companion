import * as THREE from "three";
import { SceneManager } from "./scene/SceneManager";
import { Environment } from "./scene/Environment";
import { CameraController } from "./scene/CameraController";
import { VTuberModel } from "./vtuber/VTuberModel";
import { EmotionController, type EmotionName } from "./vtuber/EmotionController";
import { AnimationMixer } from "./vtuber/AnimationMixer";
import { WebSocketClient } from "./network/WebSocketClient";
import { ChatOverlay } from "./ui/ChatOverlay";
import { EmotionDisplay } from "./ui/EmotionDisplay";

async function init() {
  const container = document.getElementById("app")!;
  const connectionStatus = document.getElementById("connection-status")!;

  // Scene setup
  const sceneManager = new SceneManager(container);
  new Environment(sceneManager.scene);
  const cameraController = new CameraController(
    sceneManager.camera,
    sceneManager.renderer.domElement
  );

  // VTuber model
  const vtuberModel = new VTuberModel(sceneManager.scene);
  const emotionController = new EmotionController();
  const animationMixer = new AnimationMixer();
  const emotionDisplay = new EmotionDisplay();

  // Try loading VRM model
  try {
    const vrm = await vtuberModel.load("/models/default.vrm");
    emotionController.setVRM(vrm);
    animationMixer.setVRM(vrm);
    console.log("VTuber model ready");
  } catch (e) {
    console.warn(
      "No VRM model found at /models/default.vrm - running without model.",
      "Place a .vrm file in frontend/public/models/default.vrm"
    );
    createPlaceholder(sceneManager);
  }

  // WebSocket connection
  const ws = new WebSocketClient();
  const chatOverlay = new ChatOverlay(ws);

  ws.on("connection", (data) => {
    if (data.status === "connected") {
      connectionStatus.className = "connected";
      connectionStatus.textContent = "Connected";
    } else {
      connectionStatus.className = "disconnected";
      connectionStatus.textContent = "Disconnected";
    }
  });

  ws.on("speech", (data) => {
    const emotion = data.emotion as EmotionName;
    emotionController.setEmotion(emotion);
    emotionDisplay.setEmotion(emotion);

    // Brief speaking animation
    animationMixer.setSpeaking(true);
    setTimeout(() => {
      animationMixer.setSpeaking(false);
    }, Math.min(data.text.length * 50, 5000));
  });

  ws.connect();

  // Update loop
  sceneManager.onUpdate((delta) => {
    cameraController.update();
    vtuberModel.update(delta);
    emotionController.update(delta);
    animationMixer.update(delta);
  });
}

function createPlaceholder(sceneManager: SceneManager) {
  // Body
  const body = new THREE.Mesh(
    new THREE.CapsuleGeometry(0.2, 0.6, 8, 16),
    new THREE.MeshStandardMaterial({ color: 0x6366f1 })
  );
  body.position.set(0, 0.9, -0.5);
  body.castShadow = true;
  sceneManager.scene.add(body);

  // Head
  const head = new THREE.Mesh(
    new THREE.SphereGeometry(0.18, 16, 16),
    new THREE.MeshStandardMaterial({ color: 0xffd5b4 })
  );
  head.position.set(0, 1.5, -0.5);
  head.castShadow = true;
  sceneManager.scene.add(head);
}

init().catch(console.error);
