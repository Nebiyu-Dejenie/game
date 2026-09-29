"""Real browser: a double-click on "Grant bonus" grants one bonus, not two
(platform audit, 2026-09-29)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from tests.integration.conftest import create_funded_user
from tests.integration.test_admin_auth import create_test_admin
from tests.integration.test_admin_console_e2e import _login

pytestmark = pytest.mark.e2e


async def test_double_clicking_grant_grants_once(admin_server, pool, conn, browser):
    user_id = await create_funded_user(conn, Decimal("0"))
    _, username, password, totp = await create_test_admin(pool, role="finance")
    page = await browser.new_page(viewport={"width": 1280, "height": 900})
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    await _login(page, admin_server, username, password, totp)
    await page.wait_for_selector("#app-shell:not([hidden])", timeout=10000)
    await page.click('.nav-btn[data-screen="bonuses"]')
    await page.wait_for_selector("#manual-grant-form", timeout=10000)

    await page.fill('#manual-grant-form input[name="user_id"]', str(user_id))
    await page.fill('#manual-grant-form input[name="amount"]', "25.00")
    await page.fill('#manual-grant-form input[name="reason"]', "goodwill credit after an outage")
    await page.dblclick('#manual-grant-form button[type="submit"]')
    await page.wait_for_function(
        "document.querySelector('#manual-grant-form input[name=\"user_id\"]').value === ''", timeout=10000
    )

    assert await conn.fetchval("SELECT count(*) FROM bonuses WHERE user_id = $1", user_id) == 1
    assert errors == [], errors
    await page.close()
