/* La constellation : sa mémoire en une boule de points, et ce qui la parcourt, en direct.
 *
 * WebGL2 écrit à la main (aucune bibliothèque : la console sert tout depuis le serveur, CSP stricte). Les points,
 * les filaments et les effets s'additionnent dans une texture ; un halo (bloom) à deux échelles s'y ajoute ; la
 * composition pose le fond. Les directions viennent du serveur (les voisins de sens de chaque élément) ; la
 * profondeur se choisit ici (le temps, la vivacité, la surface).
 *
 * Rien n'est inventé : chaque trajet est un événement du journal que le serveur a traduit (une parole et sa
 * provenance, un élément qui naît, la nuit, un rêve et ses sources). Les textes ne viennent qu'à la demande (un point
 * survolé ou ouvert), et s'écrivent par textContent : ce sont des souvenirs, pas du HTML.
 */
(() => {
  'use strict';

  const root = document.getElementById('cst');
  if (!root) return;
  const BASE = root.dataset.base;
  const CONSOLE = root.dataset.console;
  const $ = (id) => document.getElementById(id);
  const canvas = $('cst-canvas');

  // ───────────────────────── vocabulaire ─────────────────────────
  const KINDS = {
    souvenir: { label: 'souvenir', plural: 'souvenirs', color: '#58d8ff' },
    belief: { label: 'croyance', plural: 'croyances', color: '#b38cff' },
    promise: { label: 'promesse', plural: 'promesses', color: '#ffd166' },
    event: { label: 'moment', plural: 'moments', color: '#ff78b6' },
    chunk: { label: 'échange', plural: 'échanges', color: '#6b9cbd' },
    room_chunk: { label: 'échange de salon', plural: 'échanges de salon', color: '#5d86a3' },
  };
  const BORN = { souvenir: 'nouveau souvenir', belief: 'nouvelle croyance', promise: 'nouvelle promesse', event: 'nouveau moment' };
  const AGENTS = [
    { key: 'reponse', label: 'Réponse', color: '#3ff0ff',
      hint: "Elle répond : le message se pose parmi ses voisins de sens (sondés), puis ce que son prompt lui a vraiment montré s'allume (retenus)." },
    { key: 'initiative', label: 'Initiative', color: '#6dffa6', hint: "Elle écrit la première : ce qui lui est revenu pour le faire." },
    { key: 'murmure', label: 'Murmure', color: '#c7a4ff', hint: "Ce qu'elle se dit à elle-même, et ce qui le nourrit." },
    { key: 'travail', label: 'Travail', color: '#ffb14a', hint: "Un pas de travail, un projet, un réveil : la mémoire qu'il a consultée." },
    { key: 'memoire', label: 'Mémorisation', color: '#fff3a6', hint: "La consolidation : un élément qui naît près de ses voisins ; un renfort." },
    { key: 'nuit', label: 'Nuit', color: '#8190ff', hint: "Le tri de la nuit : fusions, croyances réunies ou confrontées, relecture." },
    { key: 'reve', label: 'Rêve', color: '#ff6bd6', hint: "Un rêve parcourt les souvenirs qu'il a pris, dans l'ordre." },
    { key: 'recit', label: 'Récit de soi', color: '#ffd36b', hint: "Son récit d'elle-même relit ses souvenirs." },
    { key: 'journal', label: 'Journal', color: '#ff9a5c', hint: "Son journal du jour relit ce qu'elle a vécu." },
    { key: 'autre', label: 'Autre', color: '#cfd8e3', hint: "Un autre épisode." },
  ];
  const AGENT = Object.fromEntries(AGENTS.map((a) => [a.key, a]));
  const SENSITIVITY = [
    { key: 'secret', label: 'secret', color: '#ff4d6d' },
    { key: 3, label: 'confidence', color: '#ff9f43' },
    { key: 2, label: 'personnel', color: '#ffd166' },
    { key: 1, label: 'anodin', color: '#6ee7b7' },
    { key: 0, label: 'sur elle', color: '#7dd3fc' },
    { key: -1, label: 'échange', color: '#56677d' },
  ];
  const STATUS = { active: 'tenu pour vrai', superseded: 'remplacé', merged: 'fondu dans un autre', joined: 'joint à un autre',
    honored: 'tenue', dropped: 'abandonnée', ended: 'fini', pending: 'en attente' };
  const NATURE = { claim: 'affirmation', opinion: 'opinion', preference: 'goût', hypothesis: 'hypothèse', prediction: 'prévision' };
  const FORMER = new Set(['superseded', 'merged', 'joined']);
  const EMOTIONS = {
    neutral: '#9aa3b2', happy: '#4ce08c', excited: '#ff9b3d', love: '#ff5fa2', proud: '#ffc93c', grateful: '#8be05a',
    playful: '#ffad5a', amused: '#ffe066', hopeful: '#45d6f0', relieved: '#5fe3b0', sad: '#5b84ff', angry: '#ff4b3e',
    scared: '#b07cff', disgusted: '#9acd32', frustrated: '#ff7043', lonely: '#7f8cff', anxious: '#c9a0ff', bored: '#8c97a8',
    jealous: '#6ccf6c', surprised: '#ffe14d', thinking: '#62b6ff', confused: '#d1a6ff', embarrassed: '#ff8fb1',
    nostalgic: '#e0a96d', dreamy: '#b9a4ff', determined: '#ff6f61', mischievous: '#d36bff', curious: '#3ff0ff',
    melancholic: '#7a8fd6', tender: '#ff9ecf', worried: '#c4a0ff', joy: '#4ce08c', sadness: '#5b84ff', anger: '#ff4b3e',
    fear: '#b07cff',
  };
  const DIM = '#4a5669';

  // ───────────────────────── petits outils ─────────────────────────
  const hex = (h) => [parseInt(h.slice(1, 3), 16) / 255, parseInt(h.slice(3, 5), 16) / 255, parseInt(h.slice(5, 7), 16) / 255];
  const hsl = (h, s, l) => {
    const k = (n) => (n + h / 30) % 12;
    const a = s * Math.min(l, 1 - l);
    const f = (n) => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
    return [f(0), f(8), f(4)];
  };
  const toHex = (c) => '#' + c.map((x) => Math.round(Math.max(0, Math.min(1, x)) * 255).toString(16).padStart(2, '0')).join('');
  const hashUnit = (k) => (((k * 2654435761) >>> 0) % 1000003) / 1000003;
  const hashText = (t) => { let h = 2166136261; for (let i = 0; i < t.length; i++) { h ^= t.charCodeAt(i); h = Math.imul(h, 16777619); } return (h >>> 0) / 4294967296; };
  const personColor = (i) => (i < 0 ? hex(DIM) : i < 10 ? hsl((i * 137.508 + 190) % 360, 0.85, 0.62) : hex('#7a8aa0'));
  const emotionColor = (name) => (!name ? hex(DIM) : EMOTIONS[name] ? hex(EMOTIONS[name]) : hsl(hashText(name) * 360, 0.8, 0.62));
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
  const nf = new Intl.NumberFormat('fr-FR');
  const f2 = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 2 });
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  let skew = 0; // l'heure du serveur moins celle du navigateur, en secondes
  const nowS = () => Date.now() / 1000 + skew;
  const ago = (s) => {
    if (!s) return '—';
    const d = nowS() - s;
    if (d < 60) return "à l'instant";
    if (d < 3600) return `il y a ${Math.round(d / 60)} min`;
    if (d < 86400) return `il y a ${Math.round(d / 3600)} h`;
    if (d < 86400 * 60) return `il y a ${Math.round(d / 86400)} j`;
    return new Date(s * 1000).toLocaleDateString('fr-FR', { dateStyle: 'medium' });
  };
  const clock = (s) => new Date((s || nowS()) * 1000).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  const plural = (n, one, many) => `${nf.format(n)} ${n > 1 ? many : one}`;

  // ───────────────────────── vecteurs et matrices ─────────────────────────
  const len3 = (v) => Math.hypot(v[0], v[1], v[2]);
  const scale3 = (v, s) => [v[0] * s, v[1] * s, v[2] * s];
  const norm3 = (v) => { const l = len3(v) || 1; return [v[0] / l, v[1] / l, v[2] / l]; };
  function slerp(a, b, t) {
    const d = clamp(a[0] * b[0] + a[1] * b[1] + a[2] * b[2], -1, 1);
    if (d > 0.9995) return norm3([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t]);
    let bb = b;
    if (d < -0.999) bb = norm3([a[1] - a[2], a[2] - a[0], a[0] - a[1]]); // presque opposés : un détour
    const w = Math.acos(clamp(a[0] * bb[0] + a[1] * bb[1] + a[2] * bb[2], -1, 1));
    const s = Math.sin(w), p = Math.sin((1 - t) * w) / s, q = Math.sin(t * w) / s;
    return [a[0] * p + bb[0] * q, a[1] * p + bb[1] * q, a[2] * p + bb[2] * q];
  }
  /** Un arc au-dessus de la sphère, de a à b (deux positions), soulevé au milieu. */
  function arc(a, b, t, lift = 0.22, wobble = 0) {
    const ra = len3(a), rb = len3(b);
    const na = ra > 1e-4 ? scale3(a, 1 / ra) : norm3(b), nb = rb > 1e-4 ? scale3(b, 1 / rb) : na;
    const dir = slerp(na, nb, t);
    const angle = Math.acos(clamp(na[0] * nb[0] + na[1] * nb[1] + na[2] * nb[2], -1, 1));
    let r = ra + (rb - ra) * t + lift * Math.sin(Math.PI * t) * (0.25 + angle / Math.PI);
    if (wobble) r += wobble * Math.sin(t * 19.0) * Math.sin(Math.PI * t);
    return scale3(dir, r);
  }
  function perspective(fovy, aspect, near, far) {
    const f = 1 / Math.tan(fovy / 2), q = 1 / (near - far);
    return new Float32Array([f / aspect, 0, 0, 0, 0, f, 0, 0, 0, 0, (far + near) * q, -1, 0, 0, 2 * far * near * q, 0]);
  }
  function lookAt(e, c, u) {
    let zx = e[0] - c[0], zy = e[1] - c[1], zz = e[2] - c[2];
    let l = Math.hypot(zx, zy, zz); zx /= l; zy /= l; zz /= l;
    let xx = u[1] * zz - u[2] * zy, xy = u[2] * zx - u[0] * zz, xz = u[0] * zy - u[1] * zx;
    l = Math.hypot(xx, xy, xz) || 1; xx /= l; xy /= l; xz /= l;
    const yx = zy * xz - zz * xy, yy = zz * xx - zx * xz, yz = zx * xy - zy * xx;
    return new Float32Array([xx, yx, zx, 0, xy, yy, zy, 0, xz, yz, zz, 0,
      -(xx * e[0] + xy * e[1] + xz * e[2]), -(yx * e[0] + yy * e[1] + yz * e[2]), -(zx * e[0] + zy * e[1] + zz * e[2]), 1]);
  }
  function mul4(a, b) {
    const o = new Float32Array(16);
    for (let j = 0; j < 4; j++) for (let i = 0; i < 4; i++) {
      o[i + 4 * j] = a[i] * b[4 * j] + a[i + 4] * b[4 * j + 1] + a[i + 8] * b[4 * j + 2] + a[i + 12] * b[4 * j + 3];
    }
    return o;
  }
  const rotY = (a) => { const c = Math.cos(a), s = Math.sin(a); return new Float32Array([c, 0, -s, 0, 0, 1, 0, 0, s, 0, c, 0, 0, 0, 0, 1]); };
  const rotX = (a) => { const c = Math.cos(a), s = Math.sin(a); return new Float32Array([1, 0, 0, 0, 0, c, s, 0, 0, -s, c, 0, 0, 0, 0, 1]); };
  const IDENTITY = new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]);

  // ───────────────────────── WebGL ─────────────────────────
  const gl = canvas.getContext('webgl2', { antialias: false, alpha: false, depth: false, powerPreference: 'high-performance' });
  if (!gl) { fail("Ce navigateur ne sait pas dessiner en WebGL2 : la constellation ne peut pas s'afficher."); return; }
  const floatTargets = !!gl.getExtension('EXT_color_buffer_float');

  const POINT_VS = `#version 300 es
  precision highp float;
  layout(location=0) in vec3 a_from; layout(location=1) in vec3 a_to; layout(location=2) in vec3 a_color;
  layout(location=3) in float a_size; layout(location=4) in float a_alpha; layout(location=5) in float a_seed;
  layout(location=6) in float a_boost;
  uniform mat4 u_proj, u_view; uniform float u_mix, u_stagger, u_time, u_scale, u_dist, u_sweepAmt; uniform vec4 u_sweep;
  out vec3 v_color; out float v_alpha; out float v_hot;
  void main() {
    float m = clamp(u_mix * (1.0 + u_stagger) - a_seed * u_stagger, 0.0, 1.0);
    m = m * m * (3.0 - 2.0 * m);
    vec3 p = mix(a_from, a_to, m);
    vec4 vp = u_view * vec4(p, 1.0);
    gl_Position = u_proj * vp;
    float hot = a_boost;
    if (u_sweepAmt > 0.0) { float d = dot(normalize(p + vec3(1e-5)), u_sweep.xyz) - u_sweep.w; hot += u_sweepAmt * exp(-d * d * 260.0); }
    float depth = max(-vp.z, 0.05);
    float fog = clamp(1.0 - (depth - (u_dist - 1.0)) / 2.4, 0.2, 1.0);
    float tw = 0.78 + 0.22 * sin(u_time * (0.5 + a_seed * 1.9) + a_seed * 40.0);
    gl_PointSize = a_alpha <= 0.0 ? 0.0 : clamp(a_size * (1.0 + 1.4 * hot) * u_scale / max(depth, 0.9), 1.0, 96.0);
    v_color = a_color; v_alpha = a_alpha * fog * mix(tw, 1.0, clamp(hot, 0.0, 1.0)); v_hot = hot;
  }`;
  const POINT_FS = `#version 300 es
  precision mediump float;
  in vec3 v_color; in float v_alpha; in float v_hot; out vec4 o;
  void main() {
    vec2 c = gl_PointCoord * 2.0 - 1.0; float r2 = dot(c, c);
    if (r2 > 1.0) discard;
    float core = exp(-r2 * 14.0), halo = exp(-r2 * 3.4) * 0.42;
    vec3 col = v_color * (core * 1.7 + halo) + vec3(1.0) * core * (0.18 + min(v_hot, 1.5) * 0.5);
    o = vec4(col * v_alpha * (1.0 + 0.35 * min(v_hot, 1.5)), 1.0);
  }`;
  const LINE_VS = `#version 300 es
  precision highp float;
  layout(location=0) in vec3 a_from; layout(location=1) in vec3 a_to; layout(location=2) in vec4 a_color;
  uniform mat4 u_proj, u_view, u_model; uniform float u_mix, u_dist, u_fade;
  out vec4 v_color;
  void main() {
    float m = u_mix * u_mix * (3.0 - 2.0 * u_mix);
    vec4 vp = u_view * u_model * vec4(mix(a_from, a_to, m), 1.0);
    gl_Position = u_proj * vp;
    float fog = clamp(1.0 - (-vp.z - (u_dist - 1.0)) / 2.6, 0.16, 1.0);
    v_color = vec4(a_color.rgb, a_color.a * fog * u_fade);
  }`;
  const LINE_FS = `#version 300 es
  precision mediump float;
  in vec4 v_color; out vec4 o;
  void main() { o = vec4(v_color.rgb * v_color.a, 1.0); }`;
  const FX_VS = `#version 300 es
  precision highp float;
  layout(location=0) in vec3 a_pos; layout(location=1) in vec4 a_color; layout(location=2) in float a_size;
  layout(location=3) in float a_style;
  uniform mat4 u_proj, u_view; uniform float u_scale;
  out vec4 v_color; flat out float v_style;
  void main() {
    vec4 vp = u_view * vec4(a_pos, 1.0);
    gl_Position = u_proj * vp;
    // de près, un effet ne grossit plus : il garde la taille qu'il aurait à une unité et quelque de distance
    gl_PointSize = clamp(a_size * u_scale / max(-vp.z, 1.2), 0.0, 260.0);
    v_color = a_color; v_style = a_style;
  }`;
  const FX_FS = `#version 300 es
  precision mediump float;
  in vec4 v_color; flat in float v_style; out vec4 o;
  void main() {
    vec2 c = gl_PointCoord * 2.0 - 1.0; float r = length(c);
    if (r > 1.0) discard;
    float a;
    if (v_style < 0.5) { a = exp(-r * r * 10.0) + exp(-r * r * 2.6) * 0.22; }
    else if (v_style < 1.5) { float d = (r - 0.8) * 11.0; a = exp(-d * d); }
    else {
      float d = (r - 0.62) * 14.0;
      a = exp(-r * r * 16.0) + exp(-d * d) * 0.6 + (exp(-c.x * c.x * 900.0) + exp(-c.y * c.y * 900.0)) * (1.0 - r) * 0.45;
    }
    o = vec4(v_color.rgb * a * v_color.a, 1.0);
  }`;
  const QUAD_VS = `#version 300 es
  out vec2 v_uv;
  void main() { vec2 p = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2)); v_uv = p; gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0); }`;
  const BRIGHT_FS = `#version 300 es
  precision mediump float;
  uniform sampler2D u_tex; in vec2 v_uv; out vec4 o;
  void main() { vec3 c = texture(u_tex, v_uv).rgb; float l = max(c.r, max(c.g, c.b)); o = vec4(c * smoothstep(0.04, 0.6, l), 1.0); }`;
  const BLUR_FS = `#version 300 es
  precision mediump float;
  uniform sampler2D u_tex; uniform vec2 u_dir; in vec2 v_uv; out vec4 o;
  void main() {
    vec3 c = texture(u_tex, v_uv).rgb * 0.227027;
    c += texture(u_tex, v_uv + u_dir * 1.3846154).rgb * 0.3162162; c += texture(u_tex, v_uv - u_dir * 1.3846154).rgb * 0.3162162;
    c += texture(u_tex, v_uv + u_dir * 3.2307692).rgb * 0.0702703; c += texture(u_tex, v_uv - u_dir * 3.2307692).rgb * 0.0702703;
    o = vec4(c, 1.0);
  }`;
  // la couche d'interface : des marques nettes, en pixels, posées après le halo (ni floues ni éblouies)
  const MARK_VS = `#version 300 es
  precision highp float;
  layout(location=0) in vec3 a_pos; layout(location=1) in vec4 a_color; layout(location=2) in float a_size;
  layout(location=3) in float a_style;
  uniform mat4 u_proj, u_view; uniform float u_px;
  out vec4 v_color; flat out float v_style; out float v_size;
  void main() {
    gl_Position = u_proj * u_view * vec4(a_pos, 1.0);
    gl_PointSize = a_size * u_px; v_size = a_size * u_px;
    v_color = a_color; v_style = a_style;
  }`;
  const MARK_FS = `#version 300 es
  precision mediump float;
  in vec4 v_color; flat in float v_style; in float v_size; out vec4 o;
  void main() {
    vec2 c = gl_PointCoord * 2.0 - 1.0; float r = length(c);
    float px = 2.0 / max(v_size, 1.0);              // un pixel, en unités du sprite
    float ring = 1.0 - smoothstep(0.0, 1.6 * px, abs(r - (1.0 - 2.0 * px)));
    float a = ring;
    if (v_style > 0.5) {                            // un réticule : l'anneau et quatre crans
      float tick = step(0.78, r) * step(r, 1.0) * (step(abs(c.x), 1.4 * px) + step(abs(c.y), 1.4 * px));
      a = max(ring * 0.8, min(tick, 1.0));
    }
    if (a <= 0.0) discard;
    o = vec4(v_color.rgb * a * v_color.a, a * v_color.a);
  }`;
  const COMPOSE_FS = `#version 300 es
  precision highp float;
  uniform sampler2D u_scene, u_near, u_far; uniform vec2 u_res; uniform float u_time; in vec2 v_uv; out vec4 o;
  void main() {
    vec2 p = (v_uv - 0.5) * vec2(u_res.x / u_res.y, 1.0);
    vec3 bg = mix(vec3(0.05, 0.095, 0.18), vec3(0.006, 0.01, 0.026), smoothstep(0.0, 0.95, length(p)));
    vec3 c = texture(u_scene, v_uv).rgb + texture(u_near, v_uv).rgb * 1.15 + texture(u_far, v_uv).rgb * 1.4;
    c = vec3(1.0) - exp(-c * 1.2);
    float grain = fract(sin(dot(v_uv * u_res + fract(u_time) * 91.0, vec2(12.9898, 78.233))) * 43758.5453) - 0.5;
    o = vec4(bg + c + grain * 0.014, 1.0);
  }`;

  function shader(type, src) {
    const s = gl.createShader(type);
    gl.shaderSource(s, src); gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s) || 'shader');
    return s;
  }
  function program(vs, fs) {
    const p = gl.createProgram();
    gl.attachShader(p, shader(gl.VERTEX_SHADER, vs)); gl.attachShader(p, shader(gl.FRAGMENT_SHADER, fs));
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p) || 'programme');
    const u = {};
    const count = gl.getProgramParameter(p, gl.ACTIVE_UNIFORMS);
    for (let i = 0; i < count; i++) { const info = gl.getActiveUniform(p, i); u[info.name] = gl.getUniformLocation(p, info.name); }
    return { p, u };
  }
  let PROG;
  try {
    PROG = {
      point: program(POINT_VS, POINT_FS), line: program(LINE_VS, LINE_FS), fx: program(FX_VS, FX_FS),
      bright: program(QUAD_VS, BRIGHT_FS), blur: program(QUAD_VS, BLUR_FS), compose: program(QUAD_VS, COMPOSE_FS),
      mark: program(MARK_VS, MARK_FS),
    };
  } catch (err) {
    fail(`Le rendu n'a pas pu se préparer (${err.message}).`);
    return;
  }

  /** Un tampon et sa description : [emplacement, nombre de flottants] dans l'ordre de l'entrelacement. */
  function layout(attrs) {
    const vao = gl.createVertexArray(), buf = gl.createBuffer();
    gl.bindVertexArray(vao); gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    const stride = attrs.reduce((s, [, n]) => s + n, 0) * 4;
    let off = 0;
    for (const [loc, n] of attrs) { gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, n, gl.FLOAT, false, stride, off); off += n * 4; }
    gl.bindVertexArray(null);
    return { vao, buf, count: 0, floats: stride / 4 };
  }
  const G = {
    points: layout([[0, 3], [1, 3], [2, 3], [3, 1], [4, 1], [5, 1]]),
    edges: layout([[0, 3], [1, 3], [2, 4]]),
    grid: layout([[0, 3], [1, 3], [2, 4]]),
    fxLines: layout([[0, 3], [1, 3], [2, 4]]),
    stars: layout([[0, 3], [1, 4], [2, 1], [3, 1]]),
    fxPoints: layout([[0, 3], [1, 4], [2, 1], [3, 1]]),
    marks: layout([[0, 3], [1, 4], [2, 1], [3, 1]]),
    quad: gl.createVertexArray(),
  };
  // la chaleur de chaque point, à part : elle change à chaque image
  G.boost = gl.createBuffer();
  gl.bindVertexArray(G.points.vao);
  gl.bindBuffer(gl.ARRAY_BUFFER, G.boost);
  gl.enableVertexAttribArray(6); gl.vertexAttribPointer(6, 1, gl.FLOAT, false, 4, 0);
  gl.bindVertexArray(null);

  function upload(target, data, usage = gl.STATIC_DRAW) {
    gl.bindBuffer(gl.ARRAY_BUFFER, target.buf);
    gl.bufferData(gl.ARRAY_BUFFER, data, usage);
    target.count = data.length / target.floats;
  }

  // les cibles de rendu : la scène, puis deux échelles de halo
  let T = null;
  function renderTarget(w, h) {
    const tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, floatTargets ? gl.RGBA16F : gl.RGBA8, w, h, 0, gl.RGBA,
      floatTargets ? gl.HALF_FLOAT : gl.UNSIGNED_BYTE, null);
    for (const [k, v] of [[gl.TEXTURE_MIN_FILTER, gl.LINEAR], [gl.TEXTURE_MAG_FILTER, gl.LINEAR],
      [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE]]) gl.texParameteri(gl.TEXTURE_2D, k, v);
    const fb = gl.createFramebuffer();
    gl.bindFramebuffer(gl.FRAMEBUFFER, fb);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    return { tex, fb, w, h };
  }
  function freeTarget(t) { gl.deleteTexture(t.tex); gl.deleteFramebuffer(t.fb); }
  function resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.max(1, Math.round(canvas.clientWidth * dpr)), h = Math.max(1, Math.round(canvas.clientHeight * dpr));
    if (T && canvas.width === w && canvas.height === h) return;
    canvas.width = w; canvas.height = h;
    if (T) Object.values(T).forEach(freeTarget);
    const hw = Math.max(1, w >> 1), hh = Math.max(1, h >> 1), qw = Math.max(1, w >> 2), qh = Math.max(1, h >> 2);
    T = { scene: renderTarget(w, h), a: renderTarget(hw, hh), b: renderTarget(hw, hh), c: renderTarget(qw, qh), d: renderTarget(qw, qh) };
  }

  // ───────────────────────── la carte ─────────────────────────
  const S = {
    ready: false, n: 0, keys: [], index: new Map(), kindNames: [], persons: [], emotions: [], statuses: [],
    m: null, // colonnes : kind, person, emotion, importance, confidence, born, recalled, recalls, sensitivity, secret, status
    dir: new Float32Array(0), seed: new Float32Array(0), from: new Float32Array(0), to: new Float32Array(0),
    color: new Float32Array(0), size: new Float32Array(0), alpha: new Float32Array(0), boost: new Float32Array(0),
    edges: [], edgeSims: [], total: 0, shown: 0, her: root.dataset.her || '',
    colorMode: 'kind', depthMode: 'age', showEdges: true, showChunks: true, showFormer: false, focus: null,
    morph: { start: 0, dur: 1, stagger: 0 }, hotSet: new Set(), selected: -1, hover: -1,
    search: null, preview: -1, // search : { q, hits: [{key, how, score, text}], idx: [indices], query: [x, y, z] | null }
  };

  function isFormer(i) { const s = S.m.status[i]; return s >= 0 && FORMER.has(S.statuses[s]); }
  function isChunk(i) { return S.kindNames[S.m.kind[i]].endsWith('chunk'); }

  function computeTargets() {
    const n = S.n, to = new Float32Array(n * 3), m = S.m;
    let rank = null;
    if (S.depthMode === 'age') {
      const order = Array.from({ length: n }, (_, i) => i).sort((a, b) => (m.born[a] - m.born[b]) || (S.keys[a] - S.keys[b]));
      rank = new Float32Array(n);
      order.forEach((i, r) => { rank[i] = n > 1 ? r / (n - 1) : 1; });
    }
    const now = nowS();
    for (let i = 0; i < n; i++) {
      let r;
      if (S.depthMode === 'age') r = 0.3 + 0.7 * rank[i] + (S.seed[i] - 0.5) * 0.03;
      else if (S.depthMode === 'vivid') {
        const imp = m.importance[i] < 0 ? 0.3 : m.importance[i];
        const rec = m.recalled[i] > 0 ? Math.exp(-(now - m.recalled[i]) / (10 * 86400)) : 0;
        r = 0.3 + 0.7 * (0.45 * imp + 0.35 * rec + 0.2 * Math.min(m.recalls[i], 12) / 12) + (S.seed[i] - 0.5) * 0.03;
      } else r = 1 + (S.seed[i] - 0.5) * 0.045;
      to[i * 3] = S.dir[i * 3] * r; to[i * 3 + 1] = S.dir[i * 3 + 1] * r; to[i * 3 + 2] = S.dir[i * 3 + 2] * r;
    }
    return to;
  }

  function ageRanks() {
    const n = S.n, order = Array.from({ length: n }, (_, i) => i).sort((a, b) => (S.m.born[a] - S.m.born[b]) || (S.keys[a] - S.keys[b]));
    const out = new Float32Array(n);
    order.forEach((i, r) => { out[i] = n > 1 ? r / (n - 1) : 1; });
    return out;
  }
  function sensitivityKey(i) { return S.m.secret[i] ? 'secret' : S.m.sensitivity[i]; }
  function colorOf(i, ages) {
    const m = S.m;
    switch (S.colorMode) {
      case 'person': return personColor(m.person[i]);
      case 'emotion': return emotionColor(m.emotion[i] >= 0 ? S.emotions[m.emotion[i]] : '');
      case 'sensitivity': { const k = sensitivityKey(i); return hex((SENSITIVITY.find((s) => s.key === k) || SENSITIVITY[5]).color); }
      case 'age': {
        const t = ages[i];
        const old = hex('#3b2a9f'), mid = hex('#2f9bff'), young = hex('#eafcff');
        const [a, b, u] = t < 0.6 ? [old, mid, t / 0.6] : [mid, young, (t - 0.6) / 0.4];
        return [a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u, a[2] + (b[2] - a[2]) * u];
      }
      default: return hex((KINDS[S.kindNames[m.kind[i]]] || { color: '#cfd8e3' }).color);
    }
  }
  function matchesFocus(i) {
    if (S.search && !S.search.set.has(i)) return false;
    const f = S.focus;
    if (!f) return true;
    const m = S.m;
    if (f.mode === 'kind') return m.kind[i] === f.value;
    if (f.mode === 'person') return m.person[i] === f.value;
    if (f.mode === 'emotion') return m.emotion[i] === f.value;
    if (f.mode === 'sensitivity') return sensitivityKey(i) === f.value;
    return true;
  }
  function computeStyle() {
    const n = S.n, m = S.m, now = nowS();
    S.color = new Float32Array(n * 3); S.size = new Float32Array(n); S.alpha = new Float32Array(n);
    const ages = S.colorMode === 'age' ? ageRanks() : null;
    for (let i = 0; i < n; i++) {
      const c = colorOf(i, ages);
      S.color.set(c, i * 3);
      const chunk = isChunk(i);
      const imp = m.importance[i] < 0 ? 0.45 : m.importance[i];
      const fresh = m.recalled[i] > 0 && now - m.recalled[i] < 3 * 86400 ? 0.7 : 0;
      let size = chunk ? 1.6 : 2.2 + 2.8 * imp + fresh;
      let alpha = chunk ? 0.42 : 0.95;
      if (chunk && !S.showChunks) alpha = 0;
      if (isFormer(i)) { alpha = S.showFormer ? 0.2 : 0; size *= 0.8; }
      if (!matchesFocus(i)) { alpha *= 0.1; size *= 0.75; }
      S.size[i] = size; S.alpha[i] = alpha;
    }
  }
  function uploadPoints() {
    const n = S.n, buf = new Float32Array(n * 12);
    for (let i = 0; i < n; i++) {
      const o = i * 12;
      buf[o] = S.from[i * 3]; buf[o + 1] = S.from[i * 3 + 1]; buf[o + 2] = S.from[i * 3 + 2];
      buf[o + 3] = S.to[i * 3]; buf[o + 4] = S.to[i * 3 + 1]; buf[o + 5] = S.to[i * 3 + 2];
      buf[o + 6] = S.color[i * 3]; buf[o + 7] = S.color[i * 3 + 1]; buf[o + 8] = S.color[i * 3 + 2];
      buf[o + 9] = S.size[i]; buf[o + 10] = S.alpha[i]; buf[o + 11] = S.seed[i];
    }
    upload(G.points, buf);
    gl.bindBuffer(gl.ARRAY_BUFFER, G.boost);
    gl.bufferData(gl.ARRAY_BUFFER, S.boost, gl.DYNAMIC_DRAW);
  }
  function uploadEdges() {
    const out = [];
    for (let e = 0; e < S.edges.length; e += 2) {
      const a = S.edges[e], b = S.edges[e + 1];
      if (!(S.alpha[a] > 0.05 && S.alpha[b] > 0.05)) continue;
      const sim = S.edgeSims[e >> 1] ?? 0.5;
      const al = (0.06 + 0.26 * clamp((sim - 0.3) / 0.55, 0, 1)) * Math.min(S.alpha[a], S.alpha[b]);
      const c = [(S.color[a * 3] + S.color[b * 3]) / 2, (S.color[a * 3 + 1] + S.color[b * 3 + 1]) / 2, (S.color[a * 3 + 2] + S.color[b * 3 + 2]) / 2];
      for (const i of [a, b]) out.push(S.from[i * 3], S.from[i * 3 + 1], S.from[i * 3 + 2], S.to[i * 3], S.to[i * 3 + 1], S.to[i * 3 + 2], c[0], c[1], c[2], al);
    }
    upload(G.edges, new Float32Array(out));
  }

  /** Où sont les points à l'instant (au milieu d'une transition, le même calcul que le nuanceur). */
  function currentPositions() {
    const n = S.n, out = new Float32Array(n * 3), mix = morphMix(), st = S.morph.stagger;
    for (let i = 0; i < n; i++) {
      let m = clamp(mix * (1 + st) - S.seed[i] * st, 0, 1);
      m = m * m * (3 - 2 * m);
      for (let a = 0; a < 3; a++) out[i * 3 + a] = S.from[i * 3 + a] + (S.to[i * 3 + a] - S.from[i * 3 + a]) * m;
    }
    return out;
  }
  function morphMix() { return clamp((performance.now() - S.morph.start) / S.morph.dur, 0, 1); }
  /** Une transition vers les cibles du moment : chacun part d'où il est. */
  function morphTo(dur = 1600, stagger = 0, from = null) {
    S.from = from || currentPositions();
    S.to = computeTargets();
    S.morph = { start: performance.now(), dur, stagger };
    uploadPoints(); uploadEdges();
  }
  function restyle() { computeStyle(); uploadPoints(); uploadEdges(); renderLegend(); }
  function posOf(i) { return [S.to[i * 3], S.to[i * 3 + 1], S.to[i * 3 + 2]]; }

  function installMap(d) {
    const previous = new Map();
    if (S.ready) { const cur = currentPositions(); S.keys.forEach((k, i) => previous.set(k, [cur[i * 3], cur[i * 3 + 1], cur[i * 3 + 2]])); }
    const P = d.points, n = d.shown;
    S.her = d.her || S.her; S.total = d.total; S.shown = n; S.n = n;
    S.keys = P.key.slice(); S.index = new Map(S.keys.map((k, i) => [k, i]));
    S.kindNames = d.kinds.slice(); S.persons = d.persons.slice(); S.emotions = d.emotions.slice(); S.statuses = d.statuses.slice();
    S.m = { kind: P.kind.slice(), person: P.person.slice(), emotion: P.emotion.slice(), importance: P.importance.slice(),
      confidence: P.confidence.slice(), born: P.born.slice(), recalled: P.recalled.slice(), recalls: P.recalls.slice(),
      sensitivity: P.sensitivity.slice(), secret: P.secret.slice(), status: P.status.slice() };
    S.dir = Float32Array.from(P.dir);
    S.seed = Float32Array.from(S.keys, hashUnit);
    S.boost = new Float32Array(n); S.hotSet.clear();
    S.edges = d.edges.slice(); S.edgeSims = d.edge_sims.slice();
    S.selected = -1; S.hover = -1; S.preview = -1;
    resolveSearch();
    computeStyle();
    const first = !S.ready;
    let from;
    if (first) from = new Float32Array(n * 3); // tout part du centre
    else {
      const to = computeTargets();
      from = new Float32Array(n * 3);
      S.keys.forEach((k, i) => { const p = previous.get(k) || [to[i * 3] * 1.6, to[i * 3 + 1] * 1.6, to[i * 3 + 2] * 1.6]; from.set(p, i * 3); });
    }
    morphTo(first ? 2800 : 1500, first ? 1.1 : 0, from);
    S.ready = true;
    renderLegend(); renderNote();
  }

  /** Un élément né sous nos yeux : il entre dans la carte, près de ses voisins. */
  function addPoint(ev) {
    if (S.index.has(ev.key)) return S.index.get(ev.key);
    const cur = currentPositions();
    const i = S.n;
    S.n += 1;
    S.keys.push(ev.key); S.index.set(ev.key, i);
    let kind = S.kindNames.indexOf(ev.kind);
    if (kind < 0) { S.kindNames.push(ev.kind); kind = S.kindNames.length - 1; }
    let person = -1;
    if (ev.person) {
      person = S.persons.findIndex((p) => p.key === ev.person);
      if (person < 0) { S.persons.push({ key: ev.person, name: ev.person_name || ev.person, count: 0 }); person = S.persons.length - 1; }
      S.persons[person].count += 1;
    }
    const m = S.m;
    m.kind.push(kind); m.person.push(person); m.emotion.push(-1); m.importance.push(ev.importance ?? 0.5);
    m.confidence.push(-1); m.born.push(ev.at || Math.round(nowS())); m.recalled.push(0); m.recalls.push(0);
    m.sensitivity.push(-1); m.secret.push(0); m.status.push(-1);
    const grow = (arr, size, vals) => { const out = new Float32Array(size); out.set(arr); out.set(vals, arr.length); return out; };
    S.dir = grow(S.dir, S.n * 3, ev.dir);
    S.seed = grow(S.seed, S.n, [hashUnit(ev.key)]);
    S.boost = grow(S.boost, S.n, [0]);
    for (const k of ev.near || []) if (S.index.has(k)) { S.edges.push(S.index.get(k), i); S.edgeSims.push(0.6); }
    S.shown = S.n; S.total += 1;
    computeStyle();
    const from = grow(cur, S.n * 3, scale3(ev.dir, 2.4));
    morphTo(1300, 0, from);
    renderLegend(); renderNote();
    return i;
  }
  function markFormer(i, status) {
    let s = S.statuses.indexOf(status);
    if (s < 0) { S.statuses.push(status); s = S.statuses.length - 1; }
    S.m.status[i] = s;
    restyle();
  }
  function heat(i, v) { if (i < 0 || i >= S.n) return; S.boost[i] = Math.max(S.boost[i], v); S.hotSet.add(i); }

  // ───────────────────────── la caméra ─────────────────────────
  const cam = { yaw: 0.6, pitch: 0.22, dist: 3.6, tYaw: 0.6, tPitch: 0.22, tDist: 3.6, vYaw: 0, vPitch: 0,
    auto: true, lastInput: 0, flyUntil: 0 };
  let proj = IDENTITY, view = IDENTITY, pv = IDENTITY, eye = [0, 0, 3];
  function updateCamera(dt) {
    const idle = performance.now() - cam.lastInput > 3500;
    if (!drag.active) {
      cam.tYaw += cam.vYaw * dt; cam.tPitch = clamp(cam.tPitch + cam.vPitch * dt, -1.35, 1.35);
      cam.vYaw *= Math.exp(-dt * 3); cam.vPitch *= Math.exp(-dt * 3);
      if (cam.auto && idle && !S.search && S.selected < 0) cam.tYaw += dt * 0.055;
    }
    const k = 1 - Math.exp(-dt * (performance.now() < cam.flyUntil ? 2.4 : 7));
    cam.yaw += (cam.tYaw - cam.yaw) * k; cam.pitch += (cam.tPitch - cam.pitch) * k; cam.dist += (cam.tDist - cam.dist) * k;
    const cp = Math.cos(cam.pitch);
    eye = [cam.dist * cp * Math.sin(cam.yaw), cam.dist * Math.sin(cam.pitch), cam.dist * cp * Math.cos(cam.yaw)];
    proj = perspective(0.78, canvas.width / canvas.height, 0.05, 200);
    view = lookAt(eye, [0, 0, 0], [0, 1, 0]);
    pv = mul4(proj, view);
  }
  function focusOn(i) {
    const p = posOf(i), l = len3(p) || 1;
    let yaw = Math.atan2(p[0], p[2]);
    while (yaw - cam.tYaw > Math.PI) yaw -= 2 * Math.PI;
    while (yaw - cam.tYaw < -Math.PI) yaw += 2 * Math.PI;
    cam.tYaw = yaw; cam.tPitch = clamp(Math.asin(p[1] / l), -1.3, 1.3); cam.tDist = Math.max(2.1, l + 1.7);
    cam.vYaw = cam.vPitch = 0; cam.lastInput = performance.now();
  }
  /** Voler vers une direction : la caméra s'y place, à cette distance du centre, lentement. */
  function flyTo(dir, dist) {
    const d = norm3(dir);
    let yaw = Math.atan2(d[0], d[2]);
    while (yaw - cam.tYaw > Math.PI) yaw -= 2 * Math.PI;
    while (yaw - cam.tYaw < -Math.PI) yaw += 2 * Math.PI;
    cam.tYaw = yaw; cam.tPitch = clamp(Math.asin(clamp(d[1], -1, 1)), -1.3, 1.3); cam.tDist = clamp(dist, 1.6, 6);
    cam.vYaw = cam.vPitch = 0; cam.lastInput = performance.now(); cam.flyUntil = performance.now() + 2200;
  }
  /** Le cadrage d'un groupe de points : leur direction moyenne, plus loin s'ils sont épars. */
  function frameOn(indices, dir = null) {
    if (!indices.length && !dir) return;
    let c = dir;
    if (!c) { c = [0, 0, 0]; for (const i of indices) { const p = norm3(posOf(i)); c[0] += p[0]; c[1] += p[1]; c[2] += p[2]; } }
    c = norm3(c);
    let spread = 0;
    for (const i of indices) { const p = norm3(posOf(i)); spread += Math.acos(clamp(p[0] * c[0] + p[1] * c[1] + p[2] * c[2], -1, 1)); }
    spread = indices.length ? spread / indices.length : 0.3;
    flyTo(c, 2.3 + spread * 2.2);
  }
  function home() { cam.tDist = 3.6; cam.tPitch = 0.22; cam.vYaw = cam.vPitch = 0; cam.lastInput = 0; }

  // ───────────────────────── le décor : étoiles et grille ─────────────────────────
  (function scenery() {
    const stars = [];
    let s = 7;
    const rnd = () => { s = (s * 16807) % 2147483647; return s / 2147483647; };
    for (let i = 0; i < 1600; i++) {
      const d = norm3([rnd() * 2 - 1, rnd() * 2 - 1, rnd() * 2 - 1]), r = 25 + rnd() * 40, b = 0.25 + rnd() * 0.75;
      const tint = rnd() < 0.15 ? [1, 0.85, 0.7] : rnd() < 0.3 ? [0.7, 0.85, 1] : [0.9, 0.95, 1];
      stars.push(d[0] * r, d[1] * r, d[2] * r, tint[0], tint[1], tint[2], b * 0.55, 1.2 + rnd() * 2.2, 0);
    }
    upload(G.stars, new Float32Array(stars));
    const grid = [];
    const seg = (a, b, alpha, c = [0.37, 0.86, 1]) => grid.push(...a, ...a, ...c, alpha, ...b, ...b, ...c, alpha);
    const R = 1.12;
    for (let lat = -60; lat <= 60; lat += 30) {
      const y = Math.sin(lat * Math.PI / 180) * R, rr = Math.cos(lat * Math.PI / 180) * R;
      for (let j = 0; j < 96; j++) {
        const a = j / 96 * 2 * Math.PI, b = (j + 1) / 96 * 2 * Math.PI;
        if (lat !== 0 && j % 4 === 3) continue; // des pointillés, sauf l'équateur
        seg([Math.cos(a) * rr, y, Math.sin(a) * rr], [Math.cos(b) * rr, y, Math.sin(b) * rr], lat === 0 ? 0.16 : 0.06);
      }
    }
    for (let lon = 0; lon < 180; lon += 30) {
      const t = lon * Math.PI / 180;
      for (let j = 0; j < 64; j++) {
        if (j % 4 === 3) continue;
        const a = j / 64 * 2 * Math.PI, b = (j + 1) / 64 * 2 * Math.PI;
        seg([Math.cos(a) * Math.cos(t) * R, Math.sin(a) * R, Math.cos(a) * Math.sin(t) * R],
          [Math.cos(b) * Math.cos(t) * R, Math.sin(b) * R, Math.cos(b) * Math.sin(t) * R], 0.045);
      }
    }
    // un anneau gradué, plus loin
    const R2 = 1.42;
    for (let j = 0; j < 180; j++) {
      const a = j / 180 * 2 * Math.PI, b = (j + 0.5) / 180 * 2 * Math.PI;
      seg([Math.cos(a) * R2, 0, Math.sin(a) * R2], [Math.cos(b) * R2, 0, Math.sin(b) * R2], 0.12, [0.5, 0.9, 1]);
      if (j % 10 === 0) seg([Math.cos(a) * R2, 0, Math.sin(a) * R2], [Math.cos(a) * (R2 + 0.06), 0, Math.sin(a) * (R2 + 0.06)], 0.3, [0.6, 0.95, 1]);
    }
    upload(G.grid, new Float32Array(grid));
  })();

  // ───────────────────────── les effets ─────────────────────────
  const FX = [];
  let fxP = [], fxL = [], marks = [];
  const mark = (p, c, px, a, style = 0) => marks.push(p[0], p[1], p[2], c[0], c[1], c[2], a, px, style);
  /** Où un point tombe à l'écran (en pixels CSS), ou ``null`` derrière la caméra. */
  function onScreen(p) {
    const cw = pv[3] * p[0] + pv[7] * p[1] + pv[11] * p[2] + pv[15];
    if (cw <= 0.05) return null;
    return [((pv[0] * p[0] + pv[4] * p[1] + pv[8] * p[2] + pv[12]) / cw * 0.5 + 0.5) * canvas.clientWidth,
      (1 - ((pv[1] * p[0] + pv[5] * p[1] + pv[9] * p[2] + pv[13]) / cw * 0.5 + 0.5)) * canvas.clientHeight];
  }
  /** Des anneaux autour de ces points : ceux qui se touchent à l'écran n'en font qu'un, centré sur leur groupe et
   * assez grand pour tous les entourer — des souvenirs presque identiques ne font pas une tache de dix anneaux. */
  function ringsAround(indices, c, alpha, limit = 120) {
    const groups = [];
    let n = 0;
    for (const i of indices) {
      if (i < 0 || n >= limit) continue;
      n += 1;
      const p = posOf(i), at = onScreen(p);
      if (!at) continue;
      const g = groups.find((g) => g.r < 70 && Math.hypot(g.x - at[0], g.y - at[1]) < 22 + g.r);
      if (g) {
        g.members.push([p, at]);
        g.x = g.members.reduce((s, m) => s + m[1][0], 0) / g.members.length;
        g.y = g.members.reduce((s, m) => s + m[1][1], 0) / g.members.length;
        g.r = Math.max(...g.members.map((m) => Math.hypot(m[1][0] - g.x, m[1][1] - g.y)));
      } else groups.push({ x: at[0], y: at[1], r: 0, members: [[p, at]] });
    }
    for (const g of groups) {
      const k = g.members.length, centre = [0, 0, 0];
      for (const [p] of g.members) { centre[0] += p[0] / k; centre[1] += p[1] / k; centre[2] += p[2] / k; }
      mark(centre, c, 2 * (g.r + 9 + Math.min(k, 6)), alpha);
    }
  }
  let sweep = null;
  const addFx = (f) => { f.t0 = performance.now() + (f.delay || 0); FX.push(f); return f; };
  const glow = (p, c, size, a, style = 0) => fxP.push(p[0], p[1], p[2], c[0], c[1], c[2], a, size, style);
  const line = (a, b, c, al) => fxL.push(a[0], a[1], a[2], a[0], a[1], a[2], c[0], c[1], c[2], al, b[0], b[1], b[2], b[0], b[1], b[2], c[0], c[1], c[2], al);

  function ring(pos, c, dur = 900, s0 = 6, s1 = 70, a0 = 0.9, delay = 0) {
    return addFx({ delay, dur, draw(t) { glow(pos, c, s0 + (s1 - s0) * ease(t), a0 * (1 - t) * (1 - t), 1); } });
  }
  function beacon(pos, c, dur = 4200) {
    return addFx({ dur, draw(t, now) {
      const a = Math.min(1, t * 8) * (1 - Math.pow(t, 3));
      glow(pos, c, 40 + 8 * Math.sin(now / 160), a * 0.95, 2);
      glow(pos, c, 120, a * 0.18, 0);
    } });
  }
  function comet(a, b, c, { delay = 0, dur = 1000, lift = 0.22, wobble = 0, size = 22, trail = 18, onArrive = null } = {}) {
    let arrived = false;
    return addFx({ delay, dur: dur + 450, draw(t, now, elapsed) {
      const u = clamp(elapsed / dur, 0, 1), e = ease(u);
      const fade = elapsed > dur ? 1 - (elapsed - dur) / 450 : 1;
      let prev = null;
      for (let j = trail; j >= 0; j--) {
        const tt = clamp(e - j * 0.028, 0, 1);
        const p = arc(a, b, tt, lift, wobble);
        if (prev) line(prev, p, c, (1 - j / trail) * 0.75 * fade);
        prev = p;
      }
      if (u < 1) { glow(prev, c, size, 1, 0); glow(prev, [1, 1, 1], size * 0.35, 0.9, 0); }
      if (u >= 1 && !arrived) { arrived = true; if (onArrive) onArrive(); }
    } });
  }
  function rays(from, targets, c, dur = 3200, delay = 0) {
    return addFx({ delay, dur, draw(t) {
      const a = Math.min(1, t * 6) * (1 - t);
      for (const [p, w] of targets) line(from, p, c, a * (0.08 + 0.22 * w));
    } });
  }
  function traces(from, targets, c, dur = 5200, delay = 0) {
    return addFx({ delay, dur, draw(t) { const a = Math.sin(Math.PI * Math.min(1, t * 1.2)) * 0.35; for (const p of targets) line(from, p, c, a); } });
  }

  // ───────────────────────── ce que font les événements ─────────────────────────
  const counters = Object.fromEntries(AGENTS.map((a) => [a.key, 0]));
  const lastActive = {};
  function agentOf(key) { return AGENT[key] || AGENT.autre; }
  function idx(key) { return S.index.has(key) ? S.index.get(key) : -1; }

  function play(ev) {
    const agent = agentOf(ev.agent);
    const c = hex(agent.color);
    counters[agent.key] = (counters[agent.key] || 0) + 1;
    lastActive[agent.key] = performance.now();
    renderAgents();
    flashLive();
    const handlers = { rappel: playRecall, naissance: playBirth, renfort: playReinforce, fusion: playFusion,
      confrontation: playConfrontation, relecture: playReread, parcours: playPath };
    if (ev.type === 'carte') { log(ev, agent, 'la carte change : quelque chose a été oublié'); loadMap(); return; }
    const handler = handlers[ev.type];
    if (handler) handler(ev, agent, c);
  }

  function playRecall(ev, agent, c) {
    const shown = ev.shown.map(idx).filter((i) => i >= 0);
    const probed = (ev.probed || []).map(([k, s]) => [idx(k), s]).filter(([i]) => i >= 0);
    const q = scale3(ev.query, 1.12); // le message se pose à la surface, au-dessus de ce qui lui ressemble
    beacon(q, c, 4600);
    ring(q, c, 1100, 10, 110, 0.6);
    const sims = probed.map(([, s]) => s), lo = Math.min(...sims, 1), hi = Math.max(...sims, 0);
    rays(q, probed.map(([i, s]) => [posOf(i), hi > lo ? (s - lo) / (hi - lo) : 0.5]), c, 3400, 150);
    probed.forEach(([i], j) => setTimeout(() => heat(i, 0.35), 200 + j * 25));
    // une grappe de souvenirs presque identiques reçoit un seul anneau, pas dix qui s'additionnent
    const ringed = [];
    shown.forEach((i, j) => {
      const at = onScreen(posOf(i));
      const lone = !at || !ringed.some((r) => Math.hypot(r[0] - at[0], r[1] - at[1]) < 24);
      if (lone && at) ringed.push(at);
      comet(q, posOf(i), c, { delay: 500 + j * 150, dur: 850 + (j % 3) * 90, size: lone ? 22 : 12, onArrive: () => {
        heat(i, lone ? 1.1 : 0.7);
        if (lone) ring(posOf(i), c, 900, 6, 48, 0.55);
      } });
    });
    traces(q, shown.map(posOf), c, 5600, 600);
    const who = ev.who || '';
    const title = `${agent.label}${who ? ' · ' + who : ''}`;
    const detail = `${probed.length ? `${probed.length} sondés · ` : ''}${plural(shown.length, 'élément lui revient', 'éléments lui reviennent')}`;
    caption(agent, title, ev.message ? `« ${ev.message} »` : detail);
    const text = `${who ? who + ' — ' : ''}${ev.message ? `« ${ev.message} » — ` : ''}${detail}`;
    log(ev, agent, text, ev.seq ? { href: `${CONSOLE}/parole/${ev.seq}`, label: 'pourquoi ↗' } : null);
  }
  function playBirth(ev, agent, c) {
    const i = addPoint(ev);
    const p = posOf(i);
    comet(scale3(ev.dir, 2.4), p, c, { dur: 1200, lift: 0.05, size: 26, onArrive: () => {
      heat(i, 2.2); ring(p, c, 1300, 8, 120, 1); ring(p, [1, 1, 1], 900, 4, 50, 0.7, 120);
    } });
    for (let j = 0; j < 10; j++) {
      const off = norm3([Math.sin(j * 2.4) + (hashUnit(ev.key + j) - 0.5), Math.cos(j * 1.7), Math.sin(j * 0.9 + 1)]);
      comet([p[0] + off[0] * 0.35, p[1] + off[1] * 0.35, p[2] + off[2] * 0.35], p, c, { delay: 700 + j * 40, dur: 600, lift: 0, size: 8, trail: 8 });
    }
    traces(p, (ev.near || []).map(idx).filter((k) => k >= 0).map(posOf), c, 6000, 1300);
    const label = BORN[ev.kind] || 'nouvel élément';
    caption(agent, label, ev.person_name ? `à propos de ${ev.person_name}` : 'sa mémoire grandit');
    log(ev, agent, `${label}${ev.person_name ? ' · ' + ev.person_name : ''}`, { href: `${CONSOLE}/evenement/${ev.key}`, label: 'voir ↗' });
  }
  function playReinforce(ev, agent, c) {
    const i = idx(ev.key);
    if (i < 0) return;
    heat(i, 1.5); ring(posOf(i), c, 1100, 6, 90, 1); ring(posOf(i), c, 1100, 6, 60, 0.6, 250);
    const kind = (KINDS[S.kindNames[S.m.kind[i]]] || { label: 'élément' }).label;
    log(ev, agent, `${kind} renforcé${ev.corroborated ? ' · corroboré par quelqu’un d’autre' : ''}`, { href: `${CONSOLE}/evenement/${ev.key}`, label: 'voir ↗' });
  }
  function playFusion(ev, agent, c) {
    ev.pairs.forEach(([kept, fused], j) => {
      const a = idx(fused), b = idx(kept);
      if (a < 0 || b < 0) return;
      comet(posOf(a), posOf(b), c, { delay: j * 260, dur: 1100, onArrive: () => { heat(b, 1.6); ring(posOf(b), c); markFormer(a, ev.how === 'fondu' ? 'merged' : 'joined'); } });
    });
    caption(agent, 'La nuit trie', plural(ev.pairs.length, ev.how === 'fondu' ? 'souvenir fondu' : 'croyance réunie', ev.how === 'fondu' ? 'souvenirs fondus' : 'croyances réunies'));
    log(ev, agent, plural(ev.pairs.length, ev.how === 'fondu' ? 'souvenir fondu dans un autre' : 'croyance réunie à une autre',
      ev.how === 'fondu' ? 'souvenirs fondus dans un autre' : 'croyances réunies à une autre'));
  }
  function playConfrontation(ev, agent) {
    const red = hex('#ff5d5d'), amber = hex('#ffb347');
    ev.replaced.forEach(([winner, loser], j) => {
      const a = idx(winner), b = idx(loser);
      if (a < 0 || b < 0) return;
      comet(posOf(a), posOf(b), red, { delay: j * 300, dur: 1000, onArrive: () => { ring(posOf(b), red); markFormer(b, 'superseded'); } });
    });
    ev.contested.forEach(([x, y], j) => {
      const a = idx(x), b = idx(y);
      if (a < 0 || b < 0) return;
      comet(posOf(a), posOf(b), amber, { delay: j * 300, dur: 1000, onArrive: () => heat(b, 1.2) });
      comet(posOf(b), posOf(a), amber, { delay: j * 300 + 150, dur: 1000, onArrive: () => heat(a, 1.2) });
    });
    caption(agent, 'La nuit confronte', `${ev.replaced.length} remplacée(s) · ${ev.contested.length} contestée(s)`);
    log(ev, agent, `confrontation : ${ev.replaced.length} croyance(s) remplacée(s), ${ev.contested.length} contestée(s)`);
  }
  function playReread(ev, agent) {
    const n = norm3([Math.sin(ev.seq || 1), 0.6, Math.cos((ev.seq || 1) * 1.3)]);
    sweep = { n, t0: performance.now(), dur: 3600 };
    caption(agent, 'La nuit relit', `${nf.format(ev.readings)} lecture(s) · ${nf.format(ev.pairs)} paire(s)`);
    log(ev, agent, `relecture de la nuit · ${plural(ev.readings, 'lecture', 'lectures')}, ${plural(ev.pairs, 'paire confrontée', 'paires confrontées')}`);
  }
  function playPath(ev, agent, c) {
    const nodes = ev.keys.map(idx).filter((i) => i >= 0);
    if (!nodes.length) return;
    const wobble = ev.agent === 'reve' ? 0.06 : 0;
    const hop = 700;
    let prev = scale3(norm3(posOf(nodes[0])), 2.2);
    nodes.forEach((i, j) => {
      const p = posOf(i);
      comet(prev, p, c, { delay: j * hop, dur: hop, lift: 0.3, wobble, trail: 22, onArrive: () => { heat(i, 1.5); ring(p, c, 900, 6, 70); } });
      prev = p;
    });
    const what = { reve: 'Un rêve', recit: 'Son récit', journal: 'Son journal' }[ev.agent] || agent.label;
    caption(agent, what, `traverse ${plural(nodes.length, 'souvenir', 'souvenirs')}`);
    log(ev, agent, `${what.toLowerCase()} traverse ${plural(nodes.length, 'élément', 'éléments')}`, ev.seq ? { href: `${CONSOLE}/evenement/${ev.seq}`, label: 'voir ↗' } : null);
  }

  // la file : des événements arrivés ensemble se jouent l'un après l'autre
  const queue = [];
  let pumping = false;
  function enqueue(ev) { queue.push(ev); if (!pumping) pump(); }
  function pump() {
    const ev = queue.shift();
    if (!ev) { pumping = false; replayDone(); return; }
    pumping = true;
    if (S.ready) play(ev);
    const gap = ev.replay ? 2600 : queue.length > 20 ? 220 : ev.type === 'rappel' ? 1500 : 650;
    setTimeout(pump, gap);
  }

  // ───────────────────────── l'affichage tête haute ─────────────────────────
  function renderNote() {
    const note = $('cst-note');
    if (!S.n) { note.textContent = "Sa mémoire est encore vide : rien n'est indexé. Ce qui naîtra apparaîtra ici, en direct."; return; }
    note.textContent = `${plural(S.n, 'point', 'points')}${S.total > S.n ? ` · les plus récents des ${nf.format(S.total)} de l'index` : ''}`;
  }
  function legendItems() {
    const m = S.m, n = S.n;
    const count = (fn) => { const c = new Map(); for (let i = 0; i < n; i++) { if (S.alpha[i] === 0 && !S.focus) continue; const k = fn(i); c.set(k, (c.get(k) || 0) + 1); } return c; };
    switch (S.colorMode) {
      case 'person': {
        const c = count((i) => m.person[i]);
        return [...c.entries()].sort((a, b) => b[1] - a[1]).slice(0, 9).map(([k, v]) => ({
          value: k, label: k < 0 ? 'personne' : (S.persons[k] || {}).name || '?', count: v, color: toHex(personColor(k)) }));
      }
      case 'emotion': {
        const c = count((i) => m.emotion[i]);
        return [...c.entries()].sort((a, b) => b[1] - a[1]).slice(0, 9).map(([k, v]) => ({
          value: k, label: k < 0 ? 'sans émotion' : S.emotions[k], count: v, color: toHex(emotionColor(k < 0 ? '' : S.emotions[k])) }));
      }
      case 'sensitivity': {
        const c = count(sensitivityKey);
        return SENSITIVITY.filter((s) => c.get(s.key)).map((s) => ({ value: s.key, label: s.label, count: c.get(s.key), color: s.color }));
      }
      case 'age': return [{ value: null, label: 'ancien', count: null, color: '#3b2a9f' }, { value: null, label: 'récent', count: null, color: '#eafcff' }];
      default: {
        const c = count((i) => m.kind[i]);
        return [...c.entries()].sort((a, b) => b[1] - a[1]).map(([k, v]) => {
          const kd = KINDS[S.kindNames[k]] || { plural: S.kindNames[k], color: '#cfd8e3' };
          return { value: k, label: kd.plural, count: v, color: kd.color };
        });
      }
    }
  }
  function renderLegend() {
    const ul = $('cst-counts');
    ul.replaceChildren();
    for (const it of legendItems()) {
      const li = el('li');
      const sw = el('span', 'cst-swatch');
      sw.style.setProperty('--sw', it.color);
      li.append(sw);
      if (it.count != null) li.append(el('b', null, nf.format(it.count)));
      const label = el('span', 'cst-legend-label', it.label);
      if (it.value !== null && S.colorMode !== 'age') {
        const active = S.focus && S.focus.mode === S.colorMode && S.focus.value === it.value;
        label.classList.add('cst-filter');
        label.tabIndex = 0;
        label.setAttribute('role', 'button');
        label.setAttribute('aria-pressed', active ? 'true' : 'false');
        label.title = active ? 'tout montrer' : 'ne montrer que ceux-là';
        const toggle = () => { S.focus = active ? null : { mode: S.colorMode, value: it.value }; restyle(); };
        label.addEventListener('click', toggle);
        label.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); } });
      }
      li.append(label);
      ul.append(li);
    }
  }
  function renderAgents() {
    const ul = $('cst-agents');
    if (!ul.children.length) {
      for (const a of AGENTS) {
        const li = el('li', 'cst-agent');
        li.dataset.agent = a.key;
        li.title = a.hint;
        const sw = el('span', 'cst-swatch');
        sw.style.setProperty('--sw', a.color);
        li.append(sw, el('span', null, a.label), el('b', null, '0'));
        ul.append(li);
      }
    }
    const now = performance.now();
    for (const li of ul.children) {
      const k = li.dataset.agent;
      li.lastChild.textContent = nf.format(counters[k] || 0);
      li.classList.toggle('is-active', now - (lastActive[k] || -1e9) < 2600);
      li.hidden = k === 'autre' && !counters.autre;
    }
  }
  function log(ev, agent, text, link = null) {
    const ol = $('cst-log');
    ol.querySelector('.cst-log-empty')?.remove();
    const li = el('li', ev.replay ? 'is-replay' : null);
    li.append(el('time', null, clock(ev.at)));
    const tag = el('span', 'cst-tag', ev.replay ? `${agent.label} · rejeu` : agent.label);
    tag.style.setProperty('--tag', agent.color);
    const body = el('span', null, text);
    if (link) { const a = el('a', null, link.label); a.href = link.href; a.target = '_blank'; a.rel = 'noopener'; body.append(a); }
    li.append(tag, body);
    ol.prepend(li);
    while (ol.children.length > 9) ol.lastChild.remove();
  }
  let captionTimer = 0;
  function caption(agent, title, sub) {
    const c = $('cst-caption');
    c.replaceChildren(document.createTextNode(title), el('small', null, sub || ''));
    c.style.setProperty('--tag', agent.color);
    c.classList.add('is-on');
    clearTimeout(captionTimer);
    captionTimer = setTimeout(() => c.classList.remove('is-on'), 3400);
  }
  let liveTimer = 0;
  function setLive(state) {
    const live = $('cst-live');
    live.classList.toggle('is-live', state === 'live');
    live.classList.toggle('is-lost', state === 'lost');
    $('cst-live-text').textContent = state === 'live' ? 'en direct' : state === 'lost' ? 'hors ligne' : state === 'paused' ? 'en pause' : 'connexion…';
  }
  function flashLive() {
    const live = $('cst-live');
    live.classList.add('is-flash');
    clearTimeout(liveTimer);
    liveTimer = setTimeout(() => live.classList.remove('is-flash'), 500);
  }
  function fail(text, withLogin = false) {
    const box = $('cst-loading');
    box.classList.remove('is-done');
    box.classList.add('is-error');
    const p = $('cst-loading-text');
    p.replaceChildren(document.createTextNode(text));
    if (withLogin) { const a = el('a', null, ' se reconnecter'); a.href = `${CONSOLE}/connexion`; p.append(a); }
  }

  // ───────────────────────── survol, sélection, fiche ─────────────────────────
  const details = new Map();
  function fetchPoint(key) {
    if (!details.has(key)) {
      details.set(key, fetch(`${BASE}/point/${key}`, { credentials: 'same-origin', cache: 'no-store' })
        .then((r) => (r.ok ? r.json() : null)).catch(() => null));
    }
    return details.get(key);
  }
  function pick(mx, my) {
    if (!S.ready || morphMix() < 1) return -1;
    const w = canvas.clientWidth, h = canvas.clientHeight;
    let best = -1, bestW = Infinity;
    const lim2 = 14 * 14;
    for (let i = 0; i < S.n; i++) {
      if (S.alpha[i] < 0.05) continue;
      const x = S.to[i * 3], y = S.to[i * 3 + 1], z = S.to[i * 3 + 2];
      const cw = pv[3] * x + pv[7] * y + pv[11] * z + pv[15];
      if (cw <= 0.05) continue;
      const sx = ((pv[0] * x + pv[4] * y + pv[8] * z + pv[12]) / cw * 0.5 + 0.5) * w;
      const sy = (1 - ((pv[1] * x + pv[5] * y + pv[9] * z + pv[13]) / cw * 0.5 + 0.5)) * h;
      const d2 = (sx - mx) ** 2 + (sy - my) ** 2;
      if (d2 < lim2 && cw - d2 * 0.002 < bestW) { bestW = cw - d2 * 0.002; best = i; }
    }
    return best;
  }
  function describe(i) {
    const m = S.m, parts = [];
    if (m.importance[i] >= 0) parts.push(`importance ${f2.format(m.importance[i])}`);
    if (m.confidence[i] >= 0 && S.kindNames[m.kind[i]] === 'belief') parts.push(`confiance ${f2.format(m.confidence[i])}`);
    parts.push(ago(m.born[i]));
    if (m.recalls[i]) parts.push(`${plural(m.recalls[i], 'rappel', 'rappels')}`);
    return parts.join(' · ');
  }
  let hoverToken = 0;
  function showHover(i, mx, my) {
    const box = $('cst-hover');
    if (i < 0) { box.hidden = true; canvas.classList.remove('is-pointing'); return; }
    canvas.classList.add('is-pointing');
    const kind = KINDS[S.kindNames[S.m.kind[i]]] || { label: S.kindNames[S.m.kind[i]], color: '#cfd8e3' };
    box.style.setProperty('--chip', kind.color);
    box.style.left = `${mx}px`; box.style.top = `${my}px`;
    if (S.hover !== i) {
      box.replaceChildren(el('b', null, kind.label), el('span', null, describe(i)));
      const token = ++hoverToken;
      const key = S.keys[i];
      setTimeout(() => {
        if (token !== hoverToken) return;
        fetchPoint(key).then((d) => {
          if (!d || token !== hoverToken) return;
          const text = d.text || d.said || '';
          if (text) box.append(el('span', null, `« ${text.length > 140 ? text.slice(0, 139) + '…' : text} »`));
        });
      }, 160);
    }
    box.hidden = false;
  }
  function openDetail(i) {
    S.selected = i;
    const panel = $('cst-detail'), body = $('cst-detail-body'), title = $('cst-detail-title');
    const kindName = S.kindNames[S.m.kind[i]];
    const kind = KINDS[kindName] || { label: kindName, color: '#cfd8e3' };
    panel.style.setProperty('--chip', kind.color);
    title.textContent = `${kind.label} · n° ${S.keys[i]}`;
    body.replaceChildren(el('p', 'cst-detail-loading', 'lecture…'));
    panel.hidden = false;
    fetchPoint(S.keys[i]).then((d) => {
      if (S.selected !== i) return;
      body.replaceChildren();
      if (!d) { body.append(el('p', 'cst-detail-loading', "Ce point n'existe plus (oublié ou effacé depuis).")); return; }
      if (d.said != null) {
        const said = el('p', 'cst-text'); said.append(el('small', null, 'on lui a dit'), document.createTextNode(d.said || '—'));
        const reply = el('p', 'cst-text'); reply.append(el('small', null, 'elle a répondu'), document.createTextNode(d.reply || '—'));
        body.append(said, reply);
      } else body.append(el('p', 'cst-text', d.text || '(sans texte)'));
      const dl = el('dl', 'cst-meta');
      const row = (k, v) => { if (v == null || v === '' || (Array.isArray(v) && !v.length)) return; dl.append(el('dt', null, k)); const dd = el('dd'); if (v instanceof Node) dd.append(v); else dd.textContent = Array.isArray(v) ? v.join(', ') : v; dl.append(dd); };
      const bar = (v) => { const wrap = el('span'); const b = el('span', 'cst-bar'); const fill = el('i'); fill.style.setProperty('--v', `${Math.round(clamp(v, 0, 1) * 100)}%`); b.append(fill); wrap.append(b, document.createTextNode(f2.format(v))); return wrap; };
      row('né', d.born ? `${new Date(d.born * 1000).toLocaleString('fr-FR', { dateStyle: 'medium', timeStyle: 'short' })} (${ago(d.born)})` : null);
      if (d.importance != null) row('importance', bar(d.importance));
      if (d.confidence != null && kindName === 'belief') row('confiance', bar(d.confidence));
      row('rappels', d.recalls != null ? `${nf.format(d.recalls)}${d.recalled ? ' · dernier ' + ago(d.recalled) : ''}` : null);
      row('émotion', d.emotion);
      row('concerne', d.about);
      row('confié par', d.told_by);
      const sens = d.secret ? 'secret' : (SENSITIVITY.find((s) => s.key === d.sensitivity) || {}).label;
      row('sensibilité', sens);
      row('statut', d.status ? STATUS[d.status] || d.status : null);
      row('nature', d.knowledge_kind && kindName === 'belief' ? NATURE[d.knowledge_kind] || d.knowledge_kind : null);
      body.append(dl);
      const actions = el('div', 'cst-actions');
      const open = el('a', null, 'ouvrir dans la console ↗'); open.href = d.href; open.target = '_blank'; open.rel = 'noopener';
      const center = el('button', null, 'centrer'); center.type = 'button'; center.addEventListener('click', () => focusOn(i));
      actions.append(open, center);
      body.append(actions);
    });
  }
  function closeDetail() { S.selected = -1; $('cst-detail').hidden = true; }

  // ───────────────────────── la recherche ─────────────────────────
  const fold = (t) => t.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  const searchBox = $('cst-search'), searchInput = $('cst-q');
  let searchToken = 0, searchTimer = 0;
  function resolveSearch() {
    if (!S.search) return;
    S.search.idx = S.search.hits.map((h) => idx(h.key));
    S.search.set = new Set(S.search.idx.filter((i) => i >= 0));
  }
  function clearSearch(keepText = false) {
    searchToken += 1;
    clearTimeout(searchTimer);
    searchBox.classList.remove('is-busy');
    if (!keepText) searchInput.value = '';
    $('cst-q-clear').hidden = !searchInput.value;
    $('cst-results').hidden = true;
    S.preview = -1;
    if (S.search) { S.search = null; restyle(); }
  }
  async function runSearch(q) {
    q = q.trim();
    if (q.length < 2) { if (!q) clearSearch(); return; }
    const token = ++searchToken;
    searchBox.classList.add('is-busy');
    try {
      if (pendingCount > 0) await loadMap(); // ce que l'index a gagné entre sur la carte avant qu'on y cherche
      if (token !== searchToken) return;
      const r = await fetch(`${BASE}/cherche?q=${encodeURIComponent(q)}`, { credentials: 'same-origin', cache: 'no-store' });
      if (r.status === 401) { fail('Ta session a expiré :', true); return; }
      const j = await r.json();
      if (token !== searchToken) return;
      S.search = { q: j.q, hits: j.hits, query: j.query, idx: [], set: new Set() };
      resolveSearch();
      restyle();
      const people = S.persons.map((p, k) => ({ ...p, k })).filter((p) => fold(p.name || '').includes(fold(q))).slice(0, 3);
      renderResults(people);
      frameOn(S.search.idx.filter((i) => i >= 0).slice(0, 24), S.search.query);
    } catch {
      // rien : la recherche suivante réessaiera
    } finally {
      if (token === searchToken) searchBox.classList.remove('is-busy');
    }
  }
  function resultButton(color, title, sub, how, howClass) {
    const b = el('button', 'cst-result');
    b.type = 'button';
    const sw = el('span', 'cst-swatch');
    sw.style.setProperty('--sw', color);
    const text = el('span', 'cst-result-text');
    text.append(el('small', null, sub), document.createTextNode(title));
    const tag = el('span', `cst-result-how${howClass ? ' ' + howClass : ''}`, how);
    b.append(sw, text, tag);
    return b;
  }
  function renderResults(people) {
    const box = $('cst-results'), list = $('cst-results-list');
    list.replaceChildren();
    const hits = S.search.hits.map((h, r) => ({ ...h, i: S.search.idx[r] })).filter((h) => h.i >= 0);
    const words = hits.filter((h) => h.how === 'mot').length;
    $('cst-results-head').title = "Par les mots : le texte les contient (casse et accents ignorés). Par le sens : tout ce "
      + "dont la pertinence dépasse 0,4 (la similarité, plus un bonus pour les mots du sujet).";
    $('cst-results-head').textContent = hits.length
      ? `${plural(hits.length, 'point', 'points')} · ${nf.format(words)} par les mots · ${nf.format(hits.length - words)} par le sens`
      : 'rien sur la carte ne contient ni ne ressemble à ça';
    for (const p of people) {
      const count = S.m.person.filter((x) => x === p.k).length;
      const b = resultButton(toHex(personColor(p.k)), p.name, 'personne', plural(count, 'point', 'points'), 'is-word');
      b.addEventListener('click', () => showPerson(p.k));
      const li = el('li'); li.append(b); list.append(li);
    }
    for (const h of hits.slice(0, 40)) {
      const kindName = S.kindNames[S.m.kind[h.i]];
      const kind = KINDS[kindName] || { label: kindName, color: '#cfd8e3' };
      const b = resultButton(kind.color, h.text || describe(h.i), `${kind.label} · ${ago(S.m.born[h.i])}`,
        h.how === 'mot' ? 'mot' : `sens ${f2.format(h.score)}`, h.how === 'mot' ? 'is-word' : '');
      b.addEventListener('click', () => {
        for (const x of list.querySelectorAll('.is-current')) x.classList.remove('is-current');
        b.classList.add('is-current');
        focusOn(h.i); openDetail(h.i);
      });
      b.addEventListener('mouseenter', () => { S.preview = h.i; });
      b.addEventListener('mouseleave', () => { if (S.preview === h.i) S.preview = -1; });
      const li = el('li'); li.append(b); list.append(li);
    }
    if (!hits.length && !people.length) list.append(el('li', 'cst-results-empty', 'essaie un autre mot, ou une idée plutôt qu’un mot exact'));
    box.hidden = false;
  }
  /** Ne montrer que ce qui concerne cette personne, en couleur par personne, et y voler. */
  function showPerson(k) {
    clearSearch();
    S.colorMode = 'person';
    const group = document.querySelector('[data-color]').closest('.cst-group');
    press(group, 'color', 'person');
    S.focus = { mode: 'person', value: k };
    restyle();
    const mine = [];
    for (let i = 0; i < S.n; i++) if (S.m.person[i] === k) mine.push(i);
    frameOn(mine.slice(0, 200));
  }
  searchBox.addEventListener('submit', (e) => { e.preventDefault(); clearTimeout(searchTimer); runSearch(searchInput.value); });
  searchInput.addEventListener('input', () => {
    $('cst-q-clear').hidden = !searchInput.value;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => runSearch(searchInput.value), 320);
  });
  searchInput.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); clearSearch(); searchInput.blur(); }
    else if (e.key === 'ArrowDown') { const first = $('cst-results-list').querySelector('button'); if (first) { e.preventDefault(); first.focus(); } }
  });
  $('cst-results-list').addEventListener('keydown', (e) => {
    const buttons = [...$('cst-results-list').querySelectorAll('button')], at = buttons.indexOf(document.activeElement);
    if (e.key === 'ArrowDown' && at >= 0) { e.preventDefault(); (buttons[at + 1] || buttons[at]).focus(); }
    else if (e.key === 'ArrowUp' && at >= 0) { e.preventDefault(); (at ? buttons[at - 1] : searchInput).focus(); }
    else if (e.key === 'Escape') { e.preventDefault(); clearSearch(); searchInput.blur(); }
  });
  $('cst-q-clear').addEventListener('click', () => { clearSearch(); searchInput.focus(); });
  searchInput.addEventListener('focus', () => { if (S.search) $('cst-results').hidden = false; });

  // ───────────────────────── entrées ─────────────────────────
  const drag = { active: false, id: null, x: 0, y: 0, moved: 0, pointers: new Map(), pinch: 0 };
  canvas.addEventListener('pointerdown', (e) => {
    canvas.setPointerCapture(e.pointerId);
    $('cst-results').hidden = true; // la recherche reste allumée ; sa liste revient quand on rouvre la barre
    drag.pointers.set(e.pointerId, [e.clientX, e.clientY]);
    if (drag.pointers.size === 2) { const [a, b] = [...drag.pointers.values()]; drag.pinch = Math.hypot(a[0] - b[0], a[1] - b[1]); }
    drag.active = true; drag.x = e.clientX; drag.y = e.clientY; drag.moved = 0;
    cam.vYaw = cam.vPitch = 0; cam.lastInput = performance.now();
    canvas.classList.add('is-dragging');
  });
  canvas.addEventListener('pointermove', (e) => {
    const rect = canvas.getBoundingClientRect();
    if (drag.active && drag.pointers.has(e.pointerId)) {
      drag.pointers.set(e.pointerId, [e.clientX, e.clientY]);
      if (drag.pointers.size === 2) {
        const [a, b] = [...drag.pointers.values()], d = Math.hypot(a[0] - b[0], a[1] - b[1]);
        if (drag.pinch) cam.tDist = clamp(cam.tDist * drag.pinch / d, 1.25, 9);
        drag.pinch = d; drag.moved += 10;
        return;
      }
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      drag.x = e.clientX; drag.y = e.clientY; drag.moved += Math.abs(dx) + Math.abs(dy);
      cam.tYaw -= dx * 0.0055; cam.tPitch = clamp(cam.tPitch + dy * 0.0055, -1.35, 1.35);
      cam.vYaw = -dx * 0.33; cam.vPitch = dy * 0.33;
      cam.lastInput = performance.now();
      showHover(-1);
      return;
    }
    pendingHover = [e.clientX - rect.left, e.clientY - rect.top];
  });
  let pendingHover = null;
  const release = (e) => {
    drag.pointers.delete(e.pointerId);
    if (drag.pointers.size) return;
    canvas.classList.remove('is-dragging');
    const click = drag.active && drag.moved < 5;
    drag.active = false; drag.pinch = 0;
    if (click) {
      const rect = canvas.getBoundingClientRect();
      const i = pick(e.clientX - rect.left, e.clientY - rect.top);
      if (i >= 0) openDetail(i); else closeDetail();
    }
  };
  canvas.addEventListener('pointerup', release);
  canvas.addEventListener('pointercancel', release);
  canvas.addEventListener('pointerleave', () => { pendingHover = null; showHover(-1); S.hover = -1; });
  canvas.addEventListener('dblclick', (e) => {
    const rect = canvas.getBoundingClientRect();
    const i = pick(e.clientX - rect.left, e.clientY - rect.top);
    if (i >= 0) focusOn(i); else home();
  });
  canvas.addEventListener('wheel', (e) => {
    e.preventDefault();
    cam.tDist = clamp(cam.tDist * Math.exp(e.deltaY * 0.0012), 1.25, 9);
    cam.lastInput = performance.now();
  }, { passive: false });
  $('cst-detail-close').addEventListener('click', closeDetail);
  document.addEventListener('keydown', (e) => {
    if (e.target instanceof HTMLInputElement || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === '/') { e.preventDefault(); searchInput.focus(); searchInput.select(); }
    else if (e.key === 'Escape') { if (S.selected >= 0) closeDetail(); else if (S.search) clearSearch(); }
    else if (e.key === ' ' && e.target === document.body) { e.preventDefault(); toggleRotate(); }
    else if (e.key === 'r' || e.key === 'R') home();
  });

  function press(group, attr, value) {
    for (const b of document.querySelectorAll(`[data-${attr}]`)) if (b.closest('.cst-group') === group) b.setAttribute('aria-pressed', b.dataset[attr] === value ? 'true' : 'false');
  }
  for (const b of document.querySelectorAll('[data-color]')) b.addEventListener('click', () => {
    S.colorMode = b.dataset.color; S.focus = null; press(b.closest('.cst-group'), 'color', S.colorMode); restyle();
  });
  for (const b of document.querySelectorAll('[data-depth]')) b.addEventListener('click', () => {
    S.depthMode = b.dataset.depth; press(b.closest('.cst-group'), 'depth', S.depthMode); morphTo(1700);
  });
  for (const b of document.querySelectorAll('[data-toggle]')) b.addEventListener('click', () => {
    const k = { edges: 'showEdges', chunks: 'showChunks', former: 'showFormer' }[b.dataset.toggle];
    S[k] = !S[k]; b.setAttribute('aria-pressed', S[k] ? 'true' : 'false'); restyle();
  });
  function toggleRotate() { cam.auto = !cam.auto; $('cst-rotate').setAttribute('aria-pressed', cam.auto ? 'true' : 'false'); }
  $('cst-rotate').addEventListener('click', toggleRotate);
  $('cst-home').addEventListener('click', home);
  $('cst-pending').addEventListener('click', () => loadMap());

  let replaying = false;
  function replayDone() { if (replaying) { replaying = false; $('cst-replay').classList.remove('is-playing'); $('cst-replay').textContent = '▶ rejouer'; } }
  $('cst-replay').addEventListener('click', async () => {
    if (replaying) { queue.length = 0; replayDone(); return; }
    const btn = $('cst-replay');
    btn.textContent = '…';
    try {
      const r = await fetch(`${BASE}/rejeu?n=12`, { credentials: 'same-origin', cache: 'no-store' });
      if (r.status === 401) { fail('Ta session a expiré :', true); return; }
      const j = await r.json();
      if (!j.events.length) {
        btn.textContent = '▶ rejouer';
        log({ at: nowS(), replay: true }, AGENT.autre, "rien à rejouer : aucune parole ne s'est encore souvenue de quoi que ce soit");
        return;
      }
      replaying = true;
      btn.classList.add('is-playing');
      btn.textContent = '■ arrêter';
      j.events.forEach(enqueue);
    } catch {
      btn.textContent = '▶ rejouer';
    }
  });

  // ───────────────────────── le serveur ─────────────────────────
  let cursor = 0;
  let loading = null;
  let pendingCount = 0;
  async function loadMap() {
    if (loading) return loading;
    loading = (async () => {
      try {
        const r = await fetch(`${BASE}/carte`, { credentials: 'same-origin', cache: 'no-store' });
        if (r.status === 401) { fail('Ta session a expiré :', true); return; }
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = await r.json();
        skew = d.now - Date.now() / 1000;
        if (!S.ready) cursor = d.head;
        installMap(d);
        $('cst-loading').classList.add('is-done');
        $('cst-pending').hidden = true;
        pendingCount = 0;
      } catch (err) {
        if (!S.ready) fail(`La carte n'a pas pu se calculer (${err.message}). Réessaie dans un instant.`);
      } finally {
        loading = null;
      }
    })();
    return loading;
  }
  async function poll() {
    if (document.hidden) { setLive('paused'); return; }
    try {
      const r = await fetch(`${BASE}/flux?apres=${cursor}`, { credentials: 'same-origin', cache: 'no-store' });
      if (r.status === 401) { setLive('lost'); fail('Ta session a expiré :', true); return; }
      if (!r.ok) throw new Error(String(r.status));
      const j = await r.json();
      setLive('live');
      if (j.head < cursor) cursor = j.head; // le serveur a redémarré : son flux repart de zéro
      for (const ev of j.events) enqueue(ev);
      if (j.events.length) cursor = j.events[j.events.length - 1].id;
      const pending = $('cst-pending');
      pendingCount = j.pending || 0;
      pending.hidden = !(j.pending > 0);
      if (j.pending > 0) pending.textContent = `${plural(j.pending, 'élément nouveau', 'éléments nouveaux')} dans l'index — recalculer la carte`;
    } catch {
      setLive('lost');
    }
  }
  setInterval(poll, 1000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });
  setInterval(() => { $('cst-clock').textContent = clock(); renderAgents(); }, 1000);

  // ───────────────────────── l'image ─────────────────────────
  function drawLines(target, model, mix, fade) {
    if (!target.count) return;
    gl.useProgram(PROG.line.p);
    const u = PROG.line.u;
    gl.uniformMatrix4fv(u.u_proj, false, proj); gl.uniformMatrix4fv(u.u_view, false, view); gl.uniformMatrix4fv(u.u_model, false, model);
    gl.uniform1f(u.u_mix, mix); gl.uniform1f(u.u_dist, cam.dist); gl.uniform1f(u.u_fade, fade);
    gl.bindVertexArray(target.vao);
    gl.drawArrays(gl.LINES, 0, target.count);
  }
  function drawFxPoints(target, scale) {
    if (!target.count) return;
    gl.useProgram(PROG.fx.p);
    const u = PROG.fx.u;
    gl.uniformMatrix4fv(u.u_proj, false, proj); gl.uniformMatrix4fv(u.u_view, false, view); gl.uniform1f(u.u_scale, scale);
    gl.bindVertexArray(target.vao);
    gl.drawArrays(gl.POINTS, 0, target.count);
  }
  function quad(prog, out, uniforms) {
    gl.bindFramebuffer(gl.FRAMEBUFFER, out ? out.fb : null);
    gl.viewport(0, 0, out ? out.w : canvas.width, out ? out.h : canvas.height);
    gl.useProgram(prog.p);
    uniforms(prog.u);
    gl.bindVertexArray(G.quad);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }
  function bindTex(unit, tex, loc) { gl.activeTexture(gl.TEXTURE0 + unit); gl.bindTexture(gl.TEXTURE_2D, tex); gl.uniform1i(loc, unit); }

  let last = performance.now();
  let hoverClock = 0;
  function frame(now) {
    requestAnimationFrame(frame);
    resize();
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    updateCamera(dt);
    const time = now / 1000;

    if (pendingHover && now - hoverClock > 40 && !drag.active) {
      hoverClock = now;
      const [mx, my] = pendingHover;
      const i = pick(mx, my);
      showHover(i, mx, my);
      S.hover = i;
      pendingHover = null;
    }

    // la chaleur retombe
    if (S.hotSet.size) {
      const k = Math.exp(-dt * 1.4);
      for (const i of S.hotSet) { S.boost[i] *= k; if (S.boost[i] < 0.01) { S.boost[i] = 0; S.hotSet.delete(i); } }
      gl.bindBuffer(gl.ARRAY_BUFFER, G.boost);
      gl.bufferSubData(gl.ARRAY_BUFFER, 0, S.boost);
    }

    // les effets de l'instant
    fxP = []; fxL = [];
    for (let j = FX.length - 1; j >= 0; j--) {
      const f = FX[j], elapsed = now - f.t0;
      if (elapsed < 0) continue;
      const t = elapsed / f.dur;
      if (t >= 1) { FX.splice(j, 1); if (f.draw.length >= 3) f.draw(1, now, f.dur); continue; }
      f.draw(t, now, elapsed);
    }
    marks = [];
    if (S.search && S.search.set.size) ringsAround(S.search.idx, [1, 0.886, 0.478], 0.55 + 0.2 * Math.sin(now / 340));
    if (S.preview >= 0 && S.preview < S.n) mark(posOf(S.preview), [1, 1, 1], 30, 0.9, 1);
    if (S.selected >= 0 && S.selected < S.n) {
      const p = posOf(S.selected);
      mark(p, [0.25, 0.94, 1], 26 + 2 * Math.sin(now / 260), 0.95, 1);
    }
    upload(G.fxPoints, new Float32Array(fxP), gl.DYNAMIC_DRAW);
    upload(G.marks, new Float32Array(marks), gl.DYNAMIC_DRAW);
    upload(G.fxLines, new Float32Array(fxL), gl.DYNAMIC_DRAW);

    let sweepAmt = 0, sweepVec = [0, 1, 0, 0];
    if (sweep) {
      const t = (now - sweep.t0) / sweep.dur;
      if (t >= 1) sweep = null;
      else { sweepAmt = 1.4 * Math.sin(Math.PI * t); sweepVec = [...sweep.n, -1.1 + 2.2 * t]; }
    }

    // la scène, additive, dans sa texture
    const scale = canvas.height * 0.0105;
    gl.bindFramebuffer(gl.FRAMEBUFFER, T.scene.fb);
    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.clearColor(0, 0, 0, 1);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE);
    drawFxPoints(G.stars, scale * 2.6);
    const mix = morphMix();
    drawLines(G.grid, mul4(rotY(time * 0.018), rotX(0.32)), 1, 1);
    if (S.showEdges) drawLines(G.edges, IDENTITY, mix, S.morph.stagger ? mix * mix * mix : 1);
    if (S.n) {
      gl.useProgram(PROG.point.p);
      const u = PROG.point.u;
      gl.uniformMatrix4fv(u.u_proj, false, proj); gl.uniformMatrix4fv(u.u_view, false, view);
      gl.uniform1f(u.u_mix, mix); gl.uniform1f(u.u_stagger, S.morph.stagger); gl.uniform1f(u.u_time, time);
      gl.uniform1f(u.u_scale, scale); gl.uniform1f(u.u_dist, cam.dist);
      gl.uniform1f(u.u_sweepAmt, sweepAmt); gl.uniform4fv(u.u_sweep, sweepVec);
      gl.bindVertexArray(G.points.vao);
      gl.drawArrays(gl.POINTS, 0, S.n);
    }
    drawLines(G.fxLines, IDENTITY, 1, 1);
    drawFxPoints(G.fxPoints, scale);
    gl.disable(gl.BLEND);

    // le halo : ce qui brille, flouté à deux échelles
    quad(PROG.bright, T.a, (u) => bindTex(0, T.scene.tex, u.u_tex));
    quad(PROG.blur, T.b, (u) => { bindTex(0, T.a.tex, u.u_tex); gl.uniform2f(u.u_dir, 1 / T.a.w, 0); });
    quad(PROG.blur, T.a, (u) => { bindTex(0, T.b.tex, u.u_tex); gl.uniform2f(u.u_dir, 0, 1 / T.a.h); });
    quad(PROG.blur, T.c, (u) => { bindTex(0, T.a.tex, u.u_tex); gl.uniform2f(u.u_dir, 1.5 / T.a.w, 0); });
    quad(PROG.blur, T.d, (u) => { bindTex(0, T.c.tex, u.u_tex); gl.uniform2f(u.u_dir, 0, 1.5 / T.c.h); });
    quad(PROG.blur, T.c, (u) => { bindTex(0, T.d.tex, u.u_tex); gl.uniform2f(u.u_dir, 2.5 / T.c.w, 0); });
    quad(PROG.blur, T.d, (u) => { bindTex(0, T.c.tex, u.u_tex); gl.uniform2f(u.u_dir, 0, 2.5 / T.c.h); });
    quad(PROG.compose, null, (u) => {
      bindTex(0, T.scene.tex, u.u_scene); bindTex(1, T.a.tex, u.u_near); bindTex(2, T.d.tex, u.u_far);
      gl.uniform2f(u.u_res, canvas.width, canvas.height); gl.uniform1f(u.u_time, time);
    });

    // les marques, par-dessus : nettes, hors du halo
    if (G.marks.count) {
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
      gl.useProgram(PROG.mark.p);
      const u = PROG.mark.u;
      gl.uniformMatrix4fv(u.u_proj, false, proj); gl.uniformMatrix4fv(u.u_view, false, view);
      gl.uniform1f(u.u_px, canvas.width / Math.max(1, canvas.clientWidth));
      gl.bindVertexArray(G.marks.vao);
      gl.drawArrays(gl.POINTS, 0, G.marks.count);
      gl.disable(gl.BLEND);
    }
  }

  // le flux se pose toujours au-dessus des commandes, quelle que soit leur hauteur
  const controls = document.querySelector('.cst-controls');
  new ResizeObserver(() => root.style.setProperty('--controls-h', `${controls.offsetHeight}px`)).observe(controls);
  // et les agents, sous l'en-tête
  const head = document.querySelector('.cst-head');
  new ResizeObserver(() => root.style.setProperty('--head-h', `${head.offsetHeight}px`)).observe(head);
  renderAgents();
  $('cst-log').append(el('li', 'cst-log-empty', 'en attente : ce qui la parcourra apparaîtra ici.'));
  $('cst-clock').textContent = clock();
  resize();
  requestAnimationFrame(frame);
  loadMap().then(poll);
})();
