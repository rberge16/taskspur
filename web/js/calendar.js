// Kalender: Monat, Woche, Liste. Jede Ansicht wird komplett neu aufgebaut; Listener hängen nur an den neuen Elementen.
import { get } from './api.js';
import { h, render } from './dom.js';
import { openEditor } from './editor.js';
import { duration, km, num, SPORT } from './format.js';

const DAY_NAMES = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'];
const KIND_LABEL = { normal: 'Normal', important: 'Wichtig', test: 'Leistungstest' };
const SYNC_LABEL = { sent: 'Übertragen', sending: 'Wird gesendet', error: 'Fehler' };

const pad = (n) => String(n).padStart(2, '0');
export const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;   // lokal, ohne UTC-Verschiebung
const parse = (s) => { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d, 12); };
const addDays = (d, n) => { const c = new Date(d); c.setDate(c.getDate() + n); return c; };
const mondayOf = (d) => addDays(d, -((d.getDay() + 6) % 7));
const monthLabel = (d) => d.toLocaleDateString('de-DE', { month: 'long', year: 'numeric' });
const longDay = (s) => parse(s).toLocaleDateString('de-DE', { weekday: 'long', day: 'numeric', month: 'long' });

const state = { view: 'month', anchor: new Date(), selected: iso(new Date()) };
state.anchor.setHours(12);

