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

/**
 * lineChart(container, { title, x: number[], series: [{label, values, unit?, color?, fill?}], xLabel?, xFormat?, height?, bands? })
 * Gibt { destroy, update } zurück. Passt sich per ResizeObserver der Breite an (Handy → PC).
 * Dunkles/helles Farbschema folgt den CSS-Variablen; Farben sind nie das einzige Unterscheidungsmerkmal (Legende + Tooltip-Werte).
 */
export function lineChart(container, { title, x, series, xLabel = '', xFormat = (v) => String(v), height = 240, bands = [] }) {
  ensureCss();
  const text = cssVar('--text', '#14203a'), muted = cssVar('--muted', '#5b6784'), grid = cssVar('--line', '#d9dfeb');
  const rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
  const axis = (extra) => ({ stroke: muted, grid: { stroke: grid, width: 1 }, ticks: { stroke: grid }, font: `${0.75 * rem}px system-ui, sans-serif`, ...extra });

  const wrap = h('figure', { class: 'chart', role: 'img', 'aria-label': `${title}: ${series.map((s) => s.label).join(', ')}` },
    h('figcaption', {}, title));
  const holder = h('div', { class: 'chart-holder' });
  wrap.append(holder);
  container.append(wrap);

  const opts = (width) => ({
    width, height,
    legend: { show: true, live: true },
    cursor: { drag: { x: true, y: false } },       // Ziehen zum Zoomen, Doppelklick setzt zurück
    scales: { x: { time: false } },
    axes: [axis({ label: xLabel, values: (u, ticks) => ticks.map(xFormat) }), axis({})],
    series: [{ label: xLabel || 'x', value: (u, v) => (v == null ? '–' : xFormat(v)) },
      ...series.map((s, i) => ({
        label: s.label + (s.unit ? ` (${s.unit})` : ''),
        stroke: s.color || cssVar(PALETTE[i % PALETTE.length], '#2563eb'),
        width: 2, points: { show: false }, spanGaps: false,
        fill: s.fill ? (s.color || cssVar(PALETTE[i % PALETTE.length], '#2563eb')) + '33' : undefined,
        value: (u, v) => (v == null ? '–' : Number(v.toFixed(2)) + (s.unit ? ` ${s.unit}` : '')),
      }))],
    bands,
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
