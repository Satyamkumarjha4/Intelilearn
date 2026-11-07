"""Razorpay's side of the wire, for the payment tests (credits plan §13.3, phase 10.8): the entities of its webhooks as
it documents them, and the signature it puts on a body (the hex HMAC-SHA256 of the raw body with the webhook
secret; there is no timestamp)."""

import hashlib
import hmac

CREATED = 1567674606


def sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def payment(**fields) -> dict:
    return {
        "id": "pay_DESlfW9H8K9uqM", "entity": "payment", "amount": 49900, "currency": "INR", "status": "captured",
        "order_id": "order_DESlLckIVRkHWj", "captured": True, "method": "upi", "amount_refunded": 0, **fields,
    }  # fmt: skip


def order(**fields) -> dict:
    return {
        "id": "order_DESlLckIVRkHWj", "entity": "order", "amount": 49900, "amount_paid": 49900, "amount_due": 0,
        "currency": "INR", "receipt": "rcptid #1", "status": "paid", "attempts": 1, **fields,
    }  # fmt: skip


def refund(**fields) -> dict:
    return {
        "id": "rfnd_FS8TWyPrCsa0OB", "entity": "refund", "amount": 20000, "currency": "INR",
        "payment_id": "pay_DESlfW9H8K9uqM", "status": "processed", "created_at": 1597734071, **fields,
    }  # fmt: skip


def envelope(kind: str, **entities) -> dict:
    """A webhook body: `envelope("order.paid", order=order(), payment=payment())`."""
    return {
        "entity": "event", "account_id": "acc_BFQ7uQEaa7j2z7", "event": kind, "contains": list(entities),
        "payload": {name: {"entity": body} for name, body in entities.items()}, "created_at": CREATED,
    }  # fmt: skip
