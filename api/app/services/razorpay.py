"""Razorpay Standard Checkout, test mode (04 §7) — over plain HTTPS, no SDK.

`create_order` makes the Razorpay order for a `pending_payment` order; the browser opens the
modal; `POST /orders/{id}/verify` checks the payment signature (HMAC-SHA256 of
`order_id|payment_id` with the key secret) and the webhook checks `X-Razorpay-Signature` (HMAC of
the raw body with the webhook secret). Both end in the same idempotent `orders.mark_paid`.
"""

import hashlib
import hmac

import httpx

from app.core.config import Settings
from app.core.errors import ApiError

API = "https://api.razorpay.com/v1"


async def create_order(settings: Settings, *, amount_paise: int, receipt: str) -> str:
    if not settings.razorpay_enabled:
        raise ApiError(
            503, "payments_off", "Online payment is switched off — choose cash on delivery"
        )
    assert settings.razorpay_key_secret is not None  # noqa: S101
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{API}/orders",
                auth=(
                    settings.razorpay_key_id or "",
                    settings.razorpay_key_secret.get_secret_value(),
                ),
                json={"amount": amount_paise, "currency": "INR", "receipt": receipt},
            )
        r.raise_for_status()
        return str(r.json()["id"])
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise ApiError(
            502, "payments_down", "Razorpay didn't answer — try cash on delivery"
        ) from exc


async def refund(settings: Settings, payment_id: str, amount_paise: int, *, receipt: str) -> str:
    """A full refund of a captured payment; returns Razorpay's refund id. Razorpay refuses to
    refund more than was captured, so a repeat of a full refund can't pay out twice."""
    if not settings.razorpay_enabled:
        raise ApiError(503, "payments_off", "Online payment is switched off")
    assert settings.razorpay_key_secret is not None  # noqa: S101
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{API}/payments/{payment_id}/refund",
                auth=(
                    settings.razorpay_key_id or "",
                    settings.razorpay_key_secret.get_secret_value(),
                ),
                json={"amount": amount_paise, "receipt": receipt, "speed": "normal"},
            )
        r.raise_for_status()
        return str(r.json()["id"])
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise ApiError(502, "refund_failed", "Razorpay didn't take the refund") from exc


def _hmac(secret: str, message: bytes) -> str:
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def payment_signature(secret: str, razorpay_order_id: str, payment_id: str) -> str:
    return _hmac(secret, f"{razorpay_order_id}|{payment_id}".encode())


def verify_payment(
    settings: Settings, razorpay_order_id: str, payment_id: str, signature: str
) -> bool:
    if settings.razorpay_key_secret is None:
        return False
    expected = payment_signature(
        settings.razorpay_key_secret.get_secret_value(), razorpay_order_id, payment_id
    )
    return hmac.compare_digest(expected, signature)


def verify_webhook(settings: Settings, body: bytes, signature: str) -> bool:
    if settings.razorpay_webhook_secret is None:
        return False
    expected = _hmac(settings.razorpay_webhook_secret.get_secret_value(), body)
    return hmac.compare_digest(expected, signature or "")
