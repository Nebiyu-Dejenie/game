"""Real-browser checks of the admin console's configuration screens:
platform settings, Keno rules, the tier stake editor, change history and
the grouped/mobile navigation. Each flow goes through the real confirm
dialog (diff + mandatory reason) and is checked against the database, not
just the DOM."""

from __future__ import annotations

import os
from decimal import Decimal

import pytest

from packages.core import platform_settings
from services.admin import keno_queries as admin_keno
from tests.integration.test_admin_auth import create_test_admin
from tests.integration.test_admin_console_e2e import _login

pytestmark = pytest.mark.e2e

# Set to a directory to keep screenshots of each screen for a visual check.
SCREENSHOT_DIR = os.environ.get("ADMIN_E2E_SCREENSHOTS")


async def _shot(page, name: str) -> None:
    if SCREENSHOT_DIR:
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)
        await page.screenshot(path=os.path.join(SCREENSHOT_DIR, f"{name}.png"), full_page=True)


@pytest.fixture(autouse=True)
async def _no_setting_overrides(pool):
    await pool.execute("DELETE FROM platform_settings")
    yield
    await pool.execute("DELETE FROM platform_settings")


async def _confirm(page, reason: str) -> None:
    dialog = page.locator("dialog.confirm-dialog")
    await dialog.wait_for(state="visible")
    confirm = dialog.locator("[data-confirm]")
    await dialog.locator("textarea").fill("short")
    assert await confirm.is_disabled()  # the backend's 10-character minimum, enforced up front
    await dialog.locator("textarea").fill(reason)
    await confirm.click()
    await dialog.wait_for(state="detached")


async def test_settings_screen_changes_a_limit_through_the_confirm_dialog(admin_server, pool, browser):
    _, username, password, totp = await create_test_admin(pool, role="superadmin")
    page = await browser.new_page(viewport={"width": 1280, "height": 900})
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    await _login(page, admin_server, username, password, totp)
    await page.wait_for_selector("#app-shell:not([hidden])")

    await page.click('.nav-btn[data-screen="settings"]')
    await page.wait_for_selector("#setting-min_withdraw_etb")
    await _shot(page, "settings")
    assert await page.is_disabled("#settings-review")

    await page.fill("#setting-min_withdraw_etb", "350.00")
    await page.fill("#setting-auto_approve_withdraw_etb", "9000.00")
    assert await page.is_enabled("#settings-review")
    await page.click("#settings-review")
    dialog = page.locator("dialog.confirm-dialog")
    await dialog.wait_for(state="visible")
    # Raising the auto-approve threshold is flagged as risky in the diff.
    assert "without anyone reviewing it" in await dialog.inner_text()
    await _shot(page, "settings-confirm")
    await _confirm(page, "finance asked for a higher withdrawal minimum")

    await page.wait_for_selector("text=Settings saved")
    loaded = await platform_settings.load(pool)
    assert loaded.min_withdraw_etb == Decimal("350.00")
    assert loaded.auto_approve_withdraw_etb == Decimal("9000.00")
    assert await page.is_visible('[data-reset="min_withdraw_etb"]')
    assert errors == [], errors
    await page.close()


async def test_settings_screen_shows_backend_rejection(admin_server, pool, browser):
    _, username, password, totp = await create_test_admin(pool, role="superadmin")
    page = await browser.new_page(viewport={"width": 1280, "height": 900})
    await _login(page, admin_server, username, password, totp)
    await page.wait_for_selector("#app-shell:not([hidden])")
    await page.click('.nav-btn[data-screen="settings"]')
    await page.wait_for_selector("#setting-rg_self_exclusion_minimum_days")
    await page.fill("#setting-rg_self_exclusion_minimum_days", "30")
    await page.click("#settings-review")
    await _confirm(page, "trying to weaken self-exclusion")
    toast = page.locator("#toast.toast-error")
    await toast.wait_for(state="visible")
    assert "between 180" in await toast.inner_text()
    assert (await platform_settings.load(pool)).rg_self_exclusion_minimum_days == 180
    await page.close()


async def test_finance_sees_settings_read_only(admin_server, pool, browser):
    _, username, password, totp = await create_test_admin(pool, role="finance")
    page = await browser.new_page(viewport={"width": 1280, "height": 900})
    await _login(page, admin_server, username, password, totp)
    await page.wait_for_selector("#app-shell:not([hidden])")
    await page.click('.nav-btn[data-screen="settings"]')
    await page.wait_for_selector("#setting-min_deposit_etb")
    assert await page.is_disabled("#setting-min_deposit_etb")
    assert await page.locator("#settings-review").count() == 0
    await page.close()


