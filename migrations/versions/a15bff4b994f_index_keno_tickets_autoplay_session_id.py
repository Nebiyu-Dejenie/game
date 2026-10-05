"""index keno tickets autoplay session id

Revision ID: a15bff4b994f
Revises: ce874c0262e7
Create Date: 2026-10-05 07:00:00.000000

packages/core/keno_tickets.py's _check_autoplay_loss_limit() sums an
autoplay session's tickets (WHERE autoplay_session_id = $1) for every
autoplay placement with a stop-loss: once per active session per round,
every 45 seconds, while that player's advisory lock and rows are held.
No index led with autoplay_session_id, so each check read every Keno
ticket ever placed, and the work per round grew with sessions times
all-time tickets.

Partial, on the tickets that belong to a session: a manual ticket's
autoplay_session_id is NULL and is never looked up this way, so leaving
those out keeps the index small. The query's equality on the column
implies NOT NULL, so the planner can use it.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a15bff4b994f'
down_revision: Union[str, None] = 'ce874c0262e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_keno_tickets_autoplay_session_id ON keno_tickets (autoplay_session_id) "
        "WHERE autoplay_session_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX ix_keno_tickets_autoplay_session_id")
