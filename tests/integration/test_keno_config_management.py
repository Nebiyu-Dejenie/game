"""Admin-controlled Keno configuration: the copy-forward config editor,
stake management on risk tiers, the RTP band actually being enforced, the
configurable autoplay cap, and the backend refusing a stake the operator
turned off -- however the request arrives."""

from __future__ import annotations

import uuid
from decimal import Decimal

import asyncpg
import httpx
import pytest

from packages.core import keno, keno_autoplay, keno_config, keno_queries, keno_tickets
from services.admin import keno_queries as admin_keno
from tests.integration.conftest import create_funded_user
from tests.integration.test_admin_app import _auth_headers
from tests.integration.test_admin_auth import create_test_admin
from tests.integration.test_keno_tickets import _seed_keno_round

pytestmark = pytest.mark.asyncio

# Tier fixtures here aren't testing the multiplier cap unless they say so;
# other test files leave extreme paytables live in the shared database.
_HIGH_CAP = Decimal("100000")
# Tier automation promotes to the highest tier whose min_reserve the
# reserve covers; test tiers must never become that target for other tests.
_UNREACHABLE_RESERVE = Decimal("900000000000.00")


async def _funded(pool, amount: Decimal) -> int:
    async with pool.acquire() as conn:
        return await create_funded_user(conn, amount)


@pytest.fixture(autouse=True)
async def _close_any_dangling_betting_open_round(pool: asyncpg.Pool):
    async def _close() -> None:
        async with pool.acquire() as conn:
            await conn.execute("UPDATE keno_rounds SET status = 'completed' WHERE status = 'betting_open'")

    await _close()
    yield
    await _close()


async def _baseline_config(pool, admin_id: int, **overrides) -> dict:
    """A known active config to edit from, with the settings the old kill
    switch used to drop set to non-default values, and Keno switched on."""
    if not (await admin_keno.get_active_config_admin(pool))["keno_enabled"]:
        await admin_keno.set_keno_enabled_admin(pool, admin_id=admin_id, enabled=True, reason="tests start with Keno on")
    await admin_keno.create_config_admin(
        pool, admin_id=admin_id, round_cycle_seconds=45, betting_seconds=25, draw_seconds=12,
        result_seconds=8, min_picks=1, max_picks=10, max_tickets_per_user_per_round=3,
        per_user_round_capacity_share_bps=2000, jackpot_diversion_bps=150, reason="baseline for config management tests",
    )
    changes = {
        "reserve_withdrawal_floor": "50000.00",
        "beta_restricted": False,
        "daily_payout_circuit_breaker_multiple": "4.5",
        "max_autoplay_rounds": 25,
        **overrides,
    }
    try:
        return await admin_keno.update_config_admin(
            pool, admin_id=admin_id, changes=changes, reason="set non-default values"
        )
    except admin_keno.InvalidKenoConfig as exc:
        # create_config_admin carried an earlier test's identical values
        # forward, so there's nothing to change -- that's the state we want.
        assert "nothing changed" in str(exc)
        return await admin_keno.get_active_config_admin(pool)


# --- config: copy-forward ----------------------------------------------------


async def test_kill_switch_no_longer_resets_floor_beta_breaker_or_autoplay_cap(pool):
    """The bug: the kill switch listed the columns it copied by hand and
    silently reset every column added after it was written."""
    admin_id, *_ = await create_test_admin(pool, role="superadmin")
    before = await _baseline_config(pool, admin_id)

    flipped = await admin_keno.set_keno_enabled_admin(pool, admin_id=admin_id, enabled=False, reason="kill it")

    assert flipped["keno_enabled"] is False
    for column in ("reserve_withdrawal_floor", "beta_restricted", "daily_payout_circuit_breaker_multiple",
                   "max_autoplay_rounds", "betting_seconds", "jackpot_diversion_bps", "rtp_floor_bps"):
        assert flipped[column] == before[column], column
    assert flipped["reserve_withdrawal_floor"] == Decimal("50000.00")


async def test_full_create_carries_forward_columns_it_does_not_name(pool):
    admin_id, *_ = await create_test_admin(pool, role="superadmin")
    await _baseline_config(pool, admin_id)
    created = await admin_keno.create_config_admin(
        pool, admin_id=admin_id, round_cycle_seconds=50, betting_seconds=30, draw_seconds=12,
        result_seconds=8, min_picks=1, max_picks=10, max_tickets_per_user_per_round=3,
        per_user_round_capacity_share_bps=2000, jackpot_diversion_bps=150, reason="full create after edits",
    )
    assert created["reserve_withdrawal_floor"] == Decimal("50000.00")
    assert created["beta_restricted"] is False
    assert created["max_autoplay_rounds"] == 25