async def test_keno_rules_and_stake_editor(admin_server, pool, browser):
    admin_id, username, password, totp = await create_test_admin(pool, role="superadmin")
    await admin_keno.create_config_admin(
        pool, admin_id=admin_id, round_cycle_seconds=45, betting_seconds=25, draw_seconds=12,
        result_seconds=8, min_picks=1, max_picks=10, max_tickets_per_user_per_round=3,
        per_user_round_capacity_share_bps=2000, jackpot_diversion_bps=150, keno_enabled=False,
        reason="known config for the browser test",
    )
    tier = await admin_keno.create_tier_admin(
        pool, admin_id=admin_id, tier_number=1, min_reserve=Decimal("0"), max_pick_count=5,
        max_top_multiplier=Decimal("100000"), stake_options=[Decimal("10"), Decimal("20"), Decimal("50")],
        max_win_per_ticket=Decimal("800"), max_round_exposure_pct=Decimal("0.10"),
        paytable_profile="low_variance", reason="known tier for the browser test",
    )
    await admin_keno.set_current_tier_admin(pool, admin_id=admin_id, tier_id=tier["id"], reason="browser test tier")

    page = await browser.new_page(viewport={"width": 1280, "height": 900})
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    await _login(page, admin_server, username, password, totp)
    await page.wait_for_selector("#app-shell:not([hidden])")
    await page.click('.nav-btn[data-screen="keno"]')

    # Rules: slow the draw down; the derived round length updates live.
    await page.click('.subnav-btn[data-section="rules"]')
    await page.wait_for_selector("#keno-rules-form")
    await page.fill('#keno-rules-form input[name="draw_seconds"]', "18")
    assert "One round = 51 s" in await page.inner_text("#keno-cycle")
    await _shot(page, "keno-rules")
    await page.click("#keno-rules-review")
    await _confirm(page, "the draw was too fast to follow")
    await page.wait_for_selector("text=Keno rules saved")
    active = await admin_keno.get_active_config_admin(pool)
    assert active["draw_seconds"] == 18
    assert active["round_cycle_seconds"] == 51
    assert active["keno_enabled"] is False  # untouched

    # Stakes: turn 20 off, add 100, make 10 the default, use from next round.
    await page.click('.subnav-btn[data-section="tiers"]')
    await page.click(f'[data-edit-tier="{tier["id"]}"]')
    await page.wait_for_selector("#tier-edit-form")
    await page.click('[data-toggle="20.00"], [data-toggle="20"]')
    await page.fill("#new-stake", "100")
    await page.click("#add-stake")
    await page.check('input[name="default_stake"][value^="10"]')
    await _shot(page, "keno-stake-editor")
    await page.click('#tier-edit-form button[type="submit"]')
    await _confirm(page, "retire the 20 ETB stake and add 100")
    await page.wait_for_selector("text=in use from the next round")

    current = await pool.fetchrow(
        "SELECT t.* FROM keno_tier_state s JOIN keno_risk_tiers t ON t.id = s.current_tier_id WHERE s.id = 1"
    )
    assert current["id"] != tier["id"]
    assert current["stake_options"] == [Decimal("10.00"), Decimal("50.00"), Decimal("100.00")]
    assert current["disabled_stake_options"] == [Decimal("20.00")]
    assert current["default_stake"] == Decimal("10.00")
    assert errors == [], errors
    await page.close()


async def test_change_history_and_mobile_navigation(admin_server, pool, browser):
    _, username, password, totp = await create_test_admin(pool, role="ops")
    page = await browser.new_page(viewport={"width": 390, "height": 844})
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    await _login(page, admin_server, username, password, totp)
    await page.wait_for_selector("#app-shell:not([hidden])")

    # On a phone the nav collapses behind a menu button.
    assert await page.is_hidden('.nav-btn[data-screen="config_history"]')
    toggle = page.locator("#nav-toggle")
    assert (await toggle.bounding_box())["height"] >= 44
    await toggle.click()
    await page.click('.nav-btn[data-screen="config_history"]')
    await page.wait_for_selector("#history-filter")
    await page.select_option('#history-filter select[name="scope"]', "keno")
    await page.click('#history-filter button[type="submit"]')
    await page.wait_for_selector("#history-results table, #history-results .empty")
    await _shot(page, "history-mobile")
    # No horizontal page scroll at phone width.
    overflow = await page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert overflow <= 1
    # ops can't see the superadmin-only audit log or staff screens.
    await toggle.click()
    assert await page.locator('.nav-btn[data-screen="audit"]').count() == 0
    assert errors == [], errors
    await page.close()
