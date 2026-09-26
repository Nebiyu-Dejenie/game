"""Operator-controlled platform settings: business limits an admin can
change from the console without a redeploy.

Before this, minimum deposit, withdrawal limits, the auto-approve and KYC
thresholds and withdrawals-per-day lived only in environment variables
(packages/core/config.py), and the responsible-gaming timings were module
constants. Changing any of them meant a developer and a deploy.

How it fits together:

- REGISTRY is the one list of what's configurable: type, bounds, category
  and the plain-language description the admin console shows. The console
  renders its settings screen from it (GET /settings), so adding a setting
  here is the whole job on the UI side.
- platform_settings holds one row per key an operator has overridden. A
  key with no row uses its default -- the environment value for the
  settings that used to be env-only -- so a deployment that never touches
  the console behaves exactly as before.
- load() returns the effective values, typed. Every caller that enforces
  one of these limits (gateway, bot, admin approvals, responsible gaming)
  reads it per request, so a change applies to the next request with no
  cache to go stale.
- Writes, validation of the merged whole and the audit trail live in
  services/admin/platform_settings_queries.py.

Some bounds are safety floors rather than sanity checks: the
responsible-gaming limit-increase delay can't go below 24 hours and
self-exclusion can't be shorter than 180 days (spec section 12: "6 months
minimum"). An operator can make them stricter, never weaker.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Protocol

from packages.core.config import Settings, get_settings

Kind = Literal["money", "int"]


class InvalidSetting(Exception):
    pass


@dataclass(frozen=True)
class SettingDef:
    key: str
    kind: Kind
    category: str
    label: str
    description: str
    minimum: Decimal
    maximum: Decimal
    unit: str

    def default(self, settings: Settings) -> Decimal | int:
        value = _DEFAULTS[self.key](settings)
        return Decimal(value) if self.kind == "money" else int(value)


def _money(amount: str) -> Decimal:
    return Decimal(amount)


REGISTRY: dict[str, SettingDef] = {
    d.key: d
    for d in (
        SettingDef(
            "min_deposit_etb", "money", "deposits", "Minimum deposit",
            "The smallest deposit a player can make, on every rail.",
            _money("1.00"), _money("100000.00"), "ETB",
        ),
        SettingDef(
            "daily_deposit_cap_etb", "money", "deposits", "Daily deposit cap (platform)",
            "The most one player can deposit per day. A player's own lower responsible-gaming "
            "limit still applies on top of this.",
            _money("1.00"), _money("10000000.00"), "ETB",
        ),
        SettingDef(
            "min_withdraw_etb", "money", "withdrawals", "Minimum withdrawal",
            "The smallest withdrawal a player can request.",
            _money("1.00"), _money("1000000.00"), "ETB",
        ),
        SettingDef(
            "auto_approve_withdraw_etb", "money", "withdrawals", "Auto-approve / two-person threshold",
            "Withdrawals at or below this pay out without review. Manual deposits and withdrawals "
            "at or above it need a second admin's approval. Raising it lets more money leave "
            "without a person looking at it.",
            _money("0.00"), _money("10000000.00"), "ETB",
        ),
        SettingDef(
            "kyc_required_above_etb", "money", "withdrawals", "KYC required above",
            "Withdrawals above this need a verified identity.",
            _money("0.00"), _money("10000000.00"), "ETB",
        ),
        SettingDef(
            "withdraw_chargeback_window_minutes", "int", "withdrawals", "Deposit hold before withdrawal",
            "Minutes a fresh deposit must wait before it can be withdrawn.",
            Decimal(0), Decimal(1440), "minutes",
        ),
        SettingDef(
            "max_withdrawals_per_day", "int", "withdrawals", "Withdrawals per player per day",
            "How many withdrawal requests one player can make per day.",
            Decimal(1), Decimal(50), "requests",
        ),
        SettingDef(
            "rg_limit_increase_delay_hours", "int", "responsible_gaming", "Delay before a raised limit applies",
            "When a player raises their own deposit or loss limit, the new limit waits this long. "
            "Lowering a limit is always immediate. Can't be set below 24 hours.",
            Decimal(24), Decimal(720), "hours",
        ),
        SettingDef(
            "rg_self_exclusion_minimum_days", "int", "responsible_gaming", "Minimum self-exclusion",
            "The shortest self-exclusion a player can choose. Can't be set below 180 days.",
            Decimal(180), Decimal(3650), "days",
        ),
    )
}

CATEGORY_LABELS: dict[str, str] = {
    "deposits": "Deposits",
    "withdrawals": "Withdrawals",
    "responsible_gaming": "Responsible gaming",
}

# Defaults: the environment value where one existed, so an untouched
# deployment keeps behaving exactly as it did.
_DEFAULTS: dict[str, Any] = {
    "min_deposit_etb": lambda s: s.min_deposit_etb,
    "daily_deposit_cap_etb": lambda s: s.daily_deposit_cap_etb,
    "min_withdraw_etb": lambda s: s.min_withdraw_etb,
    "auto_approve_withdraw_etb": lambda s: s.auto_approve_withdraw_etb,
    "kyc_required_above_etb": lambda s: s.kyc_required_above_etb,
    "withdraw_chargeback_window_minutes": lambda s: s.withdraw_chargeback_window_minutes,
    "max_withdrawals_per_day": lambda s: s.max_withdrawals_per_day,
    "rg_limit_increase_delay_hours": lambda s: 24,
    "rg_self_exclusion_minimum_days": lambda s: 180,
}


@dataclass(frozen=True)
class PlatformSettings:
    min_deposit_etb: Decimal
    daily_deposit_cap_etb: Decimal
    min_withdraw_etb: Decimal
    auto_approve_withdraw_etb: Decimal
    kyc_required_above_etb: Decimal
    withdraw_chargeback_window_minutes: int
    max_withdrawals_per_day: int
    rg_limit_increase_delay_hours: int
    rg_self_exclusion_minimum_days: int


class _Fetcher(Protocol):
    async def fetch(self, query: str, *args: Any) -> Any: ...


def coerce(key: str, raw: Any) -> Decimal | int:
    """Parses and range-checks one value. Raises InvalidSetting."""
    definition = REGISTRY.get(key)
    if definition is None:
        raise InvalidSetting(f"unknown setting: {key}")
    if isinstance(raw, bool):
        raise InvalidSetting(f"{definition.label} must be a number")
    if definition.kind == "int":
        if isinstance(raw, float) or (isinstance(raw, str) and not raw.strip().lstrip("-").isdigit()):
            raise InvalidSetting(f"{definition.label} must be a whole number")
        try:
            value: Decimal | int = int(raw)
        except (TypeError, ValueError) as exc:
            raise InvalidSetting(f"{definition.label} must be a whole number") from exc
    else:
        if isinstance(raw, float):
            # Money never goes through binary floating point.
            raise InvalidSetting(f"{definition.label} must be sent as a string like \"200.00\"")
        try:
            amount = Decimal(str(raw).strip())
        except InvalidOperation as exc:
            raise InvalidSetting(f"{definition.label} must be an amount in ETB") from exc
        if not amount.is_finite() or abs(amount) > definition.maximum * 10:
            # Checked before quantize(), which raises on huge exponents.
            raise InvalidSetting(
                f"{definition.label} must be between {definition.minimum} and {definition.maximum} {definition.unit}"
            )
        if amount != amount.quantize(Decimal("0.01")):
            raise InvalidSetting(f"{definition.label} must be an amount in whole cents")
        value = amount.quantize(Decimal("0.01"))
    if not definition.minimum <= Decimal(value) <= definition.maximum:
        raise InvalidSetting(
            f"{definition.label} must be between {definition.minimum} and {definition.maximum} {definition.unit}"
        )
    return value


def validate(values: dict[str, Decimal | int]) -> None:
    """Rules across settings, checked on the complete merged set so no
    order of individual edits can reach an impossible combination."""
    if values["daily_deposit_cap_etb"] < values["min_deposit_etb"]:
        raise InvalidSetting("the daily deposit cap can't be below the minimum deposit")


def _stored_value(raw: Any) -> Any:
    # asyncpg hands jsonb back as its JSON text
    return json.loads(raw) if isinstance(raw, str) else raw


async def load_values(db: _Fetcher, settings: Settings | None = None) -> dict[str, Decimal | int]:
    settings = settings or get_settings()
    values: dict[str, Decimal | int] = {key: d.default(settings) for key, d in REGISTRY.items()}
    for row in await db.fetch("SELECT key, value FROM platform_settings"):
        if row["key"] in REGISTRY:
            # A stored value was valid when written; if a later release
            # tightened a bound, fall back to the default rather than
            # enforce a value the code no longer accepts.
            try:
                values[row["key"]] = coerce(row["key"], _stored_value(row["value"]))
            except InvalidSetting:
                continue
    return values


async def load(db: _Fetcher, settings: Settings | None = None) -> PlatformSettings:
    v = await load_values(db, settings)
    return PlatformSettings(
        min_deposit_etb=Decimal(v["min_deposit_etb"]),
        daily_deposit_cap_etb=Decimal(v["daily_deposit_cap_etb"]),
        min_withdraw_etb=Decimal(v["min_withdraw_etb"]),
        auto_approve_withdraw_etb=Decimal(v["auto_approve_withdraw_etb"]),
        kyc_required_above_etb=Decimal(v["kyc_required_above_etb"]),
        withdraw_chargeback_window_minutes=int(v["withdraw_chargeback_window_minutes"]),
        max_withdrawals_per_day=int(v["max_withdrawals_per_day"]),
        rg_limit_increase_delay_hours=int(v["rg_limit_increase_delay_hours"]),
        rg_self_exclusion_minimum_days=int(v["rg_self_exclusion_minimum_days"]),
    )


def to_json(value: Decimal | int) -> str:
    return json.dumps(str(value) if isinstance(value, Decimal) else value)
