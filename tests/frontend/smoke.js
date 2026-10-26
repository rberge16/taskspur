const { JSDOM } = require('jsdom');
const fs = require('fs');
const base = 'http://127.0.0.1:8775';
const H = { 'X-Requested-With': 'taktspur', 'Content-Type': 'application/json' };
const call = async (m, p, b) => { const r = await fetch(base + p, { method: m, headers: H, body: b ? JSON.stringify(b) : undefined }); return r.status === 204 ? null : r.json(); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let fails = 0; const ok = (c, m) => { console.log((c ? 'OK   ' : 'FAIL ') + m); if (!c) fails++; };

(async () => {
  const today = new Date(); const pad = (n) => String(n).padStart(2, '0');
  const day = `${today.getFullYear()}-${pad(today.getMonth() + 1)}-${pad(today.getDate())}`;
  const st = (z) => [{ type: 'warmup', duration: { value: 10, unit: 'min' }, target: { type: 'power', zone: z } }];
  const XSS = '<img src=x onerror="window.__pwn=1">';
  const plan = await call('POST', '/api/plans', { name: XSS, status: 'active', color: 2 });
  await call('POST', `/api/plans/${plan.id}/phases`, { name: 'Grundlage', start_date: day, end_date: day, description: '' });
  await call('POST', '/api/workouts', { title: XSS, sport: 'Laufen', date: day, kind: 'important', steps: st('Z2') });
  await call('POST', '/api/workouts/brick', { part1: { title: 'Rad', sport: 'Radfahren', date: day, start_time: '08:00', kind: 'normal', steps: st('Z2') }, part2: { title: 'Lauf', sport: 'Laufen', date: day, start_time: '10:00', kind: 'normal', steps: st('Z2') } }).then((r) => { if (r.detail) console.log('brick payload:', JSON.stringify(r.detail).slice(0, 300)); });

  const dom = new JSDOM(fs.readFileSync('/home/claude/taktspur-neu/web/index.html', 'utf8').replace(/<script[^>]*><\/script>/, ''), { url: base + '/', runScripts: 'outside-only', pretendToBeVisual: true });
  const w = dom.window;
  w.structuredClone = structuredClone; w.fetch = (u, o) => fetch(new URL(u, base), o);
  w.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
  w.HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
  w.HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); };
  const errors = []; w.addEventListener('error', (e) => errors.push(e.message));
  w.eval(fs.readFileSync(__dirname + '/bundle.js', 'utf8'));
  await sleep(800);
  const view = w.document.getElementById('view');
  ok(!w.__pwn, 'XSS-Payload wurde nicht ausgeführt');
  ok(view.querySelectorAll('img').length === 0, 'kein <img> aus Nutzertext erzeugt');
  ok(view.textContent.includes(XSS), 'Payload als Text sichtbar');
  ok(view.querySelectorAll('.chip').length === 3, `3 Chips am Tag (${view.querySelectorAll('.chip').length})`);
  ok([...view.querySelectorAll('.brick-mark')].map((e) => e.textContent).join() === 'K1,K2', 'Koppel-Marker K1,K2');
  ok(view.querySelectorAll('.day-list .card').length === 3, 'Tagesliste zeigt 3 Karten');
  for (const v of ['plans', 'settings']) { w.__taktspur.show(v); await sleep(500); ok(view.children.length > 0 && !view.querySelector('.form-message.error'), `Ansicht ${v} rendert`); }
  ok(!w.__pwn, 'XSS auch nach Plänen/Einstellungen nicht ausgeführt');
  const nav = [...w.document.querySelectorAll('#nav button')]; nav[0].click(); await sleep(500); nav[0].click(); await sleep(500);
  ok(view.querySelectorAll('.chip').length === 3, 'Nach mehrfacher Navigation keine Duplikate');
  // Editor öffnen
  view.querySelector('.chip').click(); await sleep(600);
  const dlg = w.document.getElementById('editor');
  ok(dlg.hasAttribute('open') && dlg.textContent.length > 20, 'Editor öffnet | open=' + dlg.hasAttribute('open') + ' len=' + dlg.textContent.length + ' err=' + (view.querySelector('.form-message.error')||{}).textContent + ' js=' + errors.join('|'));
  ok(!w.__pwn, 'XSS im Editor nicht ausgeführt');
  const html = dlg.innerHTML + view.innerHTML; ok(!/secret|api_key/i.test(html.replace(/API-Schlüssel/g, '')), 'kein Schlüssel im DOM');
  ok(errors.length === 0, 'keine JS-Fehler ' + errors.join('|'));
  console.log(fails ? `${fails} FEHLER` : 'ALLES OK'); process.exit(fails ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
