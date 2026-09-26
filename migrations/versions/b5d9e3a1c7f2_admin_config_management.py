"""admin configuration management: Keno stake management, autoplay cap,
and database-backed platform settings

Three gaps where business configuration could only be changed by a
developer (SQL or a redeploy), not from the admin console:

- keno_risk_tiers.default_stake / disabled_stake_options: a tier's
  stake_options stays the one enforced "stakes a ticket may use" list
  (packages/core/keno_tickets.py checks it inside the placement
  transaction), in display order. default_stake is the chip the Mini App
  preselects; disabled_stake_options holds stakes an operator switched
  off but wants to keep on the list for re-enabling later -- they are
  never accepted for a ticket, because they are not in stake_options.
  CHECKs make an impossible combination unrepresentable rather than
  merely rejected by the API: every stake positive, the default one of
  the enabled stakes, and no stake both enabled and disabled.

- keno_configs.max_autoplay_rounds: the per-session round cap was a
  module constant (packages/core/keno_autoplay.py MAX_ROUNDS_TOTAL = 100).
  That constant stays as the hard ceiling; the operator can now lower
  it. Versioned with every other keno_configs column.

- platform_settings: operator overrides for business limits that lived
  only in environment variables (minimum deposit, withdrawal limits,
  auto-approve and KYC thresholds, withdrawals per day) plus the
  responsible-gaming timings. One row per overridden key; a key with no
  row falls back to the environment default, so a fresh deployment
  behaves exactly as before. History lives in the immutable
  admin_audit_log like every other admin change.

Revision ID: b5d9e3a1c7f2
Revises: a7c3e9f2d146
Create Date: 2026-09-27

"""
from typing import Sequence, Union

from alembic import op

revision: str = "b5d9e3a1c7f2"
down_revision: Union[str, None] = "a7c3e9f2d146"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE keno_risk_tiers
          ADD COLUMN default_stake numeric(18,2),
          ADD COLUMN disabled_stake_options numeric(18,2)[] NOT NULL DEFAULT '{}',
          ADD CONSTRAINT chk_keno_risk_tiers_stakes_positive
            CHECK (cardinality(stake_options) >= 1 AND 0 < ALL (stake_options)),
          ADD CONSTRAINT chk_keno_risk_tiers_disabled_stakes_positive
            CHECK (cardinality(disabled_stake_options) = 0 OR 0 < ALL (disabled_stake_options)),
          ADD CONSTRAINT chk_keno_risk_tiers_default_stake_enabled
            CHECK (default_stake IS NULL OR default_stake = ANY (stake_options)),
          ADD CONSTRAINT chk_keno_risk_tiers_stakes_disjoint
            CHECK (NOT (stake_options && disabled_stake_options));
        """
    )
    op.execute(
        """
        ALTER TABLE keno_configs
          ADD COLUMN max_autoplay_rounds int NOT NULL DEFAULT 100
            CHECK (max_autoplay_rounds BETWEEN 1 AND 100);
        """
    )
    op.execute(
        """
        CREATE TABLE platform_settings (
          key                  text PRIMARY KEY,
          value                jsonb NOT NULL,
          updated_by_admin_id  bigint NOT NULL REFERENCES admin_users(id),
          updated_at           timestamptz NOT NULL DEFAULT now()
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE platform_settings")
    op.execute("ALTER TABLE keno_configs DROP COLUMN max_autoplay_rounds")
    op.execute(
        """
        ALTER TABLE keno_risk_tiers
          DROP CONSTRAINT chk_keno_risk_tiers_stakes_disjoint,
          DROP CONSTRAINT chk_keno_risk_tiers_default_stake_enabled,
          DROP CONSTRAINT chk_keno_risk_tiers_disabled_stakes_positive,
          DROP CONSTRAINT chk_keno_risk_tiers_stakes_positive,
          DROP COLUMN disabled_stake_options,
          DROP COLUMN default_stake;
        """
    )
