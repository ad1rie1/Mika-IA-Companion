/**
 * Panneau "vie intérieure" de Mika.
 *
 * Affiche, à partir du payload ``inner_state`` attaché à chaque événement
 * ``speech`` diffusé par le backend :
 *   - blend émotionnel (ambivalence multi-label)
 *   - ce qu'elle fait dans sa chambre (« en train de dessiner »)
 *   - ce qu'elle a en train (« En ce moment ») et ses rappels promis
 *   - self-narrative (qui elle pense être devenue)
 *   - besoins (compagnie, s'exprimer, apprendre — les mots de la console)
 *   - ruminations actives
 *   - profil de la personne courante + engagements pendants
 *
 * L'affichage ne fait aucun appel réseau : tout arrive par le WebSocket.
 * Seule exception, l'approbation/refus d'une action en attente, qui est un
 * POST HTTP (via ``postJson``) — le backend répond par un
 * ``inner_state_update`` qui repeint la section. Le panneau peut être replié
 * (clic sur le header) pour libérer l'écran.
 */

import type {
  DreamType,
  EmotionBlend,
  InnerState,
  InnerStateActivity,
  PendingProjectAction,
  ProjectSummary,
  SleepPhase,
} from "../types";
import { emotionFr, resolveSleepPhase } from "../types";
import { postJson } from "../network/api";

const PHASE_META: Record<
  "morning" | "afternoon" | "evening" | "night",
  { label: string; icon: string; color: string }
> = {
  morning: { label: "Matin", icon: "🌅", color: "#f59e0b" },
  afternoon: { label: "Aprem", icon: "☀️", color: "#fbbf24" },
  evening: { label: "Soir", icon: "🌆", color: "#a78bfa" },
  night: { label: "Nuit", icon: "🌙", color: "#6366f1" },
};

/**
 * Ses besoins, avec les mots de la console (`faculties/needs/inspect.py` :
 * compagnie, s'exprimer, apprendre) — un seul vocabulaire, vérifié par un
 * test côté serveur. Le panneau disait « Pulsions : Lien social, Expression,
 * Curiosité » quand la console disait « Besoins : compagnie… ».
 */
export const DRIVE_LABELS: Record<string, { label: string; icon: string; color: string }> = {
  social: { label: "Compagnie", icon: "👥", color: "#ec4899" },
  expression: { label: "S'exprimer", icon: "💬", color: "#f59e0b" },
  curiosity: { label: "Apprendre", icon: "❔", color: "#6366f1" },
};

/** La confiance du transport, en mots (`vocab/privacy.py::ChannelTrust`) —
 * le panneau affichait « (100 % — authenticated) ». */
export const TRUST_LABEL: Record<string, string> = {
  authenticated: "connexion authentifiée",
  account: "compte privé",
  public: "salon public",
  internal: "interne",
};

/** Le titre du journal montré : le serveur le date (« Son journal d'hier »).
 * Jamais « d'aujourd'hui » : la journée en cours ne s'écrit que la nuit. */
export function journalTitle(journal: { title?: string } | undefined): string {
  const title = journal?.title?.trim();
  return title || "Son dernier journal";
}

/** Toutes les quinze secondes, la ligne « ce qu'elle fait » se relit : sa
 * durée grandit, une occupation minutée finit sans trame du serveur. */
const ACTIVITY_REFRESH_MS = 15_000;

/** Depuis combien de temps, en mots (jamais un chiffre, comme dans son
 * prompt) : du plus long au plus court ; en deçà, rien. */
const ACTIVITY_LASTING: Array<[number, string]> = [
  [90, "depuis un bon moment"],
  [45, "depuis une heure"],
  [25, "depuis une demi-heure"],
  [10, "depuis un quart d'heure"],
  [2, "depuis quelques minutes"],
];

/** « En train de regarder dehors, depuis un quart d'heure » : son
 * occupation telle qu'elle la dit (le libellé du serveur), et sa durée. */
export function activityLine(label: string, since: number, now: number): string {
  const minutes = (now - since) / 60_000;
  const lasting = ACTIVITY_LASTING.find(([min]) => minutes >= min)?.[1];
  const of = /^[aeiouyàâéèêëîïôöùûü]/i.test(label) ? "d'" : "de ";
  return `En train ${of}${label}${lasting ? `, ${lasting}` : ""}`;
}

