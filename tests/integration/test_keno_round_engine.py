"""Real-Postgres, real-Redis integration tests for
services/engine/keno_round_engine.py: the full round lifecycle end to
end (Part 17's "bet -> deduct -> draw -> settle -> credit"), idempotent
re-settlement, and crash recovery (stuck-round refund, resuming a
round left mid-lifecycle)."""

from __future__ import annotations

import asyncio
import itertools
import json
import random
import uuid
from decimal import Decimal

import asyncpg
import pytest

from packages.core import keno, keno_autoplay, ledger, metrics
from services.engine.keno_lock import LOCK_KEY as KENO_LOCK_KEY
from services.engine.keno_round_engine import KenoRoundEngine
from tests.integration.conftest import create_funded_user

pytestmark = pytest.mark.asyncio

_version_counter = itertools.count(random.randint(3 * 10**6, 4 * 10**6))


def _next_version() -> int:
    return next(_version_counter)


# Fast, test-only timings -- real seconds, not mocked, so the engine's
# own asyncio.sleep-based pacing is exercised for real, just compressed.
_FAST_MULTIPLIERS = {1: Decimal("3.40")}  # RTP=0.85, matches keno.py's own solved reference table


async def _seed_fast_config_and_tier(
    conn: asyncpg.Connection, *, betting_seconds: float = 1, draw_seconds: float = 1, result_seconds: float = 1
) -> None:
    version = _next_version()
    await conn.execute(
        """
        INSERT INTO keno_configs
            (version, round_cycle_seconds, betting_seconds, draw_seconds, result_seconds,
             min_picks, max_picks, draw_count, number_pool_size,
             max_tickets_per_user_per_round, per_user_round_capacity_share_bps, keno_enabled,
             beta_restricted, effective_from)
        VALUES ($1, 10, $2, $3, $4, 1, 5, 20, 80, 5, 5000, true, false, GREATEST(now() - interval '1 second', (SELECT max(effective_from) FROM keno_configs WHERE effective_from <= now()) + interval '1 microsecond'))
        """,
        version,
        betting_seconds,
        draw_seconds,
        result_seconds,
    )
    tier_id = await conn.fetchval(
        """
        INSERT INTO keno_risk_tiers
            (tier_number, version, min_reserve, max_pick_count, max_top_multiplier,
             stake_options, max_win_per_ticket, max_round_exposure_pct, paytable_profile, effective_from)
        VALUES (1, $1, 0, 5, 16, ARRAY[10.00, 20.00, 50.00]::numeric(18,2)[], 800, 0.50, 'low_variance',
                GREATEST(now() - interval '1 second', (SELECT max(effective_from) FROM keno_risk_tiers WHERE effective_from <= now()) + interval '1 microsecond'))
        RETURNING id
        """,
        version,
    )
    stats = keno.compute_paytable_stats(1, _FAST_MULTIPLIERS)
    await conn.execute(
        """
        INSERT INTO keno_paytables
            (pick_count, version, profile, multipliers, computed_rtp_bps, hit_frequency_bps,
             max_multiplier, volatility, effective_from)
        VALUES (1, $1, 'low_variance', $2::jsonb, $3, $4, $5, $6, GREATEST(now() - interval '1 second', (SELECT max(effective_from) FROM keno_paytables WHERE effective_from <= now()) + interval '1 microsecond'))
        """,
        version,
        json.dumps({str(k): str(v) for k, v in _FAST_MULTIPLIERS.items()}),
        int(stats.rtp * 10000),
        int(stats.hit_frequency * 10000),
        stats.max_multiplier,
        stats.volatility,
    )

    # current_tier_id is NOT NULL -- an UPDATE...SET NULL (an earlier
    # version of this helper) violates that constraint outright. A plain
    # upsert handles both "no row yet" (first test in the file) and
    # "row already exists" (every subsequent test) in one statement.
    await conn.execute(
        "INSERT INTO keno_tier_state (id, current_tier_id) VALUES (1, $1) "
        "ON CONFLICT (id) DO UPDATE SET current_tier_id = $1",
        tier_id,
    )

    reserve = await ledger.get_or_create_account(conn, None, "keno_reserve")
    jackpot = await ledger.get_or_create_account(conn, None, "keno_jackpot_pool")
    house_float = await ledger.get_or_create_account(conn, None, "house_float")
    await ledger.post(
        conn,
        "keno_reserve_deposit",
        [ledger.Entry(house_float.id, -Decimal("100000")), ledger.Entry(reserve.id, Decimal("100000"))],
        idempotency_key=f"test-engine-reserve-{uuid.uuid4()}",
        created_by="test",
    )
    await conn.execute("INSERT INTO keno_jackpot_pool (id, account_id) VALUES (1, $1) ON CONFLICT (id) DO NOTHING", jackpot.id)


@pytest.fixture(autouse=True)
async def _clean_keno_lock_and_rounds(pool: asyncpg.Pool, redis):
    """keno:round:lock is a true global singleton (services/engine/
    keno_lock.py) -- a prior test's engine that didn't release cleanly
    (a failure, a timeout) would otherwise make every subsequent test's
    run_forever() fail to acquire it and hang waiting for a round that
    never appears. Also closes any dangling betting_open round, same
    reasoning as test_keno_tickets.py's own autouse fixture. Also stops
    any dangling active autoplay session -- place_for_active_sessions()
    operates on every active session platform-wide, so a session an
    earlier test left active would otherwise get a real, unexpected
    ticket placed into a later test's own round the moment its engine
    opens betting."""

    async def _clean() -> None:
        await redis.delete(KENO_LOCK_KEY)
        async with pool.acquire() as conn:
            await conn.execute("UPDATE keno_rounds SET status = 'completed' WHERE status NOT IN ('completed', 'failed', 'voided')")
            await conn.execute(
                "UPDATE keno_autoplay_sessions SET status = 'stopped', stop_reason = 'test_cleanup', updated_at = now() "
                "WHERE status = 'active'"
            )

    await _clean()
    yield
    await _clean()


async def _wait_until(predicate, *, timeout: float = 15.0, interval: float = 0.1) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        if await predicate():
            return
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError(f"condition not met within {timeout}s")
        await asyncio.sleep(interval)


