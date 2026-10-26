// Editor für strukturierte Abschnitte: Aufwärmen, Intervallzyklus, freier Abschnitt, Ausfahren.
import { h } from './dom.js';

export const ZONES = ['Z1', 'Z2', 'Z3', 'Z4', 'Z5', 'Z6', 'Z7'];
export const STEP_LABELS = { warmup: 'Aufwärmen', cycle: 'Intervallzyklus', free: 'Freier Abschnitt', cooldown: 'Ausfahren' };

const makers = {
  warmup: () => ({ type: 'warmup', duration: { value: 10, unit: 'min' }, target: { type: 'heart_rate', zone: 'Z1' } }),
  free: () => ({ type: 'free', duration: { value: 30, unit: 'min' }, target: { type: 'heart_rate', zone: 'Z2' } }),
  cooldown: () => ({ type: 'cooldown', duration: { value: 10, unit: 'min' }, target: { type: 'open' } }),
  cycle: () => ({
    type: 'cycle', repeats: 4,
    work: { duration: { value: 4, unit: 'min' }, target: { type: 'power', zone: 'Z4' } },
    recovery: { duration: { value: 3, unit: 'min' }, target: { type: 'power', zone: 'Z1' } },
  }),
};

const num = (value) => { const n = Number(value); return Number.isFinite(n) && value !== '' ? Math.round(n) : null; };

function field(label, control) { return h('label', { class: 'field' }, h('span', {}, label), control); }

function blockFields(block, onChange, readOnly) {
  const target = block.target;
  const open = target.type === 'open';
  const unit = target.type === 'power' ? 'W' : 'bpm';
  const set = () => onChange();
  return h('div', { class: 'block-fields' },
    field('Dauer', h('input', { type: 'number', min: 1, max: 100000, value: block.duration.value, disabled: readOnly,
      onchange: (e) => { block.duration.value = Math.max(1, num(e.target.value) || 1); e.target.value = block.duration.value; set(); } })),
    field('Einheit', h('select', { disabled: readOnly, onchange: (e) => { block.duration.unit = e.target.value; set(); } },
      [['min', 'Minuten'], ['sec', 'Sekunden'], ['km', 'Kilometer']].map(([v, l]) => h('option', { value: v, selected: block.duration.unit === v }, l)))),
    field('Ziel', h('select', { disabled: readOnly, onchange: (e) => {
      const type = e.target.value;
      block.target = type === 'open' ? { type } : { type, zone: target.zone || 'Z2' };
      onChange(true);
    } }, [['open', 'Offen'], ['power', 'Leistung'], ['heart_rate', 'Herzfrequenz']].map(([v, l]) => h('option', { value: v, selected: target.type === v }, l)))),
    field('Zielzone', h('select', { disabled: readOnly || open, onchange: (e) => { target.zone = e.target.value; set(); } },
      ZONES.map((z) => h('option', { value: z, selected: target.zone === z }, z)))),
    field(`Von (${unit})`, h('input', { type: 'number', min: 1, max: 2500, value: target.min ?? '', disabled: readOnly || open, placeholder: 'optional',
      onchange: (e) => { const v = num(e.target.value); if (v === null) delete target.min; else target.min = v; set(); } })),
    field(`Bis (${unit})`, h('input', { type: 'number', min: 1, max: 2500, value: target.max ?? '', disabled: readOnly || open, placeholder: 'optional',
      onchange: (e) => { const v = num(e.target.value); if (v === null) delete target.max; else target.max = v; set(); } })),
  );
}

/** Liefert { element, refresh }. `steps` wird direkt verändert; onChange() meldet jede Änderung. */
export function stepsEditor(steps, onChange, { readOnly = false } = {}) {
  const list = h('div', { class: 'steps-list' });
  const root = h('section', { class: 'steps-editor', 'aria-label': 'Workout-Abschnitte' }, list);

  const changed = (rerender) => { if (rerender) render(); onChange(); };

  function move(index, delta) {
    const target = index + delta;
    if (target < 0 || target >= steps.length) return;
    [steps[index], steps[target]] = [steps[target], steps[index]];
    changed(true);
  }

  function card(step, index) {
    const head = h('div', { class: 'step-head' },
      h('strong', {}, `${index + 1}. ${STEP_LABELS[step.type]}`),
      readOnly ? null : h('span', { class: 'step-tools' },
        h('button', { type: 'button', class: 'icon', 'aria-label': 'Nach oben', disabled: index === 0, onclick: () => move(index, -1) }, '↑'),
        h('button', { type: 'button', class: 'icon', 'aria-label': 'Nach unten', disabled: index === steps.length - 1, onclick: () => move(index, 1) }, '↓'),
        h('button', { type: 'button', class: 'icon danger', 'aria-label': `Abschnitt ${index + 1} entfernen`, onclick: () => { steps.splice(index, 1); changed(true); } }, '×')));
    if (step.type === 'cycle') {
      return h('article', { class: 'step-card cycle' }, head,
        field('Wiederholungen', h('input', { type: 'number', min: 1, max: 99, value: step.repeats, disabled: readOnly,
          onchange: (e) => { step.repeats = Math.min(99, Math.max(1, num(e.target.value) || 1)); e.target.value = step.repeats; changed(); } })),
        h('div', { class: 'cycle-part' }, h('h4', {}, 'Arbeit'), blockFields(step.work, () => changed(), readOnly)),
        h('div', { class: 'cycle-part' }, h('h4', {}, 'Erholung'), blockFields(step.recovery, () => changed(), readOnly)));
    }
    return h('article', { class: `step-card ${step.type}` }, head, blockFields(step, (r) => changed(r), readOnly));
  }

  function render() {
    list.replaceChildren(...(steps.length
      ? steps.map(card)
      : [h('p', { class: 'empty' }, 'Noch keine Abschnitte. Füge Aufwärmen, einen Intervallzyklus, einen freien Abschnitt oder Ausfahren hinzu.')]));
  }
  render();

  if (!readOnly) {
    root.append(h('div', { class: 'step-add' }, Object.keys(makers).map((type) =>
      h('button', { type: 'button', class: 'secondary', onclick: () => { steps.push(makers[type]()); changed(true); } }, `+ ${STEP_LABELS[type]}`))));
  }
  return { element: root, refresh: render };
}
