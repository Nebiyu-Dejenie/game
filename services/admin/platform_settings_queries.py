"""Admin reads and writes of platform settings (packages/core/
platform_settings.py): the effective value of each setting with its
default, bounds and who last changed it; atomic multi-setting updates
validated as a whole; reset-to-default; and the configuration change
history drawn from the immutable admin_audit_log.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import asyncpg

from packages.core import platform_settings
from packages.core.config import get_settings
from services.admin import audit

InvalidSetting = platform_settings.InvalidSetting


def _display(value: Decimal | int) -> str | int:
    return str(value) if isinstance(value, Decimal) else value


async def list_settings_admin(pool: asyncpg.Pool) -> dict[str, Any]:
    settings = get_settings()
    async with pool.acquire() as conn:
        effective = await platform_settings.load_values(conn, settings)
        rows = {
            row["key"]: row
            for row in await conn.fetch(
                """
                SELECT s.key, s.updated_at, a.username AS updated_by
                FROM platform_settings s JOIN admin_users a ON a.id = s.updated_by_admin_id
                """
            )
        }
    categories: dict[str, list[dict[str, Any]]] = {}
    for key, definition in platform_settings.REGISTRY.items():
        row = rows.get(key)
        default = definition.default(settings)
        categories.setdefault(definition.category, []).append({
            "key": key,
            "label": definition.label,
            "description": definition.description,
            "kind": definition.kind,
            "unit": definition.unit,
            "minimum": _display(definition.minimum if definition.kind == "money" else int(definition.minimum)),
            "maximum": _display(definition.maximum if definition.kind == "money" else int(definition.maximum)),
            "value": _display(effective[key]),
            "default": _display(default),
            "overridden": row is not None,
            "updated_at": row["updated_at"].isoformat() if row else None,
            "updated_by": row["updated_by"] if row else None,
        })
    return {
        "categories": [
            {"key": key, "label": platform_settings.CATEGORY_LABELS.get(key, key), "settings": items}
            for key, items in categories.items()
        ]
    }


async def update_settings_admin(
    pool: asyncpg.Pool,
    *,
    admin_id: int,
    changes: dict[str, Any],
    reason: str,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Applies several settings at once, all or nothing. The merged set is
    validated as a whole, so two edits that are each fine alone but
    impossible together (a daily cap under the minimum deposit) are
    refused. One audit entry records every changed key, before and after."""
    if not reason.strip():
        raise InvalidSetting("reason is required")
    if not changes:
        raise InvalidSetting("nothing to change")
    coerced = {key: platform_settings.coerce(key, value) for key, value in changes.items()}
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Serializes concurrent editors: the cross-setting check below
            # must see the other editor's committed values, not a stale read.
            await conn.execute("LOCK TABLE platform_settings IN SHARE ROW EXCLUSIVE MODE")
            current = await platform_settings.load_values(conn)
            merged = {**current, **coerced}
            changed = sorted(k for k in coerced if coerced[k] != current[k])
            if not changed:
                raise InvalidSetting("nothing changed")
            platform_settings.validate(merged)
            for key in changed:
                await conn.execute(
                    """
                    INSERT INTO platform_settings (key, value, updated_by_admin_id, updated_at)
                    VALUES ($1, $2::jsonb, $3, now())
                    ON CONFLICT (key) DO UPDATE
                      SET value = EXCLUDED.value, updated_by_admin_id = EXCLUDED.updated_by_admin_id,
                          updated_at = now()
                    """,
                    key, platform_settings.to_json(merged[key]), admin_id,
                )
            await audit.record(
                conn, admin_id=admin_id, action="platform_settings.update", target_type="platform_setting",
                target_id=",".join(changed),
                before={k: _display(current[k]) for k in changed},
                after={k: _display(merged[k]) for k in changed},
                reason=reason, ip_address=ip_address,
            )
    return await list_settings_admin(pool)


async def reset_setting_admin(
    pool: asyncpg.Pool, *, admin_id: int, key: str, reason: str, ip_address: str | None = None
) -> dict[str, Any]:
    """Drops the override so the setting goes back to its default. The
    default must still pass the cross-setting rules with everything else
    as it is now."""
    if key not in platform_settings.REGISTRY:
        raise InvalidSetting(f"unknown setting: {key}")
    if not reason.strip():
        raise InvalidSetting("reason is required")
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("LOCK TABLE platform_settings IN SHARE ROW EXCLUSIVE MODE")
            current = await platform_settings.load_values(conn)
            default = platform_settings.REGISTRY[key].default(get_settings())
            exists = await conn.fetchval("SELECT 1 FROM platform_settings WHERE key = $1", key)
            if not exists:
                raise InvalidSetting("this setting is already at its default")
            platform_settings.validate({**current, key: default})
            await conn.execute("DELETE FROM platform_settings WHERE key = $1", key)
            await audit.record(
                conn, admin_id=admin_id, action="platform_settings.reset", target_type="platform_setting",
                target_id=key, before={key: _display(current[key])}, after={key: _display(default)},
                reason=reason, ip_address=ip_address,
            )
    return await list_settings_admin(pool)


# What counts as a configuration change for the history view: every
# target_type an admin config write records, and nothing that concerns an
# individual player or payment (those stay in the superadmin audit log).
CONFIG_TARGET_TYPES: dict[str, tuple[str, ...]] = {
    "platform": ("platform_setting",),
    "keno": ("keno_config", "keno_risk_tier", "keno_paytable"),
    "bingo": ("room", "simulated_players_settings"),
    "payments": ("payment_provider_availability", "manual_payment_destination"),
    "promotions": ("bonus_rule",),
    "content": ("platform_announcement", "bot_command"),
}


async def config_history_admin(
    pool: asyncpg.Pool, *, scope: str | None = None, target_id: str | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    if scope is not None and scope not in CONFIG_TARGET_TYPES:
        raise InvalidSetting(f"unknown history scope: {scope}")
    types = (
        list(CONFIG_TARGET_TYPES[scope]) if scope is not None
        else [t for group in CONFIG_TARGET_TYPES.values() for t in group]
    )
    limit = max(1, min(limit, 500))
    rows = await pool.fetch(
        """
        SELECT l.id, a.username AS admin_username, l.action, l.target_type, l.target_id,
               l.before, l.after, l.reason, l.created_at
        FROM admin_audit_log l JOIN admin_users a ON a.id = l.admin_id
        WHERE l.target_type = ANY($1::text[])
          AND ($2::text IS NULL OR l.target_id = $2 OR l.target_id LIKE '%' || $2 || '%')
        ORDER BY l.id DESC
        LIMIT $3
        """,
        types, target_id, limit,
    )
    return [
        {
            **dict(row),
            "before": json.loads(row["before"]) if row["before"] else None,
            "after": json.loads(row["after"]) if row["after"] else None,
            "created_at": row["created_at"].isoformat(),
        }
        for row in rows
    ]