async def test_full_round_lifecycle_bet_to_settle(pool: asyncpg.Pool, redis) -> None:
    async with pool.acquire() as conn:
        await _seed_fast_config_and_tier(conn, betting_seconds=1, draw_seconds=1, result_seconds=1)
        user_id = await create_funded_user(conn, Decimal("1000.00"))
    balance_before = await ledger.user_balance_snapshot(pool, user_id)

    engine = KenoRoundEngine(pool, redis)
    engine_task = asyncio.create_task(engine.run_forever())
    try:
        async def _round_is_betting_open() -> bool:
            async with pool.acquire() as conn:
                row = await conn.fetchrow("SELECT id FROM keno_rounds WHERE status = 'betting_open'")
            return row is not None

        await _wait_until(_round_is_betting_open)
        async with pool.acquire() as conn:
            round_row = await conn.fetchrow("SELECT id FROM keno_rounds WHERE status = 'betting_open'")
        assert round_row is not None
        round_id = round_row["id"]

        from packages.core import keno_tickets

        ticket = await keno_tickets.place_ticket(
            pool, redis=redis, user_id=user_id, picks=[7], stake=Decimal("10"), idempotency_key=f"test-{uuid.uuid4()}"
        )
        assert ticket.round_id == round_id

        async def _round_is_completed() -> bool:
            async with pool.acquire() as conn:
                status = await conn.fetchval("SELECT status FROM keno_rounds WHERE id = $1", round_id)
            return status == "completed"

        await _wait_until(_round_is_completed, timeout=20.0)
    finally:
        engine.stop()
        await asyncio.wait_for(engine_task, timeout=15.0)

    async with pool.acquire() as conn:
        round_row = await conn.fetchrow("SELECT * FROM keno_rounds WHERE id = $1", round_id)
        ticket_row = await conn.fetchrow("SELECT * FROM keno_tickets WHERE id = $1", ticket.id)

    assert round_row["status"] == "completed"
    assert round_row["server_seed"] is not None  # revealed
    assert len(round_row["drawn_numbers"]) == 20
    assert round_row["public_seed"] is not None
    # Independent verification: anyone can recompute the draw from the
    # revealed seeds and confirm it matches what was actually settled --
    # the literal point of the commit-reveal scheme (Part 4.1).
    assert keno.verify_draw(bytes(round_row["server_seed"]), round_row["public_seed"], list(round_row["drawn_numbers"]))
    assert keno.verify_server_seed_hash(bytes(round_row["server_seed"]), round_row["server_seed_hash"])

    assert ticket_row["status"] in ("won", "lost")
    matches = keno.count_matches(frozenset({7}), list(round_row["drawn_numbers"]))
    assert ticket_row["matches"] == matches
    expected_payout = keno.compute_payout(Decimal("10"), matches, _FAST_MULTIPLIERS, max_win_per_ticket=Decimal("800"))
    assert Decimal(ticket_row["payout"]) == expected_payout

    balance_after = await ledger.user_balance_snapshot(pool, user_id)
    net_change = Decimal(balance_after["cash"]) - Decimal(balance_before["cash"])
    # Staked 10, then received expected_payout back (0 if lost).
    assert net_change == expected_payout - Decimal("10")


async def test_settlement_batches_every_ticket_in_the_round_together(pool: asyncpg.Pool, redis) -> None:
    """Spec 6.2: 'Settle in batched transactions -- no N+1.' Proves the
    batched rewrite (services/engine/keno_round_engine.py::
    _settle_tickets, one transaction for the whole round rather than one
    per ticket, a real gap this session's own spec-compliance audit
    caught) still settles every ticket in a round correctly when there's
    more than one -- five different users, five tickets, one round,
    settled together."""
    async with pool.acquire() as conn:
        await _seed_fast_config_and_tier(conn, betting_seconds=1, draw_seconds=1, result_seconds=1)
        user_ids = [await create_funded_user(conn, Decimal("1000.00")) for _ in range(5)]
    balances_before = {uid: await ledger.user_balance_snapshot(pool, uid) for uid in user_ids}

    engine = KenoRoundEngine(pool, redis)
    engine_task = asyncio.create_task(engine.run_forever())
    try:
        async def _round_is_betting_open() -> bool:
            async with pool.acquire() as conn:
                row = await conn.fetchrow("SELECT id FROM keno_rounds WHERE status = 'betting_open'")
            return row is not None

        await _wait_until(_round_is_betting_open)
        async with pool.acquire() as conn:
            round_row = await conn.fetchrow("SELECT id FROM keno_rounds WHERE status = 'betting_open'")
        assert round_row is not None
        round_id = round_row["id"]

        from packages.core import keno_tickets

        tickets = [
            await keno_tickets.place_ticket(
                pool, redis=redis, user_id=uid, picks=[1], stake=Decimal("10"), idempotency_key=f"test-batch-{uuid.uuid4()}"
            )
            for uid in user_ids
        ]
        assert {t.round_id for t in tickets} == {round_id}

        async def _round_is_completed() -> bool:
            async with pool.acquire() as conn:
                status = await conn.fetchval("SELECT status FROM keno_rounds WHERE id = $1", round_id)
            return status == "completed"

        await _wait_until(_round_is_completed, timeout=20.0)
    finally:
        engine.stop()
        await asyncio.wait_for(engine_task, timeout=15.0)

    async with pool.acquire() as conn:
        round_row = await conn.fetchrow("SELECT * FROM keno_rounds WHERE id = $1", round_id)
        ticket_rows = await conn.fetch(
            "SELECT * FROM keno_tickets WHERE id = ANY($1) ORDER BY id", [t.id for t in tickets]
        )

    assert len(ticket_rows) == 5
    matches = keno.count_matches(frozenset({1}), list(round_row["drawn_numbers"]))
    expected_payout = keno.compute_payout(Decimal("10"), matches, _FAST_MULTIPLIERS, max_win_per_ticket=Decimal("800"))
    for row in ticket_rows:
        # Every ticket picked the identical single number, so every one
        # of the five must settle to the exact same outcome -- if
        # batching mixed up which ticket got which result, this is
        # exactly the kind of thing that would catch it.
        assert row["status"] in ("won", "lost")
        assert row["matches"] == matches
        assert Decimal(row["payout"]) == expected_payout

    for uid in user_ids:
        balance_after = await ledger.user_balance_snapshot(pool, uid)
        net_change = Decimal(balance_after["cash"]) - Decimal(balances_before[uid]["cash"])
        assert net_change == expected_payout - Decimal("10")