/** Ce qu'elle a en train, en mots (`app/mindport.py::_doing_kind`) : une
 * rêverie n'est pas une recherche. Une sorte inconnue se montre sans étiquette. */
const DOING_KIND_LABEL: Record<string, string> = {
  musing: "rêverie",
  reflection: "elle y repense",
  exploration: "elle va voir",
};

/** L'heure d'un rappel (« jeudi 9 octobre à 09:00 ») ; absente ou illisible :
 * rien plutôt qu'une date fausse. */
export function reminderWhen(due: string | null | undefined): string {
  if (!due) return "";
  const at = new Date(due);
  if (Number.isNaN(at.getTime())) return "";
  const day = at.toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" });
  const hour = at.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
  return `${day} à ${hour}`;
}

/** Une revendication d'identité en une ligne : la phrase citée seulement
 * quand il y en a une (sinon « — «  » »). */
export function claimLine(claim: { name: string; evidence?: string }): string {
  const evidence = (claim.evidence ?? "").trim();
  return (
    `se présente comme <strong>${escapeHtml(claim.name)}</strong>` +
    (evidence ? ` — « ${escapeHtml(evidence)} »` : "")
  );
}

const CLOSENESS_LABEL: Record<string, string> = {
  stranger: "inconnu·e",
  acquaintance: "connaissance",
  friend: "ami·e",
  close: "proche",
};

const TONE_LABEL: Record<string, string> = {
  direct: "direct",
  gentle: "doux",
  playful: "joueur",
  formal: "formel",
  unknown: "—",
};

const SLEEP_PHASE_META: Record<SleepPhase, { label: string; icon: string }> = {
  awake: { label: "éveillée", icon: "" },
  light_sleep: { label: "endormie (journal)", icon: "📓" },
  rem: { label: "endormie (rêve)", icon: "💫" },
  deep_sleep: { label: "sommeil profond", icon: "💤" },
};

// Une entrée par sorte que le serveur envoie : `Record<DreamType, …>` fait
// refuser au compilateur une sorte oubliée (« melancholic » s'affichait brut).
export const DREAM_TYPE_LABEL: Record<DreamType, { label: string; color: string }> = {
  associative: { label: "rêve associatif", color: "#a78bfa" },
  nightmare: { label: "cauchemar léger", color: "#ef4444" },
  pleasant: { label: "rêve doux", color: "#fbbf24" },
  mundane: { label: "rêve banal", color: "#9ca3af" },
  melancholic: { label: "rêve mélancolique", color: "#60a5fa" },
};

export class InnerLifePanel {
  private root: HTMLElement;
  private blendEl: HTMLElement;
  private drivesEl: HTMLElement;
  private narrativeEl: HTMLElement;
  private ruminationsEl: HTMLElement;
  private profileEl: HTMLElement;
  private phaseBadgeEl: HTMLElement;
  private sleepBadgeEl: HTMLElement;
  private energyFillEl: HTMLElement;
  private energyValueEl: HTMLElement;
  private esteemSectionEl: HTMLElement;
  private esteemFillEl: HTMLElement;
  private esteemValueEl: HTMLElement;
  private dreamEl: HTMLElement;
  private journalEl: HTMLElement;
  private projectsEl: HTMLElement;
  private pendingEl: HTMLElement;
  private activitySectionEl: HTMLElement;
  private activityEl: HTMLElement;
  private doingSectionEl: HTMLElement;
  private doingEl: HTMLElement;
  private remindersSectionEl: HTMLElement;
  private remindersEl: HTMLElement;

  /** Son occupation montrée, relue tant qu'elle dure (ACTIVITY_REFRESH_MS). */
  private activity: InnerStateActivity | null = null;
  private activityTick: number | null = null;

  private currentSleepPhase: SleepPhase = "awake";
  private sleepPhaseListeners: Array<(phase: SleepPhase) => void> = [];

