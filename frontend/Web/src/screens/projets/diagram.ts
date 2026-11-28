/**
 * Projets, les calculs du diagramme des objectifs (pur, sans DOM) : ses lignes (un objectif, puis ses jalons en
 * retrait, puis les missions), la part faite de chacun (« Avancement »), et sa place dans le temps (« Dans le
 * temps » : un axe en jours, une barre de quand elle s'y est mise à quand c'est atteint, les fantômes de ce qui n'a
 * pas commencé). De vraies dates seulement, celles de `GET …/diagramme` : 0 veut dire « pas encore arrivé », et ce
 * qui n'a pas commencé n'a pas de date — il se range après aujourd'hui, dans l'ordre du plan.
 *
 * Deux défauts de la maquette n'y sont plus : l'axe se resserre pour que la première date tienne à l'écran avec
 * aujourd'hui (sinon il s'ouvre sur la première date), et le mot d'une barre garde sa place en long (l'écran le
 * retient au bord quand sa barre a défilé).
 */
import type { Diagram, DiagramMilestone, DiagramObjective } from "../../api/projects";
import { DAY_MS, dayStart } from "./time";
import type { Tone } from "./tones";

export const ROW_GOAL = 46;
export const ROW_MILESTONE = 36;

export type Row =
  | { sort: "goal"; o: DiagramObjective; folded: boolean; y: number; height: number }
  | { sort: "milestone"; o: DiagramObjective; m: DiagramMilestone; y: number; height: number }
  | { sort: "mission"; o: DiagramObjective; y: number; height: number };

/** Les lignes : les objectifs dans l'ordre servi (celui du plan), chacun suivi de ses jalons sauf replié, puis les missions. */
export function rows(d: Pick<Diagram, "objectives">, folded: ReadonlySet<number> = new Set()): { rows: Row[]; height: number } {
  const out: Row[] = [];
  let y = 0;
  const put = (r: Row): void => {
    out.push(r);
    y += r.height;
  };
  for (const o of d.objectives.filter((x) => x.kind !== "constant")) {
    const closed = folded.has(o.id);
    put({ sort: "goal", o, folded: closed, y, height: ROW_GOAL });
    if (!closed) for (const m of o.milestones) put({ sort: "milestone", o, m, y, height: ROW_MILESTONE });
  }
  for (const o of d.objectives.filter((x) => x.kind === "constant")) put({ sort: "mission", o, y, height: ROW_GOAL });
  return { rows: out, height: y };
}

/** La couleur d'un jalon du diagramme : atteint, prêt (à toi), commencé, à venir. */
export function milestoneTone(m: Pick<DiagramMilestone, "status" | "ready" | "started_at">): Tone {
  if (m.status === "reached") return "done";
  if (m.ready) return "you";
  return m.started_at ? "work" : "wait";
}

/** La part faite d'un jalon : atteint ou prêt, entière ; commencé, selon ses exécutions (jamais entière) ; sinon rien. */
export function milestonePart(m: Pick<DiagramMilestone, "status" | "ready" | "started_at" | "runs">): number {
  if (m.status === "reached" || m.ready) return 1;
  if (!m.started_at) return 0;
  return Math.min(0.9, 0.15 + 0.25 * Math.max(1, m.runs));
}

export interface Segment {
  tone: Tone;
  /** De 0 à 1. */
  part: number;
}

const ORDER: Tone[] = ["done", "you", "work", "fail"];

/** La barre d'un objectif : la somme de ses jalons, couleur par couleur ; sans jalon, son état seul. */
export function goalSegments(o: Pick<DiagramObjective, "status" | "runs" | "milestones">): Segment[] {
  const n = o.milestones.length;
  if (!n) {
    if (o.status === "done") return [{ tone: "done", part: 1 }];
    if (o.status === "blocked") return [{ tone: "fail", part: o.runs ? 0.5 : 0.15 }];
    return o.runs ? [{ tone: "work", part: 0.5 }] : [];
  }
  const sums = new Map<Tone, number>();
  for (const m of o.milestones) {
    const tone = milestoneTone(m);
    sums.set(tone, (sums.get(tone) ?? 0) + milestonePart(m) / n);
  }
  return ORDER.filter((t) => (sums.get(t) ?? 0) > 0).map((t) => ({ tone: t, part: sums.get(t) ?? 0 }));
}

// ── Dans le temps ────────────────────────────────────────────────────

export interface TimeOptions {
  zoom: "days" | "weeks";
  /** La largeur visible de la piste, en pixels (0 : inconnue). */
  width: number;
}

