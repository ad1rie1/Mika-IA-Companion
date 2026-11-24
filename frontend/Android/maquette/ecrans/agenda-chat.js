/* L'agenda dans le chat (proposé le 2026-11-23, pas encore validé). Posé par-dessus l'écran Chat validé, sans le
   retoucher : la route #chat/agenda montre le début d'après-midi du lundi 23 novembre. Un rendez-vous se décide dans la
   conversation : Mika pose la carte d'accord « Ajouter à ton agenda » au-dessus du champ (la même proposition attend dans
   l'Agenda, hachurée de rose) ; puis un de ses rappels, une demi-heure avant la revue du budget, avec sa note rose qui
   mène à l'événement. C'est agenda-chat.js du web, dans le chat du téléphone. */
(function () {
  const { h, ico } = A;
  const X = A.agenda;
  const C0 = A.vue('chat');
  if (!X || !C0) return;
  const { G, S, AG } = X;

  const moi = (t, txt) => `<div class="msg me"><div class="bubble">${h(txt)}</div><div class="meta">${h(t)} ${ico('checks')}</div></div>`;
  const elle = (t, bulles, extra) => {
    const e = extra || {};
    return `<div class="msg her">${e.note || ''}${bulles.map((b) => `<div class="bubble">${h(b)}</div>`).join('')}${e.lien || ''}<div class="row"><span class="meta">${h(t)}</span></div></div>`;
  };
  function fil() {
    const revue = X.trouver('revue-budget');
    return `<div class="day">Aujourd'hui</div>
      ${moi('12:48', 'Léa m\'invite samedi soir pour son anniversaire, 20h chez elle 🎂')}
      ${elle('12:50', ['oh trop bien. samedi 28, 20 h, chez elle', 'je te le mets dans ton agenda Perso ? et je te le rappelle la veille au soir, pour le livre de photos'])}
      ${moi('12:51', 'attends je finis de manger 😄')}
      ${elle('12:51', ['pas de souci, je te laisse la carte en bas'])}
      ${elle('13:30', ['dans une demi-heure, ta revue du budget avec Marc, dans son bureau', 'le devis de Lefèvre dépasse de 1 240 €, surtout la main-d\'œuvre. tu connais le dossier par cœur, bon courage'], {
        note: `<button class="msg-note" type="button" data-go="#agenda/evenement/revue-budget">${ico('bell')}Rappel de Mika · 30 min avant, comme réglé pour « Travail »</button>`,
        lien: `<button class="msg-link" type="button" data-go="#agenda/evenement/revue-budget">${ico('agenda')}<span class="grow"><b>${h(revue.ev.titre)}</b><small>Travail · aujourd'hui ${X.hm(revue.deb)} – ${X.hm(revue.finMin)} · bureau de Marc</small></span>${ico('chev-right', 'sm')}</button>` })}
      ${moi('13:34', 'merci 🙏')}`;
  }
  function carte() {
    const o = X.trouver('prop-diner'), a = AG[o.ev.agenda];
    if (S.proposition === 'ajoute') return `<div class="tray"><button class="tray-fold" type="button" data-go="#agenda/evenement/prop-diner">${ico('check', 'sm')}<span class="grow ellipsis"><b>Ajouté à « ${h(a.nom)} »</b> · parti chez Google</span>${ico('chev-right', 'sm')}</button></div>`;
    if (S.proposition === 'refuse') return `<div class="tray"><div class="tray-fold">${ico('x', 'sm')}<span class="grow ellipsis"><b>Refusé</b> · rien n'est ajouté à ton agenda</span></div></div>`;
    const brut = JSON.stringify({ agenda: 'Perso (Google)', titre: o.ev.titre, debut: '2026-11-28T20:00', fin: '2026-11-28T23:00', fuseau: G.fuseau, lieu: o.ev.lieu, rappel_de_mika: 'la veille au soir' }, null, 2);
    return `<div class="tray"><div class="approval ag-ap" data-foldroot>
      <div class="ap-h">${ico('agenda')}<span class="grow"><b>Ajouter à ton agenda « ${h(a.nom)} »</b><small>Mika demande ton accord · expire dans 1 h 40</small></span></div>
      <button class="ag-ap-ev" type="button" data-go="#agenda/evenement/prop-diner" style="--c:var(--ag-${a.couleur})"><span class="ag-ap-bar"></span>
        <span class="grow"><b>${h(o.ev.titre)}</b><span>${h(X.cap(X.jourDit(o.jour)))} · ${X.hm(o.deb)} – ${X.hm(o.finMin)}</span>
          <span>${ico('pin', 'xxs')} ${h(o.ev.lieu)}</span><span class="mk-txt">${ico('sparkle', 'xxs')} Mika te le rappelle : la veille au soir</span></span>${ico('chev-right', 'sm')}</button>
      <button class="ag-ap-plus" type="button" data-fold=".ag-ap-raw"><svg class="ico xs"><use class="fold-ico" href="#i-chev-down"/></svg>Ce qui partira · elle en gardera : un souvenir</button>
      <div class="ag-ap-raw" hidden><pre>agenda_create (Perso · Google)\n${h(brut)}</pre><p class="note" style="padding:4px 0 0">Seuls ces boutons décident : un « oui » tapé dans la conversation ne vaut pas accord. Sans réponse, la carte expire ; la proposition reste dans ton Agenda.</p></div>
      <div class="ap-foot"><button class="btn text sm" type="button" data-go="#agenda/modifier/prop-diner">Modifier</button><span class="grow"></span><button class="btn text sm" type="button" data-agchat="non">Refuser</button><button class="btn filled sm" type="button" data-agchat="ok">${ico('check')}Ajouter</button></div></div></div>`;
  }
  function poser(root) {
    const thread = root.querySelector('.thread'), tray = root.querySelector('.tray');
    if (!thread) return;
    thread.innerHTML = `<div class="spacer"></div>${fil()}`;
    if (tray) tray.outerHTML = carte();
    thread.scrollTop = thread.scrollHeight;
  }

  A.ecran('chat', (args) => {
    if (args[0] !== 'agenda') return C0(args);
    const v = C0([]);
    const after0 = v.after;
    return { ...v,
      after(root) { if (after0) after0(root); poser(root); },
      notes: {
        titre: 'Chat · l\'agenda (proposé)',
        reprend: [
          'Un rendez-vous se décide dans la conversation (12:48, l\'anniversaire de Léa) : Mika le propose → agenda_create → la carte d\'accord « Ajouter à ton agenda » au-dessus du champ, à la place de la ligne repliée des accords.',
          'La carte montre l\'événement (sa couleur, quand, où, « Mika te le rappelle ») ; la toucher ouvre sa fiche dans l\'Agenda. « Ce qui partira » déplie l\'appel exact et ce qu\'elle en gardera. Modifier ouvre le formulaire (« Ce que Mika propose »), Refuser, Ajouter.',
          'La même proposition attend dans l\'Agenda, hachurée de rose, et dans « À décider » : décider ici ou là, c\'est pareil.',
          'Son rappel (13:30) : un message à elle, avec la note rose « Rappel de Mika · 30 min avant, comme réglé pour « Travail » » et le lien vers l\'événement.',
        ],
        trancher: ['La carte expire comme les autres (1 h 40 ici) ; la proposition, elle, reste dans l\'Agenda jusqu\'à ta décision ou sa date. D\'accord ?',
          'La carte d\'un ajout à l\'agenda dépliée d\'emblée (ici), ou repliée sur la ligne « 1 accord » comme les autres ?',
          'Son rappel : seulement dans le chat (qui notifie déjà), ou aussi une notification d\'agenda à part (voir « Notification ») ?'],
      } };
  });
  document.addEventListener('click', (e) => {
    const b = e.target.closest('[data-agchat]');
    if (!b) return;
    S.proposition = b.dataset.agchat === 'ok' ? 'ajoute' : 'refuse';
    const root = document.querySelector('#app .scr[data-screen="chat"]');
    const tray = root && root.querySelector('.tray');
    if (tray) tray.outerHTML = carte();
    A.snack(S.proposition === 'ajoute' ? 'Ajouté à « Perso » : parti chez Google' : 'Refusé : rien n\'est ajouté');
  });

  A.index('Agenda · chat (proposé)', [['Le chat', '#chat/agenda']]);
})();
