// agents.js: the Agents page (cards) and the agent editor.
import {
  CAP_ICON, api, clear, confirmBox, fail, field, get, h, icon, initials, input, loadMeta, mdEl, modal, post, seg,
  select, store, tags, textarea, toast, toggle, grow,
} from "./core.js";

const MODE_OPTS = [["off", "Off"], ["allow", "Allow"], ["ask", "Ask first"]];

// ---------------------------------------------------------------- access presets
// Each sets only the capability modes (and the scope it needs); anything else stays as it was.
const ALL_CAPS = ["files.read", "files.create", "files.modify", "files.move", "files.delete", "internet.read",
  "internet.search", "email.read", "email.organize", "memory.read", "memory.write", "interaction.ask_user"];
const PRESETS = [
  { id: "answers", icon: "chat", title: "Answers only", sub: "Talks with you. Touches nothing.",
    modes: { "interaction.ask_user": "allow" } },
  { id: "workspace", icon: "file", title: "Workspace files", sub: "Reads and writes in its workspace. Asks before changing a file.",
    modes: { "files.read": "allow", "files.create": "allow", "files.modify": "ask", "interaction.ask_user": "allow" },
    scope: (p) => { if (!p.files.folders.length) p.files.folders = ["workspace"]; } },
  { id: "organize", icon: "folder", title: "Organize a folder", sub: "Sorts and moves files. Asks which folder, and before moving.",
    modes: { "files.read": "allow", "files.create": "allow", "files.move": "ask", "interaction.ask_user": "allow" },
    scope: (p) => { p.files.ask_for_other_folders = true; } },
  { id: "web", icon: "globe", title: "Web research", sub: "Searches and reads the web, saves notes in its workspace.",
    modes: { "internet.read": "allow", "internet.search": "allow", "files.read": "allow", "files.create": "allow", "interaction.ask_user": "allow" },
    scope: (p) => { p.internet.other_domains = "ask"; if (!p.files.folders.length) p.files.folders = ["workspace"]; } },
  { id: "email", icon: "mail", title: "Email", sub: "Reads your mail. Asks before moving anything.",
    modes: { "email.read": "allow", "email.organize": "ask", "interaction.ask_user": "allow" } },
];
const modeOf = (pol, cap) => { const [g, a] = cap.split("."); return (pol[g] || {})[a] || "off"; };
const setMode = (pol, cap, m) => { const [g, a] = cap.split("."); pol[g][a] = m; };
function presetOf(pol) {
  for (const p of PRESETS) {
    if (ALL_CAPS.every((c) => modeOf(pol, c) === (p.modes[c] || "off"))) return p.id;
  }
  return "custom";
}
function applyPreset(pol, p) {
  for (const c of ALL_CAPS) setMode(pol, c, p.modes[c] || "off");
  p.scope && p.scope(pol);
}

// tool name -> capability group, for the little icons on cards
function capGroups(toolNames, meta) {
  const groups = new Set();
  for (const t of toolNames || []) {
    const cap = meta.tools[t];
    if (cap && !cap.startsWith("internal")) groups.add(cap.split(".")[0]);
  }
  groups.delete("interaction");
  return [...groups];
}