async def test_update_changes_only_named_fields_derives_cycle_and_audits_the_diff(pool):
    admin_id, *_ = await create_test_admin(pool, role="superadmin")
    before = await _baseline_config(pool, admin_id)

    after = await admin_keno.update_config_admin(
        pool, admin_id=admin_id, changes={"draw_seconds": 18, "max_picks": 8}, reason="slower, readable draw"
    )

    assert after["draw_seconds"] == 18
    assert after["max_picks"] == 8
    assert after["round_cycle_seconds"] == after["betting_seconds"] + 18 + after["result_seconds"]
    assert after["version"] > before["version"]
    assert after["reserve_withdrawal_floor"] == before["reserve_withdrawal_floor"]
    active = await admin_keno.get_active_config_admin(pool)
    assert active["id"] == after["id"]

    entry = await pool.fetchrow(
        "SELECT * FROM admin_audit_log WHERE action = 'keno.config.update' AND target_id = $1", str(after["id"])
    )
    assert entry["reason"] == "slower, readable draw"
    import json
    changed = json.loads(entry["after"])
    assert changed == {"draw_seconds": 18, "max_picks": 8, "round_cycle_seconds": after["round_cycle_seconds"]}
    assert json.loads(entry["before"])["draw_seconds"] == before["draw_seconds"]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"keno_enabled": True}, "can't be changed here"),
        ({"number_pool_size": 90}, "can't be changed here"),
        ({"min_picks": 6, "max_picks": 5}, "min_picks cannot be greater"),
        ({"max_picks": 11}, "between"),
        ({"jackpot_diversion_bps": 5000}, "between"),
        ({"betting_seconds": 2}, "between"),
        ({"rtp_floor_bps": 9600, "rtp_ceiling_bps": 9500}, "floor cannot be above"),
        ({"rtp_ceiling_bps": 9900}, "between"),
        ({"reserve_withdrawal_floor": "-1"}, "zero or more"),
        ({"reserve_withdrawal_floor": "10.005"}, "whole cents"),
        ({"reserve_withdrawal_floor": "1e400"}, "usable number"),
        ({"daily_payout_circuit_breaker_multiple": "0.5"}, "between 1 and 50"),
        ({"max_autoplay_rounds": 101}, "between"),
        ({"beta_restricted": "no"}, "true or false"),
        ({"max_picks": "ten"}, "whole number"),
    ],
)
async def test_update_rejects_invalid_or_unsafe_changes(pool, changes, message):
    admin_id, *_ = await create_test_admin(pool, role="superadmin")
    await _baseline_config(pool, admin_id)
    active_before = await admin_keno.get_active_config_admin(pool)
    with pytest.raises(admin_keno.InvalidKenoConfig, match=message):
        await admin_keno.update_config_admin(pool, admin_id=admin_id, changes=changes, reason="bad change")
    assert (await admin_keno.get_active_config_admin(pool))["id"] == active_before["id"]


async def test_update_refuses_a_no_op_and_a_blank_reason(pool):
    admin_id, *_ = await create_test_admin(pool, role="superadmin")
    current = await _baseline_config(pool, admin_id)
    with pytest.raises(admin_keno.InvalidKenoConfig, match="nothing changed"):
        await admin_keno.update_config_admin(
            pool, admin_id=admin_id, changes={"draw_seconds": current["draw_seconds"]}, reason="no-op"
        )
    with pytest.raises(admin_keno.InvalidKenoConfig, match="reason"):
        await admin_keno.update_config_admin(pool, admin_id=admin_id, changes={"draw_seconds": 20}, reason="  ")


async def test_rtp_band_that_live_paytables_fall_outside_is_refused(pool):
    admin_id, *_ = await create_test_admin(pool, role="superadmin")
    await _baseline_config(pool, admin_id)
    async with pool.acquire() as conn:
        lowest_live = await conn.fetchval(
            """SELECT MIN(computed_rtp_bps) FROM (
                 SELECT DISTINCT ON (pick_count, profile) computed_rtp_bps FROM keno_paytables
                 WHERE effective_from <= now() ORDER BY pick_count, profile, effective_from DESC, id DESC) live"""
        )
    with pytest.raises(admin_keno.InvalidKenoConfig, match="outside the new RTP band"):
        await admin_keno.update_config_admin(
            pool, admin_id=admin_id, changes={"rtp_floor_bps": lowest_live + 1}, reason="narrow the band"
        )


