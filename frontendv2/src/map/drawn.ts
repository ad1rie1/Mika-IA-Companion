/**
 * Le plan dessiné d'une scène (`scene.ts`), sans tuile ni MapLibre : ce qu'une miniature montre en attendant sa carte,
 * au-delà des quatre cartes vivantes du chat, sans WebGL ou sans carte servie. Ses tracés et ses épingles, à leur
 * place (Mercator), sur un fond quadrillé — un plan, pas une carte : aucune rue n'y est inventée.
 */
import { h } from "../shell/dom";
import { cleanScene, sceneBounds, type Scene } from "./scene";

const mx = (lon: number) => (lon + 180) / 360;
const my = (lat: number) => {
  const r = (Math.max(-85, Math.min(85, lat)) * Math.PI) / 180;
  return (1 - Math.asinh(Math.tan(r)) / Math.PI) / 2;
};

export interface DrawnOptions {
  width: number;
  height: number;
  /** Ce que le plan montre, pour un lecteur d'écran. */
  title: string;
  /** Les marges, en unités du dessin. */
  pad?: number;
}

/** Le plan d'une scène, en SVG (tout texte échappé). Une scène vide : le fond seul. */
export function drawnScene(raw: Scene, opts: DrawnOptions): string {
  const scene = cleanScene(raw);
  const { width: W, height: H } = opts;
  const pad = opts.pad ?? 18;
  const b = sceneBounds(scene);
  const grid = Array.from({ length: 7 }, (_, i) => `<path class="dm-grid" d="M${((i + 1) * W) / 8} 0V${H}"/>`).join("")
    + Array.from({ length: 3 }, (_, i) => `<path class="dm-grid" d="M0 ${((i + 1) * H) / 4}H${W}"/>`).join("");
  let body = "";
  if (b) {
    const x0 = mx(b[0]);
    const x1 = mx(b[2]);
    const y0 = my(b[3]);
    const y1 = my(b[1]);
    const scale = Math.min((W - 2 * pad) / Math.max(1e-9, x1 - x0), (H - 2 * pad) / Math.max(1e-9, y1 - y0));
    const ox = (W - (x1 - x0) * scale) / 2;
    const oy = (H - (y1 - y0) * scale) / 2;
    const at = (lat: number, lon: number): [number, number] => [ox + (mx(lon) - x0) * scale, oy + (my(lat) - y0) * scale];
    const lines = scene.lines
      .map((l) => {
        const d = l.points.map(([la, lo], i) => {
          const [x, y] = at(la, lo);
          return `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`;
        }).join("");
        return `<path class="dm-line${l.mika ? " mika" : ""}${l.straight ? " straight" : ""}" d="${d}"/>`;
      })
      .join("");
    const pins = [...scene.pins]
      .sort((p, q) => Number(!!p.selected) - Number(!!q.selected))
      .map((p) => {
        const [x, y] = at(p.lat, p.lon);
        const r = p.label ? 7.5 : 5;
        return `<g class="dm-pin${p.mika ? " mika" : ""}${p.selected ? " sel" : ""}"><circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${r}"/>${
          p.label ? `<text x="${x.toFixed(1)}" y="${(y + 3.3).toFixed(1)}">${h(p.label.slice(0, 3))}</text>` : ""}</g>`;
      })
      .join("");
    const here = scene.here
      ? (() => {
          const [x, y] = at(scene.here.lat, scene.here.lon);
          return `<circle class="dm-here-halo" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="10"/><circle class="dm-here" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="4.5"/>`;
        })()
      : "";
    body = lines + here + pins;
  }
  return `<svg class="drawn-map" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="${h(opts.title)}">
    <rect class="dm-bg" width="${W}" height="${H}"/>${grid}${body}</svg>`;
}
