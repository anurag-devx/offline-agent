// settings.js: email account, appearance, privacy, and where things are stored.
import { fail, field, get, h, icon, input, post, seg, toast } from "./core.js";
import { setTheme } from "./app.js";

export async function settingsPage(main) {
  const s = await get("/api/settings");
  const mail = { imap_host: s.email.imap_host, address: s.email.address, password: "" };
  const result = h("span", { class: "small" });
  const theme = (() => { try { return localStorage.getItem("oa-theme") || "system"; } catch (e) { return "system"; } })();
  main.append(h("div", { class: "page" },
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Settings"))),
    h("div", { class: "stack", style: { gap: "16px", maxWidth: "760px" } },
      h("div", { class: "card" }, h("div", { class: "card-head" }, icon("mail"), h("h2", {}, "Email account")),
        h("div", { class: "card-body stack" },
          h("div", { class: "small muted" }, "For email agents. With Gmail, turn on 2-Step Verification, then create an ",
            h("a", { href: "https://myaccount.google.com/apppasswords", target: "_blank", rel: "noopener" }, "app password"),
            " and paste it here (not your normal password). You can revoke it any time."),
          h("div", { class: "fields" },
            field("IMAP server", input(mail.imap_host, (v) => (mail.imap_host = v))),
            field("Email address", input(mail.address, (v) => (mail.address = v), { type: "email" })),
            field("App password", input("", (v) => (mail.password = v), { type: "password", placeholder: s.email.saved ? "Saved · leave empty to keep" : "" }))),
          h("div", { class: "row" },
            h("button", { class: "btn primary", onclick: async () => { try { await post("/api/settings/email", mail); toast("Saved"); } catch (e) { fail(e); } } }, "Save"),
            h("button", { class: "btn", onclick: async () => {
              result.textContent = "Connecting…"; result.style.color = "";
              const r = await post("/api/settings/email/test").catch((e) => ({ ok: false, error: e.message }));
              result.textContent = r.ok ? `Connected · ${r.folders} folders` : `Couldn't connect: ${r.error}`;
              result.style.color = r.ok ? "var(--ok)" : "var(--bad)";
            } }, "Test connection"), result),
          h("div", { class: "tiny faint" }, `Stored only on this computer, in ${s.cred_path}, readable only by your user. Never in the project folder.`))),
      h("div", { class: "card" }, h("div", { class: "card-head" }, icon("sun"), h("h2", { class: "grow" }, "Appearance"),
        seg([["system", "System"], ["light", "Light"], ["dark", "Dark"]], theme, (v) => { setTheme(v); window.dispatchEvent(new HashChangeEvent("hashchange")); }))),
      h("div", { class: "card" }, h("div", { class: "card-head" }, icon("shield"), h("h2", {}, "What leaves your computer")),
        h("div", { class: "card-body stack tight small" }, [
          ["Your prompts and data never go to an AI company.", "The model runs in Ollama on this machine."],
          ["Internet:", "only agents with an internet permission, only to the sites you list or approve during a run. Every request is recorded; redirects to other sites are blocked. What's in an address (e.g. a search) reaches that site, so use Ask first to review each one."],
          ["Email:", "only between this computer and your mail server. No agent can send or delete email."],
          ["Files:", "only the folders each agent lists, or ones you grant during a run. Credential folders (~/.ssh, ~/.aws, Keychains…) and this app's own code and records are always blocked. Delete goes to the Trash; every change is logged; moves can be undone."],
          ["This Studio:", "listens only on this computer (127.0.0.1) and only accepts changes from its own page."],
        ].map(([a, b]) => h("div", {}, h("strong", {}, a), " ", h("span", { class: "muted" }, b))))),
      h("div", { class: "card" }, h("div", { class: "card-head" }, icon("folder"), h("h2", {}, "Where things are")),
        h("div", { class: "card-body stack tight small" },
          h("div", {}, h("span", { class: "muted" }, "Your data: "), h("code", {}, s.root)),
          h("div", {}, h("span", { class: "muted" }, "Workspace: "), h("code", {}, s.workspace)),
          h("div", {}, h("span", { class: "muted" }, "Version: "), s.version),
          h("div", { class: "faint" }, "Set OFFLINE_AGENT_HOME to move your data. The classic Streamlit Studio is still available: offline-agent studio --classic."))))));
  return null;
}