async def test_settlement_is_idempotent_on_retry(pool: asyncpg.Pool, redis) -> None:
    """Directly exercises _settle_and_complete twice on the same round
    (simulating a crash-and-redeliver) without going through the full
    run_forever() loop -- confirms no double payout via real ledger
    totals, not just "no exception"."""
    async with pool.acquire() as conn:
        await _seed_fast_config_and_tier(conn)
        user_id = await create_funded_user(conn, Decimal("1000.00"))

        config_id = await conn.fetchval("SELECT id FROM keno_configs ORDER BY id DESC LIMIT 1")
        tier_id = await conn.fetchval("SELECT id FROM keno_risk_tiers ORDER BY id DESC LIMIT 1")
        paytable_id = await conn.fetchval("SELECT id FROM keno_paytables WHERE pick_count = 1 ORDER BY id DESC LIMIT 1")

        server_seed = keno.generate_server_seed()
        round_id = await conn.fetchval(
            """
            INSERT INTO keno_rounds (seq, status, config_id, tier_id, server_seed, server_seed_hash,
                                      public_seed, drawn_numbers, betting_closed_at, draw_completed_at)
            VALUES ((SELECT COALESCE(MAX(seq),0)+1 FROM keno_rounds), 'draw_complete', $1, $2, $3, $4, $5, $6, now(), now())
            RETURNING id
            """,
            config_id,
            tier_id,
            server_seed,
            keno.server_seed_hash(server_seed),
            "test-public-seed",
            keno.derive_keno_draw(server_seed, "test-public-seed"),
        )

        ticket_id = await conn.fetchval(
            """
            INSERT INTO keno_tickets (round_id, user_id, paytable_id, pick_count, stake, idempotency_key)
            VALUES ($1, $2, $3, 1, 10, $4) RETURNING id
            """,
            round_id,
            user_id,
            paytable_id,
            f"test-{uuid.uuid4()}",
        )
        await conn.execute("INSERT INTO keno_ticket_selections (ticket_id, number) VALUES ($1, 1)", ticket_id)

    engine = KenoRoundEngine(pool, redis)
    total_payout_1, _ = await engine._settle_tickets(round_id, list((await pool.fetchrow("SELECT drawn_numbers FROM keno_rounds WHERE id=$1", round_id))["drawn_numbers"]))
    # Ticket is now terminal (won/lost) -- a second, fully independent
    # settlement pass must be a safe no-op, not a double payout.
    total_payout_2, _ = await engine._settle_tickets(round_id, list((await pool.fetchrow("SELECT drawn_numbers FROM keno_rounds WHERE id=$1", round_id))["drawn_numbers"]))

    async with pool.acquire() as conn:
        ledger_txn_count = await conn.fetchval(
            "SELECT count(*) FROM ledger_transactions WHERE idempotency_key = $1", f"keno:settle:{round_id}:{ticket_id}"
        )
    assert ledger_txn_count <= 1
    assert total_payout_1 == total_payout_2  # both read the same persisted total, not an accumulating one


async def test_stuck_round_is_marked_failed_and_refunded(pool: asyncpg.Pool, redis) -> None:
    async with pool.acquire() as conn:
        await _seed_fast_config_and_tier(conn)
        user_id = await create_funded_user(conn, Decimal("1000.00"))
        config_id = await conn.fetchval("SELECT id FROM keno_configs ORDER BY id DESC LIMIT 1")
        tier_id = await conn.fetchval("SELECT id FROM keno_risk_tiers ORDER BY id DESC LIMIT 1")
        paytable_id = await conn.fetchval("SELECT id FROM keno_paytables WHERE pick_count = 1 ORDER BY id DESC LIMIT 1")

        server_seed = keno.generate_server_seed()
        # scheduled_at far enough in the past to exceed STUCK_ROUND_THRESHOLD_SECONDS.
        round_id = await conn.fetchval(
            """
            INSERT INTO keno_rounds (seq, status, config_id, tier_id, server_seed, server_seed_hash, scheduled_at)
            VALUES ((SELECT COALESCE(MAX(seq),0)+1 FROM keno_rounds), 'betting_open', $1, $2, $3, $4,
                    now() - interval '3600 seconds')
            RETURNING id
            """,
            config_id,
            tier_id,
            server_seed,
            keno.server_seed_hash(server_seed),
        )
        ticket_id = await conn.fetchval(
            """
            INSERT INTO keno_tickets (round_id, user_id, paytable_id, pick_count, stake, idempotency_key)
            VALUES ($1, $2, $3, 1, 25, $4) RETURNING id
            """,
            round_id,
            user_id,
            paytable_id,
            f"test-{uuid.uuid4()}",
        )
        # Mirror what place_ticket() would really have posted: a real
        # stake debit, since the refund path reverses real money, not a
        # bookkeeping-only row.
        reserve = await ledger.get_or_create_account(conn, None, "keno_reserve")
        cash = await ledger.get_or_create_account(conn, user_id, "user_cash")
        await ledger.post(
            conn, "keno_stake", [ledger.Entry(cash.id, Decimal("-25")), ledger.Entry(reserve.id, Decimal("25"))],
            idempotency_key=f"test-stake-{uuid.uuid4()}", created_by="test",
        )

    balance_before = await ledger.user_balance_snapshot(pool, user_id)

    engine = KenoRoundEngine(pool, redis)
    recovered = await engine.recover_on_startup()
    assert round_id in recovered

    async with pool.acquire() as conn:
        round_row = await conn.fetchrow("SELECT status, failure_reason FROM keno_rounds WHERE id = $1", round_id)
        ticket_row = await conn.fetchrow("SELECT status FROM keno_tickets WHERE id = $1", ticket_id)
    assert round_row["status"] == "failed"
    assert round_row["failure_reason"] == "stuck_round_recovery"
    assert ticket_row["status"] == "refunded"

    balance_after = await ledger.user_balance_snapshot(pool, user_id)
    assert Decimal(balance_after["cash"]) - Decimal(balance_before["cash"]) == Decimal("25")


async def _seed_settling_round_with_one_ticket(conn, *, scheduled_at_offset_seconds: float) -> tuple[int, int, int]:
    """Shared setup for the two tests below: a round already sitting in
    'settling' (as if a prior _settle_and_complete() attempt raised
    before ever reaching 'completed') with one real, still-pending,
    real-money-staked ticket -- so recovery has something concrete to
    either wrongly refund or correctly settle."""
    await _seed_fast_config_and_tier(conn)
    user_id = await create_funded_user(conn, Decimal("1000.00"))
    config_id = await conn.fetchval("SELECT id FROM keno_configs ORDER BY id DESC LIMIT 1")
    tier_id = await conn.fetchval("SELECT id FROM keno_risk_tiers ORDER BY id DESC LIMIT 1")
    paytable_id = await conn.fetchval("SELECT id FROM keno_paytables WHERE pick_count = 1 ORDER BY id DESC LIMIT 1")

    server_seed = keno.generate_server_seed()
    public_seed = "test-settling-recovery-public-seed"
    drawn = keno.derive_keno_draw(server_seed, public_seed)
    round_id = await conn.fetchval(
        """
        INSERT INTO keno_rounds
            (seq, status, config_id, tier_id, server_seed, server_seed_hash, public_seed, drawn_numbers,
             betting_closed_at, draw_completed_at, scheduled_at)
        VALUES ((SELECT COALESCE(MAX(seq),0)+1 FROM keno_rounds), 'settling', $1, $2, $3, $4, $5, $6,
                now(), now(), now() - make_interval(secs => $7))
        RETURNING id
        """,
        config_id, tier_id, server_seed, keno.server_seed_hash(server_seed), public_seed, drawn,
        scheduled_at_offset_seconds,
    )
    ticket_id = await conn.fetchval(
        """
        INSERT INTO keno_tickets (round_id, user_id, paytable_id, pick_count, stake, idempotency_key)
        VALUES ($1, $2, $3, 1, 10, $4) RETURNING id
        """,
        round_id, user_id, paytable_id, f"test-{uuid.uuid4()}",
    )
    await conn.execute("INSERT INTO keno_ticket_selections (ticket_id, number) VALUES ($1, 1)", ticket_id)
    reserve = await ledger.get_or_create_account(conn, None, "keno_reserve")
    cash = await ledger.get_or_create_account(conn, user_id, "user_cash")
    await ledger.post(
        conn, "keno_stake", [ledger.Entry(cash.id, Decimal("-10")), ledger.Entry(reserve.id, Decimal("10"))],
        idempotency_key=f"test-stake-{uuid.uuid4()}", created_by="test",
    )
    return round_id, ticket_id, user_id