async def test_paytable_save_enforces_the_configured_band_not_the_constants(pool):
    """rtp_floor_bps/rtp_ceiling_bps used to be stored and never read."""
    admin_id, *_ = await create_test_admin(pool, role="superadmin")
    await _baseline_config(pool, admin_id)
    async with pool.acquire() as conn:
        # Narrow the band directly: going through the editor would refuse
        # it because of other tests' live paytables, which isn't what
        # this test is about.
        await conn.execute(
            """INSERT INTO keno_configs (version, round_cycle_seconds, betting_seconds, draw_seconds,
                   result_seconds, max_tickets_per_user_per_round, keno_enabled, beta_restricted,
                   rtp_floor_bps, rtp_ceiling_bps)
               VALUES ((SELECT MAX(version) + 1 FROM keno_configs), 45, 25, 12, 8, 3, true, false, 8600, 9700)"""
        )
        assert await admin_keno.rtp_band(conn) == (Decimal("0.86"), Decimal("0.97"))
    try:
        # 1-pick at 3.40x is RTP 0.85: inside the hard 75-97% band, outside this config's.
        with pytest.raises(admin_keno.InvalidKenoConfig):
            await admin_keno.create_paytable_admin(
                pool, admin_id=admin_id, pick_count=1, profile="standard", multipliers={"1": "3.40"},
                reason="should be refused",
            )
        preview = admin_keno.preview_paytable_stats(1, {"1": "3.40"}, floor=Decimal("0.86"), ceiling=Decimal("0.97"))
        assert preview["within_guardrail"] is False
    finally:
        await admin_keno.create_config_admin(
            pool, admin_id=admin_id, round_cycle_seconds=45, betting_seconds=25, draw_seconds=12,
            result_seconds=8, min_picks=1, max_picks=10, max_tickets_per_user_per_round=3,
            per_user_round_capacity_share_bps=2000, jackpot_diversion_bps=150, reason="restore the default band",
        )


async def test_configured_autoplay_cap_is_enforced(pool):
    admin_id, *_ = await create_test_admin(pool, role="superadmin")
    await _baseline_config(pool, admin_id, max_autoplay_rounds=5)
    user_id = await _funded(pool, Decimal("1000"))
    with pytest.raises(keno_autoplay.InvalidAutoplayConfig, match="between 1 and 5"):
        await keno_autoplay.start_session(pool, user_id=user_id, picks=[1, 2, 3], stake=Decimal("10"), rounds_total=6)
    session = await keno_autoplay.start_session(
        pool, user_id=user_id, picks=[1, 2, 3], stake=Decimal("10"), rounds_total=5
    )
    assert session.rounds_total == 5
    await keno_autoplay.stop_session(pool, user_id=user_id)


# --- tiers: stake management -------------------------------------------------


async def _tier(pool, admin_id: int, **overrides) -> dict:
    values = dict(
        tier_number=900 + uuid.uuid4().int % 1000, min_reserve=_UNREACHABLE_RESERVE, max_pick_count=5,
        max_top_multiplier=_HIGH_CAP, stake_options=[Decimal("10"), Decimal("20"), Decimal("50")],
        max_win_per_ticket=Decimal("800"), max_round_exposure_pct=Decimal("0.10"),
        paytable_profile="standard", reason="tier for stake tests",
    )
    values.update(overrides)
    return await admin_keno.create_tier_admin(pool, admin_id=admin_id, **values)


