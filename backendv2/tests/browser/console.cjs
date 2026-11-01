/* Régressions dans un vrai navigateur, sur l'export fictif de `mika console apercu`.
   MIKA_CONSOLE_PREVIEW=/tmp/mika-console-apercu node --test tests/browser/console.cjs
   Nécessite Playwright disponible pour Node et Chrome (ou PLAYWRIGHT_CHROMIUM_EXECUTABLE). */
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const { chromium } = require('playwright');
const preview = process.env.MIKA_CONSOLE_PREVIEW;
if (!preview) throw new Error('Définir MIKA_CONSOLE_PREVIEW vers un export de mika console apercu.');
const assets = path.resolve(__dirname, '../../src/mika/inspector/static');
let browser;
before(async () => {
  browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || '/usr/bin/google-chrome',
    headless: true, args: ['--no-sandbox'] });
});
after(async () => { await browser?.close(); });

async function open(t, { file = 'accueil.html', width = 1440, html, vitalsStatus = 200, clock = false, javaScriptEnabled = true } = {}) {
  const context = await browser.newContext({ viewport: { width, height: 900 }, reducedMotion: 'reduce', javaScriptEnabled });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  t.after(async () => { await context.close(); assert.deepEqual(errors, [], 'aucune erreur JavaScript'); });
  if (clock) await page.clock.install();
  await page.route('http://console.test/**', async route => {
    const url = new URL(route.request().url());
    // les fichiers de la console (feuilles des pages dessinées, scripts, polices), depuis les sources
    // (l'export les appelle « ../static/… », le cadre « /inspecteur/static/… »)
    const at = url.pathname.indexOf('/static/');
    if (at !== -1) {
      const rel = url.pathname.slice(at + '/static/'.length);
      const type = { css: 'text/css', js: 'application/javascript', woff2: 'font/woff2' }[rel.split('.').pop()] || 'application/octet-stream';
      return route.fulfill({ path: path.join(assets, rel), contentType: type });
    }
    if (url.pathname.endsWith('/_vitals')) return route.fulfill({ status: vitalsStatus, body: '<span>État actualisé</span>', contentType: 'text/html' });
    if (url.pathname.startsWith('/cadres/')) return route.fulfill({ path: path.join(preview, 'cadres', path.basename(url.pathname)), contentType: 'text/html' });
    const appPath = url.pathname.startsWith('/inspecteur/');
    if (!url.pathname.startsWith('/preview/') && !appPath) return route.fulfill({ status: 404, body: 'Route hors aperçu' });
    let filename = appPath ? (url.pathname.slice('/inspecteur/'.length) || 'accueil').replace(/[^A-Za-z0-9._-]+/g, '_').slice(0, 120) + '.html' : path.basename(url.pathname);
    if (!html && url.search) {
      // l'export nomme une page « chemin_requête », ses paramètres dans l'ordre où il l'a demandée, qui n'est pas
      // toujours celui du lien ; un lien relatif « ?… » remplace la requête : depuis une page déjà filtrée, on retire
      // des segments de la fin jusqu'à retrouver son chemin
      const orders = xs => xs.length < 2 ? [xs] : xs.flatMap((x, i) => orders(xs.filter((_, j) => j !== i)).map(rest => [x, ...rest]));
      const params = url.search.slice(1).split('&');
      const queries = (params.length > 4 ? [params] : orders(params)).map(xs => xs.join('&').replace(/[^A-Za-z0-9._-]+/g, '_'));
      const parts = filename.replace(/\.html$/, '').split('_');
      found: for (let n = parts.length; n > 0; n--) for (const query of queries) {
        const candidate = (parts.slice(0, n).join('_') + '_' + query).slice(0, 120) + '.html';
        try { await fs.access(path.join(preview, 'clair', candidate)); filename = candidate; break found; } catch { /* export sans ce filtre */ }
      }
    }
    const body = html || await fs.readFile(path.join(preview, 'clair', filename), 'utf8');
    return route.fulfill({ body: body.replace('</head>', '<script src="/inspecteur/static/console.js"></script></head>'), contentType: 'text/html' });
  });
  // Toute tentative vers un autre serveur est interdite pendant cette vérification.
  await context.route(/^(?!http:\/\/console\.test\/)/, route => route.abort());
  await page.goto('http://console.test/preview/' + file);
  return page;
}

const fixture = body => `<!doctype html><html lang="fr"><head><meta charset="utf-8"><link rel="stylesheet" href="/inspecteur/static/console.css"></head><body>${body}</body></html>`;

