import json
import operator
from typing import Annotated, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph

from src.order_support_agent import MISTRAL_MODEL, TOOL_REGISTRY, TOOLS_SCHEMA, get_client
from src.order_support_agent.agent import SYSTEM_PROMPT
from src.tools.tools import get_order

PERMISSION_GATED_TOOLS = {"cancel_order", "update_shipping_address"}


class AgentState(TypedDict):
    messages: Annotated[list, operator.add]
    iteration_count: int


def need_permission(tool_name: str, args: dict) -> bool:
    """True if this tool call must be confirmed by a human before it runs."""
    if tool_name not in PERMISSION_GATED_TOOLS:
        return False
    order = get_order(args.get("order_id", ""))
    return bool(order) and order["status"] == "shipped"


def call_model(state: AgentState, config: RunnableConfig) -> dict:
    client = config.get("configurable", {}).get("client") or get_client()
    response = client.chat_completion(model=MISTRAL_MODEL, messages=state["messages"], tools=TOOLS_SCHEMA, tool_choice="auto")
    message = response.choices[0].message

    new_message = {"role": "assistant", "content": message.content}
    if message.tool_calls:
        new_message["tool_calls"] = [
            {"id": tc.id, "type": "function",
             "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in message.tool_calls
        ]

    return {"messages": [new_message], "iteration_count": state["iteration_count"] + 1}


def call_tool(state: AgentState) -> dict:
    last = state["messages"][-1]
    tool_messages = []
    for tc in last.get("tool_calls", []):
        name = tc["function"]["name"]
        try:
            args = json.loads(tc["function"]["arguments"] or "{}")
        except json.JSONDecodeError:
            args = {}

        if need_permission(name, args):
            result = {"success": False, "error": "requires_confirmation",
                      "message": f"{name} on a shipped order requires human confirmation before it can run."}
        else:
            fn = TOOL_REGISTRY.get(name)
            if fn is None:
                result = {"success": False, "error": f"unknown_tool:{name}"}
            else:
                try:
                    result = fn(**args)
                except TypeError as e:
                    result = {"success": False, "error": f"bad_arguments:{e}"}

        tool_messages.append({
            "role": "tool",
            "tool_call_id": tc["id"],
            "name": name,
            "content": json.dumps(result, default=str),
        })

    return {"messages": tool_messages}


def route_after_model(state: AgentState) -> str:
    return "call_tool" if state["messages"][-1].get("tool_calls") else END


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("call_model", call_model)
    graph.add_node("call_tool", call_tool)
    graph.add_edge(START, "call_model")
    graph.add_conditional_edges("call_model", route_after_model, {"call_tool": "call_tool", END: END})
    graph.add_edge("call_tool", "call_model")
    return graph.compile()


def run_graph(user_message: str, max_steps: int = 8, client=None) -> dict:
    app = build_graph()
    initial_state = {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        "iteration_count": 0,
    }
    try:
        final_state = app.invoke(
            initial_state,
            config={"configurable": {"client": client}, "recursion_limit": max_steps * 2 + 2},
        )
    except GraphRecursionError:
        return {"response": None, "messages": initial_state["messages"], "error": "max_steps_exceeded"}

    return {"response": final_state["messages"][-1]["content"], "messages": final_state["messages"]}


if __name__ == "__main__":
    from types import SimpleNamespace

    from src.db.connect_db import get_connection

    conn = get_connection()
    order_id = conn.execute("SELECT order_id FROM orders LIMIT 1").fetchone()[0]
    shipped_order = conn.execute("SELECT order_id, shipping_address FROM orders WHERE status = 'shipped' LIMIT 1").fetchone()
    shipped_order_id, shipped_order_address = shipped_order
    conn.close()

    def tool_call(call_id, name, arguments):
        return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=json.dumps(arguments)))

    def chat_response(content=None, tool_calls=None):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls))])

    class FakeClient:
        def __init__(self):
            self.calls = 0

        def chat_completion(self, model, messages, tools, tool_choice):
            self.calls += 1
            if self.calls == 1:
                return chat_response(tool_calls=[tool_call("call_1", "get_order", {"order_id": order_id})])
            return chat_response(content=f"Your order {order_id} was found.")

    result = run_graph(f"What's the status of order {order_id}?", client=FakeClient())
    assert result["response"] == f"Your order {order_id} was found."
    tool_msgs = [m for m in result["messages"] if m["role"] == "tool"]
    assert tool_msgs and json.loads(tool_msgs[0]["content"])["order_id"] == order_id

    class LoopingClient:
        def chat_completion(self, model, messages, tools, tool_choice):
            return chat_response(tool_calls=[tool_call("call_1", "search_knowledge_base", {"query": "x"})])

    capped_result = run_graph("hi", max_steps=2, client=LoopingClient())
    assert capped_result["error"] == "max_steps_exceeded"

    assert need_permission("update_shipping_address", {"order_id": shipped_order_id}) is True
    assert need_permission("get_order", {"order_id": shipped_order_id}) is False

    class AddressChangeClient:
        def __init__(self):
            self.calls = 0

        def chat_completion(self, model, messages, tools, tool_choice):
            self.calls += 1
            if self.calls == 1:
                return chat_response(tool_calls=[tool_call(
                    "call_1", "update_shipping_address",
                    {"order_id": shipped_order_id, "new_address": "999 Hijacked Ave, Nowhere, XX"},
                )])
            return chat_response(content="That order has already shipped, so I can't change the address without confirmation.")

    gated_result = run_graph("please change my shipping address", client=AddressChangeClient())
    tool_msgs = [m for m in gated_result["messages"] if m["role"] == "tool"]
    assert json.loads(tool_msgs[0]["content"])["error"] == "requires_confirmation"

    unchanged_order = get_order(shipped_order_id)
    assert unchanged_order["shipping_address"] == shipped_order_address

    print("OK: langgraph self-checks passed")
