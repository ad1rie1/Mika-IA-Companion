/* L'effort de réflexion dans le chat (proposé le 2026-11-21, pas encore validé).

   « Auto » ou forcé à un niveau, pour toute la conversation et pour chaque fil de travail : un fil en auto suit la
   conversation, la conversation en auto suit ce que la console règle pour le rôle (« Qui sert quoi », ADR 0285).
   Réservé à un opérateur, comme le mode pro.

   Les écrans validés ne se retouchent pas : ce fichier se pose par-dessus l'écran Chat (`ecrans/chat.js`) sans le
   modifier. Il ajoute une entrée à son menu ⋮, une ligne à « Régler ce fil », une feuille, et, quand l'effort est
   forcé, une pastille dans le champ à côté de « Pro ». Routes : `#chat/effort`, `#chat/pro/effort` (la feuille ouverte). */
(function () {
  const { h, ico, D } = A;
  const NIVEAUX = [['low', 'faible', 'le plus rapide'], ['medium', 'moyen', ''], ['high', 'élevé', ''], ['xhigh', 'très élevé', ''], ['max', 'maximal', 'le plus lent']];
  const nomEffort = (k) => (NIVEAUX.find((n) => n[0] === k) || [])[1] || '';
  const maj = (s) => s.charAt(0).toUpperCase() + s.slice(1);
  // L'exemple : la conversation en auto, le fil « Devis Lefèvre » forcé à « élevé » ; `role` : ce que la console
  // règle aujourd'hui, pour dire ce que « auto » vaut en ce moment.
  const effort = { conv: '', fil: 'high', role: { ordinaire: 'medium', pro: 'high' } };
  const ROUTE = /^#chat(\/pro)?\/effort$/;   // la feuille ouverte d'emblée

  // Cinq barres : autant d'allumées que le niveau.
  function jauge(k) {
    const n = NIVEAUX.findIndex((x) => x[0] === k) + 1;
    return `<svg class="ico" viewBox="0 0 24 24" style="stroke-width:2.4" aria-hidden="true">${[0, 1, 2, 3, 4].map((i) =>
      `<path d="M${4 + i * 4} 20v-${4 + i * 3}"${i < n ? '' : ' style="opacity:.26"'}/>`).join('')}</svg>`;
  }

  // ── La feuille ────────────────────────────────────────────────────────
  function feuille(fil) {
    const k = fil ? effort.fil : effort.conv;
    const titreFil = (document.querySelector('.strand-bar .sb-title b') || {}).textContent || 'ce fil';
    const auto = fil ? `suit la conversation · ${nomEffort(effort.conv || effort.role.pro)} en ce moment`
      : `suit le réglage de la console · ${nomEffort(effort.role.ordinaire)} en ce moment`;
    const ligne = (v, nom, sous) => `<button class="li${k === v ? ' sel' : ''}" type="button" data-effort="${v}" data-portee="${fil ? 'fil' : 'conv'}">
      <span class="lead">${v ? jauge(v) : ico('sparkle')}</span><span class="txt"><b>${h(nom)}</b>${sous ? `<small>${h(sous)}</small>` : ''}</span>${k === v ? ico('check') : ''}</button>`;
    A.sheet('Effort de réflexion', `<p class="note" style="padding:0 24px 8px">${fil ? `Ce fil · ${h(titreFil)}` : 'Toute la conversation, mode pro compris'}</p>
      ${ligne('', 'Auto', auto)}
      <div class="list-head" style="padding-left:24px">Forcer</div>
      ${NIVEAUX.map(([v, nom, sous]) => ligne(v, maj(nom), sous)).join('')}
      <p class="note" style="padding:8px 24px 4px">${fil ? 'Vaut pour ce fil seulement, sur tous tes appareils. Les autres fils suivent la conversation.'
        : 'Vaut sur tous tes appareils, jusqu\'à ce que tu le changes. Un fil de travail peut avoir le sien.'}</p>`);
  }
  A.sheets.effort = () => feuille(false);
  A.sheets['effort-fil'] = () => feuille(true);
  document.addEventListener('click', (e) => {
    const b = e.target.closest('[data-effort]');
    if (!b) return;
    const k = b.dataset.effort, fil = b.dataset.portee === 'fil';
    if (fil) effort.fil = k; else effort.conv = k;
    A.closeAll();
    // venue par la route de la feuille : revenir à l'écran, sinon le rendu la rouvrirait
    if (ROUTE.test(location.hash)) history.replaceState(null, '', location.hash.replace(/\/effort$/, ''));
    A.render();
    A.snack(k ? `Effort forcé à « ${nomEffort(k)} » ${fil ? 'pour ce fil' : 'pour toute la conversation'}` : fil ? 'Ce fil suit de nouveau la conversation' : 'Effort en auto');
  });

  // ── Le menu ⋮ et « Régler ce fil » ────────────────────────────────────
  const ditEffort = (k) => `Effort de réflexion · ${k ? nomEffort(k) : 'auto'}`;
  const menuChat = A.menus.chat, menuPro = A.menus['chat-pro'], reglerFil = A.dialogs.fil;
  A.menus.chat = (x) => {
    const m = menuChat(x);
    if (D.moi.operatrice) m.splice(1, 0, { ico: 'sort', l: ditEffort(effort.conv), sheet: 'effort' });
    return m;
  };
  A.menus['chat-pro'] = (x) => {
    const m = menuPro(x);
    m.splice(2, 0, { ico: 'sort', l: ditEffort(effort.fil), sheet: 'effort-fil' });
    return m;
  };
  A.dialogs.fil = (x) => {
    reglerFil(x);
    const archive = document.querySelector('#overlay .dialog .set-row');
    if (archive) archive.insertAdjacentHTML('beforebegin', `<button class="set-row" type="button" data-sheet="effort-fil" style="padding:14px 0 0;width:100%;text-align:left">
      <span class="txt"><b style="font-size:15px">Effort de réflexion</b><small>${effort.fil ? 'forcé pour ce fil' : 'auto : suit la conversation'}</small></span>
      <span class="muted">${effort.fil ? h(nomEffort(effort.fil)) : 'auto'}</span>${ico('chev-right', 'sm')}</button>`);
  };

  // ── Par-dessus l'écran Chat, à chaque rendu : la pastille, les notes, la feuille d'une route ──
  function pose() {
    const scr = document.querySelector('#app .scr[data-screen="chat"]');
    if (!scr) return;
    const pro = scr.classList.contains('pro');
    const force = pro ? effort.fil || effort.conv : effort.conv;
    const chip = scr.querySelector('.composer .pro-chip');
    if (chip && force && !scr.querySelector('[data-eff-chip]')) {
      chip.insertAdjacentHTML('afterend', `<button class="pro-chip" type="button" data-eff-chip data-sheet="${pro && effort.fil ? 'effort-fil' : 'effort'}"
        title="Effort forcé" style="color:var(--primary);border-color:var(--primary)">${jauge(force)}${h(nomEffort(force))}</button>`);
    }
    const notes = document.getElementById('pn-notes');
    if (notes && !notes.querySelector('[data-eff-note]')) {
      notes.insertAdjacentHTML('beforeend', `<div data-eff-note><h4>Proposé : l'effort de réflexion</h4><ul>
        <li>⋮ › « Effort de réflexion » ouvre une feuille : Auto, ou forcé à un niveau. ${pro
          ? 'Ici il vaut pour ce fil ; en auto, le fil suit la conversation. Il se règle aussi dans « Régler ce fil ».'
          : 'Ici il vaut pour toute la conversation, mode pro compris ; en auto, il suit le réglage de la console.'}</li>
        <li>Forcé, il se voit dans le champ, à côté de « Pro » ; toucher la pastille rouvre la feuille.</li></ul>
        <h4 class="q">À trancher</h4><ol><li>En auto, rien ne se voit dans le champ (on passe par ⋮) : d'accord, ou une pastille toujours visible à côté de « Pro » ?</li></ol></div>`);
    }
    if (ROUTE.test(location.hash)) feuille(pro);
  }
  addEventListener('DOMContentLoaded', () => {
    new MutationObserver(pose).observe(document.getElementById('app'), { childList: true });
    pose();
  });

  A.index('Chat · effort (proposé)', [['Effort', '#chat/effort'], ['Effort d\'un fil', '#chat/pro/effort']]);
})();
