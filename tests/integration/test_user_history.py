"""The wallet's History tab (/api/history, services/gateway/queries.py
user_history()) lists Keno as well as Bingo, and calls a refund a refund.

Before 2026-10-02 it read Bingo only, so a player's Keno play never showed,
and a voided Bingo round (stakes refunded) read as "No win"."""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import asyncpg

from packages.core import keno
from services.engine import refunds
from services.engine.round_engine import RoundEngine, load_room_config
from services.gateway import queries
from tests.integration.conftest import create_funded_user, create_room
from tests.integration.test_keno_round_engine import _seed_fast_config_and_tier


async def _keno_round(conn: asyncpg.Connection, status: str) -> int:
    config_id = await conn.fetchval("SELECT id FROM keno_configs ORDER BY id DESC LIMIT 1")
    tier_id = await conn.fetchval("SELECT id FROM keno_risk_tiers ORDER BY id DESC LIMIT 1")
    seed = keno.generate_server_seed()
    return await conn.fetchval(
        "INSERT INTO keno_rounds (seq, status, config_id, tier_id, server_seed, server_seed_hash) "
        "VALUES ((SELECT COALESCE(MAX(seq),0)+1 FROM keno_rounds), $1, $2, $3, $4, $5) RETURNING id",
        status, config_id, tier_id, seed, keno.server_seed_hash(seed),
    )


async def _ticket(conn, round_id: int, user_id: int, *, stake: str, status: str,
                  payout: str | None = None, jackpot: str | None = None, settled_offset_s: int = 0) -> None:
    paytable_id = await conn.fetchval("SELECT id FROM keno_paytables WHERE pick_count = 1 ORDER BY id DESC LIMIT 1")
    await conn.execute(
        "INSERT INTO keno_tickets (round_id, user_id, paytable_id, pick_count, stake, status, payout, jackpot_payout, "
        "idempotency_key, settled_at) VALUES ($1, $2, $3, 1, $4, $5, $6, $7, $8, "
        "CASE WHEN $5 = 'pending' THEN NULL ELSE now() + make_interval(secs => $9) END)",
        round_id, user_id, paytable_id, Decimal(stake), status,
        Decimal(payout) if payout is not None else None, Decimal(jackpot) if jackpot is not None else None,
        f"test-{uuid.uuid4()}", settled_offset_s,
    )


async def test_history_lists_keno_rounds_and_refunds(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await _seed_fast_config_and_tier(conn)
        user_id = await create_funded_user(conn, Decimal("100.00"))

        won = await _keno_round(conn, "completed")
        await _ticket(conn, won, user_id, stake="10.00", status="won", payout="34.00", settled_offset_s=-30)
        await _ticket(conn, won, user_id, stake="5.00", status="lost", payout="0.00", settled_offset_s=-30)
        lost = await _keno_round(conn, "completed")
        await _ticket(conn, lost, user_id, stake="20.00", status="lost", payout="0.00", settled_offset_s=-20)
        refunded = await _keno_round(conn, "failed")
        await _ticket(conn, refunded, user_id, stake="10.00", status="refunded", settled_offset_s=-10)
        # Not finished for this player yet: no history row until it is.
        # betting_closed, not betting_open: a leftover open round would be
        # the one later tests (and engines) find and bet into.
        open_round = await _keno_round(conn, "betting_closed")
        await _ticket(conn, open_round, user_id, stake="10.00", status="pending")

    try:
        history = await queries.user_history(pool, user_id)
    finally:
        # Never leave an unsettled round behind for a recovering engine.
        await pool.execute("DELETE FROM keno_tickets WHERE round_id = $1", open_round)
        await pool.execute("UPDATE keno_rounds SET status = 'voided' WHERE id = $1", open_round)

    keno_rows = {h["round_id"]: h for h in history if h["game"] == "keno"}
    assert set(keno_rows) == {won, lost, refunded}
    assert keno_rows[won] | {"ended_at": None} == {
        "game": "keno", "round_id": won, "seq": keno_rows[won]["seq"], "stake": "15.00", "ended_at": None,
        "won": True, "won_amount": "34.00", "refunded": False,
    }
    assert keno_rows[lost]["won"] is False and keno_rows[lost]["refunded"] is False
    assert keno_rows[refunded]["won"] is False and keno_rows[refunded]["refunded"] is True
    # Newest first.
    assert [h["round_id"] for h in history] == [refunded, lost, won]


async def test_a_keno_jackpot_counts_as_a_win_in_history(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await _seed_fast_config_and_tier(conn)
        user_id = await create_funded_user(conn, Decimal("100.00"))
        round_id = await _keno_round(conn, "completed")
        await _ticket(conn, round_id, user_id, stake="10.00", status="won", payout="0.00", jackpot="500.00")

    [row] = await queries.user_history(pool, user_id)
    assert row["won"] is True and row["won_amount"] == "500.00"


async def test_a_voided_bingo_round_reads_as_refunded_not_lost(pool, redis, conn, card_pool) -> None:
    room = await load_room_config(pool, await create_room(conn, stake=Decimal("20.00"), min_players=2, lobby_seconds=60))
    user_id = await create_funded_user(conn, Decimal("100.00"))
    engine = RoundEngine(pool, redis, room, card_pool)
    task = asyncio.create_task(engine.run_forever())
    try:
        assert (await engine.join(user_id, 1)).ok
        round_id = await conn.fetchval("SELECT round_id FROM round_entries WHERE user_id = $1", user_id)
        await refunds.refund_round(pool, round_id, reason="test_void")
    finally:
        await engine.stop()
        await asyncio.wait_for(task, timeout=15)

    [row] = [h for h in await queries.user_history(pool, user_id) if h["round_id"] == round_id]
    assert row["game"] == "bingo"
    assert row["won"] is False
    assert row["refunded"] is True
