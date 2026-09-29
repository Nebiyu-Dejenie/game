"""A manual bonus grant must happen once per intended grant (platform
audit, 2026-09-29). The ledger key used to be the current timestamp, so a
double-click or a retried request granted the bonus twice -- and both
bonuses then clear on the same wagering and convert to withdrawable cash."""

from __future__ import annotations

import uuid
from decimal import Decimal

import httpx
import pytest

from packages.core import ledger
from tests.integration.conftest import create_funded_user
from tests.integration.test_admin_app import _auth_headers

pytestmark = pytest.mark.asyncio


async def test_the_same_grant_request_sent_twice_grants_once(admin_server, pool, conn):
    headers = await _auth_headers(admin_server, pool, role="superadmin")
    user_id = await create_funded_user(conn, Decimal("0"))
    body = {"user_id": user_id, "amount": "50.00", "reason": "goodwill credit after an outage",
            "request_id": str(uuid.uuid4())}
    async with httpx.AsyncClient() as client:
        first = await client.post(f"{admin_server}/bonuses/grant", headers=headers, json=body)
        again = await client.post(f"{admin_server}/bonuses/grant", headers=headers, json=body)

    assert first.status_code == 200 and again.status_code == 200, (first.text, again.text)
    assert first.json()["id"] == again.json()["id"]
    assert await conn.fetchval("SELECT count(*) FROM bonuses WHERE user_id = $1", user_id) == 1
    bonus_account = await ledger.get_or_create_account(conn, user_id, "user_bonus")
    assert await ledger.balance(conn, bonus_account.id) == Decimal("50.00")
    assert await conn.fetchval(
        "SELECT count(*) FROM admin_audit_log WHERE action = 'bonuses.manual_grant' AND target_id = $1",
        str(first.json()["id"]),
    ) == 1


async def test_two_separate_grants_both_go_through(admin_server, pool, conn):
    headers = await _auth_headers(admin_server, pool, role="superadmin")
    user_id = await create_funded_user(conn, Decimal("0"))
    async with httpx.AsyncClient() as client:
        for _ in range(2):
            r = await client.post(
                f"{admin_server}/bonuses/grant", headers=headers,
                json={"user_id": user_id, "amount": "10.00", "reason": "two separate goodwill credits",
                      "request_id": str(uuid.uuid4())},
            )
            assert r.status_code == 200, r.text
    assert await conn.fetchval("SELECT count(*) FROM bonuses WHERE user_id = $1", user_id) == 2


@pytest.mark.parametrize("reason", ["ok", "test", "   "])
async def test_a_grant_needs_a_real_reason(admin_server, pool, conn, reason):
    headers = await _auth_headers(admin_server, pool, role="superadmin")
    user_id = await create_funded_user(conn, Decimal("0"))
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{admin_server}/bonuses/grant", headers=headers,
            json={"user_id": user_id, "amount": "10.00", "reason": reason, "request_id": str(uuid.uuid4())},
        )
    assert r.status_code == 422
    assert await conn.fetchval("SELECT count(*) FROM bonuses WHERE user_id = $1", user_id) == 0
