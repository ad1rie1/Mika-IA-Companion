/* Proposé le 2026-11-22 (ADR 0300) : les photos de profil de Teams à la place des initiales, partout où une personne
   a un avatar (fil Teams, conversations, Contacts, Mail…). Seules les personnes que Teams montre ont une photo — les
   collègues ; un proche vu seulement au téléphone ou au courrier garde ses initiales, une organisation son carré.
   Chargé juste après maquette.js, avant les écrans (qui prennent `M.av` à leur chargement). `?photos=0` : sans. */
(function () {
  if (new URLSearchParams(location.search).get('photos') === '0') return;

  /* Des portraits dessinés (la maquette n'a pas de vraies photos) : un fond, une tête, des épaules, une teinte par
     personne ; le vrai écran montre la photo que l'extension a téléchargée de Teams (64 px). */
  const TEINTES = { claire: [18, 62], marc: [210, 30], sophie: [330, 45], karim: [28, 40], nadia: [280, 35] };
  function portrait(teinte, peau) {
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
      <defs><linearGradient id="f" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="hsl(${teinte} 45% 78%)"/><stop offset="1" stop-color="hsl(${teinte} 40% 58%)"/></linearGradient></defs>
      <rect width="64" height="64" fill="url(#f)"/>
      <path d="M10 64c2-13 11-19 22-19s20 6 22 19z" fill="hsl(${teinte} 30% 32%)"/>
      <circle cx="32" cy="27" r="12" fill="hsl(${peau} 45% 72%)"/>
      <path d="M20 26c0-9 6-14 12-14s12 5 12 14c-3-5-7-7-12-7s-9 2-12 7z" fill="hsl(${teinte} 25% 25%)"/></svg>`;
    return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
  }
  const PHOTOS = {};
  for (const [cle, [teinte, peau]] of Object.entries(TEINTES)) PHOTOS[cle] = portrait(teinte, peau);
  /* Les images de groupe de Teams : une conversation de groupe a la sienne. */
  PHOTOS['groupe:lumen'] = portrait(250, 30);
  M.photoDe = (cle) => PHOTOS[cle] || '';

  const avant = M.av;
  M.av = (qui, taille, pres) => {
    const cle = typeof qui === 'string' ? qui : '';
    const photo = cle && cle !== 'mika' ? PHOTOS[cle] : '';
    if (!photo) return avant(qui, taille, pres);
    const p = pres ? `<i class="pres ${pres}"></i>` : '';
    const nom = M.who(cle).nom;
    return `<span class="av photo${taille ? ' ' + taille : ''}" title="${M.h(nom)}"><img src="${photo}" alt="">${p}</span>`;
  };
})();
