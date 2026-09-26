"""Payouts awaiting reconciliation (operator decision, 2026-09-26): an
automatic payout whose outcome the worker doesn't know stays 'processing'
with the funds locked, and an admin records what Chapa's dashboard shows.
Real Postgres, Redis, payout worker and admin API."""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest

from services.admin import queries
from services.payments import payout_worker
from services.payments.payout_settlement import mark_payout_paid
from tests.integration.conftest import create_funded_user
from tests.integration.test_admin_app import _auth_headers
from tests.integration.test_admin_auth import create_test_admin
from tests.integration.test_payout_worker import FakePayoutProvider, _approved_withdrawal, _cash, _locked, _provider_settlement

pytestmark = pytest.mark.asyncio


class _TimeoutProvider(FakePayoutProvider):
    async def create_payout(self, *, method, amount, our_ref):
        raise TimeoutError("read timeout talking to chapa")


async def _stuck_payout(pool, redis, conn, amount: Decimal = Decimal("150.00"), *, age_minutes: int = 11):
    user_id = await create_funded_user(conn, Decimal("500.00"))
    our_ref = await _approved_withdrawal(pool, redis, conn, user_id, amount)
    assert await payout_worker.process_next(pool, redis, _TimeoutProvider(), consumer_name="w1") == "awaiting_reconciliation"
    payment_id = await conn.fetchval("SELECT id FROM payments WHERE our_ref = $1", our_ref)
    await conn.execute(
        "UPDATE payments SET updated_at = now() - make_interval(mins => $2) WHERE id = $1", payment_id, age_minutes
    )
    return user_id, payment_id, our_ref


async def test_a_payout_with_an_unknown_outcome_is_listed_with_what_the_worker_saw(pool, redis, conn):
    _, payment_id, our_ref = await _stuck_payout(pool, redis, conn)

    rows = {r["id"]: r for r in await queries.list_payouts_awaiting_reconciliation(pool)}

    assert payment_id in rows
    assert rows[payment_id]["our_ref"] == our_ref
    assert rows[payment_id]["failure_reason"].startswith("outcome unknown: read timeout")
    assert rows[payment_id]["resolvable"] is True


async def test_marking_failed_returns_the_locked_amount_exactly_once(pool, redis, conn):
    admin_id, *_ = await create_test_admin(pool, role="finance")
    user_id, payment_id, _ = await _stuck_payout(pool, redis, conn)

    await queries.resolve_payout_admin(
        pool, redis, admin_id=admin_id, payment_id=payment_id, outcome="failed", provider_ref=None,
        reason="Chapa dashboard has no record of this transfer", ip_address=None,
    )

    assert await _cash(conn, user_id) == Decimal("500.00")
    assert await _locked(conn, user_id) == Decimal("0.00")
    assert await conn.fetchval("SELECT status FROM payments WHERE id = $1", payment_id) == "failed"
    audit = await conn.fetchrow(
        "SELECT action, reason FROM admin_audit_log WHERE target_id = $1 ORDER BY id DESC LIMIT 1", str(payment_id)
    )
    assert audit["action"] == "payouts.resolve_failed"
    with pytest.raises(queries.PayoutNotResolvable):
        await queries.resolve_payout_admin(
            pool, redis, admin_id=admin_id, payment_id=payment_id, outcome="failed", provider_ref=None,
            reason="second click on the same payout", ip_address=None,
        )
    assert await _cash(conn, user_id) == Decimal("500.00")


async def test_marking_paid_settles_to_provider_settlement(pool, redis, conn):
    admin_id, *_ = await create_test_admin(pool, role="superadmin")
    user_id, payment_id, _ = await _stuck_payout(pool, redis, conn)
    settlement_before = await _provider_settlement(conn)

    await queries.resolve_payout_admin(
        pool, redis, admin_id=admin_id, payment_id=payment_id, outcome="paid", provider_ref="CHAPA-TX-7781",
        reason="Chapa dashboard shows the transfer completed", ip_address=None,
    )

    assert await _locked(conn, user_id) == Decimal("0.00")
    assert await _cash(conn, user_id) == Decimal("350.00")
    assert await _provider_settlement(conn) - settlement_before == Decimal("150.00")
    row = await conn.fetchrow("SELECT status, provider_ref FROM payments WHERE id = $1", payment_id)
    assert (row["status"], row["provider_ref"]) == ("succeeded", "CHAPA-TX-7781")


async def test_a_payout_still_in_flight_cannot_be_resolved(pool, redis, conn):
    """Under ten minutes at 'processing', the worker may still be waiting
    on Chapa; marking it failed now could pay the player twice."""
    admin_id, *_ = await create_test_admin(pool, role="superadmin")
    user_id, payment_id, _ = await _stuck_payout(pool, redis, conn, age_minutes=0)

    with pytest.raises(queries.PayoutNotResolvable):
        await queries.resolve_payout_admin(
            pool, redis, admin_id=admin_id, payment_id=payment_id, outcome="failed", provider_ref=None,
            reason="trying too early on purpose", ip_address=None,
        )
    assert await _locked(conn, user_id) == Decimal("150.00")


async def test_the_worker_cannot_settle_a_payout_an_admin_already_resolved(pool, redis, conn):
    admin_id, *_ = await create_test_admin(pool, role="superadmin")
    user_id, payment_id, _ = await _stuck_payout(pool, redis, conn)
    await queries.resolve_payout_admin(
        pool, redis, admin_id=admin_id, payment_id=payment_id, outcome="failed", provider_ref=None,
        reason="Chapa dashboard has no record of this transfer", ip_address=None,
    )

    async with pool.acquire() as c:
        async with c.transaction():
            assert await mark_payout_paid(c, payment_id=payment_id, provider_ref="late") is None
    assert await _cash(conn, user_id) == Decimal("500.00")


async def test_over_http_support_can_view_but_only_finance_can_resolve(admin_server, pool, redis, conn):
    _, payment_id, _ = await _stuck_payout(pool, redis, conn)
    support = await _auth_headers(admin_server, pool, role="support")
    finance = await _auth_headers(admin_server, pool, role="finance")
    body = {"outcome": "failed", "reason": "Chapa dashboard has no record of this transfer"}
    async with httpx.AsyncClient() as client:
        listed = await client.get(f"{admin_server}/payouts/awaiting-reconciliation", headers=support)
        refused = await client.post(f"{admin_server}/payouts/{payment_id}/resolve", headers=support, json=body)
        resolved = await client.post(f"{admin_server}/payouts/{payment_id}/resolve", headers=finance, json=body)
        again = await client.post(f"{admin_server}/payouts/{payment_id}/resolve", headers=finance, json=body)
    assert listed.status_code == 200 and any(r["id"] == payment_id for r in listed.json())
    assert refused.status_code == 403
    assert resolved.status_code == 200, resolved.text
    assert again.status_code == 409
