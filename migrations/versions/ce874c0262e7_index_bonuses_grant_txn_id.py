"""index bonuses grant txn id

Revision ID: ce874c0262e7
Revises: b5d9e3a1c7f2
Create Date: 2026-10-05 06:40:00.000000

packages/core/bonuses.py's grant_bonus() looks a bonus up by its
grant_txn_id on every grant: welcome bonuses, referral rewards and admin
grants. No index led with grant_txn_id, so each lookup read the whole
bonuses table, which gains a row per grant. The second of those lookups
runs after ledger.post() has row-locked the shared promo_expense balance,
so the scan also lengthened how long every grant held that lock, queueing
all other grants behind it. services/admin/bonus_queries.py's manual
grant joins on the same column.

Not UNIQUE, though each grant transaction should own exactly one row: a
race fixed on 2026-10-01 could write a second row for the same grant, and
rows from before that fix may still exist in production. A unique index
would fail to build there.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'ce874c0262e7'
down_revision: Union[str, None] = 'b5d9e3a1c7f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE INDEX ix_bonuses_grant_txn_id ON bonuses (grant_txn_id)")


def downgrade() -> None:
    op.execute("DROP INDEX ix_bonuses_grant_txn_id")