// ---------------------------------------------------------------- Agents page
export async function agentsPage(main) {
  const [data, meta] = await Promise.all([get("/api/agents"), loadMeta()]);
  let filter = "all", q = "";
  const grid = h("div", { class: "grid" });
  const page = h("div", { class: "page wide" },
    h("div", { class: "page-head" },
      h("div", {}, h("h1", {}, "Agents"), h("p", {}, "Each agent is one YAML file: instructions, a model, and exactly what it may touch.")),
      h("div", { class: "actions" },
        h("button", { class: "btn", onclick: () => describeModal() }, icon("sparkle"), "Describe one"),
        h("button", { class: "btn primary", onclick: () => (location.hash = "#/agents/new") }, icon("plus"), "New agent"))),
    h("div", { class: "row", style: { marginBottom: "18px", gap: "12px" } },
      h("div", { style: { position: "relative", width: "320px" } },
        h("span", { style: { position: "absolute", left: "10px", top: "9px", color: "var(--text-3)" } }, icon("search")),
        h("input", { class: "input", placeholder: "Search agents", style: { paddingLeft: "32px" },
          oninput: (e) => { q = e.target.value.toLowerCase(); draw(); } })),
      seg([["all", "All"], ["mine", "Yours"], ["template", "Templates"]], filter, (v) => { filter = v; draw(); })),
    grid);
  main.append(page);

  function card(a) {
    const groups = capGroups(a.tools, meta);
    return h("div", { class: "card agent-card", onclick: () => (location.hash = `#/agents/${a.id}`) },
      h("div", { class: "top" }, h("span", { class: "avatar" }, initials(a.name)),
        h("div", { class: "grow" }, h("h3", { class: "ellipsis" }, a.name),
          h("div", { class: "tiny faint" }, a.kind === "template" ? "Template" : "Yours", " · ", a.model))),
      h("div", { class: "what clamp2" }, a.what),
      h("div", { class: "foot" },
        h("span", { class: "cap-icons", title: a.needs }, groups.length ? groups.map((g) => icon(CAP_ICON[g] || "info")) : h("span", { class: "tiny" }, "No access")),
        a.route === "relay" ? h("span", { class: "chip" }, "Relay") : null,
        a.mode_key === "rules" ? h("span", { class: "chip" }, "Rule mode") : null,
        a.tested ? h("span", { class: `pill ${String(a.tested).includes("passed") ? "ok" : "bad"}`, title: a.tested },
          String(a.tested).includes("passed") ? "Tested" : "Test failed") : null));
  }
  function draw() {
    clear(grid);
    const list = [...data.mine, ...data.templates].filter((a) => !a.error)
      .filter((a) => filter === "all" || a.kind === filter)
      .filter((a) => !q || `${a.name} ${a.what}`.toLowerCase().includes(q));
    if (!list.length) grid.append(h("div", { class: "empty", style: { gridColumn: "1/-1" } }, icon("search"), h("h3", {}, "No agents match")));
    list.forEach((a) => grid.append(card(a)));
  }
  draw();
  return null;
}

function describeModal() {
  let desc = "", model = store.status.models[0] || "";
  const btn = { label: "Draft it", kind: "primary", run: async (close) => {
    if (!desc.trim()) return;
    const b = m.foot.querySelector(".btn.primary");
    b.disabled = true; b.textContent = "Drafting…";
    try {
      const out = await post("/api/agents/generate", { description: desc, model });
      store.draft = out.config;
      close();
      location.hash = "#/agents/new";
    } catch (e) { fail(e); b.disabled = false; b.textContent = "Draft it"; }
  } };
  const m = modal({ title: "Describe an agent", actions: [{ label: "Cancel", kind: "ghost" }, btn], body: [
    h("p", { class: "muted", style: { margin: 0 } }, "Your local model drafts the instructions and access. You review everything before saving."),
    field("What should it do?", textarea("", (v) => (desc = v), { placeholder: "Sort files in a folder I choose into images and documents", rows: 4 })),
    store.status.models.length ? field("Model that drafts it", select(store.status.models.map((x) => [x, x]), model, (v) => (model = v))) : null,
  ] });
}

