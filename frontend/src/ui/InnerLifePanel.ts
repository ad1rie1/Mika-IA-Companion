/**
 * Panneau "vie intérieure" de Mika.
 *
 * Affiche, à partir du payload ``inner_state`` attaché à chaque événement
 * ``speech`` diffusé par le backend :
 *   - blend émotionnel (ambivalence multi-label)
 *   - self-narrative (qui elle pense être devenue)
 *   - drives (4 tensions intrinsèques)
 *   - ruminations actives
 *   - profil de la personne courante + engagements pendants
 *
 * Ne fait AUCUN appel réseau : tout passe par le WebSocket. Le panneau
 * peut être replié (clic sur le header) pour libérer l'écran.
 */

type EmotionBlend = Array<{ emotion: string; weight: number }>;

interface InnerState {
  drives?: Record<string, { tension: number; last_satisfied: number }>;
  self_narrative?: {
    content: string;
    key_themes: string[];
    key_people: string[];
    dominant_mood: string;
    created_at: string;
  };
  ruminations?: Array<{
    summary: string;
    intensity: number;
    emotion: string;
  }>;
  person_profile?: {
    name: string;
    summary: string;
    closeness: string;
    preferred_tone: string;
    topics_of_interest: string[];
    sensitive_topics: string[];
    interaction_count: number;
  };
  pending_commitments?: string[];
}

const DRIVE_LABELS: Record<string, { label: string; icon: string; color: string }> = {
  curiosity: { label: "Curiosité", icon: "❔", color: "#6366f1" },
  social: { label: "Lien social", icon: "👥", color: "#ec4899" },
  expression: { label: "Expression", icon: "💬", color: "#f59e0b" },
  rest: { label: "Repos", icon: "💤", color: "#10b981" },
};

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

export class InnerLifePanel {
  private root: HTMLElement;
  private blendEl: HTMLElement;
  private drivesEl: HTMLElement;
  private narrativeEl: HTMLElement;
  private ruminationsEl: HTMLElement;
  private profileEl: HTMLElement;

  constructor(containerId: string = "inner-life-panel") {
    this.root = document.getElementById(containerId)!;
    if (!this.root) {
      throw new Error(`InnerLifePanel: container #${containerId} not found`);
    }

    this.root.innerHTML = `
      <div class="il-header" role="button" aria-expanded="true">
        <span>Vie intérieure</span>
        <span class="il-toggle">▾</span>
      </div>
      <div class="il-body">
        <section class="il-section" id="il-blend">
          <h4>Émotion</h4>
          <div class="il-blend-body">—</div>
        </section>
        <section class="il-section" id="il-drives">
          <h4>Pulsions</h4>
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
        `<span class="il-emotion-primary">${primary.emotion}</span> ` +
        `<span class="il-weight">(${Math.round(primary.weight * 100)}%)</span>`;
      return;
    }
    const secondary = blend[1];
    this.blendEl.innerHTML =
      `<span class="il-emotion-primary">${primary.emotion}</span> ` +
      `<span class="il-weight">(${Math.round(primary.weight * 100)}%)</span>` +
      `<span class="il-ambivalence"> mais aussi </span>` +
      `<span class="il-emotion-secondary">${secondary.emotion}</span> ` +
      `<span class="il-weight">(${Math.round(secondary.weight * 100)}%)</span>`;
  }

  applyInnerState(state: InnerState | undefined) {
    if (!state) return;
    this.renderDrives(state.drives);
    this.renderNarrative(state.self_narrative);
    this.renderRuminations(state.ruminations);
    this.renderProfile(state.person_profile, state.pending_commitments);
  }

  // ── Renderers ───────────────────────────────────────────────

  private renderDrives(drives: InnerState["drives"]) {
    this.drivesEl.innerHTML = "";
    if (!drives) return;
    for (const [kind, state] of Object.entries(drives)) {
      const meta = DRIVE_LABELS[kind] || { label: kind, icon: "•", color: "#888" };
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

  private renderProfile(
    profile: InnerState["person_profile"],
    commitments: InnerState["pending_commitments"],
  ) {
    const section = document.getElementById("il-profile")!;
    if (!profile) {
      section.setAttribute("hidden", "");
      this.profileEl.innerHTML = "";
      return;
    }
    section.removeAttribute("hidden");
    const closeness = CLOSENESS_LABEL[profile.closeness] || profile.closeness;
    const tone = TONE_LABEL[profile.preferred_tone] || profile.preferred_tone;
    const topics = profile.topics_of_interest.slice(0, 4).join(", ") || "—";
    const avoid = profile.sensitive_topics.slice(0, 3).join(", ");

    const parts: string[] = [];
    if (profile.summary) {
      parts.push(`<p class="il-profile-summary">${escapeHtml(profile.summary)}</p>`);
    }
    parts.push(`
      <ul class="il-profile-tags">
        <li>relation : <strong>${closeness}</strong></li>
        <li>ton : <strong>${tone}</strong></li>
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
    .replace(/"/g, "&quot;");
}