export async function renderCalendar(root) {
  let workouts = [], plans = [], acts = [];
  try {
    [workouts, plans, acts] = await Promise.all([get('/api/workouts'), get('/api/plans'), get('/api/activities')]);
  } catch (e) {
    render(root, h('p', { class: 'form-message error', role: 'alert' }, e.message));
    return;
  }
  const refresh = () => renderCalendar(root);
  const open = (id, date = '') => openEditor({ workoutId: id, date, plans, onChange: refresh }).catch((e) => root.prepend(h('p', { class: 'form-message error', role: 'alert' }, e.message)));
  const byDate = new Map();
  workouts.filter((w) => w.date).forEach((w) => { if (!byDate.has(w.date)) byDate.set(w.date, []); byDate.get(w.date).push(w); });
  const undated = workouts.filter((w) => !w.date);
  // Absolvierte Aktivitäten (importiert oder von Intervals.icu): am lokalen Tag des Starts
  const actsByDate = new Map();
  acts.filter((a) => a.start_time).forEach((a) => { const k = iso(new Date(a.start_time)); if (!actsByDate.has(k)) actsByDate.set(k, []); actsByDate.get(k).push(a); });
  const actsOn = (k) => actsByDate.get(k) || [];
  const sportName = (a) => SPORT[a.sport] || a.sport || 'Aktivität';
  const actChip = (a) => h('a', { class: 'chip activity', href: `#activities/${a.id}`, 'aria-label': `Absolviert: ${a.name}, ${sportName(a)}${a.distance_m ? `, ${km(a.distance_m)} km` : ''}` },
    h('b', { class: 'done-mark', 'aria-hidden': 'true' }, '✓'), h('span', { class: 'chip-title' }, `${a.name}`));
  const actCard = (a) => h('a', { class: 'card activity-card done', href: `#activities/${a.id}` },
    h('div', { class: 'card-top' }, h('small', {}, `${new Date(a.start_time).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' })} · ${sportName(a)}`),
      h('span', { class: 'badges' }, h('em', { class: 'badge sync-sent' }, 'Absolviert'), a.has_rr ? h('em', { class: 'badge' }, 'HRV') : null)),
    h('strong', {}, a.name),
    h('span', { class: 'card-meta' }, [duration(a.duration_s), a.distance_m ? `${km(a.distance_m)} km` : null, a.avg_hr ? `Ø ${num(a.avg_hr, 0)} bpm` : null, a.avg_power ? `Ø ${num(a.avg_power, 0)} W` : null].filter(Boolean).join(' · ')));
  const colorOf = (w) => plans.find((p) => p.id === w.plan_id)?.color || 0;

  const badge = (w) => [
    h('em', { class: `badge kind-${w.kind}` }, KIND_LABEL[w.kind]),
    w.link_group ? h('em', { class: 'badge brick' }, `Koppel ${w.link_order}/2`) : null,
    w.sync_status !== 'none' ? h('em', { class: `badge sync-${w.sync_status}` }, SYNC_LABEL[w.sync_status]) : null,
    w.read_only ? h('em', { class: 'badge ro' }, 'Schreibgeschützt') : null,
  ];

  const chip = (w) => h('button', {
    type: 'button', class: `chip kind-${w.kind}${w.link_group ? ' is-brick' : ''} plan-${colorOf(w)}`,
    'aria-label': `${w.title}, ${w.sport}${w.start_time ? `, ${w.start_time} Uhr` : ''}${w.link_group ? `, Koppeleinheit Teil ${w.link_order} von 2` : ''}`,
    onclick: () => open(w.id),
  }, w.link_group ? h('b', { class: 'brick-mark' }, `K${w.link_order}`) : null, w.start_time ? h('small', {}, w.start_time) : null, h('span', { class: 'chip-title' }, w.title));

  const card = (w) => h('button', { type: 'button', class: `card kind-${w.kind} plan-${colorOf(w)}`, onclick: () => open(w.id) },
    h('div', { class: 'card-top' }, h('small', {}, [w.start_time, w.sport].filter(Boolean).join(' · ')), h('span', { class: 'badges' }, badge(w))),
    h('strong', {}, w.title),
    h('span', { class: 'card-meta' }, [w.duration_min ? `${w.duration_min} Min.` : null, w.tss ? `${w.tss} TSS` : null].filter(Boolean).join(' · ') || 'Keine Struktur'));

  const phasesOn = (day) => plans.filter((p) => p.status === 'active').flatMap((p) => p.phases.filter((ph) => ph.start_date <= day && day <= ph.end_date).map((ph) => ({ p, ph })));

  // ----- Werkzeugleiste -----
  const step = (dir) => {
    if (state.view === 'week') state.anchor = addDays(state.anchor, dir * 7);
    else { const a = state.anchor; state.anchor = new Date(a.getFullYear(), a.getMonth() + dir, 1, 12); }
    refresh();
  };
  const label = state.view === 'week'
    ? `${parse(iso(mondayOf(state.anchor))).toLocaleDateString('de-DE', { day: 'numeric', month: 'short' })} – ${addDays(mondayOf(state.anchor), 6).toLocaleDateString('de-DE', { day: 'numeric', month: 'short', year: 'numeric' })}`
    : monthLabel(state.anchor);
  const toolbar = h('div', { class: 'toolbar' },
    h('div', { class: 'nav-group' },
      h('button', { type: 'button', class: 'secondary', 'aria-label': 'Zurück', onclick: () => step(-1) }, '‹'),
      h('button', { type: 'button', class: 'secondary', onclick: () => { state.anchor = new Date(); state.anchor.setHours(12); state.selected = iso(new Date()); refresh(); } }, 'Heute'),
      h('button', { type: 'button', class: 'secondary', 'aria-label': 'Weiter', onclick: () => step(1) }, '›')),
    h('h2', { class: 'range-label' }, label),
    h('div', { class: 'segmented', role: 'tablist' }, [['month', 'Monat'], ['week', 'Woche'], ['list', 'Liste']].map(([v, l]) =>
      h('button', { type: 'button', role: 'tab', 'aria-selected': state.view === v, class: state.view === v ? 'active' : '', onclick: () => { state.view = v; refresh(); } }, l))),
    h('button', { type: 'button', class: 'primary', onclick: () => open(null, state.selected) }, '+ Einheit'));

  // ----- Ansichten -----
  let body;
  if (state.view === 'month') {
    const first = new Date(state.anchor.getFullYear(), state.anchor.getMonth(), 1, 12);
    const start = mondayOf(first);
    const cells = [];
    for (let i = 0; i < 42; i++) {
      const day = addDays(start, i), key = iso(day), items = byDate.get(key) || [], done = actsOn(key), shown = items.length + done.length;
      if (i >= 35 && day.getMonth() !== first.getMonth()) break;
      cells.push(h('div', { class: `day${day.getMonth() !== first.getMonth() ? ' other' : ''}${key === iso(new Date()) ? ' today' : ''}${key === state.selected ? ' selected' : ''}` },
        h('button', { type: 'button', class: 'day-num', 'aria-label': longDay(key), onclick: () => { state.selected = key; refresh(); } }, day.getDate()),
        phasesOn(key).slice(0, 2).map(({ p, ph }) => h('span', { class: `phase plan-${p.color}`, title: `${p.name} · ${ph.name}` }, ph.name)),
        [...items.map(chip), ...done.map(actChip)].slice(0, 3),
        shown > 3 ? h('button', { type: 'button', class: 'more', onclick: () => { state.selected = key; refresh(); } }, `+${shown - 3} weitere`) : null));
    }
    const sel = byDate.get(state.selected) || [], selDone = actsOn(state.selected);
    body = h('div', {},
      h('div', { class: 'month' }, DAY_NAMES.map((n) => h('div', { class: 'dow' }, n)), cells),
      h('section', { class: 'day-list', 'aria-label': `Einheiten am ${longDay(state.selected)}` },
        h('h3', {}, longDay(state.selected)),
        sel.length || selDone.length ? [sel.map(card), selDone.map(actCard)] : h('p', { class: 'empty' }, 'Keine Einheiten an diesem Tag.'),
        h('button', { type: 'button', class: 'secondary', onclick: () => open(null, state.selected) }, '+ Einheit an diesem Tag')));
  } else if (state.view === 'week') {
    const monday = mondayOf(state.anchor);
    body = h('div', { class: 'week' }, Array.from({ length: 7 }, (_, i) => {
      const day = addDays(monday, i), key = iso(day), items = byDate.get(key) || [], done = actsOn(key);
      return h('section', { class: `week-day${key === iso(new Date()) ? ' today' : ''}` },
        h('h3', {}, `${DAY_NAMES[i]} ${day.getDate()}.${day.getMonth() + 1}.`),
        phasesOn(key).map(({ p, ph }) => h('span', { class: `phase plan-${p.color}` }, `${p.name} · ${ph.name}`)),
        items.length || done.length ? [items.map(card), done.map(actCard)] : h('p', { class: 'empty' }, '—'),
        h('button', { type: 'button', class: 'link', onclick: () => open(null, key) }, '+ Einheit'));
    }));
  } else {
    const a = state.anchor, from = iso(new Date(a.getFullYear(), a.getMonth(), 1)), to = iso(new Date(a.getFullYear(), a.getMonth() + 1, 0));
    const days = [...new Set([...byDate.keys(), ...actsByDate.keys()])].filter((k) => k >= from && k <= to).sort();
    body = h('div', { class: 'list' },
      days.length ? days.map((k) => h('section', { class: 'list-day' }, h('h3', {}, longDay(k)), (byDate.get(k) || []).map(card), actsOn(k).map(actCard))) : h('p', { class: 'empty' }, 'In diesem Monat gibt es keine Einheiten.'));
  }
  const undatedBox = undated.length ? h('section', { class: 'undated' }, h('h3', {}, 'Ohne Datum'), undated.map(card)) : null;
  render(root, toolbar, body, undatedBox);
}
