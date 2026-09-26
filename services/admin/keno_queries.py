"""Keno admin queries (build spec Part 15): config/paytable/tier
management and the kill switch, all audited. Mirrors
services/admin/bonus_queries.py's own layering -- domain logic
(packages.core.keno's guardrails, keno_config's "what's active" readers)
stays audit-agnostic; this module is what adds services/admin/audit.py's
audit trail on top, inside the same transaction as the mutation itself.

Every write here is insert-only-versioned (keno_configs/keno_paytables/
keno_risk_tiers rows are never updated in place -- a "change" is a new
row with a later effective_from), which is what makes "effective from
the next round only" (Part 15) true by construction: the engine only
re-reads "what's currently active" at round-creation time.
"""

from __future__ import annotations

import json
import math
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

import asyncpg

from packages.core import keno, keno_business_metrics, keno_config, keno_risk_simulator, ledger, metrics
from services.admin import audit


class InvalidKenoConfig(Exception):
    pass


class ReserveWithdrawalBelowFloor(Exception):
    """Part 7.1's own withdrawal-floor rule: 'the admin cannot withdraw
    below a configurable reserve floor. Attempts are blocked and
    audited' -- both halves of that sentence matter, so this is a typed
    exception the caller can catch, not a generic InvalidKenoConfig,
    and withdraw_from_reserve_admin() below audits the rejection itself,
    not only successful withdrawals."""

    def __init__(self, attempted_balance: Decimal, floor: Decimal) -> None:
        self.attempted_balance = attempted_balance
        self.floor = floor
        super().__init__(f"withdrawal would leave reserve at {attempted_balance}, below floor {floor}")


def _json_safe(row: asyncpg.Record | dict[str, Any]) -> dict[str, Any]:
    """services/admin/audit.py's record() does a plain json.dumps() on
    before/after with no custom encoder (the established convention
    throughout this codebase -- every existing admin-query module hand
    -curates its own audit dict rather than passing a raw row for
    exactly this reason). keno_configs/keno_paytables/keno_risk_tiers
    rows carry Decimal, datetime, list[Decimal], and (multipliers) raw
    jsonb-as-string columns that plain json.dumps can't serialize --
    this converts them once, consistently, rather than hand-curating a
    field list per call site and risking one silently drifting out of
    sync with the schema."""
    safe: dict[str, Any] = {}
    for key, value in dict(row).items():
        if isinstance(value, Decimal):
            safe[key] = str(value)
        elif isinstance(value, list):
            safe[key] = [str(v) if isinstance(v, Decimal) else v for v in value]
        elif isinstance(value, (bytes, bytearray)):
            safe[key] = value.hex()
        elif hasattr(value, "isoformat"):  # date/datetime/time
            safe[key] = value.isoformat()
        else:
            safe[key] = value
    return safe


