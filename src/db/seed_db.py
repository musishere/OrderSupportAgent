import random
from datetime import datetime, timedelta

from connect_db import get_connection

random.seed(42)

FIRST_NAMES = ["Ayesha", "Bilal", "Carmen", "Derek", "Elena", "Farhan", "Grace", "Hassan",
               "Ines", "Jamal", "Kavya", "Liam", "Maria", "Noah", "Omar", "Priya", "Quinn", "Rania"]
LAST_NAMES = ["Khan", "Silva", "Novak", "Brown", "Ahmed", "Garcia", "Chen", "Malik",
              "Patel", "Ortiz", "Nguyen", "Rossi", "Baig", "Fischer", "Lopez", "Yusuf"]
CITIES = ["Karachi, PK", "Austin, TX", "Toronto, CA", "Berlin, DE", "Lahore, PK",
          "Chicago, IL", "Manchester, UK", "Dubai, AE", "Seattle, WA", "Madrid, ES"]
STATUSES = ["processing", "shipped", "delivered", "cancelled"]
STATUS_WEIGHTS = [0.25, 0.25, 0.35, 0.15]


def rand_date(days_back_min, days_back_max):
    days = random.randint(days_back_min, days_back_max)
    return (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")


def make_address():
    return f"{random.randint(10, 999)} {random.choice(['Main St', 'Oak Ave', 'Park Rd', 'Elm Blvd', '5th Ave'])}, {random.choice(CITIES)}"


def seed_customers(conn, n=15):
    customers = []
    for i in range(1, n + 1):
        cid = f"CUST{i:03d}"
        name = f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
        email = name.lower().replace(" ", ".") + "@example.com"
        address = make_address()
        created_at = rand_date(60, 730)
        customers.append((cid, name, email, address, created_at))
    conn.executemany(
        "INSERT INTO customers (customer_id, name, email, default_shipping_address, account_created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        customers,
    )
    return customers


def seed_orders(conn, customers, n=35):
    orders = []
    for i in range(1, n + 1):
        oid = f"ORD{i:04d}"
        customer = random.choice(customers)
        cid, _, _, default_address, _ = customer
        status = random.choices(STATUSES, weights=STATUS_WEIGHTS)[0]
        # most orders ship to the customer's default address; some don't (gift, alt address)
        shipping_address = default_address if random.random() < 0.75 else make_address()
        amount = round(random.uniform(12.99, 499.99), 2)
        created_at = rand_date(1, 180)
        shipped_at = None
        if status in ("shipped", "delivered"):
            shipped_at = rand_date(0, 30)
        elif status == "cancelled" and random.random() < 0.3:
            shipped_at = rand_date(0, 30)  # cancelled after it had already shipped
        orders.append((oid, cid, status, shipping_address, amount, created_at, shipped_at))
    conn.executemany(
        "INSERT INTO orders (order_id, customer_id, status, shipping_address, amount, created_at, shipped_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        orders,
    )
    return orders


def seed_address_changes(conn, orders):
    """A handful of benign changes, plus a couple of explicit fraud-pattern cases
    (address changed on an order that has already shipped) for the permission-tiering demo."""
    changes = []

    # benign: pre-shipment address correction, auto-approved
    unshipped = [o for o in orders if o[6] is None and o[2] != "cancelled"]
    for order in random.sample(unshipped, min(5, len(unshipped))):
        oid, _, _, old_addr, *_ = order
        changes.append((oid, old_addr, make_address(), rand_date(0, 5), "auto"))

    # fraud pattern: address changed AFTER shipment -> required human confirm
    shipped = [o for o in orders if o[6] is not None]
    for order in random.sample(shipped, min(3, len(shipped))):
        oid, _, _, old_addr, *_ = order
        changes.append((oid, old_addr, make_address(), rand_date(0, 3), "human_review:agent_daniyal"))

    conn.executemany(
        "INSERT INTO address_change_log (order_id, old_address, new_address, changed_at, approved_by) "
        "VALUES (?, ?, ?, ?, ?)",
        changes,
    )
    return changes


def seed(conn):
    conn.execute("DELETE FROM address_change_log")
    conn.execute("DELETE FROM orders")
    conn.execute("DELETE FROM customers")
    customers = seed_customers(conn)
    orders = seed_orders(conn, customers)
    changes = seed_address_changes(conn, orders)
    conn.commit()
    return len(customers), len(orders), len(changes)


if __name__ == "__main__":
    conn = get_connection()
    n_customers, n_orders, n_changes = seed(conn)
    counts = {
        row[0]: row[1]
        for row in conn.execute(
            "SELECT status, COUNT(*) FROM orders GROUP BY status"
        )
    }
    assert n_customers > 0 and n_orders > 0
    print(f"OK: seeded {n_customers} customers, {n_orders} orders, {n_changes} address changes")
    print(f"order status breakdown: {counts}")
    conn.close()
