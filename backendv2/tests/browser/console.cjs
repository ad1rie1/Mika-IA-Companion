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
    if (url.pathname.endsWith('/console.css')) return route.fulfill({ path: path.join(assets, 'console.css'), contentType: 'text/css' });
    if (url.pathname.endsWith('/console.js')) return route.fulfill({ path: path.join(assets, 'console.js'), contentType: 'application/javascript' });
    if (url.pathname.endsWith('/_vitals')) return route.fulfill({ status: vitalsStatus, body: '<span>État actualisé</span>', contentType: 'text/html' });
    const appPath = url.pathname.startsWith('/inspecteur/');
    if (!url.pathname.startsWith('/preview/') && !appPath) return route.fulfill({ status: 404, body: 'Route hors aperçu' });
    let filename = appPath ? (url.pathname.slice('/inspecteur/'.length) || 'accueil').replace(/[^A-Za-z0-9._-]+/g, '_').slice(0, 120) + '.html' : path.basename(url.pathname);
    if (!html && url.search) {
      const candidate = (filename.replace(/\.html$/, '') + '_' + url.search.slice(1).replace(/[^A-Za-z0-9._-]+/g, '_')).slice(0, 120) + '.html';
      try { await fs.access(path.join(preview, 'clair', candidate)); filename = candidate; } catch { /* export sans ce filtre */ }
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
  const items = page.locator('.collection.list .collection-item');
  const count = await items.count();
  assert.ok(count >= 2);
  assert.match(await items.allTextContents().then(xs => xs.join(' ')), /secret/);
  await page.getByRole('link', { name: 'Tableau', exact: true }).click();
  assert.equal(await page.locator('main [name=person]').inputValue(), 'Adrien');
  await page.getByRole('link', { name: 'Liste', exact: true }).click();
  assert.equal(await items.count(), count);
  await items.first().locator('summary').first().focus();
  await page.keyboard.press('Enter');
  assert.equal(await items.first().locator('details').first().evaluate(el => el.open), true);
  await items.first().getByRole('link', { name: 'Voir l’origine →', exact: true }).click();
  assert.equal(await page.locator('h1').count(), 1);
  assert.match(await page.locator('main').textContent(), /souvenir/i);
});

test('pensées : historique replié, lisible au clavier, sans confondre les pensées dissipées', async t => {
  const page = await open(t, { file: 'pensees_pensees.html' });
  const live = page.locator('.collection.cards');
  assert.equal(await live.getByText('Cette idée de titre me préoccupait', { exact: false }).count(), 0);
  const history = page.locator('details.card').filter({ has: page.locator('summary > b', { hasText: /^Historique des pensées$/ }) });
  assert.equal(await history.evaluate(el => el.open), false);
  await history.locator(':scope > summary').focus();
  await page.keyboard.press('Enter');
  assert.equal(await history.getByText('Cette idée de titre me préoccupait', { exact: false }).isVisible(), true);
});

test('relecture mémoire : détail lisible, clé liée au passage et confirmation annulable', async t => {
  const page = await open(t, { file: 'memoire_consolidation.html', width: 390 });
  const item = page.locator('.collection.cards .collection-item').first();
  await item.locator('.collection-details > summary').click();
  assert.equal(await item.locator('.document-text').isVisible(), true);
  const form = item.locator('form');
  assert.equal(await form.locator('input[name=key]').getAttribute('type'), 'hidden');
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
  assert.equal(await apps.getByRole('heading', { name: 'Écran de démonstration', exact: true }).isVisible(), true);
  let posts = 0;
  page.on('request', req => { if (req.method() === 'POST') posts += 1; });
  page.once('dialog', dialog => dialog.dismiss());
  await apps.getByRole('button', { name: 'révoquer', exact: true }).click();
  assert.equal(posts, 0);
  assert.equal(await apps.getByText('actif', { exact: true }).isVisible(), true);
});

