// core.js: tiny helpers shared by every page — DOM builder, API, icons, markdown, overlays, formatting.

// Element.append, but it skips null/false/undefined (so `cond ? el : null` works anywhere) and flattens arrays.
const nativeAppend = Element.prototype.append;
Element.prototype.append = function (...kids) {
  return nativeAppend.apply(this, kids.flat(Infinity).filter((k) => k !== null && k !== undefined && k !== false));
};

export const TOKEN = document.querySelector('meta[name="oa-token"]')?.content || "";

// ---------------------------------------------------------------- DOM
// h("div", {class: "x", onclick: fn}, child, "text", [more]) — text is always escaped.
export function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  if (attrs && (typeof attrs !== "object" || attrs instanceof Node || Array.isArray(attrs))) { kids.unshift(attrs); attrs = null; }
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k === "html") el.innerHTML = v;              // only ever our own escaped markdown or icons
    else if (k in el && k !== "list" && typeof v !== "string") el[k] = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  add(el, kids);
  return el;
}
function add(el, kids) {
  for (const k of kids.flat(Infinity)) {
    if (k === null || k === undefined || k === false) continue;
    el.append(k instanceof Node ? k : document.createTextNode(String(k)));
  }
}
export const clear = (el) => { while (el.firstChild) el.firstChild.remove(); return el; };
export const $ = (sel, root = document) => root.querySelector(sel);

// ---------------------------------------------------------------- icons (24px line icons)
const P = {
  home: '<path d="M3.5 10.5 12 4l8.5 6.5V19a1.5 1.5 0 0 1-1.5 1.5h-4v-6h-6v6H5A1.5 1.5 0 0 1 3.5 19z"/>',
  bot: '<rect x="4" y="8" width="16" height="11" rx="3"/><path d="M12 8V5M9.5 12.5v1M14.5 12.5v1M9.5 16.5h5M2.5 13v2M21.5 13v2"/>',
  activity: '<path d="M3 12h3.5l2.5-7 5 14 2.5-7H21"/>',
  book: '<path d="M5 4.5A1.5 1.5 0 0 1 6.5 3H19v15H6.5A1.5 1.5 0 0 0 5 19.5zM5 19.5A1.5 1.5 0 0 0 6.5 21H19v-3"/><path d="M9 7h6"/>',
  flask: '<path d="M9.5 3h5M10.5 3v5.5L5 18.5A1.7 1.7 0 0 0 6.5 21h11a1.7 1.7 0 0 0 1.5-2.5l-5.5-10V3M7.5 15h9"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M12 2.5v2.2M12 19.3v2.2M4.6 4.6l1.6 1.6M17.8 17.8l1.6 1.6M2.5 12h2.2M19.3 12h2.2M4.6 19.4l1.6-1.6M17.8 6.2l1.6-1.6"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/>',
  play: '<path d="M8 5.5v13l10.5-6.5z"/>',
  stop: '<rect x="6.5" y="6.5" width="11" height="11" rx="2"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  alert: '<path d="M12 4 2.5 20h19z"/><path d="M12 10v4.5M12 17.5v.5"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8v.5"/>',
  chev: '<path d="m9.5 6 6 6-6 6"/>',
  down: '<path d="m6 9.5 6 6 6-6"/>',
  back: '<path d="M14.5 6 8.5 12l6 6"/>',
  file: '<path d="M14 3H7a1.5 1.5 0 0 0-1.5 1.5v15A1.5 1.5 0 0 0 7 21h10a1.5 1.5 0 0 0 1.5-1.5V7.5z"/><path d="M14 3v4.5h4.5"/>',
  folder: '<path d="M3.5 7A1.5 1.5 0 0 1 5 5.5h4l2 2.5h8a1.5 1.5 0 0 1 1.5 1.5V17A1.5 1.5 0 0 1 19 18.5H5A1.5 1.5 0 0 1 3.5 17z"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.6 2.6 3.8 5.6 3.8 9s-1.2 6.4-3.8 9c-2.6-2.6-3.8-5.6-3.8-9S9.4 5.6 12 3z"/>',
  mail: '<rect x="3" y="5.5" width="18" height="13" rx="2"/><path d="m3.5 7 8.5 6 8.5-6"/>',
  brain: '<path d="M9 4.5a3 3 0 0 0-3 3 3 3 0 0 0-2 5.2A3 3 0 0 0 7 18a2.5 2.5 0 0 0 5 .5V5.5A2.5 2.5 0 0 0 9 4.5zM15 4.5a3 3 0 0 1 3 3 3 3 0 0 1 2 5.2A3 3 0 0 1 17 18a2.5 2.5 0 0 1-5 .5"/>',
  chat: '<path d="M4.5 5.5h15v10h-9l-4.5 4v-4h-1.5z"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  send: '<path d="M12 19V5M6 11l6-6 6 6"/>',
  sparkle: '<path d="M12 3.5 13.8 10 20 12l-6.2 2-1.8 6.5-1.8-6.5L4 12l6.2-2zM18.5 3v3M17 4.5h3"/>',
  trash: '<path d="M4.5 7h15M9.5 7V4.5h5V7M6.5 7l1 13h9l1-13"/>',
  download: '<path d="M12 4v11M7 10.5l5 5 5-5M5 20h14"/>',
  upload: '<path d="M12 16V5M7 9.5l5-5 5 5M5 20h14"/>',
  refresh: '<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3M19.5 4.5v4h-4"/>',
  eye: '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.8"/>',
  code: '<path d="m8.5 7-5 5 5 5M15.5 7l5 5-5 5"/>',
  external: '<path d="M14 4.5h5.5V10M19.5 4.5 11 13M18 14v4.5A1.5 1.5 0 0 1 16.5 20h-11A1.5 1.5 0 0 1 4 18.5v-11A1.5 1.5 0 0 1 5.5 6H10"/>',
  shield: '<path d="M12 3.5 5 6v5.5c0 4.4 3 7.6 7 9 4-1.4 7-4.6 7-9V6z"/>',
  wrench: '<path d="M14.5 6.5a4 4 0 0 0 4.9 4.9L21 13l-8 8-1.6-1.6a4 4 0 0 0-4.9-4.9L3 11l8-8z" transform="scale(.9) translate(1.3 1.3)"/>',
  list: '<path d="M8.5 6.5h11M8.5 12h11M8.5 17.5h11M4.5 6.5v.01M4.5 12v.01M4.5 17.5v.01"/>',
  gauge: '<path d="M4 17a8 8 0 1 1 16 0"/><path d="m12 17 4-5.5"/>',
  layers: '<path d="m12 4 8.5 4.5L12 13 3.5 8.5z"/><path d="m3.5 12.5 8.5 4.5 8.5-4.5M3.5 16.5 12 21l8.5-4.5"/>',
  user: '<circle cx="12" cy="8.5" r="3.5"/><path d="M5 20a7 7 0 0 1 14 0"/>',
  calendar: '<rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 10h16M8.5 3v4M15.5 3v4"/>',
  cpu: '<rect x="6" y="6" width="12" height="12" rx="2"/><rect x="9.5" y="9.5" width="5" height="5" rx="1"/><path d="M9.5 3v3M14.5 3v3M9.5 18v3M14.5 18v3M3 9.5h3M3 14.5h3M18 9.5h3M18 14.5h3"/>',
  undo: '<path d="M9 14 4.5 9.5 9 5"/><path d="M4.5 9.5H14a5.5 5.5 0 0 1 0 11h-3"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
  flag: '<path d="M5.5 21V4.5M5.5 4.5h11l-2 4 2 4h-11"/>',
};
export function icon(name, cls = "") {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("viewBox", "0 0 24 24");
  s.setAttribute("class", `i ${cls}`);
  s.setAttribute("aria-hidden", "true");
  s.innerHTML = P[name] || P.info;
  return s;
}

