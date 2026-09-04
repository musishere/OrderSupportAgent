import logging
from datetime import datetime

from src.db.connect_db import get_connection

logger = logging.getLogger("tools")

KNOWLEDGE_BASE = [
    {"topic": "shipping_time", "question": "How long does shipping take?",
     "answer": "Standard shipping takes 3-5 business days after an order ships."},
    {"topic": "cancellation", "question": "Can I cancel my order?",
     "answer": "Orders can be cancelled for free before they ship. Once shipped, cancellation requires a support review."},
    {"topic": "address_change", "question": "Can I change my shipping address?",
     "answer": "You can update your shipping address before an order ships. Changes after shipping are reviewed for fraud prevention."},
    {"topic": "returns", "question": "What is the return policy?",
     "answer": "Items can be returned within 30 days of delivery for a full refund."},
    {"topic": "payment", "question": "What payment methods are accepted?",
     "answer": "We accept all major credit cards, PayPal, and Apple Pay."},
    {"topic": "order_status", "question": "How do I check my order status?",
     "answer": "Ask the support agent for your order ID and we'll look up its current status."},
]


def search_knowledge_base(query: str) -> list[dict]:
    q = query.lower()
    return [entry for entry in KNOWLEDGE_BASE if q in entry["question"].lower() or q in entry["answer"].lower()]


def get_order(order_id: str) -> dict | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def cancel_order(order_id: str, confirmed: bool = False) -> dict:
    conn = get_connection()
    row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    if not row:
        conn.close()
        return {"success": False, "error": "order_not_found"}

    order = dict(row)
    if order["status"] == "cancelled":
        conn.close()
        return {"success": True, "order": order, "message": "already cancelled (no-op)"}
    if order["status"] == "delivered":
        conn.close()
        return {"success": False, "error": "cannot_cancel_delivered_order"}
    if order["status"] == "shipped" and not confirmed:
        conn.close()
        return {"success": False, "error": "requires_confirmation",
                "message": "order already shipped; cancellation requires human confirmation"}

    conn.execute("UPDATE orders SET status = 'cancelled' WHERE order_id = ?", (order_id,))
    conn.commit()
    order["status"] = "cancelled"
    conn.close()
    return {"success": True, "order": order, "message": "order cancelled"}


def update_shipping_address(order_id: str, new_address: str, approved_by: str = "auto") -> dict:
    conn = get_connection()
    row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    if not row:
        conn.close()
        return {"success": False, "error": "order_not_found"}

    order = dict(row)
    if order["status"] in ("delivered", "cancelled"):
        conn.close()
        return {"success": False, "error": f"cannot_modify_{order['status']}_order"}
    if order["shipping_address"] == new_address:
        conn.close()
        return {"success": True, "order": order, "message": "address unchanged (no-op)"}

    conn.execute(
        "INSERT INTO address_change_log (order_id, old_address, new_address, changed_at, approved_by) "
        "VALUES (?, ?, ?, ?, ?)",
        (order_id, order["shipping_address"], new_address, datetime.now().isoformat(timespec="seconds"), approved_by),
    )
    conn.execute("UPDATE orders SET shipping_address = ? WHERE order_id = ?", (new_address, order_id))
    conn.commit()
    order["shipping_address"] = new_address
    conn.close()
    return {"success": True, "order": order, "message": "shipping address updated"}


def send_notification_email(to_email: str, subject: str, body: str) -> dict:
    if not to_email or "@" not in to_email:
        return {"success": False, "error": "invalid_recipient"}
    logger.info("EMAIL to=%s subject=%r body=%r", to_email, subject, body)
    return {"success": True, "error": None}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    assert search_knowledge_base("cancel")

    conn = get_connection()
    sample_order_id = conn.execute("SELECT order_id FROM orders WHERE status = 'processing' LIMIT 1").fetchone()[0]
    shipped_ids = [r[0] for r in conn.execute("SELECT order_id FROM orders WHERE status = 'shipped' LIMIT 2")]
    shipped_order_id, shipped_order_id_2 = shipped_ids[0], shipped_ids[1]
    conn.close()

    order = get_order(sample_order_id)
    assert order and order["order_id"] == sample_order_id

    cancel_result = cancel_order(sample_order_id)
    assert cancel_result["success"] and cancel_result["order"]["status"] == "cancelled"
    idempotent_result = cancel_order(sample_order_id)
    assert idempotent_result["success"] and "no-op" in idempotent_result["message"]

    blocked_result = cancel_order(shipped_order_id)
    assert not blocked_result["success"] and blocked_result["error"] == "requires_confirmation"
    confirmed_result = cancel_order(shipped_order_id, confirmed=True)
    assert confirmed_result["success"] and confirmed_result["order"]["status"] == "cancelled"

    addr_result = update_shipping_address(shipped_order_id_2, "123 New Test St, Testville, TS")
    assert addr_result["success"]

    email_result = send_notification_email("test@example.com", "Order update", "Your order status changed.")
    assert email_result["success"]

    print("OK: all tool self-checks passed")