async def test_recover_on_startup_retries_an_old_settling_round_instead_of_refunding_it(
    pool: asyncpg.Pool, redis
) -> None:
    """Spec 5.3: 'Crashed in SETTLING -> re-run; idempotency keys make
    paid tickets no-ops' -- never 'refund if it's been stuck a while,'
    the general rule every other status gets. A real bug this pass
    caught: recover_on_startup()'s age check used to apply to every
    non-terminal status uniformly, so a 'settling' round stuck past
    STUCK_ROUND_THRESHOLD_SECONDS got fail+refunded like any other stuck
    round -- silently handing a ticket its stake back even if the
    already-drawn, already-immutable result said it won. scheduled_at is
    set an hour in the past here specifically to be far past the
    threshold, proving the exemption (not just "it happens to be recent
    enough to take the normal resume path")."""
    async with pool.acquire() as conn:
        round_id, ticket_id, user_id = await _seed_settling_round_with_one_ticket(
            conn, scheduled_at_offset_seconds=3600
        )

    engine = KenoRoundEngine(pool, redis)
    recovered = await engine.recover_on_startup()
    assert round_id in recovered
    await engine._drain_settlement_tasks()

    async with pool.acquire() as conn:
        round_row = await conn.fetchrow("SELECT status FROM keno_rounds WHERE id = $1", round_id)
        ticket_row = await conn.fetchrow("SELECT status, payout FROM keno_tickets WHERE id = $1", ticket_id)
    assert round_row["status"] == "completed"
    assert ticket_row["status"] in ("won", "lost")  # never "refunded"


async def test_periodic_sweep_recovers_a_settling_round_orphaned_mid_session(pool: asyncpg.Pool, redis) -> None:
    """The other half of the same fix: recover_on_startup() alone only
    ever runs once, at run_forever()'s own start -- a round that falls
    into 'settling' and gets orphaned there *during* an otherwise-healthy
    long-running session (its _settle_and_complete() task raised and was
    swallowed, per that method's own try/except) would never be revisited
    until the whole process restarted. _recover_stuck_settling_rounds()
    (called once per round cycle from _run_one_round()) is what actually
    catches that now. Calls it directly rather than running a real
    _run_one_round() cycle, to isolate the sweep itself from everything
    else that method also does."""
    async with pool.acquire() as conn:
        round_id, ticket_id, user_id = await _seed_settling_round_with_one_ticket(
            conn, scheduled_at_offset_seconds=5  # recent -- proves this isn't just age-threshold recovery
        )

    engine = KenoRoundEngine(pool, redis)
    # Not in engine._settling_round_ids (no real task ever spawned this
    # session) -- exactly the "orphaned" state the sweep exists to find.
    await engine._recover_stuck_settling_rounds()
    await engine._drain_settlement_tasks()

    async with pool.acquire() as conn:
        round_row = await conn.fetchrow("SELECT status FROM keno_rounds WHERE id = $1", round_id)
        ticket_row = await conn.fetchrow("SELECT status FROM keno_tickets WHERE id = $1", ticket_id)
    assert round_row["status"] == "completed"
    assert ticket_row["status"] in ("won", "lost")


async def test_periodic_sweep_leaves_a_genuinely_in_flight_settling_round_alone(pool: asyncpg.Pool, redis) -> None:
    """The safety half: a round whose settlement task is real and still
    running (tracked in engine._settling_round_ids) must never be
    re-spawned by the periodic sweep -- that would settle it twice
    concurrently. Simulated by adding the round id to that set directly
    (standing in for a real in-flight task, without the timing fragility
    of actually racing one)."""
    async with pool.acquire() as conn:
        round_id, ticket_id, user_id = await _seed_settling_round_with_one_ticket(
            conn, scheduled_at_offset_seconds=5
        )

    engine = KenoRoundEngine(pool, redis)
    engine._settling_round_ids.add(round_id)
    await engine._recover_stuck_settling_rounds()

    # No new settlement task was spawned -- the round is left exactly as
    # it was (still 'settling', ticket still 'pending'), not re-processed.
    assert len(engine._settlement_tasks) == 0
    async with pool.acquire() as conn:
        round_row = await conn.fetchrow("SELECT status FROM keno_rounds WHERE id = $1", round_id)
        ticket_row = await conn.fetchrow("SELECT status FROM keno_tickets WHERE id = $1", ticket_id)
    assert round_row["status"] == "settling"
    assert ticket_row["status"] == "pending"


async def test_autoplay_session_places_real_tickets_across_real_rounds_and_exhausts(
    pool: asyncpg.Pool, redis
) -> None:
    """The full wiring, end to end, against a real running engine --
    not just packages/core/keno_autoplay.py's own functions called
    directly (see test_keno_autoplay.py for that). A rounds_total=2
    session started *before* the engine ever runs must, with zero manual
    ticket-placement calls, place exactly one real ticket per round
    across two real consecutive rounds and land on 'exhausted' -- proving
    keno_round_engine.py's own _open_betting()/_settle_tickets() hooks
    (place_for_active_sessions/record_settlement) actually fire from the
    real round lifecycle, not just from a test calling them by hand."""
    async with pool.acquire() as conn:
        await _seed_fast_config_and_tier(conn, betting_seconds=1, draw_seconds=1, result_seconds=1)
        user_id = await create_funded_user(conn, Decimal("1000.00"))
    session = await keno_autoplay.start_session(pool, user_id=user_id, picks=[7], stake=Decimal("10"), rounds_total=2)

    engine = KenoRoundEngine(pool, redis)
    engine_task = asyncio.create_task(engine.run_forever())
    try:
        async def _session_is_exhausted() -> bool:
            refreshed = await pool.fetchrow("SELECT status FROM keno_autoplay_sessions WHERE id = $1", session.id)
            return refreshed is not None and refreshed["status"] == "exhausted"

        await _wait_until(_session_is_exhausted, timeout=25.0)
    finally:
        engine.stop()
        await asyncio.wait_for(engine_task, timeout=15.0)

    async with pool.acquire() as conn:
        session_row = await conn.fetchrow(
            "SELECT status, stop_reason, rounds_placed FROM keno_autoplay_sessions WHERE id = $1", session.id
        )
        tickets = await conn.fetch(
            "SELECT round_id, status, stake, autoplay_session_id FROM keno_tickets WHERE autoplay_session_id = $1 "
            "ORDER BY id",
            session.id,
        )
    assert session_row["status"] == "exhausted"
    assert session_row["stop_reason"] == "rounds_exhausted"
    assert session_row["rounds_placed"] == 2
    assert len(tickets) == 2
    assert tickets[0]["round_id"] != tickets[1]["round_id"]  # two different real rounds, not the same one twice
    for ticket in tickets:
        assert ticket["stake"] == Decimal("10.00")
        assert ticket["status"] in ("won", "lost")  # both real rounds ran their full lifecycle to settlement

    balance = await ledger.user_balance_snapshot(pool, user_id)
    async with pool.acquire() as conn:
        payout_rows = await conn.fetch(
            "SELECT payout FROM keno_tickets WHERE autoplay_session_id = $1", session.id
        )
    total_payout = sum((Decimal(r["payout"]) for r in payout_rows), start=Decimal(0))
    # Started at 1000, staked 10 twice (20 total), got back whatever the
    # two real draws actually paid -- a real, independently-checkable
    # ledger balance, not just "no exception was raised."
    assert Decimal(balance["cash"]) == Decimal("1000.00") - Decimal("20.00") + total_payout


