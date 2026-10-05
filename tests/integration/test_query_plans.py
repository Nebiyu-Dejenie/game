"""Lookups on tables that grow without bound must be able to use an index.

Each test plans the real query with sequential scans disabled. If the plan
still scans the table, no index can serve the lookup, and on a production-
sized table every call reads all of it. Plans are checked, not timings: the
test database is too small for a missing index to show up as slowness.
"""

from __future__ import annotations


async def _plan(conn, query: str, *args: object) -> str:
    async with conn.transaction():
        await conn.execute("SET LOCAL enable_seqscan = off")
        rows = await conn.fetch(f"EXPLAIN (COSTS OFF) {query}", *args)
    return "\n".join(row[0] for row in rows)


async def test_a_bonus_is_found_by_its_grant_transaction_without_scanning_bonuses(conn) -> None:
    # grant_bonus() runs this on every grant (welcome, referral, admin),
    # after ledger.post() has row-locked the shared promo_expense balance,
    # so a full scan here held that lock for longer as bonuses grew and
    # queued every other grant behind it.
    plan = await _plan(
        conn,
        "SELECT id, user_id, rule_id, referral_of_user_id, amount, wagering_required, "
        "status, grant_txn_id FROM bonuses WHERE grant_txn_id = $1",
        1,
    )
    assert "Seq Scan on bonuses" not in plan, plan


async def test_an_autoplay_sessions_tickets_are_summed_without_scanning_every_keno_ticket(conn) -> None:
    # keno_tickets._check_autoplay_loss_limit() runs this for every
    # autoplay placement with a stop-loss: once per active session per
    # round, while that player's locks are held. keno_tickets keeps every
    # ticket ever placed.
    plan = await _plan(
        conn,
        "SELECT COALESCE(SUM(CASE status WHEN 'refunded' THEN 0 WHEN 'pending' THEN -stake "
        "ELSE COALESCE(payout, 0) + COALESCE(jackpot_payout, 0) - stake END), 0) AS worst_case_net, "
        "count(*) FILTER (WHERE status = 'pending') AS unsettled "
        "FROM keno_tickets WHERE autoplay_session_id = $1",
        1,
    )
    assert "Seq Scan on keno_tickets" not in plan, plan
