// Aktivitäten: FIT-Import, alle Messkanäle als Diagramme und Tabellen, HRV/DFA a1.
import { ApiError, del, get, put, upload } from './api.js';
import { lineChart } from './charts.js';
import { h, render, toast } from './dom.js';
import { dateTime, duration, km, kmh, num, pace, paceFromSpeed, SPORT } from './format.js';

const SYNC = 'aktivitaet';
let charts = [];
const destroyCharts = () => { charts.forEach((c) => c.destroy()); charts = []; };

const wrapTable = (...children) => h('div', { class: 'table-wrap' }, h('table', {}, ...children));
const tr = (cells, header = false) => h('tr', {}, cells.map((c) => h(header ? 'th' : 'td', header ? { scope: 'col' } : {}, c)));
const section = (title, ...body) => h('section', { class: 'panel-box act-section' }, h('h3', {}, title), ...body);

// ---------- Liste ----------
export async function renderActivities(root, activityId = null) {
  destroyCharts();
  if (activityId) return renderDetail(root, activityId);
  let list;
  try { list = await get('/api/activities'); } catch (e) { render(root, h('p', { class: 'form-message error', role: 'alert' }, e.message)); return; }
  const message = h('p', { class: 'form-message', role: 'status', hidden: true });
  const input = h('input', { type: 'file', accept: '.fit,application/octet-stream', multiple: true, hidden: true, id: 'fit-input' });
  input.addEventListener('change', async () => {
    const files = [...input.files];
    input.value = '';
    let imported = 0; const problems = [];
    for (const file of files) {
      message.hidden = false; message.className = 'form-message'; message.textContent = `Importiere ${file.name} …`;
      try { await upload(`/api/activities?filename=${encodeURIComponent(file.name)}`, await file.arrayBuffer()); imported += 1; }
      catch (e) { problems.push(`${file.name}: ${e instanceof ApiError ? e.message : 'Import fehlgeschlagen.'}`); }
    }
    if (imported) toast(`${imported} Aktivität${imported > 1 ? 'en' : ''} importiert.`, 'success');
    if (problems.length) toast(problems.join(' · '), 'error', 9000);
    await renderActivities(root);
  });
  const rows = list.map((a) => h('a', { class: 'card activity-card', href: `#activities/${a.id}` },
    h('div', { class: 'card-top' }, h('small', {}, `${dateTime(a.start_time)} · ${SPORT[a.sport] || a.sport || 'Aktivität'}`),
      h('span', { class: 'badges' }, a.has_rr ? h('em', { class: 'badge sync-sent' }, 'HRV') : h('em', { class: 'badge' }, 'ohne HRV'))),
    h('strong', {}, a.name),
    h('span', { class: 'card-meta' }, [duration(a.duration_s), a.distance_m ? `${km(a.distance_m)} km` : null, a.avg_hr ? `Ø ${num(a.avg_hr, 0)} bpm` : null, a.avg_power ? `Ø ${num(a.avg_power, 0)} W` : null].filter(Boolean).join(' · '))));
  render(root, 
    h('h2', {}, 'Aktivitäten'),
    h('p', { class: 'hint' }, 'FIT-Dateien importieren (z. B. Export aus Intervals.icu oder von der Uhr). Die Auswertung bleibt auf diesem Gerät.'),
    h('div', { class: 'actions' }, input, h('button', { type: 'button', class: 'primary', onclick: () => input.click() }, 'FIT-Dateien importieren')),
    message,
    rows.length ? rows : h('p', { class: 'empty' }, 'Noch keine Aktivität importiert.'));
}

