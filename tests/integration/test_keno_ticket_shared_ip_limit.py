"""Keno ticket rate limits for players who share a public IP (platform
audit, 2026-09-29, #25). /api/keno/tickets has a per-player bucket and a
per-IP bucket of the same size, 20 a minute. Ethio Telecom mobile data puts
many subscribers behind one carrier NAT address, which is what
CF-Connecting-IP carries, so two ordinary players on the same network
placing 11 tickets each in a minute run the shared bucket dry and one of
them is refused, though each is well inside their own limit. The bucket is
charged before the request is validated, so even rejected attempts count.

Recorded as a strict xfail: the fix is a policy choice (drop the per-IP
bucket, or make it much larger than the per-player one), which is the
operator's to make. Once it's made, this test starts passing and strict
mode fails the run as a reminder to drop the marker."""

from __future__ import annotations

import random
import uuid

import httpx
import pytest

from tests.integration.conftest import build_init_data, next_telegram_id
from tests.integration.test_gateway_rest import http_base

pytestmark = pytest.mark.asyncio


async def _attempt(client: httpx.AsyncClient, base: str, init_data: str, ip: str) -> int:
    response = await client.post(
        f"{base}/api/keno/tickets",
        headers={"Authorization": f"tma {init_data}", "CF-Connecting-IP": ip},
        # An invalid stake: refused with 422 after the rate limits are
        # charged, so nothing is placed and no Keno setup is needed.
        json={"picks": [1, 2, 3], "stake": "not-a-number", "idempotency_key": uuid.uuid4().hex},
    )
    return response.status_code


@pytest.mark.xfail(strict=True, reason="per-IP Keno ticket bucket equals the per-player one; policy decision pending")
async def test_two_players_behind_one_carrier_address_each_get_their_own_ticket_limit(gateway_server):
    base = http_base(gateway_server)
    players = [build_init_data(next_telegram_id()) for _ in range(2)]
    shared_carrier_ip = f"196.188.{random.randint(0, 255)}.{random.randint(1, 254)}"
    statuses: list[int] = []
    async with httpx.AsyncClient() as client:
        for _ in range(11):
            for init_data in players:
                statuses.append(await _attempt(client, base, init_data, shared_carrier_ip))

    assert 429 not in statuses, f"refused at attempt {statuses.index(429) + 1} of {len(statuses)}"