// ---------------------------------------------------------------- API
export async function api(method, path, body) {
  const opts = { method, headers: { "X-Offline-Agent": TOKEN } };
  if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
  let res;
  try { res = await fetch(path, opts); } catch (e) { throw new Error("The Studio server isn't reachable. Is it still running?"); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `${res.status} ${res.statusText}`);
  return data;
}
export const get = (p) => api("GET", p);
export const post = (p, b = {}) => api("POST", p, b);

// ---------------------------------------------------------------- overlays
export function toast(text, kind = "") {
  const t = h("div", { class: `toast ${kind}` }, kind === "bad" ? icon("alert") : icon("check"), text);
  $("#toasts").append(t);
  setTimeout(() => t.remove(), kind === "bad" ? 6000 : 3200);
}
export function fail(e) { toast(e.message || String(e), "bad"); }

export function modal({ title, body, actions = [], wide = false, onclose }) {
  const back = h("div", { class: "modal-back" });
  const close = () => { back.remove(); document.removeEventListener("keydown", esc); onclose && onclose(); };
  const esc = (ev) => { if (ev.key === "Escape") close(); };
  document.addEventListener("keydown", esc);
  back.addEventListener("mousedown", (ev) => { if (ev.target === back) close(); });
  const foot = h("div", { class: "modal-foot" }, actions.map((a) =>
    h("button", { class: `btn ${a.kind || ""}`, onclick: () => a.run ? a.run(close) : close(), disabled: a.disabled }, a.label)));
  back.append(h("div", { class: `modal ${wide ? "wide" : ""}`, role: "dialog" },
    h("div", { class: "modal-head" }, h("h2", { class: "grow" }, title),
      h("button", { class: "btn ghost sm icon", onclick: close, "aria-label": "Close" }, icon("x"))),
    h("div", { class: "modal-body" }, body), actions.length ? foot : null));
  document.body.append(back);
  setTimeout(() => back.querySelector("textarea, input")?.focus(), 30);
  return { close, foot, back };
}
export function confirmBox(title, text, label = "Confirm", danger = true) {
  return new Promise((resolve) => {
    modal({ title, body: h("p", { class: "muted", style: { margin: 0 } }, text), onclose: () => resolve(false),
      actions: [{ label: "Cancel", kind: "ghost", run: (c) => { resolve(false); c(); } },
                { label, kind: danger ? "danger solid" : "primary", run: (c) => { resolve(true); c(); } }] });
  });
}

