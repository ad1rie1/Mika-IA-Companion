/* Mika en VRM dans son coin. Ne marche que servie en HTTP (les modules sont refusés en file://) : la page garde
   alors son portrait pré-rendu. Le modèle est celui du client web (frontend/Web/public/models/default.vrm, VRM 0.x,
   ~100 Mo, non versionné). Une vie simple et procédurale : souffle, clignements, regard vers le pointeur, tête qui
   bouge, humeur sur le visage, bouche quand elle parle. Le vrai frontendv2 reprendra le corps du client web.
   ?vrm=0 coupe la VRM (captures). */
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';

const URL_VRM = '../../frontend/Web/public/models/default.vrm';
const corner = document.getElementById('mika-corner');
const stage = document.getElementById('mc-stage');
const canvas = document.getElementById('mc-canvas');
const live = document.getElementById('mc-live');

if (new URLSearchParams(location.search).get('vrm') !== '0') demarrer();

function demarrer() {
  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true, powerPreference: 'low-power' });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(20, 1, 0.05, 20);
  const key = new THREE.DirectionalLight(0xffffff, Math.PI * 0.75);
  key.position.set(0.8, 1.6, 2.2);
  scene.add(key, new THREE.AmbientLight(0xffffff, 0.55));
  const regard = new THREE.Object3D();
  scene.add(regard);

  let vrm = null, sign = 1, teteY = 1.35;
  const os = {};
  const etat = { humeur: 'curious', dort: false, ecrit: false, parleJusqua: 0, pointeur: new THREE.Vector2(0, 0) };
  Object.assign(etat, lireEtat(window.MIKA_DONNEES && window.MIKA_DONNEES.mika));

  live.hidden = false;
  live.textContent = 'VRM…';

  const loader = new GLTFLoader();
  loader.register((parser) => new VRMLoaderPlugin(parser));
  loader.load(URL_VRM, (gltf) => {
    vrm = gltf.userData.vrm;
    VRMUtils.removeUnnecessaryVertices(gltf.scene);
    if (VRMUtils.combineSkeletons) VRMUtils.combineSkeletons(gltf.scene);
    vrm.scene.traverse((o) => { o.frustumCulled = false; });
    const root = new THREE.Group();
    const vrm0 = vrm.meta && vrm.meta.metaVersion === '0';
    root.rotation.y = vrm0 ? Math.PI : 0;     // un VRM 0.x regarde -Z : on le tourne vers la caméra
    sign = vrm0 ? -1 : 1;                      // les rotations s'écrivent en convention VRM 1.0
    root.add(vrm.scene);
    scene.add(root);
    for (const n of ['hips', 'spine', 'chest', 'upperChest', 'neck', 'head', 'leftShoulder', 'rightShoulder',
      'leftUpperArm', 'rightUpperArm', 'leftLowerArm', 'rightLowerArm', 'leftHand', 'rightHand']) {
      os[n] = vrm.humanoid.getNormalizedBoneNode(n);
    }
    poseDeRepos();
    vrm.update(0);
    const p = new THREE.Vector3();
    os.head.getWorldPosition(p);
    teteY = p.y;
    if (vrm.lookAt) { vrm.lookAt.target = regard; vrm.lookAt.autoUpdate = true; }
    cadrer();
    canvas.hidden = false;
    corner.classList.add('vrm-on');
    live.textContent = 'VRM';
    setTimeout(() => { live.hidden = true; }, 2500);
  }, (ev) => {
    if (ev.total) live.textContent = `VRM ${Math.round((ev.loaded / ev.total) * 100)} %`;
  }, (err) => {
    console.warn('VRM indisponible, le portrait reste :', err);
    live.hidden = true;
  });

  function poseDeRepos() {
    // Les bras le long du corps (le repos d'un VRM est un T), les épaules un peu basses, les coudes à peine pliés.
    const z = (n, v) => { if (os[n]) os[n].rotation.z = v * sign; };
    z('leftUpperArm', -1.2); z('rightUpperArm', 1.2);
    z('leftLowerArm', -0.12); z('rightLowerArm', 0.12);
    z('leftShoulder', 0.06); z('rightShoulder', -0.06);
    if (os.leftHand) os.leftHand.rotation.x = 0.1;
    if (os.rightHand) os.rightHand.rotation.x = 0.1;
  }

  /* Le buste dans la carte ; réduite, son visage seul dans le rond. */
  function cadrer() {
    const w = stage.clientWidth, h = stage.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    const mini = corner.dataset.size === 'mini';
    const visible = mini ? 0.2 : h > 380 ? 0.66 : 0.5; // hauteur vue, en mètres : son visage, ou son buste
    const d = visible / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)));
    const cible = mini ? teteY + 0.065 : teteY - 0.04; // visage vers 36 % de la hauteur en carte
    camera.position.set(0, cible + 0.01, d);
    camera.lookAt(0, cible, 0);
    camera.updateProjectionMatrix();
  }
  new ResizeObserver(cadrer).observe(stage);
  document.addEventListener('mika:size', () => setTimeout(cadrer, 270));
  document.addEventListener('mika:state', (e) => Object.assign(etat, lireEtat(e.detail)));
  document.addEventListener('mika:typing', (e) => { etat.ecrit = !!e.detail.on; });
  document.addEventListener('mika:talk', (e) => { etat.parleJusqua = performance.now() + (e.detail.ms || 1800); });
  addEventListener('pointermove', (e) => {
    const r = stage.getBoundingClientRect();
    etat.pointeur.set(
      THREE.MathUtils.clamp((e.clientX - (r.left + r.width / 2)) / innerWidth * 2, -1, 1),
      THREE.MathUtils.clamp((e.clientY - (r.top + r.height * 0.3)) / innerHeight * 2, -1, 1));
  });

  /* L'humeur sur le visage, avec les expressions de base (VRM 0.x converties par three-vrm). */
  const VISAGES = {
    happy: { happy: 0.55 }, excited: { happy: 0.7 }, playful: { happy: 0.4 }, love: { happy: 0.5 },
    curious: { happy: 0.16, relaxed: 0.12 }, thinking: { relaxed: 0.12 }, determined: {},
    tired: { relaxed: 0.38 }, sad: { sad: 0.45 }, melancholic: { sad: 0.3 }, angry: { angry: 0.4 }, neutral: {},
  };
  const NOMS = ['happy', 'relaxed', 'sad', 'angry', 'surprised', 'aa', 'ih', 'ou', 'ee', 'oh', 'blink'];
  const courant = Object.fromEntries(NOMS.map((n) => [n, 0]));
  let prochainClin = 2, clin = -1, viseme = 'aa', changeViseme = 0;

  const horloge = new THREE.Clock();
  let accu = 0;
  function boucle() {
    requestAnimationFrame(boucle);
    const dt = Math.min(horloge.getDelta(), 0.1);
    accu += dt;
    if (document.hidden || accu < 1 / 40) return;      // 40 images/s au plus, rien quand l'onglet est caché
    if (!canvas.offsetParent && !corner.offsetParent) { accu = 0; return; }   // pas de dessin quand elle n'est pas affichée
    const delta = accu; accu = 0;
    if (!vrm) return;
    const t = horloge.elapsedTime;

    // Le souffle et la tête.
    const souffle = Math.sin(t * 1.6);
    if (os.chest) os.chest.rotation.x = souffle * 0.012;
    if (os.spine) os.spine.rotation.x = souffle * 0.006;
    const baisse = etat.dort ? 0.32 : etat.ecrit ? 0.1 : 0;
    const suitX = etat.dort ? 0 : etat.pointeur.x * 0.22, suitY = etat.dort ? 0 : etat.pointeur.y * 0.1;
    if (os.neck) {
      os.neck.rotation.y = suitX * 0.4 * -sign + Math.sin(t * 0.31) * 0.03;
      os.neck.rotation.x = (baisse * 0.4 + suitY * 0.4) * sign * -1;
    }
    if (os.head) {
      os.head.rotation.y = suitX * 0.6 * -sign + Math.sin(t * 0.47) * 0.04;
      os.head.rotation.x = (baisse * 0.6 + suitY * 0.6 + Math.sin(t * 0.23) * 0.02) * sign * -1;
      os.head.rotation.z = Math.sin(t * 0.37) * 0.035 * sign;
    }
    regard.position.set(etat.pointeur.x * 1.2, teteY - etat.pointeur.y * 0.6 - (etat.ecrit ? 0.5 : 0), 1.4);

    // Le visage : l'humeur, les clignements, la bouche quand elle parle.
    const cible = Object.fromEntries(NOMS.map((n) => [n, 0]));
    Object.assign(cible, VISAGES[etat.humeur] || {});
    prochainClin -= delta;
    if (prochainClin <= 0 && clin < 0) { clin = 0; prochainClin = 2.4 + Math.random() * 3.5; }
    if (clin >= 0) { clin += delta; cible.blink = Math.sin(Math.min(clin / 0.16, 1) * Math.PI); if (clin > 0.16) clin = -1; }
    if (etat.dort) cible.blink = 1;
    if (performance.now() < etat.parleJusqua) {
      changeViseme -= delta;
      if (changeViseme <= 0) { viseme = ['aa', 'ih', 'ou', 'ee', 'oh'][Math.floor(Math.random() * 5)]; changeViseme = 0.08 + Math.random() * 0.07; }
      cible[viseme] = 0.35 + Math.random() * 0.35;
    }
    for (const n of NOMS) {
      const vitesse = n === 'blink' ? 1 : Math.min(1, delta * 10);
      courant[n] += (cible[n] - courant[n]) * vitesse;
      if (vrm.expressionManager && vrm.expressionManager.getExpression(n)) vrm.expressionManager.setValue(n, courant[n]);
    }
    vrm.update(delta);
    renderer.render(scene, camera);
  }
  boucle();
}

function lireEtat(m) {
  if (!m) return {};
  return { humeur: m.humeur || 'neutral', dort: m.etat === 'dort' };
}
