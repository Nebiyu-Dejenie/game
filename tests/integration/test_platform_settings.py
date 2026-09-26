"""Operator-controlled platform settings (packages/core/platform_settings.py,
services/admin/platform_settings_queries.py): defaults from the
environment, validated atomic updates, reset, audit history, RBAC, and --
the point of it all -- the enforcement paths actually reading the value
the operator set rather than the environment."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from packages.core import platform_settings, responsible_gaming
from packages.core.config import get_settings
from services.admin import platform_settings_queries as psq
from tests.integration.conftest import build_init_data, create_user, next_telegram_id
from tests.integration.test_admin_app import _auth_headers
from tests.integration.test_admin_auth import create_test_admin
from tests.integration.test_admin_manual_payments import _pending_manual_deposit, _unique_ref
from tests.integration.test_gateway_rest import http_base

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def _no_overrides(pool):
    """Every other test file assumes the environment defaults, so each test
    here starts and ends with no overrides in the shared database."""
    await pool.execute("DELETE FROM platform_settings")
    yield
    await pool.execute("DELETE FROM platform_settings")


async def test_defaults_are_the_environment_values(pool):
    env = get_settings()
    loaded = await platform_settings.load(pool)
    assert loaded.min_deposit_etb == env.min_deposit_etb
    assert loaded.min_withdraw_etb == env.min_withdraw_etb
    assert loaded.auto_approve_withdraw_etb == env.auto_approve_withdraw_etb
    assert loaded.max_withdrawals_per_day == env.max_withdrawals_per_day
    assert loaded.rg_limit_increase_delay_hours == responsible_gaming.LIMIT_INCREASE_DELAY_HOURS
    assert loaded.rg_self_exclusion_minimum_days == responsible_gaming.SELF_EXCLUSION_MINIMUM_DAYS


async def test_update_applies_audits_and_reports_who_changed_it(pool):
    admin_id, username, *_ = await create_test_admin(pool, role="superadmin")
    result = await psq.update_settings_admin(
        pool, admin_id=admin_id, reason="raise the withdrawal minimum",
        changes={"min_withdraw_etb": "250.00", "max_withdrawals_per_day": 2},
    )

    loaded = await platform_settings.load(pool)
    assert loaded.min_withdraw_etb == Decimal("250.00")
    assert loaded.max_withdrawals_per_day == 2

    withdrawals = next(c for c in result["categories"] if c["key"] == "withdrawals")
    row = next(s for s in withdrawals["settings"] if s["key"] == "min_withdraw_etb")
    assert row["value"] == "250.00"
    assert row["overridden"] is True
    assert row["updated_by"] == username
    assert row["default"] == str(get_settings().min_withdraw_etb)

    entry = await pool.fetchrow(
        "SELECT * FROM admin_audit_log WHERE action = 'platform_settings.update' AND admin_id = $1", admin_id
    )
    assert json.loads(entry["before"]) == {
        "max_withdrawals_per_day": get_settings().max_withdrawals_per_day,
        "min_withdraw_etb": str(get_settings().min_withdraw_etb),
    }
    assert json.loads(entry["after"]) == {"max_withdrawals_per_day": 2, "min_withdraw_etb": "250.00"}
    assert entry["reason"] == "raise the withdrawal minimum"


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"no_such_setting": 1}, "unknown setting"),
        ({"min_deposit_etb": "0"}, "between"),
        ({"min_deposit_etb": "-5"}, "between"),
        ({"min_deposit_etb": 12.5}, "string"),
        ({"min_deposit_etb": "12.345"}, "whole cents"),
        ({"min_deposit_etb": "twelve"}, "amount in ETB"),
        ({"min_deposit_etb": True}, "must be a number"),
        ({"max_withdrawals_per_day": 0}, "between"),
        ({"max_withdrawals_per_day": "2.5"}, "whole number"),
        ({"rg_limit_increase_delay_hours": 12}, "between 24"),
        ({"rg_self_exclusion_minimum_days": 90}, "between 180"),
        ({"min_deposit_etb": "60000.00"}, "daily deposit cap can't be below"),
    ],
)
async def test_invalid_or_unsafe_values_are_refused(pool, changes, message):
    admin_id, *_ = await create_test_admin(pool, role="superadmin")
    with pytest.raises(platform_settings.InvalidSetting, match=message):
        await psq.update_settings_admin(pool, admin_id=admin_id, changes=changes, reason="should be refused")
    assert await pool.fetchval("SELECT count(*) FROM platform_settings") == 0


async def test_a_multi_setting_update_is_all_or_nothing(pool):
    admin_id, *_ = await create_test_admin(pool, role="superadmin")
    with pytest.raises(platform_settings.InvalidSetting):
        await psq.update_settings_admin(
            pool, admin_id=admin_id, reason="one good, one bad",
            changes={"min_withdraw_etb": "300.00", "rg_self_exclusion_minimum_days": 10},
        )
    assert (await platform_settings.load(pool)).min_withdraw_etb == get_settings().min_withdraw_etb


async def test_cross_setting_rule_holds_whatever_order_edits_arrive_in(pool):
    admin_id, *_ = await create_test_admin(pool, role="superadmin")
    await psq.update_settings_admin(
        pool, admin_id=admin_id, reason="raise both", changes={"daily_deposit_cap_etb": "80000.00", "min_deposit_etb": "60000.00"},
    )
    # Now lowering the cap alone would put it under the minimum.
    with pytest.raises(platform_settings.InvalidSetting, match="daily deposit cap"):
        await psq.update_settings_admin(
            pool, admin_id=admin_id, reason="lower the cap", changes={"daily_deposit_cap_etb": "50000.00"}
        )
    # ...and so would resetting the cap to its 50,000 default.
    with pytest.raises(platform_settings.InvalidSetting, match="daily deposit cap"):
        await psq.reset_setting_admin(pool, admin_id=admin_id, key="daily_deposit_cap_etb", reason="reset the cap")


async def test_reset_returns_a_setting_to_its_default_and_is_audited(pool):
    admin_id, *_ = await create_test_admin(pool, role="superadmin")
    await psq.update_settings_admin(pool, admin_id=admin_id, changes={"min_deposit_etb": "25.00"}, reason="raise it")
    await psq.reset_setting_admin(pool, admin_id=admin_id, key="min_deposit_etb", reason="back to the default")
    assert (await platform_settings.load(pool)).min_deposit_etb == get_settings().min_deposit_etb
    with pytest.raises(platform_settings.InvalidSetting, match="already at its default"):
        await psq.reset_setting_admin(pool, admin_id=admin_id, key="min_deposit_etb", reason="again")
    history = await psq.config_history_admin(pool, scope="platform", target_id="min_deposit_etb")
    assert [h["action"] for h in history[:2]] == ["platform_settings.reset", "platform_settings.update"]
    assert history[0]["before"] == {"min_deposit_etb": "25.00"}


async def test_no_op_and_blank_reason_are_refused(pool):
    admin_id, *_ = await create_test_admin(pool, role="superadmin")
    with pytest.raises(platform_settings.InvalidSetting, match="nothing changed"):
        await psq.update_settings_admin(
            pool, admin_id=admin_id, changes={"min_deposit_etb": str(get_settings().min_deposit_etb)}, reason="same",
        )
    with pytest.raises(platform_settings.InvalidSetting, match="reason"):
        await psq.update_settings_admin(pool, admin_id=admin_id, changes={"min_deposit_etb": "20.00"}, reason=" ")


# --- enforcement reads the operator's value -----------------------------------


async def test_responsible_gaming_uses_the_configured_delay_and_minimum(pool, conn):
    admin_id, *_ = await create_test_admin(pool, role="superadmin")
    await psq.update_settings_admin(
        pool, admin_id=admin_id, reason="stricter responsible gaming",
        changes={"rg_limit_increase_delay_hours": 72, "rg_self_exclusion_minimum_days": 365},
    )
    user_id = await create_user(conn)
    await responsible_gaming.set_deposit_limit(conn, user_id, Decimal("100"))
    applied_now = await responsible_gaming.set_deposit_limit(conn, user_id, Decimal("500"))
    assert applied_now is False
    effective_at = await conn.fetchval(
        "SELECT pending_daily_deposit_cap_effective_at FROM responsible_gaming_limits WHERE user_id = $1", user_id
    )
    assert effective_at - datetime.now(UTC) > timedelta(hours=71)

    with pytest.raises(responsible_gaming.SelfExclusionTooShort, match="365"):
        await responsible_gaming.self_exclude(pool, user_id, days=200)
    await responsible_gaming.self_exclude(pool, user_id)  # default = the configured minimum
    until = await conn.fetchval("SELECT self_excluded_until FROM responsible_gaming_limits WHERE user_id = $1", user_id)
    assert until - datetime.now(UTC) > timedelta(days=364)


async def test_two_person_threshold_follows_the_setting(admin_server, pool, redis, conn):
    """With the 2,000 ETB environment default a 600 ETB manual deposit is
    credited on one approval; with the threshold lowered to 500 it needs two."""
    admin_id, *_ = await create_test_admin(pool, role="superadmin")
    await psq.update_settings_admin(
        pool, admin_id=admin_id, changes={"auto_approve_withdraw_etb": "500.00"}, reason="tighten approvals",
    )
    headers = await _auth_headers(admin_server, pool, role="finance")
    user_id = await create_user(conn)
    payment_id, _ = await _pending_manual_deposit(pool, redis, conn, user_id, Decimal("600.00"), _unique_ref())
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{admin_server}/manual-deposits/{payment_id}/approve", headers=headers,
            json={"reason": "receipt matches the deposit"},
        )
    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "awaiting_second_approval"


async def test_player_limits_endpoint_shows_the_configured_values(gateway_server, pool):
    admin_id, *_ = await create_test_admin(pool, role="superadmin")
    await psq.update_settings_admin(
        pool, admin_id=admin_id, changes={"min_deposit_etb": "30.00", "min_withdraw_etb": "300.00"},
        reason="new minimums",
    )
    init_data = build_init_data(next_telegram_id())
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{http_base(gateway_server)}/api/limits", headers={"Authorization": f"tma {init_data}"}
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["min_deposit"] == "30.00"
    assert body["min_withdraw"] == "300.00"


# --- over HTTP: RBAC ------------------------------------------------------------


async def test_settings_rbac_over_http(admin_server, pool):
    support = await _auth_headers(admin_server, pool, role="support")
    finance = await _auth_headers(admin_server, pool, role="finance")
    superadmin = await _auth_headers(admin_server, pool, role="superadmin")
    async with httpx.AsyncClient() as client:
        assert (await client.get(f"{admin_server}/settings", headers=support)).status_code == 403
        listed = await client.get(f"{admin_server}/settings", headers=finance)
        assert listed.status_code == 200
        keys = {s["key"] for c in listed.json()["categories"] for s in c["settings"]}
        assert keys == set(platform_settings.REGISTRY)

        denied = await client.patch(
            f"{admin_server}/settings", headers=finance,
            json={"changes": {"min_deposit_etb": "20.00"}, "reason": "finance cannot change this"},
        )
        assert denied.status_code == 403

        invalid = await client.patch(
            f"{admin_server}/settings", headers=superadmin,
            json={"changes": {"rg_self_exclusion_minimum_days": 30}, "reason": "weaken self exclusion"},
        )
        assert invalid.status_code == 422

        ok = await client.patch(
            f"{admin_server}/settings", headers=superadmin,
            json={"changes": {"min_deposit_etb": "20.00"}, "reason": "raise the minimum deposit"},
        )
        assert ok.status_code == 200, ok.text

        history = await client.get(f"{admin_server}/config-history?scope=platform", headers=finance)
        assert history.status_code == 200
        assert history.json()[0]["after"] == {"min_deposit_etb": "20.00"}
        assert (await client.get(f"{admin_server}/config-history?scope=bogus", headers=finance)).status_code == 422
        assert (await client.get(f"{admin_server}/config-history", headers=support)).status_code == 403


async def test_history_includes_keno_changes(pool):
    history = await psq.config_history_admin(pool, scope="keno", limit=5)
    assert all(h["target_type"] in ("keno_config", "keno_risk_tier", "keno_paytable") for h in history)
