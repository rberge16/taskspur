import { renderActivities } from './activities.js';
import { renderCalendar } from './calendar.js';
import { renderPlans } from './plans.js';
import { renderSettings } from './settings.js';

const views = { calendar: renderCalendar, activities: renderActivities, plans: renderPlans, settings: renderSettings };
const root = document.getElementById('view');
let current = null;

function show(name, param = null) {
  if (!views[name]) name = 'calendar';
  current = name;
  document.querySelectorAll('#nav button').forEach((b) => {
    const on = b.dataset.view === name;
    b.classList.toggle('active', on);
    if (on) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
  });
  const wanted = `#${name}${param ? `/${param}` : ''}`;
  if (location.hash !== wanted) history.replaceState(null, '', wanted);
  window.scrollTo(0, 0);
  return views[name](root, param);
}

function route() {
  const [name, param] = location.hash.slice(1).split('/');
  return show(name || 'calendar', param || null);
}

// Je ein Listener für Navigation und Adressleiste – beide werden genau einmal beim Start registriert.
document.getElementById('nav').addEventListener('click', (event) => {
  const button = event.target.closest('button[data-view]');
  if (button) show(button.dataset.view);
});
window.addEventListener('hashchange', route);

route();
window.__taktspur = { show, get current() { return current; } };
