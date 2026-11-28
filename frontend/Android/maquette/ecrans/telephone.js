/* Téléphone : ce que ce téléphone montre à Mika (ses messages WhatsApp et SMS, ADR 0120), ses réponses proposées
   et sa dernière position (ADR 0119). Sur Android, la réponse part d'ici même : le geste « Envoyer » vaut accord, et
   passe par l'action « Répondre » de la notification de WhatsApp ou de Messages tant qu'elle est là. */
(function () {
  const { h, ico, av, who } = A;

  const CONV = [
    { id: 'julien', qui: 'julien', app: 'whatsapp', titre: 'Julien Roux', nonlus: 2, t: '14:09', dernier: 'départ 8h30 du parking de la gare', msgs: [
      { jour: 'Hier' }, { de: 'julien', t: '19:02', txt: 'on fait la boucle des Monts dimanche avec thomas et camille, t\'es chaud ?' },
      { jour: 'Aujourd\'hui' }, { de: 'julien', t: '14:08', txt: 'alors dimanche, tu viens ?' }, { de: 'julien', t: '14:09', txt: 'départ 8h30 du parking de la gare' },
      { note: 'Mika a lu ces messages et t\'en a parlé dans le chat, à 14:12' }] },
    { id: 'rando', groupe: true, membres: ['thomas', 'julien', 'camille'], app: 'whatsapp', titre: 'Rando dimanche 🥾', nonlus: 5, t: '13:47', dernier: 'Thomas : on décale à 9h ?', prop: true, msgs: [
      { jour: 'Aujourd\'hui' }, { de: 'thomas', t: '11:20', txt: 'Je propose la boucle des Monts : 14 km, 300 m de dénivelé' }, { de: 'camille', t: '11:24', txt: 'grave partante !' },
      { de: 'julien', t: '12:02', txt: 'je peux prendre 3 personnes dans la voiture' }, { de: 'thomas', t: '13:45', txt: 'Météo : averses le matin' }, { de: 'thomas', t: '13:47', txt: 'on décale à 9h ?' },
      { prop: { txt: '9h ça me va 👍 je prends ma voiture aussi si besoin', exp: 'expire dans 1 h 52', t: '13:58' } }] },
    { id: 'maman', qui: 'maman', app: 'sms', titre: 'Maman', t: '12:40', dernier: 'Toi : Je viens après la rando, vers 13h30 !', msgs: [
      { jour: 'Aujourd\'hui' }, { de: 'maman', t: '12:31', txt: 'Tu passes dimanche midi ? Je fais un rôti' }, { moi: true, t: '12:40', txt: 'Je viens après la rando, vers 13h30 !' }] },
    { id: 'lea', qui: 'lea', app: 'whatsapp', titre: 'Léa', t: '11:02', dernier: 'tu as reçu mon colis ? c\'est pour l\'anniv de papa', msgs: [
      { jour: 'Aujourd\'hui' }, { de: 'lea', t: '11:02', txt: 'tu as reçu mon colis ? c\'est pour l\'anniv de papa, ne l\'ouvre pas 🙃' }] },
    { id: 'garage', qui: 'garage', app: 'sms', titre: 'Garage Martin', t: '10:15', dernier: 'votre véhicule est prêt. Vous pouvez le récupérer à partir de 17h.', msgs: [
      { jour: 'Aujourd\'hui' }, { de: 'garage', t: '10:15', txt: 'Bonjour M. Moreau, votre véhicule est prêt. Vous pouvez le récupérer à partir de 17h. Garage Martin' }] },
  ];
  const conv = (id) => CONV.find((c) => c.id === id) || CONV[0];
  const tete = (c) => (c.groupe ? `<span class="av grp">${ico('users', 'sm')}<i class="app-b ${c.app}">${c.app === 'whatsapp' ? 'W' : 'M'}</i></span>` : av(c.qui, '', c.app));
  const ONGLETS = [['#telephone', 'Messages', 5], ['#telephone/position', 'Position']];
  const haut = (cur) => `${A.top({ racine: true, back: A.v.nav === 'barre', title: 'Téléphone', sub: `Ce téléphone · samsung SM-S931B ${ico('chev-down', 'xxs')}`, titleAttrs: 'data-sheet="telephones"', small: true })}${A.tabs(ONGLETS, cur)}`;

  function vueMessages() {
    return {
      nav: A.v.nav === 'barre' ? 'plus' : 'telephone', racine: true, back: '#plus',
      html: `${haut('#telephone')}
        <div class="body">
          <div style="padding:10px 16px 4px"><button class="mk-line" type="button" data-go="#telephone/c/rando">${ico('sparkle')}<span class="grow"><b>Mika propose une réponse</b><small>Rando dimanche 🥾 · « 9h ça me va 👍… » · expire dans 1 h 52</small></span><span class="cnt-pill mk">1</span></button></div>
          ${CONV.map((c) => `<button class="li${c.nonlus ? ' unread' : ''}" type="button" data-go="#telephone/c/${c.id}">${tete(c)}<span class="txt"><b>${h(c.titre)}</b><small>${c.prop ? `<span class="mk-txt">${ico('sparkle', 'xxs')} réponse proposée · </span>` : ''}${h(c.dernier)}</small></span>
            <span class="trail"><span class="t">${h(c.t)}</span>${c.nonlus ? `<span class="cnt-pill">${c.nonlus}</span>` : ''}</span></button>`).join('')}
          <p class="note">Ce que WhatsApp et Messages affichent sur ce téléphone, et seulement les applis cochées dans Paramètres › Ce téléphone › Ses messages. Mika s'en souvient.</p>
        </div>`,
      notes: {
        titre: 'Téléphone · Messages',
        reprend: ['L\'écran Téléphone du client web : les conversations que l\'app a lues, leurs fils, ses propositions et leur sort.', 'Le sélecteur en titre passe d\'un téléphone à l\'autre (le Pixel 7a), « Ce téléphone » d\'abord.',
          'Ici sous « Plus » (la barre du bas n\'a que cinq cases) ; dans la variante « Tiroir », c\'est une rubrique comme les autres.'],
        trancher: ['« Téléphone » sous « Plus », ou à la place de Carte dans la barre du bas ?', 'Le nom : « Téléphone » (comme le web), ou « Ses messages » / « Messages du téléphone » sur un téléphone ?'],
      },
    };
  }

  function vueConv(id) {
    const c = conv(id);
    const sous = c.groupe ? `WhatsApp · ${c.membres.map((k) => who(k).court).join(', ')}` : c.app === 'whatsapp' ? 'WhatsApp' : 'Messages · SMS';
    const msgs = c.msgs.map((m) => {
      if (m.jour) return `<div class="day">${h(m.jour)}</div>`;
      if (m.note) return `<button class="msg-note" type="button" data-go="#chat" style="align-self:center;margin:6px 0">${ico('eye')}${h(m.note)}</button>`;
      if (m.prop) return `<div class="prop"><div class="over">${ico('sparkle', 'xs')}Mika propose de répondre · ${h(m.prop.t)}</div><q>${h(m.prop.txt)}</q><small class="muted">${h(m.prop.exp)} · part par WhatsApp, sous ton nom</small>
        <div class="btns"><button class="btn text sm" type="button" data-snack="Ignorée">Ignorer</button><button class="btn outlined sm" type="button" data-snack="Le texte est dans le champ">Écrire autre chose</button><button class="btn mk filled sm" type="button" data-snack="Parti par WhatsApp">${ico('send')}Envoyer</button></div></div>`;
      if (m.moi) return `<div class="tmsg me"><div><div class="bubble">${h(m.txt)}</div><div class="meta" style="justify-content:flex-end">${h(m.t)}</div></div></div>`;
      return `<div class="tmsg">${av(m.de, 'sm')}<div>${c.groupe ? `<div class="who">${h(who(m.de).court)} · ${h(m.t)}</div>` : ''}<div class="bubble them">${h(m.txt)}</div>${c.groupe ? '' : `<div class="meta">${h(m.t)}</div>`}</div></div>`;
    }).join('');
    return {
      nav: A.v.nav === 'barre' ? 'plus' : 'telephone', back: '#telephone',
      html: `${A.top({ title: h(c.titre), sub: h(sous), small: true, back: true, actions: [A.act('more', 'Plus', 'data-menu="conv"')] })}
        <div class="thread plain" data-bottom><div class="spacer"></div>${msgs}</div>
        <div class="composer plain">${A.act('sparkle', 'Préremplir avec Mika', 'data-snack="Mika préremplit…"', 'mk')}
          <div class="cf"><input type="text" placeholder="Répondre par ${c.app === 'whatsapp' ? 'WhatsApp' : 'SMS'}" aria-label="Réponse"></div>
          <button class="ibtn filled" type="button" disabled aria-label="Envoyer">${ico('send', 'sm')}</button><span class="cap">part par la notification de ${c.app === 'whatsapp' ? 'WhatsApp' : 'Messages'}, tant qu'elle est là</span></div>`,
      notes: {
        titre: 'Téléphone · une conversation',
        reprend: ['Le fil lu sur le téléphone ; sa proposition en carte rose dans le fil : Ignorer, Écrire autre chose, Envoyer.', 'Nouveau sur Android : répondre d\'ici marche (le web ne le peut pas, ADR 0189), par l\'action « Répondre » de la notification gardée en mémoire.',
          'Sinon (notification balayée), le texte est copié et WhatsApp s\'ouvre pour le coller.', '⋮ : Lui en parler dans le chat, Ouvrir dans WhatsApp.'],
        trancher: ['Sa proposition dans le fil (comme ici), ou en carte au-dessus du champ comme dans Teams ?'],
      },
    };
  }

  function vuePosition() {
    const at = [3.0583, 50.6365];
    return {
      nav: A.v.nav === 'barre' ? 'plus' : 'telephone', racine: true, back: '#plus',
      html: `${haut('#telephone/position')}
        <div class="mapwrap" style="flex:none;height:300px">${A.cartePosition ? A.cartePosition(at, 384, 300) : ''}<div class="cm-attrib" style="bottom:6px">© OpenStreetMap · plan dessiné</div></div>
        <div class="body"><div class="cards">
          <div class="card"><div class="over">Sa dernière position</div><h3>rue Nationale, Lille</h3><p class="muted">±12 m · mesurée à 14:10 · 50.636512, 3.058271</p>
            <p class="mk-txt row" style="margin-top:8px;font-size:13px">${ico('eye', 'xs')}Mika l'a regardée à 14:12, pendant votre conversation</p></div>
          <div class="card out"><div class="set-row" style="padding:0"><span class="txt"><b>Lui dire où je suis</b><small>Application ouverte seulement. Couper efface ta position chez elle.</small></span>${A.sw(true)}</div></div>
          <button class="btn text" type="button" data-go="#carte" style="justify-self:start">${ico('map')}Ouvrir dans Carte</button>
        </div></div>`,
      notes: { titre: 'Téléphone · Position', reprend: ['Sa dernière position sur la carte (le point et le cercle de sa précision), quand elle l\'a regardée.', 'L\'interrupteur « Lui dire où je suis » ici aussi, en plus de Paramètres (ADR 0119).'], trancher: ['L\'interrupteur ici ET dans Paramètres, ou seulement dans Paramètres ?'] },
    };
  }

  A.ecran('telephone', (args) => (args[0] === 'c' ? vueConv(args[1]) : args[0] === 'position' ? vuePosition() : vueMessages()));
  A.sheets.telephones = () => A.sheet('Ses téléphones', `<button class="li sel" type="button" data-close><span class="lead box">${ico('phone')}</span><span class="txt"><b>Ce téléphone</b><small>samsung SM-S931B · vu maintenant</small></span>${ico('check', 'sm')}</button>
    <button class="li" type="button" data-close data-snack="Google Pixel 7a"><span class="lead box">${ico('phone')}</span><span class="txt"><b>Google Pixel 7a</b><small>vu hier à 22:10</small></span></button>
    <button class="li" type="button" data-go="#parametres/telephones"><span class="lead box">${ico('settings')}</span><span class="txt"><b>Régler les téléphones</b><small>Paramètres › Téléphones</small></span></button>`);
  A.menus.conv = () => [{ ico: 'chat', l: 'Lui en parler dans le chat', go: '#chat' }, { ico: 'external', l: 'Ouvrir dans WhatsApp', snack: 'Maquette : WhatsApp s\'ouvre' }];
  A.index('Téléphone', [['Messages', '#telephone'], ['Julien', '#telephone/c/julien'], ['Sa proposition', '#telephone/c/rando'], ['Position', '#telephone/position']]);
})();
