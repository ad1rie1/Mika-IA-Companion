/**
 * Projets, les fenêtres des onglets Code et Documentation : une confirmation qui montre ce qui va se faire (la fusion
 * d'une pull request), et une question en une ligne (le mot sur ce qui a changé). Comme `confirmModal` du cadre :
 * fermée autrement que par son bouton, la réponse est non.
 */
import { h } from "../../shell/dom";
import { closeModal, openModal } from "../../shell/float";
import { ico, type IconName } from "../../shell/icons";

/** Quand la fenêtre se ferme sans réponse : `none()`. */
function onClose(el: HTMLElement, none: () => void): void {
  const scrim = el.parentElement;
  const watch = new MutationObserver(() => {
    if (!scrim?.isConnected) {
      watch.disconnect();
      none();
    }
  });
  if (scrim?.parentElement) watch.observe(scrim.parentElement, { childList: true });
}

/** Une confirmation dont le corps est du HTML déjà échappé : ce qui va être fait, dit en entier. */
export function confirmHtml(o: { title: string; bodyHtml: string; ok: string; icon?: IconName; danger?: boolean }): Promise<boolean> {
  return new Promise((resolve) => {
    let answered = false;
    const el = openModal({
      title: o.title, size: "narrow", body: o.bodyHtml,
      foot: `<span class="grow"></span><button class="btn" type="button" data-close>Annuler</button><button class="btn ${o.danger ? "danger" : "primary"}" type="button" data-ok>${o.icon ? ico(o.icon, "sm") : ""}${h(o.ok)}</button>`,
    });
    el.querySelector("[data-ok]")?.addEventListener("click", () => {
      answered = true;
      closeModal();
      resolve(true);
    });
    onClose(el, () => {
      if (!answered) resolve(false);
    });
  });
}

/** Une question en une ligne ; `null` si on renonce. Entrée valide. `required` : une réponse vide ne part pas. */
export function askLine(o: { title: string; label: string; hint?: string; ok: string; noteHtml?: string; required?: boolean; value?: string }): Promise<string | null> {
  return new Promise((resolve) => {
    let answered = false;
    const el = openModal({
      title: o.title, size: "narrow",
      body: `<div class="stack"><label class="field"><span>${h(o.label)}</span><input data-p2-line value="${h(o.value ?? "")}" placeholder="${h(o.hint ?? "")}" maxlength="200"></label>${o.noteHtml ?? ""}</div>`,
      foot: `<span class="grow"></span><button class="btn" type="button" data-close>Annuler</button><button class="btn primary" type="button" data-ok>${ico("check", "sm")}${h(o.ok)}</button>`,
    });
    const field = el.querySelector<HTMLInputElement>("[data-p2-line]");
    const answer = (): void => {
      const text = field?.value.trim() ?? "";
      if (!text && o.required) {
        field?.classList.add("p2-manque");
        field?.focus();
        return;
      }
      answered = true;
      closeModal();
      resolve(text);
    };
    el.querySelector("[data-ok]")?.addEventListener("click", answer);
    field?.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        answer();
      }
    });
    onClose(el, () => {
      if (!answered) resolve(null);
    });
  });
}