// ---------------------------------------------------------------- controls
export function seg(options, value, onchange, cls = "") {
  const wrap = h("div", { class: `seg ${cls}`, role: "radiogroup" });
  const draw = (v) => {
    clear(wrap);
    for (const [val, label] of options) {
      wrap.append(h("button", { type: "button", class: `${v === val ? "on" : ""} m-${val}`, role: "radio",
        "aria-checked": String(v === val), onclick: () => { draw(val); onchange(val); } }, label));
    }
  };
  draw(value);
  return wrap;
}
export function toggle(label, checked, onchange, sub = "") {
  const input = h("input", { type: "checkbox", checked, onchange: () => onchange(input.checked) });
  return h("label", { class: "switch" }, input, h("span", { class: "track" }),
    h("span", { class: "txt" }, h("span", {}, label), sub ? h("small", {}, sub) : null));
}
export function field(label, control, hint) {
  return h("div", { class: "field" }, label ? h("label", {}, label) : null, control, hint ? h("div", { class: "hint" }, hint) : null);
}
export function input(value, oninput, attrs = {}) {
  return h("input", { class: "input", value: value ?? "", oninput: (e) => oninput(e.target.value), ...attrs });
}
export function textarea(value, oninput, attrs = {}) {
  const t = h("textarea", { class: "textarea", oninput: (e) => { oninput(e.target.value); grow(t); }, ...attrs });
  t.value = value ?? "";
  requestAnimationFrame(() => grow(t));
  return t;
}
export function grow(t, max = 520) { t.style.height = "auto"; t.style.height = Math.min(max, t.scrollHeight + 2) + "px"; }
export function select(options, value, onchange, attrs = {}) {
  const s = h("select", { class: "select", onchange: (e) => onchange(e.target.value), ...attrs },
    options.map(([v, l]) => h("option", { value: v, selected: v === value }, l)));
  return s;
}
// Tag input: a list of strings as removable chips plus a text box (Enter or comma adds).
export function tags(list, onchange, placeholder = "Add…") {
  const items = [...(list || [])];
  const wrap = h("div", { class: "tags" });
  const box = h("input", { placeholder });
  const commit = () => {
    const v = box.value.trim().replace(/,$/, "");
    if (v && !items.includes(v)) { items.push(v); onchange([...items]); }
    box.value = ""; draw();
  };
  box.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === ",") { e.preventDefault(); commit(); }
    else if (e.key === "Backspace" && !box.value && items.length) { items.pop(); onchange([...items]); draw(); }
  });
  box.addEventListener("blur", commit);
  function draw() {
    clear(wrap);
    items.forEach((t, i) => wrap.append(h("span", { class: "chip" }, t,
      h("span", { class: "x", onclick: () => { items.splice(i, 1); onchange([...items]); draw(); } }, icon("x")))));
    wrap.append(box);
  }
  draw();
  wrap.addEventListener("click", () => box.focus());
  return wrap;
}

