import { del, get, post, put } from './api.js';
import { h, render, toast } from './dom.js';

export async function renderSettings(root) {
  let st, settings, log, sync;
  try { [st, settings, log, sync] = await Promise.all([get('/api/intervals'), get('/api/settings'), get('/api/intervals/log'), get('/api/intervals/sync')]); }
  catch (e) { render(root, h('p', { class: 'form-message error', role: 'alert' }, e.message)); return; }
  const refresh = () => renderSettings(root);
  const message = h('p', { class: 'form-message', role: 'alert', hidden: true });
  const fail = (e) => { message.textContent = e.message; message.className = 'form-message error'; message.hidden = false; };

  const idInput = h('input', { name: 'athlete', required: true, maxlength: 20, value: st.athlete_id || '', placeholder: 'z. B. i12345', autocomplete: 'off', inputmode: 'text' });
  const keyInput = h('input', { name: 'key', type: 'password', required: !st.has_key, maxlength: 200, autocomplete: 'new-password',
    placeholder: st.has_key ? '•••••••• gespeichert (zum Ersetzen neu eingeben)' : 'API-Schlüssel aus Intervals.icu (Einstellungen › Entwickler)' });

  const statusLine = st.connected
    ? h('p', { class: 'pill sent', role: 'status' }, `Verbunden mit ${st.athlete_id} · API-Schlüssel gespeichert`)
    : st.has_key ? h('p', { class: 'pill error', role: 'alert' }, `API-Schlüssel gespeichert, aber die Verbindung ist gestört: ${st.last_error}`) : h('p', { class: 'pill none' }, 'Nicht verbunden');

  const form = h('form', { class: 'panel-box', onsubmit: async (e) => {
    e.preventDefault();
    message.hidden = true;
    if (!keyInput.value.trim()) { fail(new Error(st.has_key ? 'Es ist bereits ein Schlüssel gespeichert. Zum Ändern der Athleten-ID bitte den Schlüssel erneut eingeben.' : 'Bitte den API-Schlüssel eingeben.')); return; }
    try { await put('/api/intervals', { athlete_id: idInput.value.trim(), api_key: keyInput.value.trim() }); keyInput.value = ''; toast('Intervals.icu verbunden. Der Schlüssel ist gespeichert.', 'success'); await refresh(); }
    catch (err) { fail(err); }       // Eingaben bleiben stehen, damit man nur den Fehler korrigieren muss
  } },
    h('h3', {}, 'Intervals.icu'), statusLine,
    h('p', { class: 'hint' }, 'Der API-Schlüssel wird verschlüsselt auf diesem Gerät gespeichert und nie an den Browser zurückgegeben – deshalb zeigt das Feld nach dem Speichern nur Punkte. Gesendet werden nur in Taktspur geplante Workouts; importierte und absolvierte Einträge bleiben schreibgeschützt.'),
    h('label', { class: 'field' }, h('span', {}, 'Athleten-ID'), idInput),
    h('label', { class: 'field' }, h('span', {}, 'API-Schlüssel'), keyInput),
    message,
    h('div', { class: 'actions' },
      h('button', { type: 'submit', class: 'primary' }, st.has_key ? 'Neu verbinden' : 'Verbinden'),
      st.has_key ? h('button', { type: 'button', class: 'secondary', onclick: async () => { try { const r = await post('/api/intervals/verify'); toast(r.connected ? 'Verbindung ist in Ordnung.' : `Verbindung gestört: ${r.last_error}`, r.connected ? 'success' : 'error', 8000); await refresh(); } catch (err) { fail(err); } } }, 'Verbindung prüfen') : null,
      st.has_key ? h('button', { type: 'button', class: 'danger', onclick: async () => { if (!window.confirm('Verbindung trennen und gespeicherten Schlüssel löschen?')) return; try { await del('/api/intervals'); toast('Verbindung getrennt.', 'success'); await refresh(); } catch (err) { fail(err); } } }, 'Trennen') : null));

  const auto = h('input', { type: 'checkbox', checked: settings.intervals_auto_send, onchange: async (e) => {
    try { await put('/api/settings', { intervals_auto_send: e.target.checked }); toast(e.target.checked ? 'Automatische Übertragung ist an.' : 'Automatische Übertragung ist aus.', 'success'); }
    catch (err) { e.target.checked = !e.target.checked; toast(err.message, 'error'); }
  } });
  const numberField = (label, key, min, max) => h('label', { class: 'field' }, h('span', {}, label), h('input', { type: 'number', min, max, value: settings[key] ?? '', placeholder: 'optional',
    onchange: async (e) => { if (e.target.value === '') return; try { await put('/api/settings', { [key]: Number(e.target.value) }); toast('Gespeichert.', 'success'); } catch (err) { toast(err.message, 'error'); } } }));

  const prefs = h('section', { class: 'panel-box' }, h('h3', {}, 'Übertragung & Zonen'),
    h('label', { class: 'check' }, auto, h('span', {}, 'Einheiten beim Speichern automatisch an Intervals.icu senden (Standard: aus)')),
    h('div', { class: 'row' }, numberField('FTP (Watt) für die TSS-Schätzung', 'ftp', 50, 600), numberField('Schwellen-HF (bpm)', 'lthr', 80, 230)),
    h('p', { class: 'hint' }, 'FTP und Schwellen-HF werden für individuelle Zielbereiche und die TSS-Schätzung genutzt. Ohne Angabe zählt die gewählte Zielzone.'));

  const syncBox = st.has_key ? renderSyncBox(settings, sync) : null;

  const logBox = h('section', { class: 'panel-box' }, h('h3', {}, 'Übertragungsprotokoll'),
    log.length ? h('ul', { class: 'log' }, log.map((l) => h('li', { class: l.level }, h('time', {}, l.at.replace('T', ' ').slice(0, 16)), ' ', l.message))) : h('p', { class: 'empty' }, 'Noch keine Einträge.'));

  render(root, h('h2', {}, 'Einstellungen'), form, syncBox, prefs, logBox);
}