// ---------------------------------------------------------------- editor
export async function editorPage(main, id) {
  const meta = await loadMeta();
  let info, kind;
  if (id === "new") {
    info = store.draft ? await post("/api/agents/check", { config: store.draft }) : await get("/api/agents/blank");
    store.draft = null;
    kind = "new";
  } else {
    info = await get(`/api/agents/${encodeURIComponent(id)}`);
    kind = info.kind;
  }
  const cfg = info.config;
  let timer = null, dirty = false;

  const nameIn = h("input", { class: "name-input", value: cfg.name, oninput: (e) => { cfg.name = e.target.value; changed(); } });
  const badge = h("span", { class: "small" });
  const side = h("div", { class: "side" });
  const head = h("div", { class: "page-head", style: { alignItems: "center" } },
    h("div", { class: "grow" },
      h("a", { href: "#/agents", class: "small row", style: { gap: "4px", color: "var(--text-3)", marginBottom: "6px" } }, icon("back"), "Agents"),
      nameIn, h("div", { class: "row", style: { marginTop: "4px" } }, badge)),
    h("div", { class: "actions" },
      h("button", { class: "btn", onclick: () => testModal(cfg) }, icon("check"), "Test"),
      h("button", { class: "btn", onclick: () => planModal(cfg) }, icon("list"), "Plan"),
      h("button", { class: "btn", onclick: () => save() }, "Save"),
      h("button", { class: "btn primary", onclick: () => runModal(cfg) }, icon("play"), "Run")));
  const form = h("div", { class: "stack", style: { gap: "16px" } });
  main.append(h("div", { class: "page wide" }, head,
    kind === "template" ? h("div", { class: "banner info" }, icon("info"),
      h("div", {}, h("strong", {}, "This is a template. "), "Change anything you like; Save makes it your own agent.")) : null,
    h("div", { class: "editor" }, form, side)));

  function changed() {
    dirty = true;
    badge.className = "small unsaved"; badge.textContent = "Unsaved changes";
    clearTimeout(timer);
    timer = setTimeout(refresh, 350);
  }
  async function refresh() {
    try { info = await post("/api/agents/check", { config: cfg }); drawSide(); } catch (e) { fail(e); }
  }
  async function save() {
    try {
      const out = await post("/api/agents", { config: cfg });
      toast(`Saved ${cfg.name}`);
      if (`#/agents/${out.id}` !== location.hash) location.hash = `#/agents/${out.id}`;
      else { info = out; drawSide(); }
    } catch (e) { fail(e); }
  }

  // ---------------------------------------------------------- side panel
  function drawSide() {
    badge.className = `small ${info.unsaved ? "unsaved" : "faint"}`;
    badge.textContent = info.unsaved ? (info.saved_as ? "Unsaved changes" : kind === "template" && !dirty ? "Template" : "Not saved yet") : "Saved";
    const s = info.summary;
    const bad = info.checks.filter((c) => !c.ok);
    const li = (ic, cls, t) => h("li", {}, icon(ic, cls), h("span", {}, t));
    const short = (t) => t.split(": ").slice(0, 2).join(" · ").replace(/\.$/, "");
    clear(side).append(
      h("div", { class: "card pad stack" },
        h("div", { class: "row between" }, h("h2", {}, "What it can do"),
          h("button", { class: "btn ghost sm", onclick: () => yamlModal(info.yaml, cfg) }, icon("code"), "YAML")),
        s.allowed.length ? h("div", { class: "stack tight" }, h("div", { class: "eyebrow" }, "Does freely"),
          h("ul", { class: "summary-list" }, s.allowed.map((t) => li("check", "", short(t))))) : null,
        s.asks.length ? h("div", { class: "stack tight" }, h("div", { class: "eyebrow" }, "Asks you first"),
          h("ul", { class: "summary-list" }, s.asks.map((t) => li("user", "", short(t))))) : null,
        s.notes.length ? h("div", { class: "stack tight" }, h("div", { class: "eyebrow" }, "Limits"),
          h("ul", { class: "summary-list" }, s.notes.map((t) => li("shield", "", t)))) : null),
      h("div", { class: "card pad stack tight" },
        h("div", { class: "row between" }, h("h2", {}, "Checks"),
          bad.length ? h("span", { class: `pill ${info.valid ? "warn" : "bad"}` }, `${bad.length} to look at`) : h("span", { class: "pill ok" }, "Ready")),
        bad.length ? bad.map((c) => h("div", { class: "check-line" }, icon(c.level === "error" ? "x" : "alert"),
          h("div", {}, h("strong", {}, c.check), " ", h("span", { class: "muted" }, c.detail))))
          : h("div", { class: "small muted" }, `All ${info.checks.length} checks passed.`)),
      h("div", { class: "card pad stack tight" }, h("h2", {}, "Tools"),
        h("div", { class: "row wrap", style: { gap: "6px" } }, info.tools.map((t) => h("span", { class: "chip mono" }, t)))));
  }

  // ---------------------------------------------------------- sections
  const pol = cfg.permissions;
  const openGroups = new Set();
  function basics() {
    const models = [...new Set([cfg.model, ...store.status.models])];
    return h("div", { class: "card" },
      h("div", { class: "card-head" }, h("h2", {}, "Basics")),
      h("div", { class: "card-body stack" },
        h("div", { class: "fields" },
          field("What it does", input(cfg.description, (v) => { cfg.description = v; changed(); }, { placeholder: "One line, shown on its card" })),
          field("Model", select(models.map((m) => [m, store.status.models.includes(m) ? m : `${m} (not installed)`]), cfg.model,
            (v) => { cfg.model = v; changed(); }))),
        field("Instructions", textarea(cfg.system_prompt, (v) => { cfg.system_prompt = v; changed(); }, { rows: 8 }),
          "How it should work, in plain words. Permissions are enforced in code, not here."),
        field("Example tasks", tags(cfg.examples, (v) => { cfg.examples = v; changed(); }, "Add an example and press Enter"),
          "Shown on Home as one-click suggestions."),
        h("details", { class: "disclosure", style: { margin: "0 -20px -20px" } },
          h("summary", {}, h("span", { class: "small" }, "Catalog card"), icon("chev", "chev")),
          h("div", { class: "body fields" },
            field("Good for", tags(cfg.good_for, (v) => { cfg.good_for = v; changed(); })),
            field("Not for", tags(cfg.not_for, (v) => { cfg.not_for = v; changed(); }))))));
  }

  function access() {
    const body = h("div", { class: "card-body stack" });
    const draw = () => {
      const current = presetOf(pol);
      clear(body).append(
        h("div", { class: "presets" }, [...PRESETS, { id: "custom", icon: "wrench", title: "Custom", sub: "Choose each permission yourself." }].map((p) =>
          h("div", { class: `preset ${current === p.id ? "on" : ""}`, onclick: () => {
            if (p.id !== "custom") { applyPreset(pol, p); changed(); }
            details.open = true; draw();
          } }, h("div", { class: "ttl" }, icon(p.icon), p.title), h("div", { class: "sub" }, p.sub)))));
      body.append(details);
      details.open = details.open || current === "custom";
      clear(details).append(h("summary", {}, h("span", { class: "small" }, "Permissions in detail"), icon("chev", "chev")),
        h("div", { class: "body caps" }, Object.entries(meta.groups).map(([g, label]) => capGroup(g, label, draw))));
    };
    const details = h("details", { class: "disclosure", style: { margin: "0 -20px -20px", borderTop: "1px solid var(--border)" } });
    draw();
    return h("div", { class: "card" },
      h("div", { class: "card-head" }, h("h2", { class: "grow" }, "Access"),
        h("span", { class: "small faint" }, "Off: it can't even see the tool · Ask first: the run pauses for your OK")),
      body);
  }
  function capGroup(g, label, redraw) {
    const caps = Object.entries(meta.capabilities).filter(([c]) => c.startsWith(g + "."));
    const on = caps.some(([c]) => modeOf(pol, c) !== "off");
    const rows = caps.map(([c, inf]) => h("div", { class: "cap-row" },
      h("div", {}, h("div", { class: "name" }, h("span", { class: `risk ${inf.risk}` }), inf.label), h("div", { class: "detail" }, inf.detail)),
      seg(c === "interaction.ask_user" ? MODE_OPTS.slice(0, 2) : MODE_OPTS, modeOf(pol, c), (v) => {
        const was = on; setMode(pol, c, v); changed();
        if (was !== caps.some(([x]) => modeOf(pol, x) !== "off")) redraw();
      })));
    if (!on && !openGroups.has(g)) {  // all off: one quiet line instead of a block of switches
      return h("div", { class: "cap-group row" }, icon(CAP_ICON[g]), h("h3", { class: "grow" }, label),
        h("span", { class: "small faint" }, "Off"),
        h("button", { class: "btn ghost sm", onclick: () => { openGroups.add(g); redraw(); } }, "Turn on…"));
    }
    return h("div", { class: "cap-group" },
      h("div", { class: "row" }, icon(CAP_ICON[g]), h("h3", {}, label)), rows, on ? scopeFor(g) : null);
  }
  function scopeFor(g) {
    if (g === "files") return h("div", { class: "scope" },
      field("Folders it may use", tags(pol.files.folders, (v) => { pol.files.folders = v; changed(); }, "~/Downloads, workspace…"),
        "Subfolders included. “workspace” is the Studio's own workspace folder."),
      h("div", { class: "fields" },
        field("Only these file types", tags(pol.files.file_types, (v) => { pol.files.file_types = v.map((t) => (t.startsWith(".") ? t : "." + t).toLowerCase()); changed(); }, ".pdf, .jpg (empty = all)")),
        field("Max file changes per run", input(pol.files.max_changes, (v) => { pol.files.max_changes = parseInt(v, 10) || 1; changed(); }, { type: "number", min: 1 }))),
      toggle("Ask before using any other folder", pol.files.ask_for_other_folders, (v) => { pol.files.ask_for_other_folders = v; changed(); },
        "You grant it for this run only."));
    if (g === "internet") return h("div", { class: "scope" },
      field("Sites it may open", tags(pol.internet.domains, (v) => { pol.internet.domains = v.map((d) => d.toLowerCase().replace(/^https?:\/\//, "").split("/")[0]); changed(); }, "wikipedia.org"),
        "Subdomains included. Redirects elsewhere are blocked."),
      field("Other sites", seg([["block", "Block"], ["ask", "Ask me each time"]], pol.internet.other_domains, (v) => { pol.internet.other_domains = v; changed(); })));
    if (g === "email") return h("div", { class: "scope" },
      field("Only these mail folders", tags(pol.email.folders, (v) => { pol.email.folders = v; changed(); }, "INBOX, Receipts (empty = all)"),
        h("span", {}, "Set up your account in ", h("a", { href: "#/settings" }, "Settings"), ". Agents can never send or delete mail.")));
    if (g === "memory") return h("div", { class: "scope" },
      h("div", { class: "fields" },
        field("Notes recalled at the start", input(pol.memory.recall, (v) => { pol.memory.recall = parseInt(v, 10) || 0; changed(); }, { type: "number", min: 0, max: 20 }))),
      toggle("Save a summary of each run", pol.memory.run_summaries, (v) => { pol.memory.run_summaries = v; changed(); }, "Written by code from recorded facts."),
      toggle("Use shared memory", pol.memory.shared, (v) => { pol.memory.shared = v; changed(); }, "Off: this agent keeps its own notes."));
    return null;
  }

  function advanced() {
    const v = cfg.verify;
    const models = store.status.models;
    const rules = cfg.mode === "rules";
    const body = h("div", { class: "body stack", style: { gap: "18px" } });
    const draw = () => clear(body).append(
      h("div", { class: "stack tight" }, h("div", { class: "eyebrow" }, "How it works"),
        field("Mode", seg([["agent", "Agent: the model does the work"], ["rules", "Rule: the model writes a rule, code does it"]], cfg.mode,
          (x) => { cfg.mode = x; changed(); draw(); })),
        !rules ? field("Big tasks", seg([["auto", "Triage decides"], ["single", "One agent"], ["relay", "Relay: a PM and small agents"]], cfg.route,
          (x) => { cfg.route = x; changed(); draw(); }), "Relay splits a big job into small chunks, tests them in a browser, and pulls them together.") : null,
        !rules && cfg.route !== "single" ? h("div", { class: "fields" },
          field("Lead model (plans, designs, reviews)", select([["", "Same as the agent"], ...models.filter((m) => m !== cfg.model).map((m) => [m, m]),
            ...(cfg.lead_model && !models.includes(cfg.lead_model) ? [[cfg.lead_model, `${cfg.lead_model} (not installed)`]] : [])],
            cfg.lead_model || "", (x) => { cfg.lead_model = x; changed(); })),
          field("Relay time limit (minutes, 0 = none)", input(cfg.time_limit_min, (x) => { cfg.time_limit_min = parseInt(x, 10) || 0; changed(); }, { type: "number", min: 0 }))) : null),
      h("div", { class: "stack tight" }, h("div", { class: "eyebrow" }, "Speed"),
        h("div", { class: "fields" },
          toggle("Job notes", cfg.plan_steps, (x) => { cfg.plan_steps = x; changed(); }, "Plan + checklist; finished steps drop out"),
          toggle("Telegram style", cfg.terse, (x) => { cfg.terse = x; changed(); }, "Short working replies, compact tools"),
          toggle("Full Voice", cfg.full_voice, (x) => { cfg.full_voice = x; changed(); }, "Complete final answers")),
        h("div", { class: "fields" },
          field("Max steps", input(cfg.max_steps, (x) => { cfg.max_steps = parseInt(x, 10) || 1; changed(); }, { type: "number", min: 1, max: 200 })),
          field("Context (tokens)", select([4096, 8192, 16384, 32768, 65536, 131072].map((n) => [String(n), n.toLocaleString()]), String(cfg.context_length),
            (x) => { cfg.context_length = parseInt(x, 10); changed(); })),
          field("Max reply tokens (0 = no cap)", input(cfg.max_reply_tokens, (x) => { cfg.max_reply_tokens = parseInt(x, 10) || 0; changed(); }, { type: "number", min: 0, step: 256 })),
          field(`Temperature · ${Number(cfg.temperature).toFixed(1)}`, h("input", { type: "range", min: 0, max: 2, step: 0.1, value: cfg.temperature,
            oninput: (e) => { cfg.temperature = parseFloat(e.target.value); e.target.previousSibling.textContent = `Temperature · ${cfg.temperature.toFixed(1)}`; changed(); } }))),
        toggle("Thinking mode", cfg.think, (x) => { cfg.think = x; changed(); }, "Reasoning models only; slower, better at hard tasks")),
      !rules ? h("div", { class: "stack tight" }, h("div", { class: "eyebrow" }, "Checking its work"),
        toggle("Inspector", v.enabled, (x) => { v.enabled = x; changed(); draw(); }, "A read-only checker confirms the real result and sends it back if it isn't done"),
        v.enabled ? h("div", { class: "scope" },
          field("What does “done” mean?", textarea(v.criteria, (x) => { v.criteria = x; changed(); }, { rows: 2, placeholder: "No .pdf files remain in ~/Downloads" })),
          h("div", { class: "fields" },
            field("Max rounds (0 = until you stop it)", input(v.max_attempts, (x) => { v.max_attempts = parseInt(x, 10) || 0; changed(); }, { type: "number", min: 0 })),
            field("Inspector model", select([["", "Same as the agent"], ...models.map((m) => [m, m])], v.model || "", (x) => { v.model = x; changed(); })))) : null) : null);
    draw();
    return h("details", { class: "card disclosure" },
      h("summary", {}, h("h2", {}, "Advanced"), h("span", { class: "small faint" }, "Mode, Relay, speed, checking"), icon("chev", "chev")), body);
  }

  async function schedules() {
    if (kind !== "mine") return null;
    const data = await get("/api/schedules").catch(() => ({ schedules: [] }));
    const slug = id.replace(/^a-/, "");
    const mine = data.schedules.filter((s) => s.agent.replace(/\\/g, "/").endsWith(`/${slug}.yaml`));
    const list = h("div", { class: "stack tight" });
    const draw = (items) => {
      clear(list);
      if (!items.length) list.append(h("div", { class: "small muted" }, "No schedules. It only runs when you start it."));
      for (const s of items) {
        list.append(h("div", { class: "row", style: { padding: "8px 0", borderTop: "1px solid var(--border)" } },
          icon("clock"), h("div", { class: "grow" }, h("div", { style: { fontWeight: 550 } }, s.name),
            h("div", { class: "small faint ellipsis" }, `${s.when} · ${s.task}`)),
          toggle("", s.enabled, async (x) => { try { await api("PUT", `/api/schedules/${s.id}`, { enabled: x }); } catch (e) { fail(e); } }),
          h("button", { class: "btn ghost sm", onclick: async () => { try { const r = await post(`/api/schedules/${s.id}`, { run_now: true }); location.hash = `#/activity/${r.run}`; } catch (e) { fail(e); } } }, icon("play"), "Run now"),
          h("button", { class: "btn ghost sm icon", title: "Delete", onclick: async () => {
            if (!(await confirmBox("Delete schedule?", `“${s.name}” will stop running.`, "Delete"))) return;
            await api("DELETE", `/api/schedules/${s.id}`, {}); draw(items.filter((x) => x.id !== s.id));
          } }, icon("trash"))));
      }
    };
    draw(mine);
    return h("div", { class: "card" },
      h("div", { class: "card-head" }, h("h2", { class: "grow" }, "Schedule"),
        h("button", { class: "btn sm", onclick: () => scheduleModal(id, cfg, () => route()) }, icon("plus"), "Add")),
      h("div", { class: "card-body" }, list));
  }
  const route = () => window.dispatchEvent(new HashChangeEvent("hashchange"));

  form.append(basics(), access(), advanced());
  const sch = await schedules();
  if (sch) form.append(sch);
  drawSide();
  if (kind === "new") { badge.className = "small unsaved"; badge.textContent = "Not saved yet"; }
  return () => clearTimeout(timer);
}

// ---------------------------------------------------------------- modals
function yamlModal(yaml, cfg) {
  modal({ title: `${cfg.name}.yaml`, wide: true, body: [
    h("pre", { class: "code-view", style: { maxHeight: "60vh" } }, yaml),
    h("div", { class: "small muted" }, "An agent is just this file. Run it anywhere: ", h("code", {}, `offline-agent run ${cfg.name}`)),
  ], actions: [
    { label: "Copy", run: async () => { await navigator.clipboard.writeText(yaml).catch(() => {}); toast("Copied"); } },
    { label: "Download", kind: "primary", run: () => {
      const a = h("a", { href: URL.createObjectURL(new Blob([yaml], { type: "text/yaml" })), download: `${(cfg.name || "agent").toLowerCase().replace(/[^a-z0-9]+/g, "_")}.yaml` });
      a.click();
    } }] });
}

export function runModal(cfg, agentId) {
  let task = "";
  const ta = textarea("", (v) => (task = v), { rows: 4, placeholder: "What should it do?" });
  const go = async (close) => {
    if (!task.trim()) return;
    try {
      const { id } = await post("/api/runs", agentId ? { agent: agentId, task } : { config: cfg, task });
      close(); location.hash = `#/activity/${id}`;
    } catch (e) { fail(e); }
  };
  ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) go(m.close); });
  const m = modal({ title: `Run ${cfg.name}`, body: [ta,
    (cfg.examples || []).length ? h("div", { class: "row wrap" }, cfg.examples.slice(0, 4).map((x) =>
      h("button", { class: "chip click", onclick: () => { ta.value = x; task = x; grow(ta); } }, x))) : null,
    h("div", { class: "tiny faint" }, "Runs keep going in the background. Unsaved changes are included.")],
  actions: [{ label: "Cancel", kind: "ghost" }, { label: "Run", kind: "primary", run: go }] });
}

function testModal(cfg) {
  let task = "What can you help me with?";
  const out = h("div", { class: "stack tight" });
  const m = modal({ title: "Test it", body: [
    h("p", { class: "muted small", style: { margin: 0 } }, "One real question. Actions that ask first are denied, and questions get no answer, so nothing changes."),
    input(task, (v) => (task = v)), out],
  actions: [{ label: "Close", kind: "ghost" }, { label: "Run test", kind: "primary", run: async () => {
    const b = m.foot.querySelector(".primary"); b.disabled = true; b.textContent = "Running…";
    clear(out).append(h("div", { class: "row muted small" }, h("span", { class: "spinner" }), "The model is working…"));
    try {
      const r = await post("/api/agents/dry-run", { config: cfg, task });
      const answer = [...r.events].reverse().find((e) => e.type === "answer");
      const tools = r.events.filter((e) => e.type === "tool_call").length;
      clear(out).append(h("div", { class: "row" }, h("span", { class: `pill ${r.ok ? "ok" : "bad"}` }, r.ok ? "Passed" : "No answer"),
        h("span", { class: "small faint" }, `${r.seconds}s · ${tools} tool call${tools === 1 ? "" : "s"}`)),
        answer ? mdEl(answer.content, "card pad") : h("div", { class: "small muted" }, (r.events.find((e) => e.type === "error") || {}).content || ""));
    } catch (e) { clear(out); fail(e); }
    b.disabled = false; b.textContent = "Run again";
  } }] });
}

function planModal(cfg) {
  let task = (cfg.examples || [])[0] || "";
  const out = h("div", { class: "stack tight" });
  const ICON = { allowed: ["check", "ok"], "asks you": ["user", "warn"], blocked: ["x", "bad"], reasoning: ["sparkle", ""], "unknown tool": ["info", ""] };
  const m = modal({ title: "How would it do this?", wide: true, body: [
    h("p", { class: "muted small", style: { margin: 0 } }, "The agent explains its plan. Nothing runs."),
    input(task, (v) => (task = v), { placeholder: "e.g. Sort my Downloads folder" }), out],
  actions: [{ label: "Close", kind: "ghost" }, { label: "Show plan", kind: "primary", run: async () => {
    if (!task.trim()) return;
    const b = m.foot.querySelector(".primary"); b.disabled = true;
    clear(out).append(h("div", { class: "row muted small" }, h("span", { class: "spinner" }), "Planning…"));
    try {
      const p = await post("/api/agents/plan", { config: cfg, task });
      clear(out).append(h("p", { style: { margin: "0 0 6px" } }, h("em", {}, p.understanding || "")),
        h("div", { class: "card" }, (p.steps || []).map((s, i) => {
          const [ic, kind] = ICON[s.status] || ["info", ""];
          return h("div", { class: "row", style: { padding: "10px 14px", borderTop: i ? "1px solid var(--border)" : "0" } },
            h("span", { class: "faint small", style: { width: "18px" } }, i + 1), h("div", { class: "grow" }, s.action),
            h("span", { class: "chip mono" }, s.tool), h("span", { class: `pill ${kind}` }, icon(ic), s.status + (s.needs ? ` · needs ${s.needs}` : "")));
        })),
        (p.steps || []).some((s) => s.status === "blocked") ? h("div", { class: "banner" }, icon("alert"), "Some steps need permissions this agent doesn't have.") : null,
        h("div", { class: "tiny faint" }, "A plan is the model's intention, not a guarantee."));
    } catch (e) { clear(out); fail(e); }
    b.disabled = false;
  } }] });
}

function scheduleModal(agentId, cfg, done) {
  const s = { agent: agentId, name: `${cfg.name} schedule`, task: "", kind: "daily", time: "09:00", weekdays: [], every_minutes: 60 };
  const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const extra = h("div", {});
  const drawExtra = () => clear(extra).append(
    s.kind === "interval" ? field("Every N minutes", input(s.every_minutes, (v) => (s.every_minutes = parseInt(v, 10) || 60), { type: "number", min: 5 }))
      : h("div", { class: "fields" }, field("At", input(s.time, (v) => (s.time = v), { type: "time" })),
        s.kind === "weekdays" ? field("Days", h("div", { class: "row wrap" }, days.map((d, i) => {
          const c = h("button", { class: `chip click ${s.weekdays.includes(i) ? "on" : ""}`, onclick: () => {
            s.weekdays = s.weekdays.includes(i) ? s.weekdays.filter((x) => x !== i) : [...s.weekdays, i]; drawExtra();
          } }, d); return c;
        }))) : null));
  drawExtra();
  modal({ title: "Schedule", body: [
    field("Task", textarea("", (v) => (s.task = v), { rows: 3, placeholder: "Collect today's market headlines and save them." })),
    field("When", seg([["daily", "Every day"], ["weekdays", "Chosen days"], ["interval", "Every N minutes"]], s.kind, (v) => { s.kind = v; drawExtra(); })),
    extra, field("Name", input(s.name, (v) => (s.name = v))),
    h("div", { class: "tiny faint" }, "Runs while the Studio is open, or headless with offline-agent scheduler. Nobody may be watching: actions that ask first wait for you.")],
  actions: [{ label: "Cancel", kind: "ghost" }, { label: "Save schedule", kind: "primary", run: async (close) => {
    try {
      await post("/api/schedules", { ...s, kind: s.kind === "interval" ? "interval" : "daily", weekdays: s.kind === "weekdays" ? s.weekdays : [] });
      close(); toast("Scheduled"); done();
    } catch (e) { fail(e); }
  } }] });
}
