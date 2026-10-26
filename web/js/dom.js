// Kleiner DOM-Baukasten. Nutzertext landet ausschließlich als Textknoten (textContent) – nie als HTML.
export function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') el.className = value;
    else if (key === 'dataset') Object.assign(el.dataset, value);
    else if (key.startsWith('on') && typeof value === 'function') el.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === 'value') el.value = value;
    else if (['checked', 'disabled', 'hidden', 'selected', 'required', 'open'].includes(key)) el[key] = Boolean(value);
    else el.setAttribute(key, value === true ? '' : String(value));
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

export const clear = (el) => el.replaceChildren();

let toastTimer = null;
export function toast(message, kind = 'info', ms = 5000) {
  const el = document.getElementById('toast');
  el.textContent = message;
  el.className = `show ${kind}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.className = ''; }, ms);
}

/** Ersetzt den Inhalt von `el`. Arrays werden abgeflacht, null/false übersprungen (replaceChildren würde Arrays als Text ausgeben). */
export function render(el, ...children) {
  el.replaceChildren(...children.flat(Infinity).filter((c) => c !== null && c !== undefined && c !== false).map((c) => (c instanceof Node ? c : document.createTextNode(String(c)))));
}
