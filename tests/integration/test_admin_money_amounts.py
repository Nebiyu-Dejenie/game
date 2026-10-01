"""Admin-entered money amounts must be whole cents (platform audit #77,
2026-10-01). ledger.post() now refuses a fraction of a cent, and a fraction
of a cent anywhere upstream can't become money: a room stake of 12.505 is
multiplied into every pot. Each endpoint that takes a money amount from an
admin refuses one with a clear 422, and nothing moves."""

from __future__ import annotations

import uuid
from decimal import Decimal

import httpx
import pytest

from packages.core import ledger
from tests.integration.conftest import create_funded_user
from tests.integration.test_admin_app import _auth_headers

pytestmark = pytest.mark.asyncio


async def test_every_admin_money_endpoint_refuses_a_fraction_of_a_cent(admin_server, pool, conn):
    headers = await _auth_headers(admin_server, pool, role="superadmin")
    user_id = await create_funded_user(conn, Decimal("100.00"))
    reserve = await ledger.get_or_create_account(conn, None, "keno_reserve")
    reserve_before = await ledger.balance(conn, reserve.id)
    reason = "precision check by the test suite"
    requests = [
        (f"/users/{user_id}/adjust", {"amount": "10.005", "reason": reason, "request_id": str(uuid.uuid4())}),
        ("/keno/reserve/deposit", {"amount": "10.005", "reason": reason, "request_id": str(uuid.uuid4())}),
        ("/keno/reserve/withdraw", {"amount": "10.005", "reason": reason, "request_id": str(uuid.uuid4())}),
        ("/bonuses/grant", {"user_id": user_id, "amount": "10.005", "reason": reason, "request_id": str(uuid.uuid4())}),
        ("/rooms", {"code": f"T{uuid.uuid4().hex[:6]}", "stake": "12.505"}),
    ]
    async with httpx.AsyncClient() as client:
        statuses = [
            (path, (await client.post(f"{admin_server}{path}", headers=headers, json=body)).status_code)
            for path, body in requests
        ]

    assert statuses == [(path, 422) for path, _ in requests]
    cash = await ledger.get_or_create_account(conn, user_id, "user_cash")
    assert await ledger.balance(conn, cash.id) == Decimal("100.00")
    assert await ledger.balance(conn, reserve.id) == reserve_before
