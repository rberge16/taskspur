import { del, get, post, put } from './api.js';
import { h, toast } from './dom.js';

const STATUS = { active: 'Aktiv', inactive: 'Inaktiv', draft: 'Entwurf' };

export async function renderPlans(root) {
  let plans;
  try { plans = await get('/api/plans'); } catch (e) { root.replaceChildren(h('p', { class: 'form-message error', role: 'alert' }, e.message)); return; }
  const refresh = () => renderPlans(root);
  const run = async (fn, ok) => { try { await fn(); if (ok) toast(ok, 'success'); await refresh(); } catch (e) { toast(e.message, 'error', 8000); } };

  const newForm = h('form', { class: 'plan-form', onsubmit: (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    run(() => post('/api/plans', { name: String(f.get('name')).trim(), goal_date: f.get('goal') || null, status: f.get('status'), color: Number(f.get('color')) }), 'Plan angelegt.');
  } },
    h('h3', {}, 'Neuer Trainingsplan'),
    h('div', { class: 'row' },
      h('label', { class: 'field' }, h('span', {}, 'Name'), h('input', { name: 'name', required: true, maxlength: 120, placeholder: 'z. B. Marathon-Vorbereitung' })),
      h('label', { class: 'field' }, h('span', {}, 'Zieldatum'), h('input', { name: 'goal', type: 'date' }))),
    h('div', { class: 'row' },
      h('label', { class: 'field' }, h('span', {}, 'Status'), h('select', { name: 'status' }, Object.entries(STATUS).map(([v, l]) => h('option', { value: v }, l)))),
      h('label', { class: 'field' }, h('span', {}, 'Farbe'), h('select', { name: 'color' }, [1, 2, 3, 4, 5, 6].map((c) => h('option', { value: c }, `Farbe ${c}`))))),
    h('button', { type: 'submit', class: 'primary' }, 'Plan anlegen'));

  const phaseRow = (plan, ph) => {
    const form = h('form', { class: 'phase-row', onsubmit: (e) => {
      e.preventDefault(); const f = new FormData(e.target);
      run(() => put(`/api/phases/${ph.id}`, { name: String(f.get('name')).trim(), start_date: f.get('start'), end_date: f.get('end'), description: String(f.get('desc')) }), 'Phase gespeichert.');
    } },
      h('label', { class: 'field' }, h('span', {}, 'Phase'), h('input', { name: 'name', value: ph.name, required: true, maxlength: 120 })),
      h('label', { class: 'field' }, h('span', {}, 'Anfang'), h('input', { name: 'start', type: 'date', value: ph.start_date, required: true })),
      h('label', { class: 'field' }, h('span', {}, 'Ende'), h('input', { name: 'end', type: 'date', value: ph.end_date, required: true })),
      h('label', { class: 'field wide' }, h('span', {}, 'Beschreibung'), h('input', { name: 'desc', value: ph.description, maxlength: 2000 })),
      h('div', { class: 'actions' },
        h('button', { type: 'submit', class: 'secondary' }, 'Speichern'),
        h('button', { type: 'button', class: 'danger', onclick: () => { if (window.confirm(`Phase „${ph.name}“ löschen? Einheiten bleiben als freie Einheiten erhalten.`)) run(() => del(`/api/phases/${ph.id}`), 'Phase gelöscht.'); } }, 'Löschen')));
    return form;
  };

  const planCard = (plan) => h('article', { class: `plan plan-${plan.color}` },
    h('div', { class: 'plan-head' },
      h('h3', {}, plan.name), h('span', { class: `pill ${plan.status}` }, STATUS[plan.status]),
      plan.goal_date ? h('small', {}, `Ziel: ${plan.goal_date.split('-').reverse().join('.')}`) : null),
    h('div', { class: 'actions' },
      h('select', { 'aria-label': `Status von ${plan.name}`, onchange: (e) => run(() => put(`/api/plans/${plan.id}`, { name: plan.name, goal_date: plan.goal_date, status: e.target.value, color: plan.color }), 'Status geändert.') },
        Object.entries(STATUS).map(([v, l]) => h('option', { value: v, selected: plan.status === v }, l))),
      h('button', { type: 'button', class: 'danger', onclick: () => { if (window.confirm(`Plan „${plan.name}“ löschen? Alle Einheiten bleiben als freie Einheiten im Kalender erhalten.`)) run(() => del(`/api/plans/${plan.id}`), 'Plan gelöscht.'); } }, 'Plan löschen')),
    plan.phases.length ? plan.phases.map((ph) => phaseRow(plan, ph)) : h('p', { class: 'empty' }, 'Noch keine Phasen.'),
    h('form', { class: 'phase-add', onsubmit: (e) => {
      e.preventDefault(); const f = new FormData(e.target);
      run(() => post(`/api/plans/${plan.id}/phases`, { name: String(f.get('name')).trim(), start_date: f.get('start'), end_date: f.get('end'), description: '' }), 'Phase hinzugefügt.');
    } },
      h('label', { class: 'field' }, h('span', {}, 'Neue Phase'), h('input', { name: 'name', required: true, maxlength: 120, placeholder: 'z. B. Grundlage' })),
      h('label', { class: 'field' }, h('span', {}, 'Anfang'), h('input', { name: 'start', type: 'date', required: true })),
      h('label', { class: 'field' }, h('span', {}, 'Ende'), h('input', { name: 'end', type: 'date', required: true })),
      h('button', { type: 'submit', class: 'secondary' }, '+ Phase')));

  root.replaceChildren(h('h2', {}, 'Trainingspläne'), plans.length ? plans.map(planCard) : h('p', { class: 'empty' }, 'Noch kein Plan. Lege unten deinen ersten Plan an.'), newForm);
}
