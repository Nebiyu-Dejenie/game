"""A Keno reserve deposit or withdrawal happens once per intended transfer
(platform audit, 2026-09-29). The ledger key used to be a fresh uuid on
every call, so a double-click on Deposit, or a retry after a lost
response, moved the money twice. Step 2 of the Keno launch is a 30,000 ETB
deposit from house_float, so a repeat would have taken 60,000.

The admin screen now sends one request_id per intended transfer; the
backend keys the ledger transaction on it and answers a repeat with the
original result instead of posting again."""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import httpx
import pytest

from packages.core import ledger
from services.admin import keno_queries
from tests.integration.test_admin_app import _auth_headers
from tests.integration.test_admin_auth import create_test_admin

pytestmark = pytest.mark.asyncio


async def _reserve(conn) -> Decimal:
    return await ledger.balance(conn, (await ledger.get_or_create_account(conn, None, "keno_reserve")).id)


async def _audit_rows(conn, action: str, reason: str) -> int:
    return await conn.fetchval(
        "SELECT count(*) FROM admin_audit_log WHERE action = $1 AND reason = $2", action, reason
    )


async def test_a_repeated_deposit_request_moves_the_money_once(admin_server, pool, conn):
    headers = await _auth_headers(admin_server, pool, role="superadmin")
    reason = f"double-click deposit {uuid.uuid4()}"
    body = {"amount": "30000.00", "reason": reason, "request_id": str(uuid.uuid4())}
    before = await _reserve(conn)

    async with httpx.AsyncClient() as client:
        first = await client.post(f"{admin_server}/keno/reserve/deposit", headers=headers, json=body)
        again = await client.post(f"{admin_server}/keno/reserve/deposit", headers=headers, json=body)

    assert (first.status_code, again.status_code) == (200, 200), (first.text, again.text)
    assert await _reserve(conn) == before + Decimal("30000.00")
    assert await _audit_rows(conn, "keno.reserve.deposit", reason) == 1
    assert again.json()["replayed"] is True


async def test_two_deposit_requests_racing_with_one_id_move_the_money_once(admin_server, pool, conn):
    headers = await _auth_headers(admin_server, pool, role="superadmin")
    reason = f"racing deposit {uuid.uuid4()}"
    body = {"amount": "500.00", "reason": reason, "request_id": str(uuid.uuid4())}
    before = await _reserve(conn)

    async with httpx.AsyncClient() as client:
        responses = await asyncio.gather(
            *(client.post(f"{admin_server}/keno/reserve/deposit", headers=headers, json=body) for _ in range(4))
        )

    assert [r.status_code for r in responses] == [200] * 4, [r.text for r in responses]
    assert await _reserve(conn) == before + Decimal("500.00")
    assert await _audit_rows(conn, "keno.reserve.deposit", reason) == 1


async def test_a_repeated_withdrawal_request_moves_the_money_once(admin_server, pool, conn):
    admin_id, *_ = await create_test_admin(pool, role="superadmin")
    await keno_queries.deposit_to_reserve_admin(
        pool, admin_id=admin_id, amount=Decimal("1000.00"), reason="fund first", request_id=str(uuid.uuid4())
    )
    headers = await _auth_headers(admin_server, pool, role="superadmin")
    reason = f"double-click withdrawal {uuid.uuid4()}"
    body = {"amount": "400.00", "reason": reason, "request_id": str(uuid.uuid4())}
    before = await _reserve(conn)

    async with httpx.AsyncClient() as client:
        first = await client.post(f"{admin_server}/keno/reserve/withdraw", headers=headers, json=body)
        again = await client.post(f"{admin_server}/keno/reserve/withdraw", headers=headers, json=body)

    assert (first.status_code, again.status_code) == (200, 200), (first.text, again.text)
    assert await _reserve(conn) == before - Decimal("400.00")
    assert await _audit_rows(conn, "keno.reserve.withdraw", reason) == 1


async def test_a_repeated_withdrawal_that_emptied_the_reserve_is_not_reported_as_refused(pool, conn):
    """The first request took the reserve to its floor. The repeat isn't a
    new withdrawal, so it must not be refused and logged as a blocked
    attempt."""
    admin_id, *_ = await create_test_admin(pool, role="superadmin")
    await keno_queries.deposit_to_reserve_admin(
        pool, admin_id=admin_id, amount=Decimal("100.00"), reason="fund first", request_id=str(uuid.uuid4())
    )
    everything = await _reserve(conn)
    request_id = str(uuid.uuid4())
    reason = f"withdraw everything {uuid.uuid4()}"
    try:
        first = await keno_queries.withdraw_from_reserve_admin(
            pool, admin_id=admin_id, amount=everything, reason=reason, request_id=request_id
        )
        again = await keno_queries.withdraw_from_reserve_admin(
            pool, admin_id=admin_id, amount=everything, reason=reason, request_id=request_id
        )

        assert Decimal(first["balance"]) == Decimal("0") and again["replayed"] is True
        assert await _reserve(conn) == Decimal("0")
        assert await _audit_rows(conn, "keno.reserve.withdraw_rejected", reason) == 0
    finally:
        # The reserve is shared by every Keno test; put it back.
        refill = everything - await _reserve(conn)
        if refill > 0:
            await keno_queries.deposit_to_reserve_admin(
                pool, admin_id=admin_id, amount=refill, reason="restore after test", request_id=str(uuid.uuid4())
            )


async def test_two_intended_deposits_both_go_through(pool, conn):
    admin_id, *_ = await create_test_admin(pool, role="superadmin")
    before = await _reserve(conn)
    for _ in range(2):
        await keno_queries.deposit_to_reserve_admin(
            pool, admin_id=admin_id, amount=Decimal("100.00"), reason="two separate top-ups",
            request_id=str(uuid.uuid4()),
        )
    assert await _reserve(conn) == before + Decimal("200.00")


async def test_reusing_a_request_id_for_a_different_amount_is_refused(admin_server, pool, conn):
    headers = await _auth_headers(admin_server, pool, role="superadmin")
    request_id = str(uuid.uuid4())
    before = await _reserve(conn)

    async with httpx.AsyncClient() as client:
        first = await client.post(
            f"{admin_server}/keno/reserve/deposit", headers=headers,
            json={"amount": "100.00", "reason": "first amount", "request_id": request_id},
        )
        changed = await client.post(
            f"{admin_server}/keno/reserve/deposit", headers=headers,
            json={"amount": "900.00", "reason": "different amount", "request_id": request_id},
        )

    assert first.status_code == 200 and changed.status_code == 409, (first.text, changed.text)
    assert await _reserve(conn) == before + Decimal("100.00")


async def test_a_transfer_without_a_request_id_is_rejected(admin_server, pool, conn):
    headers = await _auth_headers(admin_server, pool, role="superadmin")
    before = await _reserve(conn)
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{admin_server}/keno/reserve/deposit", headers=headers,
            json={"amount": "100.00", "reason": "no request id"},
        )
    assert response.status_code == 422
    assert await _reserve(conn) == before