// ---------- Detail ----------
const SESSION_LABELS = {
  start_time: ['Start', (v) => dateTime(v)], timestamp: ['Ende', (v) => dateTime(v)], sport: ['Sportart', (v) => SPORT[v] || v], sub_sport: ['Unterart', String],
  total_elapsed_time: ['Gesamtzeit', duration], total_timer_time: ['Zeit (Timer)', duration], total_moving_time: ['Bewegungszeit', duration],
  total_distance: ['Distanz (km)', km], num_laps: ['Runden', String],
  avg_speed: ['Ø Geschwindigkeit', (v) => `${kmh(v)} km/h`], enhanced_avg_speed: ['Ø Geschwindigkeit', (v) => `${kmh(v)} km/h · ${paceFromSpeed(v)} min/km`],
  max_speed: ['Max. Geschwindigkeit', (v) => `${kmh(v)} km/h`], enhanced_max_speed: ['Max. Geschwindigkeit', (v) => `${kmh(v)} km/h · ${paceFromSpeed(v)} min/km`],
  avg_heart_rate: ['Ø Herzfrequenz (bpm)', (v) => num(v, 0)], max_heart_rate: ['Max. Herzfrequenz (bpm)', (v) => num(v, 0)], min_heart_rate: ['Min. Herzfrequenz (bpm)', (v) => num(v, 0)],
  avg_power: ['Ø Leistung (W)', (v) => num(v, 0)], max_power: ['Max. Leistung (W)', (v) => num(v, 0)], normalized_power: ['Normalisierte Leistung (W)', (v) => num(v, 0)],
  total_work: ['Arbeit (kJ)', (v) => num(v / 1000, 0)], training_stress_score: ['TSS', (v) => num(v, 0)], intensity_factor: ['IF', (v) => num(v, 2)], threshold_power: ['Schwellenleistung (W)', (v) => num(v, 0)],
  total_ascent: ['Anstieg (m)', (v) => num(v, 0)], total_descent: ['Abstieg (m)', (v) => num(v, 0)], avg_grade: ['Ø Steigung (%)', (v) => num(v * 100, 1)],
  avg_cadence: ['Ø Kadenz (Doppelschritte/min)', (v) => num(v, 0)], max_cadence: ['Max. Kadenz', (v) => num(v, 0)], avg_running_cadence: ['Ø Schrittfrequenz (spm)', (v) => num(v, 0)], max_running_cadence: ['Max. Schrittfrequenz (spm)', (v) => num(v, 0)],
  avg_vertical_oscillation: ['Ø Vertikale Oszillation (mm)', (v) => num(v, 1)], avg_vertical_ratio: ['Ø Vertikalverhältnis (%)', (v) => num(v, 1)], avg_stance_time: ['Ø Bodenkontaktzeit (ms)', (v) => num(Array.isArray(v) ? v[0] : v, 0)],
  avg_step_length: ['Ø Schrittlänge (m)', (v) => num(v / 1000, 2)], avg_stance_time_percent: ['Ø Bodenkontakt (%)', (v) => num(v, 1)], intensity: ['Intensität', (v) => INTENSITY[v] || String(v)],
  min_altitude: ['Min. Höhe (m)', (v) => num(v, 1)], max_altitude: ['Max. Höhe (m)', (v) => num(v, 1)], avg_altitude: ['Ø Höhe (m)', (v) => num(v, 1)],
  enhanced_min_altitude: ['Min. Höhe (m)', (v) => num(v, 1)], enhanced_max_altitude: ['Max. Höhe (m)', (v) => num(v, 1)], enhanced_avg_altitude: ['Ø Höhe (m)', (v) => num(v, 1)],
  first_lap_index: ['Erste Runde', String], repetition_num: ['Wiederholung', String], RunCadence: ['Schrittfrequenz (spm)', (v) => num(v, 0)],
};
const INTENSITY = { active: 'Belastung', recovery: 'Erholung', warmup: 'Aufwärmen', cooldown: 'Abkühlen', rest: 'Pause', interval: 'Intervall', other: 'Sonstiges' };
const SKIP_DUP = new Set(['avg_speed', 'max_speed', 'min_altitude', 'max_altitude', 'avg_altitude']);   // „enhanced_*“ gleichwertig vorhanden → nicht doppelt zeigen
const fieldRow = (key, value) => {
  const [label, fmt] = SESSION_LABELS[key] || [key, (v) => (typeof v === 'number' ? num(v, 2) : Array.isArray(v) ? v.join(', ') : String(v))];
  return [label, fmt(value)];
};