  constructor(containerId: string = "inner-life-panel") {
    this.root = document.getElementById(containerId)!;
    if (!this.root) {
      throw new Error(`InnerLifePanel: container #${containerId} not found`);
    }

    this.root.innerHTML = `
      <div class="il-header" role="button" aria-expanded="true">
        <span>Vie intérieure</span>
        <span class="il-sleep-badge" title="État de sommeil" hidden></span>
        <span class="il-phase-badge" title="Phase circadienne">—</span>
        <span class="il-toggle">▾</span>
      </div>
      <div class="il-body">
        <section class="il-section" id="il-energy">
          <h4>Énergie</h4>
          <div class="il-energy-row">
            <span class="il-energy-bar">
              <span class="il-energy-fill" style="width:50%"></span>
            </span>
            <span class="il-energy-value">—</span>
          </div>
        </section>
        <section class="il-section" id="il-esteem" hidden>
          <h4>Estime de soi</h4>
          <div class="il-energy-row">
            <span class="il-energy-bar">
              <span class="il-energy-fill il-esteem-fill" style="width:50%"></span>
            </span>
            <span class="il-energy-value il-esteem-value">—</span>
          </div>
        </section>
        <section class="il-section" id="il-activity" hidden>
          <h4>Ce qu'elle fait</h4>
          <p class="il-activity-body"></p>
        </section>
        <section class="il-section" id="il-doing" hidden>
          <h4>En ce moment</h4>
          <ul class="il-doing-body"></ul>
        </section>
        <section class="il-section" id="il-reminders" hidden>
          <h4>Ce qu'elle t'a promis</h4>
          <ul class="il-commitments il-reminders-body"></ul>
        </section>
        <section class="il-section" id="il-dream" hidden>
          <h4>Rêve de cette nuit</h4>
          <div class="il-dream-body"></div>
        </section>
        <section class="il-section" id="il-journal" hidden>
          <h4 class="il-journal-title">Son dernier journal</h4>
          <div class="il-journal-body"></div>
        </section>
        <section class="il-section" id="il-pending-actions" hidden>
          <h4>⚠ Ce qui attend ton accord</h4>
          <div class="il-pending-body"></div>
        </section>
        <section class="il-section" id="il-projects" hidden>
          <h4>Projets en cours</h4>
          <div class="il-projects-body"></div>
        </section>
        <section class="il-section" id="il-blend">
          <h4>Émotion</h4>
          <div class="il-blend-body">—</div>
        </section>
        <section class="il-section" id="il-drives">
          <h4>Besoins</h4>
          <div class="il-drives-body"></div>
        </section>
        <section class="il-section" id="il-narrative" hidden>
          <h4>Qui elle est devenue</h4>
          <p class="il-narrative-body"></p>
        </section>
        <section class="il-section" id="il-ruminations" hidden>
          <h4>Elle repense à…</h4>
          <ul class="il-ruminations-body"></ul>
        </section>
        <section class="il-section" id="il-profile" hidden>
          <h4>Comment elle te perçoit</h4>
          <div class="il-profile-body"></div>
        </section>
      </div>
    `;

    this.blendEl = this.root.querySelector(".il-blend-body")!;
    this.drivesEl = this.root.querySelector(".il-drives-body")!;
    this.narrativeEl = this.root.querySelector(".il-narrative-body")!;
    this.ruminationsEl = this.root.querySelector(".il-ruminations-body")!;
    this.profileEl = this.root.querySelector(".il-profile-body")!;
    this.phaseBadgeEl = this.root.querySelector(".il-phase-badge")!;
    this.sleepBadgeEl = this.root.querySelector(".il-sleep-badge")!;
    this.energyFillEl = this.root.querySelector("#il-energy .il-energy-fill")!;
    this.energyValueEl = this.root.querySelector("#il-energy .il-energy-value")!;
    this.esteemSectionEl = this.root.querySelector("#il-esteem")!;
    this.esteemFillEl = this.root.querySelector(".il-esteem-fill")!;
    this.esteemValueEl = this.root.querySelector(".il-esteem-value")!;
    this.dreamEl = this.root.querySelector(".il-dream-body")!;
    this.journalEl = this.root.querySelector(".il-journal-body")!;
    this.projectsEl = this.root.querySelector(".il-projects-body")!;
    this.pendingEl = this.root.querySelector(".il-pending-body")!;
    this.activitySectionEl = this.root.querySelector("#il-activity")!;
    this.activityEl = this.root.querySelector(".il-activity-body")!;
    this.doingSectionEl = this.root.querySelector("#il-doing")!;
    this.doingEl = this.root.querySelector(".il-doing-body")!;
    this.remindersSectionEl = this.root.querySelector("#il-reminders")!;
    this.remindersEl = this.root.querySelector(".il-reminders-body")!;

    // Collapse/expand on header click
    const header = this.root.querySelector(".il-header") as HTMLElement;
    const body = this.root.querySelector(".il-body") as HTMLElement;
    const toggle = this.root.querySelector(".il-toggle") as HTMLElement;
    header.addEventListener("click", () => {
      const hidden = body.hasAttribute("hidden");
      if (hidden) {
        body.removeAttribute("hidden");
        header.setAttribute("aria-expanded", "true");
        toggle.textContent = "▾";
      } else {
        body.setAttribute("hidden", "");
        header.setAttribute("aria-expanded", "false");
        toggle.textContent = "▸";
      }
    });
  }

