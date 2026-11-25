/**
 * Demander quelque chose à Mika depuis un autre écran : le chat s'ouvre, la question posée dans son champ (« Lui
 * demander » de Paramètres › Compte, la fiche d'un outil dans Outils).
 */
import type { Shell } from "../shell/shell";

/**
 * Ouvrir le chat avec une question posée dans son champ, à relire avant de l'envoyer : l'aide de « Lui demander »,
 * dans Paramètres › Compte et sur la fiche d'un outil (Outils). Ce qui y était déjà écrit reste, la question vient à la
 * suite. Le champ est attendu le temps que le chat se dessine (il garde ce qui est écrit quand il se redessine).
 */
export function askMika(shell: Shell, question: string): void {
  shell.go("#chat");
  let tries = 0;
  const put = () => {
    const input = document.querySelector<HTMLTextAreaElement>('.screen[data-screen="chat"]:not([hidden]) [data-chat-input]');
    if (!input || input.disabled) {
      if (++tries < 40) window.setTimeout(put, 25);
      return;
    }
    const before = input.value.trim();
    input.value = before ? `${before}\n${question}` : question;
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  };
  window.setTimeout(put, 0);
}
