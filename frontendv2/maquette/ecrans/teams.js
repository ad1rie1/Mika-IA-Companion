/* Teams : tes discussions comme dans un vrai client. L'extension « Mika · Teams » lit ce que Teams web reçoit
   et pose ce qui part (ADR 0069) ; tu réponds toi-même, ou tu demandes à Mika de préremplir. Ce qu'elle a
   préparé ou envoyé à ta place se relit dans « Brouillons de Mika ». */
(function () {
  const { h, ico, av } = M;
  const D = M.D;

  const DISC = [
    { id: 'lumen', groupe: true, titre: 'Projet Lumen', membres: ['claire', 'sophie', 'karim'], nonlus: 3, mention: true, t: '12:58', msgs: [
      { jour: 'Aujourd\'hui' },
      { de: 'claire', t: '10:02', txt: 'Bonjour à tous, point d\'étape : la maquette est validée côté client 🎉', reac: [['🎉', 3]] },
      { de: 'karim', t: '10:05', txt: 'top ! je pousse la démo sur la préprod cet aprem' },
      { de: 'adrien', t: '10:11', txt: 'Bravo à tous. Je prépare le support pour jeudi.' },
      { de: 'sophie', t: '12:40', txt: '@Adrien Moreau tu peux valider les chiffres du T3 avant jeudi ? Je les ai mis dans le dossier partagé.', mention: true,
        piece: { nom: 'chiffres-T3-v2.xlsx', taille: '84 Ko', ico: 'file' } },
      { de: 'karim', t: '12:58', txt: 'la démo tourne sur la préprod 🎉', reac: [['🎉', 2], ['👍', 1]] },
    ], brouillon: { txt: 'Je regarde les chiffres demain matin et je te dis avant midi.', etat: 'pose', t: '12:59' } },
    { id: 'claire', qui: 'claire', titre: 'Claire Dubois', nonlus: 1, t: '13:41', msgs: [
      { jour: 'Aujourd\'hui' },
      { de: 'claire', t: '13:38', txt: 'Tu as vu mon mail sur la présentation ?' },
      { de: 'claire', t: '13:41', txt: 'Rien de grave hein, juste la partie budget qui arrive tard 🙂' },
    ], brouillon: { txt: 'Oui je l\'ai vu, merci ! Je te réponds par mail avant ce soir.', etat: 'accord', t: '13:42' } },
    { id: 'marc', qui: 'marc', titre: 'Marc Delmas', t: '11:32', msgs: [
      { jour: 'Hier' },
      { de: 'adrien', t: '21:55', txt: 'Bonsoir Marc, tu aurais dix minutes demain matin ? J\'aimerais revenir sur la réunion.' },
      { de: 'marc', t: '22:10', txt: 'Oui. 11h dans mon bureau.' },
      { jour: 'Aujourd\'hui' },
      { de: 'marc', t: '11:32', txt: 'Merci pour l\'échange de ce matin. Tu as eu raison de m\'en parler. On en reparle vendredi.' },
    ] },
    { id: 'sophie', qui: 'sophie', titre: 'Sophie Laurent', t: '10:20', msgs: [
      { jour: 'Aujourd\'hui' },
      { de: 'sophie', t: '10:18', txt: 'Je t\'envoie le fichier des chiffres, dis-moi si les formules te vont' },
      { de: 'sophie', t: '10:20', txt: '', piece: { nom: 'chiffres-T3-v2.xlsx', taille: '84 Ko', ico: 'file' } },
    ] },
    { id: 'cafe', groupe: true, titre: 'Café ☕', membres: ['nadia', 'karim', 'sophie'], t: '09:47', msgs: [
      { jour: 'Aujourd\'hui' }, { de: 'nadia', t: '09:47', txt: 'Gâteau en salle 3 à 16h pour l\'anniversaire de Karim 🎂', reac: [['🎂', 5]] },
      { de: 'adrien', t: '09:50', txt: 'J\'arrive !', mika: true },
    ] },
    { id: 'karim', qui: 'karim', titre: 'Karim Haddad', t: 'hier', msgs: [
      { jour: 'Hier' }, { de: 'karim', t: '17:20', txt: 'tu peux relire ma PR sur l\'export CSV quand tu as 5 min ?' },
      { de: 'adrien', t: '17:26', txt: 'Je regarde ta PR demain matin.', mika: true },
    ] },
    { id: 'hebdo', groupe: true, titre: 'Réunion hebdo Lumen', membres: ['marc', 'claire', 'sophie'], t: 'lun.', reunion: true, msgs: [
      { jour: 'Lundi 2 novembre' }, { sys: 'Réunion terminée · 45 min' }, { de: 'marc', t: '10:47', txt: 'Merci à tous, compte rendu dans la journée.' },
    ] },
  ];

  const ENVOIS = [
    { disc: 'claire', txt: 'Oui je l\'ai vu, merci ! Je te réponds par mail avant ce soir.', regle: 'ton accord', etat: ['warn', 'attend ton accord · jusqu\'à 15:42'], t: 'aujourd\'hui 13:42', source: 'd\'elle-même' },
    { disc: 'lumen', txt: 'Je regarde les chiffres demain matin et je te dis avant midi.', regle: 'brouillon', etat: ['info', 'posée dans Teams'], t: 'aujourd\'hui 12:59', source: 'd\'elle-même' },
    { disc: 'cafe', txt: 'J\'arrive !', regle: 'brouillon', etat: ['ok', 'partie'], t: 'aujourd\'hui 09:50', source: 'demandée' },
    { disc: 'karim', txt: 'Je regarde ta PR demain matin.', regle: 'ton accord', etat: ['ok', 'partie · retouchée'], t: 'hier 17:26', source: 'demandée', note: 'elle avait écrit « Je regarde ta PR ce soir. »' },
    { disc: 'marc', txt: 'Bonsoir Marc, je voulais te dire que la réunion de ce matin…', regle: 'ton accord', etat: ['', 'tu as répondu toi-même'], t: 'hier 21:40', source: 'demandée' },
    { disc: 'hebdo', txt: 'Compte rendu bien reçu, merci Marc.', regle: 'brouillon', etat: ['danger', 'pas servie'], t: 'lun. 11:02', source: 'd\'elle-même', note: 'Teams web n\'était ouvert nulle part : la file attend 8 h, puis abandonne' },
  ];

  const etat = { disc: 'lumen', filtre: 'tout', info: !matchMedia('(max-width: 1240px)').matches, rempli: false, q: '', cherche: false, mobileLecture: false, texteRempli: null };
  // Comment ça part : la règle du compte (Réglages › Canaux, tableau teams:principal), lue de haut en bas.
  const REGLES = [['Marc', 'oui', 'ton accord'], ['Projet Lumen', 'oui', 'brouillon — c\'est toi qui l\'envoies'], ['par défaut', 'non', 'ton accord']];

  function teteDisc(d, taille) {
    if (d.groupe) return `<span class="av sq grp${taille ? ' ' + taille : ''}" title="${h(d.titre)}">${d.reunion ? ico('calendar', 'sm') : h(M.initiales(d.titre.replace(/[^\p{L}\s]/gu, '')))}</span>`;
    return av(d.qui, taille || '');
  }
  function liste() {
    const garde = (d) => (etat.filtre === 'tout' || (etat.filtre === 'nonlus' ? d.nonlus : d.mention)) && (!etat.q || M.norm(d.titre).includes(M.norm(etat.q)));
    return DISC.filter(garde).map((d) => {
      const der = d.msgs.filter((m) => m.de).slice(-1)[0];
      const qui = der.de === 'adrien' ? 'Toi : ' : d.groupe ? M.who(der.de).court + ' : ' : '';
      return `<button class="li tm-li${d.nonlus ? ' unread' : ''}" type="button" data-disc="${d.id}" aria-selected="${d.id === etat.disc}">
        <span class="tm-av">${teteDisc(d)}</span>
        <span class="li-main"><span class="li-top"><span class="li-title">${h(d.titre)}</span>${d.reunion ? `<span class="tag">${ico('calendar', 'xs')}réunion</span>` : ''}<time>${h(d.t)}</time></span>
          <span class="li-snip">${h(qui + (der.txt || der.piece && der.piece.nom || ''))}</span>
          ${d.brouillon || d.nonlus ? `<span class="li-marks">${d.brouillon ? `<span class="mk">${ico('pen')}${d.brouillon.etat === 'accord' ? 'attend ton accord' : 'brouillon de Mika'}</span>` : ''}
          ${d.mention ? '<span class="badge soft" title="On t\'a mentionné">@</span>' : ''}${d.nonlus ? `<span class="badge">${d.nonlus}</span>` : ''}</span>` : ''}</span></button>`;
    }).join('') || `<div class="empty">${ico('teams')}<b>Rien ici</b><p>Aucune discussion pour ce filtre.</p></div>`;
  }

  function message(m, prec) {
    if (m.jour) return `<div class="day"><span>${h(m.jour)}</span></div>`;
    if (m.sys) return `<div class="tm-sys">${ico('calendar', 'sm')}${h(m.sys)}</div>`;
    const moi = m.de === 'adrien';
    const p = M.who(m.de);
    const suite = prec && prec.de === m.de;
    const txt = h(m.txt).replace(/@Adrien Moreau/g, '<span class="tm-at">@Adrien Moreau</span>');
    return `<div class="tm-msg${moi ? ' me' : ''}${suite ? ' suite' : ''}${m.mention ? ' mention' : ''}">
      ${moi || suite ? '<span class="tm-gut"></span>' : av(m.de, 'sm')}
      <div class="tm-body">${suite ? '' : `<div class="tm-meta"><b>${h(moi ? 'Toi' : p.nom)}</b><time>${h(m.t)}</time></div>`}
        ${m.txt ? `<div class="tm-txt">${txt}</div>` : ''}
        ${m.piece ? `<div class="tm-file">${ico(m.piece.ico)}<span><b>${h(m.piece.nom)}</b><small>${h(m.piece.taille)} · Excel</small></span>${ico('download', 'sm')}</div>` : ''}
        ${m.mika ? `<div class="by-mika">${ico('sparkle')}rédigé avec Mika</div>` : ''}
        ${m.reac ? `<div class="tm-reac">${m.reac.map(([e, n]) => `<span>${e} ${n}</span>`).join('')}</div>` : ''}</div></div>`;
  }

  function brouillonCarte(d) {
    if (!d.brouillon) return '';
    const b = d.brouillon;
    const lib = b.etat === 'accord' ? ['warn', 'Ton accord : elle part quand tu l\'acceptes, ici'] : ['info', 'Posée dans la zone de saisie de Teams : tu l\'envoies là-bas, ou d\'ici'];
    return `<div class="tm-draft"><div class="tm-draft-head">${av('mika', 'xs')}<b>Mika a préparé une réponse</b><span class="tag ${lib[0]}">${h(lib[1])}</span><span class="muted small">${h(b.t)}</span></div>
      <p>« ${h(b.txt)} »</p>
      <div class="row"><span class="grow"></span><button class="btn xs ghost danger" type="button" data-draft="retirer">Retirer</button>
        <button class="btn xs" type="button" data-draft="reprendre">${ico('pen', 'xs')}La reprendre ici</button>
        ${b.etat === 'accord' ? `<button class="btn xs primary" type="button" data-draft="accepter">${ico('check', 'xs')}Accepter</button>` : `<button class="btn xs primary" type="button" data-draft="accepter">${ico('send', 'xs')}Envoyer d'ici</button>`}</div></div>`;
  }

  function info(d) {
    const membres = d.groupe ? d.membres.concat('adrien') : [d.qui, 'adrien'];
    const resume = {
      lumen: 'La démo tourne sur la préprod. Sophie attend ta validation des chiffres du T3 avant jeudi ; le fichier est dans le dossier partagé.',
      claire: 'Claire attend une réponse à son mail sur la présentation de jeudi. Ce n\'est pas un reproche : la partie budget arrive trop tard.',
      marc: 'Le tête-à-tête de ce matin s\'est bien passé. Marc veut en reparler vendredi.',
    }[d.id] || 'Rien qui demande ton attention.';
    return `<aside class="pane tm-info"><div class="pane-head"><h2>Informations</h2><span class="grow"></span>
        <button class="btn icon ghost sm" type="button" data-info title="Fermer">${ico('x', 'sm')}</button></div>
      <div class="pane-scroll tm-info-body">
        <div class="mika-note">${av('mika', 'sm')}<div class="mn-body"><div class="mn-title">${ico('sparkle', 'xs')}Ce que Mika en retient</div><span class="small">${h(resume)}</span></div></div>
        <h4>Participants <span class="cnt">${membres.length}</span></h4>
        <ul class="tm-people">${membres.map((k) => { const p = M.who(k); return `<li>${av(k, 'sm')}<div><b>${h(k === 'adrien' ? 'Toi' : p.nom)}</b><small>${h(p.titre || p.lien || '')}</small></div></li>`; }).join('')}</ul>
        <h4>Fichiers</h4>
        ${d.msgs.some((m) => m.piece) ? d.msgs.filter((m) => m.piece).slice(0, 1).map((m) => `<div class="tm-file sm">${ico('file')}<span><b>${h(m.piece.nom)}</b><small>${h(m.piece.taille)} · ${h(M.who(m.de).court)}</small></span></div>`).join('') : '<p class="small muted">Aucun fichier dans cette discussion.</p>'}
        <h4>Comment part ce qu'elle prépare ici</h4>
        <p class="small text-2">${h(d.id === 'lumen' ? 'Brouillon — c\'est toi qui l\'envoies (règle « Projet Lumen »).' : d.id === 'marc' ? 'Ton accord (règle « Marc »).' : 'Ton accord (par défaut). Elle ne prépare rien d\'elle-même ici.')}</p>
      </div></aside>`;
  }

  function vueDiscussions() {
    const d = DISC.find((x) => x.id === etat.disc) || DISC[0];
    const sous = d.groupe ? `${d.membres.length + 1} participants` : (M.who(d.qui).titre || '');
    return `<div class="split tm-split${etat.info ? ' with-info' : ''}${etat.mobileLecture ? ' lire' : ''}">
      <aside class="pane"><div class="pane-head">${etat.cherche ? `<label class="search grow">${ico('search', 'sm')}<input type="search" data-tq placeholder="Chercher une discussion" value="${h(etat.q)}"></label>
          <button class="btn icon ghost sm" type="button" title="Fermer la recherche" data-chercher>${ico('x', 'sm')}</button>`
        : `<div class="seg" role="group">${[['tout', 'Tout'], ['nonlus', 'Non lus'], ['mentions', 'Mentions']].map(([k, l]) => `<button type="button" data-filtre="${k}" aria-pressed="${etat.filtre === k}">${l}</button>`).join('')}</div>
        <span class="grow"></span><button class="btn icon ghost sm" type="button" title="Chercher une discussion" data-chercher>${ico('search', 'sm')}</button>`}</div>
        <div class="pane-scroll">${liste()}</div></aside>
      <section class="pane tm-conv">
        <div class="pane-head thread-head"><button class="btn sm icon ghost mobile-back" type="button" data-retour title="Les discussions">${ico('chev-left', 'sm')}</button><span class="tm-av">${teteDisc(d)}</span><div class="grow"><h2>${h(d.titre)}</h2><p class="small muted">${h(sous)}</p></div>
          <button class="btn sm mika" type="button" data-resume>${ico('sparkle', 'sm')}<span class="lbl">Ce qu'elle en retient</span></button>
          <button class="btn icon ghost sm${etat.info ? ' on' : ''}" type="button" data-info title="Informations">${ico('info', 'sm')}</button></div>
        <div class="chat-scroll" data-scroll><div class="tm-msgs">${d.msgs.map((m, i) => message(m, d.msgs[i - 1])).join('')}${brouillonCarte(d)}</div></div>
        <div class="tm-dock">
          <div class="composer tm-cmp${etat.rempli ? ' filled' : ''}">
            ${etat.rempli ? `<div class="tm-filled">${ico('sparkle', 'xs')}Rédigé avec Mika — relis avant d'envoyer<button type="button" class="btn xs ghost" data-vider>Effacer</button></div>` : ''}
            <textarea rows="2" data-tm-input placeholder="Répondre dans « ${h(d.titre)} »…">${etat.rempli ? h(etat.texteRempli || remplissage(d)) : ''}</textarea>
            <div class="cmp-bar"><button class="btn icon ghost sm" type="button" title="Joindre">${ico('clip')}</button>
              <button class="btn icon ghost sm" type="button" title="Emojis">${ico('smile')}</button>
              <button class="btn sm mika" type="button" data-preremplir>${ico('sparkle', 'sm')}<span class="lbl">Préremplir avec Mika</span></button>
              <span class="grow"></span><span class="small muted cmp-hint">${ico('external', 'xs')}partira par l'extension, dans Teams, en ton nom</span>
              <button class="btn sm primary" type="button" data-tm-envoyer>${ico('send', 'sm')}<span class="lbl">Envoyer</span></button></div></div></div>
      </section>${etat.info ? info(d) : ''}</div>`;
  }
  function remplissage(d) {
    return { lumen: 'Oui, je regarde les chiffres demain matin et je te fais un retour avant midi.', claire: 'Oui je l\'ai vu, merci ! Bonne remarque sur le budget, je le remonte en slide 2. Je te renvoie la version corrigée ce soir.',
      marc: 'Merci à toi. Vendredi me va, je te propose 14h ?' }[d.id] || 'Merci, je regarde ça et je reviens vers toi.';
  }

  function vueEnvois() {
    return `<div class="fill-scroll"><div class="page-pad">
      <p class="lede">Ce que Mika a préparé ou envoyé dans Teams à ta place, et ce que c'est devenu. Tu relis et tu décides ici. Comment ça part se règle par personne ou par discussion : brouillon posé dans Teams (c'est toi qui l'envoies), ton accord, ou seule.</p>
      <table class="tbl"><thead><tr><th>Discussion</th><th>Ce qu'elle a écrit</th><th>Comment ça part</th><th>Où ça en est</th><th>Quand</th><th></th></tr></thead><tbody>
      ${ENVOIS.map((e) => { const d = DISC.find((x) => x.id === e.disc); return `<tr><td><a href="#teams/discussions/${d.id}" class="row">${teteDisc(d)}<b>${h(d.titre)}</b></a></td>
        <td>« ${h(e.txt)} »<div class="tiny muted">${h(e.source)}${e.note ? ` · ${h(e.note)}` : ''}</div></td><td class="small">${h(e.regle)}</td>
        <td><span class="tag ${e.etat[0]}">${h(e.etat[1])}</span></td><td class="small nowrap">${h(e.t)}</td>
        <td class="actions">${e.etat[1].startsWith('attend') ? '<button class="btn xs primary" type="button">Accepter</button>' : e.etat[1].startsWith('posée') ? '<button class="btn xs" type="button">Envoyer d\'ici</button>' : ''}</td></tr>`; }).join('')}
      </tbody></table></div></div>`;
  }

  function choisirMode(b) {
    M.menu(b, [{ entete: 'Comment part ce qu\'elle prépare' },
      ...REGLES.map(([qui, prep, part]) => ({ html: `<div class="rule-line"><b>${h(qui)}</b><span>préparer d'elle-même : ${h(prep)}</span><span>part : ${h(part)}</span></div>` })),
      'sep', { label: 'Régler les règles d\'envoi', ico: 'settings', action: () => M.go('#parametres/teams') }]);
  }

  M.register('teams', {
    titre: 'Teams',
    onglets: [{ id: 'discussions', titre: 'Discussions' }, { id: 'brouillons', titre: 'Ses brouillons', cnt: 2 }],
    compte: () => DISC.reduce((n, d) => n + (d.nonlus || 0), 0),
    actions: () => `<span class="ext-chip" title="Ce que le serveur sait de l'extension « Mika · Teams » : son dernier envoi">${ico('plug', 'sm')}<span class="dot ok"></span><b>Extension</b><span class="muted">dernier envoi il y a 2 min</span></span>
      <button class="btn sm" type="button" data-mode-teams title="Comment part ce qu'elle prépare">${ico('send', 'sm')}<span class="lbl">Comment ça part</span>${ico('chev-down', 'sm')}</button>
      <button class="btn primary" type="button" data-nouvelle>${ico('plus', 'sm')}<span class="lbl">Nouvelle discussion</span></button>`,
    monte(sec) {
      M.on(sec, '[data-disc]', 'click', (e, b) => { etat.disc = b.dataset.disc; etat.rempli = false; etat.mobileLecture = true; const d = DISC.find((x) => x.id === etat.disc); d.nonlus = 0; M.go('#teams/discussions/' + etat.disc); M.compter(); });
      M.on(sec, '[data-retour]', 'click', () => { etat.mobileLecture = false; M.rafraichir(); });
      M.on(sec, '[data-chercher]', 'click', () => { etat.cherche = !etat.cherche; if (!etat.cherche) etat.q = ''; M.rafraichir(); const i = sec.querySelector('[data-tq]'); if (i) i.focus(); });
      sec.addEventListener('input', (e) => { if (e.target.matches('[data-tq]')) { etat.q = e.target.value; sec.querySelector('.tm-split > .pane:first-child .pane-scroll').innerHTML = liste(); } });
      M.on(sec, '[data-filtre]', 'click', (e, b) => { etat.filtre = b.dataset.filtre; M.rafraichir(); });
      M.on(sec, '[data-info]', 'click', () => { etat.info = !etat.info; M.rafraichir(); });
      M.on(sec, '[data-mode-teams]', 'click', (e, b) => choisirMode(b));
      M.on(sec, '[data-nouvelle]', 'click', () => M.toast('Maquette : une discussion neuve se commence dans Teams ; l\'extension la verra.', { ico: 'teams' }));
      M.on(sec, '[data-resume]', 'click', () => { if (!etat.info) { etat.info = true; M.rafraichir(); } M.toast('Son résumé est dans le panneau Informations.', { mika: true }); });
      M.on(sec, '[data-preremplir]', 'click', () => {
        const d = DISC.find((x) => x.id === etat.disc);
        if (d.brouillon) { etat.texteRempli = d.brouillon.txt; d.brouillon = null; etat.rempli = true; M.rafraichir(); M.toast('Elle reprend son brouillon ici : il n\'est plus en attente ailleurs.', { mika: true }); return; }
        etat.texteRempli = null;
        M.mika.typing(true); M.mika.set({ etat: 'ecrit', fait: 'en train d\'écrire…' });
        setTimeout(() => { M.mika.typing(false); M.mika.set({ etat: 'eveillee', fait: 'travaille à son bureau' }); etat.rempli = true; M.rafraichir(); M.mika.talk(900); }, 1300);
      });
      M.on(sec, '[data-vider]', 'click', () => { etat.rempli = false; M.rafraichir(); });
      M.on(sec, '[data-draft]', 'click', (e, b) => {
        const d = DISC.find((x) => x.id === etat.disc);
        if (b.dataset.draft === 'reprendre') { etat.texteRempli = d.brouillon.txt; etat.rempli = true; d.brouillon = null; M.rafraichir(); return; }
        if (b.dataset.draft === 'accepter') { d.msgs.push({ de: 'adrien', t: D.maintenant.heure, txt: d.brouillon.txt, mika: true }); M.toast('Accepté : l\'extension l\'envoie dans Teams.', { ico: 'check' }); }
        else M.toast('Brouillon retiré.', { ico: 'x' });
        d.brouillon = null; M.rafraichir();
      });
      M.on(sec, '[data-tm-envoyer]', 'click', () => {
        const ta = sec.querySelector('[data-tm-input]'), txt = ta.value.trim();
        if (!txt) return;
        const d = DISC.find((x) => x.id === etat.disc);
        d.msgs.push({ de: 'adrien', t: D.maintenant.heure, txt, mika: etat.rempli });
        etat.rempli = false; M.rafraichir();
        M.toast('En file : l\'extension le pose dans Teams et l\'envoie.', { ico: 'send' });
      });
    },
    rendu(body, ctx) {
      if (ctx.onglet === 'discussions' && ctx.item && DISC.some((d) => d.id === ctx.item)) { etat.disc = ctx.item; DISC.find((d) => d.id === ctx.item).nonlus = 0; setTimeout(M.compter, 0); }
      body.innerHTML = ctx.onglet === 'brouillons' ? vueEnvois() : vueDiscussions();
      const s = body.querySelector('[data-scroll]'); if (s) s.scrollTop = s.scrollHeight;
    },
    recherche: () => DISC.map((d) => ({ groupe: 'Teams', titre: d.titre, sous: d.msgs.filter((m) => m.txt).slice(-1)[0].txt, ico: 'teams', route: '#teams/discussions/' + d.id })),
    notes: () => [
      { groupe: 'Décidé', statut: 'decide', titre: 'Ses réponses se relisent ici', texte: 'dans Teams (Ses brouillons et la discussion), pas en carte dans le chat : accepter, retoucher, refuser, envoyer d\'ici' },
      { statut: 'decide', titre: 'Envoyer toi-même d\'ici', texte: 'ton message part par l\'extension, comme ce qu\'elle prépare ; une ADR dira s\'il entre dans sa vie' },
      { statut: 'decide', titre: 'Un Teams à chacun', texte: 'chaque utilisateur branche le sien (sa clé, son extension) ; le partager est une délégation' },
      { groupe: 'Ce qui marche déjà', statut: 'existe', titre: 'L\'extension lit Teams web', texte: 'elle pousse ce que Teams reçoit (/api/teams/inbox, clé mtk_), relève la file (/api/teams/outbox) et accuse ; le serveur ne parle jamais à Microsoft', src: 'ADR 0069 · adapters/web/app.py:616-662 · app/teams.py:230-291' },
      { statut: 'existe', titre: 'Le cache', texte: 'tête-à-tête, groupes, canaux, réunions ; texte plat, 1 000 derniers messages par conversation ; « mentions_me »', src: 'adapters/teams/models.py:58-152' },
      { statut: 'existe', titre: 'Elle trie, lit et prépare', texte: 'teams_conversations, teams_read, teams_draft ; d\'elle-même pour une question où elle peut aider, de moins de 2 h', src: 'plugins/teams/tools.py:108-220 · tasks.py:81-112' },
      { statut: 'existe', titre: 'Comment ça part', texte: 'brouillon posé dans Teams, ton accord (carte, 2 h) ou seule, par personne ou discussion ; par défaut : préparer non, ton accord', src: 'vocab/canals.py:189-198' },
      { statut: 'existe', titre: 'Ce que ses réponses deviennent', texte: 'partie, retouchée, « tu as répondu toi-même », pas servie, échec', src: 'adapters/teams/store.py:277-299' },
      { statut: 'en_cours', titre: 'Un Teams par personne', texte: 'plusieurs comptes, chacun à toi, à elle ou à une personne, chacun sa clé', src: 'ADR 0186 (non commitée) · adapters/teams/config.py:27-110' },
      { groupe: 'À faire ou à décider', statut: 'manque', titre: 'Tes discussions dans le frontendv2', texte: 'aucune route ni trame : la console seulement (opérateur), ou Mika dans le chat', src: 'adapters/web/app.py:772-794' },
      { statut: 'manque', titre: 'Écrire toi-même', texte: 'seul teams_draft remplit la file ; un message à toi demande une décision (passe-t-il au journal ?)' },
      { statut: 'manque', titre: '« Préremplir » dans ce compositeur', texte: 'teams.rediger est une action de console, et son résultat arrive dans Teams web, en carte, ou part seul' },
      { statut: 'manque', titre: 'Pièces, réactions, présence, participants, non-lus', texte: 'rien n\'est capté : une pièce n\'est que « [pièce jointe : nom] » (la maquette les montre pour la cible)', src: 'frontend/Extension/lib/extract.js:187-226' },
      { statut: 'partiel', titre: 'L\'historique', texte: 'rien d\'avant l\'installation, 24 h de rattrapage au plus' },
      { statut: 'partiel', titre: 'Teams fermé', texte: 'sans Teams web ouvert avec l\'extension, rien n\'arrive ni ne part : la file attend 8 h, puis « pas servie »' },
      { statut: 'partiel', titre: 'L\'envoi par l\'extension', texte: 'pas encore vérifié contre le vrai Teams (README de l\'extension)' },
      { statut: 'manque', titre: 'Nouvelle discussion, recherche dans les messages', texte: 'on n\'écrit que dans une conversation déjà vue ; la recherche ne porte que sur les titres' },
    ],
  });
})();
