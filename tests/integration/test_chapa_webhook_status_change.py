"""A later Chapa webhook for the same transaction but a new status (platform
audit, 2026-09-29, #28). ChapaProvider.verify_webhook uses Chapa's
transaction reference as the event id, and _apply_confirmed_status records
that id in payment_events before it looks at the status, committing it even
for a 'pending' or 'failed' event. The 'success' webhook for the same
reference then hit ON CONFLICT and came back 'duplicate', so a player who
paid was never credited. After a 'failed' the row wasn't 'processing' any
more, so the polling fallback never picked it up either. The poll path
already had the status in its key (poll:{ref}:{status}); the webhook path
didn't."""

from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal

from packages.core import ledger
from services.payments import deposits
from services.payments.chapa import ChapaProvider
from tests.integration.conftest import create_user
from tests.integration.test_payments_deposits import FakePaymentProvider

SECRET = "test-secret-for-status-change"


def _signed_webhook(*, tx_ref: str, reference: str, status: str, amount: str) -> tuple[dict[str, str], bytes]:
    body = json.dumps({"tx_ref": tx_ref, "reference": reference, "status": status, "amount": amount}).encode()
    return {
        "x-chapa-signature": hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest(),
        "chapa-signature": hmac.new(SECRET.encode(), SECRET.encode(), hashlib.sha256).hexdigest(),
    }, body


async def _deposit(pool, redis, conn) -> tuple[int, str]:
    user_id = await create_user(conn)
    intent = await deposits.create_deposit_intent(
        pool, redis, FakePaymentProvider(),
        user_id=user_id, amount=Decimal("100.00"), phone_e164="+251911000000",
        return_url="https://app.test/return", callback_url="https://payments.test/webhooks/chapa",
        min_deposit=Decimal("10.00"), daily_cap=Decimal("50000.00"),
    )
    return user_id, intent.our_ref


async def _cash(conn, user_id: int) -> Decimal:
    account = await ledger.get_or_create_account(conn, user_id, "user_cash")
    return await ledger.balance(conn, account.id)


async def _send(pool, redis, *, tx_ref: str, reference: str, status: str) -> str:
    headers, body = _signed_webhook(tx_ref=tx_ref, reference=reference, status=status, amount="100.00")
    return await deposits.handle_webhook(pool, redis, ChapaProvider(SECRET), headers=headers, raw_body=body)


async def test_a_success_webhook_after_a_pending_one_for_the_same_reference_credits(pool, redis, conn):
    user_id, our_ref = await _deposit(pool, redis, conn)
    reference = f"AP-{our_ref}"

    assert await _send(pool, redis, tx_ref=our_ref, reference=reference, status="pending") == "pending"
    assert await _send(pool, redis, tx_ref=our_ref, reference=reference, status="success") == "credited"

    assert await _cash(conn, user_id) == Decimal("100.00")
    assert await conn.fetchval("SELECT status FROM payments WHERE our_ref = $1", our_ref) == "succeeded"


async def test_a_success_webhook_after_a_failed_one_for_the_same_reference_credits(pool, redis, conn):
    user_id, our_ref = await _deposit(pool, redis, conn)
    reference = f"AP-{our_ref}"

    assert await _send(pool, redis, tx_ref=our_ref, reference=reference, status="failed") == "not_succeeded"
    assert await _send(pool, redis, tx_ref=our_ref, reference=reference, status="success") == "credited"

    assert await _cash(conn, user_id) == Decimal("100.00")
    assert await conn.fetchval("SELECT status FROM payments WHERE our_ref = $1", our_ref) == "succeeded"


async def test_a_redelivered_success_webhook_still_credits_once(pool, redis, conn):
    user_id, our_ref = await _deposit(pool, redis, conn)
    reference = f"AP-{our_ref}"

    assert await _send(pool, redis, tx_ref=our_ref, reference=reference, status="success") == "credited"
    assert await _send(pool, redis, tx_ref=our_ref, reference=reference, status="success") == "duplicate"

    assert await _cash(conn, user_id) == Decimal("100.00")
    assert await conn.fetchval(
        "SELECT count(*) FROM ledger_transactions WHERE idempotency_key = $1", our_ref
    ) == 1
