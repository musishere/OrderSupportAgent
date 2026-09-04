import json

from src.order_support_agent import TOOL_REGISTRY, TOOLS_SCHEMA, get_client

SYSTEM_PROMPT = (
    "You are an order support agent. Use the available tools to look up orders, "
    "cancel them, update shipping addresses, search the knowledge base, and send "
    "notification emails. Stay within order support scope."
)


def run_agent(user_message: str, max_steps: int = 8, client=None) -> dict:
    client = client or get_client()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]
    trace = []

    for step in range(max_steps):
        response = client.chat_completion(messages=messages, tools=TOOLS_SCHEMA, tool_choice="auto")
        message = response.choices[0].message

        if not message.tool_calls:
            messages.append({"role": "assistant", "content": message.content})
            return {"response": message.content, "messages": messages, "trace": trace}

        messages.append({
            "role": "assistant",
            "content": message.content,
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in message.tool_calls
            ],
        })

        for tc in message.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            fn = TOOL_REGISTRY.get(name)
            if fn is None:
                result = {"success": False, "error": f"unknown_tool:{name}"}
            else:
                try:
                    result = fn(**args)
                except TypeError as e:
                    result = {"success": False, "error": f"bad_arguments:{e}"}

            trace.append({"step": step, "tool": name, "args": args, "result": result})
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "name": name,
                "content": json.dumps(result, default=str),
            })

    return {"response": None, "messages": messages, "trace": trace, "error": "max_steps_exceeded"}


if __name__ == "__main__":
    from types import SimpleNamespace

    from src.db.connect_db import get_connection

    conn = get_connection()
    order_id = conn.execute("SELECT order_id FROM orders LIMIT 1").fetchone()[0]
    conn.close()

    def tool_call(call_id, name, arguments):
        return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=json.dumps(arguments)))

    def chat_response(content=None, tool_calls=None):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls))])

    class FakeClient:
        def __init__(self):
            self.calls = 0

        def chat_completion(self, messages, tools, tool_choice):
            self.calls += 1
            if self.calls == 1:
                return chat_response(tool_calls=[tool_call("call_1", "get_order", {"order_id": order_id})])
            return chat_response(content=f"Your order {order_id} was found.")

    result = run_agent(f"What's the status of order {order_id}?", client=FakeClient())
    assert result["response"] == f"Your order {order_id} was found."
    assert result["trace"][0]["tool"] == "get_order"
    assert result["trace"][0]["result"]["order_id"] == order_id

    class UnknownToolClient:
        def chat_completion(self, messages, tools, tool_choice):
            return chat_response(tool_calls=[tool_call("call_1", "delete_everything", {})])

    class LoopingClient:
        def chat_completion(self, messages, tools, tool_choice):
            return chat_response(tool_calls=[tool_call("call_1", "search_knowledge_base", {"query": "x"})])

    unknown_result = run_agent("hi", max_steps=1, client=UnknownToolClient())
    assert unknown_result["trace"][0]["result"]["error"] == "unknown_tool:delete_everything"

    capped_result = run_agent("hi", max_steps=2, client=LoopingClient())
    assert capped_result["error"] == "max_steps_exceeded"
    assert len(capped_result["trace"]) == 2

    print("OK: agent loop self-checks passed")
