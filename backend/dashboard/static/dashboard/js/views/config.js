Dash.render(async (root) => {
  root.innerHTML = `
    <div class="card">
      <h3>Configuration</h3>
      <div class="narr">
        Cet onglet est réservé pour l'édition live (personality.yaml, seuils
        conscience, toggles modules, gestion .env, …).
        <br/><br/>
        Pour l'instant le dashboard est <b>read-only</b> pour éviter toute
        corruption d'état accidentelle. Les endpoints d'écriture seront
        branchés ici au fur et à mesure.
      </div>
      <div class="mt chips">
        <a class="chip link" href="/dashboard/system/">Voir le routeur IA + paramètres runtime →</a>
        <a class="chip link" href="/dashboard/modules/">Voir l'état des modules →</a>
      </div>
    </div>`;
});