test('projets : fiches et tableau montrent les mêmes projets, sans JavaScript', async t => {
  const page = await open(t, { file: 'projets.html', javaScriptEnabled: false });
  const count = await page.locator('.collection.cards .collection-item').count();
  assert.ok(count >= 2);
  const names = await page.locator('.collection-heading h4').allTextContents();
  await page.getByRole('navigation', { name: 'Affichage : Projets', exact: true }).getByRole('link', { name: 'Tableau', exact: true }).click();
  assert.equal(await page.locator('.collection.cards').count(), 0);
  for (const name of names) assert.ok((await page.locator('.tbl').first().textContent()).includes(name));
  await page.getByRole('navigation', { name: 'Affichage : Projets', exact: true }).getByRole('link', { name: 'Fiches', exact: true }).click();
  assert.equal(await page.locator('.collection.cards .collection-item').count(), count);
});

test('fil : lecture directe, détails et explication accessibles au clavier', async t => {
  const page = await open(t, { file: 'fil_messages.html' });
  const first = page.locator('.collection.feed .collection-item:has(.collection-open)').first();
  const body = (await first.locator('.collection-body').textContent()).replace(/^texte/, '').trim();
  assert.ok(body.length > 10);
  const details = first.locator('.collection-details > summary');
  await details.focus();
  await page.keyboard.press('Enter');
  assert.equal(await first.locator('.collection-details').evaluate(el => el.open), true);
  assert.ok((await first.locator('.document-text').textContent()).includes(body));
  assert.match(await first.locator('.collection-open').getAttribute('href'), /^\/inspecteur\/parole\/\d+$/);
});

test('validation : aperçu relisible, blocage visible et Entrée sans décision', async t => {
  const page = await open(t, { file: 'approbations_en_attente.html' });
  const cards = page.locator('.approval-card');
  assert.equal(await cards.count(), 2);
  assert.match(await cards.first().locator('.document-text').textContent(), /bea@example\.net/);
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
  assert.equal(await page.locator('.sidebar').evaluate(el => el.inert), true);
  const button = page.getByRole('button', { name: 'Menu', exact: true });
  await button.focus();
  await page.keyboard.press('Enter');
  assert.equal(await button.getAttribute('aria-expanded'), 'true');
  assert.equal(await page.locator('.main').evaluate(el => el.inert), true);
  assert.equal(await page.locator('[data-nav-close]').evaluate(el => el === document.activeElement), true);
  await page.locator('.sidebar-foot button').last().focus();
  await page.keyboard.press('Tab');
  assert.equal(await page.locator('.brand-link').evaluate(el => el === document.activeElement), true);
  await page.keyboard.press('Shift+Tab');
  assert.equal(await page.locator('.sidebar-foot button').last().evaluate(el => el === document.activeElement), true);
  await page.keyboard.press('Escape');
  assert.equal(await button.getAttribute('aria-expanded'), 'false');
  assert.equal(await button.evaluate(el => el === document.activeElement), true);
  await page.keyboard.press('/');
  assert.equal(await page.locator('#q-global').evaluate(el => el === document.activeElement), true);
  await page.keyboard.press('Escape');
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForFunction(() => !document.querySelector('.sidebar').inert);
});

test('rubriques mémorisées, page courante ouverte et sous-menu filtrable sans accents', async t => {
  const page = await open(t, { file: 'reglages_fournisseurs.html' });
  const group = page.locator('[data-nav-group="Mika"]');
  await group.locator('summary').click();
  await page.waitForFunction(() => sessionStorage.getItem('mika.console.nav.Mika') === 'true');
  await page.reload();
  assert.equal(await group.evaluate(el => el.open), true);
  assert.equal(await page.locator('[data-nav-group="Réglages"]').evaluate(el => el.open), true);
  assert.equal(await page.locator('.submenu-shell').evaluate(el => el.open), false);
  await page.locator('.submenu-toggle').click();
  const initial = await page.locator('.submenu-group').evaluateAll(els => els.map(el => el.open));
  await page.locator('#q-menu').fill('memoire');
  assert.ok(await page.locator('.submenu-item:visible').count() > 0);
  assert.match((await page.locator('.submenu-item:visible').allTextContents()).join(' '), /Mémoire/);
  await page.locator('#q-menu').fill('aucune-page-de-ce-nom');
  assert.equal(await page.locator('[data-menu-empty]').isVisible(), true);
  await page.locator('#q-menu').fill('');
  assert.deepEqual(await page.locator('.submenu-group').evaluateAll(els => els.map(el => el.open)), initial);
});

