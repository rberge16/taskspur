// Echter Browser: importierte Aktivität im Kalender, API-Schlüssel-Feld, Abgleich-Einstellungen.
// Aufruf (frischer Server auf 127.0.0.1:8775): node calendar_browser.js <ausgabeordner> <datei.fit>
const { chromium } = require('playwright');
const base = 'http://127.0.0.1:8775';
const [out, fit] = process.argv.slice(2);
let fails = 0; const ok = (c, m) => { console.log((c ? 'OK   ' : 'FAIL ') + m); if (!c) fails++; };

(async () => {
  const browser = await chromium.launch();
  const problems = [];
  for (const [name, w, h] of [['phone', 390, 844], ['desktop', 1280, 900]]) {
    const page = await (await browser.newContext({ viewport: { width: w, height: h } })).newPage();
    page.on('pageerror', (e) => problems.push(`${name}: ${e.message}`));
    page.on('console', (m) => { if (m.type() === 'error' && !/40[49]|50[023]/.test(m.text())) problems.push(`${name}: ${m.text()}`); });
    if (name === 'phone') {
      await page.goto(base + '/#activities'); await page.waitForSelector('#fit-input', { state: 'attached' });
      await page.setInputFiles('#fit-input', fit); await page.waitForSelector('.activity-card');
    }
    // Kalender: Aktivität am Starttag sichtbar
    const acts = await (await fetch(base + '/api/activities')).json();
    const d = new Date(acts[0].start_time);
    await page.goto(base + '/#calendar'); await page.waitForSelector('.toolbar');
    for (let i = 0; i < 48 && !(await page.locator('.chip.activity').count()); i++) { await page.getByRole('button', { name: 'Zurück' }).click(); await page.waitForTimeout(150); }
    ok((await page.locator('.chip.activity').count()) >= 1, `${name}: importierte Aktivität erscheint im Monatskalender`);
    await page.locator('.day:has(.chip.activity) .day-num').first().click(); await page.waitForSelector('.day-list .activity-card');   // Handy: Chips sind ausgeblendet, Tag antippen
    ok((await page.locator('.day-list .activity-card').count()) >= 1, `${name}: Tagesliste zeigt die absolvierte Aktivität`);
    await page.screenshot({ path: `${out}/cal-${name}.png`, fullPage: true });
    await page.locator('.day-list .activity-card').first().click(); await page.waitForSelector('.act-head h2');
    ok(/#activities\/[\w-]+/.test(page.url()), `${name}: Klick öffnet die Aktivität`);
    await page.goto(base + '/#calendar'); await page.waitForSelector('.toolbar');
    await page.getByRole('tab', { name: 'Liste' }).click(); await page.waitForSelector('.list');
    await page.waitForTimeout(200);
    // Listenansicht des Monats, ggf. zurückblättern
    for (let i = 0; i < 48 && !(await page.locator('.list .activity-card').count()); i++) { await page.getByRole('button', { name: 'Zurück' }).click(); await page.waitForTimeout(150); }
    ok((await page.locator('.list .activity-card').count()) >= 1, `${name}: Listenansicht zeigt die Aktivität`);
    await page.getByRole('tab', { name: 'Monat' }).click();

    // Einstellungen ohne Verbindung: Schlüssel bleibt nach Fehler stehen, kein Abgleich-Block
    await page.goto(base + '/#settings'); await page.waitForSelector('input[name=key]');
    ok((await page.locator('text=Aktivitäten von Intervals.icu').count()) === 0, `${name}: Abgleich-Block erst nach Verbindung`);
    await page.fill('input[name=athlete]', 'i123'); await page.fill('input[name=key]', 'geheim-test-123');
    await page.getByRole('button', { name: 'Verbinden' }).click();
    await page.waitForSelector('.form-message.error:not([hidden])', { timeout: 20000 });
    ok((await page.inputValue('input[name=key]')) === 'geheim-test-123' && (await page.inputValue('input[name=athlete]')) === 'i123', `${name}: Eingaben bleiben nach Verbindungsfehler stehen`);
    ok((await (await fetch(base + '/api/intervals')).text()).includes('geheim') === false, `${name}: Schlüssel nie in der API-Antwort`);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    ok(overflow <= 0, `${name}: kein horizontales Scrollen (${overflow}px)`);
    await page.screenshot({ path: `${out}/settings-${name}.png`, fullPage: true });

    // Abgleich-Block mit simuliertem Backend (nichts geht an Intervals.icu)
    let running = false, posted = 0;
    const last = { at: '2026-10-26T08:00:00', days: 30, found: 5, imported: 3, summary_only: 1, already: 1, failed: [], error: null };
    await page.route('**/api/intervals', (r) => (r.request().method() === 'GET' ? r.fulfill({ json: { connected: true, has_key: true, athlete_id: 'i123', last_error: '' } }) : r.continue()));
    await page.route('**/api/intervals/sync', (r) => { if (r.request().method() === 'POST') { posted++; running = true; setTimeout(() => { running = false; }, 1200); } r.fulfill({ json: { running, last: running ? null : (posted ? last : null) } }); });
    await page.goto(base + '/#calendar'); await page.goto(base + '/#settings'); await page.waitForSelector('text=Aktivitäten von Intervals.icu');
    const days = page.locator('input[type=number][max="730"]');
    ok((await days.inputValue()) === '30', `${name}: Zeitraum-Standard 30 Tage`);
    ok(await page.locator('input[type=checkbox]').first().isChecked(), `${name}: Abgleich beim Start ist standardmäßig an`);
    await days.fill('90'); await days.dispatchEvent('change'); await page.waitForTimeout(400);
    ok((await (await fetch(base + '/api/settings')).json()).intervals_history_days === 90, `${name}: Zeitraum wird gespeichert`);
    await days.fill('30'); await days.dispatchEvent('change'); await page.waitForTimeout(300);
    await page.getByRole('button', { name: 'Jetzt abgleichen' }).click();
    await page.waitForSelector('text=Abgleich läuft');
    await page.waitForSelector('text=5 gefunden', { timeout: 10000 });
    ok(posted === 1, `${name}: Abgleich ausgelöst, Ergebnis wird angezeigt`);
    await page.screenshot({ path: `${out}/sync-${name}.png`, fullPage: true });
    await page.unroute('**/api/intervals'); await page.unroute('**/api/intervals/sync');
  }
  ok(problems.length === 0, 'keine JS-/Konsolenfehler ' + problems.join(' | '));
  await browser.close();
  console.log(fails ? `${fails} FEHLER` : 'ALLES OK'); process.exit(fails ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
