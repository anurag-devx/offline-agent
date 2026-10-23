// app.js: the shell (left rail), the router, and the Home page.
import { $, ago, clear, fail, get, h, icon, post, statusDot, store, grow } from "./core.js";
import { agentsPage, editorPage } from "./agents.js";
import { activityPage } from "./activity.js";
import { libraryPage } from "./library.js";
import { testsPage } from "./tests.js";
import { settingsPage } from "./settings.js";

const NAV = [
  ["home", "Home", "#/"],
  ["bot", "Agents", "#/agents"],
  ["activity", "Activity", "#/activity"],
  ["book", "Library", "#/library"],
  ["flask", "Tests", "#/tests"],
];

// ---------------------------------------------------------------- rail
function drawRail() {
  const rail = clear($("#rail"));
  const here = location.hash || "#/";
  const active = (href) => (href === "#/" ? here === "#/" || here === "" : here.startsWith(href));
  rail.append(h("div", { class: "brand" }, h("span", { class: "logo" }, icon("bot")), "offline-agent"));
  for (const [ic, label, href] of NAV) {
    const badge = label === "Activity" && store.status.waiting ? h("span", { class: "badge", title: "Waiting for you" }, store.status.waiting) : null;
    rail.append(h("a", { class: `nav-item ${active(href) ? "active" : ""}`, href }, icon(ic), h("span", { class: "lbl" }, label), badge));
  }
  rail.append(h("div", { class: "spacer" }));
  const s = store.status;
  const theme = document.documentElement.dataset.theme || "system";
  const dark = theme === "dark" || (theme === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  rail.append(h("div", { class: "rail-foot" },
    h("div", { class: "status-line", title: s.ollama ? s.models.join(", ") : "Open the Ollama app" },
      h("span", { class: `dot ${s.ollama ? "ok" : "bad"}` }),
      s.ollama ? `Ollama · ${s.models.length} model${s.models.length === 1 ? "" : "s"}` : "Ollama isn't running"),
    s.running ? h("div", { class: "status-line" }, h("span", { class: "dot info pulse" }), `${s.running} running`) : null,
    h("a", { class: `nav-item ${active("#/settings") ? "active" : ""}`, href: "#/settings" }, icon("gear"), h("span", { class: "lbl" }, "Settings")),
    h("button", { class: "nav-item", style: { border: 0, background: "none", font: "inherit", width: "100%" },
      onclick: () => { setTheme(dark ? "light" : "dark"); drawRail(); } },
      icon(dark ? "sun" : "moon"), h("span", { class: "lbl" }, dark ? "Light mode" : "Dark mode"))));
}
export function setTheme(t) {
  try { localStorage.setItem("oa-theme", t); } catch (e) { /* private mode */ }
  if (t === "system") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = t;
}
async function pollStatus() {
  try {
    const s = await get("/api/status");
    const changed = JSON.stringify(s) !== JSON.stringify(store.status);
    store.status = s;
    if (changed) drawRail();
  } catch (e) { /* server restarting */ }
  setTimeout(pollStatus, 4000);
}

// ---------------------------------------------------------------- router
let cleanup = null;
async function route() {
  if (cleanup) { try { cleanup(); } catch (e) { /* ignore */ } cleanup = null; }
  const parts = (location.hash.replace(/^#\/?/, "") || "").split("/").map(decodeURIComponent);
  const main = clear($("#main"));
  main.scrollTop = 0;
  drawRail();
  const [page, a, b] = parts;
  try {
    if (!page) cleanup = await homePage(main);
    else if (page === "agents" && a) cleanup = await editorPage(main, a, b);
    else if (page === "agents") cleanup = await agentsPage(main);
    else if (page === "activity") cleanup = await activityPage(main, a);
    else if (page === "library") cleanup = await libraryPage(main, a || "catalog");
    else if (page === "tests") cleanup = await testsPage(main);
    else if (page === "settings") cleanup = await settingsPage(main);
    else location.hash = "#/";
  } catch (e) {
    main.append(h("div", { class: "page" }, h("div", { class: "banner bad" }, icon("alert"), e.message)));
  }
}
window.addEventListener("hashchange", route);

// ---------------------------------------------------------------- Home
async function homePage(main) {
  const page = h("div", { class: "page" });
  main.append(page);
  const [agents, runs] = await Promise.all([get("/api/agents"), get("/api/runs?limit=6")]);
  const all = [...agents.mine, ...agents.templates].filter((a) => !a.error);
  let pick = (() => { try { return localStorage.getItem("oa-home-agent"); } catch (e) { return null; } })();
  if (!all.find((a) => a.id === pick)) pick = (all.find((a) => a.name === "General Assistant") || all[0] || {}).id;

  const ta = h("textarea", { placeholder: "Describe the task. For example: sort the PDFs in my Downloads folder", rows: 2 });
  ta.addEventListener("input", () => grow(ta, 300));
  ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); go(); } });
  const runBtn = h("button", { class: "btn primary icon round", title: "Run (Enter)", onclick: () => go() }, icon("send"));
  const pickerWrap = h("div", { class: "picker" });
  const examples = h("div", { class: "examples" });

  function current() { return all.find((a) => a.id === pick) || {}; }
  function drawPicker() {
    const a = current();
    clear(pickerWrap).append(h("button", { class: "picker-btn", onclick: openMenu },
      h("span", { class: "avatar", style: { width: "20px", height: "20px", borderRadius: "6px", fontSize: "10px" } }, (a.name || "?")[0]),
      h("span", { class: "ellipsis" }, a.name || "Choose an agent"), icon("down")));
    clear(examples);
    for (const ex of (a.examples || []).slice(0, 4)) {
      examples.append(h("button", { class: "chip click", onclick: () => { ta.value = ex; grow(ta, 300); ta.focus(); } }, ex));
    }
  }
  function openMenu(ev) {
    ev.stopPropagation();
    const menu = h("div", { class: "menu up" });
    const group = (title, list) => {
      if (!list.length) return;
      menu.append(h("div", { class: "group eyebrow" }, title));
      for (const a of list) {
        menu.append(h("div", { class: `menu-item ${a.id === pick ? "on" : ""}`, onclick: () => {
          pick = a.id; try { localStorage.setItem("oa-home-agent", pick); } catch (e) { /* ignore */ }
          menu.remove(); drawPicker(); ta.focus();
        } }, h("span", { class: "avatar", style: { width: "26px", height: "26px", fontSize: "11px" } }, (a.name || "?")[0]),
          h("div", { class: "grow" }, h("div", { style: { fontWeight: 550 } }, a.name), h("div", { class: "what clamp2" }, a.what))));
      }
    };
    group("Your agents", agents.mine.filter((a) => !a.error));
    group("Templates", agents.templates);
    pickerWrap.append(menu);
    setTimeout(() => document.addEventListener("click", () => menu.remove(), { once: true }));
  }
  async function go() {
    const task = ta.value.trim();
    if (!task || !pick) { ta.focus(); return; }
    runBtn.disabled = true;
    try {
      const { id } = await post("/api/runs", { agent: pick, task });
      location.hash = `#/activity/${id}`;
    } catch (e) { fail(e); runBtn.disabled = false; }
  }

  const s = store.status;
  page.append(h("div", { class: "hero" },
    !s.ollama ? h("div", { class: "banner bad" }, icon("alert"),
      h("div", {}, h("strong", {}, "Ollama isn't running. "), "Open the Ollama app, then try again. Agents need it to think.")) : null,
    h("h1", {}, "What should an agent do?"),
    h("p", {}, "Everything runs on this computer. Nothing you type leaves it."),
    h("div", { class: "composer" }, ta, h("div", { class: "bar" }, pickerWrap, h("span", { class: "grow" }),
      h("span", { class: "tiny faint" }, h("span", { class: "kbd" }, "Enter"), " to run"), runBtn)),
    examples,
    runs.runs.length ? h("div", { class: "recent" },
      h("div", { class: "row between", style: { padding: "0 14px 6px" } }, h("span", { class: "eyebrow" }, "Recent"),
        h("a", { href: "#/activity", class: "small" }, "All activity")),
      runs.runs.map((r) => h("div", { class: "run-line", onclick: () => (location.hash = `#/activity/${r.id}`) },
        statusDot(r.status), h("div", { class: "task ellipsis" }, r.task.replace(/^\[bench\]\s*/, "")),
        h("span", { class: "small faint ellipsis", style: { maxWidth: "180px" } }, r.agent),
        h("span", { class: "small faint", style: { width: "90px", textAlign: "right" } }, ago(r.started))))) : null));
  drawPicker();
  ta.focus();
  return null;
}

// ---------------------------------------------------------------- start
drawRail();
pollStatus();
route();