async function renderDetail(root, id) {
  let a, hrv;
  try { [a, hrv] = await Promise.all([get(`/api/activities/${id}`), get(`/api/activities/${id}/hrv`)]); }
  catch (e) { render(root, h('p', { class: 'form-message error', role: 'alert' }, e.message), h('a', { href: '#activities', class: 'link' }, '← Zur Liste')); return; }
  const s = a.session, isRun = a.sport === 'running';
  const out = [];

  // Kopf
  out.push(h('div', { class: 'act-head' },
    h('a', { href: '#activities', class: 'link' }, '← Alle Aktivitäten'),
    h('h2', {}, a.name),
    h('p', { class: 'hint' }, `${dateTime(a.start_time)} · ${SPORT[a.sport] || a.sport}${a.sub_sport && a.sub_sport !== 'generic' ? ` (${a.sub_sport})` : ''}`),
    h('div', { class: 'actions' },
      h('a', { class: 'secondary button-link', href: `/api/activities/${id}/export.csv`, download: '' }, 'Alle Messwerte als CSV'),
      h('button', { type: 'button', class: 'secondary', onclick: async () => {
        const name = window.prompt('Neuer Name:', a.name); if (!name || name.trim() === a.name) return;
        try { await put(`/api/activities/${id}`, { name: name.trim() }); await renderActivities(root, id); } catch (e) { toast(e.message, 'error'); }
      } }, 'Umbenennen'),
      h('button', { type: 'button', class: 'danger', onclick: async () => {
        if (!window.confirm(`Aktivität „${a.name}“ aus Taktspur löschen? Die Original-FIT-Datei bleibt unberührt.`)) return;
        try { await del(`/api/activities/${id}`); location.hash = '#activities'; } catch (e) { toast(e.message, 'error'); }
      } }, 'Löschen'))));

  // Kennzahlen
  const avgSpeed = s.enhanced_avg_speed ?? s.avg_speed;
  const tiles = [
    ['Dauer', duration(s.total_timer_time ?? a.duration_s)], ['Distanz', `${km(a.distance_m)} km`],
    [isRun ? 'Ø Pace' : 'Ø Tempo', isRun ? `${paceFromSpeed(avgSpeed)} min/km` : `${kmh(avgSpeed)} km/h`],
    ['Ø Herzfrequenz', s.avg_heart_rate ? `${num(s.avg_heart_rate, 0)} bpm` : '–'], ['Max. Herzfrequenz', s.max_heart_rate ? `${num(s.max_heart_rate, 0)} bpm` : '–'],
    ['Ø Leistung', s.avg_power ? `${num(s.avg_power, 0)} W` : '–'], ['Norm. Leistung', s.normalized_power ? `${num(s.normalized_power, 0)} W` : '–'],
    ['Anstieg', s.total_ascent !== undefined ? `${num(s.total_ascent, 0)} m` : '–'], ['TSS', s.training_stress_score ? num(s.training_stress_score, 0) : '–'], ['IF', s.intensity_factor ? num(s.intensity_factor, 2) : '–'],
  ];
  out.push(section('Übersicht', h('div', { class: 'tiles' }, tiles.map(([k, v]) => h('div', { class: 'tile' }, h('small', {}, k), h('strong', {}, v)))),
    h('details', {}, h('summary', {}, 'Alle Sitzungswerte aus der Datei'),
      wrapTable(h('tbody', {}, Object.entries(s).filter(([k]) => !SKIP_DUP.has(k) || !(`enhanced_${k}` in s)).map(([k, v]) => tr(fieldRow(k, v))))))));

  // Diagramme
  const t = a.t, d = a.data, labels = Object.fromEntries(a.channels.map((c) => [c.key, c]));
  const chartSection = h('section', { class: 'panel-box act-section' }, h('h3', {}, 'Verlauf'), h('p', { class: 'hint' }, 'Ziehen zum Zoomen (gilt für alle Diagramme), Doppelklick setzt zurück. Die Legende zeigt die Werte unter dem Mauszeiger.'));
  out.push(chartSection);
  const used = new Set();
  const make = (title, defs, extra = {}) => {
    const series = defs.filter(([k]) => d[k]).map(([k, scale, over]) => { used.add(k); return { label: labels[k].label, unit: labels[k].unit, values: d[k], scale, ...(over || {}) }; });
    if (!series.length) return;
    charts.push(lineChart(chartSection, { title, x: t, series, xFormat: duration, xLabel: 'Zeit', syncKey: SYNC, ...extra }));
  };
  const res = a.resolution_s || 1, win = Math.max(1, Math.round(10 / res));
  const smooth = (arr) => arr.map((_, i) => { let sum = 0, n = 0; for (let j = Math.max(0, i - win + 1); j <= i; j++) if (arr[j] !== null) { sum += arr[j]; n++; } return n ? sum / n : null; });
  if (d.speed) {
    used.add('speed');
    if (isRun) {
      const sp = smooth(d.speed);
      charts.push(lineChart(chartSection, { title: 'Pace (Ø 10 s, langsamer als 12 min/km nicht dargestellt)', x: t, xFormat: duration, xLabel: 'Zeit', syncKey: SYNC, yReverse: true,
        series: [{ label: 'Pace', unit: 'min/km', format: (v) => pace(v), tickFormat: (v) => pace(v), values: sp.map((v) => (v && 1000 / v <= 720 ? 1000 / v : null)) }] }));
    } else {
      charts.push(lineChart(chartSection, { title: 'Geschwindigkeit', x: t, xFormat: duration, xLabel: 'Zeit', syncKey: SYNC, series: [{ label: 'Geschwindigkeit', unit: 'km/h', values: d.speed.map((v) => (v === null ? null : v * 3.6)) }] }));
    }
  }
  make('Herzfrequenz und Leistung', [['heart_rate', 'y'], ['power', 'y2']]);
  make('Höhe', [['altitude', 'y', { fill: true }]]);
  make('Schrittfrequenz / Trittfrequenz und Schrittlänge', [['cadence', 'y'], ['step_length', 'y2']]);
  make('Laufdynamik: Bodenkontaktzeit und Vertikale Oszillation', [['stance_time', 'y'], ['vertical_oscillation', 'y2']]);
  make('Vertikalverhältnis', [['vertical_ratio', 'y']]);
  make('Atemfrequenz und Temperatur', [['respiration', 'y'], ['temperature', 'y2']]);
  for (const c of a.channels) if (!used.has(c.key) && c.key !== 'distance') make(c.label, [[c.key, 'y']]);

  // HRV / DFA a1
  out.push(hrvSection(hrv, isRun));

  // Runden
  if (a.laps.length) out.push(lapsSection(a.laps, isRun));

  // Werte pro Zeitabschnitt
  out.push(tableSection(id));

  render(root, ...out.map((x) => x));
  // Diagramme brauchen ihren Container im DOM → erst jetzt einhängen
  charts.forEach((c) => c.plot.setSize({ width: Math.max(240, c.plot.root.parentElement.clientWidth), height: 240 }));
  void renderHrvCharts(root, hrv);
}

