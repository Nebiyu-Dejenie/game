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
