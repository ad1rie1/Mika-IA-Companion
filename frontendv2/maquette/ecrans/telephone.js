/* Téléphone : ce que ton téléphone montre à Mika (ADR 0120 : WhatsApp et Messages), sa dernière position
   (ADR 0119), et répondre : toi-même, ou en lui demandant. Une réponse ne part que par le téléphone : le geste
   « Envoyer » y vaut accord. */
(function () {
  const { h, ico, av } = M;
  const D = M.D;
  const APPS = { whatsapp: ['whatsapp', 'W', 'WhatsApp'], sms: ['sms', 'M', 'Messages'], colis: ['colis', 'C', 'Colissimo'],
    agenda: ['agenda', 'A', 'Agenda'], strava: ['strava', 'S', 'Strava'] };
  const appIco = (k, lg) => `<span class="app-ico ${APPS[k][0]}${lg ? ' lg' : ''}" title="${APPS[k][2]}">${APPS[k][1]}</span>`;

  const TELS = [
    { id: 's25', nom: 'Android · samsung SM-S931B', court: 'samsung SM-S931B', vu: 'vu il y a 3 min', dot: 'ok', pos: { lieu: 'rue Nationale, Lille', prec: 12, quand: '14:10', coord: '50.636512, 3.058271', x: 400, y: 182 } },
    { id: 'p7a', nom: 'Android · Google Pixel 7a', court: 'Google Pixel 7a', vu: 'vu hier à 22:10', dot: 'warn', pos: { lieu: 'Euralille, Lille', prec: 25, quand: 'hier 18:05', coord: '50.637690, 3.075130', x: 610, y: 250 } },
  ];
  const CONV = [
    { id: 'julien', tel: 's25', qui: 'julien', app: 'whatsapp', titre: 'Julien Roux', nonlus: 2, t: '14:09', msgs: [
      { jour: 'Hier' },
      { de: 'julien', t: '19:02', txt: 'on fait la boucle des Monts dimanche avec thomas et camille, t\'es chaud ?' },
      { jour: 'Aujourd\'hui' },
      { de: 'julien', t: '14:08', txt: 'alors dimanche, tu viens ?' },
      { de: 'julien', t: '14:09', txt: 'départ 8h30 du parking de la gare' },
      { note: 'Mika a lu ces messages et t\'en a parlé dans le chat, à 14:12', route: '#chat' },
    ] },
    { id: 'rando', tel: 's25', groupe: true, membres: ['thomas', 'julien', 'camille'], app: 'whatsapp', titre: 'Rando dimanche 🥾', nonlus: 5, t: '13:47', msgs: [
      { jour: 'Aujourd\'hui' },
      { de: 'thomas', t: '11:20', txt: 'Je propose la boucle des Monts : 14 km, 300 m de dénivelé' },
      { de: 'camille', t: '11:24', txt: 'grave partante !' },
      { de: 'julien', t: '12:02', txt: 'je peux prendre 3 personnes dans la voiture' },
      { de: 'thomas', t: '13:45', txt: 'Météo : averses le matin' },
      { de: 'thomas', t: '13:47', txt: 'on décale à 9h ?' },
      { prop: { txt: '9h ça me va 👍 je prends ma voiture aussi si besoin', etat: 'attente', exp: 'expire dans 1 h 52', t: '13:58' } },
    ] },
    { id: 'maman', tel: 's25', qui: 'maman', app: 'sms', titre: 'Maman', t: '12:40', msgs: [
      { jour: 'Aujourd\'hui' },
      { de: 'maman', t: '12:31', txt: 'Tu passes dimanche midi ? Je fais un rôti' },
      { moi: true, t: '12:40', txt: 'Je viens après la rando, vers 13h30 !', etat: 'parti par Messages · écrit depuis le web' },
    ] },
    { id: 'lea', tel: 's25', qui: 'lea', app: 'whatsapp', titre: 'Léa', t: '11:02', msgs: [
      { jour: 'Aujourd\'hui' },
      { de: 'lea', t: '11:02', txt: 'tu as reçu mon colis ? c\'est pour l\'anniv de papa, ne l\'ouvre pas 🙃' },
    ] },
    { id: 'garage', tel: 's25', qui: 'garage', app: 'sms', titre: 'Garage Martin', t: '10:15', msgs: [
      { jour: 'Aujourd\'hui' },
      { de: 'garage', t: '10:15', txt: 'Bonjour M. Moreau, votre véhicule est prêt. Vous pouvez le récupérer à partir de 17h. Garage Martin' },
    ] },
    { id: 'camille', tel: 's25', qui: 'camille', app: 'whatsapp', titre: 'Camille Petit', t: 'hier', msgs: [
      { jour: 'Hier' }, { de: 'camille', t: '22:14', txt: '😂😂 trop bien la photo' },
    ] },
    { id: 'sophie', tel: 'p7a', qui: 'sophie', app: 'whatsapp', titre: 'Sophie Laurent', t: 'hier', nonlus: 1, msgs: [
      { jour: 'Hier' }, { de: 'sophie', t: '21:48', txt: 'tu as pu regarder le fichier des chiffres ? pas de stress, c\'est pour jeudi' },
    ] },
    { id: 'mutuelle', tel: 'p7a', qui: { nom: 'Mutuelle Horizon', c: 4 }, app: 'sms', titre: 'Mutuelle Horizon', t: 'lun.', msgs: [
      { jour: 'Lundi 2 novembre' }, { de: '_mutuelle', t: '10:02', txt: 'Votre remboursement de 32,50 € a été effectué. Mutuelle Horizon.' },
    ] },
  ];

  const NOTIFS = [
    { jour: 'Aujourd\'hui' },
    { app: 'whatsapp', t: '14:09', titre: 'Julien Roux', txt: 'départ 8h30 du parking de la gare', sort: ['mika', 'lue par Mika'], conv: 'julien' },
    { app: 'whatsapp', t: '14:08', titre: 'Julien Roux', txt: 'alors dimanche, tu viens ?', sort: ['mika', 'lue par Mika'], conv: 'julien' },
    { app: 'whatsapp', t: '13:47', titre: 'Rando dimanche 🥾 · Thomas', txt: 'on décale à 9h ?', sort: ['warn', 'réponse proposée'], conv: 'rando' },
    { app: 'colis', t: '13:30', titre: 'Colissimo', txt: 'Votre colis arrive aujourd\'hui entre 14 h et 16 h.', sort: ['', 'reçue'], autre: true },
    { app: 'sms', t: '12:31', titre: 'Maman', txt: 'Tu passes dimanche midi ? Je fais un rôti', sort: ['ok', 'répondu par toi'], conv: 'maman' },
    { app: 'agenda', t: '12:00', titre: 'Agenda', txt: 'Revue Lumen · jeudi 10:00 · salle 3', sort: ['', 'reçue'], autre: true },
    { app: 'whatsapp', t: '11:02', titre: 'Léa', txt: 'tu as reçu mon colis ? c\'est pour l\'anniv de papa, ne l\'ouvre pas 🙃', sort: ['mika', 'lue par Mika'], conv: 'lea' },
    { app: 'sms', t: '10:15', titre: 'Garage Martin', txt: 'Bonjour M. Moreau, votre véhicule est prêt…', sort: ['mika', 'lue par Mika'], conv: 'garage' },
    { app: 'strava', t: '09:58', titre: 'Strava', txt: 'Thomas Girard a aimé ta sortie « Tour du lac ».', sort: ['', 'reçue'], autre: true },
    { jour: 'Hier' },
    { app: 'whatsapp', t: '21:48', titre: 'Sophie Laurent', txt: 'tu as pu regarder le fichier des chiffres ? pas de stress, c\'est pour jeudi', sort: ['', 'reçue'], conv: 'sophie', tel: 'p7a' },
    { app: 'whatsapp', t: '22:14', titre: 'Camille Petit', txt: '😂😂 trop bien la photo', sort: ['', 'reçue'], conv: 'camille' },
    { app: 'whatsapp', t: '19:02', titre: 'Julien Roux', txt: 'on fait la boucle des Monts dimanche avec thomas et camille, t\'es chaud ?', sort: ['mika', 'lue par Mika'], conv: 'julien' },
  ];

  const REGARDS = [
    { t: 'aujourd\'hui 14:12', lieu: 'rue Nationale, Lille', pour: '« au fait, Julien t\'a écrit sur WhatsApp… »' },
    { t: 'aujourd\'hui 09:05', lieu: 'Euralille, Lille', pour: '« bonne réunion. tu me raconteras »' },
    { t: 'hier 18:41', lieu: 'gare Lille-Flandres', pour: '« tu rentres déjà ? »' },
  ];

  const etat = { conv: 'julien', filtre: 'toutes', q: '', prerempli: false, mobileLecture: false, tel: 'tous' };
  const telDe = (id) => TELS.find((t) => t.id === id);
  const garde = (c) => etat.tel === 'tous' || c.tel === etat.tel;
  // Ce qu'elle écrirait, conversation par conversation (à la première personne, comme toi).
  const PROPOSE = { julien: 'carrément, je viens ! je serai au parking vers 8h20', rando: '9h ça me va 👍 je prends ma voiture aussi si besoin',
    maman: 'Oui ! j\'arrive vers 13h30 après la rando 😊', lea: 'oui il est arrivé ce matin, je ne l\'ouvre pas promis 😄',
    garage: 'Merci, je passe le récupérer vers 17h30.', camille: '😄 je t\'envoie les autres ce soir',
    sophie: 'oui je regarde demain matin, je te fais un retour avant midi', mutuelle: '' };

  // ── Les messages ─────────────────────────────────────────────────────
  function liste() {
    return CONV.filter(garde).filter((c) => !etat.q || M.norm(c.titre).includes(M.norm(etat.q))).map((c) => {
      const p = c.groupe ? `<span class="av sq grp">${h(M.initiales(c.titre.replace(/[^\p{L}\s]/gu, '')))}</span>` : av(c.qui);
      const dernier = c.msgs.filter((m) => m.txt).slice(-1)[0];
      const qui = dernier && dernier.de && c.groupe ? M.who(dernier.de).court + ' : ' : dernier && dernier.moi ? 'Toi : ' : '';
      const prop = c.msgs.some((m) => m.prop && m.prop.etat === 'attente');
      return `<button class="li conv${c.nonlus ? ' unread' : ''}" type="button" data-conv="${c.id}" aria-selected="${c.id === etat.conv}">
        <span class="conv-av">${p}${appIco(c.app)}</span>
        <span class="li-main"><span class="li-top"><span class="li-title">${h(c.titre)}</span><time>${h(c.t)}</time></span>
          <span class="li-snip">${h(qui + (dernier ? dernier.txt : ''))}</span>
          <span class="li-marks">${etat.tel === 'tous' ? `<span class="tel-mark">${ico('phone', 'xs')}${h(telDe(c.tel).court)}</span>` : ''}${prop ? `<span class="mk">${ico('pen')}réponse proposée</span>` : ''}${c.nonlus ? `<span class="badge">${c.nonlus}</span>` : ''}</span></span></button>`;
    }).join('');
  }

  function fil(c) {
    return c.msgs.map((m) => {
      if (m.jour) return `<div class="day"><span>${h(m.jour)}</span></div>`;
      if (m.note) return `<a class="msg-note center" href="${m.route}">${ico('eye', 'xs')}${h(m.note)}</a>`;
      if (m.prop) return proposition(m.prop, c);
      if (m.moi) return `<div class="tmsg me"><div class="bubble">${h(m.txt)}</div><div class="msg-meta">${h(m.t)} · ${ico('checks', 'xs')} ${h(m.etat)}</div></div>`;
      const p = m.de === '_mutuelle' ? { court: 'Mutuelle Horizon' } : M.who(m.de);
      return `<div class="tmsg them">${c.groupe ? av(m.de, 'sm') : ''}<div class="msg-col">${c.groupe ? `<span class="tmsg-who">${h(p.court)}</span>` : ''}
        <div class="bubble">${h(m.txt)}</div><div class="msg-meta">${h(m.t)}</div></div></div>`;
    }).join('');
  }
  function proposition(p, c) {
    const etats = { attente: ['warn', `attend ton envoi · ${p.exp}`], envoyee: ['ok', `partie par ${APPS[c.app][2]}`], retiree: ['', 'retirée'] };
    const [cls, lib] = etats[p.etat];
    return `<div class="prop">
      <div class="prop-head">${av('mika', 'xs')}<b>Réponse proposée par Mika</b><span class="muted small">${h(p.t)}</span></div>
      <div class="prop-txt">« ${h(p.txt)} »</div>
      <div class="prop-foot"><span class="tag ${cls}">${ico(p.etat === 'attente' ? 'phone' : 'check')}${h(lib)}</span><span class="grow"></span>
        ${p.etat === 'attente' ? `<button class="btn xs ghost danger" type="button" data-prop="retirer">Retirer</button>
        <button class="btn xs ghost" type="button" data-prop="modifier">${ico('pen', 'xs')}Modifier</button>
        <button class="btn xs primary" type="button" data-prop="envoyer">${ico('send', 'xs')}Envoyer d'ici</button>` : ''}</div>
      ${p.etat === 'attente' ? `<p class="prop-help">Envoie-la d'ici, ou d'un geste sur ton téléphone : il affiche « Répondre à ${h(c.titre)} (${APPS[c.app][2]}) ? » avec Envoyer, Écrire autre chose et Ignorer.</p>` : ''}
    </div>`;
  }

  function vueMessages() {
    if (!garde(CONV.find((x) => x.id === etat.conv) || {})) etat.conv = (CONV.find(garde) || CONV[0]).id;
    const c = CONV.find((x) => x.id === etat.conv) || CONV[0];
    const sous = c.groupe ? c.membres.map((k) => M.who(k).court).join(', ') + ' et toi' : (M.who(c.qui).moyens.find((x) => x[0] === 'tel') || ['', ''])[1];
    return `<div class="split tel-split${etat.mobileLecture ? ' lire' : ''}">
      <aside class="pane"><div class="pane-head"><label class="search grow">${ico('search', 'sm')}<input type="search" data-cq placeholder="Chercher une conversation" value="${h(etat.q)}"></label></div>
        <div class="pane-scroll" data-convs>${liste()}</div></aside>
      <section class="pane tel-thread">
        <div class="pane-head thread-head"><button class="btn sm icon ghost mobile-back" type="button" data-retour title="Les conversations">${ico('chev-left', 'sm')}</button>
          ${c.groupe ? `<span class="av sq grp lg">${h(M.initiales(c.titre.replace(/[^\p{L}\s]/gu, '')))}</span>` : av(c.qui, 'lg')}
          <div class="grow"><h2>${h(c.titre)} ${appIco(c.app)}</h2><p class="small muted">${h(sous)} · ${ico('phone', 'xs')} ${h(telDe(c.tel).court)}</p></div>
          <button class="btn icon ghost sm" type="button" title="Plus" data-more>${ico('more')}</button></div>
        <div class="chat-scroll" data-scroll><div class="tel-msgs">${fil(c)}</div></div>
        <div class="tel-dock">
          <div class="composer tel-cmp${etat.prerempli ? ' filled' : ''}">
            ${etat.prerempli ? `<div class="tm-filled">${ico('sparkle', 'xs')}Prérempli par Mika — relis avant d'envoyer<button type="button" class="btn xs ghost" data-vider>Effacer</button></div>` : ''}
            <textarea rows="1" data-tel-input placeholder="Ta réponse à ${h(c.titre)}…">${etat.prerempli ? h(PROPOSE[c.id] || '') : ''}</textarea>
            <div class="cmp-bar"><button class="btn sm mika" type="button" data-preremplir>${ico('sparkle', 'sm')}<span class="lbl">Préremplir avec Mika</span></button>
              <span class="small muted cmp-hint">${ico('phone', 'xs')}partira par ${h(telDe(c.tel).court)}, dans ${APPS[c.app][2]}, en ton nom</span>
              <span class="grow"></span>
              <button class="btn sm primary" type="button" data-envoyer>${ico('send', 'sm')}<span class="lbl">Envoyer</span></button></div>
          </div></div>
      </section></div>`;
  }

  // ── Les notifications ────────────────────────────────────────────────
  function vueNotifs() {
    const parTel = (n) => n.jour || etat.tel === 'tous' || (n.tel || 's25') === etat.tel;
    const gardeN = (n) => n.jour || etat.filtre === 'toutes' || (etat.filtre === 'messages' ? !n.autre : n.autre);
    const items = NOTIFS.filter(parTel).filter(gardeN).filter((n, i, a) => !n.jour || (a[i + 1] && !a[i + 1].jour));
    return `<div class="fill-scroll"><div class="page-pad notifs">
      <div class="mika-note info-note">${ico('info')}<div class="mn-body"><div class="mn-title">Ce que ton téléphone lui montre</div>
        <span class="small">Les apps que tu as choisies : WhatsApp, WhatsApp Business, Messages, Colissimo, Agenda et Strava. Jamais la banque, ni les codes de connexion.
        <a href="#parametres/telephones">Choisir les apps</a></span></div></div>
      <div class="notif-list">${items.map((n) => n.jour ? `<div class="day"><span>${h(n.jour)}</span></div>` :
        `<${n.conv ? `a href="#telephone/messages/${n.conv}"` : 'div'} class="notif">${appIco(n.app, true)}
          <span class="notif-main"><span class="li-top"><b>${h(n.titre)}</b><span class="muted small">${h(APPS[n.app][2])}${etat.tel === 'tous' ? ` · ${h(telDe(n.tel || 's25').court)}` : ''}</span><time>${h(n.t)}</time></span>
          <span class="notif-txt">${h(n.txt)}</span></span>
          <span class="tag ${n.sort[0]}">${h(n.sort[1])}</span></${n.conv ? 'a' : 'div'}>`).join('')}</div>
    </div></div>`;
  }

  // ── La position ──────────────────────────────────────────────────────
  function carte(pos) {
    // Une carte dessinée : des îlots, la Deûle, la rue Nationale, la Grand-Place. Aucune tuile extérieure.
    return `<svg class="map" viewBox="0 0 800 560" role="img" aria-label="Carte : rue Nationale, Lille">
      <rect class="m-bg" width="800" height="560"/>
      <path class="m-park" d="M40 380 L210 350 L240 470 L60 520 Z"/><path class="m-park" d="M600 60 L760 40 L780 150 L640 170 Z"/>
      <path class="m-water" d="M0 300 C 120 260, 180 330, 260 300 S 380 220, 470 250 S 640 330, 800 280"/>
      ${[[90, 80, 150, 110], [270, 70, 130, 90], [430, 60, 140, 120], [100, 220, 120, 60], [470, 330, 150, 90], [300, 380, 140, 110], [640, 380, 120, 120], [520, 160, 90, 60], [620, 210, 140, 50]].map(([x, y, w, hh]) => `<rect class="m-block" x="${x}" y="${y}" width="${w}" height="${hh}" rx="6"/>`).join('')}
      <path class="m-road big" d="M0 200 L800 160"/><path class="m-road" d="M250 0 L330 560"/><path class="m-road" d="M590 0 L560 560"/>
      <path class="m-road" d="M0 470 L800 430"/><path class="m-road big" d="M120 560 C 260 400, 420 300, 800 330"/>
      <text class="m-label" x="96" y="194" transform="rotate(-3 96 194)">rue Nationale</text>
      <text class="m-label" x="600" y="320">rue Esquermoise</text><text class="m-label" x="340" y="452" transform="rotate(-6 340 452)">boulevard de la Liberté</text>
      <text class="m-label water" x="40" y="290">la Deûle</text><text class="m-label park" x="80" y="455">jardin Vauban</text>
      <circle class="m-acc" cx="${pos.x}" cy="${pos.y}" r="${pos.prec * 2.8}"/><circle class="m-pulse" cx="${pos.x}" cy="${pos.y}" r="12" style="transform-origin:${pos.x}px ${pos.y}px"/><circle class="m-dot" cx="${pos.x}" cy="${pos.y}" r="8"/>
    </svg>`;
  }
  function vuePosition() {
    const t = etat.tel === 'p7a' ? TELS[1] : TELS[0], pos = t.pos;
    return `<div class="split pos-split">
      <section class="pane map-pane">${carte(pos)}<div class="map-legend">${ico('pin', 'sm')}<b>${h(pos.lieu)}</b><span class="muted">à ${pos.prec} m près · ${h(pos.quand)} · ${h(t.court)}</span></div></section>
      <aside class="pane"><div class="pane-scroll pos-side">
        <h2 class="section-title">Ta dernière position</h2>
        <dl class="kv"><dt>Lieu</dt><dd><b>${h(pos.lieu)}</b></dd><dt>Précision</dt><dd>à ${pos.prec} m près</dd><dt>Position de</dt><dd>${h(pos.quand)}</dd>
          <dt>Coordonnées</dt><dd class="mono">${h(pos.coord)}</dd><dt>Envoyée par</dt><dd>${h(t.nom)}, application ouverte</dd></dl>
        <div class="pos-switch"><span class="switch"><input type="checkbox" checked disabled><i></i></span><div><b>Lui dire où je suis</b>
          <p class="small muted">Réglé sur le téléphone, coupé par défaut. Il ne parle de sa position que quand l'application est ouverte.</p></div></div>
        <h2 class="section-title">Quand Mika a regardé <span class="cnt">${REGARDS.length}</span></h2>
        <ul class="regards">${REGARDS.map((r) => `<li>${ico('eye', 'sm')}<div><b>${h(r.t)}</b> · ${h(r.lieu)}<span class="small muted">en te répondant ${h(r.pour)}</span></div></li>`).join('')}</ul>
        <p class="small muted">Elle ne regarde que quand vous vous parlez, jamais d'elle-même ; chaque regard laisse une bulle 📍 dans le chat.</p>
        <div class="row pos-actions"><button class="btn sm danger" type="button" data-oublier>${ico('trash', 'sm')}Oublier cette position</button></div>
      </div></aside></div>`;
  }

  function envoyer(sec) {
    const ta = sec.querySelector('[data-tel-input]');
    const c = CONV.find((x) => x.id === etat.conv);
    const txt = ta.value.trim();
    if (!txt) return;
    c.msgs.push({ moi: true, t: D.maintenant.heure, txt, etat: (etat.prerempli ? 'préremplie par Mika · ' : '') + `partie par ${telDe(c.tel).court}, dans ${APPS[c.app][2]}` });
    etat.prerempli = false;
    M.rafraichir();
    M.toast(`Partie vers ton téléphone : il l'envoie dans ${APPS[c.app][2]}.`, { ico: 'phone' });
  }

  M.register('telephone', {
    titre: 'Téléphone',
    onglets: [{ id: 'messages', titre: 'Messages', cnt: 7 }, { id: 'notifications', titre: 'Notifications' }, { id: 'position', titre: 'Position' }],
    compte: () => CONV.reduce((n, c) => n + (c.nonlus || 0), 0),
    actions: (ctx) => `${ctx.onglet === 'notifications' ? `<div class="seg" role="group">${[['toutes', 'Toutes'], ['messages', 'Messages'], ['autres', 'Autres']].map(([k, l]) => `<button type="button" data-filtre="${k}" aria-pressed="${etat.filtre === k}">${l}</button>`).join('')}</div>` : ''}
      <button class="phone-switch" type="button" data-tel-switch title="Changer de téléphone">${ico('phone', 'sm')}<b>${h(etat.tel === 'tous' ? 'Tous tes téléphones' : telDe(etat.tel).court)}</b>
        ${etat.tel === 'tous' ? `<span class="muted">${TELS.length}</span>` : `<span class="dot ${telDe(etat.tel).dot}"></span><span class="muted">${h(telDe(etat.tel).vu)}</span>`}${ico('chev-down', 'sm')}</button>
      <a class="btn icon ghost" href="#parametres/telephones" title="Régler le téléphone">${ico('settings')}</a>`,
    monte(sec) {
      M.on(sec, '[data-conv]', 'click', (e, b) => { etat.conv = b.dataset.conv; etat.prerempli = false; etat.mobileLecture = true; const c = CONV.find((x) => x.id === etat.conv); c.nonlus = 0; M.go('#telephone/messages/' + etat.conv); M.compter(); });
      M.on(sec, '[data-retour]', 'click', () => { etat.mobileLecture = false; M.rafraichir(); });
      M.on(sec, '[data-tel-switch]', 'click', (e, b) => M.menu(b, [{ entete: 'Tes téléphones' },
        { label: 'Tous tes téléphones', ico: 'phone', coche: etat.tel === 'tous', action: () => { etat.tel = 'tous'; M.rafraichir(); } },
        ...TELS.map((t) => ({ label: `${t.court} — ${t.vu}`, ico: 'phone', coche: etat.tel === t.id, action: () => { etat.tel = t.id; M.rafraichir(); } })),
        'sep', { label: 'Gérer tes téléphones', ico: 'settings', action: () => M.go('#parametres/telephones') }]));
      M.on(sec, '[data-envoyer]', 'click', () => envoyer(sec));
      M.on(sec, '[data-vider]', 'click', () => { etat.prerempli = false; M.rafraichir(); });
      M.on(sec, '[data-preremplir]', 'click', () => {
        const c = CONV.find((x) => x.id === etat.conv);
        M.mika.typing(true); M.mika.set({ etat: 'ecrit', fait: 'en train d\'écrire…' });
        setTimeout(() => { M.mika.typing(false); M.mika.set({ etat: 'eveillee', fait: 'travaille à son bureau' }); etat.prerempli = true; M.rafraichir(); M.mika.talk(900); const t = sec.querySelector('[data-tel-input]'); if (t) { t.focus(); t.style.height = t.scrollHeight + 'px'; } }, 1100);
      });
      sec.addEventListener('input', (e) => { if (e.target.matches('[data-cq]')) { etat.q = e.target.value; sec.querySelector('[data-convs]').innerHTML = liste(); } });
      M.on(sec, '[data-filtre]', 'click', (e, b) => { etat.filtre = b.dataset.filtre; M.rafraichir(); });
      M.on(sec, '[data-prop]', 'click', (e, b) => {
        const c = CONV.find((x) => x.id === etat.conv), m = c.msgs.find((x) => x.prop && x.prop.etat === 'attente');
        if (!m) return;
        if (!m) return;
        if (b.dataset.prop === 'retirer') { m.prop.etat = 'retiree'; M.rafraichir(); M.toast('Proposition retirée du téléphone.', { ico: 'x' }); }
        else if (b.dataset.prop === 'envoyer') { m.prop.etat = 'envoyee'; M.rafraichir(); M.toast(`Partie : ton téléphone l'envoie dans ${APPS[c.app][2]}.`, { ico: 'send' }); }
        else { m.prop.etat = 'retiree'; M.rafraichir(); const t = sec.querySelector('[data-tel-input]'); t.value = m.prop.txt; t.focus(); M.toast('Sa proposition est dans ta saisie : retouche-la, puis envoie.', { mika: true }); }
      });
      M.on(sec, '[data-oublier]', 'click', () => M.toast('Maquette : sa dernière position serait oubliée.', { ico: 'trash' }));
      M.on(sec, '[data-more]', 'click', (e, b) => M.menu(b, [{ label: 'Voir dans Notifications', ico: 'bell', action: () => M.go('#telephone/notifications') },
        { label: 'Ce que Mika en sait', ico: 'sparkle', action: () => M.go('#chat') }, 'sep', { label: 'Ne plus lui montrer cette conversation', ico: 'eye-off', danger: true }]));
      sec.addEventListener('keydown', (e) => { if (e.target.matches('[data-tel-input]') && e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); envoyer(sec); } });
    },
    rendu(body, ctx) {
      if (ctx.onglet === 'messages' && ctx.item && CONV.some((c) => c.id === ctx.item)) { etat.conv = ctx.item; CONV.find((c) => c.id === ctx.item).nonlus = 0; setTimeout(M.compter, 0); }
      body.innerHTML = ctx.onglet === 'notifications' ? vueNotifs() : ctx.onglet === 'position' ? vuePosition() : vueMessages();
      const s = body.querySelector('[data-scroll]'); if (s) s.scrollTop = s.scrollHeight;
    },
    recherche: () => CONV.map((c) => ({ groupe: 'Téléphone', titre: c.titre, sous: `${APPS[c.app][2]} · ${c.msgs.filter((m) => m.txt).slice(-1)[0].txt}`, ico: 'phone', route: '#telephone/messages/' + c.id })),
    notes: () => [
      { groupe: 'Décidé', statut: 'decide', titre: 'Un envoi depuis le web vaut le geste', texte: 'ta réponse, ou sa proposition, part d\'ici sans geste sur le téléphone : une ADR qui révise 0120 et le plancher de 0133' },
      { statut: 'decide', titre: 'Toutes les apps, au choix', texte: 'élargir l\'ADR 0120 au-delà de WhatsApp et Messages, app par app ; jamais la banque ni les codes' },
      { statut: 'decide', titre: 'Plusieurs téléphones', texte: 'on passe de l\'un à l\'autre, ou on les voit tous' },
      { groupe: 'Ce qui marche déjà', statut: 'existe', titre: 'Le téléphone lui montre ses messages', texte: 'si « Lui montrer mes messages » est allumé (coupé par défaut) : quatre apps en MessagingStyle, WhatsApp, WhatsApp Business, Messages de Google et de Samsung ; les groupes si tu le coches ; au journal (phone.received), les 500 derniers', src: 'ADR 0120 · data/phone/PhoneApp.kt:11-16 · /api/phone/inbox' },
      { statut: 'existe', titre: 'Elle lit et propose', texte: 'phone_messages, phone_draft ; la proposition part par Firebase à chaque téléphone du compte ; le geste « Envoyer » vaut accord ; elle expire en 2 h', src: 'plugins/phone/__init__.py:320-433 · /api/phone/settled' },
      { statut: 'existe', titre: 'Ta position', texte: 'trame where (application ouverte, coupé par défaut) ; la tranche garde la dernière, le journal garde tout l\'historique ; location_where et la bulle 📍', src: 'ADR 0119 · plugins/location/__init__.py:39-100' },
      { groupe: 'À faire ou à décider', statut: 'manque', titre: 'Tes messages et ta position dans le web', texte: 'aucune route : la console seulement, pour un opérateur' },
      { statut: 'manque', titre: 'Répondre toi-même d\'ici', texte: 'le plancher de l\'ADR 0133 : « ce que le téléphone envoie, c\'est toujours ton geste » ; soit le web prépare et le téléphone demande le geste, soit une ADR fait valoir l\'envoi web comme geste' },
      { statut: 'manque', titre: '« Préremplir avec Mika » d\'ici', texte: 'aujourd\'hui elle ne prépare qu\'en conversation avec toi, dans le chat ; le web ne connaît pas la référence d\'un message' },
      { statut: 'manque', titre: 'Suivre, retirer ou modifier une proposition', texte: 'ni route ni trame pour ses propositions et leur sort ; seuls l\'échéance et le geste existent' },
      { statut: 'partiel', titre: 'À décider : les autres apps', texte: 'Colissimo, Agenda, Strava ne sont pas lues aujourd\'hui : c\'est élargir l\'ADR 0120 (et lire des notifications sans MessagingStyle)' },
      { statut: 'manque', titre: '« Jamais les codes »', texte: 'aucun filtre de contenu : un SMS de code part aujourd\'hui avec Messages' },
      { statut: 'partiel', titre: 'Tes propres messages', texte: 'ceux que la notification contient partent (own) ; ce que tu tapes dans WhatsApp lui-même, non' },
      { statut: 'manque', titre: 'Quel téléphone', texte: 'un seul moyen de communication par compte : le serveur ne sait pas quel téléphone a envoyé quoi ; une proposition part à tous les téléphones du compte' },
      { statut: 'manque', titre: 'Lu et non lu', texte: 'aucun état de lecture côté serveur' },
      { statut: 'partiel', titre: '« Oublier cette position »', texte: 'where off n\'efface que la dernière ; le journal garde les coordonnées et les lieux' },
    ],
  });
})();
