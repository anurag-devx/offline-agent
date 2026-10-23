// library.js: Catalog, Models, Memory and Workspace, as tabs of one page.
import { TOKEN, ago, api, bytes, clear, confirmBox, fail, field, get, h, icon, initials, input, post, select, toast } from "./core.js";

const TABS = [["catalog", "Catalog", "book"], ["models", "Models", "cpu"], ["memory", "Memory", "brain"], ["workspace", "Workspace", "folder"]];

export async function libraryPage(main, tab) {
  const body = h("div", {});
  main.append(h("div", { class: "page wide" },
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Library"),
      h("p", {}, "What agents and tools can do, the models on this computer, what agents remember, and their workspace."))),
    h("div", { class: "tabs" }, TABS.map(([k, l, ic]) => h("button", { class: tab === k ? "on" : "", onclick: () => (location.hash = `#/library/${k}`) }, icon(ic), l))),
    body));
  const fn = { catalog, models, memory, workspace }[tab] || catalog;
  return fn(body);
}

// ---------------------------------------------------------------- catalog
async function catalog(root) {
  const data = await get("/api/catalog");
  let q = "";
  const list = h("div", { class: "stack" });
  root.append(h("input", { class: "input", placeholder: "Search agents and tools", style: { maxWidth: "360px", marginBottom: "18px" },
    oninput: (e) => { q = e.target.value.toLowerCase(); draw(); } }), list);
  function draw() {
    clear(list);
    const agents = [...data.agents.mine, ...data.agents.templates].filter((a) => !a.error && (!q || JSON.stringify(a).toLowerCase().includes(q)));
    const tools = data.tools.filter((t) => !q || JSON.stringify(t).toLowerCase().includes(q));
    list.append(h("div", { class: "section-title" }, h("h2", {}, "Agents"), h("span", { class: "faint small" }, agents.length)));
    list.append(h("div", { class: "grid", style: { gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))" } }, agents.map((a) =>
      h("div", { class: "card pad stack tight" },
        h("div", { class: "row" }, h("span", { class: "avatar" }, initials(a.name)), h("div", { class: "grow" }, h("h3", {}, a.name),
          h("div", { class: "tiny faint" }, a.mode)), h("a", { class: "btn sm", href: `#/agents/${a.id}` }, "Open")),
        h("div", { class: "small muted" }, a.what),
        a.good_for.length ? h("div", { class: "small" }, h("span", { class: "eyebrow" }, "Good for  "), a.good_for.join(" · ")) : null,
        a.not_for.length ? h("div", { class: "small" }, h("span", { class: "eyebrow" }, "Not for  "), a.not_for.join(" · ")) : null,
        h("div", { class: "small" }, h("span", { class: "eyebrow" }, "Needs  "), a.needs),
        a.tested ? h("div", { class: "tiny faint" }, a.tested) : null))));
    list.append(h("div", { class: "section-title" }, h("h2", {}, "Tools"), h("span", { class: "faint small" }, tools.length)));
    list.append(h("div", { class: "card" }, tools.map((t, i) => h("details", { class: "disclosure", style: { borderTop: i ? "1px solid var(--border)" : 0 } },
      h("summary", {}, h("code", {}, t.name), h("span", { class: "small muted ellipsis grow", style: { fontWeight: 400 } }, t.what.split("\n")[0]),
        h("span", { class: "chip" }, t.unlocked_by), icon("chev", "chev")),
      h("div", { class: "body stack tight small" },
        h("div", { style: { whiteSpace: "pre-wrap" } }, t.what),
        t.args.length ? h("table", { class: "table" }, h("tbody", {}, t.args.map((a) => h("tr", {},
          h("td", { class: "mono" }, a.name + (a.required ? "" : "?")), h("td", { class: "faint" }, a.type), h("td", {}, a.about,
            a.default !== null && a.default !== "" ? h("span", { class: "faint" }, ` (default ${a.default})`) : null))))) : null,
        t.safety ? h("div", {}, h("span", { class: "eyebrow" }, "Safety  "), t.safety) : null,
        t.example ? h("pre", { class: "code-view", style: { padding: "8px 12px" } }, t.example) : null)))));
  }
  draw();
}

