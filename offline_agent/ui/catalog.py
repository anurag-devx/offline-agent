"""Catalog: what every agent and every tool does, in plain words."""
import streamlit as st

from offline_agent.engine.bench import available_agents
from offline_agent.engine.catalog import agent_card, all_tool_cards, latest_bench
from offline_agent.engine.config import load_agent

st.title("📖 Catalog")
st.caption("What each agent and tool does, what it needs, and what it will never do. Built from the code, "
           "so it's always up to date.")
q = st.text_input("Search", placeholder="e.g. pdf, email, website, delete").strip().lower()

tab_agents, tab_tools = st.tabs(["Agents", "Tools"])

with tab_agents:
    for label, path in available_agents().items():
        card = agent_card(load_agent(path), latest_bench(label))
        text = " ".join([card["name"], card["what"], *card["good_for"], *card["examples"], *card["tools"]]).lower()
        if q and q not in text:
            continue
        with st.expander(f"**{label}** · {card['what']}"):
            render_agent = st.container()
            with render_agent:
                if card["good_for"]:
                    st.markdown("✅ **Good for:** " + " · ".join(card["good_for"]))
                if card["not_for"]:
                    st.markdown("⛔ **Not for:** " + " · ".join(card["not_for"]))
                st.markdown(f"🔐 **Needs:** {card['needs']}")
                st.markdown(f"⚙️ **How it works:** {card['mode']}" +
                            (f" · {', '.join(card['extras'])}" if card["extras"] else ""))
                st.markdown("🧰 **Tools:** " + ", ".join(f"`{t}`" for t in card["tools"]))
                if card["examples"]:
                    st.markdown("💬 **Try:**")
                    for e in card["examples"]:
                        st.code(e, language=None)
                st.caption(f"🧪 Test Bench: {card['tested'] or 'not tested yet'} · Model: {card['model']}")
                st.caption("Use it: Studio → Start from Template (or My agents) → pick it.")

with tab_tools:
    for card in all_tool_cards():
        text = " ".join([card["name"], card["what"], card["unlocked_by"], card["safety"]]).lower()
        if q and q not in text:
            continue
        with st.expander(f"`{card['name']}` · {card['what'][:90]}"):
            st.markdown(card["what"])
            st.markdown(f"🔐 **Unlocked by:** {card['unlocked_by']}")
            if card["args"]:
                st.dataframe([{"Input": a["name"], "Type": a["type"],
                               "Required": "yes" if a["required"] else f"no (default {a['default']!r})",
                               "About": a["about"]} for a in card["args"]], hide_index=True)
            if card["safety"]:
                st.markdown(f"🛡 **Safety:** {card['safety']}")
            if card["example"]:
                st.markdown("**Example output:**")
                st.code(card["example"], language=None)
