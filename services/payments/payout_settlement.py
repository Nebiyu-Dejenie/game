"""The two ways a payout that reached status='processing' ends: paid, or
failed with the locked amount returned to the player.

Shared by the payout worker (when Chapa gives a definite answer) and the
admin reconciliation actions (when it didn't -- services/admin/queries.py
resolve_payout_admin). Both functions must be called inside an open
transaction. Each locks the payments row first, then the balance rows
inside ledger.post(), and acts only if the payout is still 'processing'.
That's what makes the worker and an admin unable to both resolve the same
payout, and unable to deadlock against each other. The ledger keys are
the same whichever of the two resolves it, so a replay can never post
twice either.
"""

from __future__ import annotations

from decimal import Decimal

from packages.core import ledger


async def mark_payout_paid(
    conn: ledger.AsyncpgConnection, *, payment_id: int, provider_ref: str | None
) -> ledger.LedgerTransaction | None:
    """Moves the locked amount to provider_settlement and marks the payout
    'succeeded'. Returns None, changing nothing, if the payout isn't
    'processing' any more."""
    row = await conn.fetchrow(
        "SELECT user_id, amount, our_ref, status FROM payments WHERE id = $1 AND direction = 'out' FOR UPDATE",
        payment_id,
    )
    if row is None or row["status"] != "processing":
        return None
    amount: Decimal = row["amount"]
    locked = await ledger.get_or_create_account(conn, row["user_id"], "user_locked")
    provider_account = await ledger.get_or_create_account(conn, None, "provider_settlement")
    txn = await ledger.post(
        conn,
        "payout",
        [ledger.Entry(locked.id, -amount), ledger.Entry(provider_account.id, amount)],
        idempotency_key=f"payout-settle-{row['our_ref']}",
        payment_id=payment_id,
    )
    await conn.execute(
        "UPDATE payments SET status = 'succeeded', provider_ref = COALESCE($2, provider_ref), "
        "ledger_txn_id = $3, updated_at = now() WHERE id = $1",
        payment_id,
        provider_ref,
        txn.id,
    )
    return txn


async def mark_payout_failed(
    conn: ledger.AsyncpgConnection, *, payment_id: int, reason: str
) -> ledger.LedgerTransaction | None:
    """Returns the locked amount to the player's cash and marks the payout
    'failed'. Returns None, changing nothing, if the payout isn't
    'processing' any more."""
    row = await conn.fetchrow(
        "SELECT user_id, amount, our_ref, status FROM payments WHERE id = $1 AND direction = 'out' FOR UPDATE",
        payment_id,
    )
    if row is None or row["status"] != "processing":
        return None
    amount: Decimal = row["amount"]
    locked = await ledger.get_or_create_account(conn, row["user_id"], "user_locked")
    cash = await ledger.get_or_create_account(conn, row["user_id"], "user_cash")
    txn = await ledger.post(
        conn,
        "refund",
        [ledger.Entry(locked.id, -amount), ledger.Entry(cash.id, amount)],
        idempotency_key=f"payout-reverse-{row['our_ref']}",
        payment_id=payment_id,
    )
    await conn.execute(
        "UPDATE payments SET status = 'failed', failure_reason = $2, updated_at = now() WHERE id = $1",
        payment_id,
        reason,
    )
    return txn
