// Echter Browser (Playwright/Chromium) gegen den laufenden Server: Layout, CSP, Diagramm. Aufruf: node browser.js <ausgabeordner>
const { chromium } = require('playwright');
const base = 'http://127.0.0.1:8775';
const out = process.argv[2] || '.';
const H = { 'X-Requested-With': 'taktspur', 'Content-Type': 'application/json' };
const call = async (m, p, b) => (await fetch(base + p, { method: m, headers: H, body: b ? JSON.stringify(b) : undefined })).json();
let fails = 0; const ok = (c, m) => { console.log((c ? 'OK   ' : 'FAIL ') + m); if (!c) fails++; };

(async () => {
  const now = new Date(), pad = (n) => String(n).padStart(2, '0');
  const d = (off) => { const x = new Date(now); x.setDate(x.getDate() + off); return `${x.getFullYear()}-${pad(x.getMonth() + 1)}-${pad(x.getDate())}`; };
  const st = (z, m = 20) => [{ type: 'warmup', duration: { value: m, unit: 'min' }, target: { type: 'power', zone: z } }];
  const plan = await call('POST', '/api/plans', { name: 'Marathon', status: 'active', color: 2 });
  await call('POST', `/api/plans/${plan.id}/phases`, { name: 'Grundlage', start_date: d(-5), end_date: d(20), description: '' });
  for (const [off, t, s, k] of [[0, 'Lange GA1-Ausfahrt mit sehr langem Titel', 'Radfahren', 'important'], [0, 'Intervalle', 'Laufen', 'normal'], [1, 'Schwimmen Technik', 'Schwimmen', 'normal'], [3, 'Leistungstest', 'Radfahren', 'test']])
    await call('POST', '/api/workouts', { title: t, sport: s, date: d(off), start_time: '07:00', kind: k, steps: st('Z2', 60) });
  await call('POST', '/api/workouts/brick', { part1: { title: 'Rad', sport: 'Radfahren', date: d(2), start_time: '08:00', kind: 'normal', steps: st('Z2', 90) }, part2: { title: 'Lauf', sport: 'Laufen', date: d(2), start_time: '10:00', kind: 'normal', steps: st('Z2', 30) } });

  const browser = await chromium.launch();
  const problems = [];
  for (const [name, w, h] of [['phone', 390, 800], ['desktop', 1280, 900]]) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h } });
    const page = await ctx.newPage();
    page.on('console', (m) => { if (['error', 'warning'].includes(m.type())) problems.push(`${name}: ${m.text()}`); });
    page.on('pageerror', (e) => problems.push(`${name}: ${e.message}`));
    await page.goto(base + '/'); await page.waitForSelector('.month .day');
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    ok(overflow <= 0, `${name}: kein horizontales Scrollen (Überstand ${overflow}px)`);
    ok(!(await page.evaluate(() => /\bnull\b|undefined/.test(document.getElementById('view').innerText))), `${name}: kein „null“/„undefined“ im Kalender`);
    await page.screenshot({ path: `${out}/${name}-kalender.png`, fullPage: true });
    // Editor
    await page.click('.day-list .card'); await page.waitForSelector('dialog[open] form');
    const dlgBox = await page.evaluate(() => { const r = document.querySelector('dialog#editor').getBoundingClientRect(); return { l: r.left, r: r.right, w: innerWidth }; });
    ok(dlgBox.l >= 0 && dlgBox.r <= dlgBox.w + 1, `${name}: Editor passt in die Breite`);
    ok(!(await page.evaluate(() => /\bnull\b|undefined/.test(document.querySelector('dialog#editor').innerText))), `${name}: kein „null“/„undefined“ im Editor`);
    await page.screenshot({ path: `${out}/${name}-editor.png` });
    await page.keyboard.press('Escape');
    // Diagramm mit 3000 Punkten
    const chart = await page.evaluate(async () => {
      const { lineChart } = await import('/js/charts.js');
      const n = 3000, x = Array.from({ length: n }, (_, i) => i / 60);
      const host = document.createElement('div'); host.id = 'charthost'; document.getElementById('view').prepend(host);
      lineChart(host, { title: 'Test-Verlauf', x, xLabel: 'Min.', xFormat: (v) => v.toFixed(0), series: [
        { label: 'Leistung', unit: 'W', values: x.map((v) => 200 + 80 * Math.sin(v / 3)) },
        { label: 'Puls', unit: 'bpm', values: x.map((v) => 130 + 20 * Math.sin(v / 5)) }] });
      await new Promise((r) => setTimeout(r, 300));
      const c = host.querySelector('canvas'), box = host.getBoundingClientRect();
      return { canvas: !!c, w: c && c.getBoundingClientRect().width, host: box.width, legend: host.querySelectorAll('.u-legend .u-series').length };
    });
    ok(chart.canvas && chart.legend === 3 && chart.w <= chart.host + 1, `${name}: Diagramm gerendert (Breite ${Math.round(chart.w)}/${Math.round(chart.host)}, Legende ${chart.legend})`);
    await page.screenshot({ path: `${out}/${name}-diagramm.png` });
    await ctx.close();
  }
  await browser.close();
  ok(problems.length === 0, 'keine Konsolenfehler/CSP-Verstöße ' + problems.join(' | '));
  console.log(fails ? `${fails} FEHLER` : 'ALLES OK'); process.exit(fails ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