test('sans JavaScript : le menu mobile et les rubriques restent consultables', async t => {
  const page = await open(t, { width: 390, javaScriptEnabled: false });
  await page.locator('label.menu-toggle').click();
  assert.equal(await page.locator('#nav-open').isChecked(), true);
  await page.locator('[data-nav-group="Mika"] > summary').click();
  assert.equal(await page.getByRole('link', { name: 'Émotions et besoins' }).isVisible(), true);
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
  const navigation = page.locator('.workspace-navigation');
  assert.equal(await navigation.evaluate(el => el.open), false);
  await navigation.locator('summary').focus();
  await page.keyboard.press('Enter');
  assert.equal(await navigation.getByRole('link', { name: 'Archives', exact: true }).isVisible(), true);
  await page.keyboard.press('Enter');  // toujours sur le résumé : Entrée replie la liste
  assert.equal(await navigation.evaluate(el => el.open), false);
  await page.locator('.collection-open').first().click();
  assert.equal(await page.locator('.document-html').isVisible(), true);
  assert.match(await page.locator('h1').textContent(), /Maquettes du projet/);
  assert.equal(await page.locator('.document-html strong').textContent(), 'Ton retour jeudi');
  assert.equal(await page.getByRole('link', { name: 'maquettes.pdf', exact: true }).isVisible(), true);
  assert.equal(await page.locator('[data-nav-group="Relations & échanges"]').evaluate(el => el.open), true);
});

test('outils : ouvrir une fiche au clavier puis retrouver son catalogue filtré', async t => {
  const page = await open(t, { file: 'outils_tous_lot_email.html', javaScriptEnabled: false });
  const tool = page.locator('.collection-heading a[href*="outil=email_read"]').first();
  await tool.focus();
  await page.keyboard.press('Enter');
  assert.equal(await page.locator('h1').textContent(), 'email_read');
  const rules = page.locator('details').filter({ has: page.locator('summary', { hasText: 'Arguments et règles d’utilisation' }) });
  assert.equal(await rules.evaluate(el => el.open), false);
  await rules.locator('summary').click();
  assert.equal(await rules.getByRole('heading', { name: 'Ses arguments', exact: true }).isVisible(), true);
  await page.getByRole('link', { name: 'Retour aux outils', exact: true }).click();
  assert.equal(await page.locator('main select[name=lot]').inputValue(), 'email');
  assert.ok(await page.locator('.collection.cards .collection-item').count() > 0);
});

test('activité et sorties : relevé daté, erreurs prioritaires et relances adaptées', async t => {
  const page = await open(t, { file: 'decisions_en_cours.html' });
  assert.equal(await page.getByRole('link', { name: 'Actualiser cet écran', exact: true }).isVisible(), true);
  assert.match(await page.locator('main').textContent(), /Relevé à/);
  assert.equal(await page.getByRole('heading', { name: 'Le travail en cours', exact: true }).isVisible(), true);
  assert.equal(await page.getByRole('heading', { name: 'Les derniers résultats', exact: true }).isVisible(), true);
  await page.getByRole('link', { name: 'Sorties à vérifier', exact: true }).click();
  const cards = page.locator('.outbox-problem');
  assert.equal(await cards.count(), 3);
  const interrupted = cards.filter({ hasText: 'interrompu (à vérifier)' });
  assert.equal(await interrupted.getByRole('button', { name: 'Relancer', exact: true }).count(), 0);
  assert.equal(await interrupted.getByRole('button', { name: 'Marquer comme vu', exact: true }).isVisible(), true);
  assert.equal(await cards.filter({ hasText: 'échoué' }).getByRole('button', { name: 'Relancer', exact: true }).isVisible(), true);
  const beforeHistory = await page.evaluate(() => document.querySelector('.outbox-review').compareDocumentPosition(document.querySelector('#pg1')) & Node.DOCUMENT_POSITION_FOLLOWING);
  assert.ok(beforeHistory);
});

