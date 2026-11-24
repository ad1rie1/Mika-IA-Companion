/* L'Agenda (proposé le 2026-11-23, pas encore validé) se pose par-dessus Paramètres, Outils et le chat sans les retoucher :
   il lui faut leur vue d'origine pour y ajouter ses routes (#parametres/agendas, #outils/droits/<agenda>, #chat/agenda).
   Ce crochet, chargé juste après maquette.js, garde chaque vue enregistrée : A.vue(id) la rend. Rien d'autre ne change. */
(function () {
  const vues = {};
  const ecran0 = A.ecran;
  A.ecran = (id, vue) => { vues[id] = vue; ecran0(id, vue); };
  A.vue = (id) => vues[id];
})();