// ---------- HRV ----------
const HRV_ID = 'hrv-charts';
function hrvSection(hrv) {
  if (!hrv.available) return section('HRV und DFA a1', h('p', { class: 'readonly-note' }, hrv.reason || 'Keine HRV-Daten.'));
  const st = hrv.stats, th = hrv.thresholds, m = hrv.method;
  const rows = [
    ['Erfasste Schläge', num(st.beats, 0)], ['Artefakte (erkannt und ersetzt)', `${num(st.artifacts, 0)} (${num(st.artifact_percent, 1)} %)`],
    ['Ø RR-Intervall', `${num(st.mean_rr_ms, 0)} ms`], ['Ø Herzfrequenz aus RR', `${num(st.mean_hr, 0)} bpm`],
    ['SDNN', `${num(st.sdnn_ms, 1)} ms`], ['RMSSD', `${num(st.rmssd_ms, 1)} ms`], ['pNN50', `${num(st.pnn50_percent, 1)} %`],
    ['DFA a1 Ø / Min / Max', st.alpha1_mean === null ? '–' : `${num(st.alpha1_mean, 2)} / ${num(st.alpha1_min, 2)} / ${num(st.alpha1_max, 2)}`],
    ['Gültige a1-Fenster', `${st.alpha1_valid_windows} von ${st.alpha1_total_windows}`],
    ['Zeit mit a1 > 0,75', st.share_above_075_percent === undefined ? '–' : `${num(st.share_above_075_percent, 0)} %`],
    ['Zeit mit a1 zwischen 0,75 und 0,5', st.share_075_to_05_percent === undefined ? '–' : `${num(st.share_075_to_05_percent, 0)} %`],
    ['Zeit mit a1 < 0,5', st.share_below_05_percent === undefined ? '–' : `${num(st.share_below_05_percent, 0)} %`],
  ];
  const thresholdBox = th.reliable
    ? h('p', { class: 'summary' }, `Geschätzte Herzfrequenz bei a1 = 0,75: ${num(th.hr_at_075, 0)} bpm${th.hr_at_05 ? ` · bei a1 = 0,5: ${num(th.hr_at_05, 0)} bpm` : ''} (R² = ${num(th.r2, 2)}, ${th.windows} Fenster). Nur eine Orientierung.`)
    : h('p', { class: 'hint' }, `Schwellen-Schätzung nicht belastbar: ${th.reason} Für belastbare Werte braucht es einen Stufentest mit steigender Belastung.`);
  return h('section', { class: 'panel-box act-section' }, h('h3', {}, 'HRV und DFA a1'),
    h('p', { class: 'hint' }, 'Berechnet aus den echten Schlag-zu-Schlag-Intervallen (RR) der Datei – nicht aus der Herzfrequenz geschätzt. Aussagekräftig nur mit Brustgurt; optische Sensoren am Handgelenk liefern oft zu ungenaue RR.'),
    wrapTable(h('tbody', {}, rows.map((r) => tr(r)))),
    thresholdBox,
    h('div', { id: HRV_ID }),
    h('details', {}, h('summary', {}, 'Methode und Grenzen'), h('div', { class: 'hint method' },
      h('p', {}, `Kurzzeit-Skalierungsexponent α1 der Detrended Fluctuation Analysis über Boxgrößen ${m.box[0]}–${m.box[1]} Schläge (Peng et al. 1995), gleitendes ${m.window_s}-s-Fenster, Schritt ${m.step_s} s. Trend-Entfernung per „smoothness priors“ mit λ = ${m.lambda} (Tarvainen et al. 2002, wie in Kubios HRV).`),
      h('p', {}, `Artefakte: Schläge mit mehr als 20 % Abweichung vom lokalen Median (11 Schläge) oder unmöglichen Werten werden linear interpoliert. Fenster mit mehr als ${m.max_artifact_percent} % Artefakten gelten als ungültig und bleiben im Diagramm leer.`),
      h('p', {}, 'Orientierung aus Stufentests gesunder, trainierter Erwachsener (u. a. Gronwald et al.; Rogers et al. 2021): a1 ≈ 0,75 entspricht etwa der ersten Schwelle (aerob), a1 ≈ 0,5 etwa der zweiten (anaerob). Das sind Mittelwerte mit deutlicher individueller Streuung, keine medizinische Aussage. Werte sinken mit Ermüdung und Hitze und hängen von der RR-Qualität ab. Die Zeitachse der RR-Daten beginnt mit der ersten HRV-Nachricht und kann um Sekunden gegen die Aufzeichnung verschoben sein.'))));
}

