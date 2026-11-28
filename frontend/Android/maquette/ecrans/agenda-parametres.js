/* Paramètres › Agendas (proposé le 2026-11-23, pas encore validé). Posé par-dessus l'écran Paramètres validé, sans le
   retoucher : une ligne « Agendas » dans « Ce que Mika touche pour toi » (après Comptes Teams), et ses pages, une ligne
   une page, à la Android. Les comptes branchés (fournisseur, adresse, à qui, la synchro ou l'erreur en mots), la page d'un
   compte (ses agendas, sa connexion, son partage), la page d'un agenda (nom, couleur, visible, « Mika te le rappelle »,
   ce que Mika en fait, vers Outils › Droits), et « Brancher un agenda » par sorte : le système ; Google (ouvrir Google
   dans le navigateur, puis coller l'adresse de la page qui n'a pas pu s'ouvrir) ; Outlook.com / Microsoft 365 (le code
   d'appareil) ; CalDAV (DavMail, iCloud, Nextcloud, Fastmail) ; l'abonnement iCal. C'est la page web
   (frontend/Web/maquette/ecrans/agenda-parametres.js) en pages de téléphone.
   Routes : #parametres/agendas, /<compte>, /<compte>/<agenda>, /brancher, /brancher/<sorte>[/<étape>]. */
