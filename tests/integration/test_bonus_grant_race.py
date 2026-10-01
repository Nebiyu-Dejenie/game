"""Two grants of one bonus racing (platform audit #36). grant_bonus checks
for an existing ledger transaction with its key, then posts, then inserts
the bonuses row. Two overlapping deposit confirmations for one player (an
admin approving a manual deposit while a Telebirr redemption commits, say)
both reach the welcome bonus with the same key. The second one's check ran
before the first committed, its ledger.post waited and then returned the
first one's transaction as a replay, and it inserted a second bonuses row
on the same grant transaction. Two active bonuses then rested on one
credit; converting the second raised InsufficientFunds and aborted the
bonus sweep for every player after it."""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

from packages.core import bonuses
from tests.integration.conftest import create_user


async def test_two_overlapping_grants_with_one_key_make_one_bonus(pool, conn, monkeypatch):
    real_post = bonuses.post
    calls = 0

    async def post_then_pause_the_first(*args, **kwargs):
        nonlocal calls
        calls += 1
        mine = calls
        txn = await real_post(*args, **kwargs)
        if mine == 1:  # the first grant holds its transaction open a moment
            await asyncio.sleep(0.3)
        return txn

    monkeypatch.setattr(bonuses, "post", post_then_pause_the_first)
    user_id = await create_user(conn)
    key = f"welcome-{user_id}-test-{uuid.uuid4()}"

    async def grant():
        async with pool.acquire() as c:
            return await bonuses.grant_bonus(
                c, user_id=user_id, idempotency_key=key, amount=Decimal("50.00"),
                wagering_required=Decimal("150.00"),
            )

    first = asyncio.create_task(grant())
    await asyncio.sleep(0.1)  # the second starts while the first is inside its transaction
    second = asyncio.create_task(grant())
    a, b = await asyncio.gather(first, second)

    rows = await conn.fetchval("SELECT count(*) FROM bonuses WHERE grant_txn_id = $1", a.grant_txn_id)
    assert (a.id == b.id, rows) == (True, 1)


async def test_one_bonus_the_sweep_cannot_convert_does_not_stop_the_others(pool, redis, conn, monkeypatch):
    """Platform audit #67: sweep_bonus_wagering had no per-row error
    handling, so one bonus that raised (like the duplicate row above,
    hitting InsufficientFunds) ended the pass, and every active bonus after
    it, other players' included, never converted or expired."""
    from services.payments import bonus_sweep

    user_ids = [await create_user(conn) for _ in range(2)]
    granted = []
    for user_id in user_ids:
        async with pool.acquire() as c:
            granted.append(await bonuses.grant_bonus(
                c, user_id=user_id, idempotency_key=f"test-sweep-isolation-{uuid.uuid4()}",
                amount=Decimal("20.00"), wagering_required=Decimal("0.00"),
            ))
    real_convert = bonus_sweep.convert_bonus_to_cash
    calls = 0

    async def first_conversion_fails(conn, *, bonus_id):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("simulated: this bonus can't be converted")
        return await real_convert(conn, bonus_id=bonus_id)

    monkeypatch.setattr(bonus_sweep, "convert_bonus_to_cash", first_conversion_fails)

    await bonus_sweep.sweep_bonus_wagering(pool, redis)

    statuses = [await conn.fetchval("SELECT status FROM bonuses WHERE id = $1", b.id) for b in granted]
    assert calls >= 2, "the sweep stopped at the first failure"
    assert statuses.count("converted") >= 1