  // ── Public API ──────────────────────────────────────────────

  setEmotionBlend(blend: EmotionBlend, intensity: number) {
    if (!blend || blend.length === 0) {
      this.blendEl.textContent = `intensité ${Math.round(intensity * 100)}%`;
      return;
    }
    const primary = blend[0];
    if (blend.length === 1 || (blend[1] && blend[1].weight < primary.weight * 0.4)) {
      this.blendEl.innerHTML =
        `<span class="il-emotion-primary">${escapeHtml(emotionFr(primary.emotion))}</span> ` +
        `<span class="il-weight">(${Math.round(primary.weight * 100)}%)</span>`;
      return;
    }
    const secondary = blend[1];
    this.blendEl.innerHTML =
      `<span class="il-emotion-primary">${escapeHtml(emotionFr(primary.emotion))}</span> ` +
      `<span class="il-weight">(${Math.round(primary.weight * 100)}%)</span>` +
      `<span class="il-ambivalence"> mais aussi </span>` +
      `<span class="il-emotion-secondary">${escapeHtml(emotionFr(secondary.emotion))}</span> ` +
      `<span class="il-weight">(${Math.round(secondary.weight * 100)}%)</span>`;
  }

  applyInnerState(state: InnerState | undefined) {
    if (!state) return;
    this.renderCircadian(state.circadian, state.energy);
    this.renderEsteem(state.estime);
    // Absente (un serveur plus ancien) : la ligne garde ce qu'elle montrait.
    if (state.activity !== undefined) {
      this.activity = state.activity;
      this.renderActivity();
    }
    this.renderSleepPhase(resolveSleepPhase(state.sleep_phase));
    this.renderDream(state.last_dream);
    this.renderJournal(state.today_journal);
    this.renderPendingActions(state.pending_project_actions);
    this.renderProjects(state.projects);
    this.renderDrives(state.drives);
    this.renderNarrative(state.self_narrative);
    this.renderRuminations(state.ruminations);
    // Only when the payload is actually about someone. A frame that says
    // nothing about any person — a sleep-phase transition, a project
    // queueing an action — must not be read as "she no longer knows who
    // you are": these renderers clear what they are handed nothing for,
    // which is right for an empty section and wrong for an absent scope.
    if (state.person_scope !== false) {
      this.renderProfile(
        state.person_profile, state.pending_commitments, state.identity,
      );
      this.renderDoing(state.doing);
      this.renderReminders(state.reminders);
    }
  }

  /** Subscribe to sleep-phase transitions (drives avatar + scene visuals). */
  onSleepPhaseChange(cb: (phase: SleepPhase) => void): void {
    this.sleepPhaseListeners.push(cb);
    // Fire immediately with current state so new subscribers are synced
    cb(this.currentSleepPhase);
  }

  getSleepPhase(): SleepPhase {
    return this.currentSleepPhase;
  }

  private renderCircadian(
    circadian: InnerState["circadian"],
    energy: number | undefined,
  ) {
    // Phase badge in the header
    if (circadian) {
      const meta = PHASE_META[circadian.phase];
      if (meta) {
        const hour = circadian.hour.toString().padStart(2, "0");
        this.phaseBadgeEl.textContent = `${meta.icon} ${meta.label} ${hour}h`;
        this.phaseBadgeEl.style.background = `${meta.color}33`;
        this.phaseBadgeEl.style.color = meta.color;
      }
    }

    // Energy bar
    const level = typeof energy === "number" ? energy : circadian?.energy;
    if (typeof level === "number") {
      const pct = Math.max(0, Math.min(100, Math.round(level * 100)));
      this.energyFillEl.style.width = `${pct}%`;
      // Color shifts from amber (low) to green (high) to help read at a glance
      const hue = Math.round(level * 120); // 0 = red, 120 = green
      this.energyFillEl.style.background = `hsl(${hue}, 70%, 50%)`;
      this.energyValueEl.textContent = `${pct}%`;
    }
  }

