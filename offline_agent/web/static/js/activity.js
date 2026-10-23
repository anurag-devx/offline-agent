// activity.js: every run, live. A list on the left, the selected run as a conversation on the right.
import { ago, api, clear, confirmBox, dur, fail, get, h, icon, mdEl, num, post, seg, statusDot, statusPill, grow, toast } from "./core.js";

const PHASES = [["plan", "Plan"], ["design", "Design"], ["build", "Build"], ["integrate", "Integrate"],
  ["test", "Browser test"], ["look", "Look"], ["review", "Review"], ["done", "Done"]];
const TOOL_ICON = (name) => /email/.test(name) ? "mail" : /fetch|search|feed/.test(name) ? "globe" :
  /recall|remember/.test(name) ? "brain" : /ask_user/.test(name) ? "chat" : /step/.test(name) ? "list" :
  /calc|date/.test(name) ? "clock" : "file";
const short = (v, n = 90) => { const s = typeof v === "string" ? v : JSON.stringify(v); return s.length > n ? s.slice(0, n) + "…" : s; };
const firstLine = (s) => String(s ?? "").split("\n").find((x) => x.trim()) || "";

export async function activityPage(main, rid) {
  const listItems = h("div", { class: "items" });
  const detail = h("div", { class: "detail-pane" });
  let filter = "all", q = "", runs = [], timer = null, closeRun = null;
  main.append(h("div", { class: "split" },
    h("div", { class: "list-pane" },
      h("div", { class: "head" }, h("h1", { style: { fontSize: "18px", margin: 0, fontWeight: 650 } }, "Activity"),
        h("input", { class: "input", placeholder: "Search runs", oninput: (e) => { q = e.target.value.toLowerCase(); drawList(); } }),
        seg([["all", "All"], ["active", "Active"], ["you", "Needs you"]], filter, (v) => { filter = v; drawList(); })),
      listItems),
    detail));

  async function loadList() {
    try {
      runs = (await get("/api/runs?limit=300")).runs;
      drawList();
      if (!rid && runs.length) { location.replace(`#/activity/${runs[0].id}`); return; }
    } catch (e) { /* keep old list */ }
    clearTimeout(timer);
    timer = setTimeout(loadList, runs.some((r) => r.active) ? 2500 : 8000);
  }
  function drawList() {
    clear(listItems);
    const list = runs.filter((r) => filter === "all" || (filter === "active" ? r.active : r.status.startsWith("waiting")))
      .filter((r) => !q || `${r.task} ${r.agent}`.toLowerCase().includes(q));
    if (!list.length) listItems.append(h("div", { class: "empty small" }, "No runs here."));
    for (const r of list) {
      listItems.append(h("div", { class: `run-item ${r.id === rid ? "on" : ""}`, onclick: () => (location.hash = `#/activity/${r.id}`) },
        statusDot(r.status), h("div", { class: "grow" },
          h("div", { class: "t clamp2" }, r.task.replace(/^\[bench\]\s*/, "")),
          h("div", { class: "tiny faint ellipsis" }, `${r.agent} · ${ago(r.started)}${r.route === "relay" ? " · Relay" : ""}`))));
    }
  }
  loadList();
  if (rid) closeRun = await openRun(detail, rid);
  else detail.append(h("div", { class: "empty", style: { marginTop: "18vh" } }, icon("activity"),
    h("h3", {}, "No runs yet"), h("p", {}, "Start one from ", h("a", { href: "#/" }, "Home"), " or an agent's page.")));
  return () => { clearTimeout(timer); closeRun && closeRun(); };
}

