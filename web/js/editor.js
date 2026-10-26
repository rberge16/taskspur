// Workout-Dialog: Einzeleinheit oder Koppeleinheit (zwei vollständige, getrennt bearbeitbare Teile).
import { ApiError, del, get, post, put } from './api.js';
import { h, toast } from './dom.js';
import { stepsEditor } from './steps.js';

const SPORTS = ['Radfahren', 'Laufen', 'Schwimmen', 'Kraft / Mobility', 'Recovery'];
const KINDS = [['normal', 'Normal'], ['important', 'Wichtig'], ['test', 'Leistungstest']];
const STATUS_TEXT = { none: 'Nicht übertragen', sending: 'Wird gesendet …', sent: 'Übertragen', error: 'Fehler' };

const blankPart = (over = {}) => ({
  id: null, title: '', sport: '', description: '', kind: 'normal', date: '', start_time: '', steps: [], plan_id: '', phase_id: '',
  duration_min: 0, tss: 0, link_order: null, read_only: false, sync_status: 'none', sync_error: null, ...over,
});

const fromWorkout = (w) => blankPart({ ...w, date: w.date || '', start_time: w.start_time || '', plan_id: w.plan_id || '', phase_id: w.phase_id || '', steps: structuredClone(w.steps) });

function payload(part, main) {
  const isSecond = part.link_order === 2;
  return {
    title: part.title.trim(), sport: part.sport, description: part.description, kind: main.kind,
    date: (isSecond ? main.date : part.date) || null,
    start_time: (isSecond ? main.start_time : part.start_time) || null,
    steps: part.steps,
    plan_id: (isSecond ? main.plan_id : part.plan_id) || null,
    phase_id: (isSecond ? main.phase_id : part.phase_id) || null,
  };
}