  /** La variable lente : doute ↔ assurance, même lecture que l'énergie. */
  private renderEsteem(estime: number | undefined) {
    if (typeof estime !== "number") return;
    this.esteemSectionEl.hidden = false;
    const pct = Math.max(0, Math.min(100, Math.round(estime * 100)));
    this.esteemFillEl.style.width = `${pct}%`;
    const hue = Math.round(estime * 120); // 0 = rouge (doute), 120 = vert
    this.esteemFillEl.style.background = `hsl(${hue}, 55%, 50%)`;
    this.esteemValueEl.textContent = `${pct}%`;
  }

  // ── Renderers ───────────────────────────────────────────────

  /** Une ligne tant qu'elle fait quelque chose ; cachée quand elle ne fait
   * rien ou que la fin prévue est passée. */
  private renderActivity() {
    const a = this.activity;
    const now = Date.now();
    const ended = typeof a?.until === "number" && a.until <= now;
    if (!a || typeof a.label !== "string" || !a.label || ended) {
      this.activity = null;
      this.activitySectionEl.hidden = true;
      this.activityEl.textContent = "";
      if (this.activityTick !== null) {
        window.clearInterval(this.activityTick);
        this.activityTick = null;
      }
      return;
    }
    this.activityEl.textContent = activityLine(a.label, a.since, now);
    this.activitySectionEl.hidden = false;
    if (this.activityTick === null) {
      this.activityTick = window.setInterval(() => this.renderActivity(), ACTIVITY_REFRESH_MS);
    }
  }

  private renderSleepPhase(resolved: SleepPhase) {
    // Badge in the header (hidden when awake to avoid visual noise).
    // Gardé comme le lookup circadien voisin (renderCircadian) : même si
    // `resolved` est déjà validé par `resolveSleepPhase` côté appelant,
    // un lookup non gardé ici referait planter n'importe quel appel direct.
    const meta = SLEEP_PHASE_META[resolved];
    if (resolved === "awake" || !meta) {
      this.sleepBadgeEl.setAttribute("hidden", "");
      this.sleepBadgeEl.textContent = "";
    } else {
      this.sleepBadgeEl.removeAttribute("hidden");
      this.sleepBadgeEl.textContent = `${meta.icon} ${meta.label}`;
    }

    // Notify subscribers on change
    if (resolved !== this.currentSleepPhase) {
      this.currentSleepPhase = resolved;
      for (const cb of this.sleepPhaseListeners) {
        try {
          cb(resolved);
        } catch (e) {
          console.warn("sleep phase listener error:", e);
        }
      }
    }
  }

  private renderProjects(projects: ProjectSummary[] | undefined) {
    const section = document.getElementById("il-projects")!;
    if (!projects || projects.length === 0) {
      section.setAttribute("hidden", "");
      this.projectsEl.innerHTML = "";
      return;
    }
    section.removeAttribute("hidden");
    this.projectsEl.innerHTML = projects
      .map((p) => {
        const pct =
          p.tasks_total > 0
            ? Math.round((p.tasks_done / p.tasks_total) * 100)
            : 0;
        const prio =
          p.priority === "urgent"
            ? "🔥"
            : p.priority === "high"
              ? "⚡"
              : p.priority === "low"
                ? "💤"
                : "•";
        const nextRun = p.next_run_at
          ? new Date(p.next_run_at).toLocaleString("fr-FR", {
              day: "2-digit",
              month: "2-digit",
              hour: "2-digit",
              minute: "2-digit",
            })
          : "—";
        const blockedTag =
          p.tasks_blocked > 0
            ? `<span class="il-project-blocked">⛔ ${p.tasks_blocked}</span>`
            : "";
        // Son mode en mots (« impersonnel »), rien pour son mode à elle —
        // jamais `full` / `off` bruts.
        const emoPolicyTag = p.mode_label
          ? `<span class="il-project-ep">${escapeHtml(p.mode_label)}</span>`
          : "";
        return `
          <div class="il-project" data-project-id="${p.id}">
            <div class="il-project-head">
              <span class="il-project-prio">${prio}</span>
              <span class="il-project-title">${escapeHtml(p.title)}</span>
              ${emoPolicyTag}
              ${blockedTag}
            </div>
            <div class="il-project-bar-wrap">
              <span class="il-project-bar">
                <span class="il-project-fill" style="width:${pct}%"></span>
              </span>
              <span class="il-project-pct">${p.tasks_done}/${p.tasks_total}</span>
            </div>
            <div class="il-project-sched">
              ${escapeHtml(p.schedule_label || "dès que possible")}
              ${p.next_run_at ? `· prochaine séance ${nextRun}` : ""}
            </div>
          </div>
        `;
      })
      .join("");
  }

