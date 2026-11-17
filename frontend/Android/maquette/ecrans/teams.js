/* Teams : tes discussions comme dans Teams (l'extension « Mika · Teams » lit ce que Teams web reçoit et pose ce qui
   part, ADR 0069). Tu réponds toi-même, ou tu demandes à Mika de préremplir ; ce qu'elle a préparé t'attend en carte
   rose au-dessus du champ, et dans « Ses brouillons ». */
(function () {
  const { h, ico, av, who, D } = A;

  const DISC = [
    { id: 'lumen', groupe: true, titre: 'Projet Lumen', membres: ['claire', 'sophie', 'karim'], nonlus: 3, mention: true, t: '12:58', dernier: 'Karim : la démo tourne sur la préprod 🎉', msgs: [
      { jour: 'Aujourd\'hui' },
      { de: 'claire', t: '10:02', txt: 'Bonjour à tous, point d\'étape : la maquette est validée côté client 🎉', reac: [['🎉', 3]] },
      { de: 'karim', t: '10:05', txt: 'top ! je pousse la démo sur la préprod cet aprem' },
      { de: 'adrien', t: '10:11', txt: 'Bravo à tous. Je prépare le support pour jeudi.' },
      { de: 'sophie', t: '12:40', txt: '@Adrien Moreau tu peux valider les chiffres du T3 avant jeudi ? Je les ai mis dans le dossier partagé.', mention: true, piece: 'chiffres-T3-v2.xlsx · 84 Ko' },
      { de: 'karim', t: '12:58', txt: 'la démo tourne sur la préprod 🎉', reac: [['🎉', 2], ['👍', 1]] },
    ], brouillon: { txt: 'Je regarde les chiffres demain matin et je te dis avant midi.', etat: 'pose', t: '12:59' } },
    { id: 'claire', qui: 'claire', titre: 'Claire Dubois', nonlus: 1, t: '13:41', dernier: 'Rien de grave hein, juste la partie budget qui arrive tard 🙂', msgs: [
      { jour: 'Aujourd\'hui' },
      { de: 'claire', t: '13:38', txt: 'Tu as vu mon mail sur la présentation ?' },
      { de: 'claire', t: '13:41', txt: 'Rien de grave hein, juste la partie budget qui arrive tard 🙂' },
    ], brouillon: { txt: 'Oui je l\'ai vu, merci ! Je te réponds par mail avant ce soir.', etat: 'accord', t: '13:42' } },
    { id: 'marc', qui: 'marc', titre: 'Marc Delmas', t: '11:32', dernier: 'Merci pour l\'échange de ce matin. Tu as eu raison de m\'en parler.', msgs: [
      { jour: 'Hier' }, { de: 'adrien', t: '21:55', txt: 'Bonsoir Marc, tu aurais dix minutes demain matin ? J\'aimerais revenir sur la réunion.' }, { de: 'marc', t: '22:10', txt: 'Oui. 11h dans mon bureau.' },
      { jour: 'Aujourd\'hui' }, { de: 'marc', t: '11:32', txt: 'Merci pour l\'échange de ce matin. Tu as eu raison de m\'en parler. On en reparle vendredi.' },
    ] },
    { id: 'sophie', qui: 'sophie', titre: 'Sophie Laurent', t: '10:20', dernier: 'chiffres-T3-v2.xlsx', msgs: [{ jour: 'Aujourd\'hui' }, { de: 'sophie', t: '10:18', txt: 'Je t\'envoie le fichier des chiffres, dis-moi si les formules te vont', piece: 'chiffres-T3-v2.xlsx · 84 Ko' }] },
    { id: 'cafe', groupe: true, titre: 'Café ☕', membres: ['nadia', 'karim', 'sophie'], t: '09:47', dernier: 'Toi (par Mika) : J\'arrive !', msgs: [{ jour: 'Aujourd\'hui' }, { de: 'nadia', t: '09:47', txt: 'Gâteau en salle 3 à 16h pour l\'anniversaire de Karim 🎂', reac: [['🎂', 5]] }, { de: 'adrien', t: '09:50', txt: 'J\'arrive !', mika: true }] },
    { id: 'karim', qui: 'karim', titre: 'Karim Haddad', t: 'hier', dernier: 'Toi (par Mika) : Je regarde ta PR demain matin.', msgs: [{ jour: 'Hier' }, { de: 'karim', t: '17:20', txt: 'tu peux relire ma PR sur l\'export CSV quand tu as 5 min ?' }, { de: 'adrien', t: '17:26', txt: 'Je regarde ta PR demain matin.', mika: true }] },
    { id: 'hebdo', groupe: true, titre: 'Réunion hebdo Lumen', membres: ['marc', 'claire', 'sophie'], t: 'lun.', dernier: 'Marc : Merci à tous, compte rendu dans la journée.', msgs: [{ jour: 'Lundi 2 novembre' }, { de: 'marc', t: '10:47', txt: 'Merci à tous, compte rendu dans la journée.' }] },
  ];
  const disc = (id) => DISC.find((d) => d.id === id) || DISC[0];
  const tete = (d) => (d.groupe ? A.grp(ico('users', 'sm')) : av(d.qui));

  function vueListe() {
    return {
      nav: 'teams', racine: true,
      html: `${A.top({ racine: true, title: 'Teams', sub: `Lumen Conseil · a.moreau@lumen-conseil.fr`, small: true, actions: [A.act('search', 'Chercher', 'data-go="#recherche"')] })}
        ${A.chips([{ l: 'Tout', radio: 't', on: true }, { l: 'Non lus', radio: 't', n: 2 }, { l: 'Mentions', radio: 't', ico: 'at' }, { l: 'Groupes', radio: 't' }])}
        <div class="body" style="padding-bottom:84px">
          <div style="padding:4px 16px 6px"><button class="mk-line" type="button" data-go="#teams/brouillons">${ico('pen')}<span class="grow"><b>Ses brouillons</b><small>1 attend ton accord · 1 posé dans Teams</small></span><span class="cnt-pill mk">1</span></button></div>
          ${DISC.map((d) => `<button class="li${d.nonlus ? ' unread' : ''}" type="button" data-go="#teams/d/${d.id}">${tete(d)}<span class="txt"><b>${h(d.titre)}</b><small>${d.brouillon ? `<span class="mk-txt">${ico('pen', 'xxs')} Mika · </span>` : ''}${h(d.dernier)}</small></span>
            <span class="trail"><span class="t">${h(d.t)}</span>${d.mention ? `<span class="row" style="gap:3px;color:var(--primary)">${ico('at', 'xxs')}<span class="cnt-pill">${d.nonlus}</span></span>` : d.nonlus ? `<span class="cnt-pill">${d.nonlus}</span>` : ''}</span></button>`).join('')}
        </div>
        <button class="fab" type="button" data-snack="Maquette : nouvelle discussion">${ico('pen')}Nouvelle</button>`,
      notes: {
        titre: 'Teams',
        reprend: ['Tes discussions (un tête-à-tête au nom de l\'autre), les non-lus et les mentions.', '« Ses brouillons » en tête, comme dans Mail ; la discussion où elle a préparé quelque chose le dit en rose.', 'Un compte qu\'on te partage se choisit par le titre (pas d\'exemple ici : tu n\'en as qu\'un).'],
        trancher: ['Le bouton « Nouvelle » discussion : utile ici, ou à retirer (l\'extension ne sait que répondre) ?'],
      },
    };
  }

  function vueFil(id) {
    const d = disc(id);
    const sous = d.groupe ? d.membres.map((k) => who(k).court).join(', ') + ', toi' : 'Lumen Conseil · en ligne';
    const msgs = d.msgs.map((m) => {
      if (m.jour) return `<div class="day">${h(m.jour)}</div>`;
      const moi = m.de === 'adrien';
      const p = m.piece ? `<div class="msg-file" style="margin-top:4px">${ico('file')}<span style="font-size:13px">${h(m.piece)}</span></div>` : '';
      const reac = m.reac ? `<div class="reac">${m.reac.map(([e, n]) => `<span>${e} ${n}</span>`).join('')}</div>` : '';
      return `<div class="tmsg${moi ? ' me' : ''}">${moi ? '' : av(m.de, 'sm')}<div>${!moi && d.groupe ? `<div class="who">${h(who(m.de).court)} · ${h(m.t)}</div>` : ''}
        <div class="bubble${moi ? '' : ' them'}${m.mention ? ' mention' : ''}">${h(m.txt)}</div>${p}${reac}
        ${moi || !d.groupe ? `<div class="meta" style="${moi ? 'justify-content:flex-end' : ''}">${h(m.t)}${m.mika ? ' · <span class="mk-txt">écrit par Mika</span>' : ''}</div>` : ''}</div></div>`;
    }).join('');
    const b = d.brouillon;
    const carte = b ? `<div class="tray"><div class="approval"><div class="ap-h">${ico('pen')}<span class="grow"><b>${b.etat === 'accord' ? 'Mika propose une réponse' : 'Mika l\'a posée dans Teams'}</b>
        <small>${b.etat === 'accord' ? 'attend ton accord · jusqu\'à 15:42' : 'dans le champ de Teams, pas envoyée'} · ${h(b.t)}</small></span></div>
        <pre style="font-family:var(--font);font-size:14px">${h(b.txt)}</pre>
        <div class="btns"><button class="btn text sm" type="button" data-snack="Refusé : rien ne partira.">Refuser</button><button class="btn outlined sm" type="button" data-snack="Mis dans le champ, à retoucher">Retoucher</button>${b.etat === 'accord' ? '<button class="btn filled sm" type="button" data-snack="Parti dans Teams, sous ton nom">Envoyer</button>' : ''}</div></div></div>` : '';
    return {
      nav: 'teams', back: '#teams',
      html: `${A.top({ title: h(d.titre), sub: h(sous), small: true, back: true, actions: [A.act('more', 'Plus', 'data-menu="teams"')] })}
        <div class="thread plain" data-bottom><div class="spacer"></div>${msgs}</div>
        ${carte}
        <div class="composer plain">${A.act('sparkle', 'Préremplir avec Mika', 'data-snack="Mika préremplit…"', 'mk')}
          <div class="cf"><input type="text" placeholder="Écrire à ${h(d.groupe ? d.titre : who(d.qui).court)}" aria-label="Message"></div>
          <button class="ibtn filled" type="button" disabled aria-label="Envoyer">${ico('send', 'sm')}</button><span class="cap">part par l'extension, sous le nom d'Adrien Moreau</span></div>`,
      notes: {
        titre: 'Teams · une discussion',
        reprend: ['Le fil : les autres à gauche (leur nom dans un groupe), toi à droite ; « écrit par Mika » sous ce qu\'elle a envoyé pour toi.', 'Sa réponse préparée, en carte au-dessus du champ : Refuser, Retoucher, Envoyer.',
          '✦ à gauche du champ : « Préremplir avec Mika ». Ta propre réponse rend la sienne sans objet (ADR 0199).', '⋮ : comment ça part (tes droits), en parler à Mika.'],
        trancher: ['✦ Préremplir à gauche du champ (à la place du trombone), d\'accord ?', 'Sa carte au-dessus du champ, ou dans le fil, à sa place dans la conversation ?'],
      },
    };
  }

  function vueBrouillons() {
    const items = [['claire', 'Claire Dubois', 'Oui je l\'ai vu, merci ! Je te réponds par mail avant ce soir.', ['warn', 'attend ton accord · jusqu\'à 15:42'], 'd\'elle-même · 13:42'],
      ['lumen', 'Projet Lumen', 'Je regarde les chiffres demain matin et je te dis avant midi.', ['pc', 'posée dans Teams'], 'd\'elle-même · 12:59'],
      ['cafe', 'Café ☕', 'J\'arrive !', ['ok', 'partie seule (règle : « Café » en mode seule)'], 'à ta demande · 09:50']];
    return {
      nav: 'teams', back: '#teams',
      html: `${A.top({ title: 'Ses brouillons', sub: 'Teams · Lumen Conseil', small: true, back: true })}
        <div class="body"><div class="cards">${items.map(([id, t, txt, e, src]) => `<button class="card mk" type="button" data-go="#teams/d/${id}" style="text-align:left;width:100%"><div class="row"><b class="grow" style="font-weight:500">${h(t)}</b><span class="muted label-s">${h(src)}</span></div>
          <p style="margin:6px 0 8px;font-size:15px">« ${h(txt)} »</p><span class="tag ${e[0]}">${h(e[1])}</span></button>`).join('')}</div></div>`,
      notes: { titre: 'Teams · ses brouillons', reprend: ['Une carte par réponse (comme le frontendv2 sur un téléphone) ; toucher une carte ouvre sa discussion.'], trancher: [] },
    };
  }

  A.ecran('teams', (args) => (args[0] === 'd' ? vueFil(args[1]) : args[0] === 'brouillons' ? vueBrouillons() : vueListe()));
  A.menus.teams = () => [{ ico: 'shield', l: 'Comment ça part', go: '#outils' }, { ico: 'sparkle', l: 'Préremplir avec Mika', snack: 'Mika préremplit…' }, { ico: 'chat', l: 'En parler à Mika', go: '#chat' }, '-', { ico: 'bell', l: 'Couper les notifications', snack: 'Notifications coupées pour cette discussion' }];
  A.index('Teams', [['Discussions', '#teams'], ['Projet Lumen', '#teams/d/lumen'], ['Claire', '#teams/d/claire'], ['Ses brouillons', '#teams/brouillons']]);
})();
