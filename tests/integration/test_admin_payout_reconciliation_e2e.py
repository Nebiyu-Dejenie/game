"""Real-browser check of the "Payouts awaiting reconciliation" section on the
admin Payments screen: a payout with an unknown outcome is visible, not
silent, and Mark failed & refund returns the funds."""

from __future__ import annotations

from decimal import Decimal

import pytest

from tests.integration.test_admin_auth import create_test_admin
from tests.integration.test_admin_console_e2e import _login
from tests.integration.test_admin_payout_reconciliation import _stuck_payout
from tests.integration.test_payout_worker import _cash

pytestmark = pytest.mark.e2e


async def test_a_stuck_payout_is_visible_and_can_be_marked_failed(admin_server, pool, redis, conn, browser):
    user_id, payment_id, our_ref = await _stuck_payout(pool, redis, conn, Decimal("150.00"))
    _, username, password, totp = await create_test_admin(pool, role="finance")
    page = await browser.new_page(viewport={"width": 1280, "height": 900})
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.on("dialog", lambda dialog: dialog.accept("Chapa dashboard has no record of this transfer"))

    await _login(page, admin_server, username, password, totp)
    await page.wait_for_selector("#app-shell:not([hidden])", timeout=10000)
    await page.click('.nav-btn[data-screen="payments"]')
    row = f'#reconciliation-table tr[data-payment-id="{payment_id}"]'
    await page.wait_for_selector(row, timeout=10000)
    assert "outcome unknown" in await page.text_content(row)
    await page.screenshot(path="/tmp/admin-payouts-awaiting-reconciliation.png", full_page=True)

    await page.click(f"{row} .failed-btn")
    await page.wait_for_selector(row, state="detached", timeout=10000)

    assert await _cash(conn, user_id) == Decimal("500.00")
    assert await conn.fetchval("SELECT status FROM payments WHERE id = $1", payment_id) == "failed"
    assert errors == [], errors
    await page.close()
