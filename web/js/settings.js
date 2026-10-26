import { del, get, post, put } from './api.js';
import { h, toast } from './dom.js';

export async function renderSettings(root) {
  let st, settings, log;
  try { [st, settings, log] = await Promise.all([get('/api/intervals'), get('/api/settings'), get('/api/intervals/log')]); }
  catch (e) { root.replaceChildren(h('p', { class: 'form-message error', role: 'alert' }, e.message)); return; }
  const refresh = () => renderSettings(root);
  const message = h('p', { class: 'form-message', role: 'alert', hidden: true });
  const fail = (e) => { message.textContent = e.message; message.className = 'form-message error'; message.hidden = false; };

  const idInput = h('input', { name: 'athlete', required: true, maxlength: 20, value: st.athlete_id || '', placeholder: 'z. B. i12345', autocomplete: 'off', inputmode: 'text' });
  const keyInput = h('input', { name: 'key', type: 'password', required: !st.connected, maxlength: 200, autocomplete: 'off', placeholder: st.connected ? 'Gespeichert – nur zum Ersetzen neu eingeben' : 'API-Schlüssel aus Intervals.icu' });

  const statusLine = st.connected
    ? h('p', { class: 'pill sent', role: 'status' }, `Verbunden mit ${st.athlete_id}`)
    : st.athlete_id ? h('p', { class: 'pill error', role: 'alert' }, `Verbindung gestört: ${st.last_error}`) : h('p', { class: 'pill none' }, 'Nicht verbunden');

  const form = h('form', { class: 'panel-box', onsubmit: async (e) => {
    e.preventDefault();
    if (!keyInput.value) { fail(new Error('Bitte den API-Schlüssel eingeben.')); return; }
    try { await put('/api/intervals', { athlete_id: idInput.value.trim(), api_key: keyInput.value.trim() }); keyInput.value = ''; toast('Intervals.icu verbunden.', 'success'); await refresh(); }
    catch (err) { keyInput.value = ''; fail(err); }
  } },
    h('h3', {}, 'Intervals.icu'), statusLine,
    h('p', { class: 'hint' }, 'Der API-Schlüssel wird verschlüsselt auf diesem Gerät gespeichert und nie an den Browser zurückgegeben. Es werden nur in Taktspur geplante Workouts übertragen; importierte oder absolvierte Einträge bleiben schreibgeschützt.'),
    h('label', { class: 'field' }, h('span', {}, 'Athleten-ID'), idInput),
    h('label', { class: 'field' }, h('span', {}, 'API-Schlüssel'), keyInput),
    message,
    h('div', { class: 'actions' },
      h('button', { type: 'submit', class: 'primary' }, st.athlete_id ? 'Neu verbinden' : 'Verbinden'),
      st.athlete_id ? h('button', { type: 'button', class: 'secondary', onclick: async () => { try { const r = await post('/api/intervals/verify'); toast(r.connected ? 'Verbindung ist in Ordnung.' : `Verbindung gestört: ${r.last_error}`, r.connected ? 'success' : 'error', 8000); await refresh(); } catch (err) { fail(err); } } }, 'Verbindung prüfen') : null,
      st.athlete_id ? h('button', { type: 'button', class: 'danger', onclick: async () => { if (!window.confirm('Verbindung trennen und gespeicherten Schlüssel löschen?')) return; try { await del('/api/intervals'); toast('Verbindung getrennt.', 'success'); await refresh(); } catch (err) { fail(err); } } }, 'Trennen') : null));

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

  const logBox = h('section', { class: 'panel-box' }, h('h3', {}, 'Übertragungsprotokoll'),
    log.length ? h('ul', { class: 'log' }, log.map((l) => h('li', { class: l.level }, h('time', {}, l.at.replace('T', ' ').slice(0, 16)), ' ', l.message))) : h('p', { class: 'empty' }, 'Noch keine Einträge.'));

  root.replaceChildren(h('h2', {}, 'Einstellungen'), form, prefs, logBox);
}