  /**
   * Whether this viewer may approve/reject pending project actions. A chat
   * account gets 403 from the server (operator required), so the buttons
   * are replaced by a note instead of an error after the click.
   */
  private canApprove = true;

  setCanApprove(can: boolean) {
    this.canApprove = can;
  }

  private renderPendingActions(
    pending: PendingProjectAction[] | undefined,
  ) {
    const section = document.getElementById("il-pending-actions")!;
    if (!pending || pending.length === 0) {
      section.setAttribute("hidden", "");
      this.pendingEl.innerHTML = "";
      return;
    }
    section.removeAttribute("hidden");
    this.pendingEl.innerHTML = pending
      .map(
        (a) => `
          <div class="il-pending" data-action-id="${a.id}">
            <div class="il-pending-project">
              ${escapeHtml(a.owner_label || a.project_title)}
              ${a.kind_label ? `<span class="il-pending-kind">${escapeHtml(a.kind_label)}</span>` : ""}
            </div>
            <div class="il-pending-proposal">${escapeHtml(a.proposal)}</div>
            <div class="il-pending-actions">
              ${this.canApprove
                ? `<button class="il-btn il-btn-approve" data-action="approve" data-id="${a.id}">✓ Approuver</button>
              <button class="il-btn il-btn-reject" data-action="reject" data-id="${a.id}">✗ Rejeter</button>`
                : `<span class="il-pending-note">En attente d'un opérateur</span>`}
            </div>
          </div>
        `,
      )
      .join("");

    // Wire up buttons (lightweight — delegate via query)
    this.pendingEl.querySelectorAll<HTMLButtonElement>(".il-btn").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        const action = btn.dataset.action;
        const id = btn.dataset.id;
        if (!action || !id) return;
        btn.disabled = true;
        try {
          await this.resolvePending(Number(id), action as "approve" | "reject");
        } catch (err) {
          console.error("pending action error:", err);
          btn.disabled = false;
        }
      });
    });
  }

  private async resolvePending(
    actionId: number,
    decision: "approve" | "reject",
  ): Promise<void> {
    const note = decision === "reject"
      ? prompt("Note optionnelle pour le refus :") || ""
      : "";
    const resp = await postJson(
      `/api/projects/pending/${actionId}/${decision}`,
      { note },
    );
    if (!resp.ok) {
      const detail = await resp
        .json()
        .then((body) => body?.error as string | undefined)
        .catch(() => undefined);
      const msg = detail || `HTTP ${resp.status}`;
      alert(`Échec : ${msg}`);
      // Lever, sinon le `catch` du gestionnaire de clic ne s'exécute pas et
      // le bouton reste désactivé alors que rien n'a bougé côté serveur :
      // l'action attend jusqu'au rechargement de la page.
      throw new Error(msg);
    }
    // Server pushes an inner_state_update on success, which will re-render
  }

  private renderDream(dream: InnerState["last_dream"]) {
    const section = document.getElementById("il-dream")!;
    if (!dream || !dream.content) {
      section.setAttribute("hidden", "");
      this.dreamEl.innerHTML = "";
      return;
    }
    section.removeAttribute("hidden");
    // The fallback branch exists for values the whitelist doesn't cover —
    // i.e. raw LLM output — so it has to be escaped like any other.
    const typeMeta = DREAM_TYPE_LABEL[dream.dream_type as DreamType] || {
      label: escapeHtml(dream.dream_type ?? ""),
      color: "#9ca3af",
    };
    const vividnessPct = Math.round(dream.vividness * 100);
    // Opacity scales with vividness — a faint dream looks washed out
    const opacity = 0.4 + dream.vividness * 0.6;
    const recalledMark = dream.recalled
      ? `<span class="il-dream-recalled" title="Elle en a parlé">✓ évoqué</span>`
      : "";
    const emotionTag = dream.emotion
      ? `<span class="il-dream-emotion">${escapeHtml(emotionFr(dream.emotion))}</span>`
      : "";
    this.dreamEl.innerHTML = `
      <div class="il-dream-meta">
        <span class="il-dream-type" style="color:${typeMeta.color}">${typeMeta.label}</span>
        ${emotionTag}
        <span class="il-dream-vividness" title="Intensité du souvenir du rêve">${vividnessPct}%</span>
        ${recalledMark}
      </div>
      <p class="il-dream-text" style="opacity:${opacity}">${escapeHtml(dream.content)}</p>
    `;
  }

  private renderJournal(journal: InnerState["today_journal"]) {
    const section = document.getElementById("il-journal")!;
    if (!journal || !journal.narrative) {
      section.setAttribute("hidden", "");
      this.journalEl.innerHTML = "";
      return;
    }
    section.removeAttribute("hidden");
    const title = section.querySelector(".il-journal-title");
    if (title) title.textContent = journalTitle(journal);
    const emotionTag = journal.dominant_emotion
      ? `<span class="il-journal-emotion">${escapeHtml(emotionFr(journal.dominant_emotion))}</span>`
      : "";
    const persons =
      journal.persons_interacted && journal.persons_interacted.length > 0
        ? `<span class="il-journal-persons">avec ${journal.persons_interacted
            .map(escapeHtml)
            .join(", ")}</span>`
        : "";
    this.journalEl.innerHTML = `
      <div class="il-journal-meta">
        ${emotionTag}
        ${persons}
      </div>
      <p class="il-journal-text">${escapeHtml(journal.narrative)}</p>
    `;
  }

  private renderDrives(drives: InnerState["drives"]) {
    this.drivesEl.innerHTML = "";
    if (!drives) return;
    for (const [kind, state] of Object.entries(drives)) {
      // Unknown drive kinds fall back to the raw server key — escape it.
      const meta =
        DRIVE_LABELS[kind] ||
        { label: escapeHtml(kind), icon: "•", color: "#888" };
      const pct = Math.max(0, Math.min(100, Math.round(state.tension * 100)));
      const row = document.createElement("div");
      row.className = "il-drive";
      row.innerHTML = `
        <span class="il-drive-icon">${meta.icon}</span>
        <span class="il-drive-label">${meta.label}</span>
        <span class="il-drive-bar">
          <span class="il-drive-fill" style="width:${pct}%;background:${meta.color}"></span>
        </span>
        <span class="il-drive-pct">${pct}%</span>
      `;
      this.drivesEl.appendChild(row);
    }
  }

  private renderNarrative(n: InnerState["self_narrative"]) {
    const section = document.getElementById("il-narrative")!;
    if (!n || !n.content) {
      section.setAttribute("hidden", "");
      return;
    }
    section.removeAttribute("hidden");
    this.narrativeEl.textContent = n.content;
  }

  private renderRuminations(list: InnerState["ruminations"]) {
    const section = document.getElementById("il-ruminations")!;
    if (!list || list.length === 0) {
      section.setAttribute("hidden", "");
      this.ruminationsEl.innerHTML = "";
      return;
    }
    section.removeAttribute("hidden");
    this.ruminationsEl.innerHTML = "";
    for (const r of list) {
      const li = document.createElement("li");
      const pct = Math.round(r.intensity * 100);
      li.innerHTML = `
        <span class="il-rumination-intensity" style="--i:${pct}%">${pct}%</span>
        <span class="il-rumination-text">${escapeHtml(r.summary)}</span>
      `;
      this.ruminationsEl.appendChild(li);
    }
  }

  /** « En ce moment » : ce qu'elle a en train et que tu peux entendre. */
  private renderDoing(list: InnerState["doing"]) {
    const items = (list ?? []).filter((d) => d.text?.trim());
    if (items.length === 0) {
      this.doingSectionEl.setAttribute("hidden", "");
      this.doingEl.innerHTML = "";
      return;
    }
    this.doingSectionEl.removeAttribute("hidden");
    this.doingEl.innerHTML = items
      .map((d) => {
        const kind = DOING_KIND_LABEL[d.kind];
        return `<li>${kind ? `<span class="il-doing-kind">${kind}</span>` : ""}` +
          `<span class="il-doing-text">${escapeHtml(d.text.trim())}</span></li>`;
      })
      .join("");
  }

  /** « Ce qu'elle t'a promis » : ses rappels encore à dire, avec leur heure. */
  private renderReminders(list: InnerState["reminders"]) {
    const items = (list ?? []).filter((r) => r.text?.trim());
    if (items.length === 0) {
      this.remindersSectionEl.setAttribute("hidden", "");
      this.remindersEl.innerHTML = "";
      return;
    }
    this.remindersSectionEl.removeAttribute("hidden");
    this.remindersEl.innerHTML = items
      .map((r) => {
        const when = reminderWhen(r.due);
        return `<li>${when ? `<strong class="il-reminder-when">${escapeHtml(when)}</strong> : ` : ""}` +
          `${escapeHtml(r.text.trim())}</li>`;
      })
      .join("");
  }

  private renderProfile(
    profile: InnerState["person_profile"],
    commitments: InnerState["pending_commitments"],
    identity?: InnerState["identity"],
  ) {
    const section = document.getElementById("il-profile")!;
    // The identity block stands on its own: it is precisely when Mika is
    // *not* sure who this is that showing it matters most, and that is
    // exactly when `profile` is withheld.
    const identityHtml = identity ? renderIdentity(identity) : "";
    if (!profile) {
      if (identityHtml) {
        section.removeAttribute("hidden");
        this.profileEl.innerHTML = identityHtml;
      } else {
        section.setAttribute("hidden", "");
        this.profileEl.innerHTML = "";
      }
      return;
    }
    section.removeAttribute("hidden");
    const closeness =
      CLOSENESS_LABEL[profile.closeness] || escapeHtml(profile.closeness ?? "");
    const tone =
      TONE_LABEL[profile.preferred_tone] ||
      escapeHtml(profile.preferred_tone ?? "");
    const topics = profile.topics_of_interest.slice(0, 4).join(", ") || "—";
    const avoid = profile.sensitive_topics.slice(0, 3).join(", ");

    const parts: string[] = [];
    if (identityHtml) parts.push(identityHtml);
    if (profile.summary) {
      parts.push(`<p class="il-profile-summary">${escapeHtml(profile.summary)}</p>`);
    }
    parts.push(`
      <ul class="il-profile-tags">
        <li>relation : <strong>${closeness}</strong></li>
        ${tone ? `<li>ton : <strong>${tone}</strong></li>` : ""}
        <li>intérêts : ${escapeHtml(topics)}</li>
        ${avoid ? `<li>sujets sensibles : ${escapeHtml(avoid)}</li>` : ""}
        <li>${profile.interaction_count} échange(s)</li>
      </ul>
    `);
    if (commitments && commitments.length > 0) {
      parts.push(`<p class="il-commitment-head">Elle t'avait dit :</p>`);
      parts.push(
        `<ul class="il-commitments">` +
          commitments
            .map((c) => `<li>${escapeHtml(c)}</li>`)
            .join("") +
          `</ul>`,
      );
    }
    this.profileEl.innerHTML = parts.join("");
  }
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/**
 * Who Mika thinks she's talking to, and how sure.
 *
 * Rendered even — especially — when `person_profile` is absent: the whole
 * point of the certainty model is that she can be unsure who someone is
 * while still talking to them, and that state is invisible otherwise.
 * Everything here can originate from a user-supplied message (a claimed
 * name, the quoted evidence), so it all goes through escapeHtml.
 */
function renderIdentity(identity: NonNullable<InnerState["identity"]>): string {
  const pct = Math.round(identity.certainty * 100);
  const tone =
    identity.certainty >= 0.85 ? "sure"
      : identity.certainty >= 0.7 ? "likely"
        : identity.certainty >= 0.45 ? "claimed"
          : "unknown";

  const parts = [
    `<div class="il-identity il-identity-${tone}">`,
    `<span class="il-identity-name">${escapeHtml(identity.known_as)}</span>`,
    `<span class="il-weight">(${pct}% — ${escapeHtml(TRUST_LABEL[identity.trust] ?? identity.trust)})</span>`,
    `<p class="il-identity-level">${escapeHtml(identity.level)}</p>`,
  ];

  if (identity.pending_claims?.length) {
    parts.push(`<ul class="il-identity-claims">`);
    for (const claim of identity.pending_claims) {
      parts.push(`<li>${claimLine(claim)}</li>`);
    }
    parts.push(`</ul>`);
  }
  parts.push(`</div>`);
  return parts.join("");
}