test('formulaire : erreurs annoncées, lien au champ avancé et saisie préservée', async t => {
  const page = await open(t, { html: fixture(`<main><h1>Réglages</h1><form class="form">
    <details><summary>Avancé</summary><div class="field has-error"><label for="limite">Limite</label>
    <input id="limite" name="limite" value="incorrect"><span class="error">Un nombre est attendu.</span></div></details>
    <div class="form-actions"><button>Enregistrer</button></div></form></main>`) });
  const summary = page.getByRole('alert');
  assert.equal(await summary.evaluate(el => el === document.activeElement), true);
  await summary.getByRole('link').click();
  assert.equal(await page.locator('details').evaluate(el => el.open), true);
  assert.equal(await page.locator('#limite').evaluate(el => el === document.activeElement), true);
  assert.equal(await page.locator('#limite').inputValue(), 'incorrect');
  assert.equal(await page.locator('#limite').getAttribute('aria-invalid'), 'true');
  assert.equal(await page.locator('#limite').getAttribute('aria-describedby'), 'limite-error');
});

test('mémoire : filtres, tableau, contenu complet et source au clavier', async t => {
  const page = await open(t, { file: 'memoire_souvenirs_person_Adrien.html', width: 390, javaScriptEnabled: false });
  // la liste dessinée (ADR 0121) : une entrée par souvenir, sa sensibilité en étiquette
  const items = page.locator('.person-list .person-entries > li');
  const count = await items.count();
  assert.ok(count >= 2);
  assert.match(await items.locator('.person-entry-tags').allTextContents().then(xs => xs.join(' ')), /secret/);
  const modes = page.getByRole('navigation', { name: 'Affichage : Ses souvenirs', exact: true });
  await modes.getByRole('link', { name: 'Tableau', exact: true }).click();
  // le tableau garde le filtre et les mêmes souvenirs
  assert.equal(await page.locator('main [name=person]').inputValue(), 'Adrien');
  assert.equal(await page.locator('#pg1 table.hm-table tbody > tr:not(.hm-table-detail)').count(), count);
  await modes.getByRole('link', { name: 'Liste', exact: true }).click();
  assert.equal(await items.count(), count);
  const detail = items.first().locator('details.person-entry-detail');
  await detail.locator(':scope > summary').focus();
  await page.keyboard.press('Enter');
  assert.equal(await detail.evaluate(el => el.open), true);
  // le contenu complet, en entier dans le détail
  assert.equal(await detail.getByRole('article', { name: 'En entier', exact: true }).locator('.document-text').textContent(),
    await items.first().locator('.person-entry-text').textContent());
  await items.first().getByRole('link', { name: 'Voir l’origine →', exact: true }).click();
  assert.equal(await page.locator('h1').count(), 1);
  assert.match(await page.locator('main').textContent(), /souvenir/i);
});

test('pensées : historique replié, lisible au clavier, sans confondre les pensées dissipées', async t => {
  const page = await open(t, { file: 'pensees_pensees.html' });
  const live = page.getByRole('region', { name: 'Ce qui lui trotte dans la tête', exact: true });
  assert.ok(await live.locator('.person-entries > li').count() >= 1);
  assert.equal(await live.getByText('Cette idée de titre me préoccupait', { exact: false }).count(), 0);
  const history = page.locator('details.person-fold').filter({ has: page.locator(':scope > summary', { hasText: /^Historique des pensées$/ }) });
  assert.equal(await history.evaluate(el => el.open), false);
  await history.locator(':scope > summary').focus();
  await page.keyboard.press('Enter');
  const faded = history.locator('.person-entries > li').filter({ hasText: 'Cette idée de titre me préoccupait' });
  assert.equal(await faded.isVisible(), true);
  // la pensée dissipée se dit éteinte, pas vivante
  assert.equal(await faded.locator('.person-entry-tags').textContent(), 'éteinte');
});

test('relecture mémoire : détail lisible, clé liée au passage et confirmation annulable', async t => {
  const page = await open(t, { file: 'memoire_consolidation.html', width: 390 });
  const item = page.getByRole('region', { name: 'Passages à reprendre', exact: true }).locator('.person-entries > li').first();
  await item.locator('details.person-entry-detail > summary').click();
  assert.equal(await item.getByRole('article', { name: 'Détail du passage', exact: true }).locator('.document-text').isVisible(), true);
  const form = item.locator('form');
  const key = form.locator('input[name=key]');
  assert.equal(await key.getAttribute('type'), 'hidden');
  // la clé est celle du passage affiché (« message n° 85 » → 85)
  const passage = await item.locator('.person-entry-title a').getAttribute('href');
  assert.equal(passage, `/inspecteur/evenement/${await key.getAttribute('value')}`);
  let posts = 0, confirmed = false;
  page.on('request', req => { if (req.method() === 'POST') posts += 1; });
  page.once('dialog', async dialog => { confirmed = true; await dialog.dismiss(); });
  await form.getByRole('button', { name: 'Reprendre cette extraction', exact: true }).click();
  assert.equal(confirmed, true);
  assert.equal(posts, 0);
});

