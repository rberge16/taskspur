// Diagramm-Basis für Taktspur (FIT-Verlauf, HRV, DFA a1 …). uPlot lokal, Daten kommen bereits vom Server reduziert.
import uPlot from '../vendor/uplot/uPlot.esm.js';
import { h } from './dom.js';

let cssLoaded = false;
function ensureCss() {
  if (cssLoaded) return;
  cssLoaded = true;
  document.head.append(h('link', { rel: 'stylesheet', href: '/vendor/uplot/uPlot.min.css' }));
}

const cssVar = (name, fallback) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
const PALETTE = ['--p1', '--p3', '--p4', '--p2', '--p5', '--p6'];
const FALLBACK = ['#2563eb', '#c2410c', '#7c3aed', '#0f766e', '#be185d', '#4d7c0f'];

/**
 * lineChart(container, { title, x, series, xLabel?, xFormat?, height?, syncKey?, yReverse?, note? })
 * series: [{ label, values, unit?, color?, fill?, scale?: 'y' | 'y2', dash?: [4,4], points?: true, format?: (v)=>string }]
 *  - Serien mit scale 'y2' bekommen eine eigene Achse rechts (z. B. Herzfrequenz + Leistung).
 *  - points: true zeichnet nur Punkte (z. B. erkannte Artefakte), dash zeichnet Referenzlinien.
 *  - yRange: [min, max] fixiert die y-Achse (Ausreißer außerhalb werden abgeschnitten; Zoom bleibt möglich).
 *  - syncKey: Diagramme mit gleichem Schlüssel teilen Cursor und Zoom (Zeitachse).
 * Rückgabe: { plot, update, destroy }. Passt sich per ResizeObserver der Breite an (Handy → PC).
 * Farben sind nie das einzige Unterscheidungsmerkmal (Legende mit Namen und Werten unter dem Cursor).
 */
export function lineChart(container, { title, x, series, xLabel = '', xFormat = (v) => String(v), height = 240, syncKey = null, yReverse = false, yRange = null, note = '' }) {
  ensureCss();
  const muted = cssVar('--muted', '#5b6784'), grid = cssVar('--line', '#d9dfeb');
  const rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
  const font = `${0.75 * rem}px system-ui, sans-serif`;
  const axis = (extra) => ({ stroke: muted, grid: { stroke: grid, width: 1 }, ticks: { stroke: grid }, font, ...extra });
  const colorOf = (s, i) => s.color || cssVar(PALETTE[i % PALETTE.length], FALLBACK[i % FALLBACK.length]);
  const hasY2 = series.some((s) => s.scale === 'y2');

  const wrap = h('figure', { class: 'chart', role: 'img', 'aria-label': `${title}: ${series.map((s) => s.label).join(', ')}` }, h('figcaption', {}, title));
  const holder = h('div', { class: 'chart-holder' });
  wrap.append(holder);
  if (note) wrap.append(h('p', { class: 'hint chart-note' }, note));
  container.append(wrap);

  const first = series.find((s) => (s.scale || 'y') === 'y');
  const unitOf = (scale) => [...new Set(series.filter((s) => (s.scale || 'y') === scale && s.unit).map((s) => s.unit))].join(' / ');
  const opts = (width) => ({
    width, height,
    legend: { show: true, live: true },
    cursor: { drag: { x: true, y: false }, ...(syncKey ? { sync: { key: syncKey } } : {}) },
    scales: { x: { time: false }, y: { ...(yReverse ? { dir: -1, ori: 1 } : {}), ...(yRange ? { range: () => yRange } : {}) }, ...(hasY2 ? { y2: {} } : {}) },
    axes: [
      axis({ label: xLabel, values: (u, ticks) => ticks.map(xFormat), size: 0.35 * rem * 2 + 18 }),
      axis({ scale: 'y', label: unitOf('y'), labelSize: 16, size: Math.round(3.4 * rem), values: first && first.tickFormat ? (u, t) => t.map(first.tickFormat) : undefined }),
      ...(hasY2 ? [axis({ scale: 'y2', side: 1, label: unitOf('y2'), labelSize: 16, size: Math.round(3.4 * rem), grid: { show: false } })] : []),
    ],
    series: [
      { label: xLabel || 'Zeit', value: (u, v) => (v == null ? '–' : xFormat(v)) },
      ...series.map((s, i) => {
        const color = colorOf(s, i);
        return {
          label: s.label + (s.unit ? ` (${s.unit})` : ''), scale: s.scale || 'y', stroke: s.points ? undefined : color,
          width: s.points ? 0 : (s.dash ? 1.5 : 2), dash: s.dash,
          points: s.points ? { show: true, size: 6, fill: color, stroke: color } : { show: false },
          spanGaps: false, fill: s.fill ? color + '33' : undefined,
          value: (u, v) => (v == null ? '–' : (s.format ? s.format(v) : Number(v.toFixed(2))) + (s.unit && !s.format ? ` ${s.unit}` : '')),
        };
      }),
    ],
  });
  const plot = new uPlot(opts(Math.max(240, holder.clientWidth)), [x, ...series.map((s) => s.values)], holder);
  const ro = new ResizeObserver(() => plot.setSize({ width: Math.max(240, holder.clientWidth), height }));
  ro.observe(holder);
  return {
    plot,
    update(nx, nseries) { plot.setData([nx, ...nseries.map((s) => s.values)]); },
    destroy() { ro.disconnect(); plot.destroy(); wrap.remove(); },
  };
}
