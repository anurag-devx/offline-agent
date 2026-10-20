"""
Studio: build an agent in five steps.
  1 Design    settings + permissions (or let your local model draft it)
  2 Preview   exactly what THIS agent can do, a diagram, and a plan for a task (nothing runs)
  3 Validate  automatic checks + a test question
  4 Run       give it a task; watch live; approve actions; answer questions
  5 Deploy    run the saved agent elsewhere
"""
import streamlit as st

from offline_agent.engine import AgentConfig, dry_run, get_manager, is_valid, load_agent, save_agent, validate
from offline_agent.engine import audit, llm
from offline_agent.engine.config import AGENTS_DIR, ROOT, TEMPLATES_DIR, VerifyConfig, list_configs
from offline_agent.engine.paths import is_protected, resolve_folder
from offline_agent.engine.permissions import (ALLOW, ASK, CAPABILITIES, GROUPS, MODE_LABEL, OFF, RISK_ICON,
                                EmailPolicy, FilePolicy, InteractionPolicy, InternetPolicy, MemoryPolicy, Policy)
from offline_agent.engine.planner import capabilities_summary, generate_agent, plan_task, workflow_dot
from offline_agent.engine.tools import tools_for
from offline_agent.ui.common import live_run, render_event

ss = st.session_state
mgr = get_manager()
models = llm.list_models()

# ------------------------------------------------------------------ choose an agent
st.title("🛠 Studio")
c1, c2 = st.columns([1, 3])
source = c1.radio("Start from", ["Template", "My agents"], horizontal=True)
options = list_configs(TEMPLATES_DIR) if source == "Template" else list_configs(AGENTS_DIR)
if source == "Template":
    options = {"Blank agent": None, **options}
choice = c2.selectbox("Agent", list(options)) if options else None
if source == "My agents" and not options:
    c2.info("No saved agents yet. Pick a template, then Save it.")


def load(cfg):
    """Put a config into the form. New widget keys make the form show the new values."""
    ss.base = cfg
    ss.form_id = ss.get("form_id", 0) + 1
    ss.pop("plan", None)


load_key = f"{source}:{choice}"
if ss.get("load_key") != load_key:  # only reload when the selection changes
    ss.load_key = load_key
    path = options.get(choice) if options else None
    load(load_agent(path) if path else AgentConfig())
base, fid = ss.base, ss.form_id
pol = base.permissions


def k(name):
    return f"{name}_{fid}"


def mode_row(cap, current, modes=(OFF, ALLOW, ASK)):
    info = CAPABILITIES[cap]
    a, b = st.columns([2, 5])
    value = a.radio(info["label"], modes, index=modes.index(current) if current in modes else 0,
                    format_func=MODE_LABEL.get, horizontal=True, key=k(cap), label_visibility="collapsed")
    b.markdown(f"{RISK_ICON[info['risk']]} **{info['label']}**: {info['detail']}")
    return value


def lines(text):
    return [x.strip() for x in text.replace(",", "\n").splitlines() if x.strip()]


tabs = st.tabs(["1 · Design", "2 · Preview", "3 · Validate", "4 · Run", "5 · Deploy"])

