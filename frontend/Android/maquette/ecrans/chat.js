/* Le chat : la conversation d'aujourd'hui (Mika en fond, ses bulles dans la bande du bas, ses cartes d'accord
   au-dessus du champ), avec ce que le frontendv2 y a ajouté : ses notes qui mènent à Mail, Teams, Téléphone et Carte,
   les brouillons à relire repliés sur une ligne, la recherche, les fichiers échangés. Le mode pro et ses fils.
   « Ce qu'elle fait » est ici aussi : c'est son visage qui l'ouvre, partout. */
(function () {
  const { h, ico, av, D } = A;

  // ── La conversation (celle de la maquette du frontendv2, routes d'Android) ──
  const conversation = [
    { jour: 'Hier' },
    { de: 'moi', t: '21:38', lu: true, txt: 'qu\'il recommence pas' },
    { de: 'mika', t: '21:40', bulles: ['alors ce mail le fera pas. envoyé à 21h, sur ce ton, il va y lire de la colère, pas une limite', 'demande-lui dix minutes demain, en tête-à-tête. tu lui dis la même chose, plus calmement'] },
    { de: 'moi', t: '21:41', lu: true, txt: 't\'es chiante quand t\'as raison' },
    { de: 'mika', t: '21:41', bulles: ['je sais. garde le brouillon quand même, il est bien écrit'] },
    { jour: 'Aujourd\'hui' },
    { de: 'moi', t: '08:12', lu: true, txt: 'hello ça va ?' },
    { de: 'mika', t: '08:14', bulles: ['salut. ça va, un peu ailleurs', 'j\'ai passé une partie de la nuit sur des études sur les corneilles. elles reconnaissent le visage de quelqu\'un qui leur a fait du mal'] },
    { de: 'moi', t: '13:52', lu: true, txt: 'tu peux regarder le mail de claire sur la présentation ? je sais pas trop quoi lui répondre' },
    { de: 'mika', t: '13:54', note: { ico: 'mail', txt: 'Mika a lu « Re: Présentation de jeudi » de Claire Dubois', go: '#mail/lire/m-claire' },
      bulles: ['je l\'ai lu. elle critique pas le fond, elle dit juste que la partie budget arrive trop tard', 'je t\'ai mis une réponse courte dans tes brouillons. tu me diras si le ton te va'],
      lien: { ico: 'pen', titre: 'Brouillon · Re: Présentation de jeudi', sous: 'Boîte Pro · à Claire Dubois', go: '#mail/brouillon/m-brouillon-claire' } },
    { de: 'moi', t: '14:05', lu: true, txt: 'parfait merci, je regarde', fichier: { image: true, nom: 'tableau-blanc.jpg', taille: '1,8 Mo' } },
    { de: 'mika', t: '14:06', bulles: ['joli tableau. c\'est toi qui as fait le schéma du milieu ?'] },
    { de: 'mika', t: '14:12', note: { ico: 'pin', txt: 'Mika a regardé où tu es · rue Nationale, Lille · position de 14:10' },
      bulles: ['au fait, Julien t\'a écrit sur WhatsApp pour la rando de dimanche. il attend juste un oui ou un non'],
      lien: { ico: 'phone', titre: 'Julien Roux · WhatsApp', sous: '« alors dimanche, tu viens ? départ 8h30 »', go: '#telephone/c/julien' } },
    { de: 'moi', t: '14:15', lu: true, txt: 'tu m\'aides pour le road trip dans les Alpes ? cinq jours début avril, départ de Lille, j\'aimerais finir à Nice' },
    { de: 'mika', t: '14:18', note: { ico: 'search', txt: 'Mika a cherché des campings autour du lac d\'Annecy et calculé le trajet', go: '#carte' },
      bulles: ['je t\'ai fait une première version : Dijon le premier soir, deux nuits au bord du lac d\'Annecy, puis le Verdon avant Nice', 'j\'ai ajouté quatre arrêts, en rose. retire ce qui te plaît pas'],
      carte: { voyage: 'alpes', titre: 'Voyage · Les Alpes en cinq jours', sous: '5 jours · 1 388 km · 4 arrêts de Mika', go: '#carte/voyage/alpes' }, juger: true },
  ];

  const fils = [
    { id: 'devis', titre: 'Devis Lefèvre — vérifier les montants', desc: 'Comparer le devis reçu ce matin au budget du projet Lumen, ligne par ligne.', t: '13:31', n: 6 },
    { id: 'nas', titre: 'Script de sauvegarde du NAS', desc: 'Un rsync nocturne vers le disque externe, avec un rapport par mail.', t: 'hier', n: 14 },
    { id: 'revue', titre: 'Préparer la revue de jeudi', desc: 'Points d\'avancement à partir des mails et de Teams de la semaine.', t: 'lun.', n: 9 },
    { id: 'mariadb', titre: 'Migration MariaDB du portable', desc: '', t: '28 oct.', n: 22, archive: true },
    { id: 'factures', titre: 'Factures d\'octobre', desc: '', t: '19 oct.', n: 5, archive: true },
  ];
  const outilsDevis = [
    { nom: 'forge_db_query', arg: 'app « Devis » · budget du projet Lumen', ok: true, d: '410 ms' },
    { nom: 'forge_db_query', arg: 'devis × budget, par poste', ok: false, d: '290 ms' },
    { nom: 'forge_db_query', arg: 'devis × budget, par poste, sans quantités', ok: true, d: '640 ms' },
  ];
  const pro = [
    { de: 'moi', t: '13:31', txt: 'compare ce devis de Lefèvre Rénovation avec le budget du projet, ligne par ligne', fichier: { nom: 'devis-2026-114.pdf', taille: '212 Ko' } },
    { de: 'outils', liste: outilsDevis, duree: '1,3 s' },
    { de: 'pro', t: '13:32', html: `<p>Le devis dépasse le budget de <strong>1 240 €</strong> (+8 %). Trois postes expliquent l'écart :</p>
      <table><thead><tr><th>Poste</th><th class="r">Budget</th><th class="r">Devis</th><th class="r">Écart</th></tr></thead><tbody>
      <tr><td>Main-d'œuvre</td><td class="r">9 000 €</td><td class="r">9 860 €</td><td class="r up">+860 €</td></tr>
      <tr><td>Sol</td><td class="r">2 400 €</td><td class="r">2 690 €</td><td class="r up">+290 €</td></tr>
      <tr><td>Éclairage</td><td class="r">1 300 €</td><td class="r">1 390 €</td><td class="r up">+90 €</td></tr>
      </tbody></table><p>La main-d'œuvre est le seul poste sans quantité : demande le détail des heures avant de discuter le prix.</p>` },
    { de: 'moi', t: '13:35', txt: 'ok, écris à Lefèvre pour demander le détail' },
    { de: 'outils', liste: [{ nom: 'email_contacts', arg: 'Lefèvre Rénovation', ok: true, d: '210 ms' }, { nom: 'email_draft', arg: 'boîte Pro → devis@lefevre-renovation.fr', ok: true, d: '2,4 s' }], duree: '2,6 s' },
    { de: 'pro', t: '13:36', html: '<p>Brouillon prêt dans ta boîte Pro, il attend ton accord. J\'ai laissé la <strong>date de début</strong> à compléter : je ne la connais pas.</p>',
      lien: { ico: 'pen', titre: 'Brouillon · Re: Devis n° 2026-114', sous: 'Boîte Pro · à compléter', go: '#mail/brouillon/d-lefevre' } },
    { de: 'moi', t: '14:02', txt: 'et pousse la nouvelle page du site de la rando' },
    { de: 'outils', liste: [{ nom: 'project_push', arg: 'Site de l\'association · 3 commits', run: true }], enCours: true },
  ];

  // ── Les pièces ────────────────────────────────────────────────────────
  const texte = (s) => h(s);
  function bulleMoi(m) {
    const f = m.fichier ? (m.fichier.image
      ? `<div class="msg-file img"><div class="ph">${ico('image')}</div><small>${h(m.fichier.nom)} · ${h(m.fichier.taille)}</small></div>`
      : `<div class="msg-file">${ico('file')}<span><b style="font-weight:500;font-size:13.5px">${h(m.fichier.nom)}</b><small class="muted" style="display:block;font-size:12px">${h(m.fichier.taille)}</small></span></div>`) : '';
    return `<div class="msg me">${f}<div class="bubble">${texte(m.txt)}</div><div class="meta">${h(m.t)} ${ico(m.lu ? 'checks' : 'check')}</div></div>`;
  }
  function bulleMika(m) {
    const note = m.note ? `<button class="msg-note" type="button" ${m.note.go ? `data-go="${m.note.go}"` : ''}>${ico(m.note.ico)}${h(m.note.txt)}</button>` : '';
    const bulles = (m.bulles || []).map((b) => `<div class="bubble">${texte(b)}</div>`).join('');
    const lien = m.lien ? `<button class="msg-link" type="button" data-go="${m.lien.go}">${ico(m.lien.ico)}<span class="grow"><b>${h(m.lien.titre)}</b><small>${h(m.lien.sous)}</small></span>${ico('chev-right', 'sm')}</button>` : '';
    const carte = m.carte ? `<button class="msg-map" type="button" data-go="${m.carte.go}">${A.carteMini ? A.carteMini(m.carte.voyage) : ''}
      <span class="mm-t">${ico('map')}<span class="grow"><b>${h(m.carte.titre)}</b><small>${h(m.carte.sous)}</small></span>${ico('chev-right', 'sm')}</span></button>` : '';
    const juger = m.juger && D.moi.operatrice ? `<div class="verdict"><button type="button" data-snack="👍 gardé : il sert au banc">${ico('thumb-up')}</button><button type="button" data-dialog="pourquoi">${ico('thumb-down')}</button></div>` : '';
    return `<div class="msg her">${note}${bulles}${lien}${carte}<div class="row">${juger}<span class="meta">${h(m.t)}</span></div></div>`;
  }
  function outils(m) {
    const rows = m.liste.map((o) => `<div class="tc-row"><span class="st ${o.run ? 'run' : o.ok ? 'ok' : 'ko'}">${o.run ? '…' : o.ok ? '✓' : '✗'}</span><span class="mono grow ellipsis">${h(o.nom)}</span><span class="muted ellipsis" style="max-width:45%">${h(o.arg)}</span><span class="muted num">${h(o.d || '')}</span></div>`).join('');
    return `<div class="msg her"><div class="tools-card" data-foldroot><button class="tc-h" type="button" data-fold=".tc-rows">${ico('terminal', 'sm')}<span class="grow">${m.enCours ? 'Elle travaille… 1 outil en cours' : `${m.liste.length} outils · ${m.duree}`}</span><svg class="ico sm"><use class="fold-ico" href="#i-chev-${m.enCours ? 'up' : 'down'}"/></svg></button><div class="tc-rows"${m.enCours ? '' : ' hidden'}>${rows}</div></div></div>`;
  }
  function reponsePro(m) {
    const lien = m.lien ? `<button class="msg-link" type="button" data-go="${m.lien.go}" style="width:100%">${ico(m.lien.ico)}<span class="grow"><b>${h(m.lien.titre)}</b><small>${h(m.lien.sous)}</small></span>${ico('chev-right', 'sm')}</button>` : '';
    return `<div class="msg her"><div class="pro-answer">${m.html}</div>${lien}<div class="row"><div class="verdict"><button type="button" data-snack="👍 gardé">${ico('thumb-up')}</button><button type="button" data-dialog="pourquoi">${ico('thumb-down')}</button></div><span class="meta">${h(m.t)}</span></div></div>`;
  }
  const fil = (list) => list.map((m) => m.jour ? `<div class="day">${h(m.jour)}</div>` : m.de === 'moi' ? bulleMoi(m) : m.de === 'outils' ? outils(m) : m.de === 'pro' ? reponsePro(m) : bulleMika(m)).join('');

  function chatTop(estPro) {
    const lead = A.v.nav === 'tiroir' ? `<button class="ibtn" type="button" data-drawer aria-label="Menu">${ico('menu')}</button>` : '';
    return `<header class="top${estPro ? '' : ' clear'}">${lead}
      <button class="mika-head" type="button" data-go="#mika" aria-label="Ce qu'elle fait">${A.faceDot(40)}<span class="mh-text"><b>Mika</b><small>${h(D.mika.fait)}</small></span></button>
      ${A.act('search', 'Rechercher dans la conversation', 'data-go="#recherche/chat"')}${A.act('more', 'Plus d\'options', `data-menu="${estPro ? 'chat-pro' : 'chat'}"`)}</header>`;
  }
  function tray(estPro, ouvert) {
    if (estPro) {
      return `<div class="tray"><div class="tray-head"><span>2 accords attendent</span><button class="btn text sm" type="button" data-snack="Les 2 accords sont partis">Tout accepter</button></div>
        <div class="approval"><div class="ap-h">${ico('shield')}<span class="grow"><b>Pousser le dépôt « Site de l'association »</b></span></div>
          <pre>git push origin main · 3 commits\ngithub.com/rando-cassel/site</pre>
          <div class="ap-foot"><small>project_push · expire dans 9 min</small><button class="btn text sm" type="button" data-snack="Refusé : rien ne partira.">Refuser</button><button class="btn filled sm" type="button" data-snack="Accepté : c'est parti.">Accepter</button></div></div>
        <div class="approval"><div class="ap-h">${ico('shield')}<span class="grow"><b>Lire la base de l'app « Factures »</b></span></div>
          <pre>forge_db_query · factures d'octobre, par client</pre>
          <div class="ap-foot"><small>expire dans 12 min</small><button class="btn text sm" type="button" data-snack="Refusé : rien ne partira.">Refuser</button><button class="btn filled sm" type="button" data-snack="Accepté">Accepter</button></div></div></div>`;
    }
    // Replié par défaut sur une ligne (l'accord qui expire se compte dessus) ; toucher la ligne déplie la carte d'accord
    // et les brouillons à relire.
    return `<div class="tray" data-foldroot>
      <button class="tray-fold" type="button" data-fold=".tray-open">${ico('shield', 'sm')}<span class="grow ellipsis"><b>1 accord</b> · 2 brouillons à relire</span><span class="tag warn">4 min</span><svg class="ico sm"><use class="fold-ico" href="#i-chev-${ouvert ? 'up' : 'down'}"/></svg></button>
      <div class="tray-open" style="display:grid;gap:8px"${ouvert ? '' : ' hidden'}>
      <div class="approval"><div class="ap-h">${ico('shield')}<span class="grow"><b>Demander la météo de dimanche à Météo Locale</b></span></div>
        <pre>lieu : Mont des Cats (59) · jour : dimanche 8 novembre</pre>
        <div class="ap-foot"><small>expire dans 4 min</small><button class="btn text sm" type="button" data-snack="Refusé : rien ne partira.">Refuser</button><button class="btn filled sm" type="button" data-snack="Accepté : la demande est partie.">Accepter</button></div></div>
      <div class="tray-links">
        <a href="#mail/brouillon/m-brouillon-claire" data-go="#mail/brouillon/m-brouillon-claire">${ico('mail', 'sm')}<span class="grow ellipsis"><b>Mail</b> · Re: Présentation de jeudi → Claire</span>${ico('chev-right', 'xs')}</a>
        <a href="#teams/d/claire" data-go="#teams/d/claire">${ico('teams', 'sm')}<span class="grow ellipsis"><b>Teams</b> · Claire · « Oui je l'ai vu, merci ! »</span>${ico('chev-right', 'xs')}</a>
      </div></div>
    </div>`;
  }
  function composer(estPro) {
    return `<div class="composer">
      ${A.act('plus', 'Joindre', 'data-sheet="joindre"')}
      <div class="cf">${D.moi.operatrice ? `<button class="pro-chip${estPro ? ' on' : ''}" type="button" data-go="${estPro ? '#chat' : '#chat/pro'}" title="Mode pro">${ico('terminal')}Pro</button>` : ''}
        <input type="text" data-input placeholder="${estPro ? 'Demande-lui un travail…' : 'Écris à Mika…'}" aria-label="Message"></div>
      <button class="ibtn filled" type="button" data-send disabled aria-label="Envoyer">${ico('send', 'sm')}</button></div>`;
  }
  function strandBar() {
    const f = fils[0];
    return `<div class="strand-bar"><button class="sb-title" type="button" data-dialog="fil"><b>${h(f.titre)}</b><small>${h(f.desc)}</small></button>
      <button class="btn text sm" type="button" data-sheet="fils">${ico('threads')}Fils</button>
      <button class="btn tonal sm" type="button" data-snack="Un fil neuf est ouvert">${ico('plus')}Nouveau</button></div>`;
  }
  function bindComposer(root) {
    const input = root.querySelector('[data-input]'), send = root.querySelector('[data-send]'), thread = root.querySelector('.thread');
    if (!input) return;
    input.addEventListener('input', () => { send.disabled = !input.value.trim(); });
    const envoyer = () => {
      const t = input.value.trim();
      if (!t) return;
      thread.insertAdjacentHTML('beforeend', bulleMoi({ t: '14:20', txt: t }) + '<div class="msg her"><span class="typing"><i></i><i></i><i></i></span></div>');
      thread.scrollTop = thread.scrollHeight;
      input.value = '';
      send.disabled = true;
    };
    send.addEventListener('click', envoyer);
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') envoyer(); });
  }

  A.ecran('chat', (args) => {
    const estPro = args[0] === 'pro', ouvert = args[0] === 'accord';
    return {
      nav: 'chat', racine: true, cls: estPro ? 'chat pro' : 'chat',
      html: `${estPro ? '' : A.stage()}${chatTop(estPro)}${estPro ? strandBar() : ''}
        <div class="thread${estPro ? ' plain' : ''}" data-bottom><div class="spacer"></div>${fil(estPro ? pro : conversation)}</div>
        ${tray(estPro, ouvert)}${composer(estPro)}`,
      after: bindComposer,
      notes: estPro ? {
        titre: 'Chat · mode pro',
        reprend: ['La pastille « Pro » du champ allume le mode pro : Mika quitte le fond, ses réponses prennent toute la largeur (comme aujourd\'hui).',
          'La barre du fil sous la barre du haut : toucher le titre le règle, « Fils » ouvre la liste, « Nouveau » un fil neuf (ADR 0164).',
          'Ses outils en direct, repliables ; sa réponse en Markdown (tableaux) ; un lien vers son brouillon dans Mail.',
          'Plusieurs accords : « Tout accepter » au-dessus des cartes (opératrice, ADR 0170, comme le frontendv2).'],
        trancher: ['La barre du bas reste-t-elle en mode pro, ou le mode pro prend-il tout l\'écran (on en sort par la pastille) ?',
          '« Fils » et « Nouveau » sous la barre du haut (comme aujourd\'hui), ou dans le menu ⋮ pour gagner une ligne ?'],
      } : {
        titre: 'Chat',
        reprend: ['L\'écran d\'aujourd\'hui : Mika en fond (sa 3D), ses bulles dans la bande du bas, la barre de saisie, ses cartes d\'accord au-dessus.',
          'Du frontendv2 : ses notes (« Mika a lu… », 📍, sa recherche) mènent à l\'écran qui va ; le lien vers son brouillon ; sa carte de voyage en miniature.',
          'Au-dessus du champ, une seule ligne rose : « 1 accord · 2 brouillons à relire », le compte à rebours de l\'accord dessus. Touchée, elle déplie la carte d\'accord (exactement ce qui partira) et les liens vers ses brouillons, qui se décident dans Mail et Teams.',
          'En haut à droite : la recherche (messages, puis partout) et ⋮ (Ce qu\'elle fait, Fichiers échangés, Paramètres).'],
        trancher: ['La barre du bas sous le champ prend 64 dp à Mika. Elle reste là, ou le chat passe en plein écran (variante « Tiroir » du panneau) ?',
          'Les accords repliés sur une ligne (Mika reste visible), ou toujours dépliés comme aujourd\'hui (plus sûr pour un accord qui expire, mais le fil n\'a plus que deux bulles) ? Voir « Accords dépliés ».',
          'La loupe en haut cherche d\'abord dans la conversation : d\'accord, ou la recherche partout seulement depuis « Plus » ?'],
      },
    };
  });

  // ── Les feuilles et menus du chat ─────────────────────────────────────
  A.sheets.joindre = () => A.sheet('Joindre', [['image', 'Photos', 'jusqu\'à 5 fichiers de 5 Mo'], ['camera', 'Appareil photo', 'réduite en JPEG, sans EXIF ni GPS'], ['file', 'Fichier', 'images, audio, texte, CSV, Markdown, JSON, PDF']]
    .map(([i, l, s]) => `<button class="li" type="button" data-close data-snack="Maquette : ${l.toLowerCase()}"><span class="lead box">${ico(i)}</span><span class="txt"><b>${l}</b><small>${s}</small></span></button>`).join(''));
  A.sheets.fils = () => {
    const ligne = (f) => `<button class="li${f.id === 'devis' ? ' sel' : ''}" type="button" data-close data-snack="Fil « ${h(f.titre)} » ouvert"><span class="lead box">${ico('threads')}</span><span class="txt"><b>${h(f.titre)}</b><small>${h(f.desc || 'sans description')}</small></span><span class="trail"><span>${h(f.t)}</span><span>${f.n} msg</span></span></button>`;
    A.sheet('Fils de travail', `${fils.filter((f) => !f.archive).map(ligne).join('')}
      <div data-foldroot><button class="list-head" type="button" data-fold=".arch" style="width:100%">Archivés · ${fils.filter((f) => f.archive).length}<svg class="ico sm"><use class="fold-ico" href="#i-chev-down"/></svg></button>
      <div class="arch" hidden>${fils.filter((f) => f.archive).map(ligne).join('')}</div></div>`,
    `<button class="btn tonal sm" type="button" data-close data-snack="Un fil neuf est ouvert">${ico('plus')}Nouveau</button>`);
  };
  A.dialogs.fil = () => A.dialog('Le fil', `<label class="tf" style="margin-bottom:16px"><span>Titre</span><input value="${h(fils[0].titre)}"></label>
    <label class="tf"><span>Description</span><textarea rows="3">${h(fils[0].desc)}</textarea></label>
    <div class="set-row" style="padding:14px 0 0"><span class="txt"><b style="font-size:15px">Archivé</b></span>${A.sw(false)}</div>`,
  '<button class="btn text" type="button" data-close>Annuler</button><button class="btn text" type="button" data-close data-snack="Fil enregistré">Enregistrer</button>');
  A.dialogs.pourquoi = () => A.dialog('Qu\'aurait-elle dû dire ?', '<p>Ton avis va au banc de conversation (ADR 0113). Il ne change rien à ce qu\'elle a dit.</p><label class="tf"><span>Ce qu\'elle aurait dû dire</span><textarea rows="3" placeholder="Facultatif"></textarea></label>',
    '<button class="btn text" type="button" data-close>Annuler</button><button class="btn text" type="button" data-close data-snack="👎 gardé, avec ton mot">Envoyer</button>');
  A.menus.chat = () => [{ ico: 'sparkle', l: 'Ce qu\'elle fait', go: '#mika' }, { ico: 'folder', l: 'Fichiers échangés', go: '#fichiers' }, { ico: 'search', l: 'Rechercher partout', go: '#recherche' }, '-', { ico: 'settings', l: 'Paramètres', go: '#parametres' }];
  A.menus['chat-pro'] = () => [{ ico: 'threads', l: 'Fils de travail', sheet: 'fils' }, { ico: 'pen', l: 'Régler ce fil', dialog: 'fil' }, { ico: 'archive', l: 'Archiver ce fil', snack: 'Fil archivé' }, '-', { ico: 'folder', l: 'Fichiers échangés', go: '#fichiers' }, { ico: 'sparkle', l: 'Ce qu\'elle fait', go: '#mika' }];

  // ── Rechercher ────────────────────────────────────────────────────────
  A.ecran('recherche', (args) => {
    const depuisChat = args[0] === 'chat';
    const groupe = (titre, items) => `<div class="list-head">${titre}</div>${items.map(([lead, b, s, go, t]) => `<button class="li hit" type="button" data-go="${go}">${lead}<span class="txt"><b>${b}</b><small class="two">${s}</small></span>${t ? `<span class="trail">${t}</span>` : ''}</button>`).join('')}`;
    const m = (s) => s.replace(/budget/gi, (x) => `<mark>${x}</mark>`);
    const scope = [{ l: 'Tout', radio: 's', on: !depuisChat }, { l: 'Conversation', radio: 's', on: depuisChat }, { l: 'Mail', radio: 's' }, { l: 'Teams', radio: 's' }, { l: 'Téléphone', radio: 's' }, { l: 'Écrans', radio: 's' }];
    return {
      nav: 'chat', back: '#chat',
      html: `<div class="search-top">${A.act('back', 'Retour', 'data-back')}<label class="field">${ico('search', 'sm')}<input value="budget" aria-label="Rechercher">${A.act('x', 'Effacer', '')}</label></div>
        ${A.chips(scope)}
        <div class="body">
          ${groupe('Dans la conversation', [[A.faceDot(40), 'Mika · aujourd\'hui 13:54', m('elle dit juste que la partie budget arrive trop tard'), '#chat', ''], [`<span class="lead box">${ico('threads')}</span>`, 'Fil · Devis Lefèvre', m('Le devis dépasse le budget de 1 240 € (+8 %)'), '#chat/pro', '13:32']])}
          ${depuisChat ? '' : groupe('Mail', [[av('claire'), 'Claire Dubois · Re: Présentation de jeudi', m('la partie budget arrive trop tard. Tu pourrais mettre un chiffre dès la deuxième slide ?'), '#mail/lire/m-claire', '13:40'], [A.grp('LR'), 'Lefèvre Rénovation · Devis n° 2026-114', m('1 240 € au-dessus du budget, d\'après Mika'), '#mail/lire/m-lefevre', '09:42']])}
          ${depuisChat ? '' : groupe('Teams', [[av('claire'), 'Claire Dubois', m('juste la partie budget qui arrive tard 🙂'), '#teams/d/claire', '13:41']])}
          ${depuisChat ? '' : groupe('Écrans', [[`<span class="lead box">${ico('tools')}</span>`, 'Outils › Droits', 'App « Devis » de la Forge : budget du projet', '#outils', ''], [`<span class="lead box">${ico('settings')}</span>`, 'Paramètres › Boîtes mail', 'Comment part ce que Mika y prépare', '#parametres/boites', '']])}
          ${depuisChat ? `<p class="note">Seulement dans la conversation. <button class="btn text sm" type="button" data-go="#recherche">Chercher partout</button></p>` : ''}
        </div>`,
      notes: {
        titre: depuisChat ? 'Rechercher dans la conversation' : 'Rechercher partout',
        reprend: ['Le Ctrl K du frontendv2 : un écran, un fil de travail, un mot dans les messages, un mail, une discussion.', 'Les puces disent où chercher ; depuis la loupe du chat, la conversation d\'abord.', 'Toucher un résultat ouvre son écran (un message : son fil, surligné).'],
        trancher: ['Une seule recherche à puces, ou une loupe propre à chaque écran (Mail, Teams…) en plus ?'],
      },
    };
  });

  // ── Les fichiers échangés ─────────────────────────────────────────────
  A.ecran('fichiers', () => {
    const imgs = [['tableau-blanc.jpg', false], ['plan-salle.png', true], ['IMG_2041.jpg', false], ['corneilles.png', true], ['capture-préprod.png', false], ['ticket.jpg', false]];
    const docs = [['devis-2026-114.pdf', '212 Ko · toi · aujourd\'hui 13:31', false], ['comparaison-devis.csv', '4 Ko · Mika · aujourd\'hui 13:32', true], ['les-alpes.gpx', '38 Ko · Mika · aujourd\'hui 14:18', true], ['notes-réunion.md', '2 Ko · toi · lun.', false]];
    return {
      nav: 'chat', back: '#chat',
      html: `${A.top({ title: 'Fichiers échangés', small: true, back: true, actions: [A.act('sort', 'Trier', 'data-snack="Les plus récents d\'abord"')], face: false })}
        ${A.chips([{ l: 'Tout', radio: 'f', on: true }, { l: 'Les siens', radio: 'f', mk: true }, { l: 'Les tiens', radio: 'f' }])}
        <div class="body"><div class="list-head">Images · 6</div>
          <div class="grid-files">${imgs.map(([n, mk]) => `<button class="gf${mk ? ' mika' : ''}" type="button" data-snack="${h(n)} : l'image s'ouvre en grand">${ico('image')}<small class="ellipsis">${h(n)}</small></button>`).join('')}</div>
          <div class="list-head">Documents · 4</div>
          ${docs.map(([n, s, mk]) => `<div class="li"><span class="lead box"${mk ? ' style="color:var(--mika)"' : ''}>${ico('file')}</span><span class="txt"><b>${h(n)}</b><small>${h(s)}</small></span>${A.act('more', 'Actions', 'data-menu="fichier"')}</div>`).join('')}
          <p class="note">Tes pièces se gardent tant que le serveur les garde ; « Enregistrer » les met dans Téléchargements/Mika. Bord rose : ce qu'elle t'a envoyé.</p></div>`,
      notes: { titre: 'Fichiers échangés', reprend: ['La liste du frontendv2 : les siens et les tiens, « Enregistrer » sur les deux (ADR 0215).', 'Les images en grille, les documents en liste ; ⋮ : Enregistrer, Ouvrir avec…, Voir dans la conversation.'], trancher: ['Ici depuis le ⋮ du chat : assez visible ?'] },
    };
  });
  A.menus.fichier = () => [{ ico: 'download', l: 'Enregistrer', snack: 'Enregistré dans Téléchargements/Mika' }, { ico: 'external', l: 'Ouvrir avec…', snack: 'Maquette : ouvrir avec…' }, { ico: 'chat', l: 'Voir dans la conversation', go: '#chat' }];

  // ── Ce qu'elle fait ───────────────────────────────────────────────────
  A.ecran('mika', () => {
    const m = D.mika;
    const corps = { clock: 'clock', bolt: 'bolt', pin: 'pin' };
    return {
      nav: 'chat', back: '#chat',
      html: `${A.top({ title: 'Ce qu\'elle fait', small: true, back: true, face: false, actions: [A.act('refresh', 'Relire', 'data-snack="À jour"')] })}
        <div class="body"><div class="mind-hero">${A.face(112)}<b>Mika</b><span class="muted">${h(m.humeurDite)} · ${h(m.fait)}</span></div>
        <div class="cards">
          <div class="card"><div class="over">Humeur</div>${m.facettes.map(([l, x]) => `<div class="facet"><span>${h(l)}</span><span class="bar"><i style="width:${x * 100}%"></i></span><span>${Math.round(x * 100)} %</span></div>`).join('')}</div>
          <div class="card"><div class="over">Corps</div>${m.corps.map(([i, l]) => `<div class="row" style="margin:6px 0">${ico(corps[i] || 'info', 'sm')}<span>${h(l)}</span></div>`).join('')}</div>
          <div class="card"><div class="over">Elle repense à…</div><p>${h(m.repense)}</p></div>
          <div class="card"><div class="over">Ce qu'elle t'a promis</div>${m.promesses.map(([l, q]) => `<div class="row" style="margin:6px 0">${ico('check', 'sm')}<span class="grow">${h(l)}</span><span class="tag">${h(q)}</span></div>`).join('')}</div>
          <div class="card"><div class="over">Rêve de cette nuit</div><p>${h(m.reve)}</p></div>
          <div class="card"><div class="over">Son journal</div><p>${h(m.journal)}</p></div>
          <div class="card"><div class="over">Ce qu'elle sait de toi</div><p>Elle te reconnaît sous le nom d'<b>Adrien</b>. Où vous en êtes : très proches. Ce qui t'intéresse, d'après elle : la rando, le travail bien fait, les voyages.</p></div>
          <div class="card"><div class="over">Estime de soi</div><p>${h(m.estime)}</p></div>
          <div class="card"><div class="over">Besoins</div><div class="row wrap" style="margin-top:6px">${m.besoins.map((b) => `<span class="tag pc">${h(b)}</span>`).join('')}</div></div>
          <div class="card"><div class="over">Projets en cours</div>${m.projets.map(([l, e]) => `<div class="row" style="margin:6px 0">${ico('code', 'sm')}<span class="grow">${h(l)}</span><span class="tag">${h(e)}</span></div>`).join('')}</div>
        </div></div>`,
      notes: { titre: 'Ce qu\'elle fait', reprend: ['L\'écran d\'aujourd\'hui (MindScreen), inchangé : on l\'ouvre en touchant son visage, sur n\'importe quel écran.', 'Ses promesses et ce à quoi elle repense remontent en haut, comme la colonne du chat du frontendv2.'], trancher: ['L\'ordre des cartes te va ?'] },
    };
  });

  A.index('Chat', [['Chat', '#chat'], ['Accords dépliés', '#chat/accord'], ['Mode pro', '#chat/pro'], ['Rechercher', '#recherche/chat'], ['Partout', '#recherche'], ['Fichiers', '#fichiers'], ['Ce qu\'elle fait', '#mika']]);
})();