async function renderHrvCharts(root, hrv) {
  const host = root.querySelector(`#${HRV_ID}`);
  if (!host || !hrv.available) return;
  const al = hrv.alpha1, ref = (v) => al.t.map(() => v);
  charts.push(lineChart(host, { title: 'DFA a1 (gleitendes 120-s-Fenster)', x: al.t, xFormat: duration, xLabel: 'Zeit', syncKey: SYNC, height: 260,
    series: [{ label: 'DFA a1', values: al.value, color: '#0f766e', format: (v) => num(v, 2) },
      { label: 'Orientierung HRVT1 (0,75)', values: ref(0.75), dash: [6, 4], color: '#b45309', format: (v) => num(v, 2) },
      { label: 'Orientierung HRVT2 (0,5)', values: ref(0.5), dash: [2, 4], color: '#b42318', format: (v) => num(v, 2) },
      { label: 'Herzfrequenz (Fensterwert)', unit: 'bpm', values: al.hr, scale: 'y2', color: '#7c3aed', format: (v) => num(v, 0) }],
    note: 'Leere Stellen: zu viele Artefakte im Fenster oder zu wenige Schläge.' }));
  const normal = hrv.rr.ms.filter((_, i) => !hrv.rr.artifact[i]).sort((x, y) => x - y);
  const top = normal.length ? normal[Math.floor(normal.length * 0.995)] : 1500;
  charts.push(lineChart(host, { title: 'RR-Intervalle (Tachogramm) mit erkannten Artefakten', x: hrv.rr.t, xFormat: duration, xLabel: 'Zeit', syncKey: SYNC,
    yRange: [Math.max(0, Math.round(normal[0] * 0.5 / 50) * 50), Math.ceil((top * 1.3) / 100) * 100],
    note: 'Die Achse zeigt den Normalbereich; einzelne extreme Artefakte (> 2 s oder sehr kurz) liegen außerhalb und sind in den Kennzahlen mitgezählt.',
    series: [{ label: 'RR-Intervall', unit: 'ms', values: hrv.rr.ms, color: '#2563eb', format: (v) => num(v, 0) },
      { label: 'Artefakt', unit: 'ms', values: hrv.rr.ms.map((v, i) => (hrv.rr.artifact[i] ? v : null)), points: true, color: '#b42318', format: (v) => num(v, 0) }] }));
}