# --- oldest-nonterminal-round gauge (08-runbook.md's own documented
# "no configured alert for a stuck round" gap, closed 2026-09-24) --------


async def test_oldest_nonterminal_round_gauge_reflects_a_real_stuck_round(pool: asyncpg.Pool, redis) -> None:
    # Deliberately far older than anything any other test in this shared
    # dev database could plausibly leave lingering -- makes this round
    # the real MIN(scheduled_at) regardless of ambient state, so the
    # assertion doesn't need this file's own cleanup fixture to have run
    # first.
    async with pool.acquire() as conn:
        await _seed_settling_round_with_one_ticket(conn, scheduled_at_offset_seconds=10_000)

    engine = KenoRoundEngine(pool, redis)
    await engine._update_oldest_nonterminal_round_gauge()

    reported_age = metrics.keno_oldest_nonterminal_round_age_seconds._value.get()
    # Age only grows between seeding and measurement, never shrinks --
    # >= the seeded value (with a little headroom for real wall-clock
    # drift during the test itself) is the correct, non-flaky bound,
    # not an exact equality that would need perfect timing.
    assert reported_age >= 10_000


async def test_oldest_nonterminal_round_gauge_is_zero_when_nothing_is_stuck(pool: asyncpg.Pool, redis) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE keno_rounds SET status = 'completed' WHERE status NOT IN ('completed', 'failed', 'voided')"
        )

    engine = KenoRoundEngine(pool, redis)
    await engine._update_oldest_nonterminal_round_gauge()

    assert metrics.keno_oldest_nonterminal_round_age_seconds._value.get() == 0.0


# --- Stuck-round recovery after the draw (platform audit, 2026-09-29) --------


@pytest.mark.parametrize("stuck_status", ["drawing", "draw_complete"])
async def test_recovery_settles_an_old_round_whose_numbers_were_already_drawn(
    pool: asyncpg.Pool, redis, stuck_status: str
) -> None:
    """Once drawn_numbers is persisted the result exists and players have
    watched it being revealed, so recovery must settle the round however old
    it is. Refunding it instead takes a winner's payout away and hands them
    their stake back. The ticket here picks the first drawn number, so it
    won."""
    async with pool.acquire() as conn:
        round_id, ticket_id, user_id = await _seed_settling_round_with_one_ticket(
            conn, scheduled_at_offset_seconds=3600
        )
        drawn = await conn.fetchval("SELECT drawn_numbers FROM keno_rounds WHERE id = $1", round_id)
        await conn.execute(
            "UPDATE keno_ticket_selections SET number = $2 WHERE ticket_id = $1", ticket_id, drawn[0]
        )
        await conn.execute(
            "UPDATE keno_rounds SET status = $2, reveal_index = $3 WHERE id = $1",
            round_id, stuck_status, 5 if stuck_status == "drawing" else len(drawn),
        )
    balance_before = await ledger.user_balance_snapshot(pool, user_id)

    engine = KenoRoundEngine(pool, redis)
    assert await engine._lock.acquire()  # the reveal loop only runs while the lock is held
    try:
        recovered = await engine.recover_on_startup()
        assert round_id in recovered
        await engine._drain_settlement_tasks()
    finally:
        await engine._lock.release()

    async with pool.acquire() as conn:
        round_row = await conn.fetchrow("SELECT status FROM keno_rounds WHERE id = $1", round_id)
        ticket_row = await conn.fetchrow("SELECT status, payout FROM keno_tickets WHERE id = $1", ticket_id)
    assert (round_row["status"], ticket_row["status"]) == ("completed", "won")
    assert ticket_row["payout"] == Decimal("34.00")  # 10 x 3.40, not the 10.00 stake back
    balance_after = await ledger.user_balance_snapshot(pool, user_id)
    assert Decimal(balance_after["cash"]) - Decimal(balance_before["cash"]) == Decimal("34.00")


async def _wait_for_lock_waiters(pool: asyncpg.Pool, count: int, *, timeout: float = 10.0) -> None:
    async def _enough_waiting() -> bool:
        async with pool.acquire() as conn:
            waiting = await conn.fetchval(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND wait_event_type = 'Lock'"
            )
        return waiting >= count

    await _wait_until(_enough_waiting, timeout=timeout)


async def test_a_ticket_placed_while_a_stuck_round_is_refunded_is_never_left_pending(
    pool: asyncpg.Pool, redis
) -> None:
    """While the worker is down its round stays 'betting_open', so the
    gateway keeps taking tickets for it. When the worker returns it refunds
    the stuck round. A ticket whose placement is still in flight when the
    refund reads the round's tickets must end up refunded, or be rejected.
    It must never be left 'pending' on a 'failed' round, which nothing ever
    settles or refunds.

    The placement is paused mid-transaction, after it has locked the round,
    by holding the player's balance row; the refund runs meanwhile."""
    from packages.core import keno_tickets

    async with pool.acquire() as conn:
        await _seed_fast_config_and_tier(conn)
        user_id = await create_funded_user(conn, Decimal("1000.00"))
        config_id = await conn.fetchval("SELECT id FROM keno_configs ORDER BY id DESC LIMIT 1")
        tier_id = await conn.fetchval("SELECT id FROM keno_risk_tiers ORDER BY id DESC LIMIT 1")
        server_seed = keno.generate_server_seed()
        round_id = await conn.fetchval(
            """
            INSERT INTO keno_rounds (seq, status, config_id, tier_id, server_seed, server_seed_hash, scheduled_at)
            VALUES ((SELECT COALESCE(MAX(seq),0)+1 FROM keno_rounds), 'betting_open', $1, $2, $3, $4,
                    now() - interval '3600 seconds')
            RETURNING id
            """,
            config_id, tier_id, server_seed, keno.server_seed_hash(server_seed),
        )
        cash = await ledger.get_or_create_account(conn, user_id, "user_cash")

    blocker = await pool.acquire()
    engine = KenoRoundEngine(pool, redis)
    try:
        blocker_txn = blocker.transaction()
        await blocker_txn.start()
        await blocker.execute("SELECT 1 FROM account_balances WHERE account_id = $1 FOR UPDATE", cash.id)

        placement = asyncio.create_task(
            keno_tickets.place_ticket(
                pool, redis, user_id=user_id, picks=[7], stake=Decimal("10.00"), idempotency_key=str(uuid.uuid4())
            )
        )
        await _wait_for_lock_waiters(pool, 1)  # the placement, holding the round row, waits on the balance
        refund = asyncio.create_task(engine._fail_and_refund_round(round_id, reason="stuck_round_recovery"))
        await _wait_for_lock_waiters(pool, 2)  # the refund now waits on the round row too
        await blocker_txn.rollback()
        placement_result = (await asyncio.gather(placement, return_exceptions=True))[0]
        await refund
    finally:
        await pool.release(blocker)

    async with pool.acquire() as conn:
        round_status = await conn.fetchval("SELECT status FROM keno_rounds WHERE id = $1", round_id)
        ticket_statuses = [
            r["status"] for r in await conn.fetch("SELECT status FROM keno_tickets WHERE round_id = $1", round_id)
        ]
        cash_balance = await ledger.balance(conn, cash.id)
    assert round_status == "failed"
    assert "pending" not in ticket_statuses, f"placement={placement_result!r}, tickets={ticket_statuses}"
    assert cash_balance == Decimal("1000.00")  # refunded, or never charged


