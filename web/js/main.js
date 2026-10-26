import { renderCalendar } from './calendar.js';
import { renderPlans } from './plans.js';
import { renderSettings } from './settings.js';

const views = { calendar: renderCalendar, plans: renderPlans, settings: renderSettings };
const root = document.getElementById('view');
let current = null;

function show(name) {
  if (!views[name]) name = 'calendar';
  current = name;
  document.querySelectorAll('#nav button').forEach((b) => {
    const on = b.dataset.view === name;
    b.classList.toggle('active', on);
    if (on) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
  });
  history.replaceState(null, '', `#${name}`);
  return views[name](root);
}

// Ein einziger Listener für die Navigation – er wird genau einmal beim Start registriert.
document.getElementById('nav').addEventListener('click', (event) => {
  const button = event.target.closest('button[data-view]');
  if (button) show(button.dataset.view);
});

show(location.hash.slice(1) || 'calendar');
window.__taktspur = { show, get current() { return current; } };