async def test_stake_management_add_disable_reorder_and_default(pool):
    admin_id, *_ = await create_test_admin(pool, role="superadmin")
    tier = await _tier(pool, admin_id)

    edited = await admin_keno.update_tier_admin(
        pool, admin_id=admin_id, tier_id=tier["id"], reason="rework the stake ladder",
        changes={
            "stake_options": ["50", "10", "100"],   # reordered, 100 added
            "disabled_stake_options": ["20"],       # 20 switched off, kept for later
            "default_stake": "10",
        },
    )

    assert edited["id"] != tier["id"]
    assert edited["version"] == tier["version"] + 1
    assert edited["stake_options"] == [Decimal("50.00"), Decimal("10.00"), Decimal("100.00")]
    assert edited["disabled_stake_options"] == [Decimal("20.00")]
    assert edited["default_stake"] == Decimal("10.00")
    assert edited["max_win_per_ticket"] == tier["max_win_per_ticket"]  # untouched fields carried forward

    reenabled = await admin_keno.update_tier_admin(
        pool, admin_id=admin_id, tier_id=edited["id"], reason="bring 20 back",
        changes={"stake_options": ["50", "10", "100", "20"], "disabled_stake_options": []},
    )
    assert Decimal("20") in reenabled["stake_options"]
    assert reenabled["default_stake"] == Decimal("10.00")


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"stake_options": []}, "at least one stake"),
        ({"stake_options": ["10", "10"]}, "same stake twice"),
        ({"stake_options": ["10", "0"]}, "more than zero"),
        ({"stake_options": ["10", "-5"]}, "more than zero"),
        ({"stake_options": ["10.001"]}, "whole cents"),
        ({"stake_options": ["abc"]}, "amount in ETB"),
        ({"stake_options": ["1e400"]}, "not a usable amount"),
        ({"stake_options": ["100001"]}, "maximum stake"),
        ({"stake_options": [str(n) for n in range(1, 14)]}, "at most 12"),
        ({"disabled_stake_options": ["10"]}, "both enabled and disabled"),
        ({"default_stake": "30"}, "not one of the enabled stakes"),
        ({"stake_options": ["10", "900"]}, "at least the largest stake"),
        ({"max_round_exposure_pct": "0"}, "more than 0"),
        ({"max_round_exposure_pct": "1.5"}, "more than 0"),
        ({"paytable_profile": "wild"}, "unknown paytable profile"),
        ({"max_pick_count": 11}, "between"),
        ({"max_top_multiplier": "1"}, "exceed this tier's top multiplier"),
        ({"tier_number": 3}, "can't be changed here"),
    ],
)
async def test_tier_edit_rejects_invalid_stake_configurations(pool, changes, message):
    admin_id, *_ = await create_test_admin(pool, role="superadmin")
    tier = await _tier(pool, admin_id)
    with pytest.raises(admin_keno.InvalidKenoConfig, match=message):
        await admin_keno.update_tier_admin(pool, admin_id=admin_id, tier_id=tier["id"], changes=changes, reason="bad")
    latest = await pool.fetchval("SELECT MAX(version) FROM keno_risk_tiers WHERE tier_number = $1", tier["tier_number"])
    assert latest == tier["version"]  # nothing was written


async def test_database_refuses_a_default_stake_that_is_not_offered(pool):
    """The CHECK constraints hold even if application validation is bypassed."""
    with pytest.raises(asyncpg.CheckViolationError):
        await pool.execute(
            """INSERT INTO keno_risk_tiers (tier_number, version, min_reserve, max_pick_count, max_top_multiplier,
                   stake_options, default_stake, max_win_per_ticket, max_round_exposure_pct, paytable_profile)
               VALUES (7777, $1, 0, 5, 16, '{10,20}', 30, 800, 0.1, 'standard')""",
            uuid.uuid4().int % 10**6,
        )
    with pytest.raises(asyncpg.CheckViolationError):
        await pool.execute(
            """INSERT INTO keno_risk_tiers (tier_number, version, min_reserve, max_pick_count, max_top_multiplier,
                   stake_options, disabled_stake_options, max_win_per_ticket, max_round_exposure_pct, paytable_profile)
               VALUES (7777, $1, 0, 5, 16, '{10,20}', '{20}', 800, 0.1, 'standard')""",
            uuid.uuid4().int % 10**6,
        )


async def test_adopting_an_edit_of_the_current_tier_makes_it_current(pool):
    admin_id, *_ = await create_test_admin(pool, role="superadmin")
    tier = await _tier(pool, admin_id)
    await admin_keno.set_current_tier_admin(pool, admin_id=admin_id, tier_id=tier["id"], reason="use test tier")

    edited = await admin_keno.update_tier_admin(
        pool, admin_id=admin_id, tier_id=tier["id"], changes={"stake_options": ["10", "50"],
        "disabled_stake_options": ["20"]}, reason="switch off the 20 ETB stake", adopt=True,
    )

    assert edited["adopted"] is True
    async with pool.acquire() as conn:
        current = await keno_config.load_current_tier(conn)
    assert current["id"] == edited["id"]
    change = await pool.fetchrow("SELECT * FROM keno_tier_changes WHERE to_tier_id = $1", edited["id"])
    assert change["trigger"] == "admin_override"


async def test_adopt_does_not_switch_tiers_when_editing_a_tier_not_in_use(pool):
    admin_id, *_ = await create_test_admin(pool, role="superadmin")
    in_use = await _tier(pool, admin_id)
    other = await _tier(pool, admin_id)
    await admin_keno.set_current_tier_admin(pool, admin_id=admin_id, tier_id=in_use["id"], reason="use test tier")
    edited = await admin_keno.update_tier_admin(
        pool, admin_id=admin_id, tier_id=other["id"], changes={"default_stake": "20"}, reason="default", adopt=True,
    )
    assert edited["adopted"] is False
    async with pool.acquire() as conn:
        assert (await keno_config.load_current_tier(conn))["id"] == in_use["id"]


