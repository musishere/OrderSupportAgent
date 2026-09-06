import os

import httpx
import streamlit as st

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")

st.title("Order Support Agent")

if "history" not in st.session_state:
    st.session_state.history = []
if "session_id" not in st.session_state:
    st.session_state.session_id = None

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
                resp = httpx.post(
                    f"{BACKEND_URL}/chat",
                    json={"message": prompt, "session_id": st.session_state.session_id},
                    timeout=60,
                )
                resp.raise_for_status()
                result = resp.json()
                st.session_state.session_id = result.get("session_id")
            except httpx.HTTPError as e:
                result = {"response": None, "error": f"backend unreachable: {e}", "tool_calls": []}

        if result.get("error"):
            st.error(f"Agent error: {result['error']}")
            reply = f"Error: {result['error']}"
        else:
            st.markdown(result["response"])
            if result.get("tool_calls"):
                with st.expander("trace"):
                    st.json(result["tool_calls"])
            reply = result["response"]

    st.session_state.history.append(("assistant", reply))
