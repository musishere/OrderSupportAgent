import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st

from src.order_support_agent.graph import run_graph

st.title("Order Support Agent")

if "history" not in st.session_state:
    st.session_state.history = []

for role, content in st.session_state.history:
    with st.chat_message(role):
        st.markdown(content)

if prompt := st.chat_input("Ask about an order (e.g. 'what's the status of ORD0001?')"):
    st.session_state.history.append(("user", prompt))
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                result = run_graph(prompt)
            except Exception as e:
                result = {"response": None, "error": str(e), "messages": []}

        if result.get("error"):
            st.error(f"Agent error: {result['error']}")
            reply = f"Error: {result['error']}"
        else:
            st.markdown(result["response"])
            tool_steps = [m for m in result["messages"] if m["role"] in ("assistant", "tool")]
            if tool_steps:
                with st.expander("trace"):
                    st.json(tool_steps)
            reply = result["response"]

    st.session_state.history.append(("assistant", reply))