test('onglets mobiles : l’onglet courant reste dans le cadre au chargement', async t => {
  const page = await open(t, { file: 'memoire_consolidation.html', width: 390 });
  const active = page.getByRole('navigation', { name: 'Onglets', exact: true }).locator('[aria-current=page]');
  assert.ok(await active.evaluate(el => {
    const box = el.getBoundingClientRect(), tabs = el.parentElement.getBoundingClientRect();
    return box.left >= tabs.left - 1 && box.right <= tabs.right + 1;
  }));
});

test('compte mobile : les applications ont leur état et une révocation annulable', async t => {
  const page = await open(t, { file: 'reglages_comptes_compte_1.html', width: 390 });
  const apps = page.getByRole('list', { name: 'Applications connectées', exact: true });
  // chaque application, son nom en titre de l'entrée et son état en étiquette
  const app = apps.getByRole('listitem').filter({ has: page.locator('.person-entry-title', { hasText: /^Écran de démonstration$/ }) });
  assert.equal(await app.locator('.person-entry-title').isVisible(), true);
  let posts = 0, asked = '';
  page.on('request', req => { if (req.method() === 'POST') posts += 1; });
  page.once('dialog', dialog => { asked = dialog.message(); dialog.dismiss(); });
  await app.getByRole('button', { name: 'révoquer', exact: true }).click();
  assert.match(asked, /Écran de démonstration/);
  assert.equal(posts, 0);
  assert.equal(await app.locator('.person-entry-tags').getByText('actif', { exact: true }).isVisible(), true);
});

test('projets : fiches et tableau montrent les mêmes projets, sans JavaScript', async t => {
  const page = await open(t, { file: 'projets.html', javaScriptEnabled: false });
  const cards = page.locator('#pg1 .person-entries > li');
  const count = await cards.count();
  assert.ok(count >= 2);
  const names = await cards.locator('.person-entry-title').allTextContents();
  const modes = page.getByRole('navigation', { name: 'Affichage : Projets', exact: true });
  await modes.getByRole('link', { name: 'Tableau', exact: true }).click();
  assert.equal(await modes.getByRole('link', { name: 'Tableau', exact: true }).getAttribute('aria-current'), 'page');
  assert.equal(await cards.count(), 0);
  const table = page.getByRole('region', { name: 'Projets', exact: true }).locator('table.hm-table');
  assert.equal(await table.locator('tbody > tr:not(.hm-table-detail)').count(), count);
  for (const name of names) assert.ok((await table.textContent()).includes(name), name);
  await modes.getByRole('link', { name: 'Fiches', exact: true }).click();
  assert.equal(await cards.count(), count);
});

test('fil : lecture directe, détails et explication accessibles au clavier', async t => {
  const page = await open(t, { file: 'fil_messages.html' });
  // le fil dessiné (ADR 0121) : chaque message en bulle, lisible sans rien ouvrir ; ses détails sont
  // la fiche de l'événement (« n° … ») et l'explication la page « pourquoi ? »
  const thread = page.getByRole('region', { name: 'Ses messages', exact: true });
  const first = thread.locator('.person-thread > li.mine').filter({ has: page.getByRole('link', { name: 'pourquoi ?', exact: true }) }).first();
  const bubble = first.locator('.person-bubble');
  assert.equal(await bubble.isVisible(), true);
  const body = (await bubble.textContent()).trim();
  assert.ok(body.length > 10);
  const why = first.getByRole('link', { name: 'pourquoi ?', exact: true });
  assert.match(await why.getAttribute('href'), /^\/inspecteur\/parole\/\d+$/);
  await first.locator('.person-number a').focus();
  await page.keyboard.press('Enter');
  await page.waitForURL(/\/inspecteur\/evenement\/\d+$/);
  assert.match(await page.locator('h1').textContent(), /^Parole · n° \d+$/);
  assert.ok((await page.locator('main .person-bubble').first().textContent()).includes(body));
  await page.goBack();
  await why.focus();
  await page.keyboard.press('Enter');
  await page.waitForURL(/\/inspecteur\/parole\/\d+$/);
  assert.equal(await page.locator('h1').textContent(), 'Pourquoi a-t-elle dit ça ?');
  assert.ok((await page.locator('main').textContent()).includes(body));
});

test('validation : aperçu relisible, blocage visible et Entrée sans décision', async t => {
  const page = await open(t, { file: 'approbations_en_attente.html' });
  const cards = page.locator('article.hm-approval');
  assert.equal(await cards.count(), 2);
  assert.match(await cards.first().getByRole('region', { name: 'Aperçu', exact: true }).locator('.document-text').textContent(), /bea@example\.net/);
  assert.equal(await cards.last().getByRole('button', { name: 'Approuver', exact: true }).isDisabled(), true);
  assert.equal(await cards.last().getByRole('alert').isVisible(), true);
  let posts = 0;
  page.on('request', req => { if (req.method() === 'POST') posts += 1; });
  await cards.first().locator('[name=note]').fill('Une note, sans décision');
  await page.keyboard.press('Enter');
  assert.equal(posts, 0);
  assert.equal(await cards.count(), 2);
});

