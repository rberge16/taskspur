// Echter Browser: FIT-Import über die Oberfläche, Diagramme, Tabellen, HRV. Aufruf: node activity_browser.js <ausgabeordner> <datei.fit> [...]
const { chromium } = require('playwright');
const base = 'http://127.0.0.1:8775';
const [out, ...files] = process.argv.slice(2);
let fails = 0; const ok = (c, m) => { console.log((c ? 'OK   ' : 'FAIL ') + m); if (!c) fails++; };

(async () => {
  const browser = await chromium.launch();
  const problems = [];
  for (const [name, w, h] of [['phone', 390, 844], ['desktop', 1280, 900]]) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h } });
    const page = await ctx.newPage();
    page.on('console', (m) => { if (['error', 'warning'].includes(m.type()) && !m.text().includes('409')) problems.push(`${name}: ${m.text()}`); });
    page.on('pageerror', (e) => problems.push(`${name}: ${e.message}`));
    await page.goto(base + '/#activities'); await page.waitForSelector('#fit-input', { state: 'attached' });
    if (name === 'phone') {
      await page.setInputFiles('#fit-input', files); await page.waitForSelector('.activity-card');
      const n = await page.locator('.activity-card').count();
      ok(n === files.length, `Import über die Oberfläche: ${n} Aktivität(en) in der Liste`);
      await page.setInputFiles('#fit-input', files[0]); await page.waitForTimeout(800);
      ok((await page.locator('.activity-card').count()) === files.length, 'Doppelter Import wird abgewiesen (keine Dublette)');
    }
    await page.goto(base + '/#activities'); await page.waitForSelector('.activity-card');
    await page.locator('.activity-card').first().click();
    await page.waitForSelector('.act-head h2'); await page.waitForSelector('#hrv-charts canvas', { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(800);
    const info = await page.evaluate(() => ({
      canvases: document.querySelectorAll('canvas').length,
      tables: document.querySelectorAll('table').length,
      overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      text: document.getElementById('view').innerText,
      wide: [...document.querySelectorAll('.chart-holder')].filter((e) => e.scrollWidth > e.clientWidth + 2).length,
    }));
    ok(info.canvases >= 5, `${name}: ${info.canvases} Diagramme gezeichnet`);
    ok(info.tables >= 4, `${name}: ${info.tables} Tabellen`);
    ok(info.overflow <= 0, `${name}: kein horizontales Scrollen der Seite (Überstand ${info.overflow}px)`);
    ok(info.wide === 0, `${name}: Diagramme laufen nicht über`);
    ok(!/\bnull\b|undefined|NaN/.test(info.text), `${name}: kein „null“/„undefined“/„NaN“ im Text`);
    ok(/DFA a1/.test(info.text) && /RMSSD/.test(info.text), `${name}: HRV-Auswertung sichtbar`);
    // Runden: a1-Spalte in der Rundentabelle, Haarlinien in den Diagrammen schaltbar
    const heads = (title) => page.locator(`section:has(h3:text-is("${title}")) th`).allInnerTexts();
    const lapHeads = await heads('Runden'), timeHeads = await heads('Werte pro Zeitabschnitt');
    ok(lapHeads.indexOf('DFA a1 Ø') === lapHeads.indexOf('Ø HF') + 1, `${name}: Rundentabelle: DFA a1 steht direkt neben Ø HF`);
    ok(timeHeads.indexOf('DFA a1 Ø') === timeHeads.indexOf('Ø Herzfrequenz (bpm)') + 1 && timeHeads.indexOf('Ø Herzfrequenz (bpm)') > 0, `${name}: Zeitabschnitt-Tabelle: DFA a1 steht direkt neben der Herzfrequenz`);
    const box = page.locator('#lap-lines');
    ok(await box.count() === 1, `${name}: Schalter für Rundenlinien vorhanden`);
    const canvas = page.locator('canvas').first(); await canvas.scrollIntoViewIfNeeded();
    const before = await canvas.screenshot();
    await box.check(); await page.waitForTimeout(300);
    const after = await canvas.screenshot();
    ok(!before.equals(after), `${name}: Rundenlinien werden im Diagramm gezeichnet`);
    await box.uncheck(); await page.waitForTimeout(300);
    ok((await canvas.screenshot()).equals(before), `${name}: Rundenlinien lassen sich wieder ausblenden`);
    await box.check(); await page.waitForTimeout(300);
    await page.screenshot({ path: `${out}/act-${name}.png`, fullPage: true });
    await ctx.close();
  }
  await browser.close();
  ok(problems.length === 0, 'keine Konsolenfehler/CSP-Verstöße ' + problems.slice(0, 3).join(' | '));
  console.log(fails ? `${fails} FEHLER` : 'ALLES OK'); process.exit(fails ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