# ------------------------------------------------------------------ 1. Design
with tabs[0]:
    with st.expander("✨ Describe an agent and let your local model build it"):
        wish = st.text_area("What should the agent do?", key="wish",
                            placeholder="Sort files in a folder I choose into images and documents")
        gen_model = st.selectbox("Model that designs it", models or [base.model], key="gen_model")
        if st.button("Generate agent", disabled=not wish.strip()):
            with st.spinner(f"{gen_model} is designing your agent..."):
                try:
                    generated = generate_agent(wish, gen_model)
                except Exception as e:
                    generated = None
                    st.error(f"Generation failed: {e}. Try again or use a bigger model.")
            if generated:
                audit.log("agent_generated", description=wish, model=gen_model, name=generated.name)
                load(generated)
                st.rerun()
        st.caption("The form below gets filled in. Review it, especially permissions.")

    left, right = st.columns(2)
    with left:
        name = st.text_input("Name", base.name, key=k("name"))
        description = st.text_input("Description", base.description, key=k("desc"))
        model_options = models if base.model in models else [base.model] + models
        model = st.selectbox("Model", model_options, index=model_options.index(base.model), key=k("model"),
                             format_func=lambda m: m if m in models else f"{m} (not installed)")
    with right:
        max_steps = st.slider("Max steps", 1, 100, base.max_steps, key=k("steps"),
                              help="Max model calls per task. Stops endless loops.")
        temperature = st.slider("Temperature", 0.0, 2.0, float(base.temperature), 0.1, key=k("temp"),
                                help="0 = predictable, higher = more creative.")
        think = st.checkbox("Thinking mode (reasoning models; slower but better at hard tasks)",
                            base.think, key=k("think"))
        ctx_options = [4096, 8192, 16384, 32768, 65536, 131072]
        if base.context_length not in ctx_options:
            ctx_options = sorted(ctx_options + [base.context_length])
        context_length = st.select_slider(
            "Context length (tokens)", ctx_options, base.context_length, key=k("ctx"),
            help="How much the model can see at once: instructions + conversation + tool results. Too small "
                 "and it silently forgets its instructions. Bigger uses more memory and is slower.")
    system_prompt = st.text_area("System prompt (the agent's instructions)", base.system_prompt,
                                 height=200, key=k("prompt"))

    st.markdown("#### Permissions")
    st.caption("For each capability: **Off** (the agent can't even see it), **Allow**, or **Ask first** "
               "(the run pauses; you approve once, approve all for this run, or deny). "
               "Folders, sites and limits are enforced in code, not by the prompt.")

    with st.container(border=True):
        st.markdown(f"**{GROUPS['files']}**")
        folders = lines(st.text_area(
            "Folders the agent may use (one per line, subfolders included)", "\n".join(pol.files.folders),
            key=k("folders"), help="`workspace` = this project's workspace folder. Examples: ~/Downloads, "
                                   "~/Documents/site. Leave empty to choose at run time."))
        for f in folders:
            p = resolve_folder(f)
            flag = "⛔ protected, can't be used" if is_protected(p) else ("✅" if p.is_dir() else "❌ not found")
            st.caption(f"{flag} `{p}`")
        ask_other = st.checkbox("Ask me before using any other folder (grant for this run only)",
                                pol.files.ask_for_other_folders, key=k("ask_other"))
        files = FilePolicy(folders=folders, ask_for_other_folders=ask_other)
        for action in ("read", "create", "modify", "move", "delete"):
            setattr(files, action, mode_row(f"files.{action}", getattr(pol.files, action)))
        a, b = st.columns(2)
        types = lines(a.text_input("Only these file types (optional)", ", ".join(pol.files.file_types),
                                   placeholder=".jpg, .png, .pdf", key=k("types")))
        files.file_types = [(t if t.startswith(".") else "." + t).lower() for t in types]
        files.max_changes = int(b.number_input("Max file changes per run", 1, 100000, pol.files.max_changes,
                                               key=k("maxch")))

    with st.container(border=True):
        st.markdown(f"**{GROUPS['internet']}**")
        net = InternetPolicy(read=mode_row("internet.read", pol.internet.read),
                             search=mode_row("internet.search", pol.internet.search))
        if net.read != OFF:
            net.domains = [d.lower().removeprefix("https://").removeprefix("http://").split("/")[0]
                           for d in lines(st.text_area("Allowed sites (one per line, subdomains included)",
                                                       "\n".join(pol.internet.domains), key=k("domains"),
                                                       placeholder="wikipedia.org"))]
            net.other_domains = st.radio("Other sites", ["block", "ask"],
                                         index=1 if pol.internet.other_domains == "ask" else 0, horizontal=True,
                                         format_func={"block": "Block", "ask": "Ask me each time"}.get,
                                         key=k("other"))
        else:
            net.domains, net.other_domains = pol.internet.domains, pol.internet.other_domains

    with st.container(border=True):
        st.markdown(f"**{GROUPS['email']}**")
        mail = EmailPolicy(read=mode_row("email.read", pol.email.read),
                           organize=mode_row("email.organize", pol.email.organize))
        mail.folders = pol.email.folders
        if mail.read != OFF or mail.organize != OFF:
            mail.folders = lines(st.text_input("Only these mail folders (optional, comma separated)",
                                               ", ".join(pol.email.folders), placeholder="INBOX, Receipts",
                                               key=k("mailf")))
            st.caption("Set up your account on the Settings page.")

    with st.container(border=True):
        st.markdown(f"**{GROUPS['memory']}**")
        mem = MemoryPolicy(read=mode_row("memory.read", pol.memory.read),
                           write=mode_row("memory.write", pol.memory.write))
        a, b, c = st.columns(3)
        mem.recall = int(a.number_input("Notes recalled at start", 0, 20, pol.memory.recall, key=k("m_recall"),
                                        help="Relevant notes added when a run starts (0 = only via the recall tool).",
                                        disabled=mem.read == OFF))
        mem.run_summaries = b.checkbox("Save a summary of each run", pol.memory.run_summaries, key=k("m_sum"),
                                       help="Written by code from recorded facts, never by the model.")
        mem.shared = c.checkbox("Use shared memory", pol.memory.shared, key=k("m_shared"),
                                help="Off = this agent has its own memory.")

    with st.container(border=True):
        st.markdown(f"**{GROUPS['interaction']}**")
        talk = InteractionPolicy(ask_user=mode_row("interaction.ask_user", pol.interaction.ask_user, (OFF, ALLOW)))

    with st.container(border=True):
        st.markdown("**⚙️ How it works**")
        mode = st.radio("Mode", ["agent", "rules"], index=1 if base.mode == "rules" else 0, horizontal=True,
                        key=k("mode"), format_func={"agent": "Agent: the model does the work",
                                                    "rules": "Rule: the model writes a rule, code does the work"}.get)
        if mode == "rules":
            st.caption("Rule mode organizes **files** (`~/Downloads · .pdf → all_pdf`) or **email** "
                       "(`INBOX · from \"amazon\" → Receipts`). One model call writes the rule; you approve it with "
                       "the exact list; code moves and checks. Needs Files: Read + Move, or Email: Read + Organize.")
        a, b, c = st.columns(3)
        plan_steps = a.checkbox("Job notes (plan + checklist)", base.plan_steps, key=k("notes"),
                                help="The agent plans steps, ticks them off with a one-line note; code adds evidence. "
                                     "Messages from finished steps are dropped, so the context stays small.",
                                disabled=mode == "rules")
        terse = b.checkbox("Telegram style (short replies)", base.terse, key=k("terse"), disabled=mode == "rules")
        max_reply = int(c.number_input("Max reply tokens (0 = no cap)", 0, 32768, base.max_reply_tokens, step=256,
                                       key=k("maxrep"), help="Caps each model reply. Raise it for agents that "
                                                             "write long files (websites)."))

    with st.container(border=True):
        st.markdown("**🔍 Verification**")
        if mode == "rules":
            st.caption("Rule mode always checks its result with code (no model needed).")
        v_on = st.checkbox("When the agent says it's done, check with a read-only verifier. "
                           "If it's not done, send it back to finish.", base.verify.enabled, key=k("v_on"),
                           disabled=mode == "rules")
        verify_cfg = VerifyConfig(**vars(base.verify))
        verify_cfg.enabled = v_on
        if v_on:
            verify_cfg.criteria = st.text_area(
                "What does 'done' mean? (recommended)", base.verify.criteria, key=k("v_crit"),
                placeholder="No .pdf files remain directly in ~/Downloads; all of them are in ~/Downloads/all_pdf")
            a, b = st.columns(2)
            verify_cfg.max_attempts = int(a.number_input("Max verification rounds (0 = until I press Stop)",
                                                         0, 100, base.verify.max_attempts, key=k("v_max")))
            vm = [""] + models
            verify_cfg.model = b.selectbox("Verifier model", vm, vm.index(base.verify.model) if base.verify.model in vm else 0,
                                           format_func=lambda m: m or "same as agent", key=k("v_model"))

    cfg = AgentConfig(name=name, description=description, model=model, system_prompt=system_prompt,
                      permissions=Policy(files=files, internet=net, email=mail, memory=mem, interaction=talk),
                      max_steps=max_steps, temperature=temperature, think=think,
                      context_length=int(context_length), verify=verify_cfg, mode=mode,
                      plan_steps=plan_steps, terse=terse, max_reply_tokens=max_reply)
    st.caption("**Tools this agent gets:** " + ", ".join(f"`{t}`" for t in tools_for(cfg)))

    if st.button("💾 Save agent", type="primary"):
        path = save_agent(cfg)
        audit.log("agent_saved", agent=cfg.name, path=str(path.relative_to(ROOT)))
        st.success(f"Saved to `{path.relative_to(ROOT)}`. Find it under **My agents**.")
    with st.expander("YAML preview"):
        st.code(cfg.to_yaml(), language="yaml")