test('menu mobile : clavier, focus contenu, Échap et raccourci de recherche', async t => {
  const page = await open(t, { width: 390 });
  assert.equal(await page.locator('#navigation').evaluate(el => el.inert), true);
  const button = page.getByRole('button', { name: 'Menu', exact: true });
  await button.focus();
  await page.keyboard.press('Enter');
  assert.equal(await button.getAttribute('aria-expanded'), 'true');
  assert.equal(await page.locator('.content').evaluate(el => el.inert), true);
  assert.equal(await page.locator('[data-nav-close]').evaluate(el => el === document.activeElement), true);
  // le focus reste dans le panneau : du dernier élément au premier, et retour
  const last = page.locator('#navigation summary').last();
  await last.focus();
  await page.keyboard.press('Tab');
  assert.equal(await page.locator('[data-nav-close]').evaluate(el => el === document.activeElement), true);
  await page.keyboard.press('Shift+Tab');
  assert.equal(await last.evaluate(el => el === document.activeElement), true);
  await page.keyboard.press('Escape');
  assert.equal(await button.getAttribute('aria-expanded'), 'false');
  assert.equal(await button.evaluate(el => el === document.activeElement), true);
  await page.keyboard.press('/');
  assert.equal(await page.locator('#q-global').evaluate(el => el === document.activeElement), true);
  await page.keyboard.press('Escape');
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForFunction(() => !document.querySelector('#navigation').inert);
});

test('rubriques : la page courante marquée dans la barre, un menu ouvert à la fois, Échap le ferme', async t => {
  const page = await open(t, { file: 'systeme_stockage.html' });
  const system = page.locator('[data-nav-group="Système"]');
  assert.equal(await system.evaluate(el => el.classList.contains('active') && !el.open), true);
  const mika = page.locator('[data-nav-group="Mika"]');
  await mika.locator('summary').click();
  assert.equal(await mika.evaluate(el => el.open), true);
  assert.equal(await mika.getByRole('link', { name: /Besoins/ }).isVisible(), true);
  await system.locator('summary').click();
  assert.equal(await mika.evaluate(el => el.open), false);
  assert.equal(await system.evaluate(el => el.open), true);
  assert.equal(await system.locator('a[aria-current=page]').count(), 1);
  await page.keyboard.press('Escape');
  assert.equal(await system.evaluate(el => el.open), false);
  // la barre du haut suffit : pas de « Changer de page dans cette rubrique »
  assert.equal(await page.locator('.submenu-shell').count(), 0);
});

test('aller à : les pages de la console à la frappe, flèches et Entrée, puis la recherche partout', async t => {
  const page = await open(t);
  await page.keyboard.press('Control+k');
  const input = page.locator('#q-global');
  assert.equal(await input.evaluate(el => el === document.activeElement), true);
  await input.pressSequentially('besoin');
  const list = page.getByRole('listbox', { name: 'Aller à', exact: true });
  assert.equal(await list.isVisible(), true);
  assert.match(await list.getByRole('option').first().textContent(), /Besoins/);
  assert.match(await list.getByRole('option').last().textContent(), /Chercher « besoin » partout/);
  await page.keyboard.press('ArrowDown');
  assert.equal(await list.getByRole('option').nth(1).getAttribute('aria-selected'), 'true');
  await page.keyboard.press('Escape');
  assert.equal(await list.isVisible(), false);
});

test('sans JavaScript : le menu mobile et les rubriques restent consultables', async t => {
  const page = await open(t, { width: 390, javaScriptEnabled: false });
  await page.locator('label.menu-toggle').click();
  assert.equal(await page.locator('#nav-open').isChecked(), true);
  await page.locator('[data-nav-group="Mika"] > summary').click();
  assert.equal(await page.getByRole('link', { name: /^Besoins/ }).isVisible(), true);
  await page.locator('.scrim').click({ position: { x: 375, y: 300 } });
  assert.equal(await page.locator('#nav-open').isChecked(), false);
});

test('champ masqué : aucune validation ni envoi ; valeur retrouvée et lecture seule conservée', async t => {
  const page = await open(t, { html: fixture(`<form><select name="type"><option value="local">Local</option><option value="distant">Distant</option></select>
    <div data-only="type=distant"><input type="hidden" name="_champs" value="adresse"><input name="adresse" required><input name="verrouille" value="conserve" disabled></div>
    <button>Enregistrer</button></form>`) });
  assert.equal(await page.locator('form').evaluate(el => el.checkValidity()), true);
  assert.deepEqual(await page.locator('form').evaluate(el => Array.from(new FormData(el).keys())), ['type']);
  await page.locator('select').selectOption('distant');
  assert.equal(await page.locator('form').evaluate(el => el.checkValidity()), false);
  await page.locator('[name=adresse]').fill('valeur gardée');
  await page.locator('select').selectOption('local');
  await page.locator('select').selectOption('distant');
  assert.equal(await page.locator('[name=adresse]').inputValue(), 'valeur gardée');
  assert.equal(await page.locator('[name=verrouille]').isDisabled(), true);
});

