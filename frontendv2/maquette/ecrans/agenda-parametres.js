/* Paramètres › Agendas — proposé le 2026-11-23, pas encore validé. Posé par-dessus l'écran Paramètres validé, sans le
   retoucher : il lui ajoute un onglet (après Teams) et prend la main sur ses routes. Les comptes branchés (fournisseur,
   adresse, à qui, la synchro ou l'erreur en mots, leurs agendas, ce que Mika en fait), la fiche d'un compte, et
   « Brancher un agenda » avec un parcours par sorte : système, Google, Outlook.com / Microsoft 365, CalDAV, iCal. */
(function () {
  const P = M.ecrans.parametres;
  if (!P || !M.agenda) return;
  const { h, ico, av } = M;
  const G = M.agenda, A = G.A, AG = G.AG, CPT = G.CPT;
  const SORTES = A.sortes;

  const at = P.onglets.findIndex((o) => o.id === 'teams');
  P.onglets.splice(at + 1, 0, { id: 'agendas', titre: 'Agendas' });

  const row = (nom, aide, valeur, cls) => `<div class="set-row${cls ? ' ' + cls : ''}"><div class="set-label"><b>${nom}</b>${aide ? `<p>${aide}</p>` : ''}</div><div class="set-value">${valeur}</div></div>`;
  const sw = (on, attrs) => `<label class="switch"><input type="checkbox"${on ? ' checked' : ''}${attrs || ''}><i></i></label>`;
  const section = (titre, corps, id, aside) => `<section class="set-sec" data-agsous="${id}"><div class="set-sec-head"><h2>${titre}</h2>${aside ? `<div class="ph-actions">${aside}</div>` : ''}</div><div class="set-grid two">${corps}</div></section>`;
  const optRappel = (v) => G.RAPPELS.map(([k, l]) => `<option value="${k}"${k === v ? ' selected' : ''}>${h(l)}</option>`).join('');
  const agendasDe = (c) => A.agendas.filter((a) => a.compte === c.id);
  const sousActif = {};
  let br = { cle: null, etape: 1, service: 'davmail' };

  /* Ce que Mika fait d'un agenda, en une ligne, d'après son tableau (Outils › Droits). */
  function resume(agId) {
    const L = A.droits[agId];
    if (!L) return '';
    const t = L.find((l) => l.qui === 'toi' && l.quand === 'repond') || L[0];
    const ECR = { non: 'n\'y écrit pas', accord: 'y ajoute avec ton accord', seule: 'y ajoute seule', '—': '' };
    const parts = [t.lire === 'oui' ? 'le lit' : 'ne le lit pas', ECR[t.ecrire], t.repondre === 'accord' ? 'prépare tes réponses' : ''].filter(Boolean);
    const elle = L.find((l) => l.qui === 'elle');
    const avec = L.filter((l) => l.partage).map((l) => M.who(l.qui).court);
    return `Avec toi, elle ${parts.join(', ')}${elle && elle.lire === 'oui' && L.some((l) => l.quand === 'parole') ? ' ; elle te rappelle ses rendez-vous' : ''}${avec.length ? ` · aussi avec ${avec.join(' et ')}` : ''}`;
  }
  const icone = (c) => `<span class="acc-ico ag-acc-ico s-${c.sorte}">${ico(SORTES[c.sorte].ico)}</span>`;
  const aQui = (c) => (c.a === 'toi' ? '<span class="tag accent">à toi</span>' : '<span class="tag mika">à Mika</span>');

  // ── La liste ──────────────────────────────────────────────────────────
  function carteCompte(c) {
    const ags = agendasDe(c), warn = c.etat[0] !== 'ok';
    return `<div class="acc-card ag-acc">${icone(c)}
      <div class="grow"><div class="row wrap"><b>${h(c.nom)}</b><span class="muted ellipsis ag-acc-adr">${h(c.adresse)}</span></div>
        <div class="row wrap acc-tags"><span class="tag ${c.etat[0]}">${h(c.etat[1])}</span><span class="tag">${h(SORTES[c.sorte].long)}${c.service === 'davmail' ? ' · DavMail' : ''}</span>${aQui(c)}</div>
        <div class="ag-acc-cals">${ags.map((a) => `<span class="ag-acc-cal${a.visible ? '' : ' off'}" title="${a.visible ? 'Dans l\'Agenda' : 'Pas dans l\'Agenda'}">${G.sw(a.couleur)}${h(a.nom)}${a.visible ? '' : ' <i>masqué</i>'}${a.rappel !== 'non' ? `<span class="ag-acc-r" title="Mika te le rappelle">${ico('bell', 'xs')}${h(G.rappelDit(a.rappel))}</span>` : ''}</span>`).join('')}</div>
        <p class="small ${warn ? 'warn-txt ag-acc-err' : 'muted'}">${warn ? ico('alert', 'xs') + h(c.erreur) : h(cap(c.synchro))}</p>
        ${ags.filter((a) => a.visible && A.droits[a.id]).slice(0, 1).map((a) => `<p class="small ag-acc-mika">${ico('sparkle', 'xs')}<span>${h(resume(a.id))}${ags.length > 1 ? ` (« ${h(a.nom)} »)` : ''} · <a href="#outils/droits/ag-${a.id}">Ses droits</a></span></p>`).join('')}</div>
      ${warn ? `<button class="btn sm primary" type="button" data-agreco="${c.id}">${ico('key', 'sm')}Se reconnecter</button>` : ''}
      <a class="btn sm" href="#parametres/agendas/${c.id}">Régler</a>
      <button class="btn sm icon ghost" type="button" data-agcptmenu="${c.id}" title="Plus">${ico('more', 'sm')}</button></div>`;
  }
  const cap = G.cap;
  function vueListe() {
    const lea = AG.lea, mika = AG.mika;
    return `<div class="set-page">
      <p class="lede">Tes agendas, d'où qu'ils viennent : celui de ce serveur, Google, Outlook, un serveur CalDAV, un abonnement. Tu les vois tous dans l'Agenda ; Mika s'en sert selon ce que tu règles ici et dans Outils › Droits. Un compte n'est qu'à toi, sauf si tu partages ses agendas.</p>
      <h2 class="section-title">Tes comptes <span class="cnt">${A.comptes.length}</span></h2>
      <div class="acc-cards">${A.comptes.map(carteCompte).join('')}</div>
      <h2 class="section-title shared-title">Partagé avec toi <span class="cnt">1</span></h2>
      <div class="acc-cards"><div class="acc-card">${av('lea', 'lg')}<div class="grow"><div class="row"><b>${h(lea.nom)}</b><span class="tag">lire</span></div>
        <p class="small muted">Léa Moreau te l'a ouvert en lecture le ${h(lea.depuisPartage)}. Tu le vois dans l'Agenda ; tu n'y changes rien, et Mika ne s'en sert avec toi que pour le lire.</p></div>
        <a class="btn sm" href="#agenda/semaine">Ouvrir</a><label class="row small ag-vis">${sw(lea.visible, ' data-agvis="lea"')}Dans l'Agenda</label></div></div>
      <h2 class="section-title shared-title">L'agenda de Mika</h2>
      <div class="acc-cards"><div class="acc-card ag-mika-card">${av('mika', 'lg')}<div class="grow"><b>${h(mika.nom)}</b>
        <p class="small text-2">Ce qu'elle t'a promis pour une date, et ce qu'elle retient de ta vie à venir (« la livraison de ton canapé »), montrés comme un agenda, en lecture seule. Rien n'y est recopié : c'est sa mémoire. On le corrige en le lui disant.</p>
        <p class="small muted">Elle ne te montre que ce qui te concerne : ce que d'autres lui confient n'y paraît jamais.</p></div>
        <label class="row small ag-vis">${sw(mika.visible, ' data-agvis="mika"')}Dans l'Agenda</label></div></div>
      <section class="set-sec"><div class="set-sec-head"><h2>Pour tous tes agendas</h2></div><div class="set-grid two">
        ${row('Fuseau horaire', 'Celui où tu vis ; un événement peut avoir le sien.', '<select><option>(UTC+01:00) Europe/Paris</option><option>(UTC+00:00) Europe/London</option></select>')}
        ${row('La semaine commence', '', '<select><option>le lundi</option><option>le dimanche</option><option>le samedi</option></select>')}
        ${row('Un agenda neuf : Mika te le rappelle', 'Le réglage de départ d\'un agenda que tu branches ; chacun a ensuite le sien.', `<select>${optRappel('30')}</select>`)}
        ${row('Ce qui se synchronise', 'Les 90 derniers jours et l\'année qui vient. Au-delà, l\'Agenda demande au fournisseur quand tu y vas.', '<span class="tag">90 jours derrière · 1 an devant</span>')}
      </div></section>
    </div>`;
  }

  // ── La fiche d'un compte ──────────────────────────────────────────────
  function connexion(c) {
    if (c.sorte === 'systeme') return row('Connexion', 'Rien à brancher : il est sur ce serveur.', '<span class="tag ok">sur ce serveur</span><span class="small muted">rien ne sort d\'ici</span>');
    if (c.sorte === 'google') return row('Compte Google', 'Par l\'application Google de ce serveur (OAuth 2), réglée par l\'opérateur.', `<span class="tag ok">connecté</span><span class="small muted">${h(c.depuis)}</span><button class="btn xs" type="button" data-agreco="${c.id}">Se reconnecter</button><button class="btn xs ghost danger" type="button" data-agdeco>Déconnecter</button>`);
    if (c.sorte === 'microsoft') return row('Compte Microsoft', 'Par un code à entrer chez Microsoft, avec l\'application Microsoft de ce serveur.', `<span class="tag warn">accès expiré</span><span class="small muted">${h(c.depuis)}</span><button class="btn xs primary" type="button" data-agreco="${c.id}">${ico('key', 'xs')}Se reconnecter</button>`);
    if (c.sorte === 'ical') return row('Adresse .ics', 'Lue telle quelle, en lecture seule.', `<input class="mono" value="${h(c.adresse)}">`)
      + row('Relire', '', '<select><option>chaque heure</option><option selected>chaque jour</option><option>chaque semaine</option></select>');
    return row('Adresse du serveur', c.service === 'davmail' ? 'La passerelle DavMail sur cette machine (mode O365Graph), comme pour ta boîte Pro.' : '', `<input class="mono" value="${h(c.serveur)}">`)
      + row('Identifiant', '', `<input value="${h(c.adresse)}">`)
      + row('Mot de passe d\'application', 'Scellé : il ne se relit plus.', '<input type="password" value="••••••••••••"><button class="btn xs" type="button" data-agessai>' + ico('refresh', 'xs') + 'Essayer</button>');
  }
  function tableAgendas(c) {
    const ags = agendasDe(c);
    return `<div class="set-row full"><div class="tbl-wrap"><table class="tbl ag-tbl"><thead><tr><th>Couleur</th><th>Agenda</th><th>Dans l'Agenda</th><th>Mika te le rappelle</th><th>On peut</th><th>Ce que Mika en fait</th></tr></thead><tbody>
      ${ags.map((a) => `<tr><td><button class="ag-swbtn" type="button" data-agcoulp="${a.id}" title="Changer la couleur">${G.sw(a.couleur)}${ico('chev-down', 'xs')}</button></td>
        <td><input value="${h(a.nom)}" class="ag-nom-in">${a.defaut ? ' <span class="tag">par défaut</span>' : ''}</td>
        <td>${sw(a.visible, ` data-agvis="${a.id}"`)}</td>
        <td><select class="sm-select ag-mika-sel" data-agrapp="${a.id}">${optRappel(a.rappel)}</select></td>
        <td><span class="tag">${a.ecrire ? 'lire et écrire' : 'lire seulement'}</span></td>
        <td class="small">${A.droits[a.id] ? `${h(resume(a.id))} · <a href="#outils/droits/ag-${a.id}">Ses droits</a>` : `<span class="muted">${a.visible ? '' : 'Pas dans l\'Agenda : Mika ne s\'en sert pas.'}</span>`}</td></tr>`).join('')}
      </tbody></table></div>
      <div class="row tbl-help">${c.sorte === 'systeme' ? `<a class="btn xs" href="#parametres/agendas/brancher/systeme">${ico('plus', 'xs')}Créer un agenda</a>` : `<button class="btn xs" type="button" data-agsync>${ico('refresh', 'xs')}Chercher d'autres agendas sur ce compte</button>`}
        <span class="small muted">Un agenda masqué reste branché : il ne s'affiche plus, et Mika ne s'en sert plus.</span></div></div>`;
  }
  function partages(c) {
    const ags = agendasDe(c).filter((a) => a.visible);
    const fourn = c.sorte === 'google' ? 'Google' : c.sorte === 'caldav' ? 'Outlook' : c.sorte === 'microsoft' ? 'Microsoft' : '';
    return `<div class="set-row full">${fourn ? `<div class="info-line small">${ico('info', 'sm')}<span>Un agenda ${h(fourn)} se partage ici, dans Mika, avec une personne qui a un compte : elle le voit dans son Agenda de Mika. Ça ne change rien chez ${h(fourn)}, et un partage fait chez ${h(fourn)} ne se voit pas ici.</span></div>` : ''}
      <div class="ag-part-list">${ags.map((a) => `<div class="ag-part">${G.sw(a.couleur)}<b>${h(a.nom)}</b>
        <span class="grow row wrap">${a.partages.length ? a.partages.map(([k, n, d]) => `<span class="chip">${av(k, 'xs')}${h(M.who(k).court)} · ${h(G.NIVEAUX[n][0].toLowerCase())}<span class="muted small">depuis le ${h(d)}</span></span>`).join('') : '<span class="small muted">Personne</span>'}
          ${a.chezGoogle ? `<span class="small muted">· chez Google : ${h(a.chezGoogle.join(', '))} (ne se voit pas ici)</span>` : ''}</span>
        <a class="btn xs" href="#agenda/partager/${a.id}">${ico('user-plus', 'xs')}Partager…</a></div>`).join('')}</div></div>`;
  }
  function ficheCompte(c) {
    const actif = sousActif[c.id] || 'compte';
    const tab = (k, l) => `<button type="button" data-agsousv="${k}" aria-pressed="${k === actif}">${h(l)}</button>`;
    return `<form class="set-page" data-form data-agfiche="${c.id}">
      <a class="back-link" href="#parametres/agendas">${ico('chev-left', 'sm')}Agendas</a>
      <div class="fiche-head">${icone(c)}<div class="grow"><h2>${h(c.nom)}</h2><p class="muted">${h(c.adresse)} · ${h(SORTES[c.sorte].long)}${c.service === 'davmail' ? ' par DavMail' : ''}</p></div>
        <span class="tag ${c.etat[0]}">${h(c.etat[1])}</span>${aQui(c)}</div>
      ${c.erreur ? `<div class="ag-err">${ico('alert', 'sm')}<span><b>${h(c.erreur)}</b><small>${h(cap(c.synchro))}. Ses agendas ne s'affichent plus en attendant.</small></span><button class="btn sm primary" type="button" data-agreco="${c.id}">${ico('key', 'sm')}Se reconnecter</button></div>`
        : `<p class="small muted ag-sync">${ico('refresh', 'xs')}${h(cap(c.synchro))} · ${h(c.depuis)}</p>`}
      <nav class="sub-seg" data-agsouspage>${tab('compte', 'Le compte')}${tab('agendas', `Ses agendas (${agendasDe(c).length})`)}${tab('partage', 'Partage')}</nav>
      ${section('Le compte', row('Nom', 'Comme tu l\'appelles, et comme elle l\'appelle.', `<input value="${h(c.nom)}">`)
        + row('À qui', 'Un compte est à toi, à elle, ou à une personne qui a un compte : ses outils ne voient que les agendas de qui est en face.', `<select><option${c.a === 'toi' ? ' selected' : ''}>Toi</option><option>Mika (son agenda à elle)</option><option>Léa Moreau</option><option>Julien Roux</option></select>`)
        + connexion(c)
        + row('Synchronisation', c.sorte === 'ical' ? 'Un abonnement se relit à son rythme.' : 'Elle relit ce qui a changé, toutes les 5 minutes ; une modification part tout de suite.', `<span class="small text-2">${h(cap(c.synchro))}</span><button class="btn xs" type="button" data-agsync>${ico('refresh', 'xs')}Synchroniser</button>`)
        + (c.sorte === 'systeme' ? '' : row('Retirer ce compte', 'Ses agendas disparaissent de ton Agenda et de ce que Mika voit ; rien n\'est effacé chez le fournisseur.', `<button class="btn sm danger" type="button" data-agretirer="${c.id}">${ico('trash', 'sm')}Retirer</button>`)), 'compte')}
      ${section('Ses agendas', tableAgendas(c), 'agendas')}
      ${section('Partage', partages(c), 'partage')}
    </form>`;
  }

  // ── Brancher un agenda ────────────────────────────────────────────────
  const ORDRE = ['systeme', 'google', 'microsoft', 'caldav', 'ical'];
  const etapes = (liste) => `<ol class="ag-steps">${liste.map(([titre, corps], i) => {
    const n = i + 1, st = br.etape > n ? 'fait' : br.etape === n ? 'actif' : 'avenir';
    return `<li class="ag-step ${st}"><span class="ag-step-n">${st === 'fait' ? ico('check', 'sm') : n}</span><div class="ag-step-body"><h3>${titre}${st === 'fait' ? `<button class="linkish" type="button" data-agbrn="${n}">Modifier</button>` : ''}</h3>${st === 'avenir' ? `<div class="ag-step-avenir">${corps}</div>` : corps}</div></li>`;
  }).join('')}</ol>`;
  const trouves = (liste) => `<div class="ag-found">${liste.map(([nom, coul, note, coche]) => `<label class="ag-found-row"><input type="checkbox"${coche ? ' checked' : ''}${note === 'déjà branché' ? ' disabled' : ''}>${G.sw(coul)}<b>${h(nom)}</b>${note ? `<span class="small muted">${h(note)}</span>` : ''}</label>`).join('')}</div>`;
  const finir = (label) => `<div class="row wrap"><button class="btn primary" type="button" data-agbr="fin">${ico('check', 'sm')}${h(label || 'Brancher')}</button><span class="small muted">Il sera à toi. Mika s'en sert selon son tableau, que tu règles ensuite dans Outils › Droits.</span></div>`;
  const nuancier = (sel) => `<div class="ag-swatches inline">${A.palette.map(([k, l]) => `<button type="button" class="ag-swatch${k === sel ? ' on' : ''}" style="--c:var(--ag-${k})" data-agpal="${k}" title="${h(l)}"></button>`).join('')}</div>`;
  const AIDES = {
    davmail: ['Outlook pro (DavMail)', 'Pour un Outlook de travail que l\'organisation ne laisse pas brancher directement : la passerelle DavMail sur cette machine, en mode O365Graph, comme pour ta boîte Pro. L\'identifiant et le mot de passe sont ceux que DavMail attend.', 'http://127.0.0.1:1080/users/prenom.nom@entreprise.fr/calendar/'],
    icloud: ['iCloud', 'Ton identifiant Apple, et un mot de passe pour app (compte Apple › Connexion et sécurité › Mots de passe pour app) : jamais celui de ton compte.', 'https://caldav.icloud.com'],
    nextcloud: ['Nextcloud', 'L\'adresse de ton Nextcloud suivie de /remote.php/dav, et un mot de passe d\'application (Paramètres › Sécurité › Appareils et sessions).', 'https://cloud.exemple.fr/remote.php/dav'],
    fastmail: ['Fastmail', 'Un mot de passe d\'application avec l\'accès « Agendas (CalDAV) » (Paramètres › Confidentialité et sécurité › Mots de passe d\'application).', 'https://caldav.fastmail.com/dav/'],
  };
  function parcours(sorte, sansAppli) {
    if (sorte === 'systeme') return etapes([['Un agenda de ce serveur', `<p class="small text-2">Chaque personne qui a un compte a déjà « Mon agenda ». Crée-en d'autres pour ranger ta vie (« Sport », « Maison »…). Il vit sur ce serveur : rien ne sort d'ici, et tu le partages avec qui a un compte.</p>
      <div class="set-grid">${row('Nom', '', '<input placeholder="Sport">')}${row('Couleur', '', nuancier('sarcelle'))}${row('Mika te le rappelle', 'Le réglage de départ de ses événements.', `<select>${optRappel('30')}</select>`)}</div>${finir('Créer l\'agenda')}`]]);
    if (sorte === 'google') {
      const un = sansAppli
        ? `<div class="ag-err warn">${ico('alert', 'sm')}<span><b>L'application Google de ce serveur n'est pas réglée : demande à l'opérateur.</b><small>Sans elle, Google refuse de te connecter. ${M.D.moi.operatrice ? 'Tu es opérateur : elle se règle dans la console, Échanges › Agendas › Paramètres, volet « Application Google » (un client « Application de bureau » d\'un projet Google Cloud).' : ''}</small></span></div>
          <p class="small text-2">En attendant, tu peux t'abonner à l'adresse secrète iCal de ton agenda Google : en lecture seule. <a href="#parametres/agendas/brancher/ical">Un abonnement iCal</a></p>`
        : `<p class="small text-2">Une page Google s'ouvre dans un nouvel onglet : choisis ton compte, puis accepte que Mika lise et modifie tes agendas.</p>
          <div class="row wrap"><button class="btn primary" type="button" data-agbr="connecter">${ico('globe', 'sm')}Se connecter à Google</button><span class="small muted">Avec l'application Google de ce serveur, réglée par l'opérateur.</span></div>`;
      return etapes([['Se connecter à Google', un],
        ['Colle ici l\'adresse de la page qui n\'a pas pu s\'ouvrir', `<p class="small text-2">Après ton accord, Google te renvoie vers une adresse qui commence par <code>http://127.0.0.1</code>. La page ne s'ouvre pas, c'est normal : son adresse porte le code qui prouve ton accord. Copie-la dans la barre d'adresse, et colle-la ici.</p>
          <div class="ag-faux"><div class="ag-faux-barre">${ico('lock', 'xs')}<span class="mono">http://127.0.0.1/?state=k2Q…&amp;<b>code=4/0AanRRrtq8…</b>&amp;scope=…calendar</span></div><div class="ag-faux-page">${ico('alert')}<b>Ce site est inaccessible</b><span>127.0.0.1 n'autorise pas la connexion.</span></div></div>
          <div class="row"><input class="grow mono" data-agcolle placeholder="http://127.0.0.1/?state=…&amp;code=…"${br.etape > 2 ? ' value="http://127.0.0.1/?state=k2Q…&amp;code=4/0AanRRrtq8…"' : ''}><button class="btn primary" type="button" data-agbr="coller">Valider</button></div>
          <p class="small muted">Si ce serveur a une adresse en https, Google y revient tout seul et cette étape disparaît.</p>`],
        ['Choisis tes agendas', `<p class="small text-2">Compte adrien.moreau@gmail.com · 4 agendas trouvés.</p>${trouves([['Perso', 'vert', 'déjà branché', true], ['Famille', 'orange', 'déjà branché', true], ['Anniversaires', 'ambre', '', true], ['Jours fériés en France (Google)', 'ardoise', 'tu en as déjà un abonnement', false]])}${finir()}`]]);
    }
    if (sorte === 'microsoft') return etapes([
      ['Ton compte Microsoft', `<p class="small text-2">Outlook.com, Hotmail, Live, ou un compte Microsoft 365. Un compte pro dépend de l'accord de son organisation : si elle le refuse, passe par <a href="#parametres/agendas/brancher/caldav">CalDAV avec DavMail</a>.</p>
        <div class="row wrap"><input placeholder="prenom.nom@outlook.fr" value="adrien.moreau@outlook.fr" class="grow"><button class="btn primary" type="button" data-agbr="code">${ico('key', 'sm')}Obtenir un code</button></div>`],
      ['Entre le code chez Microsoft', `<div class="device ag-device">${ico('key')}<div><b>Ouvre <a href="#" data-agfaux>microsoft.com/devicelogin</a> et entre ce code</b><div class="code">H4QX-7KMT</div>
        <span class="small muted">Valable jusqu'à 14:35. Mika se connecte dès que c'est fait : rien à coller ici.</span></div><span class="ag-attente"><i class="spin"></i>En attente…</span></div>`],
      ['Choisis tes agendas', `<p class="small text-2">Compte adrien.moreau@outlook.fr · 3 agendas trouvés.</p>${trouves([['Calendrier', 'violet', 'déjà branché', true], ['Anniversaires', 'ambre', '', false], ['Jours fériés en France', 'ardoise', 'tu en as déjà un abonnement', false]])}${finir()}`]]);
    if (sorte === 'caldav') {
      const [nom, aide, exemple] = AIDES[br.service];
      return etapes([
        ['Le serveur', `<div class="row wrap ag-services"><span class="small text-2">Une aide pour :</span><div class="seg" data-seg="agservice">${Object.entries(AIDES).map(([k, [l]]) => `<button type="button" data-v="${k}" aria-pressed="${k === br.service}">${h(l)}</button>`).join('')}</div></div>
          <div class="info-line small">${ico('info', 'sm')}<span><b>${h(nom)}</b> · ${h(aide)}</span></div>
          <div class="set-grid">${row('Adresse du serveur', '', `<input class="mono" placeholder="${h(exemple)}"${br.service === 'davmail' ? ` value="http://127.0.0.1:1080/users/a.moreau@lumen-conseil.fr/calendar/"` : ''}>`)}
            ${row('Identifiant', '', `<input placeholder="ton identifiant"${br.service === 'davmail' ? ' value="a.moreau@lumen-conseil.fr"' : ''}>`)}
            ${row('Mot de passe d\'application', 'Pas celui de ton compte : un mot de passe fait pour une application.', `<input type="password"${br.service === 'davmail' ? ' value="••••••••••••"' : ''}>`)}</div>
          <div class="row"><button class="btn primary" type="button" data-agbr="essayer">${ico('refresh', 'sm')}Essayer</button></div>`],
        ['Les agendas trouvés', `<p class="ag-ok">${ico('check', 'sm')}Connexion réussie : 3 agendas trouvés.</p>${trouves([['Calendrier', 'bleu', 'déjà branché (« Travail »)', true], ['Salles de réunion', 'ardoise', 'lecture seule', false], ['Congés de l\'équipe', 'sarcelle', 'lecture seule', true]])}${finir()}`]]);
    }
    return etapes([['L\'adresse de l\'abonnement', `<p class="small text-2">Une adresse .ics : les jours fériés, le calendrier d'un club, ou l'adresse secrète d'un agenda Google ou Outlook. <b>Lecture seule</b> : ni toi ni Mika n'y écrivez.</p>
      <div class="set-grid">${row('Adresse .ics', 'Une adresse secrète donne à lire tout l\'agenda : garde-la pour toi.', '<input class="mono" placeholder="https://…/basic.ics" value="https://www.rando-cassel.fr/sorties.ics">')}
        ${row('Nom', '', '<input value="Sorties du club de rando">')}${row('Couleur', '', nuancier('ambre'))}
        ${row('Relire', 'Plus souvent ne sert à rien pour des jours fériés.', '<select><option>chaque heure</option><option selected>chaque jour</option><option>chaque semaine</option></select>')}</div>
      <div class="row wrap"><button class="btn" type="button" data-agbr="lire">${ico('refresh', 'sm')}Essayer</button><span class="small muted" data-aglu></span></div>${finir('S\'abonner')}`]]);
  }
  function vueBrancher(sorte, sansAppli) {
    const cle = `${sorte}/${sansAppli ? 1 : 0}`;
    if (br.cle !== cle) br = { cle, etape: sansAppli ? 1 : 1, service: br.service || 'davmail' };
    return `<div class="set-page ag-brancher">
      <a class="back-link" href="#parametres/agendas">${ico('chev-left', 'sm')}Agendas</a>
      <div class="fiche-head"><div><h2>Brancher un agenda</h2><p class="muted">Il sera à toi. Tu choisis ceux de ses agendas que tu vois ; ce que Mika en fait se règle ensuite dans Outils › Droits.</p></div></div>
      <div class="providers ag-providers">${ORDRE.map((k) => `<a class="provider${k === sorte ? ' on' : ''}" href="#parametres/agendas/brancher/${k}">${ico(SORTES[k].ico, 'lg')}<b>${h(SORTES[k].long)}</b><span>${h(SORTES[k].aide)}</span></a>`).join('')}</div>
      ${sorte ? `<div class="ag-parcours">${parcours(sorte, sansAppli)}</div>` : '<p class="small muted">Choisis d\'où vient ton agenda.</p>'}
    </div>`;
  }

  // ── Le branchement sur l'écran Paramètres ─────────────────────────────
  const rendu0 = P.rendu, actions0 = P.actions, notes0 = P.notes, recherche0 = P.recherche, monte0 = P.monte;
  P.rendu = (body, ctx) => {
    if (ctx.onglet !== 'agendas') { rendu0(body, ctx); return; }
    const [a, b, c] = (ctx.item || '').split('/');
    let html;
    if (a === 'brancher') html = vueBrancher(ORDRE.includes(b) ? b : null, c === 'sans-appli');
    else if (a && CPT[a]) html = ficheCompte(CPT[a]);
    else html = vueListe();
    body.innerHTML = `<div class="fill-scroll"><div class="page-pad">${html}</div></div>`;
    const f = body.querySelector('[data-form]');
    if (f) { M.formulaire(f); montrer(f); }
  };
  function montrer(f) {
    const id = f.dataset.agfiche, actif = sousActif[id] || 'compte';
    f.querySelectorAll('[data-agsous]').forEach((x) => { x.hidden = x.dataset.agsous !== actif; });
    f.querySelectorAll('[data-agsousv]').forEach((x) => x.setAttribute('aria-pressed', x.dataset.agsousv === actif));
  }
  P.actions = (ctx) => {
    if (ctx.onglet !== 'agendas') return actions0(ctx);
    const a = (ctx.item || '').split('/')[0];
    if (a === 'brancher') return '';
    if (a && CPT[a]) return `<button class="btn" type="button" data-agsync>${ico('refresh', 'sm')}<span class="lbl">Synchroniser</span></button>`;
    return `<a class="btn primary" href="#parametres/agendas/brancher">${ico('plus', 'sm')}<span class="lbl">Brancher un agenda</span></a>`;
  };
  P.monte = (sec) => {
    monte0(sec);
    M.on(sec, '[data-agsousv]', 'click', (e, b) => { const f = b.closest('[data-agfiche]'); sousActif[f.dataset.agfiche] = b.dataset.agsousv; montrer(f); });
    M.on(sec, '[data-agreco]', 'click', (e, b) => {
      const c = CPT[b.dataset.agreco];
      M.go(`#parametres/agendas/brancher/${c.sorte === 'caldav' ? 'caldav' : c.sorte}`);
    });
    M.on(sec, '[data-agdeco]', 'click', () => M.toast('Maquette : ses agendas disparaîtraient de l\'Agenda ; rien n\'est effacé chez Google.', { ico: 'logout' }));
    M.on(sec, '[data-agsync]', 'click', () => M.toast('Synchronisé : rien de neuf depuis 3 min.', { ico: 'refresh' }));
    M.on(sec, '[data-agessai]', 'click', () => M.toast('Connexion réussie : 3 agendas sur le serveur.', { ico: 'check' }));
    M.on(sec, '[data-agretirer]', 'click', (e, b) => {
      const c = CPT[b.dataset.agretirer];
      const el = M.modal({ titre: 'Retirer ce compte', taille: 'narrow', corps: `<p>Retirer « ${h(c.nom)} » (${h(c.adresse)}) ? Ses agendas disparaissent de ton Agenda et de ce que Mika voit. Rien n'est effacé chez le fournisseur ; ses partages dans Mika s'arrêtent.</p>`,
        pied: '<span class="grow"></span><button class="btn" type="button" data-close>Annuler</button><button class="btn danger" type="button" data-ok>Retirer</button>' });
      el.querySelector('[data-ok]').addEventListener('click', () => { M.fermerModal(); M.toast('Maquette : le compte serait retiré.', { ico: 'trash' }); });
    });
    M.on(sec, '[data-agcptmenu]', 'click', (e, b) => {
      const c = CPT[b.dataset.agcptmenu];
      M.menu(b, [{ label: 'Synchroniser maintenant', ico: 'refresh', action: () => M.toast('Synchronisé.', { ico: 'refresh' }) },
        { label: 'Régler', ico: 'settings', action: () => M.go('#parametres/agendas/' + c.id) },
        { label: 'Ses droits', ico: 'shield', action: () => M.go('#outils/droits/ag-' + (agendasDe(c)[0] || {}).id) },
        ...(c.sorte === 'systeme' ? [] : ['sep', { label: 'Retirer ce compte', ico: 'trash', danger: true, action: () => M.toast('Maquette : ouvre « Régler » pour le retirer.', { ico: 'info' }) }])]);
    });
    sec.addEventListener('change', (e) => {
      const v = e.target.closest('[data-agvis]');
      if (v) { const a = AG[v.dataset.agvis]; a.visible = v.checked; if (v.checked) a.coche = true; if (!v.closest('[data-form]')) M.toast(v.checked ? `« ${a.nom} » s'affiche dans ton Agenda.` : `« ${a.nom} » ne s'affiche plus dans ton Agenda ; Mika ne s'en sert plus.`, { ico: v.checked ? 'eye' : 'eye-off' }); }
      const r = e.target.closest('[data-agrapp]');
      if (r) AG[r.dataset.agrapp].rappel = r.value;
    });
    M.on(sec, '[data-agcoulp]', 'click', (e, b) => {
      const a = AG[b.dataset.agcoulp];
      const m = M.menu(b, [{ entete: 'Couleur' }, { html: `<div class="ag-swatches">${A.palette.map(([k, l]) => `<button type="button" class="ag-swatch${a.couleur === k ? ' on' : ''}" style="--c:var(--ag-${k})" data-agcoul="${k}" title="${h(l)}"></button>`).join('')}</div>` }], { align: 'left' });
      M.on(m, '[data-agcoul]', 'click', (ev, x) => { a.couleur = x.dataset.agcoul; M.fermerMenu(); b.innerHTML = `${G.sw(a.couleur)}${ico('chev-down', 'xs')}`; b.closest('form').dispatchEvent(new Event('change')); });
    });
    M.on(sec, '[data-agbrn]', 'click', (e, b) => { br.etape = +b.dataset.agbrn; M.rafraichir(); });
    M.on(sec, '[data-agpal]', 'click', (e, b) => { b.parentElement.querySelectorAll('.ag-swatch').forEach((x) => x.classList.toggle('on', x === b)); });
    M.on(sec, '[data-agfaux]', 'click', (e) => { e.preventDefault(); M.toast('Maquette : ouvrirait microsoft.com/devicelogin dans un nouvel onglet.', { ico: 'external' }); });
    sec.addEventListener('mika:seg', (e) => { if (e.detail.nom === 'agservice') { br.service = e.detail.valeur; M.rafraichir(); } });
    M.on(sec, '[data-agbr]', 'click', (e, b) => {
      const k = b.dataset.agbr;
      if (k === 'connecter') { br.etape = 2; M.toast('Maquette : la page de Google s\'ouvrirait dans un nouvel onglet.', { ico: 'globe' }); }
      if (k === 'coller') { br.etape = 3; M.toast('Code reçu : Google a dit oui.', { ico: 'check' }); }
      if (k === 'code') {
        br.etape = 2;
        const cle = br.cle;
        setTimeout(() => { if (br.cle === cle && br.etape === 2) { br.etape = 3; M.rafraichir(); M.toast('Connecté à Microsoft.', { ico: 'check' }); } }, 5000);
      }
      if (k === 'essayer') br.etape = 2;
      if (k === 'lire') { const l = sec.querySelector('[data-aglu]'); if (l) l.textContent = '24 sorties lues, de septembre 2026 à juin 2027.'; return; }
      if (k === 'fin') { br = { cle: null, etape: 1, service: br.service }; M.go('#parametres/agendas'); M.toast('Branché : ses agendas sont dans ton Agenda.', { ico: 'check' }); return; }
      M.rafraichir();
    });
  };
  P.recherche = () => [...recherche0(),
    { groupe: 'Paramètres', titre: 'Agendas', sous: 'tes comptes d\'agenda', ico: 'agenda', route: '#parametres/agendas' },
    { groupe: 'Paramètres', titre: 'Brancher un agenda', sous: 'Google, Outlook, CalDAV, iCal, ce serveur', ico: 'plus', route: '#parametres/agendas/brancher' },
    ...A.comptes.map((c) => ({ groupe: 'Paramètres', titre: `Compte d'agenda « ${c.nom} »`, sous: c.adresse, ico: 'agenda', route: '#parametres/agendas/' + c.id }))];
  P.notes = (ctx) => (ctx.onglet !== 'agendas' ? notes0(ctx) : [
    { groupe: 'Décidé le 2026-11-23', statut: 'decide', titre: 'Chacun branche ses agendas', texte: 'un compte d\'agenda est à quelqu\'un, comme une boîte ou un compte Teams (vide = à toi, elle, personne:<clé>) ; ses agendas ont leur couleur, leur place dans l\'Agenda, leur rappel', src: 'output/agenda/CONCEPTION.md · vocab/ownership.py' },
    { statut: 'decide', titre: 'Cinq sortes', texte: 'le système ; Google (OAuth 2, on colle l\'adresse de retour : Google refuse le code d\'appareil pour l\'agenda) ; Outlook.com / Microsoft 365 (code d\'appareil) ; CalDAV (DavMail pour Outlook pro, iCloud, Nextcloud, Fastmail) ; abonnement iCal en lecture seule' },
    { groupe: 'Ce qui existe déjà', statut: 'existe', titre: 'Le code d\'appareil Microsoft et son application', texte: 'pour les boîtes Outlook : la même application de l\'instance servira l\'agenda (Graph, Calendars.ReadWrite)', src: 'ADR 0166, 0238 · adapters/mail/oauth.py' },
    { statut: 'existe', titre: 'DavMail sur cette machine', texte: 'déjà la passerelle de la boîte Pro (IMAP) ; elle sert aussi CalDAV', src: 'Paramètres › Comptes mail › Pro' },
    { statut: 'existe', titre: 'Les réglages par personne, la page de compte', texte: 'le gabarit de Paramètres, la carte d\'un compte, son « Tester », sa barre d\'enregistrement' },
    { groupe: 'À faire', statut: 'manque', titre: 'Les comptes d\'agenda', texte: 'dans les réglages, par personne ; leurs secrets scellés ; la santé de leur synchro (lot 0)' },
    { statut: 'manque', titre: 'L\'application Google de l\'instance', texte: 'un client « Application de bureau » d\'un projet Google Cloud, réglé dans la console (comme l\'application Microsoft)' },
    { statut: 'manque', titre: 'Les parcours de branchement', texte: 'OAuth Google et l\'adresse collée, le code d\'appareil, l\'essai CalDAV (PROPFIND, les agendas trouvés), la lecture d\'un .ics (lots 1 et 2)' },
    { statut: 'manque', titre: 'L\'API', texte: '/api/moi/agenda/comptes : lister, brancher, régler, retirer ; protocole-moi.md (lot 4)' },
    { groupe: 'À trancher', statut: 'À trancher', titre: 'Le rappel par défaut de chaque sorte', texte: 'proposé : Système → Mika 30 min ; Google, Outlook, CalDAV → celui du fournisseur, et Mika selon l\'agenda (ici : Travail 15 min, Perso 30 min, Famille la veille au soir) ; un abonnement → aucun' },
    { statut: 'À trancher', titre: 'La fenêtre de synchronisation', texte: 'proposé : 90 jours derrière, un an devant, pour tous ; un abonnement se lit en entier' },
    { statut: 'À trancher', titre: 'Un partage dans Mika n\'est pas un partage chez Google', texte: 'l\'onglet Partage le dit, et montre à part le partage Google de « Famille » (Maman, Léa), qu\'on ne règle pas ici' },
    { statut: 'À trancher', titre: 'Un compte d\'agenda « à Mika »', texte: 'le choix existe, comme pour une boîte ; à quoi lui servirait un agenda à elle, hors de sa mémoire (l\'agenda d\'une équipe qu\'elle suit ?)' },
    { statut: 'À trancher', titre: 'Masquer, est-ce couper Mika ?', texte: 'proposé : un agenda masqué dans l\'Agenda reste branché, et Mika ne s\'en sert plus ; « coché » à gauche de l\'Agenda ne change que l\'affichage' },
    { statut: 'À trancher', titre: 'Outlook pro : Graph direct ou DavMail', texte: 'l\'organisation peut refuser l\'application : DavMail reste la voie sûre ; la maquette propose les deux' },
  ]);
})();
