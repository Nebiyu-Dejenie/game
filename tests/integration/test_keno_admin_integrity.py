"""Admin Keno configuration: writes that could break the game's money or
undo an operator's decision (audit of 2026-10-02).

- A paytable with a negative multiplier passed the RTP guardrail: the
  negative term lowered the computed RTP, but a negative payout is never
  paid, so the real RTP was far higher (a 1-spot with 0 hits at -1 and 1
  hit at 6.88 computes to 97% and really pays 172%).
- NaN, Infinity and pick counts outside 1-10 raised 500s.
- A config write read its base before taking the table lock, so a rules
  edit that waited on a concurrent kill switch wrote keno_enabled=true
  back over it.
- POST /keno/configs could set keno_enabled, outside the audited kill
  switch.
- A tier edit could be based on an old version, silently reverting every
  newer change.
- place_ticket used the newest config, not the one the round was opened
  with, so a change took effect mid-round.
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import asyncpg
import pytest

from packages.core import keno_tickets
from services.admin import keno_queries as admin_keno
from tests.integration.conftest import create_funded_user
from tests.integration.test_admin_auth import create_test_admin
from tests.integration.test_keno_config_management import _baseline_config, _tier
from tests.integration.test_keno_tickets import _fund_reserve, _seed_keno_round

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def _close_any_dangling_betting_open_round(pool: asyncpg.Pool):
    async def _close() -> None:
        async with pool.acquire() as conn:
            await conn.execute("UPDATE keno_rounds SET status = 'completed' WHERE status = 'betting_open'")

    await _close()
    yield
    await _close()


@pytest.mark.parametrize(
    "pick_count, multipliers",
    [
        (1, {"0": "-1", "1": "6.88"}),  # computes to 97%, really pays 172%
        (1, {"1": "NaN"}),
        (1, {"1": "Infinity"}),
        (11, {"11": "100"}),
        (3, {"4": "10"}),  # more matches than picks
    ],
)
async def test_a_paytable_that_cannot_be_priced_honestly_is_refused(pool, pick_count, multipliers):
    admin_id, *_ = await create_test_admin(pool, role="superadmin")
    try:
        with pytest.raises(admin_keno.InvalidKenoConfig):
            await admin_keno.create_paytable_admin(
                pool, admin_id=admin_id, pick_count=pick_count, profile="standard", multipliers=multipliers,
                reason="should be refused",
            )
    finally:
        # On the old code the first case is accepted; never leave it live.
        await pool.execute("DELETE FROM keno_paytables WHERE created_by_admin_id = $1", admin_id)


async def test_the_create_route_cannot_flip_keno_enabled(pool):
    admin_id, *_ = await create_test_admin(pool, role="superadmin")
    await _baseline_config(pool, admin_id)
    with pytest.raises(admin_keno.InvalidKenoConfig, match="kill switch"):
        await admin_keno.create_config_admin(
            pool, admin_id=admin_id, round_cycle_seconds=45, betting_seconds=25, draw_seconds=12,
            result_seconds=8, min_picks=1, max_picks=10, max_tickets_per_user_per_round=3,
            per_user_round_capacity_share_bps=2000, jackpot_diversion_bps=150, keno_enabled=False,
            reason="switch it off the side way",
        )
    assert (await admin_keno.get_active_config_admin(pool))["keno_enabled"] is True


async def test_a_rules_edit_waiting_on_the_kill_switch_does_not_switch_keno_back_on(pool):
    admin_id, *_ = await create_test_admin(pool, role="superadmin")
    base = await _baseline_config(pool, admin_id)
    holder = await pool.acquire()
    try:
        tx = holder.transaction()
        await tx.start()
        await holder.execute("LOCK TABLE keno_configs IN SHARE ROW EXCLUSIVE MODE")
        edit = asyncio.create_task(admin_keno.update_config_admin(
            pool, admin_id=admin_id, changes={"max_autoplay_rounds": base["max_autoplay_rounds"] + 1},
            reason="a rules edit racing the kill switch",
        ))
        for _ in range(400):
            if await pool.fetchval(
                "SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock' "
                "AND query ILIKE '%LOCK TABLE keno_configs%' AND pid <> pg_backend_pid()"
            ):
                break
            await asyncio.sleep(0.025)
        else:
            raise AssertionError("the rules edit never queued behind the lock")
        # The kill switch commits while the edit waits.
        values = {k: v for k, v in base.items() if k not in admin_keno._CONFIG_IDENTITY_COLUMNS}
        values["keno_enabled"] = False
        await admin_keno._insert_config_version(holder, values=values, admin_id=admin_id)
        await tx.commit()
        await asyncio.wait_for(edit, timeout=10)

        active = await admin_keno.get_active_config_admin(pool)
        assert active["keno_enabled"] is False
        assert active["max_autoplay_rounds"] == base["max_autoplay_rounds"] + 1
    finally:
        await pool.release(holder)
        await admin_keno.set_keno_enabled_admin(pool, admin_id=admin_id, enabled=True, reason="restore")


async def test_editing_an_old_tier_version_is_refused(pool):
    admin_id, *_ = await create_test_admin(pool, role="superadmin")
    first = await _tier(pool, admin_id)
    await admin_keno.update_tier_admin(
        pool, admin_id=admin_id, tier_id=first["id"], changes={"max_win_per_ticket": Decimal("900")},
        reason="newer edit",
    )
    with pytest.raises(admin_keno.InvalidKenoConfig, match="newer version"):
        await admin_keno.update_tier_admin(
            pool, admin_id=admin_id, tier_id=first["id"], changes={"max_round_exposure_pct": Decimal("0.2")},
            reason="edit from the stale version",
        )


async def test_a_config_change_waits_for_the_next_round(pool, redis):
    """The round was opened allowing 3 tickets per player; a newer config
    allowing 1 must not apply until the next round."""
    async with pool.acquire() as conn:
        await _seed_keno_round(conn, max_tickets_per_user_per_round=3)
        await _fund_reserve(conn, Decimal("40000"))
        user_id = await create_funded_user(conn, Decimal("1000.00"))
        newer_id = await conn.fetchval(
            """INSERT INTO keno_configs (version, round_cycle_seconds, betting_seconds, draw_seconds, result_seconds,
                   max_tickets_per_user_per_round, keno_enabled, beta_restricted, effective_from)
               SELECT MAX(version) + 1, 45, 25, 12, 8, 1, true, false, now() FROM keno_configs RETURNING id"""
        )
    try:
        for picks in ([7], [8]):
            await keno_tickets.place_ticket(
                pool, redis, user_id=user_id, picks=picks, stake=Decimal("10"),
                idempotency_key=f"test-{uuid.uuid4()}",
            )
    finally:
        await pool.execute("DELETE FROM keno_configs WHERE id = $1", newer_id)


# --- operator decisions (D15, D16 in docs/PROJECT_STATE.md) -----------------


@pytest.mark.xfail(strict=True, reason="D15: whether RTP ceiling + jackpot diversion must stay under 100% is the operator's call")
async def test_a_config_whose_rtp_ceiling_plus_jackpot_diversion_reaches_100_percent_is_refused(pool):
    """The paytable pays up to the RTP ceiling out of the reserve, which
    only receives the stake minus the jackpot slice; the jackpot pays the
    slice back. At a 97% ceiling and 10% diversion players get about 107%
    of stakes. Production runs at 82% + 1.5%, so this is latent."""
    admin_id, *_ = await create_test_admin(pool, role="superadmin")
    await _baseline_config(pool, admin_id)
    try:
        with pytest.raises(admin_keno.InvalidKenoConfig):
            await admin_keno.update_config_admin(
                pool, admin_id=admin_id, changes={"jackpot_diversion_bps": 1000}, reason="RTP + diversion > 100%",
            )
    finally:
        await admin_keno.update_config_admin(
            pool, admin_id=admin_id, changes={"jackpot_diversion_bps": 150}, reason="restore",
        )


@pytest.mark.xfail(strict=True, reason="D16: whether max_autoplay_rounds also limits sessions with no round count is the operator's call")
async def test_an_autoplay_session_with_no_round_count_is_held_to_the_configured_maximum(pool, conn):
    """max_autoplay_rounds is checked only when the player names a round
    count; "no limit" with a stop-on-win/loss amount runs past it."""
    from packages.core import keno_autoplay

    admin_id, *_ = await create_test_admin(pool, role="superadmin")
    await _baseline_config(pool, admin_id, max_autoplay_rounds=5)
    await _seed_keno_round(conn)
    user_id = await create_funded_user(conn, Decimal("1000.00"))
    try:
        session = await keno_autoplay.start_session(
            pool, user_id=user_id, picks=[7], stake=Decimal("10"), rounds_total=None,
            stop_on_win_amount=Decimal("100000"),
        )
        assert session.rounds_total is not None and session.rounds_total <= 5
    finally:
        await keno_autoplay.stop_session(pool, user_id=user_id)