// ---------------------------------------------------------------- one run
async function openRun(root, rid) {
  let d = await get(`/api/runs/${encodeURIComponent(rid)}`);
  let tab = "chat", es = null, pending = d.pending, queued = false;
  const head = h("div", { class: "run-head" });
  const body = h("div", { class: "run-body" });
  const foot = h("div", { class: "followup" });
  clear(root).append(head, body, foot);

  const nearBottom = () => root.scrollHeight - root.scrollTop - root.clientHeight < 160;
  function render(stick) {
    const stickNow = stick ?? nearBottom();
    drawHead(); drawBody(); drawFoot();
    if (stickNow && tab === "chat") root.scrollTop = root.scrollHeight;
  }
  function later() {
    if (queued) return;
    queued = true;
    setTimeout(() => { queued = false; render(); }, 200);
  }

  // ---------------------------------------------------------- header
  function drawHead() {
    const relay = d.route === "relay" && d.relay;
    const actions = h("div", { class: "row", style: { gap: "6px" } },
      statusPill(d.status),
      d.active ? h("button", { class: "btn sm", onclick: () => act("stop") }, icon("stop"), "Stop") : null,
      d.can_resume ? h("button", { class: "btn sm primary", onclick: () => act("resume") }, icon("play"), "Resume") : null);
    const tabs = [["chat", "Conversation"], ["notes", relay ? "Relay notes" : "Notes"], ["files", `Files${d.file_changes ? ` · ${d.file_changes}` : ""}`],
      ["speed", "Speed"]].filter(([k]) => k !== "notes" || d.notes);
    clear(head).append(
      h("div", { class: "row", style: { alignItems: "flex-start", gap: "16px" } },
        h("div", { class: "grow" }, h("h1", { class: "clamp2" }, d.task.replace(/^\[bench\]\s*/, "")),
          h("div", { class: "meta" }, h("span", {}, d.agent), h("span", {}, d.model), h("span", {}, ago(d.started)),
            h("span", {}, dur(d.seconds)), h("span", {}, `${num(d.prompt_tokens + d.output_tokens)} tokens`),
            d.verified ? h("span", { style: { color: "var(--ok)" } }, "✓ verified") : null)),
        actions),
      relay ? stepper(d.relay) : null,
      h("div", { class: "tabs" }, tabs.map(([k, l]) => h("button", { class: tab === k ? "on" : "", onclick: () => { tab = k; render(false); } }, l))));
  }
  function stepper(r) {
    const at = PHASES.findIndex(([k]) => k === r.phase);
    const chunks = r.chunks || [];
    const built = chunks.filter((c) => c.status === "done").length;
    return h("div", { class: "stepper" }, PHASES.map(([k, label], i) => {
      const state = r.phase === "failed" ? (i < PHASES.length - 1 ? "done" : "") : i < at ? "done" : i === at ? "now" : "";
      const extra = k === "build" && chunks.length ? ` ${built}/${chunks.length}` :
        k === "test" && r.test ? ` ${r.test.passed}/${r.test.total}` : "";
      return h("span", { class: `st ${state}` }, state === "done" ? icon("check") : null, label + extra);
    }), r.phase === "failed" ? h("span", { class: "st", style: { color: "var(--bad)", background: "var(--bad-soft)" } }, "Not finished") : null);
  }

  // ---------------------------------------------------------- body
  function drawBody() {
    clear(body);
    if (tab === "chat") body.append(thread());
    else if (tab === "notes") body.append(mdEl(d.notes, "card pad"),
      d.shots ? h("div", { class: "shots" },
        h("img", { src: `/api/runs/${d.id}/shot/desktop?t=${d.seconds}`, alt: "Desktop screenshot" }),
        h("img", { src: `/api/runs/${d.id}/shot/phone?t=${d.seconds}`, alt: "Phone screenshot" })) : null);
    else if (tab === "files") body.append(files());
    else if (tab === "speed") body.append(speed());
  }

  function thread() {
    const out = h("div", { class: "thread" });
    const relay = d.route === "relay";
    let block = null;
    const close = () => { block = null; };
    const step = (row) => {
      if (!block) { block = { steps: [], start: null, end: null, calls: 0 }; out.append(workBlock(block)); }
      block.steps.push(row);
      block.el.refresh();
    };
    const note = (ic, text, cls = "") => { close(); out.append(h("div", { class: `note ${cls}` }, icon(ic), h("div", {}, text))); };
    let lastTool = null;
    for (const e of d.events) {
      const t = e.type;
      if (t === "model_call") { if (block) block.calls++; continue; }
      if (t === "user") {
        if (e.worker) step({ ic: "user", tool: "brief for the worker", res: firstLine(e.content.split("YOUR CHUNK")[1] || ""), full: e.content });
        else if (e.auto) { close(); out.append(h("div", { class: "note violet" }, icon("refresh"), h("div", {}, "Sent back to finish: ", h("span", { class: "muted" }, firstLine(e.content.replace(/^A verifier.*\n/, "")))))); }
        else if (!/^\[resume/.test(e.content)) { close(); out.append(h("div", { class: "msg user" }, h("span", { class: "who" }, "You"), userBubble(e.content.replace(/^\[bench\]\s*/, "")))); }
      } else if (t === "answer") {
        if (relay && !e.relay) step({ ic: "check", tool: "worker", res: firstLine(e.content), full: e.content });
        else { close(); out.append(h("div", { class: "msg bot" }, h("span", { class: "who" }, (d.agent || "A")[0]), h("div", { class: "bubble grow" }, mdEl(e.content)))); }
      } else if (t === "tool_call") {
        lastTool = { ic: TOOL_ICON(e.name), tool: e.name, args: e.args, res: "" };
        step(lastTool);
      } else if (t === "tool_result") {
        const r = String(e.result ?? "");
        if (lastTool && lastTool.tool === e.name && !lastTool.full) { lastTool.res = firstLine(r); lastTool.full = r; lastTool.err = /^(Error|The user denied|REFUSED|ERR)/.test(r); block && block.el.refresh(); }
        else step({ ic: TOOL_ICON(e.name), tool: e.name, res: firstLine(r), full: r });
      } else if (t === "triage") {
        if (e.route !== "relay" && e.by !== "model") continue;  // simple tasks: nothing worth showing
        note("flag", `Triage: ${e.complexity !== "-" ? e.complexity + " → " : ""}${e.route === "relay" ? "Relay (a PM and small agents)" : "one agent"}. ${e.reason}`, "faint");
      } else if (t === "relay") {
        if (e.chunks) { close(); out.append(relayPlan(e)); }
        else if (e.phase === "build" && e.chunk && !e.status && !(e.problems || []).length) {
          close();  // a worker starts a chunk: its steps fold into one line
          block = { steps: [], calls: 0, title: e.content, state: "run" };
          out.append(workBlock(block));
        } else if (e.phase === "build" && e.chunk && block && block.title) {
          block.state = e.status === "done" ? "ok" : e.status === "failed" ? "bad" : "retry";
          block.result = e.status === "done" ? "" : e.content.replace(/^\S+\s/, "");
          block.el.refresh(); close();
        } else if (e.status === "done") note("check", e.content, "ok");
        else if (e.status === "failed" || (e.problems && e.problems.length)) note("alert", e.content, "warn");
        else note("layers", e.content, "faint");
      } else if (t === "verify_start") step({ ic: "eye", tool: "Inspector", res: `checking, round ${e.attempt}` });
      else if (t === "verify_step") step({ ic: "eye", tool: `Inspector · ${e.name}`, args: e.args });
      else if (t === "verification") { close(); out.append(verdict(e)); }
      else if (t === "question") { close(); out.append(h("div", { class: "msg bot" }, h("span", { class: "who" }, "?"), h("div", { class: "bubble" }, e.question))); }
      else if (t === "answer_given") { close(); out.append(h("div", { class: "msg user" }, h("span", { class: "who" }, "You"), h("div", { class: "bubble" }, e.answer))); }
      else if (t === "approval_needed") step({ ic: "user", tool: `asks to use ${e.name}`, args: e.args });
      else if (t === "approval") step({ ic: e.approved ? "check" : "x", tool: e.approved ? `approved ${e.name}` : `denied ${e.name}`, err: !e.approved });
      else if (t === "file_op") step({ ic: "file", tool: e.op.replace("_", " "), res: (e.src ? `${e.src} → ` : "") + (e.dst || "") });
      else if (t === "network") step({ ic: "globe", tool: e.allowed ? "web request" : "blocked request", res: e.url, err: !e.allowed });
      else if (t === "plan") note("list", `Plan: ${(e.steps || []).map((s, i) => `${i + 1}. ${s}`).join("  ")}`, "faint");
      else if (t === "rule") { close(); out.append(h("div", { class: "note" }, icon("code"), h("div", { class: "grow" }, "Rule written by the model:", h("pre", { class: "code-view", style: { marginTop: "6px", padding: "8px 12px" } }, e.text)))); }
      else if (t === "warning") { if (/^(Bench|Unattended)/.test(e.content)) step({ ic: "info", tool: "note", res: e.content }); else note("alert", e.content, "warn"); }
      else if (t === "error") note("alert", e.content, "bad");
      else if (t === "stopped") note("stop", e.content);
      else if (t === "recalled") step({ ic: "brain", tool: "recalled from memory", res: (e.items || []).map((x) => x.text).join(" · ") });
      else if (t === "memory_op") step({ ic: "brain", tool: `memory ${e.op}`, res: e.text || "" });
      else if (t === "undo") note("undo", "Undo: " + (e.results || []).map((r) => `${r.result}: ${r.file}`).slice(0, 6).join("; "));
      else if (t === "continued") step({ ic: "chat", tool: "Full Voice", res: `answer continued in ${e.parts} parts` });
      else if (t === "compacted") step({ ic: "layers", tool: "job notes", res: `dropped ${e.dropped} old messages` });
      else if (t === "nudge") step({ ic: "info", tool: "reminder", res: e.content });
      else if (t === "folder_granted") step({ ic: "folder", tool: "folder granted", res: e.folder });
      else if (t === "email_op") step({ ic: "mail", tool: e.op || "email", res: short(e, 80) });
      else if (t === "web_cache") continue;
      else if (t === "verdict") continue;
    }
    if (d.active && !pending) {
      const last = out.lastElementChild;
      if (last && last.tagName === "DETAILS") last.open = true;
      out.append(h("div", { class: "note faint" }, h("span", { class: "spinner" }), h("div", {}, d.status === "verifying" ? "The Inspector is checking…" : "Working…")));
    }
    if (pending) out.append(pendingCard(pending));
    return out;
  }

  function workBlock(b) {
    const list = h("div", { class: "steps" });
    const label = h("span", { class: "grow ellipsis" });
    const mark = h("span", {});
    const count = h("span", { class: "tiny faint" });
    const el = h("details", { class: "work" }, h("summary", {}, mark, label, count, icon("chev", "chev")), list);
    el.refresh = () => {
      const n = `${b.steps.length} step${b.steps.length === 1 ? "" : "s"}` + (b.calls ? ` · ${b.calls} model call${b.calls === 1 ? "" : "s"}` : "");
      clear(mark).append(b.title ? icon(b.state === "ok" ? "check" : b.state === "bad" ? "x" : b.state === "retry" ? "refresh" : "layers") : icon("wrench"));
      mark.style.color = b.state === "ok" ? "var(--ok)" : b.state === "bad" ? "var(--bad)" : b.state === "retry" ? "var(--warn)" : "";
      if (b.title) {
        label.textContent = b.title + (b.result ? ` · ${b.result}` : "");
        count.textContent = n;
      } else { label.textContent = n; count.textContent = ""; }
      clear(list);
      for (const s of b.steps) list.append(stepRow(s));
    };
    b.el = el;
    return el;
  }
  function stepRow(s) {
    const more = h("div", { class: "hidden" });
    const row = h("div", { class: `step ${s.err ? "err" : ""} ${s.full || s.args ? "click" : ""}`, onclick: () => {
      if (!(s.full || s.args)) return;
      more.classList.toggle("hidden");
      if (!more.childNodes.length) more.append(s.args ? h("pre", {}, JSON.stringify(s.args, null, 2)) : null, s.full ? h("pre", {}, s.full) : null);
    } }, icon(s.ic), h("div", { style: { minWidth: 0 } },
      h("div", { class: "ellipsis" }, h("span", { class: "tool" }, s.tool), s.args ? h("span", { class: "args" }, "  ", short(s.args)) : null),
      s.res ? h("div", { class: "res ellipsis" }, s.res) : null, more));
    return row;
  }
  function userBubble(text) {
    if (text.length < 600) return h("div", { class: "bubble" }, text);
    const body = h("div", {}, text.slice(0, 420) + "…");
    let open = false;
    const more = h("button", { class: "btn ghost sm", style: { marginTop: "6px", padding: "0" }, onclick: () => {
      open = !open; body.textContent = open ? text : text.slice(0, 420) + "…"; more.textContent = open ? "Show less" : "Show the whole task";
    } }, "Show the whole task");
    return h("div", { class: "bubble" }, body, more);
  }
  function relayPlan(e) {
    return h("div", { class: "work", style: { padding: "12px 14px" } },
      h("div", { class: "row", style: { marginBottom: "8px" } }, icon("layers"), h("strong", {}, "The PM's plan"), h("span", { class: "small faint" }, e.content)),
      h("div", { class: "stack tight" }, e.chunks.map((c) => h("div", { class: "row small" },
        h("span", { class: "chip mono" }, c.id), h("span", { class: "grow" }, c.title), c.output ? h("code", { class: "faint" }, c.output) : null))));
  }
  function verdict(e) {
    return h("div", { class: `verdict ${e.complete ? "ok" : "bad"}` },
      h("div", { class: "row" }, icon(e.complete ? "check" : "eye"), h("strong", {}, e.complete ? "Inspector: done" : `Inspector: not done yet (round ${e.attempt})`)),
      h("div", { style: { marginTop: "4px" } }, e.reason),
      !e.complete && e.missing ? h("div", { class: "small", style: { marginTop: "4px" } }, "Missing: ", e.missing) : null,
      (e.findings || []).map((f) => h("div", { class: "find small" },
        h("div", {}, h("code", {}, f.file + (f.line ? `:${f.line}` : "")), " ", f.problem),
        f.fix ? h("div", { class: "muted" }, "Fix: ", f.fix) : null,
        f.snippet ? h("pre", { class: "code-view", style: { padding: "8px 10px", marginTop: "6px", fontSize: "11.5px" } }, f.snippet) : null)));
  }
  function pendingCard(p) {
    if (p.kind === "question") {
      const ta = h("textarea", { class: "textarea", rows: 2, placeholder: "Your answer" });
      const send = () => ta.value.trim() && act("answer", { text: ta.value.trim() });
      ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } });
      setTimeout(() => ta.focus(), 50);
      return h("div", { class: "action-card ask" }, h("div", { class: "row" }, icon("chat"), h("strong", {}, "The agent asks")),
        h("div", {}, p.question), ta, h("div", { class: "row" }, h("span", { class: "grow" }), h("button", { class: "btn primary sm", onclick: send }, "Answer")));
    }
    return h("div", { class: "action-card" },
      h("div", { class: "row" }, icon("shield"), h("strong", {}, `Allow ${p.name.replace(/_/g, " ")}?`)),
      p.args && Object.keys(p.args).length ? h("pre", { class: "mono" }, JSON.stringify(p.args, null, 2)) : null,
      h("div", { class: "row" },
        h("button", { class: "btn primary sm", onclick: () => act("decide", { choice: "yes" }) }, "Allow once"),
        h("button", { class: "btn sm", onclick: () => act("decide", { choice: "all" }) }, "Allow for this run"),
        h("span", { class: "grow" }),
        h("button", { class: "btn sm danger", onclick: () => act("decide", { choice: "no" }) }, "Deny")));
  }

  function files() {
    const ops = d.events.filter((e) => e.type === "file_op");
    if (!ops.length) return h("div", { class: "empty" }, icon("file"), h("h3", {}, "No file changes"), h("p", {}, "This run didn't create, move or change any files."));
    const moves = ops.some((e) => e.op === "move" || e.op === "create_folder");
    return h("div", { class: "stack" },
      h("div", { class: "row between" }, h("h2", {}, `${ops.length} file change${ops.length === 1 ? "" : "s"}`),
        moves && !d.undone ? h("button", { class: "btn sm", onclick: async () => {
          if (!(await confirmBox("Undo file changes?", "Moved files go back and empty new folders are removed. New and edited files stay as they are.", "Undo"))) return;
          act("undo");
        } }, icon("undo"), "Undo moves") : d.undone ? h("span", { class: "pill" }, "Undone") : null),
      h("div", { class: "card" }, h("table", { class: "table" }, h("thead", {}, h("tr", {}, h("th", {}, "Change"), h("th", {}, "File"), h("th", {}, "Time"))),
        h("tbody", {}, ops.map((e) => h("tr", {}, h("td", {}, e.op.replace("_", " ")),
          h("td", { class: "mono", style: { wordBreak: "break-all" } }, (e.src ? `${e.src} → ` : "") + (e.dst || "")),
          h("td", { class: "faint" }, (e.time || "").slice(11, 19))))))));
  }

  function speed() {
    const s = d.speed;
    const parts = Object.entries(s.parts).filter(([, v]) => v > 0);
    const max = Math.max(1, ...parts.map(([, v]) => v));
    return h("div", { class: "stack", style: { gap: "18px" } },
      h("div", { class: "card pad stats" },
        stat(dur(s.total_s), "Total"), stat(dur(s.model_s), "Model time"), stat(s.calls, "Model calls"),
        stat(num(s.prompt_tokens), "Tokens read"), stat(num(s.output_tokens), "Tokens written"),
        stat(`${s.write_tps || 0}/s`, "Writing speed"), s.reuse_pct ? stat(`${s.reuse_pct}%`, "Prompt reused") : null,
        s.saved_pct ? stat(`${s.saved_pct}%`, "Saved by Telegram") : null),
      h("div", { class: "card pad stack" }, h("h2", {}, "Where the time went"),
        h("div", { class: "bars" }, parts.map(([k, v]) => h("div", { class: "bar-row" }, h("span", { class: "muted" }, k),
          h("div", { class: "bar-track" }, h("div", { class: "bar-fill", style: { width: `${(v / max) * 100}%` } })), h("span", { class: "num" }, dur(v)))))),
      s.tips.length ? h("div", { class: "card pad stack tight" }, h("h2", {}, "Tips"),
        s.tips.map((t) => h("div", { class: "row small", style: { alignItems: "flex-start" } }, icon("sparkle"), h("span", {}, t)))) : null,
      s.per_call.length ? h("details", { class: "card disclosure" }, h("summary", {}, h("span", {}, "Every model call"), icon("chev", "chev")),
        h("div", { class: "body", style: { overflowX: "auto" } }, h("table", { class: "table" },
          h("thead", {}, h("tr", {}, ["#", "What", "Load", "Read", "Tokens in", "Write", "Tokens out", "tok/s"].map((x, i) => h("th", { class: i > 1 ? "num" : "" }, x)))),
          h("tbody", {}, s.per_call.map((c) => h("tr", {}, h("td", {}, c["#"]), h("td", {}, c.what),
            ...["load s", "read s", "read tokens", "write s", "write tokens", "write tok/s"].map((k) => h("td", { class: "num" }, c[k])))))))) : null);
  }
  const stat = (v, k) => h("div", { class: "stat" }, h("span", { class: "v" }, v), h("span", { class: "k" }, k));

  // ---------------------------------------------------------- follow-up
  function drawFoot() {
    clear(foot);
    if (!d.can_continue || tab !== "chat") return;
    const ta = h("textarea", { rows: 1, placeholder: "Reply to continue this run" });
    const send = async () => { if (ta.value.trim()) { await act("send", { message: ta.value.trim() }); } };
    ta.addEventListener("input", () => grow(ta, 200));
    ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } });
    foot.append(h("div", { class: "composer" }, ta, h("button", { class: "btn primary icon round sm", onclick: send }, icon("send"))));
  }

  // ---------------------------------------------------------- actions + live
  async function act(action, payload = {}) {
    try {
      const r = await post(`/api/runs/${encodeURIComponent(rid)}/${action}`, payload);
      if (action === "undo") toast("Undone");
      if (action === "decide" || action === "answer") pending = null;
      await reload();
      if (["send", "resume"].includes(action)) listen();
      return r;
    } catch (e) { fail(e); }
  }
  async function reload() {
    d = await get(`/api/runs/${encodeURIComponent(rid)}`);
    pending = d.pending;
    render(true);
  }
  function listen() {
    if (es) es.close();
    es = new EventSource(`/api/runs/${encodeURIComponent(rid)}/stream?from=${d.events.length}`);
    es.addEventListener("event", (m) => {
      const { i, e } = JSON.parse(m.data);
      if (i === d.events.length) { d.events.push(e); later(); }
    });
    es.addEventListener("meta", (m) => {
      const x = JSON.parse(m.data);
      const phase = d.relay && d.relay.phase;
      Object.assign(d, { status: x.status, active: x.active, seconds: x.seconds, steps: x.steps, file_changes: x.file_changes,
        verified: x.verified, attempts: x.attempts });
      if (x.relay_phase && d.relay && x.relay_phase !== phase) { reload(); return; }
      pending = x.pending;
      later();
    });
    es.addEventListener("end", () => { es.close(); es = null; reload(); });
    es.onerror = () => { /* the browser retries by itself */ };
  }
  render(true);
  if (d.active) listen();
  return () => es && es.close();
}