async def test_the_refund_path_refuses_a_round_whose_numbers_were_drawn(pool: asyncpg.Pool, redis) -> None:
    async with pool.acquire() as conn:
        round_id, ticket_id, _ = await _seed_settling_round_with_one_ticket(conn, scheduled_at_offset_seconds=3600)
        await conn.execute("UPDATE keno_rounds SET status = 'draw_complete' WHERE id = $1", round_id)

    await KenoRoundEngine(pool, redis)._fail_and_refund_round(round_id, reason="stuck_round_recovery")

    async with pool.acquire() as conn:
        round_status = await conn.fetchval("SELECT status FROM keno_rounds WHERE id = $1", round_id)
        ticket_status = await conn.fetchval("SELECT status FROM keno_tickets WHERE id = $1", ticket_id)
    assert (round_status, ticket_status) == ("draw_complete", "pending")


async def test_a_drawn_round_whose_settlement_died_before_settling_is_settled_on_the_next_cycle(
    pool: asyncpg.Pool, redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The per-cycle sweep retried only 'settling' rounds. A settlement task
    that failed before it wrote 'settling' (a broken pooled connection, a
    pool-acquire timeout) left its round in 'draw_complete', which nothing
    looked at again until the process restarted: the winners stayed unpaid
    while later rounds ran normally. Here the round's move to 'settling'
    fails once; every draw is rigged to hit the ticket's pick, so it won."""
    monkeypatch.setattr(keno, "derive_keno_draw", lambda *args, **kwargs: list(range(1, 21)))
    target: dict[str, int] = {}
    failed_once = asyncio.Event()
    original_record_event = KenoRoundEngine._record_event

    async def _record_event_failing_once(self, conn, round_id, from_status, to_status, *, reason=None):
        if to_status == "settling" and round_id == target.get("id") and not failed_once.is_set():
            failed_once.set()
            raise asyncpg.exceptions.ConnectionDoesNotExistError("connection was closed in the middle of operation")
        await original_record_event(self, conn, round_id, from_status, to_status, reason=reason)

    monkeypatch.setattr(KenoRoundEngine, "_record_event", _record_event_failing_once)
    async with pool.acquire() as conn:
        await _seed_fast_config_and_tier(conn, betting_seconds=1, draw_seconds=1, result_seconds=1)
        user_id = await create_funded_user(conn, Decimal("1000.00"))
    balance_before = await ledger.user_balance_snapshot(pool, user_id)

    from packages.core import keno_tickets

    engine = KenoRoundEngine(pool, redis)
    engine_task = asyncio.create_task(engine.run_forever())
    try:
        async def _round_is_betting_open() -> bool:
            return await pool.fetchval("SELECT id FROM keno_rounds WHERE status = 'betting_open'") is not None

        await _wait_until(_round_is_betting_open)
        round_id = await pool.fetchval("SELECT id FROM keno_rounds WHERE status = 'betting_open'")
        assert round_id is not None
        target["id"] = round_id
        ticket = await keno_tickets.place_ticket(
            pool, redis=redis, user_id=user_id, picks=[7], stake=Decimal("10"), idempotency_key=f"test-{uuid.uuid4()}"
        )
        assert ticket.round_id == round_id

        await asyncio.wait_for(failed_once.wait(), timeout=15.0)

        # Two more rounds open while the process keeps running, so the sweep
        # at the start of each has had its chance.
        async def _two_later_rounds_betting() -> bool:
            later = await pool.fetchval(
                "SELECT count(*) FROM keno_rounds WHERE id > $1 AND status <> 'scheduled'", round_id
            )
            return later >= 2

        await _wait_until(_two_later_rounds_betting, timeout=20.0)
    finally:
        engine.stop()
        await asyncio.wait_for(engine_task, timeout=15.0)  # drains any settlement task still running

    async with pool.acquire() as conn:
        round_status = await conn.fetchval("SELECT status FROM keno_rounds WHERE id = $1", round_id)
        ticket_row = await conn.fetchrow("SELECT status, payout FROM keno_tickets WHERE id = $1", ticket.id)
    assert (round_status, ticket_row["status"]) == ("completed", "won")
    assert ticket_row["payout"] == Decimal("34.00")
    balance_after = await ledger.user_balance_snapshot(pool, user_id)
    assert Decimal(balance_after["cash"]) - Decimal(balance_before["cash"]) == Decimal("24.00")  # -10 stake, +34


async def test_autoplay_stop_loss_is_not_overshot_by_the_round_that_opens_during_settlement(
    pool: asyncpg.Pool, redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Round N's settlement runs in the background while round N+1's betting
    opens, and autoplay places its N+1 ticket right then. A session whose
    loss limit round N's loss reaches must not also be charged for N+1.
    Every draw here misses the session's pick, so the first loss (10.00)
    reaches the 10.00 stop-loss: exactly one ticket, then 'stop_on_loss'."""
    monkeypatch.setattr(keno, "derive_keno_draw", lambda *args, **kwargs: list(range(21, 41)))
    async with pool.acquire() as conn:
        await _seed_fast_config_and_tier(conn, betting_seconds=1, draw_seconds=1, result_seconds=1)
        user_id = await create_funded_user(conn, Decimal("1000.00"))
    session = await keno_autoplay.start_session(
        pool, user_id=user_id, picks=[7], stake=Decimal("10"), stop_on_loss_amount=Decimal("10")
    )

    engine = KenoRoundEngine(pool, redis)
    engine_task = asyncio.create_task(engine.run_forever())
    try:
        async def _session_stopped_and_settled() -> bool:
            row = await pool.fetchrow("SELECT status FROM keno_autoplay_sessions WHERE id = $1", session.id)
            pending = await pool.fetchval(
                "SELECT count(*) FROM keno_tickets WHERE autoplay_session_id = $1 AND status = 'pending'", session.id
            )
            return row["status"] != "active" and pending == 0

        await _wait_until(_session_stopped_and_settled, timeout=25.0)
    finally:
        engine.stop()
        await asyncio.wait_for(engine_task, timeout=15.0)

    async with pool.acquire() as conn:
        session_row = await conn.fetchrow(
            "SELECT status, stop_reason FROM keno_autoplay_sessions WHERE id = $1", session.id
        )
        tickets = await conn.fetch(
            "SELECT status FROM keno_tickets WHERE autoplay_session_id = $1 ORDER BY id", session.id
        )
        cash = await ledger.balance(conn, (await ledger.get_or_create_account(conn, user_id, "user_cash")).id)
    assert (session_row["status"], session_row["stop_reason"]) == ("stopped", "stop_on_loss")
    assert [t["status"] for t in tickets] == ["lost"]
    assert cash == Decimal("990.00")  # lost exactly the 10.00 limit, not 20.00


async def _top_up_jackpot(pool: asyncpg.Pool, amount: Decimal) -> None:
    """A stake's jackpot diversion, as place_ticket posts it (kind
    keno_stake), all of it into the pool."""
    async with pool.acquire() as conn:
        user_id = await create_funded_user(conn, amount)
        cash = await ledger.get_or_create_account(conn, user_id, "user_cash")
        jackpot = await ledger.get_or_create_account(conn, None, "keno_jackpot_pool")
        await ledger.post(
            conn, "keno_stake", [ledger.Entry(cash.id, -amount), ledger.Entry(jackpot.id, amount)],
            idempotency_key=f"test-jackpot-top-up-{uuid.uuid4()}", created_by="test",
        )


async def test_an_overlapping_second_settlement_pass_does_not_rewrite_a_paid_jackpot(pool, redis, monkeypatch):
    """Platform audit #56: _settle_one_ticket posted the payout before
    claiming the ticket, and _pay_jackpot ran whether or not the claim
    succeeded. A second settlement pass that read the ticket as pending
    before the first committed found the jackpot's ledger key already
    posted (so no second payment), but then wrote the pool's newly
    accumulated balance into keno_tickets.jackpot_payout, so the ticket
    and the round total showed a jackpot the player was never paid."""
    async with pool.acquire() as conn:
        await _seed_fast_config_and_tier(conn)
        config_id = await conn.fetchval("SELECT id FROM keno_configs ORDER BY id DESC LIMIT 1")
        tier_id = await conn.fetchval("SELECT id FROM keno_risk_tiers ORDER BY id DESC LIMIT 1")
        paytable_id = await conn.fetchval("SELECT id FROM keno_paytables ORDER BY id DESC LIMIT 1")
        drawn = list(range(1, 21))
        round_id = await conn.fetchval(
            "INSERT INTO keno_rounds (seq, status, config_id, tier_id, server_seed, server_seed_hash, drawn_numbers) "
            "VALUES ((SELECT COALESCE(MAX(seq), 0) + 1 FROM keno_rounds), 'settling', $1, $2, $3, 'h', $4) "
            "RETURNING id",
            config_id, tier_id, b"seed", drawn,
        )
        user_id = await create_funded_user(conn, Decimal("0"))
        ticket_id = await conn.fetchval(
            "INSERT INTO keno_tickets (round_id, user_id, paytable_id, pick_count, stake, status, idempotency_key) "
            "VALUES ($1, $2, $3, 5, 10, 'pending', $4) RETURNING id",
            round_id, user_id, paytable_id, f"test-jackpot-race-{uuid.uuid4()}",
        )
        await conn.executemany(
            "INSERT INTO keno_ticket_selections (ticket_id, number) VALUES ($1, $2)",
            [(ticket_id, n) for n in (1, 2, 3, 4, 5)],
        )
    await _top_up_jackpot(pool, Decimal("500.00"))

    engine = KenoRoundEngine(pool, redis)
    first_inside, release_first = asyncio.Event(), asyncio.Event()
    real_settle_one, real_pay = engine._settle_one_ticket, engine._pay_jackpot
    settle_calls = pay_calls = 0

    async def settle_one(conn, **kwargs):
        nonlocal settle_calls
        settle_calls += 1
        mine = settle_calls
        settled = await real_settle_one(conn, **kwargs)
        if mine == 1:  # hold the first pass's transaction open
            first_inside.set()
            await release_first.wait()
        return settled

    async def pay(conn, **kwargs):
        nonlocal pay_calls
        pay_calls += 1
        if pay_calls == 2:  # stakes keep feeding the pool between the passes
            await _top_up_jackpot(pool, Decimal("777.00"))
        return await real_pay(conn, **kwargs)

    monkeypatch.setattr(engine, "_settle_one_ticket", settle_one)
    monkeypatch.setattr(engine, "_pay_jackpot", pay)

    first = asyncio.create_task(engine._settle_tickets(round_id, drawn))
    await asyncio.wait_for(first_inside.wait(), timeout=10)
    second = asyncio.create_task(engine._settle_tickets(round_id, drawn))
    await asyncio.sleep(0.5)  # the second pass has read the ticket as pending and is now waiting on the first
    release_first.set()
    await asyncio.wait_for(asyncio.gather(first, second), timeout=15)

    async with pool.acquire() as conn:
        paid = await conn.fetchval(
            "SELECT e.amount FROM ledger_transactions t JOIN ledger_entries e ON e.transaction_id = t.id "
            "JOIN accounts a ON a.id = e.account_id "
            "WHERE t.idempotency_key = $1 AND a.kind = 'user_cash'",
            f"keno:jackpot:{round_id}:{ticket_id}",
        )
        recorded = await conn.fetchval("SELECT jackpot_payout FROM keno_tickets WHERE id = $1", ticket_id)
    assert paid is not None and paid >= Decimal("500.00")
    assert recorded == paid


@pytest.mark.xfail(strict=True, reason="rule for several jackpot winners in one round: operator decision pending (#57)")
async def test_two_jackpot_winners_in_one_round_both_get_a_share(pool, redis):
    """Platform audit #57: two 5-spot tickets that both hit 5/5 in one
    round. The first one in the (unordered) fetch took the whole pool and
    the other got nothing, so row order, not any stated rule, decided who
    won. The recommended rule, an equal split with the leftover cent kept
    in the pool, is the operator's to confirm."""
    async with pool.acquire() as conn:
        await _seed_fast_config_and_tier(conn)
        config_id = await conn.fetchval("SELECT id FROM keno_configs ORDER BY id DESC LIMIT 1")
        tier_id = await conn.fetchval("SELECT id FROM keno_risk_tiers ORDER BY id DESC LIMIT 1")
        paytable_id = await conn.fetchval("SELECT id FROM keno_paytables ORDER BY id DESC LIMIT 1")
        drawn = list(range(1, 21))
        round_id = await conn.fetchval(
            "INSERT INTO keno_rounds (seq, status, config_id, tier_id, server_seed, server_seed_hash, drawn_numbers) "
            "VALUES ((SELECT COALESCE(MAX(seq), 0) + 1 FROM keno_rounds), 'settling', $1, $2, $3, 'h', $4) "
            "RETURNING id",
            config_id, tier_id, b"seed", drawn,
        )
        ticket_ids = []
        for _ in range(2):
            user_id = await create_funded_user(conn, Decimal("0"))
            ticket_id = await conn.fetchval(
                "INSERT INTO keno_tickets (round_id, user_id, paytable_id, pick_count, stake, status, idempotency_key) "
                "VALUES ($1, $2, $3, 5, 10, 'pending', $4) RETURNING id",
                round_id, user_id, paytable_id, f"test-two-jackpots-{uuid.uuid4()}",
            )
            await conn.executemany(
                "INSERT INTO keno_ticket_selections (ticket_id, number) VALUES ($1, $2)",
                [(ticket_id, n) for n in (1, 2, 3, 4, 5)],
            )
            ticket_ids.append(ticket_id)
    await _top_up_jackpot(pool, Decimal("1000.00"))

    await KenoRoundEngine(pool, redis)._settle_tickets(round_id, drawn)

    async with pool.acquire() as conn:
        shares = [
            await conn.fetchval("SELECT COALESCE(jackpot_payout, 0) FROM keno_tickets WHERE id = $1", t)
            for t in ticket_ids
        ]
    assert all(share > 0 for share in shares), shares


async def test_a_refund_returns_the_full_stake_from_the_reserve_and_leaves_the_jackpot_slice_in_the_pool(
    pool: asyncpg.Pool, redis
) -> None:
    """Pins today's refund accounting (2026-10-01). Change it only together
    with the operator's decision D14 in docs/PROJECT_STATE.md.

    A 20.00 stake is split at placement: 19.70 to keno_reserve, 0.30 (1.5%)
    to keno_jackpot_pool. A refund pays the player the full 20.00, all of it
    from keno_reserve, and leaves the 0.30 in the pool. Net effect of a
    stake and its refund: the player is whole, the reserve is down 0.30, the
    pool is up 0.30. The spec (keno.md 8.3) calls the jackpot player-funded,
    but doesn't say what a refund does with the slice."""
    async with pool.acquire() as conn:
        await _seed_fast_config_and_tier(conn)
        user_id = await create_funded_user(conn, Decimal("1000.00"))
        config_id = await conn.fetchval("SELECT id FROM keno_configs ORDER BY id DESC LIMIT 1")
        tier_id = await conn.fetchval("SELECT id FROM keno_risk_tiers ORDER BY id DESC LIMIT 1")
        paytable_id = await conn.fetchval("SELECT id FROM keno_paytables WHERE pick_count = 1 ORDER BY id DESC LIMIT 1")
        server_seed = keno.generate_server_seed()
        round_id = await conn.fetchval(
            "INSERT INTO keno_rounds (seq, status, config_id, tier_id, server_seed, server_seed_hash) "
            "VALUES ((SELECT COALESCE(MAX(seq),0)+1 FROM keno_rounds), 'betting_open', $1, $2, $3, $4) RETURNING id",
            config_id, tier_id, server_seed, keno.server_seed_hash(server_seed),
        )
        await conn.fetchval(
            "INSERT INTO keno_tickets (round_id, user_id, paytable_id, pick_count, stake, idempotency_key) "
            "VALUES ($1, $2, $3, 1, 20, $4) RETURNING id",
            round_id, user_id, paytable_id, f"test-{uuid.uuid4()}",
        )
        reserve = await ledger.get_or_create_account(conn, None, "keno_reserve")
        jackpot = await ledger.get_or_create_account(conn, None, "keno_jackpot_pool")
        cash = await ledger.get_or_create_account(conn, user_id, "user_cash")
        # The split place_ticket() posts at the default 150 bps.
        await ledger.post(
            conn, "keno_stake",
            [ledger.Entry(cash.id, Decimal("-20")), ledger.Entry(reserve.id, Decimal("19.70")),
             ledger.Entry(jackpot.id, Decimal("0.30"))],
            idempotency_key=f"test-stake-{uuid.uuid4()}", created_by="test",
        )
        before = [await ledger.balance(conn, a.id) for a in (cash, reserve, jackpot)]

    await KenoRoundEngine(pool, redis)._fail_and_refund_round(round_id, reason="stuck_round_recovery")

    async with pool.acquire() as conn:
        after = [await ledger.balance(conn, a.id) for a in (cash, reserve, jackpot)]
    changes = [a - b for a, b in zip(after, before)]
    assert changes == [Decimal("20.00"), Decimal("-20.00"), Decimal("0.00")]  # player, reserve, pool


async def test_a_refunded_ticket_is_announced_to_its_player_with_their_new_balance(pool: asyncpg.Pool, redis) -> None:
    """A failed round's refunds used to be silent: the round-level
    keno.round.completed(failed) went out, but the player got no word about
    their ticket and no balance push. The Mini App kept the ticket pending,
    then showed it as lost (2026-10-02)."""
    async with pool.acquire() as conn:
        await _seed_fast_config_and_tier(conn)
        user_id = await create_funded_user(conn, Decimal("1000.00"))
        config_id = await conn.fetchval("SELECT id FROM keno_configs ORDER BY id DESC LIMIT 1")
        tier_id = await conn.fetchval("SELECT id FROM keno_risk_tiers ORDER BY id DESC LIMIT 1")
        paytable_id = await conn.fetchval("SELECT id FROM keno_paytables WHERE pick_count = 1 ORDER BY id DESC LIMIT 1")
        server_seed = keno.generate_server_seed()
        round_id = await conn.fetchval(
            "INSERT INTO keno_rounds (seq, status, config_id, tier_id, server_seed, server_seed_hash) "
            "VALUES ((SELECT COALESCE(MAX(seq),0)+1 FROM keno_rounds), 'betting_open', $1, $2, $3, $4) RETURNING id",
            config_id, tier_id, server_seed, keno.server_seed_hash(server_seed),
        )
        ticket_id = await conn.fetchval(
            "INSERT INTO keno_tickets (round_id, user_id, paytable_id, pick_count, stake, idempotency_key) "
            "VALUES ($1, $2, $3, 1, 20, $4) RETURNING id",
            round_id, user_id, paytable_id, f"test-{uuid.uuid4()}",
        )
        reserve = await ledger.get_or_create_account(conn, None, "keno_reserve")
        cash = await ledger.get_or_create_account(conn, user_id, "user_cash")
        await ledger.post(
            conn, "keno_stake", [ledger.Entry(cash.id, Decimal("-20")), ledger.Entry(reserve.id, Decimal("20"))],
            idempotency_key=f"test-stake-{uuid.uuid4()}", created_by="test",
        )

    pubsub = redis.pubsub()
    await pubsub.subscribe(f"user:{user_id}")
    try:
        await KenoRoundEngine(pool, redis)._fail_and_refund_round(round_id, reason="stuck_round_recovery")
        received: list[dict] = []
        deadline = asyncio.get_running_loop().time() + 5
        while asyncio.get_running_loop().time() < deadline and len(received) < 2:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
            if msg is not None:
                received.append(json.loads(msg["data"]))
    finally:
        await pubsub.aclose()

    refunded = [m for m in received if m.get("t") == "keno.ticket.refunded"]
    assert refunded == [{"t": "keno.ticket.refunded", "round_id": round_id, "ticket_id": ticket_id, "stake": "20.00"}]
    assert any(m.get("t") == "balance_update" and m.get("cash") == "1000.00" for m in received), received