(function () {
  const { h, ico, av, D } = A;
  const X = A.agenda;
  const P0 = A.vue('parametres');
  if (!X || !P0) return;
  const { G, AG, CPT } = X;
  const SORTES = G.sortes;
  const ICO = { systeme: 'server', google: 'globe', microsoft: 'key', caldav: 'server', ical: 'link' };
  const agendasDe = (c) => G.agendas.filter((a) => a.compte === c.id);
  const nav = () => (A.v.nav === 'barre' ? 'plus' : 'parametres');
  const row = (b, s, val, attrs) => `<${attrs ? `button type="button" ${attrs}` : 'div'} class="set-row"><span class="txt"><b>${b}</b>${s ? `<small>${s}</small>` : ''}</span>${val || ''}</${attrs ? 'button' : 'div'}>`;
  const page = (titre, sub, corps, notes, extra) => ({ nav: nav(), back: extra && extra.back || '#parametres/agendas', cls: 'ag-scr',
    html: `${A.top({ title: titre, sub, small: true, back: true, face: false, actions: extra && extra.actions })}<div class="body ag-param" style="padding-bottom:${extra && extra.fab ? 96 : 24}px">${corps}</div>${extra && extra.fab || ''}`,
    notes, after: extra && extra.after });
  const lead = (c) => `<span class="lead box ag-acc s-${c.sorte}">${ico(ICO[c.sorte])}</span>`;

  // ── La liste ──────────────────────────────────────────────────────────
  function vueListe() {
    const lea = AG.lea, mika = AG.mika;
    const comptes = G.comptes.map((c) => {
      const warn = c.etat[0] !== 'ok';
      const n = agendasDe(c).length;
      return `<button class="li ag-acc-li" type="button" data-go="#parametres/agendas/${c.id}">${lead(c)}<span class="txt"><b>${h(c.nom)}</b><small>${h(c.adresse)}</small>
        <small class="${warn ? 'ag-warn-t' : 'muted'}">${warn ? `${ico('alert', 'xxs')} À reconnecter : l'accès a expiré` : `${h(X.cap(c.synchro.replace(/ : il est sur ce serveur/, '')))} · ${n} agenda${n > 1 ? 's' : ''}`}</small></span>
        ${ico('chev-right', 'sm')}</button>`;
    }).join('');
    return page('Agendas', `${G.comptes.length} comptes · à toi`, `<p class="note" style="padding:4px 28px 0">Tes agendas, d'où qu'ils viennent. Tu les vois tous dans l'Agenda ; Mika s'en sert selon ce que tu règles ici et dans Outils › Droits.</p>
      <div class="set-h">Tes comptes</div><div class="set-group">${comptes}</div>
      <div class="set-h">Partagé avec toi</div><div class="set-group"><div class="li">${av('lea')}<span class="txt"><b>${h(lea.nom)}</b><small class="two">Léa Moreau, en lecture, depuis le ${h(lea.depuisPartage)}</small></span>${A.sw(lea.visible, 'data-agvis="lea" aria-label="Dans l\'Agenda"')}</div></div>
      <div class="set-h mk">${ico('sparkle')}L'agenda de Mika</div><div class="set-group mk"><div class="li ag-top-li"><span class="lead">${A.face(40)}</span><span class="txt"><b>${h(mika.nom)}</b><small class="ag-wrap">Ce qu'elle t'a promis pour une date, et ce qu'elle retient de ta vie à venir (« la livraison de ton canapé »), montrés comme un agenda, en lecture seule. Rien n'y est recopié : c'est sa mémoire ; on le corrige en le lui disant.</small></span>${A.sw(mika.visible, 'data-agvis="mika" aria-label="Dans l\'Agenda"')}</div></div>
      <p class="note" style="padding:6px 28px 0">Elle ne te montre que ce qui te concerne : ce que d'autres lui confient n'y paraît jamais.</p>
      <div class="set-h">Pour tous tes agendas</div><div class="set-group">
        ${row('Fuseau horaire', 'Celui où tu vis ; un événement peut avoir le sien.', '<span class="muted">Europe/Paris</span>', 'data-snack="Maquette : la liste des fuseaux"')}
        ${row('La semaine commence', '', '<span class="muted">le lundi</span>', 'data-snack="Maquette : lundi, dimanche ou samedi"')}
        ${row('Un agenda neuf : Mika te le rappelle', 'Le réglage de départ d\'un agenda que tu branches ; chacun a ensuite le sien.', '<span class="muted">30 min avant</span>', 'data-snack="Maquette : non, 15 min, 30 min, 1 h, la veille au soir"')}
        ${row('Ce qui se synchronise', 'Les 90 derniers jours et l\'année qui vient. Au-delà, l\'Agenda demande au fournisseur quand tu y vas.', '<span class="tag">90 j · 1 an</span>')}
        ${row('Notifications de l\'agenda', 'Ses rappels et tes invitations, chacun son canal sur ce téléphone : « Rappels d\'agenda », « Invitations ».', `<span class="ag-a">Régler</span>`, 'data-snack="Maquette : les réglages de notification d\'Android, rubrique Mika"')}
      </div>`, {
      titre: 'Paramètres › Agendas (proposé)',
      reprend: ['Une ligne « Agendas » dans Paramètres, après Comptes Teams : ce que Mika touche pour toi.',
        'Tes comptes, une ligne chacun : la sorte (son icône), le nom, l\'adresse, l\'état en mots. Outlook.com est « à reconnecter » : l\'accès a expiré.',
        'L\'agenda que Léa te partage, et l\'agenda de Mika (rose) : un interrupteur « Dans l\'Agenda » chacun.',
        'Pour tous : le fuseau, le premier jour de la semaine, le rappel de départ d\'un agenda neuf, ce qui se synchronise, les notifications (deux canaux Android).',
        '« Brancher » en bouton flottant, comme « Ajouter » dans Boîtes mail.'],
      trancher: ['Masquer un agenda ici, est-ce couper Mika (proposé : il reste branché, et elle ne s\'en sert plus) ? Décocher dans l\'Agenda ne change que l\'affichage.',
        'Le rappel par défaut de chaque sorte : Système → Mika 30 min (il n\'a pas d\'autre notification) ; Google, Outlook, CalDAV → celui du fournisseur, et Mika selon l\'agenda ; un abonnement → aucun. D\'accord ?',
        'La fenêtre de synchronisation : 90 jours derrière, un an devant ?',
        'Un compte d\'agenda « à Mika » (comme une boîte) : à quoi lui servirait-il, hors de sa mémoire ?'],
    }, { back: '#parametres', fab: `<button class="fab" type="button" data-go="#parametres/agendas/brancher">${ico('plus')}Brancher</button>` });
  }

  // ── La page d'un compte ───────────────────────────────────────────────
  function connexion(c) {
    if (c.sorte === 'systeme') return row('Connexion', 'Rien à brancher : il est sur ce serveur, rien ne sort d\'ici.', '<span class="tag ok">sur ce serveur</span>');
    if (c.sorte === 'google') return row('Compte Google', `Par l'application Google de ce serveur (OAuth 2) · ${h(c.depuis)}`, '<span class="ag-a">Se reconnecter</span>', 'data-go="#parametres/agendas/brancher/google"');
    if (c.sorte === 'microsoft') return row('Compte Microsoft', `Par un code à entrer chez Microsoft · ${h(c.depuis)}`, '<span class="tag warn">accès expiré</span>', 'data-go="#parametres/agendas/brancher/microsoft/code"');
    if (c.sorte === 'ical') return `<div class="set-row" style="display:block"><label class="tf"><span>Adresse .ics</span><input class="mono" value="${h(c.adresse)}"></label><small class="muted" style="display:block;margin-top:6px;font-size:12.5px">Lue telle quelle, en lecture seule.</small></div>`
      + row('Relire', '', `<span class="muted">${h(c.frequence)}</span>`, 'data-snack="Maquette : chaque heure, chaque jour, chaque semaine"');
    return `<div class="set-row" style="display:block"><label class="tf"><span>Adresse du serveur</span><input class="mono" value="${h(c.serveur)}"></label>
        <small class="muted" style="display:block;margin-top:6px;font-size:12.5px">La passerelle DavMail sur cette machine (mode O365Graph), comme pour ta boîte Pro.</small></div>
      <div class="set-row" style="display:block"><label class="tf"><span>Identifiant</span><input value="${h(c.adresse)}"></label></div>
      ${row('Mot de passe d\'application', 'Scellé : il ne se relit plus.', '<button class="btn tonal sm" type="button" data-snack="Connexion réussie : 3 agendas sur le serveur">Essayer</button>')}`;
  }
  function vueCompte(c) {
    const ags = agendasDe(c);
    const fourn = { google: 'Google', caldav: 'Outlook', microsoft: 'Microsoft' }[c.sorte];
    const partages = ags.filter((a) => a.visible && a.groupe === 'mes').map((a) => `<button class="li" type="button" data-go="#agenda/partager/${a.id}"><span class="lead">${X.sw(a.couleur, 'lg')}</span>
      <span class="txt"><b>${h(a.nom)}</b><small class="two">${a.partages.length ? a.partages.map(([k, n]) => `${h(A.who(k).court)} · ${h(X.NIVEAUX[n][0].toLowerCase())}`).join(' ; ') : 'Personne'}${a.chezGoogle ? ` · chez Google : ${h(a.chezGoogle.join(', '))} (ne se voit pas ici)` : ''}</small></span><span class="ag-a">Partager</span></button>`).join('');
    return page(h(c.nom), `${h(SORTES[c.sorte].long)}${c.service === 'davmail' ? ' par DavMail' : ''}`, `
      <div class="ag-acc-hero">${lead(c)}<div class="grow"><b>${h(c.adresse)}</b><div class="row wrap" style="gap:6px;margin-top:4px"><span class="tag ${c.etat[0]}">${h(c.etat[1])}</span><span class="tag pc">à toi</span></div></div></div>
      ${c.erreur ? `<div class="ag-err attn">${ico('alert', 'sm')}<span><b>${h(c.erreur)}</b><small>${h(X.cap(c.synchro))}. Ses agendas ne s'affichent plus en attendant.</small>
        <button class="btn filled sm" type="button" data-go="#parametres/agendas/brancher/microsoft/code">${ico('key')}Se reconnecter</button></span></div>`
        : `<p class="note" style="padding:4px 28px 0">${ico('refresh', 'xxs')} ${h(X.cap(c.synchro))} · ${h(c.depuis)}</p>`}
      <div class="set-h">Ses agendas</div><div class="set-group">${ags.map((a) => `<button class="li" type="button" data-go="#parametres/agendas/${c.id}/${a.id}"><span class="lead">${X.sw(a.couleur, 'lg')}</span>
        <span class="txt"><b>${h(a.nom)}${a.defaut ? ' <span class="tag">par défaut</span>' : ''}</b><small class="two">${a.visible ? `Dans l'Agenda · Mika te le rappelle : ${h(X.rappelDit(a.rappel))}` : 'Masqué : Mika ne s\'en sert pas'}</small></span>${ico('chev-right', 'sm')}</button>`).join('')}
        ${c.sorte === 'systeme' ? `<button class="li" type="button" data-go="#parametres/agendas/brancher/systeme"><span class="lead">${ico('plus')}</span><span class="txt"><b class="ag-a">Créer un agenda</b></span></button>`
          : c.sorte === 'ical' ? '' : `<button class="li" type="button" data-snack="Synchronisé : rien de neuf sur ce compte"><span class="lead">${ico('refresh')}</span><span class="txt"><b class="ag-a">Chercher d'autres agendas</b><small>sur ce compte</small></span></button>`}</div>
      <div class="set-h">Le compte</div><div class="set-group">
        <div class="set-row" style="display:block"><label class="tf"><span>Nom</span><input value="${h(c.nom)}"></label><small class="muted" style="display:block;margin-top:6px;font-size:12.5px">Comme tu l'appelles, et comme elle l'appelle.</small></div>
        ${row('À qui', 'Ses outils ne voient que les agendas de qui est en face.', '<span class="muted">Toi</span>', 'data-sheet="ag-aqui"')}
        ${connexion(c)}
        ${row('Synchronisation', c.sorte === 'ical' ? 'Un abonnement se relit à son rythme.' : 'Elle relit ce qui a changé toutes les 5 minutes ; une modification part tout de suite.', `<button class="btn tonal sm" type="button" data-snack="Synchronisé : rien de neuf depuis 3 min">${ico('refresh')}Synchroniser</button>`)}</div>
      ${partages ? `<div class="set-h">Partage</div>${fourn ? `<div class="note box">${ico('info', 'sm')}<span>Un agenda ${h(fourn)} se partage ici, dans Mika, avec une personne qui a un compte : elle le voit dans son Agenda de Mika. Ça ne change rien chez ${h(fourn)}, et un partage fait chez ${h(fourn)} ne se voit pas ici.</span></div>` : ''}<div class="set-group">${partages}</div>` : ''}
      ${c.sorte === 'systeme' ? '' : `<div style="padding:20px 16px 8px"><button class="btn danger outlined block" type="button" data-dialog="ag-retirer" data-agcpt="${c.id}">${ico('trash')}Retirer ce compte</button></div>
        <p class="note" style="padding:0 28px">Ses agendas disparaissent de ton Agenda et de ce que Mika voit ; rien n'est effacé chez le fournisseur.</p>`}`, {
      titre: `Paramètres › Agendas › ${h(c.nom)} (proposé)`,
      reprend: ['Le compte : son adresse, son état, à qui il est. ' + (c.erreur ? 'En panne : l\'erreur en mots, et « Se reconnecter » (le code d\'appareil).' : 'La dernière synchro, en mots.'),
        'Ses agendas, une ligne chacun (couleur, visible, le rappel de Mika) : toucher ouvre la page de l\'agenda.',
        'Le compte : son nom, à qui, la connexion (selon la sorte), synchroniser.',
        fourn ? 'Partage : la phrase qui dit qu\'un partage dans Mika n\'est pas un partage chez ' + fourn + ' ; chaque agenda, avec qui, vers la feuille Partager.' : '',
        c.sorte === 'systeme' ? 'L\'agenda du système : « Créer un agenda » (Sport, Maison…), rien à brancher, rien ne sort d\'ici.' : 'Retirer ce compte, confirmé dans une fenêtre.'].filter(Boolean),
      trancher: ['Le partage sur la page du compte (ici) ou seulement sur la page de chaque agenda ?', 'Retirer : un bouton rouge au pied (ici), ou dans un menu ⋮ en haut ?'],
    }, { actions: [A.act('refresh', 'Synchroniser', 'data-snack="Synchronisé : rien de neuf"')] });
  }

  // ── La page d'un agenda ───────────────────────────────────────────────
  function vueAgenda(c, a) {
    const pal = G.palette.map(([k, l]) => `<button type="button" class="ag-swatch${a.couleur === k ? ' on' : ''}" style="--c:var(--ag-${k})" data-agcoulp="${a.id}:${k}" title="${h(l)}" aria-label="${h(l)}">${a.couleur === k ? ico('check') : ''}</button>`).join('');
    return page(h(a.nom), `${h(c.nom)} · ${h(c.adresse)}`, `
      <div class="set-group" style="margin-top:12px">
        <div class="set-row" style="display:block"><label class="tf"><span>Nom</span><input value="${h(a.nom)}"></label></div>
        <div class="set-row" style="display:block"><span class="txt"><b>Couleur</b><small>Le rose n'y est pas : il est à Mika.</small></span><div class="ag-swatches" style="padding:10px 0 2px">${pal}</div></div>
        ${row('Dans l\'Agenda', a.visible ? 'Tu le vois ; Mika s\'en sert.' : 'Masqué : il reste branché, il ne s\'affiche plus, et Mika ne s\'en sert plus.', A.sw(a.visible, `data-agvis="${a.id}" aria-label="Dans l'Agenda"`))}
        ${row('On peut', '', `<span class="tag">${a.ecrire ? 'lire et écrire' : 'lire seulement'}</span>`)}
        ${a.defaut ? row('Agenda par défaut', 'Un événement créé sans dire où va ici.', '<span class="tag pc">par défaut</span>') : ''}</div>
      <div class="set-h">Rappels</div><div class="set-group">
        ${row('Ceux du fournisseur', X.cap(a.rappelFourn), '')}
        <button class="set-row ag-mkrow" type="button" data-sheet="ag-prappel" data-agid="${a.id}"><span class="txt"><b>${ico('sparkle', 'xs')} Mika te le rappelle</b><small>Le réglage de départ de ses événements ; chacun peut avoir le sien.</small></span><span class="mk-txt">${h(X.rappelDit(a.rappel))}</span></button></div>
      ${G.droits[a.id] ? `<div class="set-h mk">${ico('sparkle')}Ce que Mika en fait</div><div class="set-group mk"><button class="li" type="button" data-go="#outils/droits/${a.id}"><span class="txt"><b style="white-space:normal">${h(X.resume(a.id))}</b><small>Son tableau : lire, ajouter, répondre aux invitations, ce qu'elle en garde</small></span><span class="ag-a">Ses droits</span></button></div>` : ''}
      ${a.groupe === 'mes' ? `<div class="set-h">Partage</div><div class="set-group">${a.partages.map(([k, n, d]) => `<div class="li">${av(k, 'sm')}<span class="txt"><b>${h(A.who(k).nom)}</b><small>${h(X.NIVEAUX[n][0])} · depuis le ${h(d)}</small></span></div>`).join('')}
        <button class="li" type="button" data-go="#agenda/partager/${a.id}"><span class="lead">${ico('user-plus')}</span><span class="txt"><b class="ag-a">${a.partages.length ? 'Gérer le partage' : 'Partager'}</b>${a.chezGoogle ? `<small>chez Google : ${h(a.chezGoogle.join(', '))} (ne se voit pas ici)</small>` : ''}</span></button></div>` : ''}`, {
      titre: `Paramètres › Agendas › ${h(a.nom)} (proposé)`,
      reprend: ['La page d\'un agenda, comme dans les réglages de Google Agenda sur Android : son nom, sa couleur (huit, sans le rose), « Dans l\'Agenda », ce qu\'on peut y faire.',
        'Rappels : ceux du fournisseur, puis « Mika te le rappelle » (rose), le départ de chaque événement.',
        'Ce que Mika en fait, en une phrase tirée de son tableau, vers Outils › Droits.', 'Partage : avec qui, vers la feuille Partager.'],
      trancher: ['« Dans l\'Agenda » éteint coupe aussi Mika (ici) : d\'accord, ou deux réglages (le voir · qu\'elle s\'en serve) ?'],
    }, { back: `#parametres/agendas/${c.id}` });
  }

  // ── Brancher un agenda ────────────────────────────────────────────────
  const ORDRE = ['systeme', 'google', 'microsoft', 'caldav', 'ical'];
  const etapes = (cur, liste) => `<ol class="ag-steps">${liste.map(([titre, corps], i) => {
    const n = i + 1, st = cur > n ? 'fait' : cur === n ? 'actif' : 'avenir';
    return `<li class="ag-step ${st}"><span class="ag-step-n">${st === 'fait' ? ico('check', 'sm') : n}</span><div class="ag-step-b"><h3>${titre}</h3>${st === 'actif' ? corps : ''}</div></li>`;
  }).join('')}</ol>`;
  const trouves = (l) => `<div class="ag-found">${l.map(([nom, coul, note, coche]) => `<label class="ag-found-r"><input type="checkbox"${coche ? ' checked' : ''}${/déjà branché/.test(note) ? ' disabled' : ''}><span class="ag-cbx">${ico('check')}</span>${X.sw(coul)}<span class="txt"><b>${h(nom)}</b>${note ? `<small>${h(note)}</small>` : ''}</span></label>`).join('')}</div>`;
  const finir = (label) => `<button class="btn filled block" type="button" data-agbrfin>${ico('check')}${h(label || 'Brancher')}</button><p class="note" style="padding:8px 0 0">Il sera à toi. Mika s'en sert selon son tableau, que tu règles ensuite dans Outils › Droits.</p>`;
  const nuancier = (sel) => `<div class="ag-swatches">${G.palette.map(([k, l]) => `<button type="button" class="ag-swatch${k === sel ? ' on' : ''}" style="--c:var(--ag-${k})" data-agpal title="${h(l)}" aria-label="${h(l)}">${k === sel ? ico('check') : ''}</button>`).join('')}</div>`;
  const champ = (l, v, attrs) => `<label class="tf ag-tf"><span>${l}</span><input ${attrs || ''} value="${h(v || '')}"></label>`;
  const AIDES = {
    davmail: ['Outlook pro (DavMail)', 'Pour un Outlook de travail que l\'organisation ne laisse pas brancher directement : la passerelle DavMail sur cette machine, en mode O365Graph, comme pour ta boîte Pro.', 'http://127.0.0.1:1080/users/a.moreau@lumen-conseil.fr/calendar/', 'a.moreau@lumen-conseil.fr'],
    icloud: ['iCloud', 'Ton identifiant Apple, et un mot de passe pour app (compte Apple › Connexion et sécurité › Mots de passe pour app) : jamais celui de ton compte.', 'https://caldav.icloud.com', ''],
    nextcloud: ['Nextcloud', 'L\'adresse de ton Nextcloud suivie de /remote.php/dav, et un mot de passe d\'application (Paramètres › Sécurité › Appareils et sessions).', 'https://cloud.exemple.fr/remote.php/dav', ''],
    fastmail: ['Fastmail', 'Un mot de passe d\'application avec l\'accès « Agendas (CalDAV) » (Paramètres › Confidentialité et sécurité › Mots de passe d\'application).', 'https://caldav.fastmail.com/dav/', ''],
  };
  let service = 'davmail';
  function parcours(sorte, etape) {
    if (sorte === 'systeme') {
      return etapes(1, [['Un agenda de ce serveur', `<p>Chaque personne qui a un compte a déjà « Mon agenda ». Crée-en d'autres pour ranger ta vie (« Sport », « Maison »…). Il vit sur ce serveur : rien ne sort d'ici, et tu le partages avec qui a un compte.</p>
        ${champ('Nom', '', 'placeholder="Sport"')}<div class="ag-st-l">Couleur</div>${nuancier('sarcelle')}
        <button class="set-row ag-mkrow" type="button" data-snack="Maquette : non, 15 min, 30 min, 1 h, la veille au soir"><span class="txt"><b>${ico('sparkle', 'xs')} Mika te le rappelle</b></span><span class="mk-txt">30 min avant</span></button>${finir('Créer l\'agenda')}`]]);
    }
    if (sorte === 'google') {
      const n = etape === 'coller' ? 2 : etape === 'choisir' ? 3 : 1;
      const un = etape === 'sans-appli'
        ? `<div class="ag-err warn">${ico('alert', 'sm')}<span><b>L'application Google de ce serveur n'est pas réglée : demande à l'opérateur.</b><small>Sans elle, Google refuse de te connecter.${D.moi.operatrice ? ' Tu es opérateur : elle se règle dans la console, Échanges › Agendas › Paramètres, volet « Application Google » (un client « Application de bureau » d\'un projet Google Cloud).' : ''}</small></span></div>
          <p>En attendant, tu peux t'abonner à l'adresse secrète iCal de ton agenda Google, en lecture seule.</p><button class="btn tonal" type="button" data-go="#parametres/agendas/brancher/ical">${ico('link')}Un abonnement iCal</button>`
        : `<p>Google s'ouvre dans ton navigateur : choisis ton compte, puis accepte que Mika lise et modifie tes agendas.</p>
          <button class="btn filled block" type="button" data-go="#parametres/agendas/brancher/google/coller" data-snack="Chrome s'ouvre sur la page de Google">${ico('external')}Ouvrir Google dans le navigateur</button>
          <p class="note" style="padding:8px 0 0">Avec l'application Google de ce serveur, réglée par l'opérateur.</p>`;
      const deux = `<p>Après ton accord, Google renvoie le navigateur vers une adresse qui commence par <code>http://127.0.0.1</code>. La page ne s'ouvre pas, c'est normal : son adresse porte le code qui prouve ton accord.</p>
        <div class="ag-chrome" aria-hidden="true"><div class="ag-chrome-bar"><span class="ag-chrome-u">${ico('info', 'xs')}<span><b>127.0.0.1/?state=k2Q…&amp;code=4/0AanRRrtq8…</b></span></span>${ico('more', 'xs')}</div>
          <div class="ag-chrome-pop"><span>Copier</span><span>Partager</span><span>Modifier</span></div>
          <div class="ag-chrome-page">${ico('alert')}<b>Ce site est inaccessible</b><span>127.0.0.1 n'autorise pas la connexion.</span></div></div>
        <ol class="ag-how"><li>Dans Chrome, touche la barre d'adresse : l'adresse entière se sélectionne.</li><li>Touche <b>Copier</b> (ou l'icône ⧉ au bout de la barre).</li><li>Reviens dans Mika et touche <b>Coller</b> ci-dessous.</li></ol>
        <label class="tf ag-tf"><span>L'adresse de la page</span><input class="mono" data-agcolle placeholder="http://127.0.0.1/?state=…&amp;code=…"></label>
        <div class="btns" style="margin-top:10px"><button class="btn tonal sm" type="button" data-agcoller>${ico('copy')}Coller</button><span class="grow"></span><button class="btn filled sm" type="button" data-agvalider>Valider</button></div>
        <p class="note" style="padding:8px 0 0">Si ce serveur a une adresse en https, Google y revient tout seul et cette étape disparaît.</p>`;
      const trois = `<p>Compte adrien.moreau@gmail.com · 4 agendas trouvés.</p>${trouves([['Perso', 'vert', 'déjà branché', true], ['Famille', 'orange', 'déjà branché', true], ['Anniversaires', 'ambre', '', true], ['Jours fériés en France (Google)', 'ardoise', 'tu en as déjà un abonnement', false]])}${finir()}`;
      return etapes(n, [['Se connecter à Google', un], ['Colle l\'adresse de la page qui n\'a pas pu s\'ouvrir', deux], ['Choisis tes agendas', trois]]);
    }
    if (sorte === 'microsoft') {
      const n = etape === 'code' ? 2 : etape === 'choisir' ? 3 : 1;
      return etapes(n, [
        ['Ton compte Microsoft', `<p>Outlook.com, Hotmail, Live, ou un compte Microsoft 365. Un compte pro dépend de l'accord de son organisation : si elle le refuse, passe par <button class="ag-lien" type="button" data-go="#parametres/agendas/brancher/caldav">CalDAV avec DavMail</button>.</p>
          ${champ('Adresse', 'adrien.moreau@outlook.fr', 'type="email"')}<button class="btn filled block" type="button" data-go="#parametres/agendas/brancher/microsoft/code" style="margin-top:12px">${ico('key')}Obtenir un code</button>`],
        ['Entre le code chez Microsoft', `<div class="ag-code"><small>Ton code</small><b>H4QX-7KMT</b><span>valable jusqu'à 14:35</span></div>
          <div class="btns"><button class="btn tonal" type="button" data-snack="Code copié : H4QX-7KMT">${ico('copy')}Copier le code</button><button class="btn filled" type="button" data-snack="Chrome s'ouvre sur microsoft.com/devicelogin">${ico('external')}Ouvrir Microsoft</button></div>
          <ol class="ag-how"><li>« Ouvrir Microsoft » ouvre <b>microsoft.com/devicelogin</b> dans le navigateur.</li><li>Colle le code (il est copié), puis accepte.</li><li>Reviens ici : Mika se connecte dès que c'est fait, rien à coller.</li></ol>
          <p class="ag-attente"><i class="ag-spin"></i>En attente de Microsoft…</p>`],
        ['Choisis tes agendas', `<p>Compte adrien.moreau@outlook.fr · 3 agendas trouvés.</p>${trouves([['Calendrier', 'violet', 'déjà branché', true], ['Anniversaires', 'ambre', '', false], ['Jours fériés en France', 'ardoise', 'tu en as déjà un abonnement', false]])}${finir()}`]]);
    }
    if (sorte === 'caldav') {
      const [nom, aide, exemple, ident] = AIDES[service];
      const n = etape === 'trouves' ? 2 : 1;
      return etapes(n, [
        ['Le serveur', `<div class="ag-st-l">Une aide pour</div><div class="chips" style="padding:0 0 6px;flex-wrap:wrap">${Object.entries(AIDES).map(([k, [l]]) => `<button type="button" class="chip${k === service ? ' on' : ''}" data-agservice="${k}">${k === service ? ico('check', 'xs') : ''}${h(l)}</button>`).join('')}</div>
          <div class="note box" style="margin:4px 0 12px">${ico('info', 'sm')}<span><b>${h(nom)}</b> · ${h(aide)}</span></div>
          ${champ('Adresse du serveur', service === 'davmail' ? exemple : '', `class="mono" placeholder="${h(exemple)}"`)}${champ('Identifiant', ident, 'placeholder="ton identifiant"')}${champ('Mot de passe d\'application', service === 'davmail' ? '••••••••••••' : '', 'type="password"')}
          <p class="note" style="padding:6px 0 0">Pas celui de ton compte : un mot de passe fait pour une application.</p>
          <button class="btn filled block" type="button" data-go="#parametres/agendas/brancher/caldav/trouves" style="margin-top:10px">${ico('refresh')}Essayer</button>`],
        ['Les agendas trouvés', `<p class="ag-ok">${ico('check', 'sm')}Connexion réussie : 3 agendas trouvés.</p>${trouves([['Calendrier', 'bleu', 'déjà branché (« Travail »)', true], ['Salles de réunion', 'ardoise', 'lecture seule', false], ['Congés de l\'équipe', 'sarcelle', 'lecture seule', true]])}${finir()}`]]);
    }
    return etapes(1, [['L\'adresse de l\'abonnement', `<p>Une adresse .ics : les jours fériés, le calendrier d'un club, ou l'adresse secrète d'un agenda Google ou Outlook. <b>Lecture seule</b> : ni toi ni Mika n'y écrivez.</p>
      ${champ('Adresse .ics', 'https://www.rando-cassel.fr/sorties.ics', 'class="mono"')}<p class="note" style="padding:4px 0 8px">Une adresse secrète donne à lire tout l'agenda : garde-la pour toi.</p>
      ${champ('Nom', 'Sorties du club de rando')}<div class="ag-st-l">Couleur</div>${nuancier('ambre')}
      <button class="set-row" type="button" data-snack="Maquette : chaque heure, chaque jour, chaque semaine" style="padding:12px 0"><span class="txt"><b>Relire</b><small>Plus souvent ne sert à rien pour des jours fériés.</small></span><span class="muted">chaque jour</span></button>
      <div class="btns" style="margin-bottom:12px"><button class="btn tonal sm" type="button" data-aglire>${ico('refresh')}Essayer</button><span class="note" style="padding:0" data-aglu></span></div>${finir('S\'abonner')}`]]);
  }
  function vueBrancher(sorte, etape) {
    if (!sorte) {
      return page('Brancher un agenda', '', `<p class="note" style="padding:8px 28px 0">Il sera à toi. Tu choisis ceux de ses agendas que tu vois ; ce que Mika en fait se règle ensuite dans Outils › Droits.</p>
        <div class="set-group" style="margin-top:12px">${ORDRE.map((k) => `<button class="li" type="button" data-go="#parametres/agendas/brancher/${k}"><span class="lead box ag-acc s-${k}">${ico(ICO[k])}</span><span class="txt"><b>${h(SORTES[k].long)}</b><small class="two">${h(SORTES[k].aide)}</small></span>${ico('chev-right', 'sm')}</button>`).join('')}</div>`, {
        titre: 'Paramètres › Agendas › Brancher (proposé)',
        reprend: ['Cinq sortes, une ligne chacune, puis un parcours en étapes : le système (créer un agenda), Google, Outlook.com / Microsoft 365, CalDAV, l\'abonnement iCal.'],
        trancher: ['Outlook pro : Graph direct (le code d\'appareil, si l\'organisation l\'accepte) ou DavMail (la voie sûre) ? La maquette propose les deux.', 'Brancher un agenda depuis le téléphone, ou seulement depuis le web (le collage de Google y est plus simple) ?'],
      }, { back: '#parametres/agendas' });
    }
    const NOTES = {
      systeme: ['Créer un agenda de ce serveur : son nom, sa couleur, « Mika te le rappelle ».'],
      google: [etape === 'sans-appli' ? 'L\'état « l\'application Google de ce serveur n\'est pas réglée » : demander à l\'opérateur (et, s\'il l\'est, où la régler) ; en attendant, un abonnement iCal.'
        : 'Google refuse le code d\'appareil pour l\'agenda : « Ouvrir Google dans le navigateur », puis coller l\'adresse de la page qui n\'a pas pu s\'ouvrir.',
      'Sur un téléphone, la page dit comment copier l\'adresse depuis Chrome (un dessin de la barre d\'adresse et de son « Copier »), et « Coller » prend le presse-papiers.',
      'Puis les agendas trouvés, cochés ou non ; ceux déjà branchés grisés.'],
      microsoft: ['Le code d\'appareil, comme pour une boîte Outlook (ADR 0166, 0238) : « Copier le code », « Ouvrir Microsoft » ; Mika se connecte seule quand c\'est fait.'],
      caldav: ['Une aide par serveur (Outlook pro par DavMail, iCloud, Nextcloud, Fastmail) en puces ; l\'adresse, l\'identifiant, le mot de passe d\'application ; « Essayer » montre les agendas trouvés.'],
      ical: ['Une adresse .ics, en lecture seule : son nom, sa couleur, son rythme de relecture ; « Essayer » dit ce qu\'elle a lu.'],
    };
    return page(`Brancher · ${h(SORTES[sorte].nom)}`, h(SORTES[sorte].long), `<div class="ag-parcours">${parcours(sorte, etape)}</div>`, {
      titre: `Brancher un agenda · ${h(SORTES[sorte].long)} (proposé)`, reprend: NOTES[sorte],
      trancher: sorte === 'google' ? ['L\'adresse à coller : la phrase et le dessin suffisent-ils sur un téléphone, ou vaut-il mieux renvoyer au web pour Google (« Brancher depuis le web ») ?', 'L\'application Google : réglée une fois par l\'opérateur pour tout le serveur (proposé), ou chacun la sienne ?']
        : sorte === 'microsoft' ? ['Le code se copie tout seul quand on touche « Ouvrir Microsoft » : d\'accord, ou deux gestes séparés (ici) ?'] : [],
    }, {
      back: '#parametres/agendas/brancher',
      after() {
        if (sorte === 'microsoft' && etape === 'code') {
          const ici = location.hash;
          setTimeout(() => { if (location.hash === ici) { location.replace('#parametres/agendas/brancher/microsoft/choisir'); A.snack('Connecté à Microsoft'); } }, 6000);
        }
      },
    });
  }

  // ── Le branchement sur Paramètres ─────────────────────────────────────
  function pageAgendas(args) {
    const [a, b, c] = args;
    if (a === 'brancher') return vueBrancher(ORDRE.includes(b) ? b : null, c);
    if (a && CPT[a]) return b && AG[b] && AG[b].compte === a ? vueAgenda(CPT[a], AG[b]) : vueCompte(CPT[a]);
    return vueListe();
  }
  A.ecran('parametres', (args) => {
    if (args[0] === 'agendas') return pageAgendas(args.slice(1));
    const v = P0(args);
    if (!v.racine) return v;
    const after0 = v.after;
    const panne = G.comptes.filter((c) => c.etat[0] !== 'ok').length;
    return { ...v,
      notes: { ...v.notes, reprend: [...(v.notes.reprend || []), 'Proposé (Agenda) : une ligne « Agendas » après Comptes Teams, vers Paramètres › Agendas.'] },
      after(root) {
        if (after0) after0(root);
        const t = root.querySelector('.li[data-go="#parametres/teams"]');
        if (t && !root.querySelector('[data-go="#parametres/agendas"]')) {
          t.insertAdjacentHTML('afterend', `<button class="li" type="button" data-go="#parametres/agendas"><span class="lead">${ico('agenda')}</span><span class="txt"><b>Agendas</b><small>${G.comptes.length} comptes${panne ? ` · ${panne} à reconnecter` : ''}</small></span>${panne ? `<span class="ag-warn-t">${ico('alert', 'sm')}</span>` : ''}</button>`);
        }
      } };
  });

  // ── Feuilles, fenêtres, gestes ────────────────────────────────────────
  A.sheets['ag-aqui'] = () => A.sheet('À qui est ce compte', [['user', 'Toi', 'ses agendas sont à toi ; tu les partages si tu veux', true], ['sparkle', 'Mika', 'son agenda à elle (une équipe qu\'elle suit ?)'], ['user', 'Léa Moreau', 'a un compte'], ['user', 'Julien Roux', 'a un compte']]
    .map(([i, l, s, on]) => `<button class="li${on ? ' sel' : ''}" type="button" data-close data-snack="Maquette : à ${h(l)}"><span class="lead">${ico(i)}</span><span class="txt"><b>${h(l)}</b><small>${h(s)}</small></span>${on ? ico('check') : ''}</button>`).join(''));
  A.sheets['ag-prappel'] = (x) => {
    const a = AG[x.dataset.agid];
    A.sheet(`« ${h(a.nom)} » : Mika te le rappelle`, `<p class="note" style="padding:0 24px 6px">Le départ de chaque événement de cet agenda ; dans le chat, ou par une notification si l'app est fermée.</p>
      ${X.RAPPELS.map(([k, l]) => `<button class="li${a.rappel === k ? ' sel' : ''}" type="button" data-agprap="${a.id}:${k}"><span class="lead">${ico(k === 'non' ? 'x' : 'bell')}</span><span class="txt"><b>${h(l)}</b></span>${a.rappel === k ? ico('check') : ''}</button>`).join('')}`);
  };
  A.dialogs['ag-retirer'] = (x) => {
    const c = CPT[x.dataset.agcpt];
    A.dialog('Retirer ce compte ?', `<p>« ${h(c.nom)} » (${h(c.adresse)}) : ses agendas disparaissent de ton Agenda et de ce que Mika voit. Rien n'est effacé chez le fournisseur ; ses partages dans Mika s'arrêtent.</p>`,
      '<button class="btn text" type="button" data-close>Annuler</button><button class="btn text" type="button" data-close data-snack="Maquette : le compte serait retiré" style="color:var(--danger)">Retirer</button>');
  };
  document.addEventListener('click', (e) => {
    const t = e.target;
    let x;
    if ((x = t.closest('[data-agcoulp]'))) { const [id, k] = x.dataset.agcoulp.split(':'); AG[id].couleur = k; A.render(); A.snack(`« ${AG[id].nom} » : ${G.palette.find((p) => p[0] === k)[1].toLowerCase()}`); return; }
    if ((x = t.closest('[data-agprap]'))) { const [id, k] = x.dataset.agprap.split(':'); AG[id].rappel = k; A.closeAll(); A.render(); A.snack(k === 'non' ? `Elle ne te rappellera pas les événements de « ${AG[id].nom} »` : `« ${AG[id].nom} » : elle te les rappellera ${X.rappelDit(k)}`); return; }
    if ((x = t.closest('[data-agpal]'))) { x.parentNode.querySelectorAll('.ag-swatch').forEach((b) => { b.classList.toggle('on', b === x); b.innerHTML = b === x ? ico('check') : ''; }); return; }
    if ((x = t.closest('[data-agservice]'))) { service = x.dataset.agservice; A.render(); return; }
    if ((x = t.closest('[data-agcoller]'))) { const i = document.querySelector('[data-agcolle]'); if (i) i.value = 'http://127.0.0.1/?state=k2Q…&code=4/0AanRRrtq8…&scope=…calendar'; A.snack('Collé depuis le presse-papiers'); return; }
    if ((x = t.closest('[data-agvalider]'))) {
      const i = document.querySelector('[data-agcolle]');
      if (i && !/code=/.test(i.value)) { A.snack('Il manque l\'adresse : touche « Coller »'); return; }
      A.go('#parametres/agendas/brancher/google/choisir'); A.snack('Code reçu : Google a dit oui'); return;
    }
    if ((x = t.closest('[data-aglire]'))) { const l = document.querySelector('[data-aglu]'); if (l) l.textContent = '24 sorties lues, de septembre à juin.'; return; }
    if ((x = t.closest('[data-agbrfin]'))) { location.replace('#parametres/agendas'); A.snack('Branché : ses agendas sont dans ton Agenda'); }
  });
  document.addEventListener('change', (e) => {
    const v = e.target.closest('[data-agvis]');
    if (!v) return;
    const a = AG[v.dataset.agvis];
    a.visible = v.checked;
    if (v.checked) a.coche = true;
    A.snack(v.checked ? `« ${a.nom} » s'affiche dans ton Agenda` : `« ${a.nom} » ne s'affiche plus ; Mika ne s'en sert plus`);
    if (/^#parametres\/agendas\/[^/]+\/[^/]+$/.test(location.hash)) A.render();
  });

  A.index('Agenda · Paramètres (proposé)', [['Paramètres', '#parametres'], ['Agendas', '#parametres/agendas'], ['Lumen (CalDAV)', '#parametres/agendas/lumen'], ['Google', '#parametres/agendas/google'],
    ['Outlook.com, en panne', '#parametres/agendas/outlook'], ['Système', '#parametres/agendas/systeme'], ['Un agenda : Perso', '#parametres/agendas/google/perso'],
    ['Brancher', '#parametres/agendas/brancher'], ['… système', '#parametres/agendas/brancher/systeme'], ['… Google', '#parametres/agendas/brancher/google'],
    ['… Google, coller', '#parametres/agendas/brancher/google/coller'], ['… Google, choisir', '#parametres/agendas/brancher/google/choisir'], ['… Google sans appli', '#parametres/agendas/brancher/google/sans-appli'],
    ['… Microsoft', '#parametres/agendas/brancher/microsoft'], ['… Microsoft, le code', '#parametres/agendas/brancher/microsoft/code'], ['… CalDAV', '#parametres/agendas/brancher/caldav'],
    ['… CalDAV, trouvés', '#parametres/agendas/brancher/caldav/trouves'], ['… iCal', '#parametres/agendas/brancher/ical']]);
})();