// ---------------------------------------------------------------- models
async function models(root) {
  const data = await get("/api/models");
  if (!data.running) {
    root.append(h("div", { class: "banner bad" }, icon("alert"), "Ollama isn't running. Open the Ollama app, then reload this page."));
    return;
  }
  const rows = data.models;
  let pullName = "";
  const progress = h("div", { class: "stack tight hidden" });
  const pullBtn = h("button", { class: "btn primary", onclick: () => pull() }, icon("download"), "Download");
  function pull() {
    const name = pullName.trim();
    if (!name) return;
    pullBtn.disabled = true;
    const bar = h("div", { style: { width: "0%" } });
    const label = h("div", { class: "small muted" }, "Starting…");
    clear(progress).append(label, h("div", { class: "progress" }, bar));
    progress.classList.remove("hidden");
    const es = new EventSource(`/api/models/pull?name=${encodeURIComponent(name)}&token=${encodeURIComponent(TOKEN)}`);
    es.addEventListener("progress", (m) => {
      const p = JSON.parse(m.data);
      label.textContent = p.status + (p.fraction ? ` · ${Math.round(p.fraction * 100)}%` : "");
      if (p.fraction) bar.style.width = `${Math.round(p.fraction * 100)}%`;
    });
    es.addEventListener("end", (m) => {
      es.close();
      const r = JSON.parse(m.data);
      if (r.ok) { toast(`${name} is ready`); location.reload(); } else { label.textContent = `Download failed: ${r.error}`; pullBtn.disabled = false; }
    });
    es.onerror = () => { es.close(); pullBtn.disabled = false; label.textContent = "The download stopped."; };
  }
  root.append(
    h("div", { class: "card" }, h("table", { class: "table" },
      h("thead", {}, h("tr", {}, ["Model", "Size", "Parameters", "Quantization", "Can do", ""].map((x) => h("th", {}, x)))),
      h("tbody", {}, rows.map((m) => h("tr", {},
        h("td", {}, h("strong", {}, m.name), h("div", { class: "tiny faint" }, m.family)),
        h("td", {}, `${m.size_gb} GB`), h("td", {}, m.parameters), h("td", {}, m.quantization),
        h("td", {}, h("div", { class: "row wrap", style: { gap: "4px" } }, m.capabilities.split(", ").filter(Boolean).map((c) =>
          h("span", { class: `chip ${c === "tools" ? "on" : ""}` }, c)))),
        h("td", { class: "num" }, h("button", { class: "btn ghost sm icon", title: "Remove", onclick: async () => {
          if (!(await confirmBox(`Remove ${m.name}?`, `This frees ${m.size_gb} GB. You can download it again later.`, "Remove"))) return;
          try { await api("DELETE", `/api/models/${encodeURIComponent(m.name)}`, {}); toast(`Removed ${m.name}`); location.reload(); } catch (e) { fail(e); }
        } }, icon("trash")))))))),
    h("div", { class: "tiny faint", style: { margin: "8px 4px 24px" } }, "Agents need a model that can use ", h("strong", {}, "tools"),
      ". “thinking” models support Thinking mode, “vision” models can read images (for Relay's visual review)."),
    h("div", { class: "fields" },
      h("div", { class: "card pad stack" }, h("h2", {}, "Download"),
        h("div", { class: "small muted" }, "From the ", h("a", { href: "https://ollama.com/library", target: "_blank", rel: "noopener" }, "Ollama library"),
          ", e.g. gemma4:e4b or qwen3.5:9b."),
        h("div", { class: "row" }, input("", (v) => (pullName = v), { placeholder: "model:tag", onkeydown: (e) => e.key === "Enter" && pull() }), pullBtn),
        progress),
      importCard()));
}
function importCard() {
  let folder = "~/Downloads", found = null, pick = "", name = "";
  const out = h("div", { class: "stack tight" });
  const card = h("div", { class: "card pad stack" }, h("h2", {}, "Import a .gguf file"),
    h("div", { class: "small muted" }, "A model file on this computer, e.g. your Unsloth fine-tune. Ollama copies it; the original stays put."),
    h("div", { class: "row" }, input(folder, (v) => (folder = v)), h("button", { class: "btn", onclick: async () => {
      try { found = (await post("/api/models/find", { folder })).files; draw(); } catch (e) { fail(e); }
    } }, icon("search"), "Find")), out);
  function draw() {
    clear(out);
    if (!found) return;
    if (!found.length) { out.append(h("div", { class: "small muted" }, "No .gguf files there (looked 4 folders deep).")); return; }
    pick = pick || found[0].path;
    name = name || pick.split(/[\\/]/).pop().toLowerCase().replace(/\.gguf$/, "").replace(/_/g, "-").slice(0, 40);
    out.append(select(found.map((f) => [f.path, `${f.path.split(/[\\/]/).pop()} · ${f.size_gb} GB`]), pick, (v) => { pick = v; name = ""; draw(); }),
      field("Name in Ollama", input(name, (v) => (name = v))),
      h("button", { class: "btn primary", onclick: async (e) => {
        e.target.disabled = true; e.target.textContent = "Importing…";
        try {
          const r = await post("/api/models/import", { path: pick, name });
          r.ok ? toast(`Imported as ${name}`) : fail(new Error(r.output || "Import failed"));
          if (r.ok && !r.capabilities.includes("tools")) toast("This model can't use tools, so it can chat but not be an agent.", "bad");
        } catch (err) { fail(err); }
        e.target.disabled = false; e.target.textContent = "Import";
      } }, "Import"));
  }
  return card;
}