test('champ qui en attend un autre (« != ») : paraît à la frappe, se masque quand on le vide', async t => {
  const page = await open(t, { html: fixture(`<form><input name="serveur" value="">
    <div data-only="serveur!=" hidden><input type="hidden" name="_champs" value="port"><input name="port" value="587"></div>
    <p data-only="serveur=">Donne d'abord un serveur.</p><button>Enregistrer</button></form>`) });
  assert.equal(await page.locator('[name=port]').isVisible(), false);
  assert.equal(await page.getByText("Donne d'abord un serveur.").isVisible(), true);
  await page.locator('[name=serveur]').pressSequentially('smtp.exemple.org');
  assert.equal(await page.locator('[name=port]').isVisible(), true);
  assert.equal(await page.getByText("Donne d'abord un serveur.").isVisible(), false);
  await page.locator('[name=serveur]').fill('');
  assert.deepEqual(await page.locator('form').evaluate(el => Array.from(new FormData(el).keys())), ['serveur']);
});

test('filtres : modifier une liste ne navigue pas avant Filtrer', async t => {
  const page = await open(t, { html: fixture('<form class="filters"><input name="q" value="bonjour"><select name="etat"><option value="a">A</option><option value="b">B</option></select><button>Filtrer</button></form>') });
  let navigations = 0;
  page.on('request', req => { if (req.isNavigationRequest()) navigations += 1; });
  await page.locator('select').selectOption('b');
  assert.equal(navigations, 0);
  await Promise.all([page.waitForURL('**?q=bonjour&etat=b'), page.getByRole('button', { name: 'Filtrer' }).click()]);
  assert.equal(navigations, 1);
});

test('formulaire : état non enregistré, retour à la valeur initiale et validation dans un détail', async t => {
  const page = await open(t, { html: fixture('<form class="form"><input name="nom" value="Initial"><input name="fichier" type="file"><details><summary>Avancé</summary><input name="requis" required></details><div class="form-actions"><button>Enregistrer</button></div></form>') });
  await page.locator('[name=nom]').fill('Changé');
  assert.match(await page.locator('.form-status').textContent(), /non enregistrées/);
  await page.locator('[name=nom]').fill('Initial');
  assert.equal(await page.locator('.form-status').textContent(), '');
  await page.getByRole('button', { name: 'Enregistrer' }).click();
  assert.equal(await page.locator('details').evaluate(el => el.open), true);
  assert.equal(await page.locator('[name=requis]').evaluate(el => el === document.activeElement), true);
});

test('actions imbriquées : ouvrir un formulaire ne ferme pas son menu parent', async t => {
  const page = await open(t, { html: fixture('<details class="action-overflow"><summary>Autres actions</summary><details data-exclusive><summary>Modifier</summary><input name="nom"></details></details>') });
  await page.getByText('Autres actions', { exact: true }).click();
  await page.getByText('Modifier', { exact: true }).click();
  assert.equal(await page.locator('.action-overflow').evaluate(el => el.open), true);
  assert.equal(await page.locator('[data-exclusive]').evaluate(el => el.open), true);
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('.action-overflow').evaluate(el => el.open), false);
});

test('session expirée : état conservé, lien de reconnexion et arrêt des tentatives', async t => {
  const page = await open(t, { vitalsStatus: 401, clock: true });
  const before = await page.locator('[data-vitals-items]').innerHTML();
  let polls = 0;
  page.on('request', req => { if (req.url().endsWith('/_vitals')) polls += 1; });
  await page.clock.fastForward(10001);
  await page.getByRole('link', { name: 'Session expirée · Se reconnecter' }).waitFor();
  assert.equal(await page.locator('[data-vitals-items]').innerHTML(), before);
  assert.equal(await page.getByRole('link', { name: 'Session expirée · Se reconnecter' }).getAttribute('href'), '/inspecteur/connexion');
  await page.clock.fastForward(120000);
  assert.equal(polls, 1);
});

