/* L'agenda dans le chat — proposé le 2026-11-23, pas encore validé. Posé par-dessus l'écran Chat validé, sans le
   retoucher : la route #chat/agenda montre une matinée du lundi 23 novembre. Un rendez-vous se décide dans la
   conversation : Mika pose la carte d'accord « Ajouter à ton agenda » (la même proposition attend dans l'Agenda,
   hachurée de rose) ; puis un de ses rappels, une demi-heure avant la revue du budget. */
(function () {
  const C = M.ecrans.chat;
  if (!C || !M.agenda) return;
  const { h, ico, av } = M;
  const G = M.agenda, A = G.A, S = A.etat, AG = G.AG;

  const moi = (t, txt) => `<div class="msg me"><div class="bubble">${h(txt)}</div><div class="msg-meta">${h(t)} · ${ico('checks', 'xs')} lu</div></div>`;
  const elle = (t, bulles, extra) => {
    const e = extra || {};
    return `<div class="msg her">${av('mika', 'sm')}<div class="msg-col">${e.note || ''}${bulles.map((b) => `<div class="bubble">${h(b)}</div>`).join('')}${e.lien || ''}
      <div class="msg-meta">${h(t)}</div></div></div>`;
  };
  function fil() {
    const revue = G.trouver('revue-budget');
    return `<div class="day"><span>Aujourd'hui · lundi 23 novembre</span></div>
      ${moi('12:48', 'Léa m\'invite samedi soir pour son anniversaire, 20h chez elle 🎂')}
      ${elle('12:50', ['oh trop bien. samedi 28, 20 h, chez elle', 'je te le mets dans ton agenda Perso ? et je te le rappelle la veille au soir, pour le livre de photos'])}
      ${moi('12:51', 'attends je finis de manger 😄')}
      ${elle('12:51', ['pas de souci, je te laisse la carte en bas'])}
      ${elle('13:30', ['dans une demi-heure, ta revue du budget avec Marc, dans son bureau', 'le devis de Lefèvre dépasse de 1 240 €, surtout la main-d\'œuvre. tu connais le dossier par cœur, bon courage'], {
        note: `<a class="msg-note ag-rappel-note" href="#agenda/evenement/revue-budget">${ico('bell', 'xs')}Rappel de Mika · 30 min avant, comme réglé pour « Travail »</a>`,
        lien: `<a class="msg-link" href="#agenda/evenement/revue-budget">${ico('agenda')}<span><b>${h(revue.ev.titre)}</b><small>Travail · aujourd'hui ${G.hm(revue.deb)} – ${G.hm(revue.finMin)} · ${h(revue.ev.lieu)}</small></span>${ico('chev-right', 'sm')}</a>` })}
      ${moi('13:34', 'merci 🙏')}`;
  }
  function carte() {
    const o = G.trouver('prop-diner'), a = AG[o.ev.agenda];
    if (S.proposition === 'ajoute') return `<div class="approval done ag-ap-done">${ico('check')}<span>Ajouté à « ${h(a.nom)} » : parti chez Google. <a href="#agenda/evenement/prop-diner">Le voir dans l'Agenda</a></span></div>`;
    if (S.proposition === 'refuse') return `<div class="approval done">${ico('x')}<span>Refusé : rien n'est ajouté à ton agenda.</span></div>`;
    const brut = JSON.stringify({ agenda: 'Perso (Google)', titre: o.ev.titre, debut: '2026-11-28T20:00', fin: '2026-11-28T23:00', fuseau: A.fuseau, lieu: o.ev.lieu, rappel_de_mika: 'la veille au soir' }, null, 2);
    return `<div class="approval ag-ap">
      <div class="ap-line">${ico('agenda')}<div class="ap-main"><b>Mika voudrait ajouter à ton agenda « ${h(a.nom)} »</b><span class="ap-meta">Mika demande ton accord · <span class="ap-exp">expire dans 1 h 40</span></span></div>
        <button class="btn sm" type="button" data-agchat="non">Refuser</button><a class="btn sm" href="#agenda/modifier/prop-diner">Modifier</a>
        <button class="btn sm primary" type="button" data-agchat="ok">${ico('check', 'sm')}Ajouter</button></div>
      <div class="ag-ap-ev" style="--c:var(--ag-${a.couleur})"><span class="ag-ap-bar"></span>
        <div class="grow"><b>${h(o.ev.titre)}</b><span>${h(G.cap(G.jourDit(o.jour)))} · ${G.hm(o.deb)} – ${G.hm(o.finMin)}</span>
          <span>${ico('pin', 'xs')}${h(o.ev.lieu)}</span><span class="ag-ap-mika">${ico('sparkle', 'xs')}Mika te le rappelle : la veille au soir</span></div>
        <a class="small ag-ap-lien" href="#agenda/evenement/prop-diner">En attente dans ton Agenda ${ico('chev-right', 'xs')}</a></div>
      <details class="ap-more"><summary>${ico('chev-right', 'xs')}Voir exactement ce qui partira <span class="muted">· elle en gardera : un souvenir</span></summary>
        <div class="ap-what">Appeler « agenda_create » (Perso · Google)</div><pre class="ap-raw">${h(brut)}</pre>
        <p class="ap-help">Seuls ces boutons décident : un « oui » tapé dans la conversation ne vaut pas accord. Sans réponse, la carte expire ; la proposition reste dans ton Agenda.</p></details></div>`;
  }
  function greffer(body) {
    const thread = body.querySelector('.chat-thread'), typing = thread && thread.querySelector('[data-typing]');
    if (!thread || !typing) return;
    [...thread.children].forEach((n) => { if (n !== typing) n.remove(); });
    typing.insertAdjacentHTML('beforebegin', fil());
    const dock = body.querySelector('.chat-dock');
    if (dock) { dock.querySelectorAll(':scope > .approval').forEach((n) => n.remove()); dock.insertAdjacentHTML('afterbegin', carte()); }
    const s = body.querySelector('[data-scroll]');
    if (s) s.scrollTop = s.scrollHeight;
  }

  const rendu0 = C.rendu, monte0 = C.monte, notes0 = C.notes;
  C.rendu = (body, ctx) => { rendu0(body, ctx); if (ctx.item === 'agenda' && !body.querySelector('.pro-split')) greffer(body); };
  C.monte = (sec) => {
    monte0(sec);
    M.on(sec, '[data-agchat]', 'click', (e, b) => {
      S.proposition = b.dataset.agchat === 'ok' ? 'ajoute' : 'refuse';
      M.compter(); M.rafraichir();
      M.toast(S.proposition === 'ajoute' ? 'Ajouté à « Perso » : parti chez Google.' : 'Refusé : rien n\'est ajouté.', { ico: S.proposition === 'ajoute' ? 'check' : 'x' });
    });
  };
  C.notes = (ctx) => (ctx.item !== 'agenda' ? notes0(ctx) : [
    { groupe: 'L\'agenda dans le chat (proposé le 2026-11-23)', statut: 'decide', titre: 'Proposer d\'ajouter', texte: 'un rendez-vous décidé dans la conversation → agenda_create → la carte d\'accord « Ajouter à ton agenda », avec ce qui partira ; la même proposition attend dans l\'Agenda, hachurée de rose', src: 'output/agenda/CONCEPTION.md' },
    { statut: 'decide', titre: 'Ses rappels', texte: 'avant un rendez-vous, une initiative que l\'arbitre juge ; le délai se règle par agenda (non · 15 min · 30 min · 1 h · la veille au soir) et par événement' },
    { statut: 'existe', titre: 'Les cartes d\'accord', texte: 'approvals / approval / approval_result, avec « Ce qu\'elle en gardera »', src: 'mindport.py · plugins/mcp/calls.py' },
    { statut: 'existe', titre: 'Les rappels qu\'elle promet', texte: 'goal_remind, un rappel à l\'heure promis dans la conversation', src: 'faculties/goals/tools.py:366' },
    { statut: 'manque', titre: 'agenda_create et les rappels d\'agenda', texte: 'le plugin agenda, ses capacités, la note de message vers l\'événement (lot 3)' },
    { statut: 'À trancher', titre: 'La carte expire, la proposition non', texte: 'proposé : la carte du chat expire comme les autres ; la proposition reste dans l\'Agenda jusqu\'à ta décision ou jusqu\'à sa date' },
  ]);
})();
