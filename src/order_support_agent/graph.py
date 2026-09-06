import json
import logging
import operator
import time
from typing import Annotated, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph

from src.order_support_agent import MISTRAL_MODEL, TOOL_REGISTRY, TOOLS_SCHEMA, get_client
from src.order_support_agent.agent import SYSTEM_PROMPT
from src.tools.tools import get_order

logger = logging.getLogger("agent.graph")
trace_logger = logging.getLogger("agent.trace")

PERMISSION_GATED_TOOLS = {"cancel_order", "update_shipping_address"}


class AgentState(TypedDict):
    messages: Annotated[list, operator.add]
    iteration_count: int
    trace: Annotated[list, operator.add]
    last_call_signature: tuple | None
    repeat_count: int
    error: str | None


def _emit(event: dict) -> dict:
    """Record one structured trace event (step, latency, outcome) and log it as JSON."""
    trace_logger.info(json.dumps(event, default=str))
    return event


def need_permission(tool_name: str, args: dict) -> bool:
    """True if this tool call must be confirmed by a human before it runs."""
    if tool_name not in PERMISSION_GATED_TOOLS:
        return False
    order = get_order(args.get("order_id", ""))
    return bool(order) and order["status"] == "shipped"


def call_model(state: AgentState, config: RunnableConfig) -> dict:
    client = config.get("configurable", {}).get("client") or get_client()
    step = state["iteration_count"]
    started = time.monotonic()
    response = client.chat_completion(model=MISTRAL_MODEL, messages=state["messages"], tools=TOOLS_SCHEMA, tool_choice="auto")
    latency_ms = round((time.monotonic() - started) * 1000)
    message = response.choices[0].message

    new_message = {"role": "assistant", "content": message.content}
    if message.tool_calls:
        new_message["tool_calls"] = [
            {"id": tc.id, "type": "function",
             "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in message.tool_calls
        ]

    trace_event = _emit({
        "event": "llm_call",
        "step": step,
        "latency_ms": latency_ms,
        "tool_calls_requested": [tc.function.name for tc in (message.tool_calls or [])],
        "has_content": bool(message.content),
    })

    call_signature = tuple(sorted((tc.function.name, tc.function.arguments) for tc in message.tool_calls)) if message.tool_calls else None
    repeat_count = state.get("repeat_count", 0) + 1 if call_signature is not None and call_signature == state.get("last_call_signature") else 1

    if call_signature is not None and repeat_count >= 3:
        content = "I have tried many times, I cannot continue any further."
        _emit({"event": "loop_detected", "step": step, "tool_calls_requested": [tc.function.name for tc in message.tool_calls]})
        return {
            "messages": [{"role": "assistant", "content": content}],
            "iteration_count": step + 1,
            "trace": [trace_event],
            "error": "loop_detected",
        }

    return {
        "messages": [new_message],
        "iteration_count": step + 1,
        "trace": [trace_event],
        "last_call_signature": call_signature,
        "repeat_count": repeat_count,
    }


def call_tool(state: AgentState) -> dict:
    last = state["messages"][-1]
    step = state["iteration_count"]
    tool_messages = []
    trace_events = []
    for tc in last.get("tool_calls", []):
        name = tc["function"]["name"]
        try:
            args = json.loads(tc["function"]["arguments"] or "{}")
        except json.JSONDecodeError:
            args = {}

        logger.info("tool_call name=%s args=%s", name, args)
        started = time.monotonic()

        if need_permission(name, args):
            logger.warning("permission_denied tool=%s args=%s", name, args)
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
            logger.info("tool_result name=%s result=%s", name, result)

        latency_ms = round((time.monotonic() - started) * 1000)
        success = result.get("success", True) if isinstance(result, dict) else True
        error = result.get("error") if isinstance(result, dict) else None
        trace_events.append(_emit({
            "event": "tool_call",
            "step": step,
            "tool": name,
            "args": args,
            "success": success,
            "error": error,
            "latency_ms": latency_ms,
        }))

        tool_messages.append({
            "role": "tool",
            "tool_call_id": tc["id"],
            "name": name,
            "content": json.dumps(result, default=str),
        })

    return {"messages": tool_messages, "trace": trace_events}


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


def run_graph(user_message: str, max_steps: int = 8, client=None, history: list | None = None) -> dict:
    app = build_graph()
    messages = list(history) if history else [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.append({"role": "user", "content": user_message})
    initial_state = {"messages": messages, "iteration_count": 0, "trace": [], "last_call_signature": None, "repeat_count": 0, "error": None}
    try:
        final_state = app.invoke(
            initial_state,
            config={"configurable": {"client": client}, "recursion_limit": max_steps * 2 + 2},
        )
    except GraphRecursionError:
        # ponytail: langgraph doesn't hand back partial state on recursion error, so the
        # trace up to the cutoff is lost here — switch to app.stream() if that's ever needed.
        return {"response": None, "messages": initial_state["messages"], "error": "max_steps_exceeded", "trace": []}

    return {
        "response": final_state["messages"][-1]["content"],
        "messages": final_state["messages"],
        "trace": final_state["trace"],
        "error": final_state.get("error"),
    }


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

    trace_events = {e["event"] for e in result["trace"]}
    assert trace_events == {"llm_call", "tool_call"}
    tool_trace = next(e for e in result["trace"] if e["event"] == "tool_call")
    assert tool_trace["tool"] == "get_order" and tool_trace["success"] is True
    assert all("latency_ms" in e for e in result["trace"])

    class LoopingClient:
        def chat_completion(self, model, messages, tools, tool_choice):
            return chat_response(tool_calls=[tool_call("call_1", "search_knowledge_base", {"query": "x"})])

    loop_result = run_graph("hi", max_steps=10, client=LoopingClient())
    assert loop_result["error"] == "loop_detected"
    assert loop_result["response"] == "I have tried many times, I cannot continue any further."

    class VaryingClient:
        def __init__(self):
            self.calls = 0

        def chat_completion(self, model, messages, tools, tool_choice):
            self.calls += 1
            return chat_response(tool_calls=[tool_call("call_1", "search_knowledge_base", {"query": f"x{self.calls}"})])

    capped_result = run_graph("hi", max_steps=2, client=VaryingClient())
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
