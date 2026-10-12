
import os
import sqlite3
import hmac
import hashlib
import uuid

import razorpay
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

load_dotenv()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024

KEY_ID = os.getenv("RAZORPAY_KEY_ID", "")
KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")
WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")

# Fixed test price: Rs 50 = 5000 paise.
SWAP_PRICE_PAISE = 5000
DB_FILE = "ev_swap.db"

if not KEY_ID or not KEY_SECRET:
    raise RuntimeError("Add Razorpay test keys to your .env file.")

client = razorpay.Client(auth=(KEY_ID, KEY_SECRET))


def db():
    connection = sqlite3.connect(DB_FILE)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with db() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS swaps (
                swap_id TEXT PRIMARY KEY,
                order_id TEXT UNIQUE,
                payment_id TEXT,
                amount INTEGER NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Retain the existing table for compatibility.
        con.execute("""
            CREATE TABLE IF NOT EXISTS webhook_events (
                event_id TEXT PRIMARY KEY,
                received_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Detailed log of each webhook delivery.
        con.execute("""
            CREATE TABLE IF NOT EXISTS webhook_event_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT,
                event_type TEXT,
                payment_id TEXT,
                order_id TEXT,
                signature_valid INTEGER NOT NULL DEFAULT 0,
                processing_status TEXT NOT NULL,
                message TEXT,
                received_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        con.execute("""
            CREATE INDEX IF NOT EXISTS idx_webhook_logs_received
            ON webhook_event_logs(received_at)
        """)

        con.execute("""
            CREATE INDEX IF NOT EXISTS idx_webhook_logs_status
            ON webhook_event_logs(processing_status)
        """)
        
        con.execute("""
            CREATE TABLE IF NOT EXISTS battery_inventory (
                battery_id TEXT PRIMARY KEY,
                charge_percent INTEGER NOT NULL
                    CHECK (charge_percent BETWEEN 0 AND 100),
                slot_no INTEGER UNIQUE,
                status TEXT NOT NULL
                    CHECK (status IN ('charged', 'charging', 'in_use', 'maintenance')),
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        con.execute("""
            CREATE TABLE IF NOT EXISTS station_config (
                station_id TEXT PRIMARY KEY,
                total_slots INTEGER NOT NULL CHECK (total_slots > 0)
            )
        """)

        con.execute("""
            INSERT OR IGNORE INTO station_config (station_id, total_slots)
            VALUES ('STATION-01', 12)
        """)



def log_webhook(
    event_id,
    event_type,
    payment_id,
    order_id,
    signature_valid,
    processing_status,
    message
):
    with db() as con:
        con.execute("""
            INSERT INTO webhook_event_logs (
                event_id, event_type, payment_id, order_id,
                signature_valid, processing_status, message
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            event_id,
            event_type,
            payment_id,
            order_id,
            int(signature_valid),
            processing_status,
            message
        ))



def get_swap(swap_id):
    with db() as con:
        row = con.execute(
            "SELECT * FROM swaps WHERE swap_id = ?",
            (swap_id,)
        ).fetchone()
    return dict(row) if row else None


def mark_paid(order_id, payment_id, amount):
    """Update only a known order with its expected amount."""
    with db() as con:
        row = con.execute(
            "SELECT * FROM swaps WHERE order_id = ?",
            (order_id,)
        ).fetchone()

        if not row:
            return False

        if row["amount"] != amount:
            return False

        # Do not replace an existing payment with a different one.
        if row["status"] == "paid":
            return row["payment_id"] == payment_id

        con.execute("""
            UPDATE swaps
            SET status = 'paid', payment_id = ?
            WHERE order_id = ? AND status = 'pending'
        """, (payment_id, order_id))

        updated = con.execute(
            "SELECT status, payment_id FROM swaps WHERE order_id = ?",
            (order_id,)
        ).fetchone()

        return (
            updated is not None
            and updated["status"] == "paid"
            and updated["payment_id"] == payment_id
        )


@app.get("/")
def home():
    return render_template("index.html", key_id=KEY_ID)


@app.post("/api/create-order")
def create_order():
    # The browser cannot choose its own price.
    swap_id = str(uuid.uuid4())

    order = client.order.create(data={
        "amount": SWAP_PRICE_PAISE,
        "currency": "INR",
        "receipt": swap_id.replace("-", "")[:40],
        "notes": {
            "swap_id": swap_id,
            "project": "EV battery swap demo"
        }
    })

    with db() as con:
        con.execute("""
            INSERT INTO swaps (swap_id, order_id, amount, status)
            VALUES (?, ?, ?, 'pending')
        """, (swap_id, order["id"], SWAP_PRICE_PAISE))

    return jsonify({
        "swap_id": swap_id,
        "order_id": order["id"],
        "amount": SWAP_PRICE_PAISE,
        "currency": "INR",
        "key_id": KEY_ID
    })


@app.post("/api/verify-payment")
def verify_payment():
    data = request.get_json(silent=True) or {}

    order_id = data.get("razorpay_order_id", "")
    payment_id = data.get("razorpay_payment_id", "")
    signature = data.get("razorpay_signature", "")

    if not all([order_id, payment_id, signature]):
        return jsonify({"error": "Missing payment fields"}), 400

    # Check that the order belongs to this application.
    with db() as con:
        row = con.execute(
            "SELECT * FROM swaps WHERE order_id = ?",
            (order_id,)
        ).fetchone()

    if not row:
        return jsonify({"error": "Unknown order"}), 400

    try:
        client.utility.verify_payment_signature({
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": signature
        })
    except Exception:
        return jsonify({"error": "Invalid payment signature"}), 400

    # A valid Checkout signature alone does not prove capture.
    # Fetch the payment from Razorpay and check its actual status.
    try:
        payment = client.payment.fetch(payment_id)
    except Exception:
        app.logger.exception("Could not fetch payment")
        return jsonify({
            "error": "Could not confirm payment status; retry"
        }), 502

    if payment.get("order_id") != order_id:
        return jsonify({"error": "Payment/order mismatch"}), 400

    if payment.get("amount") != row["amount"]:
        return jsonify({"error": "Payment amount mismatch"}), 400

    if payment.get("currency") != "INR":
        return jsonify({"error": "Currency mismatch"}), 400

    if payment.get("status") != "captured":
        return jsonify({
            "status": payment.get("status", "unknown"),
            "message": "Payment is not captured yet"
        }), 202

    if not mark_paid(order_id, payment_id, payment["amount"]):
        return jsonify({"error": "Could not update swap"}), 409

    return jsonify({
        "status": "paid",
        "swap_id": row["swap_id"],
        "message": "Test payment verified. Swap marked paid."
    })


@app.post("/webhook")
def webhook():
    import json

    raw_body = request.get_data()
    signature = request.headers.get("X-Razorpay-Signature", "")
    event_id = request.headers.get("X-Razorpay-Event-Id")

    # Parse only for diagnostic metadata. The payload is untrusted
    # until signature validation succeeds.
    try:
        event = json.loads(raw_body)
        if not isinstance(event, dict):
            event = {}
    except (ValueError, UnicodeDecodeError):
        event = {}

    event_type = str(event.get("event", "unknown"))[:100]
    payload = event.get("payload") or {}
    payment_entity = (
        payload.get("payment", {}).get("entity", {})
        if isinstance(payload, dict) else {}
    )

    if not isinstance(payment_entity, dict):
        payment_entity = {}

    payment_id = payment_entity.get("id")
    order_id = payment_entity.get("order_id")

    if payment_id is not None:
        payment_id = str(payment_id)[:100]
    if order_id is not None:
        order_id = str(order_id)[:100]
    if event_id is not None:
        event_id = str(event_id)[:200]

    # Verify the exact, unmodified HTTP request body.
    expected = hmac.new(
        WEBHOOK_SECRET.encode("utf-8"),
        raw_body,
        hashlib.sha256
    ).hexdigest() if WEBHOOK_SECRET else ""

    valid = bool(
        signature
        and expected
        and hmac.compare_digest(expected, signature)
    )

    if not valid:
        log_webhook(
            event_id, event_type, payment_id, order_id,
            False, "rejected", "Webhook signature validation failed"
        )
        return jsonify({"error": "Invalid webhook signature"}), 400

    if not isinstance(event.get("payload"), dict):
        log_webhook(
            event_id, event_type, payment_id, order_id,
            True, "failed", "Webhook payload structure is invalid"
        )
        return jsonify({"error": "Invalid payload structure"}), 400

    # Ignore event types that this application does not process,
    # but record them so the monitoring page has a complete history.
    if event_type != "payment.captured":
        log_webhook(
            event_id, event_type, payment_id, order_id,
            True, "ignored", "Event type is not handled by this endpoint"
        )
        return jsonify({"received": True}), 200

    if not payment_id or not order_id:
        log_webhook(
            event_id, event_type, payment_id, order_id,
            True, "failed", "Payment ID or order ID is missing"
        )
        return jsonify({"error": "Missing payment identifiers"}), 400

    amount = payment_entity.get("amount")

    if not isinstance(amount, int) or isinstance(amount, bool):
        log_webhook(
            event_id, event_type, payment_id, order_id,
            True, "failed", "Invalid payment amount"
        )
        return jsonify({"error": "Invalid amount"}), 400

    if not mark_paid(order_id, payment_id, amount):
        log_webhook(
            event_id, event_type, payment_id, order_id,
            True, "failed",
            "Order not found, amount mismatch, or payment conflict"
        )
        # Acknowledge only after recording the outcome. Alert or retry
        # operationally when an event cannot be reconciled.
        return jsonify({"received": True, "reconciled": False}), 200

    log_webhook(
        event_id, event_type, payment_id, order_id,
        True, "processed", "Captured payment reconciled successfully"
    )

    return jsonify({"received": True}), 200



@app.get("/api/swap/<swap_id>")
def swap_status(swap_id):
    swap = get_swap(swap_id)

    if not swap:
        return jsonify({"error": "Swap not found"}), 404

    return jsonify({
        "swap_id": swap["swap_id"],
        "status": swap["status"],
        "amount": swap["amount"],
        "payment_id": swap["payment_id"]
    })


# Future ESP32 demo endpoint. Not an actuator command.
@app.post("/api/esp32/status")
def esp32_status():
    data = request.get_json(silent=True) or {}
    device_id = data.get("device_id")
    state = data.get("state")

    if not device_id or state not in ["idle", "ready", "busy"]:
        return jsonify({"error": "Invalid device status"}), 400

    app.logger.info("ESP32 %s reports %s", device_id, state)

    return jsonify({
        "received": True,
        "device_id": device_id,
        "state": state
    })



@app.get("/dashboard")
def dashboard():
    search = request.args.get("q", "").strip()[:100]
    status_filter = request.args.get("status", "").strip().lower()

    allowed_statuses = {"paid", "pending", "failed"}
    if status_filter not in allowed_statuses:
        status_filter = ""

    with db() as con:
        # Dashboard summary comes from actual SQLite records.
        stats = con.execute("""
            SELECT
                COUNT(*) AS total_swaps,
                COALESCE(SUM(CASE
                    WHEN status = 'paid' THEN 1 ELSE 0
                END), 0) AS paid_swaps,
                COALESCE(SUM(CASE
                    WHEN status = 'pending' THEN 1 ELSE 0
                END), 0) AS pending_swaps,
                COALESCE(SUM(CASE
                    WHEN status = 'paid' THEN amount ELSE 0
                END), 0) AS captured_paise
            FROM swaps
        """).fetchone()

        sql = "SELECT * FROM swaps WHERE 1=1"
        params = []

        if status_filter:
            sql += " AND status = ?"
            params.append(status_filter)

        if search:
            sql += """
                AND (
                    swap_id LIKE ?
                    OR order_id LIKE ?
                    OR COALESCE(payment_id, '') LIKE ?
                )
            """
            term = f"%{search}%"
            params.extend([term, term, term])

        sql += " ORDER BY created_at DESC LIMIT 200"

        swaps = con.execute(sql, params).fetchall()

    return render_template(
        "dashboard.html",
        stats=stats,
        swaps=swaps,
        search=search,
        status_filter=status_filter
    )



@app.get("/webhook-monitor")
def webhook_monitor():
    search = request.args.get("q", "").strip()[:100]
    status_filter = request.args.get("status", "").strip().lower()

    allowed = {"processed", "rejected", "failed", "ignored"}
    if status_filter not in allowed:
        status_filter = ""

    with db() as con:
        stats = con.execute("""
            SELECT
                COUNT(*) AS total,
                COALESCE(SUM(signature_valid = 1), 0) AS verified,
                COALESCE(SUM(signature_valid = 0), 0) AS rejected,
                COALESCE(SUM(processing_status = 'processed'), 0)
                    AS processed,
                COALESCE(SUM(processing_status = 'failed'), 0)
                    AS failed
            FROM webhook_event_logs
        """).fetchone()

        sql = "SELECT * FROM webhook_event_logs WHERE 1=1"
        params = []

        if status_filter:
            sql += " AND processing_status = ?"
            params.append(status_filter)

        if search:
            sql += """
                AND (
                    COALESCE(event_id, '') LIKE ?
                    OR COALESCE(event_type, '') LIKE ?
                    OR COALESCE(payment_id, '') LIKE ?
                    OR COALESCE(order_id, '') LIKE ?
                    OR COALESCE(message, '') LIKE ?
                )
            """
            term = f"%{search}%"
            params.extend([term] * 5)

        sql += " ORDER BY id DESC LIMIT 200"
        events = con.execute(sql, params).fetchall()

    return render_template(
        "webhook_monitor.html",
        stats=stats,
        events=events,
        search=search,
        status_filter=status_filter
    )


@app.get("/battery-inventory")
def battery_inventory():
    with db() as con:
        total_slots = con.execute("""
            SELECT total_slots FROM station_config
            WHERE station_id = 'STATION-01'
        """).fetchone()["total_slots"]

        batteries = con.execute("""
            SELECT battery_id, charge_percent, slot_no, status, updated_at
            FROM battery_inventory
            ORDER BY
                CASE WHEN slot_no IS NULL THEN 1 ELSE 0 END,
                slot_no, battery_id
        """).fetchall()

        counts = con.execute("""
            SELECT
                COUNT(*) AS total_batteries,
                SUM(CASE WHEN status = 'charged' THEN 1 ELSE 0 END)
                    AS charged,
                SUM(CASE WHEN status = 'charging' THEN 1 ELSE 0 END)
                    AS charging
            FROM battery_inventory
        """).fetchone()

    occupied_slots = sum(1 for b in batteries if b["slot_no"] is not None)

    summary = {
        "total_slots": total_slots,
        "empty_slots": total_slots - occupied_slots,
        "total_batteries": counts["total_batteries"] or 0,
        "charged": counts["charged"] or 0,
        "charging": counts["charging"] or 0,
    }

    return render_template(
        "battery_inventory.html",
        batteries=batteries,
        summary=summary
    )


@app.post("/api/batteries")
def add_battery():
    data = request.get_json(silent=True) or {}

    battery_id = str(data.get("battery_id", "")).strip()[:50]
    charge = data.get("charge_percent")
    slot_no = data.get("slot_no")
    status = data.get("status", "charging")

    if not battery_id:
        return jsonify({"error": "Battery ID is required"}), 400

    if type(charge) is not int or not 0 <= charge <= 100:
        return jsonify({"error": "Charge must be an integer from 0 to 100"}), 400

    if status not in {"charged", "charging", "in_use", "maintenance"}:
        return jsonify({"error": "Invalid battery status"}), 400

    if slot_no is not None:
        if type(slot_no) is not int or slot_no < 1:
            return jsonify({"error": "Slot number must be a positive integer"}), 400

        with db() as con:
            total = con.execute("""
                SELECT total_slots FROM station_config
                WHERE station_id = 'STATION-01'
            """).fetchone()["total_slots"]

            if slot_no > total:
                return jsonify({"error": f"Slot must be between 1 and {total}"}), 400

    if status == "charged" and charge != 100:
        return jsonify({"error": "A charged battery must be at 100%"}), 400

    if status == "charging" and charge >= 100:
        return jsonify({"error": "A battery at 100% cannot be charging"}), 400

    try:
        with db() as con:
            con.execute("""
                INSERT INTO battery_inventory
                    (battery_id, charge_percent, slot_no, status)
                VALUES (?, ?, ?, ?)
            """, (battery_id, charge, slot_no, status))
    except sqlite3.IntegrityError:
        return jsonify({
            "error": "Battery ID already exists or slot is occupied"
        }), 409

    return jsonify({"success": True, "battery_id": battery_id}), 201


@app.patch("/api/batteries/<battery_id>")
def update_battery(battery_id):
    data = request.get_json(silent=True) or {}
    charge = data.get("charge_percent")
    slot_no = data.get("slot_no")
    status = data.get("status")

    if type(charge) is not int or not 0 <= charge <= 100:
        return jsonify({"error": "Charge must be an integer from 0 to 100"}), 400

    if status not in {"charged", "charging", "in_use", "maintenance"}:
        return jsonify({"error": "Invalid battery status"}), 400

    if status == "charged" and charge != 100:
        return jsonify({"error": "A charged battery must be at 100%"}), 400

    if status == "charging" and charge >= 100:
        return jsonify({"error": "A battery at 100% cannot be charging"}), 400

    if slot_no is not None and (type(slot_no) is not int or slot_no < 1):
        return jsonify({"error": "Slot number must be positive or null"}), 400

    try:
        with db() as con:
            total = con.execute("""
                SELECT total_slots FROM station_config
                WHERE station_id = 'STATION-01'
            """).fetchone()["total_slots"]

            if slot_no is not None and slot_no > total:
                return jsonify({"error": f"Slot must be between 1 and {total}"}), 400

            cursor = con.execute("""
                UPDATE battery_inventory
                SET charge_percent = ?, slot_no = ?, status = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE battery_id = ?
            """, (charge, slot_no, status, battery_id))

            if cursor.rowcount == 0:
                return jsonify({"error": "Battery not found"}), 404
    except sqlite3.IntegrityError:
        return jsonify({"error": "That slot is already occupied"}), 409

    return jsonify({"success": True, "battery_id": battery_id})


if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", port=5000, debug=True)