// ---------------------------------------------------------------- memory
async function memory(root, scope = "", q = "") {
  const data = await get(`/api/memory?scope=${encodeURIComponent(scope)}&q=${encodeURIComponent(q)}`);
  let note = "";
  clear(root).append(
    h("div", { class: "banner info" }, icon("info"), h("div", {},
      data.semantic ? `Search by meaning is on (${data.embed_model}).` : h("span", {}, "Keyword search only. For search by meaning: ", h("code", {}, `ollama pull ${data.embed_model}`)),
      " Notes are information for agents, never instructions.")),
    h("div", { class: "row", style: { marginBottom: "14px", gap: "10px" } },
      h("div", { style: { width: "220px" } }, select(data.scopes.map((s) => [s, s === "shared" ? "Shared memory" : s]), data.scope, (v) => memory(root, v, ""))),
      h("div", { class: "grow" }, input(q, () => {}, { placeholder: "Search notes", onkeydown: (e) => e.key === "Enter" && memory(root, data.scope, e.target.value) }))),
    h("div", { class: "card" },
      h("div", { class: "row", style: { padding: "12px 16px", borderBottom: "1px solid var(--border)" } },
        h("div", { class: "grow" }, input("", (v) => (note = v), { placeholder: "Add a note, e.g. PDFs from Downloads go to ~/Downloads/all_pdf",
          onkeydown: (e) => e.key === "Enter" && add() })),
        h("button", { class: "btn", onclick: () => add() }, icon("plus"), "Add")),
      data.rows.length ? data.rows.map((r) => noteRow(r)) : h("div", { class: "empty small" }, q ? "Nothing matches." : "No notes yet. Turn on Memory for an agent under Access.")));
  async function add() {
    if (!note.trim()) return;
    try { await post("/api/memory", { scope: data.scope, text: note }); memory(root, data.scope, q); } catch (e) { fail(e); }
  }
  function noteRow(r) {
    const text = h("div", { class: "grow", contenteditable: "true", spellcheck: "false", style: { outline: "none" },
      onblur: async (e) => { const v = e.target.textContent.trim(); if (v && v !== r.text) { await api("PUT", `/api/memory/${r.id}`, { text: v }).catch(fail); toast("Saved"); } } }, r.text);
    return h("div", { class: "row", style: { padding: "12px 16px", borderTop: "1px solid var(--border)", alignItems: "flex-start" } },
      h("span", { class: "chip", style: { marginTop: "1px" } }, r.kind), text,
      r.score !== undefined ? h("span", { class: "tiny faint" }, `${Math.round(r.score * 100)}%`) : null,
      h("span", { class: "tiny faint", style: { whiteSpace: "nowrap" } }, ago(r.created)),
      h("button", { class: "btn ghost sm icon", title: "Delete", onclick: async () => {
        if (!(await confirmBox("Delete note?", r.text, "Delete"))) return;
        await api("DELETE", `/api/memory/${r.id}`, {}).catch(fail); memory(root, data.scope, q);
      } }, icon("trash")));
  }
}