test('bouton retirer lisible en clair et sombre, au repos et au survol', async t => {
  const page = await open(t, { file: 'reglages_fournisseurs.html' });
  const luminance = rgb => {
    const values = rgb.match(/[\d.]+/g).slice(0, 3).map(Number).map(v => v / 255).map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4);
    return values[0] * .2126 + values[1] * .7152 + values[2] * .0722;
  };
  for (const theme of ['light', 'dark']) {
    // le thème est dans le menu du compte (ADR 0176)
    if (!await page.locator('.account-menu').evaluate(el => el.open)) await page.locator('.account-menu > summary').click();
    await page.locator(`[data-theme-set=${theme}]`).click();
    for (const quiet of [true, false]) for (const hover of [false, true]) {
      const button = page.getByRole('button', { name: 'retirer', exact: true }).first();
      await button.evaluate((el, value) => el.classList.toggle('quiet', value), quiet);
      if (hover) await button.hover(); else await page.locator('h1').hover();
      const colors = await button.evaluate(el => ({ text: getComputedStyle(el).color, bg: getComputedStyle(el).backgroundColor }));
      const a = luminance(colors.text), b = luminance(colors.bg);
      assert.ok((Math.max(a, b) + .05) / (Math.min(a, b) + .05) >= 4.5, JSON.stringify({ theme, quiet, hover, colors }));
    }
  }
});

test('toutes les pages exportées : aucun débordement du document à 390 et 1440 px', async t => {
  const page = await open(t);
  const files = (await fs.readdir(path.join(preview, 'clair'))).filter(file => file.endsWith('.html'));
  const overflows = [];
  for (const width of [390, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    for (const file of files) {
      await page.goto('http://console.test/preview/' + file);
      assert.equal(await page.locator('h1').count(), 1, file);
      if (!await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)) {
        const elements = await page.locator('main *').evaluateAll(els => els.filter(el => el.checkVisibility() &&
          el.getBoundingClientRect().right > innerWidth + 1 && !el.closest('.table-wrap')).slice(0, 8)
          .map(el => `${el.tagName}.${el.className}`));
        overflows.push({ file, width, elements });
      }
    }
  }
  assert.deepEqual(overflows, []);
});

test('réglages : catégories accessibles sans JavaScript et recherche des paramètres avancés', async t => {
  const page = await open(t, { file: 'reglages_apercu.html', javaScriptEnabled: false });
  assert.equal(await page.locator('#reglages-avances').evaluate(el => el.open), false);
  await page.locator('#reglages-avances > summary').click();
  assert.equal(await page.locator('#reglages-avances').evaluate(el => el.open), true);
  await page.locator('main .filters input[name=q]').fill('memoire');
  await page.locator('main .filters button').click();
  assert.equal(await page.locator('#reglages-avances').evaluate(el => el.open), true);
  assert.equal(await page.locator('.settings-directory a[href="/inspecteur/reglages/comportement-memory"]').isVisible(), true);
  assert.equal(await page.locator('.settings-directory a[href="/inspecteur/reglages/comptes"]').count(), 0);
});

test('courrier mobile : déplier les dossiers au clavier, ouvrir un message et lire sa version HTML', async t => {
  const page = await open(t, { file: 'courrier_reception_compte_atelier.html', width: 390 });
  // comptes et dossiers : un volet replié sur un écran étroit (data-responsive-menu)
  const navigation = page.locator('details.hm-workspace-side');
  assert.equal(await navigation.evaluate(el => el.open), false);
  await navigation.locator(':scope > summary').focus();
  await page.keyboard.press('Enter');
  const folders = navigation.getByRole('navigation', { name: 'Dossiers', exact: true });
  assert.equal(await folders.getByRole('link', { name: 'Archives', exact: true }).isVisible(), true);
  await page.keyboard.press('Enter');  // toujours sur le résumé : Entrée replie la liste
  assert.equal(await navigation.evaluate(el => el.open), false);
  // le message s'ouvre dans la liseuse, sous la liste (ADR 0175)
  await page.getByRole('region', { name: 'Réception', exact: true }).locator('.mail-lines a', { hasText: 'Maquettes du projet' }).click();
  const reader = page.getByRole('region', { name: /Maquettes du projet/ });
  assert.equal(await reader.evaluate(el => el.classList.contains('mail-reader')), true);
  const frame = reader.locator('iframe.document-frame');
  assert.equal(await frame.isVisible(), true);
  // le mail tel qu'il a été écrit, dans son cadre isolé (ADR 0169), à la hauteur de son contenu
  assert.equal(await page.frameLocator('iframe.document-frame').locator('strong').first().textContent(), 'Ton retour jeudi');
  await page.waitForFunction(() => {
    const f = document.querySelector('iframe.document-frame');
    return f.contentDocument && f.style.height === f.contentDocument.documentElement.scrollHeight + 'px';
  });
  assert.equal(await page.getByRole('link', { name: 'maquettes.pdf', exact: true }).isVisible(), true);
  // sa rubrique est marquée dans la barre (ADR 0176), le courrier comme page courante
  const group = page.locator('[data-nav-group="Relations & échanges"]');
  assert.equal(await group.evaluate(el => el.classList.contains('active')), true);
  assert.equal(await group.locator('a[aria-current=page]').getAttribute('href'), '/inspecteur/courrier');
});