checks = validate(cfg)
valid = is_valid(checks)
saved_path = AGENTS_DIR / f"{cfg.slug}.yaml"
is_saved = saved_path.exists() and saved_path.read_text(encoding="utf-8") == cfg.to_yaml()

# ------------------------------------------------------------------ 2. Preview
with tabs[1]:
    st.subheader(f"Preview: {cfg.name}")
    st.caption(f"{cfg.description or 'No description.'}  \n"
               f"Model `{cfg.model}` · up to {cfg.max_steps} steps · "
               + ("saved" if is_saved else "**unsaved changes included**"))
    with st.expander("Instructions this agent follows"):
        st.markdown(cfg.system_prompt)

    allowed, asks, off, notes = capabilities_summary(cfg)
    a, b, c = st.columns(3)
    for col, title, items in ((a, "✅ Does freely", allowed), (b, "✋ Asks you first", asks), (c, "⛔ Cannot", off)):
        with col:
            st.markdown(f"**{title}**")
            for x in items or ["(nothing)"]:
                st.markdown(f"- {x}")
    st.markdown("**Scope and limits**")
    for n in notes:
        st.markdown(f"- {n}")

    st.markdown("**How it works**")
    st.graphviz_chart(workflow_dot(cfg))

    st.divider()
    st.markdown(f"**Plan a task.** {cfg.name} explains how it *would* do it. No tool is run.")
    plan_text = st.text_area("Task", key="plan_task", placeholder="e.g. Sort my Downloads folder")
    if st.button("🗺 Show plan", disabled=not (valid and plan_text.strip())):
        with st.spinner("Planning..."):
            try:
                ss.plan = {"cfg": cfg.to_dict(), "task": plan_text, "plan": plan_task(cfg, plan_text)}
                audit.log("plan_created", agent=cfg.name, task=plan_text)
            except Exception as e:
                st.error(f"Planning failed: {e}")
    saved_plan = ss.get("plan")
    if saved_plan and saved_plan["cfg"] != cfg.to_dict():
        st.caption("The last plan was made for a different version of this agent. Run the plan again.")
    elif saved_plan:
        plan = saved_plan["plan"]
        st.markdown(f"Plan for **{saved_plan['task']}**: *{plan.get('understanding', '')}*")
        icons = {"allowed": "🟢", "asks you": "✋", "blocked": "⛔", "reasoning": "💭", "unknown tool": "❓"}
        for i, s in enumerate(plan.get("steps", []), 1):
            extra = f" (needs **{s['needs']}**)" if s.get("needs") else ""
            st.markdown(f"{i}. {icons.get(s['status'], '')} {s['action']} · `{s['tool']}` · {s['status']}{extra}")
        if any(s["status"] == "blocked" for s in plan.get("steps", [])):
            st.warning("Some steps need permissions this agent doesn't have. "
                       "Change them in Design, or the agent will have to skip those steps.")
        st.caption("A plan is the model's intention, not a guarantee. The real run may differ.")
        if st.button("▶ Run this task"):
            ss.run_pick = mgr.start(cfg, saved_plan["task"]).id
            st.success("Started. Open the **4 · Run** tab to watch it.")
    if not valid:
        st.caption("Fix the ❌ checks in Validate to enable planning.")

