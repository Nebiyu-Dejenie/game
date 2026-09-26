"""Bingo room configuration validation (services/admin/queries.py
_validate_room_values): the stake values the database alone would get
wrong, combinations that are only invalid together, and the reason
requirement on HTTP edits."""

from __future__ import annotations

import uuid
from decimal import Decimal

import asyncpg
import httpx
import pytest

from services.admin import queries
from tests.integration.conftest import create_room
from tests.integration.test_admin_app import _auth_headers
from tests.integration.test_admin_auth import create_test_admin

pytestmark = pytest.mark.asyncio


def _room_kwargs(**overrides):
    values = dict(
        code=f"cfg-{uuid.uuid4().hex[:10]}", stake=Decimal("20.00"), house_cut_bps=2000, min_players=2,
        max_players=100, max_cards_per_player=1, lobby_seconds=30, call_interval_ms=4000, result_seconds=10,
        win_patterns=["row", "col", "diag"], min_winning_lines=2, ip_address=None,
    )
    values.update(overrides)
    return values


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"stake": Decimal("NaN")}, "amount in ETB"),
        ({"stake": Decimal("Infinity")}, "amount in ETB"),
        ({"stake": Decimal("0")}, "more than 0"),
        ({"stake": Decimal("-5")}, "more than 0"),
        ({"stake": Decimal("10.005")}, "whole cents"),
        ({"stake": Decimal("100000.01")}, "at most"),
        ({"min_players": 10, "max_players": 5}, "min_players cannot be greater"),
        ({"house_cut_bps": 10001}, "house_cut_bps"),
        ({"call_interval_ms": 50}, "call_interval_ms"),
        ({"win_patterns": []}, "win_patterns"),
        ({"win_patterns": ["corners"]}, "win_patterns"),
        ({"min_winning_lines": 5}, "min_winning_lines"),
        ({"code": "  "}, "code is required"),
    ],
)
async def test_create_refuses_invalid_rooms(pool, overrides, message):
    admin_id, *_ = await create_test_admin(pool, role="superadmin")
    with pytest.raises(ValueError, match=message):
        await queries.create_room_admin(pool, admin_id=admin_id, **_room_kwargs(**overrides))


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"stake": "NaN"}, "amount in ETB"),
        ({"stake": "1e400"}, "at most"),
        ({"stake": "10.005"}, "whole cents"),
        ({"stake": "abc"}, "decimal number"),
        ({"min_players": 500}, "min_players"),
        ({"max_players": 1}, "min_players cannot be greater"),  # the room's min is 2
        ({"is_active": "yes"}, None),
    ],
)
async def test_update_refuses_invalid_changes(pool, conn, changes, message):
    admin_id, *_ = await create_test_admin(pool, role="superadmin")
    room_id = await create_room(conn, stake=Decimal("10.00"), min_players=2)
    if message is None:
        # A non-boolean is_active reaches the DB, which refuses it.
        with pytest.raises((ValueError, asyncpg.DataError)):
            await queries.update_room_admin(
                pool, admin_id=admin_id, room_id=room_id, changes=changes, reason="bad edit", ip_address=None
            )
    else:
        with pytest.raises(ValueError, match=message):
            await queries.update_room_admin(
                pool, admin_id=admin_id, room_id=room_id, changes=changes, reason="bad edit", ip_address=None
            )
    assert await conn.fetchval("SELECT stake FROM rooms WHERE id = $1", room_id) == Decimal("10.00")


async def test_database_refuses_a_nan_stake_even_without_the_app(conn):
    with pytest.raises(asyncpg.CheckViolationError):
        await conn.execute("INSERT INTO rooms (code, stake) VALUES ($1, 'NaN')", f"nan-{uuid.uuid4().hex[:8]}")


async def test_a_legacy_room_outside_new_ranges_can_still_be_toggled(pool, conn):
    """Validation covers what an edit changes: a room created under looser
    rules (a 10 ms call interval, as tests use) can still be deactivated."""
    admin_id, *_ = await create_test_admin(pool, role="superadmin")
    room_id = await create_room(conn, stake=Decimal("10.00"), min_players=2, call_interval_ms=10)
    assert await queries.update_room_admin(
        pool, admin_id=admin_id, room_id=room_id, changes={"is_active": False}, reason="maintenance",
        ip_address=None,
    )
    assert await conn.fetchval("SELECT is_active FROM rooms WHERE id = $1", room_id) is False


async def test_http_room_edit_requires_a_real_reason(admin_server, pool, conn):
    headers = await _auth_headers(admin_server, pool, role="ops")
    room_id = await create_room(conn, stake=Decimal("10.00"), min_players=2)
    async with httpx.AsyncClient() as client:
        missing = await client.patch(
            f"{admin_server}/rooms/{room_id}", headers=headers, json={"changes": {"stake": "15.00"}}
        )
        assert missing.status_code == 422
        ok = await client.patch(
            f"{admin_server}/rooms/{room_id}", headers=headers,
            json={"changes": {"stake": "15.00"}, "reason": "raise the entry stake for this room"},
        )
        assert ok.status_code == 200, ok.text
    assert await conn.fetchval("SELECT stake FROM rooms WHERE id = $1", room_id) == Decimal("15.00")