test('outils : ouvrir une fiche au clavier puis retrouver sa grille filtrée', async t => {
  const page = await open(t, { file: 'outils_tous_lot_email.html', javaScriptEnabled: false });
  // la grille par famille (ADR 0123) : chaque outil de la famille mène à sa fiche
  const tool = page.locator('section.access-family .access-tool-list a[href*="outil=email_read"]').first();
  await tool.focus();
  await page.keyboard.press('Enter');
  await page.waitForURL(/outil=email_read/);
  assert.equal(await page.locator('h1').textContent(), 'email_read');
  const rules = page.locator('details.person-fold').filter({ has: page.locator(':scope > summary', { hasText: 'Arguments et règles d’utilisation' }) });
  assert.equal(await rules.evaluate(el => el.open), false);
  await rules.locator(':scope > summary').click();
  assert.equal(await rules.getByRole('heading', { name: 'Ses arguments', exact: true }).isVisible(), true);
  await page.getByRole('navigation', { name: "Fil d'Ariane", exact: true }).getByRole('link', { name: "Ce qu'elle peut faire", exact: true }).click();
  // de retour sur la grille, toujours filtrée sur sa famille : la seule montrée, ses droits dépliés
  await page.waitForURL(/\?lot=email$/);
  assert.match(await page.locator('main .server-alert').textContent(), /Seulement la famille « email »/);
  const families = page.locator('section.access-family');
  assert.equal(await families.count(), 1);
  assert.equal(await families.getAttribute('id'), 'f-email');
  assert.ok(await families.locator('details.access-rules[open] .access-tool').count() > 0);
});

test('activité et sorties : relevé daté, erreurs prioritaires et relances adaptées', async t => {
  const page = await open(t, { file: 'decisions_en_cours.html' });
  assert.equal(await page.getByRole('link', { name: 'Actualiser', exact: true }).isVisible(), true);
  assert.match(await page.locator('main').textContent(), /Relevé \d{2}\/\d{2}\/\d{4} \d{2}:\d{2}/);
  assert.equal(await page.getByRole('heading', { name: 'En ce moment', exact: true }).isVisible(), true);
  assert.equal(await page.getByRole('heading', { name: "Ce qu'elle vient de faire", exact: true }).isVisible(), true);
  await page.getByRole('link', { name: 'Sorties à vérifier', exact: true }).click();
  assert.equal(await page.locator('h1').textContent(), 'File de sortie');
  // « À traiter » : un départ coincé par entrée, son état en étiquette
  const review = page.getByRole('region', { name: 'À traiter', exact: true });
  const cards = review.locator('.hm-outbox-list > li');
  assert.equal(await cards.count(), 3);
  const state = text => cards.filter({ has: page.locator('.now-tag', { hasText: text }) });
  const interrupted = state(/^Interrompu \(à vérifier\)$/);
  assert.equal(await interrupted.count(), 1);
  assert.equal(await interrupted.getByRole('button', { name: 'Relancer', exact: true }).count(), 0);
  assert.equal(await interrupted.getByRole('button', { name: 'Marquer comme vu', exact: true }).isVisible(), true);
  assert.equal(await state(/^Échoué$/).getByRole('button', { name: 'Relancer', exact: true }).isVisible(), true);
  // les erreurs passent avant l'historique des départs
  const beforeHistory = await page.evaluate(() => document.querySelector('.outbox-review').compareDocumentPosition(
    document.querySelector('[aria-labelledby=out-recent]')) & Node.DOCUMENT_POSITION_FOLLOWING);
  assert.ok(beforeHistory);
});

test('santé : problèmes prioritaires, contrôles repliables et diagnostic accessible au clavier', async t => {
  const page = await open(t, { file: 'systeme_sante.html', width: 390, javaScriptEnabled: false });
  // le bilan (ADR 0121) : son verdict en titre, ses comptes ; puis une tuile par contrôle
  const summary = page.locator('section.sys-health');
  assert.equal(await summary.isVisible(), true);
  assert.equal(await summary.locator('.now-eyebrow').textContent(), 'Bilan de santé');
  assert.match(await summary.getByRole('heading', { level: 2 }).textContent(), /dégradé/);
  const checks = page.getByRole('list', { name: 'Les contrôles de santé', exact: true }).locator(':scope > li.sys-check');
  // les problèmes d'abord : aucun contrôle en forme avant un contrôle à examiner
  const tones = await checks.evaluateAll(els => els.map(el => el.classList.contains('tone-ok')));
  assert.ok(tones.length >= 2 && tones[0] === false, JSON.stringify(tones));
  assert.equal(tones.indexOf(false, tones.indexOf(true)), -1, JSON.stringify(tones));
  const outbox = checks.filter({ has: page.getByRole('heading', { name: 'File de sortie', exact: true }) });
  assert.equal(await outbox.evaluate(el => el.classList.contains('tone-ok')), false);
  // son détail replié, qui s'ouvre au clavier
  const detail = outbox.locator('.sys-check-more > details');
  assert.equal(await detail.evaluate(el => el.open), false);
  await detail.locator(':scope > summary').focus();
  await page.keyboard.press('Enter');
  assert.equal(await detail.evaluate(el => el.open), true);
  assert.equal(await detail.locator('pre').isVisible(), true);
  await outbox.getByRole('link', { name: 'Ouvrir le diagnostic →', exact: true }).focus();
  await page.keyboard.press('Enter');
  await page.waitForURL(/\/inspecteur\/systeme\/sorties$/);
  assert.equal(await page.locator('h1').textContent(), 'File de sortie');
});