async def list_configs_admin(pool: asyncpg.Pool, *, limit: int = 20) -> list[dict[str, Any]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM keno_configs ORDER BY id DESC LIMIT $1", limit)
    return [dict(row) for row in rows]


async def get_active_config_admin(pool: asyncpg.Pool) -> dict[str, Any]:
    async with pool.acquire() as conn:
        row = await keno_config.load_active_config(conn)
    return dict(row)


# --- keno_configs: copy-forward versioning -------------------------------
#
# A config "change" is a new row. The bug this replaces: every writer
# listed the columns it copied by hand, so a column added later
# (reserve_withdrawal_floor, beta_restricted, the circuit-breaker
# multiple) was silently dropped and reset to its DB default whenever the
# kill switch was flipped -- e.g. a 50,000 ETB reserve withdrawal floor
# became 0. _insert_config_version copies every column of the base row
# that isn't row identity, so a future column is carried forward by
# construction instead of by remembering to add it here.

_CONFIG_IDENTITY_COLUMNS = frozenset({"id", "version", "effective_from", "created_by_admin_id", "created_at"})

# Defaults for the very first config on a deployment (no row to copy
# from yet) -- the same values the launch seed migration uses.
_FIRST_CONFIG_DEFAULTS: dict[str, Any] = {
    "number_pool_size": keno.NUMBER_POOL_SIZE,
    "draw_count": keno.DRAW_COUNT,
    "min_picks": keno.MIN_PICKS,
    "max_picks": keno.MAX_PICKS,
    "round_cycle_seconds": 45,
    "betting_seconds": 25,
    "draw_seconds": 12,
    "result_seconds": 8,
    "max_tickets_per_user_per_round": 3,
    "per_user_round_capacity_share_bps": 2000,
    "jackpot_diversion_bps": 150,
    "rtp_floor_bps": int(keno.RTP_FLOOR * 10000),
    "rtp_ceiling_bps": int(keno.RTP_CEILING * 10000),
    "daily_payout_circuit_breaker_multiple": Decimal("3.0"),
    "keno_enabled": False,
    "reserve_withdrawal_floor": Decimal("0"),
    "beta_restricted": True,
    "max_autoplay_rounds": 100,
}

# What PATCH /keno/configs may change. Deliberately excluded:
# keno_enabled (only the audited kill switch flips it), number_pool_size /
# draw_count (the paytable math in packages/core/keno.py is exact for
# 20-from-80 only), and round_cycle_seconds (derived: the engine runs
# betting + draw + result back to back and never reads it).
EDITABLE_CONFIG_FIELDS: dict[str, type] = {
    "betting_seconds": int,
    "draw_seconds": int,
    "result_seconds": int,
    "min_picks": int,
    "max_picks": int,
    "max_tickets_per_user_per_round": int,
    "per_user_round_capacity_share_bps": int,
    "jackpot_diversion_bps": int,
    "rtp_floor_bps": int,
    "rtp_ceiling_bps": int,
    "daily_payout_circuit_breaker_multiple": Decimal,
    "reserve_withdrawal_floor": Decimal,
    "beta_restricted": bool,
    "max_autoplay_rounds": int,
}

# Hard bounds. Chosen as "outside this is a mistake, not a strategy":
# the engine needs >= 50 ms per revealed ball; a betting window under 5 s
# can't be used on a slow phone; the jackpot is a side pot, not the game.
_CONFIG_INT_BOUNDS: dict[str, tuple[int, int]] = {
    "betting_seconds": (5, 600),
    "draw_seconds": (3, 300),
    "result_seconds": (1, 300),
    "min_picks": (keno.MIN_PICKS, keno.MAX_PICKS),
    "max_picks": (keno.MIN_PICKS, keno.MAX_PICKS),
    "max_tickets_per_user_per_round": (1, 50),
    "per_user_round_capacity_share_bps": (1, 10000),
    "jackpot_diversion_bps": (0, 1000),
    "rtp_floor_bps": (int(keno.RTP_FLOOR * 10000), int(keno.RTP_CEILING * 10000)),
    "rtp_ceiling_bps": (int(keno.RTP_FLOOR * 10000), int(keno.RTP_CEILING * 10000)),
    "max_autoplay_rounds": (1, 100),
}


def _coerce_config_value(field: str, value: Any) -> Any:
    kind = EDITABLE_CONFIG_FIELDS[field]
    if kind is bool:
        if not isinstance(value, bool):
            raise InvalidKenoConfig(f"{field} must be true or false")
        return value
    if kind is int:
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise InvalidKenoConfig(f"{field} must be a whole number")
        try:
            return int(value)
        except ValueError as exc:
            raise InvalidKenoConfig(f"{field} must be a whole number") from exc
    try:
        decimal_value = Decimal(str(value))
    except InvalidOperation as exc:
        raise InvalidKenoConfig(f"{field} must be a number") from exc
    if not decimal_value.is_finite() or abs(decimal_value) > Decimal("1e15"):
        raise InvalidKenoConfig(f"{field} must be a usable number")
    return decimal_value


def validate_config_values(values: dict[str, Any]) -> None:
    """Checks one complete, merged config. Raises InvalidKenoConfig with
    the first problem found, worded for the admin who has to fix it."""
    for field, (low, high) in _CONFIG_INT_BOUNDS.items():
        if not low <= int(values[field]) <= high:
            raise InvalidKenoConfig(f"{field} must be between {low} and {high}, got {values[field]}")
    if values["number_pool_size"] != keno.NUMBER_POOL_SIZE or values["draw_count"] != keno.DRAW_COUNT:
        raise InvalidKenoConfig(
            f"the paytable math supports {keno.DRAW_COUNT} from {keno.NUMBER_POOL_SIZE} only"
        )
    if values["min_picks"] > values["max_picks"]:
        raise InvalidKenoConfig("min_picks cannot be greater than max_picks")
    if values["rtp_floor_bps"] > values["rtp_ceiling_bps"]:
        raise InvalidKenoConfig("the RTP floor cannot be above the RTP ceiling")
    if values["draw_seconds"] * 1000 / values["draw_count"] < 50:
        raise InvalidKenoConfig("draw_seconds is too short to reveal every number (minimum 50 ms per number)")
    minimum_cycle = values["betting_seconds"] + values["draw_seconds"] + values["result_seconds"]
    if values["round_cycle_seconds"] < minimum_cycle:
        raise InvalidKenoConfig(
            f"round_cycle_seconds ({values['round_cycle_seconds']}) is shorter than betting + draw + result "
            f"({minimum_cycle})"
        )
    multiple = Decimal(values["daily_payout_circuit_breaker_multiple"])
    if not Decimal("1") <= multiple <= Decimal("50"):
        raise InvalidKenoConfig("daily_payout_circuit_breaker_multiple must be between 1 and 50")
    floor = Decimal(values["reserve_withdrawal_floor"])
    if floor < 0 or floor > Decimal("1e15") or floor != floor.quantize(Decimal("0.01")):
        raise InvalidKenoConfig("reserve_withdrawal_floor must be zero or more, in whole cents")


async def _active_paytable_rtps(conn: ledger.AsyncpgConnection) -> list[asyncpg.Record]:
    return list(
        await conn.fetch(
            """
            SELECT DISTINCT ON (pick_count, profile) pick_count, profile, computed_rtp_bps
            FROM keno_paytables WHERE effective_from <= now()
            ORDER BY pick_count, profile, effective_from DESC, id DESC
            """
        )
    )


async def _check_rtp_band_covers_live_paytables(
    conn: ledger.AsyncpgConnection, floor_bps: int, ceiling_bps: int
) -> None:
    """A guardrail band that live paytables already sit outside of would
    make the guardrail a lie. Refuse it, and name the tables to fix first."""
    outside = [
        f"{row['profile']} {row['pick_count']}-pick ({Decimal(row['computed_rtp_bps']) / 100}%)"
        for row in await _active_paytable_rtps(conn)
        if not floor_bps <= row["computed_rtp_bps"] <= ceiling_bps
    ]
    if outside:
        raise InvalidKenoConfig(
            "these live paytables fall outside the new RTP band; change them first: " + ", ".join(outside)
        )


async def rtp_band(conn: ledger.AsyncpgConnection) -> tuple[Decimal, Decimal]:
    """The RTP guardrail actually in force: the active config's band, which
    validate_config_values keeps inside keno.RTP_FLOOR..RTP_CEILING. Before
    this, the config's rtp_floor_bps/rtp_ceiling_bps were stored but never
    read -- paytables were always checked against the module constants."""
    row = await conn.fetchrow(
        "SELECT rtp_floor_bps, rtp_ceiling_bps FROM keno_configs "
        "WHERE effective_from <= now() ORDER BY effective_from DESC LIMIT 1"
    )
    if row is None:
        return keno.RTP_FLOOR, keno.RTP_CEILING
    return Decimal(row["rtp_floor_bps"]) / 10000, Decimal(row["rtp_ceiling_bps"]) / 10000


async def _base_config(conn: ledger.AsyncpgConnection) -> dict[str, Any]:
    row = await conn.fetchrow(
        "SELECT * FROM keno_configs WHERE effective_from <= now() ORDER BY effective_from DESC LIMIT 1"
    )
    if row is None:
        return dict(_FIRST_CONFIG_DEFAULTS)
    return {k: v for k, v in dict(row).items() if k not in _CONFIG_IDENTITY_COLUMNS}


async def _insert_config_version(
    conn: ledger.AsyncpgConnection,
    *,
    values: dict[str, Any],
    admin_id: int,
    effective_from: Any = None,
) -> asyncpg.Record:
    # Serialize concurrent writers so two admins can't both compute the
    # same next version number (the table has no unique constraint on it).
    await conn.execute("LOCK TABLE keno_configs IN SHARE ROW EXCLUSIVE MODE")
    version = await conn.fetchval("SELECT COALESCE(MAX(version), 0) + 1 FROM keno_configs")
    columns = list(values)
    for column in columns:
        if not column.isidentifier():  # column names come from the table itself; belt and braces
            raise InvalidKenoConfig(f"bad column {column!r}")
    placeholders = ", ".join(f"${i}" for i in range(1, len(columns) + 1))
    n = len(columns)
    row = await conn.fetchrow(
        f"""
        INSERT INTO keno_configs ({", ".join(columns)}, version, created_by_admin_id, effective_from)
        VALUES ({placeholders}, ${n + 1}, ${n + 2}, COALESCE(${n + 3}, now()))
        RETURNING *
        """,
        *[values[c] for c in columns], version, admin_id, effective_from,
    )
    assert row is not None  # INSERT ... RETURNING * always yields exactly one row
    return row


async def create_config_admin(
    pool: asyncpg.Pool,
    *,
    admin_id: int,
    round_cycle_seconds: int,
    betting_seconds: int,
    draw_seconds: int,
    result_seconds: int,
    min_picks: int,
    max_picks: int,
    max_tickets_per_user_per_round: int,
    per_user_round_capacity_share_bps: int,
    jackpot_diversion_bps: int,
    rtp_floor_bps: int = 7500,
    rtp_ceiling_bps: int = 9700,
    keno_enabled: bool,
    reason: str,
    effective_from: Any = None,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Full-config create (POST /keno/configs). Every column it doesn't
    name is carried forward from the active config rather than reset."""
    if not reason.strip():
        raise InvalidKenoConfig("reason is required")
    async with pool.acquire() as conn:
        async with conn.transaction():
            values = await _base_config(conn)
            values.update(
                round_cycle_seconds=round_cycle_seconds, betting_seconds=betting_seconds,
                draw_seconds=draw_seconds, result_seconds=result_seconds, min_picks=min_picks,
                max_picks=max_picks, max_tickets_per_user_per_round=max_tickets_per_user_per_round,
                per_user_round_capacity_share_bps=per_user_round_capacity_share_bps,
                jackpot_diversion_bps=jackpot_diversion_bps, rtp_floor_bps=rtp_floor_bps,
                rtp_ceiling_bps=rtp_ceiling_bps, keno_enabled=keno_enabled,
            )
            validate_config_values(values)
            await _check_rtp_band_covers_live_paytables(conn, rtp_floor_bps, rtp_ceiling_bps)
            row = await _insert_config_version(conn, values=values, admin_id=admin_id, effective_from=effective_from)
            await audit.record(
                conn, admin_id=admin_id, action="keno.config.create", target_type="keno_config",
                target_id=str(row["id"]), before=None, after=_json_safe(row), reason=reason,
                ip_address=ip_address,
            )
    return dict(row)


async def update_config_admin(
    pool: asyncpg.Pool,
    *,
    admin_id: int,
    changes: dict[str, Any],
    reason: str,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Change some Keno rules (PATCH /keno/configs). Validates the whole
    merged config, writes a new version effective from the next round,
    and audits only the fields that actually changed, with before and
    after. round_cycle_seconds is recomputed from the three phases."""
    if not reason.strip():
        raise InvalidKenoConfig("reason is required")
    unknown = sorted(set(changes) - set(EDITABLE_CONFIG_FIELDS))
    if unknown:
        raise InvalidKenoConfig(f"these settings can't be changed here: {', '.join(unknown)}")
    coerced = {field: _coerce_config_value(field, value) for field, value in changes.items()}
    async with pool.acquire() as conn:
        async with conn.transaction():
            current = await _base_config(conn)
            merged = {**current, **coerced}
            merged["round_cycle_seconds"] = (
                merged["betting_seconds"] + merged["draw_seconds"] + merged["result_seconds"]
            )
            diff_before = {k: current[k] for k in merged if merged[k] != current.get(k)}
            if not diff_before:
                raise InvalidKenoConfig("nothing changed")
            validate_config_values(merged)
            if "rtp_floor_bps" in diff_before or "rtp_ceiling_bps" in diff_before:
                await _check_rtp_band_covers_live_paytables(conn, merged["rtp_floor_bps"], merged["rtp_ceiling_bps"])
            row = await _insert_config_version(conn, values=merged, admin_id=admin_id)
            await audit.record(
                conn, admin_id=admin_id, action="keno.config.update", target_type="keno_config",
                target_id=str(row["id"]), before=_json_safe(diff_before),
                after=_json_safe({k: merged[k] for k in diff_before}), reason=reason, ip_address=ip_address,
            )
    return dict(row)


async def set_keno_enabled_admin(
    pool: asyncpg.Pool, *, admin_id: int, enabled: bool, reason: str, ip_address: str | None = None
) -> dict[str, Any]:
    """The kill switch (Part 0: "one admin toggle... that instantly stops
    new rounds and blocks new tickets while still settling in-flight
    tickets"). A new config version identical to the active one except
    keno_enabled. Turning it off never touches a round already past
    betting_open: place_ticket() checks keno_enabled, the round engine's
    own lifecycle does not."""
    if not reason.strip():
        raise InvalidKenoConfig("reason is required")
    async with pool.acquire() as conn:
        async with conn.transaction():
            current = await keno_config.load_active_config(conn)
            values = {k: v for k, v in dict(current).items() if k not in _CONFIG_IDENTITY_COLUMNS}
            values["keno_enabled"] = enabled
            row = await _insert_config_version(conn, values=values, admin_id=admin_id)
            await audit.record(
                conn, admin_id=admin_id, action="keno.kill_switch",
                target_type="keno_config", target_id=str(row["id"]),
                before={"keno_enabled": current["keno_enabled"]}, after={"keno_enabled": enabled},
                reason=reason, ip_address=ip_address,
            )
    return dict(row)


async def list_paytables_admin(pool: asyncpg.Pool, *, pick_count: int | None = None) -> list[dict[str, Any]]:
    async with pool.acquire() as conn:
        if pick_count is not None:
            rows = await conn.fetch(
                "SELECT * FROM keno_paytables WHERE pick_count = $1 ORDER BY id DESC", pick_count
            )
        else:
            rows = await conn.fetch("SELECT * FROM keno_paytables ORDER BY pick_count, id DESC")
    return [_paytable_row_to_dict(row) for row in rows]


def _paytable_row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    data = dict(row)
    data["multipliers"] = json.loads(row["multipliers"])
    return data


def preview_paytable_stats(
    pick_count: int,
    multipliers: dict[str, str],
    *,
    floor: Decimal = keno.RTP_FLOOR,
    ceiling: Decimal = keno.RTP_CEILING,
) -> dict[str, Any]:
    """Part 15's "live RTP, hit frequency, volatility" preview -- pure,
    no DB, callable on every keystroke of the admin paytable editor
    before anything is saved. The caller passes the band from
    rtp_band() so the preview agrees with what saving will enforce."""
    decimal_multipliers = {int(k): Decimal(v) for k, v in multipliers.items()}
    stats = keno.compute_paytable_stats(pick_count, decimal_multipliers)
    within_guardrail = floor <= stats.rtp <= ceiling
    return {
        "rtp": str(stats.rtp),
        "hit_frequency": str(stats.hit_frequency),
        "max_multiplier": str(stats.max_multiplier),
        "volatility": str(stats.volatility),
        "within_guardrail": within_guardrail,
        "rtp_floor": str(floor),
        "rtp_ceiling": str(ceiling),
    }


def simulate_risk_of_ruin_admin(
    *,
    starting_reserve: str,
    daily_handle: str,
    avg_stake: str,
    pick_count: int,
    multipliers: dict[str, str],
    jackpot_diversion_bps: int,
    floor: str,
    days: int,
    num_simulations: int,
    rng_seed: int | None = None,
) -> dict[str, Any]:
    """Part 7.4's risk-of-ruin simulator -- pure, no DB, same "compare a
    hypothetical before committing to it" shape as preview_paytable_stats()
    above: every input is admin-supplied, not read from the live system,
    so comparing several candidate reserve/handle/paytable combinations
    costs nothing but repeat calls. See packages.core.keno_risk_simulator's
    own module docstring for the simulation methodology and for what
    Part 7.4 also asks for (handle-per-deposit/session-length comparison)
    that this deliberately does NOT cover -- no real player-behavior data
    exists to ground those numbers in."""
    try:
        decimal_multipliers = {int(k): Decimal(v) for k, v in multipliers.items()}
        result = keno_risk_simulator.simulate_risk_of_ruin(
            starting_reserve=Decimal(starting_reserve),
            daily_handle=Decimal(daily_handle),
            avg_stake=Decimal(avg_stake),
            pick_count=pick_count,
            multipliers=decimal_multipliers,
            jackpot_diversion_bps=jackpot_diversion_bps,
            floor=Decimal(floor),
            days=days,
            num_simulations=num_simulations,
            rng_seed=rng_seed,
        )
    except (InvalidOperation, ValueError, KeyError, keno_risk_simulator.InvalidSimulationInput) as exc:
        raise InvalidKenoConfig(f"invalid simulation input: {exc}") from exc
    return {
        "days": result.days,
        "num_simulations": result.num_simulations,
        "starting_reserve": str(result.starting_reserve),
        "floor": str(result.floor),
        "ending_reserve_p10": str(result.ending_reserve_p10),
        "ending_reserve_p50": str(result.ending_reserve_p50),
        "ending_reserve_p90": str(result.ending_reserve_p90),
        "ending_reserve_mean": str(result.ending_reserve_mean),
        "worst_drawdown_mean": str(result.worst_drawdown_mean),
        "worst_drawdown_max": str(result.worst_drawdown_max),
        "floor_breach_probability": str(result.floor_breach_probability),
    }


async def create_paytable_admin(
    pool: asyncpg.Pool,
    *,
    admin_id: int,
    pick_count: int,
    profile: str,
    multipliers: dict[str, str],
    reason: str,
    effective_from: Any = None,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Validates the RTP guardrail server-side (Part 3.2: "refuse to
    activate any paytable where RTP exceeds/falls below" the configured
    ceiling/floor) -- this is the actual enforcement point, never just a
    UI warning the admin console could be bypassed by calling the API
    directly."""
    if not reason.strip():
        raise InvalidKenoConfig("reason is required")
    if profile not in ("low_variance", "standard"):
        raise InvalidKenoConfig(f"unknown profile: {profile!r}")

    try:
        decimal_multipliers = {int(k): Decimal(v) for k, v in multipliers.items()}
    except (ValueError, InvalidOperation) as exc:
        raise InvalidKenoConfig("multipliers must map match counts to numbers") from exc
    stats = keno.compute_paytable_stats(pick_count, decimal_multipliers)

    async with pool.acquire() as conn:
        async with conn.transaction():
            floor, ceiling = await rtp_band(conn)
            try:
                rtp = keno.validate_paytable_rtp(pick_count, decimal_multipliers, floor=floor, ceiling=ceiling)
            except keno.PaytableRTPOutOfRange as exc:
                raise InvalidKenoConfig(str(exc)) from exc
            # The other half of validate_tier_values()'s top-multiplier
            # check: a tier's max_top_multiplier is a promise about every
            # paytable it can serve, so a paytable can't quietly break it.
            capped = await conn.fetch(
                """
                SELECT tier_number, max_top_multiplier FROM keno_risk_tiers t
                WHERE paytable_profile = $1 AND max_pick_count >= $2
                  AND (id = (SELECT current_tier_id FROM keno_tier_state WHERE id = 1)
                       OR version = (SELECT MAX(version) FROM keno_risk_tiers t2 WHERE t2.tier_number = t.tier_number))
                """,
                profile, pick_count,
            )
            over = sorted({
                f"tier {row['tier_number']} ({row['max_top_multiplier']}x)"
                for row in capped if stats.max_multiplier > Decimal(row["max_top_multiplier"])
            })
            if over:
                raise InvalidKenoConfig(
                    f"top multiplier {stats.max_multiplier}x is above the cap of " + ", ".join(over)
                    + "; raise the tier cap first"
                )
            version = await conn.fetchval(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM keno_paytables WHERE pick_count = $1", pick_count
            )
            row = await conn.fetchrow(
                """
                INSERT INTO keno_paytables
                    (pick_count, version, profile, multipliers, computed_rtp_bps, hit_frequency_bps,
                     max_multiplier, volatility, created_by_admin_id, effective_from)
                VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7, $8, $9, COALESCE($10, now()))
                RETURNING *
                """,
                pick_count, version, profile, json.dumps(multipliers),
                int(rtp * 10000), int(stats.hit_frequency * 10000), stats.max_multiplier,
                stats.volatility, admin_id, effective_from,
            )
            assert row is not None  # INSERT ... RETURNING * always yields exactly one row
            await audit.record(
                conn, admin_id=admin_id, action="keno.paytable.create", target_type="keno_paytable",
                target_id=str(row["id"]), before=None, after=_json_safe(_paytable_row_to_dict(row)), reason=reason,
                ip_address=ip_address,
            )
    return _paytable_row_to_dict(row)


async def list_tiers_admin(pool: asyncpg.Pool) -> list[dict[str, Any]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM keno_risk_tiers ORDER BY tier_number, id DESC")
        current = await conn.fetchrow(
            "SELECT current_tier_id, candidate_tier_id, candidate_since FROM keno_tier_state WHERE id = 1"
        )
    tiers = [dict(row) for row in rows]
    current_tier_id = current["current_tier_id"] if current else None
    for tier in tiers:
        tier["is_current"] = tier["id"] == current_tier_id
    return tiers


# --- keno_risk_tiers: stake management and validation --------------------
#
# A tier's stake_options is the one list place_ticket() enforces, in the
# order the Mini App shows the chips. disabled_stake_options keeps stakes
# an operator switched off, so re-enabling one is a click rather than
# retyping it; they're never accepted for a ticket because they aren't in
# stake_options. The migration's CHECKs back every rule below that can be
# expressed in SQL, so a bug here still can't store a default that isn't
# offered or a stake that's both on and off.

TIER_PROFILES = ("low_variance", "standard")
MAX_STAKE_OPTIONS = 12
MAX_STAKE_AMOUNT = Decimal("100000.00")
_CENT = Decimal("0.01")

EDITABLE_TIER_FIELDS = frozenset({
    "min_reserve", "max_pick_count", "max_top_multiplier", "stake_options", "disabled_stake_options",
    "default_stake", "max_win_per_ticket", "max_round_exposure_pct", "paytable_profile",
})


def _money(field: str, value: Any, *, allow_zero: bool = False) -> Decimal:
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise InvalidKenoConfig(f"{field} must be an amount in ETB") from exc
    if not amount.is_finite() or abs(amount) > Decimal("1e15"):
        # Checked before quantize(), which raises on huge exponents.
        raise InvalidKenoConfig(f"{field} is not a usable amount, got {value}")
    if amount != amount.quantize(_CENT):
        raise InvalidKenoConfig(f"{field} must be an amount in whole cents, got {value}")
    if amount < 0 or (amount == 0 and not allow_zero):
        raise InvalidKenoConfig(f"{field} must be more than zero, got {value}")
    return amount.quantize(_CENT)


def normalize_stakes(field: str, values: Any) -> list[Decimal]:
    """Exact-cent, positive, unique stakes, order preserved (order is the
    display order the operator chose)."""
    if not isinstance(values, list):
        raise InvalidKenoConfig(f"{field} must be a list of amounts")
    stakes = [_money(field, v) for v in values]
    for stake in stakes:
        if stake > MAX_STAKE_AMOUNT:
            raise InvalidKenoConfig(f"{field}: {stake} is above the {MAX_STAKE_AMOUNT} ETB maximum stake")
    duplicates = sorted({str(s) for s in stakes if stakes.count(s) > 1})
    if duplicates:
        raise InvalidKenoConfig(f"{field} lists the same stake twice: {', '.join(duplicates)}")
    if len(stakes) > MAX_STAKE_OPTIONS:
        raise InvalidKenoConfig(f"{field} can hold at most {MAX_STAKE_OPTIONS} stakes")
    return stakes


def _normalize_tier_values(values: dict[str, Any]) -> dict[str, Any]:
    out = dict(values)
    out["min_reserve"] = _money("min_reserve", values["min_reserve"], allow_zero=True)
    out["max_win_per_ticket"] = _money("max_win_per_ticket", values["max_win_per_ticket"])
    try:
        out["max_top_multiplier"] = Decimal(str(values["max_top_multiplier"]))
        out["max_round_exposure_pct"] = Decimal(str(values["max_round_exposure_pct"]))
        out["max_pick_count"] = int(values["max_pick_count"])
        out["tier_number"] = int(values["tier_number"])
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise InvalidKenoConfig(f"invalid tier value: {exc}") from exc
    out["stake_options"] = normalize_stakes("stake_options", values["stake_options"])
    out["disabled_stake_options"] = normalize_stakes("disabled_stake_options", values.get("disabled_stake_options") or [])
    default = values.get("default_stake")
    out["default_stake"] = None if default in (None, "") else _money("default_stake", default)
    return out


async def validate_tier_values(conn: ledger.AsyncpgConnection, values: dict[str, Any]) -> list[str]:
    """Raises InvalidKenoConfig for anything that would break ticket
    placement or pay out wrongly; returns warnings for combinations that
    are legal but probably not what the operator meant."""
    if values["tier_number"] < 1:
        raise InvalidKenoConfig("tier_number must be 1 or more")
    if values["paytable_profile"] not in TIER_PROFILES:
        raise InvalidKenoConfig(f"unknown paytable profile: {values['paytable_profile']!r}")
    if not keno.MIN_PICKS <= values["max_pick_count"] <= keno.MAX_PICKS:
        raise InvalidKenoConfig(f"max_pick_count must be between {keno.MIN_PICKS} and {keno.MAX_PICKS}")
    if not values["max_top_multiplier"].is_finite() or values["max_top_multiplier"] <= 0:
        raise InvalidKenoConfig("max_top_multiplier must be more than zero")
    pct = values["max_round_exposure_pct"]
    if not pct.is_finite() or not Decimal("0") < pct <= Decimal("1"):
        raise InvalidKenoConfig("max_round_exposure_pct must be more than 0 and at most 1 (100% of the reserve)")
    enabled = values["stake_options"]
    disabled = values["disabled_stake_options"]
    if not enabled:
        raise InvalidKenoConfig("at least one stake must be enabled")
    both = sorted({str(s) for s in enabled} & {str(s) for s in disabled})
    if both:
        raise InvalidKenoConfig(f"a stake can't be both enabled and disabled: {', '.join(both)}")
    if values["default_stake"] is not None and values["default_stake"] not in enabled:
        raise InvalidKenoConfig(f"the default stake {values['default_stake']} is not one of the enabled stakes")
    if values["max_win_per_ticket"] < max(enabled):
        # A capped "win" smaller than the stake that bought it is a loss
        # dressed up as a win.
        raise InvalidKenoConfig(
            f"max_win_per_ticket ({values['max_win_per_ticket']}) must be at least the largest stake ({max(enabled)})"
        )

    paytables = await conn.fetch(
        """
        SELECT DISTINCT ON (pick_count) pick_count, max_multiplier FROM keno_paytables
        WHERE profile = $1 AND pick_count <= $2 AND effective_from <= now()
        ORDER BY pick_count, effective_from DESC, id DESC
        """,
        values["paytable_profile"], values["max_pick_count"],
    )
    missing = sorted(set(range(1, values["max_pick_count"] + 1)) - {row["pick_count"] for row in paytables})
    if missing:
        raise InvalidKenoConfig(
            f"no live {values['paytable_profile']} paytable for pick counts {', '.join(map(str, missing))}; "
            "create those first or lower max_pick_count"
        )
    too_high = [
        f"{row['pick_count']}-pick ({row['max_multiplier']}x)"
        for row in paytables
        if Decimal(row["max_multiplier"]) > values["max_top_multiplier"]
    ]
    if too_high:
        raise InvalidKenoConfig(
            f"live paytables exceed this tier's top multiplier ({values['max_top_multiplier']}x): "
            + ", ".join(too_high)
        )

    warnings: list[str] = []
    round_ceiling = values["min_reserve"] * pct
    if values["min_reserve"] > 0 and values["max_win_per_ticket"] > round_ceiling:
        warnings.append(
            f"at this tier's minimum reserve the round exposure ceiling is {round_ceiling.quantize(_CENT)} ETB, "
            f"below the {values['max_win_per_ticket']} ETB max win, so large tickets may be refused"
        )
    if values["default_stake"] is None:
        warnings.append("no default stake: the Mini App preselects the first enabled stake")
    return warnings


async def _insert_tier_version(
    conn: ledger.AsyncpgConnection, values: dict[str, Any], *, admin_id: int, effective_from: Any = None
) -> asyncpg.Record:
    await conn.execute("LOCK TABLE keno_risk_tiers IN SHARE ROW EXCLUSIVE MODE")
    version = await conn.fetchval(
        "SELECT COALESCE(MAX(version), 0) + 1 FROM keno_risk_tiers WHERE tier_number = $1", values["tier_number"]
    )
    row = await conn.fetchrow(
        """
        INSERT INTO keno_risk_tiers
            (tier_number, version, min_reserve, max_pick_count, max_top_multiplier,
             stake_options, disabled_stake_options, default_stake, max_win_per_ticket,
             max_round_exposure_pct, paytable_profile, created_by_admin_id, effective_from)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, COALESCE($13, now()))
        RETURNING *
        """,
        values["tier_number"], version, values["min_reserve"], values["max_pick_count"],
        values["max_top_multiplier"], values["stake_options"], values["disabled_stake_options"],
        values["default_stake"], values["max_win_per_ticket"], values["max_round_exposure_pct"],
        values["paytable_profile"], admin_id, effective_from,
    )
    assert row is not None  # INSERT ... RETURNING * always yields exactly one row
    return row


async def create_tier_admin(
    pool: asyncpg.Pool,
    *,
    admin_id: int,
    tier_number: int,
    min_reserve: Decimal,
    max_pick_count: int,
    max_top_multiplier: Decimal,
    stake_options: list[Decimal],
    max_win_per_ticket: Decimal,
    max_round_exposure_pct: Decimal,
    paytable_profile: str,
    reason: str,
    disabled_stake_options: list[Decimal] | None = None,
    default_stake: Decimal | None = None,
    effective_from: Any = None,
    ip_address: str | None = None,
) -> dict[str, Any]:
    if not reason.strip():
        raise InvalidKenoConfig("reason is required")
    values = _normalize_tier_values({
        "tier_number": tier_number, "min_reserve": min_reserve, "max_pick_count": max_pick_count,
        "max_top_multiplier": max_top_multiplier, "stake_options": stake_options,
        "disabled_stake_options": disabled_stake_options or [], "default_stake": default_stake,
        "max_win_per_ticket": max_win_per_ticket, "max_round_exposure_pct": max_round_exposure_pct,
        "paytable_profile": paytable_profile,
    })
    async with pool.acquire() as conn:
        async with conn.transaction():
            warnings = await validate_tier_values(conn, values)
            row = await _insert_tier_version(conn, values, admin_id=admin_id, effective_from=effective_from)
            await audit.record(
                conn, admin_id=admin_id, action="keno.tier.create", target_type="keno_risk_tier",
                target_id=str(row["id"]), before=None, after=_json_safe(row), reason=reason,
                ip_address=ip_address,
            )
    return {**dict(row), "warnings": warnings}


async def update_tier_admin(
    pool: asyncpg.Pool,
    *,
    admin_id: int,
    tier_id: int,
    changes: dict[str, Any],
    reason: str,
    adopt: bool = False,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Edit a tier -- including its stakes: add, remove, disable,
    re-enable, reorder, set the default. Writes a new version of the tier
    copied from `tier_id` with `changes` applied. With adopt=True and the
    edited tier being the one in use, the new version becomes current in
    the same transaction (effective from the next round), so an operator
    disabling a stake doesn't also have to remember a second step."""
    if not reason.strip():
        raise InvalidKenoConfig("reason is required")
    unknown = sorted(set(changes) - EDITABLE_TIER_FIELDS)
    if unknown:
        raise InvalidKenoConfig(f"these tier settings can't be changed here: {', '.join(unknown)}")
    async with pool.acquire() as conn:
        async with conn.transaction():
            base = await conn.fetchrow("SELECT * FROM keno_risk_tiers WHERE id = $1", tier_id)
            if base is None:
                raise InvalidKenoConfig(f"no such tier: {tier_id}")
            base_values = _normalize_tier_values(dict(base))
            merged = _normalize_tier_values({**base_values, **changes})
            diff = [k for k in EDITABLE_TIER_FIELDS if merged[k] != base_values[k]]
            if not diff:
                raise InvalidKenoConfig("nothing changed")
            warnings = await validate_tier_values(conn, merged)
            row = await _insert_tier_version(conn, merged, admin_id=admin_id)
            await audit.record(
                conn, admin_id=admin_id, action="keno.tier.update", target_type="keno_risk_tier",
                target_id=str(row["id"]),
                before=_json_safe({"from_tier_id": tier_id, **{k: base_values[k] for k in sorted(diff)}}),
                after=_json_safe({"tier_id": row["id"], **{k: merged[k] for k in sorted(diff)}}),
                reason=reason, ip_address=ip_address,
            )
            adopted = False
            if adopt:
                current_id = await conn.fetchval("SELECT current_tier_id FROM keno_tier_state WHERE id = 1")
                current_number = (
                    await conn.fetchval("SELECT tier_number FROM keno_risk_tiers WHERE id = $1", current_id)
                    if current_id is not None else None
                )
                if current_number == merged["tier_number"]:
                    await _set_current_tier(
                        conn, admin_id=admin_id, tier_id=row["id"], reason=reason, ip_address=ip_address
                    )
                    adopted = True
    return {**dict(row), "warnings": warnings, "adopted": adopted}


async def _set_current_tier(
    conn: ledger.AsyncpgConnection, *, admin_id: int, tier_id: int, reason: str, ip_address: str | None
) -> asyncpg.Record:
    tier = await conn.fetchrow("SELECT * FROM keno_risk_tiers WHERE id = $1", tier_id)
    if tier is None:
        raise InvalidKenoConfig(f"no such tier: {tier_id}")
    before = await conn.fetchrow("SELECT current_tier_id FROM keno_tier_state WHERE id = 1 FOR UPDATE")
    await conn.execute(
        "INSERT INTO keno_tier_state (id, current_tier_id, candidate_tier_id, candidate_since) "
        "VALUES (1, $1, NULL, NULL) "
        "ON CONFLICT (id) DO UPDATE SET current_tier_id = $1, candidate_tier_id = NULL, "
        "candidate_since = NULL, updated_at = now()",
        tier_id,
    )
    reserve_account = await ledger.get_or_create_account(conn, None, "keno_reserve")
    reserve_balance = await ledger.balance(conn, reserve_account.id)
    await conn.execute(
        "INSERT INTO keno_tier_changes "
        "(from_tier_id, to_tier_id, trigger, reason, reserve_balance_at_change, admin_id) "
        "VALUES ($1, $2, 'admin_override', $3, $4, $5)",
        before["current_tier_id"] if before else None,
        tier_id,
        reason,
        reserve_balance,
        admin_id,
    )
    metrics.keno_tier_changes_total.labels(trigger="admin_override").inc()
    await audit.record(
        conn, admin_id=admin_id, action="keno.tier.set_current", target_type="keno_risk_tier",
        target_id=str(tier_id),
        before={"current_tier_id": before["current_tier_id"] if before else None},
        after={"current_tier_id": tier_id}, reason=reason, ip_address=ip_address,
    )
    return tier


async def set_current_tier_admin(
    pool: asyncpg.Pool, *, admin_id: int, tier_id: int, reason: str, ip_address: str | None = None
) -> dict[str, Any]:
    """Manual override of keno_tier_state (Part 7.2's promotion/demotion
    target) -- always available to a superadmin regardless of what the
    automated reserve-threshold evaluation (packages/core/
    keno_tier_automation.py, wired into KenoRoundEngine._create_round())
    would otherwise choose, the same "admin can always directly act"
    precedent services/admin/queries.py's void_round_admin/stop_room_admin
    already set for Bingo -- the next automated evaluation simply resumes
    from wherever this override left current_tier_id, same as it would
    after any other change. Never affects an in-flight round (Part 7.2:
    "never mid-round") -- rounds pin their own tier_id at creation and
    never re-read this table again. Recorded in keno_tier_changes
    (trigger='admin_override') alongside the existing admin_audit_log
    entry -- the former is the one place with a full tier history
    regardless of actor, the latter is admin_audit_log's own "which admin
    did this" record specifically."""
    if not reason.strip():
        raise InvalidKenoConfig("reason is required")
    async with pool.acquire() as conn:
        async with conn.transaction():
            tier = await _set_current_tier(conn, admin_id=admin_id, tier_id=tier_id, reason=reason, ip_address=ip_address)
    return dict(tier)


async def dashboard_summary_admin(pool: asyncpg.Pool) -> dict[str, Any]:
    """Part 15's dashboard: current round, reserve vs. player liability
    shown separately (the operator's own explicit warning: conflating
    them is how operators misjudge solvency), current tier, jackpot
    pool."""
    async with pool.acquire() as conn:
        round_row = await conn.fetchrow(
            "SELECT id, status, total_stake, total_payout, projected_exposure, ticket_count "
            "FROM keno_rounds WHERE status NOT IN ('completed','failed','voided') ORDER BY id DESC LIMIT 1"
        )
        reserve_account = await ledger.get_or_create_account(conn, None, "keno_reserve")
        jackpot_account = await ledger.get_or_create_account(conn, None, "keno_jackpot_pool")
        reserve_balance = await ledger.balance(conn, reserve_account.id)
        jackpot_balance = await ledger.balance(conn, jackpot_account.id)
        # Player liability: sum of every user's cash+bonus-locked balance
        # -- money the operator owes, structurally separate from the
        # reserve (money the operator has to pay claims from). Never the
        # same number, and conflating them is exactly the operator's own
        # named risk in Part 7.1.
        liability = await conn.fetchval(
            "SELECT COALESCE(SUM(balance), 0) FROM account_balances WHERE kind IN ('user_cash', 'user_bonus')"
        )
        current_tier = await conn.fetchrow(
            "SELECT tiers.tier_number, tiers.id FROM keno_tier_state "
            "JOIN keno_risk_tiers tiers ON tiers.id = keno_tier_state.current_tier_id WHERE keno_tier_state.id = 1"
        )
        config = await keno_config.load_active_config(conn)

    return {
        "keno_enabled": config["keno_enabled"],
        "current_round": dict(round_row) if round_row else None,
        "reserve_balance": str(reserve_balance),
        "player_liability": str(liability),
        "jackpot_pool": str(jackpot_balance),
        "current_tier_number": current_tier["tier_number"] if current_tier else None,
    }


# --- reserve deposit / withdrawal (Part 7.1) --------------------------------
# "keno_reserve -- funded by explicit operator deposit... reduced by...
# explicit withdrawals." Both kinds already existed in ledger_transactions'
# own allowed-kinds check (keno_reserve_deposit/keno_reserve_withdrawal,
# migrations/versions/a3f7c2e91b04_keno_core_schema.py) but nothing ever
# posted either outside a test -- the audit's own #3 finding. house_float
# is the counterparty both ways, the same real, existing account every
# other operator-funded pool (payments, simulated players) already uses --
# not a new concept.


async def deposit_to_reserve_admin(
    pool: asyncpg.Pool, *, admin_id: int, amount: Decimal, reason: str, ip_address: str | None = None
) -> dict[str, Any]:
    if not reason.strip():
        raise InvalidKenoConfig("reason is required")
    if amount <= 0:
        raise InvalidKenoConfig("amount must be positive")
    async with pool.acquire() as conn:
        async with conn.transaction():
            reserve = await ledger.get_or_create_account(conn, None, "keno_reserve")
            house_float = await ledger.get_or_create_account(conn, None, "house_float")
            before = await ledger.balance(conn, reserve.id)
            await ledger.post(
                conn, "keno_reserve_deposit",
                [ledger.Entry(house_float.id, -amount), ledger.Entry(reserve.id, amount)],
                idempotency_key=f"admin-reserve-deposit-{uuid.uuid4()}", created_by=f"admin:{admin_id}",
            )
            after = before + amount
            await audit.record(
                conn, admin_id=admin_id, action="keno.reserve.deposit", target_type="keno_reserve",
                target_id="keno_reserve", before={"balance": str(before)}, after={"balance": str(after)},
                reason=reason, ip_address=ip_address,
            )
    return {"balance": str(after)}


async def withdraw_from_reserve_admin(
    pool: asyncpg.Pool, *, admin_id: int, amount: Decimal, reason: str, ip_address: str | None = None
) -> dict[str, Any]:
    """Blocks (and audits the blocked attempt itself, not just successful
    withdrawals -- Part 7.1's own "Attempts are blocked and audited")
    anything that would leave the reserve below the active config's own
    reserve_withdrawal_floor. Never partial -- either the full requested
    amount clears the floor or nothing moves."""
    if not reason.strip():
        raise InvalidKenoConfig("reason is required")
    if amount <= 0:
        raise InvalidKenoConfig("amount must be positive")

    async def _locked_floor_check(conn: ledger.AsyncpgConnection) -> tuple[Decimal, Decimal, Decimal]:
        """Row-locks the reserve account's own balance for the rest of
        the caller's transaction (FOR UPDATE) so nothing else can move it
        between this check and whatever the caller does next -- without
        it, a concurrent payout/withdrawal landing between pass 1's check
        below and pass 2's actual debit could let a withdrawal through
        that the floor should have blocked. Returns (before,
        resulting_balance, floor)."""
        reserve = await ledger.get_or_create_account(conn, None, "keno_reserve")
        await conn.execute("SELECT balance FROM account_balances WHERE account_id = $1 FOR UPDATE", reserve.id)
        before = await ledger.balance(conn, reserve.id)
        config = await keno_config.load_active_config(conn)
        return before, before - amount, Decimal(config["reserve_withdrawal_floor"])

    # Pass 1: the floor check, in its own transaction that commits either
    # way -- raising ReserveWithdrawalBelowFloor from *inside* the same
    # transaction as the audit.record() call would roll the audit row
    # back right along with it, silently defeating Part 7.1's own
    # "Attempts are blocked and audited" (a real bug this function's own
    # tests caught: the exception WAS raised correctly, the balance WAS
    # correctly left unchanged, but the audit row never existed).
    async with pool.acquire() as conn:
        async with conn.transaction():
            before, resulting_balance, floor = await _locked_floor_check(conn)
            if resulting_balance < floor:
                await audit.record(
                    conn, admin_id=admin_id, action="keno.reserve.withdraw_rejected",
                    target_type="keno_reserve", target_id="keno_reserve",
                    before={"balance": str(before)},
                    after={"attempted_balance": str(resulting_balance), "floor": str(floor)},
                    reason=reason, ip_address=ip_address,
                )
    if resulting_balance < floor:
        raise ReserveWithdrawalBelowFloor(resulting_balance, floor)

    # Pass 2: the actual withdrawal, re-validating the floor with a fresh
    # row-locked read rather than trusting pass 1's now-stale one --
    # genuinely rare for an admin-driven action, but a real-money guard
    # must not skip re-checking just because the gap is usually empty.
    async with pool.acquire() as conn:
        async with conn.transaction():
            before, resulting_balance, floor = await _locked_floor_check(conn)
            if resulting_balance < floor:
                await audit.record(
                    conn, admin_id=admin_id, action="keno.reserve.withdraw_rejected",
                    target_type="keno_reserve", target_id="keno_reserve",
                    before={"balance": str(before)},
                    after={"attempted_balance": str(resulting_balance), "floor": str(floor)},
                    reason=f"{reason} (blocked on re-check: balance changed since the initial check)",
                    ip_address=ip_address,
                )
    if resulting_balance < floor:
        raise ReserveWithdrawalBelowFloor(resulting_balance, floor)

    async with pool.acquire() as conn:
        async with conn.transaction():
            reserve = await ledger.get_or_create_account(conn, None, "keno_reserve")
            house_float = await ledger.get_or_create_account(conn, None, "house_float")
            await ledger.post(
                conn, "keno_reserve_withdrawal",
                [ledger.Entry(reserve.id, -amount), ledger.Entry(house_float.id, amount)],
                idempotency_key=f"admin-reserve-withdrawal-{uuid.uuid4()}", created_by=f"admin:{admin_id}",
            )
            await audit.record(
                conn, admin_id=admin_id, action="keno.reserve.withdraw", target_type="keno_reserve",
                target_id="keno_reserve", before={"balance": str(before)},
                after={"balance": str(resulting_balance)}, reason=reason, ip_address=ip_address,
            )
    return {"balance": str(resulting_balance)}


# ---------------------------------------------------------------------------
# Staged-launch beta allowlist (2026-09-23, a CTO review's own required
# gate before any Stage 1). Current membership only -- who's allowed to
# play right now, not a versioned history of who was ever allowed; every
# add/remove is itself audited in admin_audit_log below, which is
# already the platform's record of "who did what, when."
# ---------------------------------------------------------------------------


async def list_beta_allowlist_admin(pool: asyncpg.Pool) -> list[dict[str, Any]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT user_id, added_by_admin_id, reason, created_at FROM keno_beta_allowlist ORDER BY created_at DESC"
        )
    return [_json_safe(row) for row in rows]


async def add_to_beta_allowlist_admin(
    pool: asyncpg.Pool, *, admin_id: int, user_id: int, reason: str, ip_address: str | None = None
) -> dict[str, Any]:
    if not reason.strip():
        raise InvalidKenoConfig("reason is required")
    async with pool.acquire() as conn:
        async with conn.transaction():
            user = await conn.fetchrow("SELECT id FROM users WHERE id = $1", user_id)
            if user is None:
                raise InvalidKenoConfig(f"no such user: {user_id}")
            row = await conn.fetchrow(
                "INSERT INTO keno_beta_allowlist (user_id, added_by_admin_id, reason) VALUES ($1, $2, $3) "
                "ON CONFLICT (user_id) DO UPDATE SET added_by_admin_id = $2, reason = $3, created_at = now() "
                "RETURNING user_id, added_by_admin_id, reason, created_at",
                user_id, admin_id, reason,
            )
            assert row is not None
            await audit.record(
                conn, admin_id=admin_id, action="keno.beta_allowlist.add", target_type="keno_beta_allowlist",
                target_id=str(user_id), before=None, after=_json_safe(row), reason=reason, ip_address=ip_address,
            )
    return _json_safe(row)


async def remove_from_beta_allowlist_admin(
    pool: asyncpg.Pool, *, admin_id: int, user_id: int, reason: str, ip_address: str | None = None
) -> dict[str, Any]:
    if not reason.strip():
        raise InvalidKenoConfig("reason is required")
    async with pool.acquire() as conn:
        async with conn.transaction():
            before = await conn.fetchrow(
                "SELECT user_id, added_by_admin_id, reason, created_at FROM keno_beta_allowlist WHERE user_id = $1",
                user_id,
            )
            result = await conn.execute("DELETE FROM keno_beta_allowlist WHERE user_id = $1", user_id)
            removed = result == "DELETE 1"
            await audit.record(
                conn, admin_id=admin_id, action="keno.beta_allowlist.remove", target_type="keno_beta_allowlist",
                target_id=str(user_id), before=_json_safe(before) if before else None, after=None,
                reason=reason, ip_address=ip_address,
            )
    return {"removed": removed}


# ---------------------------------------------------------------------------
# Read-only views for the admin Keno screens (rounds browser, reports).
# ---------------------------------------------------------------------------


async def list_rounds_admin(
    pool: asyncpg.Pool, *, limit: int = 50, before_id: int | None = None, status: str | None = None
) -> list[dict[str, Any]]:
    limit = min(max(limit, 1), 200)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, seq, status, tier_id, ticket_count, total_stake, total_payout, projected_exposure,
                   jackpot_hit, scheduled_at, betting_closed_at, completed_at, failure_reason
            FROM keno_rounds
            WHERE ($1::bigint IS NULL OR id < $1) AND ($2::text IS NULL OR status = $2)
            ORDER BY id DESC LIMIT $3
            """,
            before_id,
            status,
            limit,
        )
    return [_json_safe(row) for row in rows]


async def round_detail_admin(pool: asyncpg.Pool, round_id: int) -> dict[str, Any] | None:
    """Everything an operator investigating one round needs in one read:
    the round itself (draw included once terminal -- admins are trusted
    staff, but the same terminal-only rule as the player API keeps an
    admin screen from ever leaking a live draw), its tickets, and its
    audited state transitions."""
    async with pool.acquire() as conn:
        round_row = await conn.fetchrow("SELECT * FROM keno_rounds WHERE id = $1", round_id)
        if round_row is None:
            return None
        tickets = await conn.fetch(
            """
            SELECT t.id, t.user_id, t.pick_count, t.stake, t.status, t.matches, t.payout, t.jackpot_payout,
                   t.created_at, array_agg(s.number ORDER BY s.number) AS picks
            FROM keno_tickets t LEFT JOIN keno_ticket_selections s ON s.ticket_id = t.id
            WHERE t.round_id = $1 GROUP BY t.id ORDER BY t.id
            """,
            round_id,
        )
        events = await conn.fetch(
            "SELECT from_status, to_status, worker_id, reason, created_at FROM keno_round_events "
            "WHERE round_id = $1 ORDER BY created_at",
            round_id,
        )
    terminal = round_row["status"] in ("completed", "failed", "voided")
    detail = _json_safe(round_row)
    if not terminal:
        detail["server_seed"] = None
        detail["drawn_numbers"] = None
    return {
        "round": detail,
        "tickets": [_json_safe(t) for t in tickets],
        "events": [_json_safe(e) for e in events],
    }


async def daily_report_admin(pool: asyncpg.Pool, *, days: int = 14) -> list[dict[str, Any]]:
    """Per UTC day: handle, payouts, GGR, hold, ticket and player counts --
    settled tickets only, simulated players excluded, the same rules as
    packages/core/keno_business_metrics.py so the two never disagree."""
    days = min(max(days, 1), 90)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT date_trunc('day', t.created_at AT TIME ZONE 'UTC') AS day,
                   sum(t.stake) AS handle,
                   sum(COALESCE(t.payout, 0) + COALESCE(t.jackpot_payout, 0)) AS paid,
                   count(*) AS tickets,
                   count(DISTINCT t.user_id) AS players,
                   count(DISTINCT t.round_id) AS rounds
            FROM keno_tickets t JOIN users u ON u.id = t.user_id
            WHERE t.status IN ('won', 'lost') AND NOT u.is_simulated
              AND t.created_at >= date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'
                                  - make_interval(days => $1 - 1)
              AND t.created_at < now()
            GROUP BY 1 ORDER BY 1 DESC
            """,
            days,
        )
    report = []
    for row in rows:
        handle = Decimal(row["handle"])
        ggr = handle - Decimal(row["paid"])
        report.append(
            {
                "day": row["day"].date().isoformat(),
                "handle": str(handle),
                "paid": str(Decimal(row["paid"])),
                "ggr": str(ggr),
                "hold_pct": str((ggr / handle).quantize(Decimal("0.0001"))) if handle else None,
                "tickets": row["tickets"],
                "players": row["players"],
                "rounds": row["rounds"],
            }
        )
    return report


async def business_metrics_admin(pool: asyncpg.Pool) -> dict[str, Any]:
    """A live snapshot of the Part 8 KPIs, computed on request with the
    exact code keno-worker uses for its gauges. NaN retention (an empty
    cohort) is returned as null -- JSON has no NaN."""
    m = await keno_business_metrics.compute(pool)

    def _num(value: float) -> float | None:
        return None if math.isnan(value) else value

    return {
        "dau": m.dau,
        "sessions": m.sessions,
        "sessions_per_user": m.sessions_per_user,
        "rounds_per_session": m.rounds_per_session,
        "tickets_per_round": m.tickets_per_round,
        "avg_stake": str(m.avg_stake),
        "hold_pct": m.hold_pct,
        "ggr": str(m.ggr),
        "arpdau": str(m.arpdau),
        "d1_retention": _num(m.d1_retention),
        "d7_retention": _num(m.d7_retention),
        "d30_retention": _num(m.d30_retention),
        "player_ltv": str(m.player_ltv),
        "deposit_conversion_rate": _num(m.deposit_conversion_rate),
    }