export async function openEditor({ workoutId = null, date = '', plans = [], onChange = () => {} }) {
  const dialog = document.getElementById('editor');
  let parts, active = 0, brickMode = false, busy = false, previewTimer = null, previewSeq = 0, candidates = [];

  if (workoutId) {
    const w = await get(`/api/workouts/${workoutId}`);
    parts = [fromWorkout(w)];
    if (w.link_group) {
      const all = await get('/api/workouts');
      const other = all.find((x) => x.link_group === w.link_group && x.id !== w.id);
      parts = [w, other].filter(Boolean).sort((a, b) => a.link_order - b.link_order).map(fromWorkout);
      brickMode = parts.length === 2;
      active = brickMode ? parts.findIndex((p) => p.id === w.id) : 0;
    }
  } else {
    parts = [blankPart({ date })];
  }
  if (workoutId && parts.length === 1 && !parts[0].read_only) {
    const all = await get('/api/workouts');
    candidates = all.filter((x) => x.id !== workoutId && !x.link_group && !x.read_only);
  }
  const main = parts[0];            // Teil 1 bzw. Einzeleinheit: Datum, Zeit, Art, Plan
  const existing = Boolean(workoutId);              // beim Öffnen vorhanden (steuert Titel/Löschen)
  const saved = () => parts.every((p) => p.id);      // aktueller Speicherzustand: verhindert Dubletten bei erneutem Speichern
  let summary, syncBox, panel, tabs, saveButton, message;

  const part = () => parts[active];
  const readOnly = () => part().read_only;

  function showMessage(text, kind = 'error') {
    message.textContent = text || '';
    message.className = `form-message ${kind}`;
    message.hidden = !text;
  }

  function schedulePreview() {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(async () => {
      const seq = ++previewSeq;
      const p = part();
      if (!p.sport) { summary.textContent = 'Wähle eine Sportart, dann werden Dauer und TSS berechnet.'; return; }
      try {
        const r = await post('/api/preview', { title: 'x', sport: p.sport, steps: p.steps });
        if (seq !== previewSeq) return;
        summary.textContent = p.steps.length
          ? `Berechnet aus der Struktur: ${r.duration_min} Min. · ${r.tss} TSS`
          : 'Ohne Abschnitte gibt es keine berechnete Dauer und keine TSS.';
      } catch (e) { summary.textContent = e.message; }
    }, 250);
  }

  function renderSync() {
    const p = part();
    const issues = [];
    if (!(p.link_order === 2 ? main.date : p.date)) issues.push('Datum fehlt');
    if (!p.steps.length) issues.push('Abschnitt fehlt');
    const state = p.sync_status;
    const children = [h('strong', {}, 'Intervals.icu')];
    if (p.read_only) {
      children.push(h('p', { class: 'sync-line' }, 'Schreibgeschützt: Importierte und absolvierte Einträge werden nie zurückgeschrieben.'));
    } else if (!p.id) {
      children.push(h('p', { class: 'sync-line' }, 'Geplante Einheiten werden beim Speichern mit Intervals.icu abgeglichen (Einstellungen), sofern verbunden.'));
      issues.forEach((i) => children.push(h('span', { class: 'pill warn' }, i)));
    } else {
      children.push(h('span', { class: `pill ${state}`, role: 'status' }, STATUS_TEXT[state]));
      issues.forEach((i) => children.push(h('span', { class: 'pill warn' }, i)));
      if (state === 'error' && p.sync_error) children.push(h('p', { class: 'sync-line error', role: 'alert' }, p.sync_error));
      children.push(h('button', { type: 'button', class: 'secondary', disabled: busy || issues.length > 0, onclick: sendActive }, 'An Intervals.icu senden'));
    }
    syncBox.replaceChildren(...children);
  }

  async function sendActive() {
    if (busy) return;
    const p = part();
    if (!(await save({ close: false, quiet: true }))) return;
    busy = true; p.sync_status = 'sending'; p.sync_error = null; renderSync();
    try {
      const w = await post(`/api/workouts/${p.id}/send`);
      Object.assign(p, { sync_status: w.sync_status, sync_error: w.sync_error });
      toast('Workout wurde an Intervals.icu übertragen.', 'success');
    } catch (e) {
      Object.assign(p, { sync_status: 'error', sync_error: e.message });
      toast(`Übertragung fehlgeschlagen: ${e.message}`, 'error', 8000);
    } finally { busy = false; renderSync(); onChange(); }
  }

  async function save({ close = true, quiet = false } = {}) {
    if (busy) return false;
    for (const [i, p] of parts.entries()) {
      if (!p.title.trim()) { active = i; renderPanel(); showMessage(`Bitte einen Titel${brickMode ? ` für Teil ${i + 1}` : ''} eingeben.`); return false; }
      if (!p.sport) { active = i; renderPanel(); showMessage(`Bitte eine Sportart${brickMode ? ` für Teil ${i + 1}` : ''} wählen.`); return false; }
    }
    if (brickMode && !main.date) { showMessage('Für eine Koppeleinheit wird ein Datum benötigt.'); return false; }
    busy = true; saveButton.disabled = true; showMessage('');
    try {
      let results;
      if (!saved() && brickMode) {
        results = (await post('/api/workouts/brick', { part1: payload(parts[0], main), part2: payload(parts[1], main) })).workouts;
        results.forEach((w, i) => Object.assign(parts[i], fromWorkout(w)));
      } else if (!saved()) {
        const r = await post('/api/workouts', payload(parts[0], main));
        Object.assign(parts[0], fromWorkout(r.workouts[0]));
        results = r.workouts;
        reportAuto(r.auto_send);
      } else {
        for (const p of parts) {
          if (p.read_only) continue;
          const r = await put(`/api/workouts/${p.id}`, payload(p, main));
          reportAuto(r.auto_send);
          r.workouts.forEach((w) => { const target = parts.find((x) => x.id === w.id); if (target) Object.assign(target, fromWorkout(w)); });
        }
      }
      if (!quiet) toast('Einheit gespeichert.', 'success');
      onChange();
      if (close) dialog.close();
      return true;
    } catch (e) {
      showMessage(e instanceof ApiError ? e.message : 'Speichern fehlgeschlagen.');
      return false;
    } finally { busy = false; if (saveButton) saveButton.disabled = false; renderSync(); }
  }

  function reportAuto(info) {
    if (!info || !info.results || !info.results.length) return;
    const failed = info.results.filter((r) => !r.ok);
    if (failed.length) toast(`Einheit gespeichert. Abgleich mit Intervals.icu fehlgeschlagen: ${failed[0].message}`, 'error', 8000);
    else toast('Einheit gespeichert und mit Intervals.icu abgeglichen.', 'success');
  }

  async function remove() {
    const p = part();
    if (!p.id || busy) return;
    let cascade = false;
    const linked = brickMode && parts.length === 2;
    if (linked) {
      cascade = window.confirm('Beide Teile der Koppeleinheit löschen?\n\nOK = beide Teile löschen\nAbbrechen = weitere Auswahl');
      if (!cascade && !window.confirm(`Nur Teil ${p.link_order} löschen? Der andere Teil bleibt als einzelne Einheit erhalten.`)) return;
    } else {
      const extra = p.sync_status === 'sent' || p.synced_at ? ' Sie wird auch aus Intervals.icu entfernt.' : '';
      if (!window.confirm(`Einheit wirklich löschen?${extra}`)) return;
    }
    busy = true;
    try {
      await del(`/api/workouts/${p.id}${cascade ? '?cascade=true' : ''}`);
      toast('Einheit gelöscht.', 'success');
      onChange();
      dialog.close();
    } catch (e) {
      showMessage(`Löschen abgebrochen, lokal ist nichts verloren: ${e.message}`);
    } finally { busy = false; }
  }

  function planFields() {
    const activePlans = plans.filter((pl) => pl.status === 'active' || pl.id === main.plan_id);
    const phaseSelect = h('select', { id: 'phase', disabled: readOnly(), onchange: (e) => { main.phase_id = e.target.value; limitDate(); } });
    const fillPhases = () => {
      const plan = plans.find((pl) => pl.id === main.plan_id);
      phaseSelect.replaceChildren(...(plan ? plan.phases : []).map((ph) => h('option', { value: ph.id, selected: ph.id === main.phase_id }, `${ph.name} (${ph.start_date} – ${ph.end_date})`)));
      phaseSelect.parentElement && (phaseSelect.parentElement.hidden = !plan);
      if (plan && !plan.phases.some((ph) => ph.id === main.phase_id)) main.phase_id = plan.phases[0]?.id || '';
    };
    function limitDate() {
      const input = document.getElementById('f-date');
      const plan = plans.find((pl) => pl.id === main.plan_id);
      const phase = plan?.phases.find((ph) => ph.id === main.phase_id);
      if (!input) return;
      if (phase) { input.min = phase.start_date; input.max = phase.end_date; if (!main.date || main.date < phase.start_date || main.date > phase.end_date) { main.date = phase.start_date; input.value = main.date; renderSync(); } }
      else { input.removeAttribute('min'); input.removeAttribute('max'); }
    }
    const planSelect = h('select', { id: 'plan', disabled: readOnly(), onchange: (e) => {
      main.plan_id = e.target.value; main.phase_id = ''; fillPhases(); limitDate();
    } }, h('option', { value: '' }, 'Ohne Trainingsplan (freie Einheit)'), activePlans.map((pl) => h('option', { value: pl.id, selected: pl.id === main.plan_id }, pl.name)));
    const phaseLabel = h('label', { class: 'field' }, h('span', {}, 'Phase'), phaseSelect);
    queueMicrotask(() => { fillPhases(); limitDate(); });
    return h('div', { class: 'row' }, h('label', { class: 'field' }, h('span', {}, 'Trainingsplan'), planSelect), phaseLabel);
  }

  function renderPanel() {
    const p = part(); const ro = readOnly(); const second = p.link_order === 2 || (brickMode && active === 1);
    tabs.replaceChildren(...(brickMode ? parts.map((x, i) => h('button', { type: 'button', role: 'tab', 'aria-selected': i === active,
      class: i === active ? 'tab active' : 'tab', onclick: () => { active = i; renderPanel(); } },
      `Teil ${i + 1}${x.sport ? ` · ${x.sport}` : ''}`)) : []));
    tabs.hidden = !brickMode;
    const steps = stepsEditor(p.steps, () => { renderSync(); schedulePreview(); }, { readOnly: ro });
    const dateRow = second
      ? h('p', { class: 'follow-note' }, `Teil 2 beginnt automatisch direkt nach Teil 1 (gleicher Tag${p.start_time ? `, aktuell ${p.start_time} Uhr` : ''}).`)
      : h('div', { class: 'row' },
        h('label', { class: 'field' }, h('span', {}, 'Datum'), h('input', { id: 'f-date', type: 'date', value: p.date, disabled: ro, onchange: (e) => { p.date = e.target.value; renderSync(); } })),
        h('label', { class: 'field' }, h('span', {}, 'Startzeit'), h('input', { id: 'f-time', type: 'time', value: p.start_time, disabled: ro, onchange: (e) => { p.start_time = e.target.value; } })));
    panel.replaceChildren(...[
      ro ? h('p', { class: 'readonly-note' }, 'Schreibgeschützt: Diese Einheit stammt aus Intervals.icu bzw. ist absolviert und kann nicht bearbeitet werden.') : null,
      h('label', { class: 'field' }, h('span', {}, 'Titel'), h('input', { value: p.title, maxlength: 120, required: true, disabled: ro, placeholder: 'z. B. GA1 Ausdauer', oninput: (e) => { p.title = e.target.value; } })),
      h('div', { class: 'row' },
        h('label', { class: 'field' }, h('span', {}, 'Sportart'), h('select', { disabled: ro, onchange: (e) => { p.sport = e.target.value; schedulePreview(); renderTabsLabel(); } },
          h('option', { value: '' }, 'Bitte wählen'), SPORTS.map((s) => h('option', { value: s, selected: p.sport === s }, s)))),
        second ? null : h('label', { class: 'field' }, h('span', {}, 'Art der Einheit'), h('select', { disabled: ro, onchange: (e) => { main.kind = e.target.value; } },
          KINDS.map(([v, l]) => h('option', { value: v, selected: main.kind === v }, l))))),
      dateRow,
      second ? null : planFields(),
      h('label', { class: 'field' }, h('span', {}, 'Beschreibung'), h('textarea', { rows: 3, maxlength: 2000, disabled: ro, placeholder: 'Ziel, Intensität und Inhalt', oninput: (e) => { p.description = e.target.value; } }, p.description)),
      h('h3', {}, 'Struktur'), steps.element].filter(Boolean));
    schedulePreview(); renderSync();
  }
  function renderTabsLabel() { if (brickMode) tabs.replaceChildren(...parts.map((x, i) => h('button', { type: 'button', role: 'tab', 'aria-selected': i === active, class: i === active ? 'tab active' : 'tab', onclick: () => { active = i; renderPanel(); } }, `Teil ${i + 1}${x.sport ? ` · ${x.sport}` : ''}`))); }

  // ----- Koppeln / Verknüpfung lösen (nur für gespeicherte Einheiten) -----
  const linkBox = h('div', { class: 'sync-box', hidden: !existing });
  function renderLinkBox() {
    if (!existing) return;
    if (brickMode) {
      linkBox.replaceChildren(h('p', {}, 'Diese Einheit ist Teil einer Koppeleinheit.'),
        h('button', { type: 'button', class: 'secondary', onclick: async () => {
          if (!window.confirm('Verknüpfung lösen? Beide Einheiten bleiben als eigene Einheiten erhalten.')) return;
          try { await post(`/api/workouts/${parts[0].id}/unlink`); toast('Verknüpfung gelöst.', 'success'); onChange(); dialog.close(); }
          catch (e) { showMessage(e.message); }
        } }, 'Verknüpfung lösen'));
      return;
    }
    if (parts[0].read_only || !candidates.length) { linkBox.hidden = true; return; }
    const select = h('select', { id: 'link-partner', 'aria-label': 'Einheit für Teil 2' },
      h('option', { value: '' }, 'Einheit für Teil 2 wählen …'),
      candidates.map((c) => h('option', { value: c.id }, `${c.title} (${[c.date, c.start_time, c.sport].filter(Boolean).join(' · ') || 'ohne Datum'})`)));
    linkBox.replaceChildren(
      h('p', {}, 'Mit einer weiteren Einheit koppeln: Diese Einheit wird Teil 1, die gewählte folgt direkt danach als Teil 2 (Datum und Zeit richten sich nach Teil 1).'),
      h('div', { class: 'row' }, h('label', { class: 'field' }, h('span', {}, 'Teil 2'), select),
        h('button', { type: 'button', class: 'secondary', onclick: async () => {
          if (!select.value) { showMessage('Bitte zuerst die Einheit für Teil 2 wählen.'); return; }
          if (!(await save({ close: false, quiet: true }))) return;
          try { await post(`/api/workouts/${parts[0].id}/link`, { second_id: select.value }); toast('Zu einer Koppeleinheit verbunden.', 'success'); onChange(); dialog.close(); }
          catch (e) { showMessage(e.message); }
        } }, 'Koppeln')));
  }

  // ----- Aufbau -----
  tabs = h('div', { class: 'tabs', role: 'tablist' });
  panel = h('div', { class: 'panel' });
  summary = h('p', { class: 'summary' });
  syncBox = h('div', { class: 'sync-box' });
  message = h('p', { class: 'form-message', role: 'alert', hidden: true });
  saveButton = h('button', { type: 'submit', class: 'primary' }, 'Speichern');
  const brickToggle = !existing ? h('label', { class: 'check' },
    h('input', { type: 'checkbox', onchange: (e) => {
      brickMode = e.target.checked;
      if (brickMode && parts.length === 1) parts.push(blankPart({ link_order: 2 })); parts[0].link_order = brickMode ? 1 : null; active = 0;
      if (!brickMode) parts.length = 1;
      renderPanel();
    } }), h('span', {}, 'Koppeleinheit (zwei verbundene Einheiten nacheinander, z. B. Rad + Lauf)')) : null;

  const form = h('form', { method: 'dialog', onsubmit: (e) => { e.preventDefault(); save(); } },
    h('div', { class: 'dialog-head' }, h('h2', { id: 'editorTitle' }, existing ? 'Einheit bearbeiten' : 'Einheit planen'),
      h('button', { type: 'button', class: 'icon', 'aria-label': 'Schließen', onclick: () => dialog.close() }, '×')),
    brickToggle, tabs, panel, summary, syncBox, linkBox, message,
    h('div', { class: 'dialog-actions' },
      existing ? h('button', { type: 'button', class: 'danger', onclick: remove }, 'Löschen') : null,
      h('span', { class: 'spacer' }),
      h('button', { type: 'button', class: 'secondary', onclick: () => dialog.close() }, 'Abbrechen'),
      readOnly() ? null : saveButton));

  dialog.replaceChildren(form);
  dialog.addEventListener('close', () => dialog.replaceChildren(), { once: true });
  renderPanel();
  renderLinkBox();
  dialog.showModal();
}