# ------------------------------------------------------------------ 3. Validate
with tabs[2]:
    st.subheader(f"Validate: {cfg.name}")
    for ch in checks:
        icon = "✅" if ch["ok"] else ("❌" if ch["level"] == "error" else "⚠️")
        st.markdown(f"{icon} **{ch['check']}**: {ch['detail']}")
    st.divider()
    st.markdown("**Dry run**: one real question. *Ask first* actions are denied and questions get no answer.")
    test = st.text_input("Test question", "What can you help me with?", key="test_q")
    if st.button("▶ Run test", disabled=not valid):
        with st.spinner("Running..."):
            ok, events, secs = dry_run(cfg, test)
        (st.success if ok else st.error)(f"{'Passed' if ok else 'Failed'} in {secs:.1f}s")
        for e in events:
            render_event(e)

# ------------------------------------------------------------------ 4. Run
with tabs[3]:
    st.subheader(f"Run: {cfg.name}")
    task = st.text_area("Task", key="run_task", placeholder="What should the agent do?")
    if st.button("▶ Start run", type="primary", disabled=not (valid and task.strip())):
        ss.run_pick = mgr.start(cfg, task).id  # select the new run below
    if not valid:
        st.warning("This agent has failed checks. See the Validate tab.")
    st.caption("Runs keep going in the background. You can switch pages; all runs are on the **Runs** page.")

    mine = [r for r in mgr.list() if r.agent == cfg.name][:30]
    if mine:
        ids = [r.id for r in mine]
        if ss.get("run_pick") not in ids:
            ss.run_pick = ids[0]  # newest run
        rid = st.selectbox("Run", ids, key="run_pick",
                           format_func=lambda i: f"{i} · {mgr.runs[i].task[:60]}")
        live_run(rid, key="studio")

# ------------------------------------------------------------------ 5. Deploy
with tabs[4]:
    st.subheader(f"Deploy: {cfg.name}")
    rel = saved_path.relative_to(ROOT)
    if not is_saved:
        st.warning("Save the agent in the Design tab first, so the file below matches what you see.")
    st.markdown("An agent is just its YAML file. Anything that can read the file can run the agent.")
    st.markdown("**1. In this app**: the Run tab, tracked on the Runs page.")
    st.markdown("**2. In the terminal** (approvals and questions are asked in the terminal, also recorded):")
    st.code(f"offline-agent run {saved_path}", language="bash")
    st.markdown("**3. In your own Python code:**")
    st.code("from offline_agent.engine import Agent, load_agent\n\n"
            f'agent = Agent(load_agent("{rel}"))\n'
            'print(agent.ask("Hello!"))', language="python")
    st.markdown("**4. Share it**: send the YAML file to anyone running this project.")
    st.download_button("⬇ Download YAML", cfg.to_yaml(), file_name=f"{cfg.slug}.yaml")
