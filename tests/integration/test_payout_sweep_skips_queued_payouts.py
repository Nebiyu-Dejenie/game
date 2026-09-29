"""The stuck-payout sweep and payouts that are only waiting their turn
(platform audit, 2026-09-29, #35). sweep_stuck_approved_payouts re-enqueued
every automatic payout still 'approved' 60 seconds after its last update,
without checking whether its stream entry was still waiting to be read or
was being worked on. Any backlog, a slow Chapa, or a dead consumer added
one more entry per payout on every tick. The worker no longer sends a
payout twice (it only dispatches from 'approved', and a duplicate finds the
row at 'processing'), but each duplicate that lands after the send is
counted and logged as a redelivery awaiting reconciliation, a signal meant
for a worker that crashed mid-send, and the stream grows without bound."""

from __future__ import annotations

from decimal import Decimal

from services.payments import payout_worker, withdrawals
from tests.integration.conftest import create_funded_user
from tests.integration.test_payout_worker import FakePayoutProvider, _approved_withdrawal


async def _entries_for(redis, our_ref: str) -> int:
    entries = await redis.xrange(withdrawals.PAYOUT_STREAM, "-", "+")
    return sum(1 for _id, fields in entries if fields.get("our_ref") == our_ref)


async def _backdate(conn, our_ref: str) -> None:
    await conn.execute("UPDATE payments SET updated_at = now() - interval '2 hours' WHERE our_ref = $1", our_ref)


async def test_a_payout_whose_entry_is_still_unread_is_not_enqueued_again(pool, redis, conn):
    user_id = await create_funded_user(conn, Decimal("500.00"))
    our_ref = await _approved_withdrawal(pool, redis, conn, user_id, Decimal("100.00"))
    payment_id = await conn.fetchval("SELECT id FROM payments WHERE our_ref = $1", our_ref)
    await payout_worker.ensure_group(redis)
    await _backdate(conn, our_ref)

    for _tick in range(3):
        assert payment_id not in await withdrawals.sweep_stuck_approved_payouts(pool, redis)

    assert await _entries_for(redis, our_ref) == 1


async def test_a_payout_being_worked_on_is_not_enqueued_again(pool, redis, conn):
    user_id = await create_funded_user(conn, Decimal("500.00"))
    our_ref = await _approved_withdrawal(pool, redis, conn, user_id, Decimal("100.00"))
    payment_id = await conn.fetchval("SELECT id FROM payments WHERE our_ref = $1", our_ref)
    # A consumer has read it (it's in the group's pending list) but is
    # still busy with the entries ahead of it in its batch.
    await payout_worker.ensure_group(redis)
    await redis.xreadgroup(payout_worker.GROUP, "w-busy", {withdrawals.PAYOUT_STREAM: ">"}, count=10)
    await _backdate(conn, our_ref)

    assert payment_id not in await withdrawals.sweep_stuck_approved_payouts(pool, redis)
    assert await _entries_for(redis, our_ref) == 1


async def test_a_payout_waiting_behind_a_backlog_is_dispatched_once_and_not_flagged(pool, redis, conn):
    user_id = await create_funded_user(conn, Decimal("500.00"))
    our_ref = await _approved_withdrawal(pool, redis, conn, user_id, Decimal("100.00"))
    await payout_worker.ensure_group(redis)
    await _backdate(conn, our_ref)
    await withdrawals.sweep_stuck_approved_payouts(pool, redis)

    provider = FakePayoutProvider(outcomes={our_ref: "processing"})  # Chapa accepted it
    outcomes = []
    while (outcome := await payout_worker.process_next(pool, redis, provider, consumer_name="w-backlog")) is not None:
        outcomes.append(outcome)

    assert provider.call_count[our_ref] == 1
    assert "awaiting_reconciliation" not in outcomes


async def test_a_payout_whose_entry_was_lost_is_still_re_enqueued(pool, redis, conn):
    user_id = await create_funded_user(conn, Decimal("500.00"))
    our_ref = await _approved_withdrawal(pool, redis, conn, user_id, Decimal("100.00"))
    payment_id = await conn.fetchval("SELECT id FROM payments WHERE our_ref = $1", our_ref)
    await payout_worker.ensure_group(redis)
    # The consumer read and acked other entries past it, and its own entry
    # is gone (the XADD after the commit never happened, or Redis lost it).
    await redis.xreadgroup(payout_worker.GROUP, "w-ahead", {withdrawals.PAYOUT_STREAM: ">"}, count=10)
    for msg_id, _fields in await redis.xrange(withdrawals.PAYOUT_STREAM, "-", "+"):
        await redis.xack(withdrawals.PAYOUT_STREAM, payout_worker.GROUP, msg_id)
        await redis.xdel(withdrawals.PAYOUT_STREAM, msg_id)
    await _backdate(conn, our_ref)

    assert payment_id in await withdrawals.sweep_stuck_approved_payouts(pool, redis)
    assert await _entries_for(redis, our_ref) == 1


async def test_one_entry_stuck_pending_does_not_hide_a_later_lost_payout(pool, redis, conn):
    """An entry that stays pending (a consumer died holding it, or it keeps
    failing) is older than everything read after it. Entries acked since
    then are finished, and a payout whose entry was acked but is still
    'approved' is lost and must be re-enqueued."""
    user_id = await create_funded_user(conn, Decimal("500.00"))
    stuck_ref = await _approved_withdrawal(pool, redis, conn, user_id, Decimal("50.00"))
    lost_ref = await _approved_withdrawal(pool, redis, conn, user_id, Decimal("60.00"))
    lost_id = await conn.fetchval("SELECT id FROM payments WHERE our_ref = $1", lost_ref)
    await payout_worker.ensure_group(redis)
    await redis.xreadgroup(payout_worker.GROUP, "w-dead", {withdrawals.PAYOUT_STREAM: ">"}, count=10)
    for msg_id, fields in await redis.xrange(withdrawals.PAYOUT_STREAM, "-", "+"):
        if fields.get("our_ref") == lost_ref:
            await redis.xack(withdrawals.PAYOUT_STREAM, payout_worker.GROUP, msg_id)
    await _backdate(conn, stuck_ref)
    await _backdate(conn, lost_ref)

    assert lost_id in await withdrawals.sweep_stuck_approved_payouts(pool, redis)