async def test_a_disabled_stake_is_refused_by_the_backend(pool, redis):
    """The Mini App never offers a disabled stake, but a hand-built API
    request must be refused too: place_ticket checks the round's tier."""
    async with pool.acquire() as conn:
        round_id = await _seed_keno_round(conn, stake_options=[Decimal("10"), Decimal("50")])
    user_id = await _funded(pool, Decimal("500"))
    with pytest.raises(keno_tickets.StakeNotAllowed):
        await keno_tickets.place_ticket(
            pool, redis, user_id=user_id, picks=[1, 2, 3], stake=Decimal("20"), idempotency_key=str(uuid.uuid4())
        )
    placed = await keno_tickets.place_ticket(
        pool, redis, user_id=user_id, picks=[1, 2, 3], stake=Decimal("10"), idempotency_key=str(uuid.uuid4())
    )
    assert placed.round_id == round_id


async def test_player_state_offers_the_default_stake_and_autoplay_cap(pool):
    async with pool.acquire() as conn:
        round_id = await _seed_keno_round(conn, stake_options=[Decimal("10"), Decimal("20"), Decimal("50")])
        tier_id = await conn.fetchval("SELECT tier_id FROM keno_rounds WHERE id = $1", round_id)
        await conn.execute("UPDATE keno_risk_tiers SET default_stake = 20 WHERE id = $1", tier_id)
    user_id = await _funded(pool, Decimal("10"))
    state = await keno_queries.game_center_state(pool, user_id=user_id)
    assert state is not None
    assert state["round_id"] == round_id
    assert state["default_stake"] == "20.00"
    assert state["stake_options"] == ["10.00", "20.00", "50.00"]
    assert 1 <= state["max_autoplay_rounds"] <= keno_autoplay.MAX_ROUNDS_TOTAL


# --- over HTTP ----------------------------------------------------------------


async def test_config_and_tier_edits_over_http_are_superadmin_only(admin_server, pool):
    ops = await _auth_headers(admin_server, pool, role="ops")
    superadmin = await _auth_headers(admin_server, pool, role="superadmin")
    admin_id, *_ = await create_test_admin(pool, role="superadmin")
    await _baseline_config(pool, admin_id)
    tier = await _tier(pool, admin_id)

    async with httpx.AsyncClient() as client:
        denied = await client.patch(
            f"{admin_server}/keno/configs", headers=ops,
            json={"changes": {"draw_seconds": 16}, "reason": "ops should not be able to do this"},
        )
        assert denied.status_code == 403

        short_reason = await client.patch(
            f"{admin_server}/keno/configs", headers=superadmin, json={"changes": {"draw_seconds": 16}, "reason": "ok"},
        )
        assert short_reason.status_code == 422

        ok = await client.patch(
            f"{admin_server}/keno/configs", headers=superadmin,
            json={"changes": {"draw_seconds": 16}, "reason": "slow the draw down a little"},
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["draw_seconds"] == 16

        invalid = await client.patch(
            f"{admin_server}/keno/configs", headers=superadmin,
            json={"changes": {"min_picks": 9, "max_picks": 3}, "reason": "an invalid combination"},
        )
        assert invalid.status_code == 422

        tier_denied = await client.patch(
            f"{admin_server}/keno/tiers/{tier['id']}", headers=ops,
            json={"changes": {"default_stake": "20"}, "reason": "ops should not be able to do this"},
        )
        assert tier_denied.status_code == 403

        tier_ok = await client.patch(
            f"{admin_server}/keno/tiers/{tier['id']}", headers=superadmin,
            json={"changes": {"default_stake": "20", "stake_options": ["20", "10"],
                              "disabled_stake_options": ["50"]}, "reason": "make 20 ETB the default"},
        )
        assert tier_ok.status_code == 200, tier_ok.text
        body = tier_ok.json()
        assert body["default_stake"] == "20.00" or Decimal(body["default_stake"]) == Decimal("20")
        assert [Decimal(s) for s in body["stake_options"]] == [Decimal("20"), Decimal("10")]

        tier_invalid = await client.patch(
            f"{admin_server}/keno/tiers/{tier['id']}", headers=superadmin,
            json={"changes": {"default_stake": "999"}, "reason": "a default that isn't offered"},
        )
        assert tier_invalid.status_code == 422
