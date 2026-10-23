// tests.js: the Test Bench. Pick agents, models and settings; it runs each in a sandbox and checks the result in code.
import { clear, dur, fail, field, get, h, icon, input, post, toggle } from "./core.js";

const SETTINGS = [
  ["Telegram style", ["Telegram on", "Telegram off"]],
  ["Full Voice", ["Full Voice on", "Full Voice off"]],
  ["How big tasks run", ["Main agent", "Relay", "Triage"]],
];

export async function testsPage(main) {
  let data = await get("/api/bench");
  const root = h("div", {});
  main.append(h("div", { class: "page wide" },
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Tests"),
      h("p", {}, "Runs agents on fixed tasks in a sandbox folder, checks the results in code, and compares models and settings."))),
    root));
  const offline = Object.entries(data.agents).filter(([, c]) => !c.needs && !c.smoke).map(([n]) => n);
  const pick = { agents: new Set(offline), models: new Set(), variants: { 0: new Set(["Telegram on"]), 1: new Set(["Full Voice on"]), 2: new Set() },
    timeout: 15, internet: false, email: false };
  let timer = null, showReport = null;

  function variants() {
    const lists = [0, 1, 2].map((i) => [...pick.variants[i]].length ? [...pick.variants[i]] : [""]);
    const out = [];
    for (const a of lists[0]) for (const b of lists[1]) for (const c of lists[2]) out.push([a, b, c].filter(Boolean).join(" + "));
    return out;
  }
  function chipSet(options, set, onchange) {
    const wrap = h("div", { class: "row wrap", style: { gap: "6px" } });
    const draw = () => { clear(wrap); for (const [v, l, hint] of options) wrap.append(h("button", { class: `chip click ${set.has(v) ? "on" : ""}`, title: hint || "",
      onclick: () => { set.has(v) ? set.delete(v) : set.add(v); draw(); onchange && onchange(); } }, l)); };
    draw();
    return wrap;
  }
  function draw() {
    clear(root);
    const job = data.job;
    if (job && !job.done) { root.append(live(job)); return; }
    const total = pick.agents.size * Math.max(1, pick.models.size) * variants().length;
    const count = h("span", { class: "small muted" });
    const upd = () => { count.textContent = `${pick.agents.size * Math.max(1, pick.models.size) * variants().length} test runs`; };
    root.append(h("div", { class: "card" },
      h("div", { class: "card-head" }, h("h2", { class: "grow" }, "New test run"), count,
        h("button", { class: "btn primary", onclick: start }, icon("play"), "Start")),
      h("div", { class: "card-body stack", style: { gap: "18px" } },
        field("Agents", chipSet(Object.entries(data.agents).map(([n, c]) => [n, n + (c.needs ? ` (${c.needs})` : ""), c.task]), pick.agents, upd)),
        field("Models", data.models.length ? chipSet(data.models.map((m) => [m, m]), pick.models, upd) : h("span", { class: "small muted" }, "Ollama isn't running."),
          "None chosen: each agent uses its own model."),
        h("div", { class: "fields" }, SETTINGS.map(([label, opts], i) =>
          field(label, chipSet(opts.map((o) => [o, o.replace(label, "").trim() || o]), pick.variants[i], upd), i === 2 ? "None: as each agent is saved." : null))),
        h("div", { class: "fields" },
          field("Minutes per test before it's stopped", input(pick.timeout, (v) => (pick.timeout = parseInt(v, 10) || 15), { type: "number", min: 1 })),
          toggle("Include internet tests", pick.internet, (v) => (pick.internet = v)),
          toggle("Include email tests", pick.email, (v) => (pick.email = v), "Dry: nothing is moved")))));
    upd();
    void total;
    if (data.reports.length) {
      root.append(h("div", { class: "section-title" }, h("h2", {}, "Past results")));
      root.append(h("div", { class: "card" }, h("table", { class: "table" },
        h("thead", {}, h("tr", {}, ["Run", "Best", "Passed", "Score", "Avg time", ""].map((x) => h("th", {}, x)))),
        h("tbody", {}, data.reports.map((r) => {
          const best = r.summary[0] || {};
          return h("tr", { class: "click", onclick: () => openReport(r.id) },
            h("td", { class: "mono small" }, r.id), h("td", {}, best.model ? `${best.model} · ${best.variant}` : "—"),
            h("td", {}, best.passed || "—"), h("td", {}, best.avg_score ?? "—"), h("td", {}, best.avg_seconds ? dur(best.avg_seconds) : "—"),
            h("td", { class: "num" }, icon("chev")));
        })))));
    }
    if (showReport) root.append(showReport);
  }
  async function start() {
    try {
      await post("/api/bench", { agents: [...pick.agents], models: [...pick.models], variants: variants(),
        timeout_min: pick.timeout, internet: pick.internet, email: pick.email });
      await refresh();
    } catch (e) { fail(e); }
  }
  async function refresh() {
    data = await get("/api/bench");
    draw();
    clearTimeout(timer);
    if (data.job && !data.job.done) timer = setTimeout(refresh, 2500);
  }
  function live(job) {
    const done = job.results.length;
    return h("div", { class: "stack" },
      h("div", { class: "card pad stack" },
        h("div", { class: "row between" }, h("h2", {}, `Running ${done + 1 > job.total ? job.total : done + 1} of ${job.total}`),
          h("button", { class: "btn sm", onclick: async () => { await post("/api/bench/stop"); refresh(); } }, icon("stop"), "Stop")),
        h("div", { class: "progress" }, h("div", { style: { width: `${(done / Math.max(1, job.total)) * 100}%` } })),
        h("div", { class: "small muted row" }, h("span", { class: "spinner" }), job.current || "Starting…")),
      job.results.length ? results(job.summary, job.results) : null);
  }
  async function openReport(id) {
    try {
      const r = await get(`/api/bench/report/${encodeURIComponent(id)}`);
      showReport = h("div", {}, h("div", { class: "section-title" }, h("h2", {}, `Results · ${id}`)), results(r.summary, r.results));
      draw();
      showReport.scrollIntoView({ behavior: "smooth" });
    } catch (e) { fail(e); }
  }
  function results(summary, rows) {
    const max = Math.max(1, ...summary.map((s) => s.avg_seconds));
    return h("div", { class: "stack" },
      h("div", { class: "card" }, h("table", { class: "table" },
        h("thead", {}, h("tr", {}, ["Model · settings", "Passed", "Score", "Avg time", "", "Calls", "Tokens in"].map((x) => h("th", {}, x)))),
        h("tbody", {}, summary.map((s, i) => h("tr", {},
          h("td", {}, i === 0 ? h("span", { class: "pill ok", style: { marginRight: "8px" } }, "Best") : null, h("strong", {}, s.model), h("div", { class: "tiny faint" }, s.variant)),
          h("td", {}, s.passed), h("td", {}, s.avg_score ?? ""), h("td", {}, dur(s.avg_seconds)),
          h("td", { style: { width: "28%" } }, h("div", { class: "bar-track" }, h("div", { class: "bar-fill", style: { width: `${(s.avg_seconds / max) * 100}%` } }))),
          h("td", {}, s.avg_calls), h("td", {}, Math.round(s.avg_tokens_in).toLocaleString())))))),
      h("details", { class: "card disclosure" }, h("summary", {}, h("span", {}, `Every test · ${rows.length}`), icon("chev", "chev")),
        h("div", { class: "body" }, h("table", { class: "table" },
          h("thead", {}, h("tr", {}, ["Agent", "Model · settings", "Result", "Time", "What failed"].map((x) => h("th", {}, x)))),
          h("tbody", {}, rows.map((r) => h("tr", { class: r.run_id ? "click" : "", onclick: () => r.run_id && (location.hash = `#/activity/${r.run_id}`) },
            h("td", {}, r.agent), h("td", { class: "small" }, r.model, h("div", { class: "tiny faint" }, r.variant)),
            h("td", {}, r.passed === null || r.passed === undefined ? h("span", { class: "pill" }, "skipped")
              : h("span", { class: `pill ${r.passed ? "ok" : "bad"}` }, r.passed ? "Pass" : "Fail"), r.score !== undefined ? h("span", { class: "tiny faint" }, ` ${r.score}`) : null),
            h("td", {}, r.seconds ? dur(r.seconds) : ""),
            h("td", { class: "small muted" }, (r.checks || []).filter((c) => !c.ok).map((c) => c.check + (c.detail ? ` (${c.detail})` : "")).join("; ") || r.why || ""))))))));
  }
  draw();
  if (data.job && !data.job.done) refresh();
  return () => clearTimeout(timer);
}
