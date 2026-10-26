// Anzeigeformate (deutsch). Alle Funktionen sind rein und liefern Text.
const nf = (digits) => new Intl.NumberFormat('de-DE', { minimumFractionDigits: digits, maximumFractionDigits: digits });
export const num = (v, digits = 1) => (v === null || v === undefined || Number.isNaN(v) ? '–' : nf(digits).format(v));
export function duration(seconds) {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return '–';
  const s = Math.round(seconds), hh = Math.floor(s / 3600), mm = Math.floor((s % 3600) / 60), ss = s % 60;
  return hh ? `${hh}:${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}` : `${mm}:${String(ss).padStart(2, '0')}`;
}
export const pace = (secPerKm) => (secPerKm === null || secPerKm === undefined ? '–' : `${Math.floor(secPerKm / 60)}:${String(Math.round(secPerKm % 60)).padStart(2, '0')}`.replace(/:60$/, ':00'));
export const paceFromSpeed = (ms) => (ms && ms > 0.3 ? pace(1000 / ms) : '–');
export const kmh = (ms) => (ms === null || ms === undefined ? '–' : num(ms * 3.6, 1));
export const km = (m) => (m === null || m === undefined ? '–' : num(m / 1000, 2));
export const dateTime = (iso) => (iso ? new Date(iso).toLocaleString('de-DE', { dateStyle: 'medium', timeStyle: 'short' }) : '–');
export const SPORT = { running: 'Laufen', cycling: 'Radfahren', swimming: 'Schwimmen', walking: 'Gehen', training: 'Training', hiking: 'Wandern' };