test('santé : problèmes prioritaires, contrôles repliables et diagnostic accessible au clavier', async t => {
  const page = await open(t, { file: 'systeme_sante.html', width: 390, javaScriptEnabled: false });
  assert.equal(await page.getByRole('region', { name: 'Bilan de santé', exact: true }).isVisible(), true);
  assert.equal(await page.getByRole('heading', { name: 'Points à examiner', exact: true }).isVisible(), true);
  const healthy = page.locator('details.card').filter({ has: page.locator('summary > b', { hasText: /^Contrôles sans problème/ }) }).first();
  assert.equal(await healthy.evaluate(el => el.open), false);
  await healthy.locator(':scope > summary').focus();
  await page.keyboard.press('Enter');
  assert.equal(await healthy.evaluate(el => el.open), true);
  const outbox = page.locator('.collection.cards .collection-item').filter({ has: page.getByRole('heading', { name: 'File de sortie', exact: true }) });
  await outbox.getByRole('link', { name: 'Ouvrir le diagnostic →', exact: true }).focus();
  await page.keyboard.press('Enter');
  assert.equal(await page.locator('h1').textContent(), 'File de sortie');
});

test('épisode : résumé de l’échec, déroulé, données complètes puis retour au résumé', async t => {
  const page = await open(t, { file: 'episode_apercu-activite-connexion.html', javaScriptEnabled: false });
  assert.match(await page.locator('main').textContent(), /Le service de transcription n’a pas répondu/);
  const tabs = page.getByRole('navigation', { name: 'Onglets', exact: true });
  assert.equal(await tabs.getByRole('link', { name: 'Résumé', exact: true }).getAttribute('aria-current'), 'page');
  await tabs.getByRole('link', { name: 'Déroulé', exact: true }).click();
  assert.ok(await page.locator('.collection.list .collection-item').count() >= 2);
  const event = page.locator('.collection.list .collection-item').last();
  await event.locator('.collection-details > summary').focus();
  await page.keyboard.press('Enter');
  assert.match(await event.locator('pre').first().textContent(), /Le service de transcription/);
  await event.getByRole('link', { name: 'Ouvrir l’événement →', exact: true }).click();
  assert.match(await page.locator('h1').textContent(), /Fin d’épisode|Fin d'épisode/);
  await page.goBack();
  await tabs.getByRole('link', { name: 'Résumé', exact: true }).click();
  assert.equal(await page.getByRole('link', { name: 'Contexte transmis', exact: true }).isVisible(), true);
  await page.getByRole('link', { name: 'Contexte transmis', exact: true }).click();
  assert.match(await page.locator('main').textContent(), /n'a pas été gardé/);
});

test('épisode de réponse : distinguer qui parle du destinataire et retrouver le message déclencheur', async t => {
  const files = await fs.readdir(path.join(preview, 'clair'));
  const file = files.find(name => /^episode_01[^_]+\.html$/.test(name));
  assert.ok(file, 'un épisode de réponse dans la vie fictive');
  const page = await open(t, { file, width: 390 });
  const spoken = page.locator('.collection.feed .collection-item').first();
  assert.equal(await spoken.locator('.collection-heading h4').textContent(), 'elle');
  assert.equal(await spoken.locator('.collection-fields dt').first().textContent(), 'À');
  const name = await spoken.locator('.collection-fields dd').first().textContent();
  assert.match(name, /adrien|Béa/);
  const message = await page.locator('.document-text').textContent();
  await page.getByRole('link', { name: /^Message n° / }).click();
  assert.match(await page.locator('h1').textContent(), /Message ou signal reçu/);
  assert.ok((await page.locator('main').textContent()).includes(message));
});
