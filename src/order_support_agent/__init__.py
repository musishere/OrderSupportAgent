import os

from huggingface_hub import InferenceClient

from src.tools.tools import (
    cancel_order,
    get_order,
    search_knowledge_base,
    send_notification_email,
    update_shipping_address,
)

HF_MODEL = os.environ.get("HF_MODEL", "meta-llama/Llama-3.3-70B-Instruct")


def get_client() -> InferenceClient:
    return InferenceClient(model=HF_MODEL, token=os.environ.get("HF_TOKEN"))


# OpenAI-style function schemas — harness-controlled fields (confirmed, approved_by)
# are intentionally left out so the model can't self-approve a risky action.
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": "Search the support knowledge base for policy/FAQ answers (shipping, returns, cancellation, etc).",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "search text"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_order",
            "description": "Look up an order by its ID.",
            "parameters": {
                "type": "object",
                "properties": {"order_id": {"type": "string"}},
                "required": ["order_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_order",
            "description": "Cancel an order. Fails with 'requires_confirmation' if the order has already shipped.",
            "parameters": {
                "type": "object",
                "properties": {"order_id": {"type": "string"}},
                "required": ["order_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_shipping_address",
            "description": "Update the shipping address on an order that hasn't been delivered or cancelled yet.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string"},
                    "new_address": {"type": "string"},
                },
                "required": ["order_id", "new_address"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_notification_email",
            "description": "Send a notification email to a customer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to_email": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["to_email", "subject", "body"],
            },
        },
    },
]

TOOL_REGISTRY = {
    "search_knowledge_base": search_knowledge_base,
    "get_order": get_order,
    "cancel_order": cancel_order,
    "update_shipping_address": update_shipping_address,
    "send_notification_email": send_notification_email,
}


def main() -> None:
    print(f"HF client ready for model={HF_MODEL}, {len(TOOLS_SCHEMA)} tools registered")


if __name__ == "__main__":
    main()