// ---------- Abgleich: Aktivitäten von Intervals.icu holen ----------
const when = (iso) => (iso ? new Date(iso).toLocaleString('de-DE', { dateStyle: 'medium', timeStyle: 'short' }) : '–');

function describe(last) {
  if (!last) return 'Noch kein Abgleich durchgeführt.';
  const parts = [`${last.found} gefunden`, `${last.imported} mit Messdaten importiert`];
  if (last.summary_only) parts.push(`${last.summary_only} nur mit Kennzahlen (keine Datei bei Intervals.icu)`);
  parts.push(`${last.already} schon vorhanden`);
  return `Zuletzt ${when(last.at)} (letzte ${last.days} Tage): ${parts.join(', ')}.`;
}

function renderSyncBox(settings, initial) {
  const status = h('p', { class: 'hint', role: 'status' });
  const problems = h('ul', { class: 'log' });
  const button = h('button', { type: 'button', class: 'primary' }, 'Jetzt abgleichen');
  const box = h('section', { class: 'panel-box' }, h('h3', {}, 'Aktivitäten von Intervals.icu'),
    h('p', { class: 'hint' }, 'Taktspur holt absolvierte Aktivitäten (nur lesend) aus Intervals.icu der letzten Tage, wertet sie hier aus und zeigt sie im Kalender und unter Aktivitäten. Bereits vorhandene werden nicht doppelt angelegt; hier gelöschte kommen nicht wieder. Es wird nichts an Intervals.icu gesendet.'),
    h('div', { class: 'row' },
      h('label', { class: 'field' }, h('span', {}, 'Zeitraum in Tagen (1–730)'), h('input', { type: 'number', min: 1, max: 730, value: settings.intervals_history_days,
        onchange: async (e) => { const v = Number(e.target.value); if (!(v >= 1 && v <= 730)) { toast('Bitte eine Zahl von 1 bis 730 eingeben.', 'error'); e.target.value = settings.intervals_history_days; return; }
          try { await put('/api/settings', { intervals_history_days: v }); settings.intervals_history_days = v; toast('Gespeichert.', 'success'); } catch (err) { toast(err.message, 'error'); } } }))),
    h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: settings.intervals_sync_on_start, onchange: async (e) => {
      try { await put('/api/settings', { intervals_sync_on_start: e.target.checked }); toast(e.target.checked ? 'Beim Start wird nach neuen Aktivitäten gesucht.' : 'Automatischer Abgleich beim Start ist aus.', 'success'); }
      catch (err) { e.target.checked = !e.target.checked; toast(err.message, 'error'); } } }), h('span', {}, 'Beim Start von Taktspur automatisch nach neuen Aktivitäten suchen')),
    h('div', { class: 'actions' }, button), status, problems);

  function show(state) {
    button.disabled = state.running;
    status.textContent = state.running ? 'Abgleich läuft …' : describe(state.last);
    status.className = state.last && state.last.error && !state.running ? 'form-message error' : 'hint';
    const issues = state.running || !state.last ? [] : [...(state.last.error ? [state.last.error] : []), ...state.last.failed];
    render(problems, issues.map((m) => h('li', { class: 'error' }, m)));
  }
  async function poll() {
    try {
      const state = await get('/api/intervals/sync');
      show(state);
      if (state.running && document.body.contains(box)) setTimeout(poll, 1500);
      else if (!state.running && wasRunning) { wasRunning = false; toast('Abgleich abgeschlossen.', state.last && state.last.error ? 'error' : 'success'); }
    } catch (err) { status.textContent = err.message; }
  }
  let wasRunning = false;
  button.addEventListener('click', async () => {
    button.disabled = true;
    try { show(await post('/api/intervals/sync', {})); wasRunning = true; setTimeout(poll, 800); }
    catch (err) { toast(err.message, 'error', 8000); button.disabled = false; }
  });
  show(initial);
  if (initial.running) { wasRunning = true; setTimeout(poll, 1000); }
  return box;
}