// ---------- Runden ----------
function lapsSection(laps, isRun) {
  const first = laps[0].start_time ? new Date(laps[0].start_time).getTime() : null;
  const speed = (l) => l.enhanced_avg_speed ?? l.avg_speed;
  const cols = [['#', (l, i) => String(i + 1)], ['Start', (l) => (first && l.start_time ? duration((new Date(l.start_time).getTime() - first) / 1000) : '–')],
    ['Dauer', (l) => duration(l.total_timer_time ?? l.total_elapsed_time)], ['Distanz (km)', (l) => km(l.total_distance)],
    [isRun ? 'Pace (min/km)' : 'Tempo (km/h)', (l) => (isRun ? paceFromSpeed(speed(l)) : kmh(speed(l)))],
    ['Ø HF', (l) => num(l.avg_heart_rate, 0)], ['Max HF', (l) => num(l.max_heart_rate, 0)], ['Ø Leistung (W)', (l) => num(l.avg_power, 0)], ['Norm. Leistung (W)', (l) => num(l.normalized_power, 0)],
    ['Schritte/min', (l) => num(l.avg_running_cadence ? l.avg_running_cadence * 2 : l.avg_cadence ? l.avg_cadence * (isRun ? 2 : 1) : null, 0)], ['Anstieg (m)', (l) => num(l.total_ascent, 0)], ['Intensität', (l) => INTENSITY[l.intensity] || l.intensity || '–']];
  const keys = [...new Set(laps.flatMap((l) => Object.keys(l)))].filter((k) => !SKIP_DUP.has(k) || !laps.some((l) => `enhanced_${k}` in l));
  return section('Runden',
    wrapTable(h('thead', {}, tr(cols.map((c) => c[0]), true)), h('tbody', {}, laps.map((l, i) => tr(cols.map((c) => c[1](l, i)))))),
    h('details', {}, h('summary', {}, 'Alle Rundenwerte aus der Datei'),
      wrapTable(h('thead', {}, tr(['#', ...keys.map((k) => fieldRow(k, 0)[0])], true)), h('tbody', {}, laps.map((l, i) => tr([String(i + 1), ...keys.map((k) => (l[k] === undefined ? '–' : fieldRow(k, l[k])[1]))]))))));
}

// ---------- Tabelle pro Zeitabschnitt ----------
function tableSection(id) {
  const holder = h('div', {});
  const select = h('select', { 'aria-label': 'Zeitabschnitt', onchange: () => load(Number(select.value)) },
    [[30, '30 Sekunden'], [60, '1 Minute'], [120, '2 Minuten'], [300, '5 Minuten']].map(([v, l]) => h('option', { value: v, selected: v === 60 }, l)));
  async function load(bucket) {
    try {
      const t = await get(`/api/activities/${id}/table?bucket=${bucket}`);
      const fmt = (c, v) => (v === null || v === undefined ? '–' : c.key === 'pace_s_per_km' ? pace(v) : c.key === 'speed' ? `${kmh(v)}` : c.key === 'distance' ? km(v) : c.key === 'alpha1' ? num(v, 2) : num(v, Math.abs(v) >= 100 ? 0 : 1));
      holder.replaceChildren(wrapTable(
        h('thead', {}, tr(['Zeit', ...t.columns.map((c) => (c.key === 'speed' ? 'Geschwindigkeit (km/h)' : c.key === 'distance' ? 'Distanz (km)' : c.unit ? `${c.label} (${c.unit})` : c.label))], true)),
        h('tbody', {}, t.rows.map((r) => tr([`${duration(r.from_s)}–${duration(r.to_s)}`, ...t.columns.map((c) => fmt(c, r[c.key]))])))));
    } catch (e) { holder.replaceChildren(h('p', { class: 'form-message error', role: 'alert' }, e.message)); }
  }
  load(60);
  return section('Werte pro Zeitabschnitt', h('label', { class: 'field narrow' }, h('span', {}, 'Zeitabschnitt'), select), holder,
    h('p', { class: 'hint' }, 'Mittelwerte je Abschnitt (Distanz: Stand am Ende). Alle Rohwerte im Sekundentakt gibt es als CSV.'));
}