export interface Bar {
  cls: string;
  left: number;
  width: number;
}

export interface Track {
  bars: Bar[];
  /** Où se pose le mot de la ligne (son bord gauche), ou -1 : pas de mot. */
  label: number;
  /** Une mission : son fil (de 0 à aujourd'hui) et ses passages. */
  line?: number;
  passes?: { x: number; at: number }[];
}

export interface AxisDay {
  x: number;
  at: number;
  today: boolean;
}

export interface Arrow {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export interface TimeLayout {
  /** La largeur d'un jour, en pixels. */
  day: number;
  /** La largeur de tout le diagramme. */
  width: number;
  /** Le premier minuit de l'axe, et où tombe maintenant. */
  origin: number;
  today: number;
  days: AxisDay[];
  tracks: Track[];
  arrows: Arrow[];
  /** Tout tient dans la piste : rien à faire défiler. */
  fits: boolean;
}

/** Ce qu'un jour mesure quand rien ne presse, et jusqu'où il se resserre pour que la première date tienne à l'écran. */
export const DAY_WIDTH = { days: { natural: 124, min: 56 }, weeks: { natural: 46, min: 14 } } as const;
const TAIL = 150;

/** Combien de jours l'axe compte avant aujourd'hui : de la première date servie à ce matin. */
export function daysBack(d: Pick<Diagram, "now" | "from" | "objectives">, zoom: "days" | "weeks"): number {
  const dated = [d.from, ...d.objectives.flatMap((o) => [o.started_at, ...o.passes])].filter((x) => x > 0);
  const first = dated.length ? Math.min(...dated) : d.now;
  const span = Math.max(0, Math.ceil((dayStart(d.now) - dayStart(first)) / DAY_MS));
  return Math.max(zoom === "weeks" ? 13 : 2, span + (zoom === "weeks" ? 1 : 0));
}

/** Les fantômes d'une largeur de jour : où chacun se pose après aujourd'hui, et jusqu'où va le diagramme. */
interface Ghosts {
  today: number;
  end: number;
  width: number;
  goal: Map<number, { x0: number; x1: number }>;
  milestone: Map<string, number>;
}

export function timeLayout(d: Diagram, list: readonly Row[], opts: TimeOptions): TimeLayout {
  const back = daysBack(d, opts.zoom);
  const origin = dayStart(d.now) - back * DAY_MS;
  const goals = list.filter((r): r is Extract<Row, { sort: "goal" }> => r.sort === "goal");
  const GAP = 8;
  // Ce qui n'a pas commencé, à la suite d'aujourd'hui (ou de l'objectif dont il dépend), sans date.
  const ghosts = (day: number): Ghosts => {
    const today = Math.round(((d.now - origin) / DAY_MS) * day);
    const width = Math.max(74, Math.round(day * 0.8));
    const goal = new Map<number, { x0: number; x1: number }>();
    const milestone = new Map<string, number>();
    let end = today + TAIL;
    for (const r of goals) {
      let cur = today + 34;
      const before = r.o.after ? goal.get(r.o.after) : undefined;
      if (before) cur = Math.max(cur, before.x1 + 18);
      const waiting = r.o.milestones.filter((m) => !m.started_at && m.status !== "reached");
      if (!waiting.length && (r.o.started_at || r.o.status === "done")) continue;
      const x0 = cur;
      for (const m of waiting) {
        milestone.set(`${r.o.id}:${m.id}`, cur);
        cur += width + GAP;
      }
      const g = { x0, x1: waiting.length ? cur - GAP : cur + width };
      goal.set(r.o.id, g);
      end = Math.max(end, g.x1 + 40);
    }
    return { today, end, width, goal, milestone };
  };
  // La largeur d'un jour : la naturelle ; puis, si la piste est mesurée et que tout n'y tient pas, resserrée — du
  // passé seulement, la suite sans date gardant sa place — jusqu'à ce que la première date et la suite tiennent.
  const { natural, min } = DAY_WIDTH[opts.zoom];
  let J: number = natural;
  let G = ghosts(J);
  for (let i = 0; i < 5 && opts.width > 0 && G.end > opts.width && J > min; i++) {
    const past = (d.now - origin) / DAY_MS;
    J = Math.max(min, Math.min(J - 1, Math.floor((opts.width - (G.end - G.today)) / past)));
    G = ghosts(J);
  }
  const x = (ms: number): number => Math.round(((ms - origin) / DAY_MS) * J);
  const today = G.today;
  const GW = G.width;
  const ghost = G.goal;
  const ghostX = G.milestone;
  const end = G.end;

  const span = (cls: string, a: number, b: number): Bar => ({ cls, left: a, width: Math.max(10, b - a) });
  const tracks: Track[] = list.map((r) => {
    if (r.sort === "mission") {
      return { bars: [], label: today + 14, line: today, passes: r.o.passes.filter((p) => p >= origin).map((p) => ({ x: x(p), at: p })) };
    }
    if (r.sort === "milestone") {
      const m = r.m;
      const tone = milestoneTone(m);
      if (!m.started_at && m.status !== "reached") {
        const gx = ghostX.get(`${r.o.id}:${m.id}`) ?? today + 34;
        return { bars: [span("fantome", gx, gx + GW)], label: -1 };
      }
      const a = x(m.started_at || m.reached_at);
      const b = x(m.status === "reached" ? m.reached_at || d.now : d.now);
      const bars = m.ready && m.ready_at ? [span("work", a, x(m.ready_at)), span("you hache", x(m.ready_at), b)] : [span(`${tone}${m.status === "reached" ? "" : " encours"}`, a, b)];
      return { bars, label: Math.max(b, a + 10) + 10 };
    }
    const o = r.o;
    const tone: Tone = o.status === "done" ? "done" : o.status === "blocked" ? "fail" : "work";
    const g = ghost.get(o.id);
    const bars: Bar[] = [];
    let label = -1;
    if (o.started_at) {
      const running = o.status !== "done";
      const stop = x(running ? d.now : o.closed_at || o.last_run || d.now);
      bars.push(span(`obj ${tone}${running ? " encours" : ""}`, x(o.started_at), stop));
      // une flèche part de cette barre vers l'objectif qui en dépend : son mot lui laisse la place
      if (!g) label = stop + (goals.some((q) => q.o.after === o.id) ? 24 : 10);
    }
    if (g) bars.push(span("obj fantome", g.x0, g.x1));
    return { bars, label };
  });

  // Les flèches : d'un objectif à celui qui en dépend.
  const arrows: Arrow[] = [];
  for (const r of goals) {
    const from = r.o.after ? goals.find((q) => q.o.id === r.o.after) : undefined;
    if (!from) continue;
    const gd = ghost.get(from.o.id);
    const ga = ghost.get(r.o.id);
    const x1 = gd ? gd.x1 : from.o.started_at ? x(from.o.status === "done" ? from.o.closed_at || d.now : d.now) : 0;
    const x2 = ga ? ga.x0 : x(r.o.started_at || d.now);
    arrows.push({ x1, y1: from.y + ROW_GOAL / 2, x2, y2: r.y + ROW_GOAL / 2 });
  }

  const days: AxisDay[] = Array.from({ length: back + 1 }, (_, i) => ({ x: i * J, at: origin + i * DAY_MS, today: i === back }));
  const width = Math.max(end, opts.width > 0 ? opts.width : 0);
  return { day: J, width, origin, today, days, tracks, arrows, fits: opts.width > 0 && end <= opts.width };
}

/**
 * L'échelle quand la personne n'en a pas choisi : en jours si la première date et aujourd'hui tiennent ensemble dans la
 * piste (resserrée au besoin), sinon en semaines — les premiers jours ne sont pas hors champ à l'ouverture. Un
 * diagramme qui ne tient pas même en semaines s'ouvre sur sa première date.
 */
export function pickZoom(d: Pick<Diagram, "now" | "from" | "objectives">, trackWidth: number): "days" | "weeks" {
  if (trackWidth <= 0) return "days";
  return (daysBack(d, "days") + 1) * DAY_WIDTH.days.min + TAIL <= trackWidth ? "days" : "weeks";
}

/** Le tracé d'une flèche : en équerre vers la droite, ou en contournant quand la cible est avant la source. */
export function arrowPath(a: Arrow): { line: string; head: string } {
  if (a.x2 >= a.x1 + 16) {
    // un court trait après la barre, puis la descente, puis l'entrée dans la cible : le mot de la barre reste lisible
    return { line: `M${a.x1 + 2} ${a.y1} h8 V${a.y2} H${a.x2 - 7}`, head: `M${a.x2 - 9} ${a.y2 - 4} l6 4 l-6 4` };
  }
  return {
    line: `M${a.x1 + 2} ${a.y1} h10 V${a.y2 - ROW_GOAL / 2 + 3} H${a.x2 - 12} V${a.y2} H${a.x2 - 4}`,
    head: `M${a.x2 - 8} ${a.y2 - 4} l6 4 l-6 4`,
  };
}
