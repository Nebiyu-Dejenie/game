"""Pure parsing and validation rules of packages/core/platform_settings.py."""

from decimal import Decimal

import pytest

from packages.core import platform_settings, responsible_gaming
from packages.core.config import get_settings


def test_money_is_exact_cents_from_strings_or_ints():
    assert platform_settings.coerce("min_deposit_etb", "25") == Decimal("25.00")
    assert platform_settings.coerce("min_deposit_etb", " 25.50 ") == Decimal("25.50")
    assert platform_settings.coerce("min_deposit_etb", 25) == Decimal("25.00")


@pytest.mark.parametrize("raw", [25.5, "25.555", "NaN", "Infinity", "", "1e400", True])
def test_money_rejects_floats_sub_cents_and_non_numbers(raw):
    with pytest.raises(platform_settings.InvalidSetting):
        platform_settings.coerce("min_deposit_etb", raw)


@pytest.mark.parametrize("raw", ["3", 3])
def test_ints_accept_whole_numbers(raw):
    assert platform_settings.coerce("max_withdrawals_per_day", raw) == 3


@pytest.mark.parametrize("raw", ["3.0", 3.0, "three", "-3", True])
def test_ints_reject_everything_else(raw):
    with pytest.raises(platform_settings.InvalidSetting):
        platform_settings.coerce("max_withdrawals_per_day", raw)


def test_responsible_gaming_floors_match_the_hard_constants():
    registry = platform_settings.REGISTRY
    assert registry["rg_limit_increase_delay_hours"].minimum == responsible_gaming.LIMIT_INCREASE_DELAY_HOURS
    assert registry["rg_self_exclusion_minimum_days"].minimum == responsible_gaming.SELF_EXCLUSION_MINIMUM_DAYS


def test_every_setting_has_a_default_inside_its_own_bounds():
    env = get_settings()
    for definition in platform_settings.REGISTRY.values():
        default = definition.default(env)
        assert definition.minimum <= Decimal(default) <= definition.maximum, definition.key
        assert definition.category in platform_settings.CATEGORY_LABELS


def test_cross_setting_rule():
    env = get_settings()
    values = {k: d.default(env) for k, d in platform_settings.REGISTRY.items()}
    platform_settings.validate(values)
    with pytest.raises(platform_settings.InvalidSetting):
        platform_settings.validate({**values, "daily_deposit_cap_etb": Decimal("5.00"), "min_deposit_etb": Decimal("10.00")})