test('épisode : résumé de l’échec, déroulé, données complètes puis retour au résumé', async t => {
  const page = await open(t, { file: 'episode_apercu-activite-connexion.html', javaScriptEnabled: false });
  // le résumé de l'échec, en tête (ADR 0121)
  assert.equal(await page.locator('.episode-hero .episode-outcome').textContent(), 'échec');
  assert.match(await page.locator('.episode-hero .now-lede').textContent(), /Le service de transcription n’a pas répondu/);
  const tabs = page.getByRole('navigation', { name: 'Onglets', exact: true });
  assert.equal(await tabs.getByRole('link', { name: 'Résumé', exact: true }).getAttribute('aria-current'), 'page');
  await tabs.getByRole('link', { name: 'Déroulé', exact: true }).click();
  // le déroulé : un événement par ligne, la raison de la fin citée
  const events = page.locator('ol.episode-feed > li');
  assert.ok(await events.count() >= 2);
  const event = events.last();
  assert.match(await event.locator('q').textContent(), /Le service de transcription/);
  // les données complètes : sur la fiche de l'événement, ouverte puis dépliée au clavier
  await event.getByRole('link', { name: /^Fin d’épisode$|^Fin d'épisode$/ }).focus();
  await page.keyboard.press('Enter');
  await page.waitForURL(/\/inspecteur\/evenement\/\d+$/);
  assert.match(await page.locator('h1').textContent(), /Fin d’épisode|Fin d'épisode/);
  const raw = page.locator('details.person-fold').filter({ has: page.locator(':scope > summary', { hasText: /^Ses données brutes$/ }) });
  assert.equal(await raw.evaluate(el => el.open), false);
  await raw.locator(':scope > summary').focus();
  await page.keyboard.press('Enter');
  assert.equal(await raw.locator('pre').isVisible(), true);
  assert.match(await raw.locator('pre').textContent(), /Le service de transcription/);
  await page.goBack();
  await tabs.getByRole('link', { name: 'Résumé', exact: true }).click();
  assert.equal(await tabs.getByRole('link', { name: 'Résumé', exact: true }).getAttribute('aria-current'), 'page');
  // le contexte transmis au modèle : l'onglet « Prompt », qui dit qu'il n'a pas été gardé
  await tabs.getByRole('link', { name: 'Prompt', exact: true }).click();
  assert.match(await page.locator('main').textContent(), /n'a pas été gardé/);
});

test('épisode de réponse : distinguer qui parle du destinataire et retrouver le message déclencheur', async t => {
  const files = await fs.readdir(path.join(preview, 'clair'));
  const file = files.find(name => /^episode_01[^_]+\.html$/.test(name));
  assert.ok(file, 'un épisode de réponse dans la vie fictive');
  const page = await open(t, { file, width: 390 });
  // ce qu'elle a dit : sa bulle (« mine »), le destinataire nommé après « à »
  const spoken = page.getByRole('region', { name: "Ce qu'elle a dit", exact: true }).locator('.person-thread > li').first();
  assert.equal(await spoken.evaluate(el => el.classList.contains('mine')), true);
  const to = (await spoken.locator('.person-meta').textContent()).trim().match(/^à (\S+) ·/);
  assert.ok(to, 'le destinataire est nommé');
  assert.match(to[1], /adrien|B[ée]a/);
  // le message déclencheur : la bulle de l'autre (« theirs »), signée de son auteur, sans « à »
  const trigger = page.getByRole('region', { name: "Ce qui l'a déclenché", exact: true }).locator('.person-thread > li').first();
  assert.equal(await trigger.evaluate(el => el.classList.contains('theirs')), true);
  assert.ok((await trigger.locator('.person-meta').textContent()).trim().startsWith(`${to[1]} · `));
  const message = await trigger.locator('.person-bubble').textContent();
  await trigger.getByRole('link', { name: /^message n° \d+$/ }).click();
  assert.match(await page.locator('h1').textContent(), /Message ou signal reçu/);
  assert.ok((await page.locator('main').textContent()).includes(message));
});