// ---------------------------------------------------------------- formatting
export function ago(iso) {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  if (s < 86400 * 7) return `${Math.round(s / 86400)} d ago`;
  return new Date(iso).toLocaleDateString();
}
export function dur(sec) {
  sec = Math.round(sec || 0);
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${sec % 60}s`;
  return `${Math.floor(sec / 3600)}h ${Math.floor((sec % 3600) / 60)}m`;
}
export const num = (n) => (n || 0).toLocaleString();
export function bytes(n) { return n > 1e9 ? (n / 1e9).toFixed(1) + " GB" : n > 1e6 ? (n / 1e6).toFixed(1) + " MB" : n > 1e3 ? Math.round(n / 1e3) + " KB" : n + " B"; }
export function initials(name) { return (name || "?").split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase(); }

export const STATUS = {
  running: ["Running", "info", true], verifying: ["Checking", "violet", true],
  waiting_approval: ["Needs your OK", "warn", true], waiting_input: ["Needs an answer", "warn", true],
  completed: ["Done", "ok"], failed: ["Failed", "bad"], stopped: ["Stopped", ""], interrupted: ["Interrupted", ""],
};
export function statusPill(status) {
  const [label, kind, live] = STATUS[status] || [status, ""];
  return h("span", { class: `pill ${kind}` }, h("span", { class: `dot ${live ? "pulse" : ""}` }), label);
}
export function statusDot(status) {
  const [, kind, live] = STATUS[status] || ["", ""];
  return h("span", { class: `dot ${kind} ${live ? "pulse" : ""}` });
}

// ---------------------------------------------------------------- markdown (safe: escapes everything first)
const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
function inline(s) {
  return s
    .replace(/`([^`]+)`/g, (_, c) => `<code>${c}</code>`)
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[\s(])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
}
export function md(text) {
  const lines = esc(text || "").split("\n");
  const out = [];
  let i = 0;
  const para = [];
  const flush = () => { if (para.length) { out.push(`<p>${inline(para.join("<br>"))}</p>`); para.length = 0; } };
  while (i < lines.length) {
    const l = lines[i];
    if (/^```/.test(l)) {
      flush();
      const code = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i])) code.push(lines[i++]);
      out.push(`<pre><code>${code.join("\n")}</code></pre>`);
      i++; continue;
    }
    const hm = l.match(/^(#{1,4})\s+(.*)/);
    if (hm) { flush(); out.push(`<h${hm[1].length}>${inline(hm[2])}</h${hm[1].length}>`); i++; continue; }
    if (/^\s*(---|\*\*\*)\s*$/.test(l)) { flush(); out.push("<hr>"); i++; continue; }
    if (/^\s*[-*•]\s+/.test(l) || /^\s*\d+[.)]\s+/.test(l)) {
      flush();
      const ordered = /^\s*\d+[.)]\s+/.test(l);
      const items = [];
      while (i < lines.length && (/^\s*[-*•]\s+/.test(lines[i]) || /^\s*\d+[.)]\s+/.test(lines[i]) || /^\s{2,}\S/.test(lines[i]))) {
        const t = lines[i].replace(/^\s*([-*•]|\d+[.)])\s+/, "");
        if (/^\s{2,}\S/.test(lines[i]) && !/^\s*([-*•]|\d+[.)])\s+/.test(lines[i]) && items.length) items[items.length - 1] += "<br>" + inline(t.trim());
        else items.push(inline(t.replace(/^\[( |x|-|!)\]\s*/, (m, c) => (c === "x" ? "✓ " : c === "!" ? "✗ " : ""))));
        i++;
      }
      out.push(`<${ordered ? "ol" : "ul"}>${items.map((x) => `<li>${x}</li>`).join("")}</${ordered ? "ol" : "ul"}>`);
      continue;
    }
    if (/^\|.*\|\s*$/.test(l) && i + 1 < lines.length && /^\|[\s:|-]+\|\s*$/.test(lines[i + 1])) {
      flush();
      const row = (r) => r.trim().replace(/^\||\|$/g, "").split("|").map((c) => inline(c.trim()));
      const head = row(l);
      i += 2;
      const body = [];
      while (i < lines.length && /^\|.*\|\s*$/.test(lines[i])) body.push(row(lines[i++]));
      out.push(`<table><thead><tr>${head.map((c) => `<th>${c}</th>`).join("")}</tr></thead><tbody>${body.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody></table>`);
      continue;
    }
    if (/^&gt;\s?/.test(l)) { flush(); out.push(`<blockquote>${inline(l.replace(/^&gt;\s?/, ""))}</blockquote>`); i++; continue; }
    if (!l.trim()) { flush(); i++; continue; }
    para.push(l); i++;
  }
  flush();
  return out.join("");
}
export const mdEl = (text, cls = "") => h("div", { class: `md ${cls}`, html: md(text) });

// ---------------------------------------------------------------- shared state
export const store = {
  status: { ollama: true, models: [], running: 0, waiting: 0 },
  meta: null,
  draft: null,   // an agent config handed from one page to another (e.g. after "Describe it")
};
export async function loadMeta() {
  if (!store.meta) store.meta = await get("/api/meta");
  return store.meta;
}
export const CAP_ICON = { files: "folder", internet: "globe", email: "mail", memory: "brain", interaction: "chat" };
