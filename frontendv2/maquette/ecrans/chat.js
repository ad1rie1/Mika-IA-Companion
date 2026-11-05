/* Le chat : la conversation avec Mika, comme sur Android, et le mode pro tel que le client web le fait aujourd'hui
   (ADR 0116 : outils en direct, une bulle en Markdown ; ADR 0164 : les fils de travail ; ADR 0064/0165 : les cartes
   d'accord ; ADR 0170 : « Tout accepter » pour une opératrice ; ADR 0113 : 👍/👎 ; ADR 0119 : la bulle 📍). */
(function () {
  const { h, ico, av } = M;
  const D = M.D;

  // ── Les données de la conversation ────────────────────────────────────
  const conversation = [
    { jour: 'Hier' },
    { de: 'moi', t: '21:34', lu: true, txt: 'j\'ai écrit un mail au chef. je l\'envoie ce soir. il va comprendre sa douleur\n\n« Suite à la réunion de ce matin, je tiens à souligner que critiquer publiquement le travail de quelqu\'un ne relève pas du management mais de l\'humiliation. »' },
    { de: 'mika', t: '21:36', bulles: ['ta phrase est juste. je suis pas sûre qu\'elle soit utile ce soir', 'tu veux obtenir quoi, concrètement, en l\'envoyant ?'] },
    { de: 'moi', t: '21:38', lu: true, txt: 'qu\'il recommence pas' },
    { de: 'mika', t: '21:40', bulles: ['alors ce mail le fera pas. envoyé à 21h, sur ce ton, il va y lire de la colère, pas une limite. il va se défendre, et c\'est toi qui deviendras le sujet', 'demande-lui dix minutes demain, en tête-à-tête. tu lui dis la même chose, plus calmement. ça, il pourra le transférer à personne'] },
    { de: 'moi', t: '21:41', lu: true, txt: 't\'es chiante quand t\'as raison' },
    { de: 'mika', t: '21:41', bulles: ['je sais. garde le brouillon quand même, il est bien écrit'] },
    { jour: 'Aujourd\'hui' },
    { de: 'moi', t: '08:12', lu: true, txt: 'hello ça va ?' },
    { de: 'mika', t: '08:14', bulles: ['salut. ça va, un peu ailleurs', 'j\'ai passé une partie de la nuit sur des études sur les corneilles. elles reconnaissent le visage de quelqu\'un qui leur a fait du mal, et elles l\'apprennent à leurs petits'] },
    { de: 'moi', t: '08:18', lu: true, txt: 'profond pour 8h du mat 😅 faut que j\'y aille, réunion à 9h' },
    { de: 'mika', t: '08:18', bulles: ['vas-y. tu me raconteras'] },
    { de: 'moi', t: '13:52', lu: true, txt: 'tu peux regarder le mail de claire sur la présentation ? je sais pas trop quoi lui répondre' },
    { de: 'mika', t: '13:54', note: { ico: 'mail', txt: 'Mika a lu « Re: Présentation de jeudi » de Claire Dubois', route: '#mail/messages/m-claire' },
      bulles: ['je l\'ai lu. elle critique pas le fond, elle dit juste que la partie budget arrive trop tard et qu\'il faudrait un chiffre dès la deuxième slide', 'je t\'ai mis une réponse courte dans tes brouillons. tu me diras si le ton te va'],
      lien: { ico: 'pen', titre: 'Brouillon · Re: Présentation de jeudi', sous: 'Boîte Pro · à Claire Dubois', route: '#mail/messages/m-brouillon-claire' } },
    { de: 'moi', t: '14:05', lu: true, txt: 'parfait merci, je regarde', fichier: { image: true, nom: 'tableau-blanc.jpg', taille: '1,8 Mo' } },
    { de: 'mika', t: '14:06', bulles: ['joli tableau. c\'est toi qui as fait le schéma du milieu ?'] },
    { de: 'mika', t: '14:12', note: { ico: 'pin', txt: 'Mika a regardé où tu es · rue Nationale, Lille · position de 14:10' },
      bulles: ['au fait, Julien t\'a écrit sur WhatsApp pour la rando de dimanche. il attend juste un oui ou un non'],
      lien: { ico: 'phone', titre: 'Julien Roux · WhatsApp', sous: '« alors dimanche, tu viens ? départ 8h30 »', route: '#telephone/messages/julien' } },
    { de: 'moi', t: '18:40', lu: true, txt: 'tu m\'aides pour le road trip dans les Alpes ? cinq jours début avril, départ de Lille, j\'aimerais finir à Nice' },
    { de: 'mika', t: '18:43', note: { ico: 'search', txt: 'Mika a cherché des campings autour du lac d\'Annecy et calculé le trajet', route: '#carte/explorer' },
      bulles: ['je t\'ai fait une première version : Dijon le premier soir, deux nuits au bord du lac d\'Annecy, puis le Verdon avant Nice', 'j\'ai ajouté quatre arrêts, en rose. le Point Sublime, c\'est là que les gorges sont les plus belles. retire ce qui te plaît pas'],
      carte: { voyage: 'alpes', titre: 'Voyage · Les Alpes en cinq jours', sous: '5 jours · 1 388 km · 16 h 10 de route · 4 arrêts de Mika', route: '#carte/voyages/alpes' } },
  ];

  const fils = [
    { id: 'devis', titre: 'Devis Lefèvre — vérifier les montants', desc: 'Comparer le devis reçu ce matin au budget du projet Lumen, ligne par ligne.', t: '13:31', n: 6 },
    { id: 'nas', titre: 'Script de sauvegarde du NAS', desc: 'Un rsync nocturne vers le disque externe, avec un rapport par mail.', t: 'hier', n: 14 },
    { id: 'revue', titre: 'Préparer la revue de jeudi', desc: 'Points d\'avancement à partir des mails et de Teams de la semaine.', t: 'lun.', n: 9 },
    { id: 'mariadb', titre: 'Migration MariaDB du portable', desc: '', t: '28 oct.', n: 22, archive: true },
    { id: 'factures', titre: 'Factures d\'octobre', desc: '', t: '19 oct.', n: 5, archive: true },
  ];
  // Les vrais outils. Ses outils de courrier ne lisent pas les pièces (le nom et le nombre seulement) : le devis lui
  // arrive en pièce jointe du chat, qu'elle lit (ADR 0106). Le budget est dans l'app « Devis » de la Forge.
  // Un brouillon de mail pour tes boîtes n'a pas de carte d'accord : il attend dans Mail.
  const outilsDevis = [
    { nom: 'forge_db_query', arg: 'app « Devis » · budget du projet Lumen', ok: true, d: '410 ms', out: '11 lignes · budget validé le 12 oct. : 15 500 € TTC (dont 9 000 € de main-d\'œuvre)' },
    { nom: 'forge_db_query', arg: 'devis × budget, par poste', ok: false, d: '290 ms', out: 'Erreur : colonne « quantite » inconnue' },
    { nom: 'forge_db_query', arg: 'devis × budget, par poste, sans quantités', ok: true, d: '640 ms', out: '3 écarts au-dessus de 5 %' },
  ];
  const proDevis = [
    { de: 'moi', t: '13:31', txt: 'compare ce devis de Lefèvre Rénovation avec le budget du projet, ligne par ligne', fichier: { nom: 'devis-2026-114.pdf', taille: '212 Ko' } },
    { de: 'outils', t: '13:31', liste: outilsDevis, fini: true, duree: '1,3 s' },
    { de: 'pro', t: '13:32', html: `<p>Le devis dépasse le budget de <strong>1 240 €</strong> (+8 %). Trois postes expliquent l'écart :</p>
      <table><thead><tr><th>Poste</th><th class="r">Budget</th><th class="r">Devis</th><th class="r">Écart</th></tr></thead><tbody>
      <tr><td>Main-d'œuvre</td><td class="r">9 000 €</td><td class="r">9 860 €</td><td class="r up">+860 €</td></tr>
      <tr><td>Revêtement de sol</td><td class="r">2 400 €</td><td class="r">2 690 €</td><td class="r up">+290 €</td></tr>
      <tr><td>Éclairage</td><td class="r">1 300 €</td><td class="r">1 390 €</td><td class="r up">+90 €</td></tr>
      <tr><td>Les 8 autres postes</td><td class="r">2 800 €</td><td class="r">2 800 €</td><td class="r">0 €</td></tr>
      </tbody></table>
      <p>La main-d'œuvre est le seul poste sans quantité : je te propose de demander le détail des heures avant de discuter le prix.</p>` },
    { de: 'moi', t: '13:35', txt: 'ok, écris à Lefèvre pour demander le détail' },
    { de: 'outils', t: '13:35', liste: [
      { nom: 'email_contacts', arg: 'Lefèvre Rénovation', ok: true, d: '210 ms', out: 'devis@lefevre-renovation.fr · 2 reçus · 0 envoyé · il y a 4 h' },
      { nom: 'email_draft', arg: 'boîte Pro → devis@lefevre-renovation.fr', ok: true, d: '2,4 s', out: 'Brouillon proposé : il partira quand Adrien l\'aura approuvé (il reste un passage à compléter).' },
    ], fini: true, duree: '2,6 s' },
    { de: 'pro', t: '13:36', html: `<p>Brouillon prêt dans ta boîte Pro, il attend ton accord. J'ai laissé la <strong>date de début</strong> à compléter : je ne la connais pas.</p>`,
      lien: { ico: 'pen', titre: 'Brouillon · Re: Devis n° 2026-114', sous: 'Boîte Pro · à devis@lefevre-renovation.fr · à compléter', route: '#mail/messages/d-lefevre' } },
  ];

  // ── L'état de l'écran ─────────────────────────────────────────────────
  const etat = { pro: false, fil: 'devis', accord: 'demander', archives: false, carte: true, carteRes: null, cartePro: false };
  try { etat.pro = sessionStorage.getItem('mika-maquette-pro') === '1'; } catch (e) { /* rien */ }
  if (new URLSearchParams(location.search).get('pro') === '1') etat.pro = true;   // pour les captures

  // ── Les pièces de la conversation ─────────────────────────────────────
  function bulleMoi(m) {
    const f = m.fichier ? `<div class="msg-file${m.fichier.image ? ' img' : ''}">${m.fichier.image
      ? `<span class="ph-img">${ico('image', 'lg')}</span><span class="mf-cap">${h(m.fichier.nom)} · ${h(m.fichier.taille)}</span>`
      : `${ico('file')}<b>${h(m.fichier.nom)}</b><span class="muted">${h(m.fichier.taille)}</span>`}</div>` : '';
    return `<div class="msg me">${f}<div class="bubble">${texte(m.txt)}</div>
      <div class="msg-meta">${h(m.t)}${m.lu ? ` · ${ico('checks', 'xs')} lu` : ` · ${ico('check', 'xs')} envoyé`}</div></div>`;
  }
  function bulleMika(m, i) {
    const note = m.note ? `<a class="msg-note"${m.note.route ? ` href="${m.note.route}"` : ''}>${ico(m.note.ico, 'xs')}${h(m.note.txt)}</a>` : '';
    const lien = m.lien ? `<a class="msg-link" href="${m.lien.route}">${ico(m.lien.ico)}<span><b>${h(m.lien.titre)}</b><small>${h(m.lien.sous)}</small></span>${ico('chev-right', 'sm')}</a>` : '';
    // Sa carte (ADR à écrire) : la note de message « voyage: » ou « carte: », en carte miniature qui s'ouvre dans Carte.
    const carte = m.carte ? `<a class="msg-map" href="${m.carte.route}">${M.carteMini ? M.carteMini(m.carte.voyage) : ''}
      <span class="mm-text">${ico('map')}<span><b>${h(m.carte.titre)}</b><small>${h(m.carte.sous)}</small></span>${ico('chev-right', 'sm')}</span></a>` : '';
    return `<div class="msg her">${av('mika', 'sm')}<div class="msg-col">${note}
      ${m.bulles.map((b) => `<div class="bubble">${texte(b)}</div>`).join('')}${lien}${carte}
      <div class="msg-meta">${h(m.t)}${D.moi.operatrice ? `<span class="verdict"><button type="button" title="Bonne réponse" data-verdict="up">${ico('thumb-up', 'xs')}</button><button type="button" title="Elle aurait dû dire autre chose" data-verdict="down">${ico('thumb-down', 'xs')}</button></span>` : ''}</div></div></div>`;
  }
  function carteOutils(m) {
    const ko = m.liste.filter((o) => !o.ok && !o.encours).length;
    const resume = m.fini ? `${m.liste.length} outils${ko ? ` · ${ko} échec${ko > 1 ? 's' : ''}` : ''} · ${m.duree}` : `Au travail… · ${m.liste.length} outils`;
    return `<details class="tools-card${m.fini ? '' : ' live'}"${m.fini ? '' : ' open'}><summary>${ico('terminal', 'sm')}<b>Son travail</b><span class="muted">${h(resume)}</span>${ico('chev-down', 'sm')}</summary>
      <ol>${m.liste.map((o) => `<li class="${o.encours ? 'run' : o.ok ? 'ok' : 'ko'}"><span class="st">${o.encours ? '<i class="spin"></i>' : ico(o.ok ? 'check' : 'x', 'xs')}</span>
        <code>${h(o.nom)}</code><span class="arg">${h(o.arg)}</span><span class="d">${h(o.d)}</span>${o.out ? `<pre>${h(o.out)}</pre>` : ''}</li>`).join('')}</ol></details>`;
  }
  function bullePro(m) {
    const lien = m.lien ? `<a class="msg-link" href="${m.lien.route}">${ico(m.lien.ico)}<span><b>${h(m.lien.titre)}</b><small>${h(m.lien.sous)}</small></span>${ico('chev-right', 'sm')}</a>` : '';
    return `<div class="msg pro">${av('mika', 'sm')}<div class="msg-col"><div class="bubble md">${m.html}</div>${lien}
      <div class="msg-meta">${h(m.t)} · mode pro</div></div></div>`;
  }
  function texte(s) { return h(s).split('\n\n').map((p) => p.replace(/\n/g, '<br>')).join('<br><br>'); }

  function carteAccord(pro) {
    if (pro ? !etat.cartePro : !etat.carte) return '';
    if (etat.carteRes) return `<div class="approval done">${ico(etat.carteRes === 'ok' ? 'check' : 'x')}<span>${etat.carteRes === 'ok' ? 'Accepté : c\'est parti.' : 'Refusé : rien ne partira.'}</span></div>`;
    const c = pro ? {
      phrase: 'Mika voudrait créer un devis révisé pour Lumen Conseil dans « factures »', titre: 'Appeler « devis_create » (factures) : {"client": "Lumen Conseil"}', exp: 'expire dans 9 min',
      garde: 'un savoir',
      brut: '{\n  "client": "Lumen Conseil",\n  "objet": "Salle de réunion — devis révisé",\n  "montant_ht": 13950\n}',
    } : {
      phrase: 'Mika voudrait demander la météo de dimanche à Cassel au service « meteo »', titre: 'Appeler « prevision » (meteo) : {"ville": "Cassel"}', exp: 'expire dans 4 min',
      garde: 'un souvenir — comme ce qu\'on lui raconte',
      brut: '{\n  "ville": "Cassel",\n  "jour": "2026-11-08",\n  "details": ["pluie", "vent"]\n}',
    };
    return `<div class="approval">
      <div class="ap-line">${ico('shield')}<div class="ap-main"><b>${h(c.phrase)}</b><span class="ap-meta">Mika demande ton accord · <span class="ap-exp">${h(c.exp)}</span></span></div>
        <button class="btn sm" type="button" data-ap="non">Refuser</button><button class="btn sm primary" type="button" data-ap="ok">${ico('check', 'sm')}Accepter</button></div>
      <details class="ap-more"><summary>${ico('chev-right', 'xs')}Voir exactement ce qui partira <span class="muted">· elle en gardera : ${h(c.garde)}</span></summary>
        <div class="ap-what">${h(c.titre)}</div><pre class="ap-raw">${h(c.brut)}</pre>
        <p class="ap-help">Seuls ces boutons décident : un « oui » tapé dans la conversation ne vaut pas accord.</p></details></div>`;
  }

  function composer() {
    return `<div class="composer${etat.pro ? ' pro' : ''}">
      <div class="cmp-attach" data-attach hidden></div>
      <textarea data-chat-input rows="1" placeholder="${etat.pro ? 'Une tâche pour Mika… (/ pour les commandes du fil)' : 'Écrire à Mika…'}"></textarea>
      <div class="cmp-bar">
        <button class="btn icon ghost sm" type="button" data-cmp="joindre" title="Joindre des fichiers (5 au plus, 5 Mo chacun)">${ico('clip')}</button>
        <button class="btn icon ghost sm" type="button" data-cmp="emoji" title="Emojis">${ico('smile')}</button>
        ${etat.pro ? `<button class="btn ghost sm" type="button" data-cmp="commandes" title="Commandes du fil">/<span class="lbl"> commandes</span></button>` : ''}
        <span class="grow"></span>
        ${D.moi.operatrice ? `<button class="pill-toggle${etat.accord === 'tout' ? ' bolt' : ''}" type="button" data-cmp="accord" title="${etat.accord === 'tout' ? 'Chaque carte acceptable part acceptée, une à la fois (pour cet onglet)' : 'Chaque appel extérieur attend ta carte d\'accord'}">
          ${ico(etat.accord === 'tout' ? 'bolt' : 'shield', 'sm')}<span class="lbl">${etat.accord === 'tout' ? 'Tout accepter' : 'Accords : un par un'}</span></button>
        <button class="pill-toggle pro${etat.pro ? ' on' : ''}" type="button" data-cmp="pro" aria-pressed="${etat.pro}" title="Mode pro : sans son caractère, outils en direct, fils de travail">${ico('terminal', 'sm')}<span>Pro</span></button>` : ''}
        <button class="btn primary sm" type="button" data-cmp="envoyer">${ico('send', 'sm')}<span class="lbl">Envoyer</span></button>
      </div></div>`;
  }

  // Sa colonne, en haut à droite du chat : sa VRM en grand, puis ce qu'elle vit (les sections de « Ce qu'elle fait »).
  function colonneMika() {
    const m = D.mika;
    return `<aside class="chat-mika" aria-label="Mika">
      <div class="cm-scene" data-mika-scene></div>
      <div class="cm-who"><b>Mika</b><span>${h(m.etat === 'dort' ? 'dort' : 'éveillée')} · ${h(m.fait)} · ${h(m.humeurDite)}</span></div>
      <div class="cm-body">
        <section><h4>Humeur</h4>${m.facettes.map(([n, v]) => `<div class="facet"><span>${h(n)}</span><span class="bar"><i style="width:${Math.round(v * 100)}%"></i></span><span class="num">${Math.round(v * 100)} %</span></div>`).join('')}</section>
        <section><h4>Elle repense à…</h4><p>${h(m.repense)}</p></section>
        <section><h4>Ce qu'elle t'a promis</h4>${m.promesses.map(([t, q]) => `<div class="sc-line">${ico('check', 'sm')}<span>${h(t)} <span class="muted">· ${h(q)}</span></span></div>`).join('')}</section>
        <button class="btn sm ghost cm-more" type="button" data-head="etat">${ico('sparkle', 'sm')}Tout ce qu'elle fait</button>
      </div></aside>`;
  }

  function vueOrdinaire() {
    return `<div class="chat-split"><div class="chat-wrap"><div class="chat-col">
      <div class="chat-scroll" data-scroll><div class="chat-thread">${conversation.map((m, i) =>
        m.jour ? `<div class="day"><span>${h(m.jour)}</span></div>` : m.de === 'moi' ? bulleMoi(m) : bulleMika(m, i)).join('')}
        <div class="msg her typing-row" data-typing hidden>${av('mika', 'sm')}<div class="bubble typing"><i></i><i></i><i></i></div></div>
      </div></div>
      <div class="chat-dock">${carteAccord(false)}${composer()}</div></div></div>${colonneMika()}</div>`;
  }

  function vuePro() {
    const actifs = fils.filter((f) => !f.archive), archives = fils.filter((f) => f.archive);
    const f = fils.find((x) => x.id === etat.fil) || fils[0];
    const messages = f.id === 'devis' ? proDevis : f.n === 0 ? [] : [{ de: 'moi', t: f.t, txt: f.desc || f.titre }, { de: 'pro', t: f.t, html: '<p>Ce fil a son propre contexte : je n\'y relis que ses messages, sous son titre et sa description.</p>' }];
    const vide = `<div class="empty">${ico('threads')}<b>Un fil à part</b><p>Mika n'y relit que ce qui s'y dit. Demande-lui un travail ; /aide pour les commandes.</p></div>`;
    const li = (x) => `<button class="li${x.id === f.id ? ' on' : ''}" type="button" data-fil="${x.id}"><span class="li-main">
      <span class="li-top"><span class="li-title">${h(x.titre)}</span><time>${h(x.t)}</time></span>
      <span class="li-snip">${h(x.desc || 'Sans description')}</span></span></button>`;
    return `<div class="split pro-split">
      <aside class="pane fils-pane">
        <div class="pane-head"><h2>Fils de travail</h2><span class="cnt">${actifs.length}</span><span class="grow"></span>
          <button class="btn sm" type="button" data-cmd="nouveau" title="Ouvrir un fil neuf (/clear)">${ico('plus', 'sm')}Nouveau</button></div>
        <div class="pane-scroll">${actifs.map(li).join('')}
          <button class="group-label as-btn" type="button" data-archives>${ico(etat.archives ? 'chev-down' : 'chev-right', 'xs')}Archivés<span class="cnt">${archives.length}</span></button>
          ${etat.archives ? archives.map(li).join('') : ''}</div>
        <div class="pane-foot small muted">Le fil avec Mika est caché en mode pro ; il revient quand tu l'éteins.</div>
      </aside>
      <section class="pane chat-pro">
        <div class="pane-head strand-head"><button class="btn sm icon ghost mobile-back" type="button" data-fils-mobile title="Les fils">${ico('threads', 'sm')}</button><div class="grow"><h2>${h(f.titre)}</h2><p class="small muted ellipsis">${h(f.desc || 'Ajoute une petite description : c\'est tout le contexte du fil.')}</p></div>
          <button class="btn icon ghost sm" type="button" data-cmd="renommer" title="Titre et description">${ico('pen', 'sm')}</button>
          <button class="btn icon ghost sm" type="button" data-cmd="archiver" title="Archiver le fil">${ico('archive', 'sm')}</button></div>
        <div class="chat-scroll" data-scroll>${messages.length ? `<div class="chat-thread wide">${messages.map((m) =>
          m.de === 'moi' ? bulleMoi(m) : m.de === 'outils' ? carteOutils(m) : bullePro(m)).join('')}</div>` : vide}</div>
        <div class="chat-dock wide">${carteAccord(true)}${composer()}</div>
      </section></div>`;
  }

  function enBas(body) { const s = body.querySelector('[data-scroll]'); if (s) s.scrollTop = s.scrollHeight; }

  // ── Les réponses simulées ─────────────────────────────────────────────
  const reponses = [
    ['d\'accord. je regarde ça et je te dis'],
    ['oui, je m\'en souviens', 'tu veux que je te le prépare maintenant ou ça peut attendre ce soir ?'],
    ['bonne idée. je note'],
  ];
  let tour = 0;
  function envoyer(body) {
    const ta = body.querySelector('[data-chat-input]');
    const txt = ta.value.trim();
    if (!txt) return;
    if (etat.pro && txt.startsWith('/') && !txt.startsWith('//')) { commande(txt.split(/\s+/)[0], body); ta.value = ''; return; }
    if (etat.pro) {
      proDevis.push({ de: 'moi', t: D.maintenant.heure, txt });
      M.rafraichir();
      M.toast('Maquette : en mode pro, ses outils s\'afficheraient ici en direct.', { mika: true, ico: 'terminal' });
      return;
    }
    conversation.push({ de: 'moi', t: D.maintenant.heure, txt, lu: false });
    M.rafraichir();
    const typing = document.querySelector('[data-typing]');
    setTimeout(() => {
      if (typing) typing.hidden = false;
      M.mika.typing(true);
      M.mika.set({ etat: 'ecrit', fait: 'en train d\'écrire…' });
      enBas(body);
    }, 700);
    setTimeout(() => {
      M.mika.typing(false);
      M.mika.set({ etat: 'eveillee', fait: 'travaille à son bureau' });
      conversation[conversation.length - 1].lu = true;
      conversation.push({ de: 'mika', t: D.maintenant.heure, bulles: reponses[tour++ % reponses.length] });
      M.rafraichir();
      M.mika.talk(2200);
    }, 2600);
  }
  function commande(cmd, body) {
    const f = fils.find((x) => x.id === etat.fil);
    if (cmd === '/clear' || cmd === '/nouveau') { fils.unshift({ id: 'neuf' + fils.length, titre: 'Nouveau fil', desc: '', t: D.maintenant.heure, n: 0 }); etat.fil = fils[0].id; M.rafraichir(); M.toast('Fil neuf ouvert : rien n\'est effacé.', { ico: 'threads' }); }
    else if (cmd === '/archiver' && f) { f.archive = true; etat.fil = fils.find((x) => !x.archive).id; M.rafraichir(); M.toast('Fil archivé', { ico: 'archive' }); }
    else if (cmd === '/renommer' || cmd === '/description') renommer();
    else menuCommandes(body.querySelector('[data-cmp="commandes"]') || body);
  }
  function menuCommandes(ancre) {
    M.menu(ancre, [
      { entete: 'Commandes du fil' },
      { label: '/clear — ouvrir un fil neuf', ico: 'plus', action: () => commande('/clear') },
      { label: '/renommer <titre>', ico: 'pen', action: renommer },
      { label: '/description <texte>', ico: 'threads', action: renommer },
      { label: '/archiver', ico: 'archive', action: () => commande('/archiver') },
      { label: '/aide', ico: 'info', action: () => M.toast('// en tête envoie le message avec un seul /.', { ico: 'info' }) },
    ], { align: 'left' });
  }
  function renommer() {
    const f = fils.find((x) => x.id === etat.fil);
    const el = M.modal({ titre: 'Le fil', taille: 'narrow',
      corps: `<div class="stack"><label class="field"><span>Titre</span><input data-f="titre" value="${h(f.titre)}"></label>
        <label class="field"><span>Petite description</span><textarea data-f="desc" rows="3" placeholder="Ce que Mika doit savoir de ce fil, et rien d'autre.">${h(f.desc)}</textarea></label></div>`,
      pied: `<span class="grow"></span><button class="btn" type="button" data-close>Annuler</button><button class="btn primary" type="button" data-ok>Enregistrer</button>` });
    el.querySelector('[data-ok]').addEventListener('click', () => {
      f.titre = el.querySelector('[data-f="titre"]').value || f.titre;
      f.desc = el.querySelector('[data-f="desc"]').value;
      M.fermerModal(); M.rafraichir();
    });
  }
  function emojis(ancre, body) {
    const liste = ['😊', '😅', '😂', '🙂', '😉', '😍', '🥲', '😴', '🤔', '😬', '🙏', '👍', '👌', '🔥', '✨', '❤️', '💪', '🎉', '☕', '🌧️', '🚶', '📎', '✅', '❌'];
    const m = M.menu(ancre, [{ html: `<div class="emoji-grid">${liste.map((e) => `<button type="button" data-emo="${e}">${e}</button>`).join('')}</div>` }], { align: 'left' });
    M.on(m, '[data-emo]', 'click', (e, b) => { const ta = body.querySelector('[data-chat-input]'); ta.value += b.dataset.emo; ta.focus(); });
  }

  // ── L'écran ───────────────────────────────────────────────────────────
  M.register('chat', {
    titre: 'Chat',
    sousTitre: () => (etat.pro ? 'mode pro · ' + fils.filter((f) => !f.archive).length + ' fils' : 'Mika · en ligne'),
    actions: () => `<button class="btn icon ghost" type="button" data-head="chercher" title="Chercher dans la conversation">${ico('search')}</button>
      <button class="btn ghost sm" type="button" data-head="fichiers" title="Les fichiers échangés">${ico('clip', 'sm')}<span class="lbl">Fichiers</span></button>`,
    monte(sec) {
      M.on(sec, '[data-head]', 'click', (e, b) => {
        const k = b.dataset.head;
        if (k === 'etat') document.getElementById('state-pill').click();
        if (k === 'fichiers') M.modal({ titre: 'Les fichiers échangés', corps: `<table class="tbl"><thead><tr><th>Fichier</th><th>De</th><th>Quand</th><th></th></tr></thead><tbody>
          <tr><td>${ico('image', 'sm')} tableau-blanc.jpg</td><td>toi</td><td>aujourd'hui 14:05</td><td class="actions"><button class="btn xs">${ico('download', 'xs')}Enregistrer</button></td></tr>
          <tr><td>${ico('file', 'sm')} comparatif-devis-lefevre.csv</td><td>Mika</td><td>aujourd'hui 13:32</td><td class="actions"><button class="btn xs">${ico('download', 'xs')}Enregistrer</button></td></tr>
          <tr><td>${ico('file', 'sm')} slides-lumen-v3.pdf</td><td>toi</td><td>dim. 1 nov.</td><td class="actions"><button class="btn xs">${ico('download', 'xs')}Enregistrer</button></td></tr></tbody></table>` });
        if (k === 'chercher') M.toast('Maquette : la recherche filtrerait la conversation.', { ico: 'search' });
      });
      M.on(sec, '[data-cmp]', 'click', (e, b) => {
        const body = sec.querySelector('.page-body');
        const k = b.dataset.cmp;
        if (k === 'pro') {
          etat.pro = !etat.pro;
          try { sessionStorage.setItem('mika-maquette-pro', etat.pro ? '1' : '0'); } catch (err) { /* rien */ }
          M.rafraichir();
          M.toast(etat.pro ? 'Mode pro : sans son caractère, ses outils en direct, tes fils de travail.' : 'Retour à la conversation avec Mika.', { ico: 'terminal' });
        }
        if (k === 'accord') { etat.accord = etat.accord === 'tout' ? 'demander' : 'tout'; M.rafraichir(); }
        if (k === 'envoyer') envoyer(body);
        if (k === 'emoji') emojis(b, body);
        if (k === 'commandes') menuCommandes(b);
        if (k === 'joindre') {
          const z = body.querySelector('[data-attach]');
          z.hidden = false;
          z.innerHTML = `<span class="chip">${ico('file', 'xs')}compte-rendu-reunion.pdf<span class="muted">412 Ko</span><button type="button" title="Retirer" data-unattach>${ico('x', 'xs')}</button></span>`;
        }
      });
      M.on(sec, '[data-unattach]', 'click', (e, b) => { const z = b.closest('[data-attach]'); z.hidden = true; z.innerHTML = ''; });
      M.on(sec, '[data-ap]', 'click', (e, b) => {
        etat.carteRes = b.dataset.ap;
        M.rafraichir();
        setTimeout(() => { if (etat.pro) etat.cartePro = false; else etat.carte = false; etat.carteRes = null; M.rafraichir(); }, 1600);
      });
      M.on(sec, '[data-fil]', 'click', (e, b) => { etat.fil = b.dataset.fil; M.rafraichir(); });
      M.on(sec, '[data-archives]', 'click', () => { etat.archives = !etat.archives; M.rafraichir(); });
      M.on(sec, '[data-fils-mobile]', 'click', (e, b) => M.menu(b, [{ entete: 'Fils de travail' },
        ...fils.filter((f) => !f.archive).map((f) => ({ label: f.titre, ico: f.id === etat.fil ? 'check' : 'threads', action: () => { etat.fil = f.id; M.rafraichir(); } })),
        'sep', { label: 'Nouveau fil', ico: 'plus', action: () => commande('/clear') }], { align: 'left' }));
      M.on(sec, '[data-cmd]', 'click', (e, b) => commande('/' + (b.dataset.cmd === 'nouveau' ? 'clear' : b.dataset.cmd), sec.querySelector('.page-body')));
      M.on(sec, '[data-verdict]', 'click', (e, b) => {
        if (b.dataset.verdict === 'up') { b.classList.add('on'); M.toast('Noté : bonne réponse.', { ico: 'thumb-up' }); }
        else M.modal({ titre: 'Ce qu\'elle aurait dû dire', taille: 'narrow',
          corps: '<p class="text-2 small" style="margin-bottom:8px">Ta version reste à côté de la sienne, comme exemple (ADR 0113).</p><textarea rows="4" placeholder="Ce qu\'elle aurait dû répondre…"></textarea>',
          pied: '<span class="grow"></span><button class="btn" type="button" data-close>Annuler</button><button class="btn primary" type="button" data-close>Enregistrer</button>' });
      });
      sec.addEventListener('keydown', (e) => {
        if (e.target.matches('[data-chat-input]') && e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); envoyer(sec.querySelector('.page-body')); }
        if (e.target.matches('[data-chat-input]') && e.key === '/' && etat.pro && !e.target.value) setTimeout(() => menuCommandes(sec.querySelector('[data-cmp="commandes"]')), 0);
      });
      sec.addEventListener('input', (e) => {
        if (e.target.matches('[data-chat-input]')) { e.target.style.height = 'auto'; e.target.style.height = Math.min(e.target.scrollHeight, 180) + 'px'; }
      });
    },
    rendu(body) {
      body.innerHTML = etat.pro ? vuePro() : vueOrdinaire();
      enBas(body);
    },
    notes: () => [
      { groupe: 'Ce qui marche déjà', statut: 'existe', titre: 'Le chat limité au compte connecté', texte: 'fil, fichiers, cartes d\'accord et position passent par le moyen de communication du compte', src: 'adapters/web/app.py:714-743 · hub.py' },
      { statut: 'existe', titre: 'Ses bulles, ses fichiers, la bulle 📍', texte: 'trame speech (bulles séparées par une ligne vide), GET /files/<id>, notes de message', src: 'protocol.py:335-372 · app.py:513-539' },
      { statut: 'existe', titre: 'Cartes d\'accord', texte: 'approvals / approval / approval_result, avec « Ce qu\'elle en gardera »', src: 'mindport.py:454-507 · plugins/mcp/calls.py:36' },
      { statut: 'existe', titre: 'Mode pro, « Son travail », fils, 👍/👎', texte: 'réservés à un opérateur authentifié : une seule garde côté serveur', src: 'app.py:1318 · hub.py:216-230' },
      { statut: 'existe', titre: '« Tout accepter »', texte: 'vaut pour l\'onglet (sessionStorage), le serveur ne voit qu\'une trame approval ordinaire', src: 'ADR 0170 · frontend/Web/src/ui/approvals.ts' },
      { statut: 'existe', titre: '« Ce qu\'elle fait »', texte: 'trame inner_state_update ; ses sections suivent tes droits', src: 'protocol.py:468-521 · mindport.py:312-354' },
      { groupe: 'À faire ou à décider', statut: 'partiel', titre: '« Mika écrit… »', texte: 'aucune trame typing : le client le déduit de l\'envoi jusqu\'à sa réponse' },
      { statut: 'partiel', titre: '« Lu »', texte: 'le serveur connaît la trame read, le web ne l\'envoie pas (Android oui)', src: 'app.py:953-993' },
      { statut: 'partiel', titre: 'Sa VRM, en haut à droite', texte: 'le corps du web se réutilise sans la pièce ni le monde ; muette (la voix serait celle du navigateur) ; 97 Mio, ou 28 Mio préparé pour Android, ou les portraits', src: 'frontend/Web/src/vtuber · frontend/Android/tools/vrm_mobile.py' },
      { statut: 'manque', titre: 'Remonter au-delà des 50 derniers messages', texte: 'sync ne rend que l\'après ; seul strand_history accepte before' },
      { statut: 'manque', titre: 'Chercher, effacer ou modifier un message', texte: 'aucune trame ; le 🗑️ du web ne vide que l\'affichage' },
      { statut: 'manque', titre: 'Revoir les fichiers que tu as envoyés', texte: '/files ne sert que les siens' },
      { statut: 'manque', titre: 'Être prévenu dans le navigateur', texte: 'pas de Web Push : Firebase sert seulement le téléphone' },
    ],
    recherche: () => [
      ...conversation.filter((m) => m.de).slice(-6).map((m) => ({ groupe: 'Conversation', titre: (m.txt || m.bulles[0]).slice(0, 70), sous: `${m.de === 'moi' ? 'Toi' : 'Mika'} · ${m.t}`, ico: 'chat', route: '#chat' })),
      ...fils.map((f) => ({ groupe: 'Fils de travail', titre: f.titre, sous: f.desc, ico: 'terminal', action: () => { etat.pro = true; etat.fil = f.id; M.go('#chat'); } })),
    ],
  });
})();