// ---------------------------------------------------------------- workspace
async function workspace(root) {
  const data = await get("/api/workspace");
  let pick = null, view = "preview";
  const tree = h("div", { class: "file-tree" });
  const pane = h("div", { class: "grow", style: { minWidth: 0 } });
  const upload = h("input", { type: "file", multiple: true, class: "hidden", onchange: async (e) => {
    const files = await Promise.all([...e.target.files].map((f) => new Promise((res) => {
      const rd = new FileReader();
      rd.onload = () => res({ name: f.name, data: String(rd.result).split(",")[1] });
      rd.readAsDataURL(f);
    })));
    try { const r = await post("/api/workspace/upload", { files }); toast(`Added ${r.saved.length} file${r.saved.length === 1 ? "" : "s"}`); location.reload(); } catch (err) { fail(err); }
  } });
  root.append(
    h("div", { class: "row", style: { marginBottom: "14px" } }, h("span", { class: "small muted grow mono ellipsis" }, data.root),
      upload, h("button", { class: "btn", onclick: () => upload.click() }, icon("upload"), "Add files"),
      h("a", { class: "btn", href: "/api/workspace/zip" }, icon("download"), "Download all")),
    data.files.length ? h("div", { class: "row", style: { alignItems: "flex-start", gap: "18px" } },
      h("div", { class: "card", style: { width: "300px", padding: "8px", maxHeight: "720px", overflow: "auto", flex: "none" } }, tree), pane)
      : h("div", { class: "card empty" }, icon("folder"), h("h3", {}, "The workspace is empty"), h("p", {}, "Agents can only read and write here. Add files, or let an agent build something.")));
  function drawTree() {
    clear(tree);
    let dir = null;
    const pages = data.files.filter((f) => /\.html?$/i.test(f.path));
    for (const f of data.files) {
      const parts = f.path.split("/");
      const d = parts.slice(0, -1).join("/");
      if (d !== dir) { dir = d; if (d) tree.append(h("div", { class: "dir ellipsis", title: d }, d)); }
      tree.append(h("div", { class: `f ${pick === f.path ? "on" : ""}`, onclick: () => { pick = f.path; view = /\.html?$/i.test(f.path) ? "preview" : "source"; drawTree(); show(); } },
        icon(/\.html?$/i.test(f.path) ? "globe" : /\.(png|jpe?g|gif|svg|webp)$/i.test(f.path) ? "eye" : "file"),
        h("span", { class: "ellipsis grow" }, parts[parts.length - 1]), h("span", { class: "tiny faint" }, bytes(f.size))));
    }
    if (!pick) { pick = (pages[pages.length - 1] || data.files[0]).path; drawTree(); show(); }
  }
  async function show() {
    clear(pane);
    const url = `/ws/${pick.split("/").map(encodeURIComponent).join("/")}`;
    const isPage = /\.html?$/i.test(pick), isImg = /\.(png|jpe?g|gif|svg|webp)$/i.test(pick);
    pane.append(h("div", { class: "row", style: { marginBottom: "10px" } }, h("strong", { class: "grow ellipsis mono small" }, pick),
      isPage ? h("div", { class: "seg" }, [["preview", "Preview"], ["source", "Source"]].map(([k, l]) =>
        h("button", { class: view === k ? "on" : "", onclick: () => { view = k; show(); } }, l))) : null,
      h("a", { class: "btn sm", href: url, target: "_blank", rel: "noopener" }, icon("external"), "Open")));
    if (isPage && view === "preview") pane.append(h("iframe", { class: "preview-frame", src: url, sandbox: "allow-scripts allow-forms allow-modals" }));
    else if (isImg) pane.append(h("div", { class: "card pad", style: { textAlign: "center" } }, h("img", { src: url, style: { maxWidth: "100%", maxHeight: "600px" } })));
    else {
      try { const t = await get(`/api/workspace/text?path=${encodeURIComponent(pick)}`); pane.append(h("pre", { class: "code-view" }, t.text)); }
      catch (e) { pane.append(h("div", { class: "muted" }, e.message)); }
    }
  }
  if (data.files.length) drawTree();
}
