/* Outils : le reflet de ses droits pour toi (ADR 0208, 0209) — ressource par ressource, chaque outil nommé pour
   elle, ce qu'elle en fait quand tu lui parles et d'elle-même, par le canal choisi ; les services qui lui sont ouverts.
   Sur un téléphone, on lit un canal à la fois (comme le frontendv2) : l'app Android d'abord. */
(function () {
  const { h, ico } = A;
  const CANAUX = [['mobile', 'App Android'], ['web', 'Chat web · en privé'], ['salon', 'Chat web · en salon'], ['teams', 'Teams'], ['courrier', 'Courrier']];
  const NIV = { S: 'Seule', A: 'Accord', N: '—' };
  const O = (l, n, r, pourquoi) => ({ l, n, r, pourquoi });
  // r : pour chaque canal, deux lettres (quand tu lui parles, d'elle-même) : S seule, A ton accord, N non.
  const RES = [
    { g: 'Ses propres outils', nom: 'Mémoire', ico: 'book', sous: 'ses souvenirs, ce qu\'elle sait de toi', outils: [
      O('Chercher dans sa mémoire', 'memory_search', { mobile: 'SS', web: 'SS', salon: 'SN', teams: 'SN', courrier: 'SN' }, 'Ligne 3 : tout le monde · tous · quand elle répond — lit : seule'),
      O('Dire qu\'une promesse est tenue', 'memory_promise_done', { mobile: 'SS', web: 'SS', salon: 'NN', teams: 'SN', courrier: 'SN' }, 'Minimum vital : toi — seule')] },
    { g: 'Ses propres outils', nom: 'Rappels', ico: 'clock', sous: 'les rappels qu\'elle te promet', outils: [
      O('Te promettre un rappel', 'goal_remind', { mobile: 'SS', web: 'SS', salon: 'NN', teams: 'SN', courrier: 'SN' }, 'Minimum vital : toi — seule'),
      O('Déplacer ou retirer un rappel', 'goal_remind_change', { mobile: 'SN', web: 'SN', salon: 'NN', teams: 'SN', courrier: 'SN' }, 'Minimum vital : toi — seule, quand elle répond')] },
    { g: 'Ses propres outils', nom: 'Projets', ico: 'code', sous: 'Piloter un projet : modification', outils: [
      O('Lancer une séance de travail', 'start_project', { mobile: 'SN', web: 'SN', salon: 'NN', teams: 'NN', courrier: 'NN' }, 'Labo de trading · Site de l\'association : Piloter — modification'),
      O('Pousser le dépôt d\'un projet', 'project_push', { mobile: 'AN', web: 'AN', salon: 'NN', teams: 'NN', courrier: 'NN' }, 'Pousser — accord du propriétaire')] },
    { g: 'Tes comptes', nom: 'Courrier · Pro', ico: 'mail', sous: 'a.moreau@lumen-conseil.fr · à toi', outils: [
      O('Lister et lire les mails', 'email_list · email_read', { mobile: 'SS', web: 'SS', salon: 'NN', teams: 'NN', courrier: 'NN' }, 'Ligne 1 : toi · tous · quand elle répond — lit : seule'),
      O('Préparer une réponse', 'email_draft', { mobile: 'SA', web: 'SA', salon: 'NN', teams: 'NN', courrier: 'NN' }, 'Ligne 2 : toi · quand elle prend la parole — agit : ton accord'),
      O('Envoyer un mail', 'email_send', { mobile: 'AN', web: 'AN', salon: 'NN', teams: 'NN', courrier: 'NN' }, 'Règle d\'envoi de la boîte : ton accord, toujours')] },
    { g: 'Tes comptes', nom: 'Teams · Lumen Conseil', ico: 'teams', sous: 'par l\'extension · à toi', outils: [
      O('Lire les discussions', 'teams_read', { mobile: 'SS', web: 'SS', salon: 'NN', teams: 'SS', courrier: 'NN' }, 'Ligne 1 : toi · tous — lit : seule'),
      O('Répondre dans une discussion', 'teams_reply', { mobile: 'AA', web: 'AA', salon: 'NN', teams: 'AA', courrier: 'NN' }, 'Règle d\'envoi : « Café » seule ; ailleurs ton accord')] },
    { g: 'Ce téléphone', nom: 'Position', ico: 'pin', sous: 'Lui dire où je suis · allumé', outils: [
      O('Regarder où tu es', 'location_where', { mobile: 'SN', web: 'SN', salon: 'NN', teams: 'NN', courrier: 'NN' }, 'ADR 0119 : en tête-à-tête, quand vous vous parlez, jamais d\'elle-même')] },
    { g: 'Services', nom: 'Le web', ico: 'globe', sous: 'chercher et lire une page', outils: [
      O('Chercher sur le web', 'web_search', { mobile: 'SS', web: 'SS', salon: 'SN', teams: 'SN', courrier: 'SN' }, 'Ligne 4 : tout le monde · quand elle répond — lit : seule'),
      O('Lire une page', 'web_fetch', { mobile: 'SS', web: 'SS', salon: 'SN', teams: 'SN', courrier: 'NN' }, 'Ligne 4 : tout le monde — lit : seule')] },
    { g: 'Services', nom: 'Météo Locale', ico: 'plug', sous: 'service distant · à toi', outils: [
      O('Prévisions d\'un lieu', 'meteo_previsions', { mobile: 'AN', web: 'AN', salon: 'NN', teams: 'NN', courrier: 'NN' }, 'Ton réglage du service : il lit — avec ton accord')] },
  ];
  const lvl = (c) => `<span class="lvl ${c}">${NIV[c]}</span>`;

  function vueDroits() {
    const canal = 'mobile';
    let groupe = '';
    const cartes = RES.map((r, i) => {
      const tete = r.g !== groupe ? `<div class="list-head" style="padding:12px 4px 2px">${h(r.g)}</div>` : '';
      groupe = r.g;
      const compte = { S: 0, A: 0, N: 0 };
      r.outils.forEach((o) => { compte[o.r[canal][0]]++; });
      return `${tete}<div class="res" data-foldroot><button type="button" data-fold=".tools">${ico(r.ico)}<span class="grow"><b>${h(r.nom)}</b><small>${h(r.sous)}</small>
          <span class="sum-pills">${compte.S ? `<span class="lvl S">${compte.S} seule</span>` : ''}${compte.A ? `<span class="lvl A">${compte.A} accord</span>` : ''}${compte.N ? `<span class="lvl N">${compte.N} non</span>` : ''}</span></span><svg class="ico sm"><use class="fold-ico" href="#i-chev-${i < 1 ? 'up' : 'down'}"/></svg></button>
        <div class="tools"${i < 1 ? '' : ' hidden'}>${r.outils.map((o) => `<button class="tool-row" type="button" data-sheet="pourquoi" data-why="${h(o.pourquoi)}" data-tool="${h(o.l)}"><span class="txt">${h(o.l)}<small class="muted" style="display:block">${h(o.n)}</small></span><span class="lvls">${lvl(o.r[canal][0])}${lvl(o.r[canal][1])}</span></button>`).join('')}</div></div>`;
    }).join('');
    return {
      nav: A.v.nav === 'barre' ? 'plus' : 'outils', racine: true, back: '#plus',
      html: `${A.top({ racine: true, back: A.v.nav === 'barre', title: 'Outils', small: true })}${A.tabs([['#outils', 'Droits'], ['#outils/services', 'Services'], ['#outils/accords', 'Accords']], '#outils')}
        <div class="row" style="padding:10px 16px 6px"><span class="muted">Par où</span><button class="chip on" type="button" data-sheet="canal">${ico('phone', 'xs')}App Android${ico('chev-down', 'xs')}</button></div>
        <div class="row" style="padding:0 30px 4px 16px;justify-content:flex-end;gap:4px;font-size:10.5px;line-height:13px;color:var(--muted)"><span style="width:56px;text-align:center">quand tu lui parles</span><span style="width:56px;text-align:center">d'elle-même</span></div>
        <div class="body"><div style="display:grid;gap:8px;padding:0 16px 16px">${cartes}</div></div>`,
      notes: {
        titre: 'Outils · Droits',
        reprend: ['La matrice du frontendv2, lue un canal à la fois (le choix en haut, l\'app Android d\'abord) : pour chaque outil, ce qu\'elle fait quand tu lui parles, et d\'elle-même.', 'Une ressource par carte, repliable, avec son résumé ; toucher un outil dit pourquoi (la ligne qui décide).'],
        trancher: ['Deux pastilles par outil (tu lui parles · d\'elle-même) : lisible à cette taille ?', 'Outils mérite-t-il une place dans l\'app, ou seulement sur le web ?'],
      },
    };
  }
  function vueServices() {
    const S = [['globe', 'Le web', 'de Mika · chercher et lire une page', ['ok', 'ouvert']], ['plug', 'Météo Locale', 'à toi · service distant', ['ok', 'branché']], ['code', 'Devis', 'app de la Forge · base du projet Lumen', ['ok', 'ouvert']],
      ['plug', 'Factures', 'de l\'opératrice · ligne de son catalogue', ['pc', 'lecture']], ['calendar', 'Agenda de Léa', 'partagé avec toi · utiliser', ['pc', 'partagé']]];
    return {
      nav: A.v.nav === 'barre' ? 'plus' : 'outils', racine: true, back: '#plus',
      html: `${A.top({ racine: true, back: A.v.nav === 'barre', title: 'Outils', small: true })}${A.tabs([['#outils', 'Droits'], ['#outils/services', 'Services'], ['#outils/accords', 'Accords']], '#outils/services')}
        <div class="body">${S.map(([i, n, s, e]) => `<button class="li" type="button" data-go="#parametres/mcp"><span class="lead box">${ico(i)}</span><span class="txt"><b>${h(n)}</b><small>${h(s)}</small></span><span class="tag ${e[0]}">${h(e[1])}</span></button>`).join('')}
        <p class="note">Brancher ou régler un service : Paramètres › Services MCP.</p></div>`,
      notes: { titre: 'Outils · Services', reprend: ['Ceux qui lui sont ouverts : le web, les tiens, ceux de l\'opératrice, ceux qu\'on te partage.'], trancher: [] },
    };
  }
  function vueAccords() {
    return {
      nav: A.v.nav === 'barre' ? 'plus' : 'outils', racine: true, back: '#plus',
      html: `${A.top({ racine: true, back: A.v.nav === 'barre', title: 'Outils', small: true })}${A.tabs([['#outils', 'Droits'], ['#outils/services', 'Services'], ['#outils/accords', 'Accords']], '#outils/accords')}
        <div class="body"><div class="cards"><div class="card"><h3>Ses accords se décident dans le chat</h3><p class="muted" style="margin:6px 0 12px">Une carte au-dessus du champ, avec exactement ce qui partira. L'historique des décisions viendra ici quand une route le rendra.</p>
        <button class="btn tonal" type="button" data-go="#chat">${ico('chat')}Ouvrir le chat</button></div></div></div>`,
      notes: { titre: 'Outils · Accords', reprend: ['Comme le frontendv2 : l\'onglet attend une route qui rende ses cartes.'], trancher: ['Garder l\'onglet vide, ou le retirer tant qu\'il n\'a rien ?'] },
    };
  }
  A.ecran('outils', (args) => (args[0] === 'services' ? vueServices() : args[0] === 'accords' ? vueAccords() : vueDroits()));
  A.sheets.pourquoi = (el) => A.sheet(h(el.dataset.tool), `<div style="padding:0 24px 16px"><div class="over">Ce qui décide</div><p style="margin:4px 0 12px">${h(el.dataset.why)}</p>
    <p class="muted label-s">La ligne même et sa page dans la console sont montrées aux opératrices (ADR 0209).</p></div>`);
  A.sheets.canal = () => A.sheet('Par où elle te parle', CANAUX.map(([k, l]) => `<button class="li${k === 'mobile' ? ' sel' : ''}" type="button" data-close data-snack="Colonne : ${h(l)}"><span class="lead box">${ico(k === 'mobile' ? 'phone' : k === 'teams' ? 'teams' : k === 'courrier' ? 'mail' : 'chat')}</span><span class="txt"><b>${h(l)}</b></span></button>`).join(''));
  A.index('Outils', [['Droits', '#outils'], ['Services', '#outils/services'], ['Accords', '#outils/accords']]);
})();
