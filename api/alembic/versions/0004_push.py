"""v2 L2: Web Push subscriptions, each tied to the browser session that made it (signing out or
the session expiring drops it).

Revision ID: 0004_push
Revises: 0003_offers
"""

from alembic import op

revision = "0004_push"
down_revision = "0003_offers"
branch_labels = None
depends_on = None

UPGRADE = """
create table push_subscriptions (
  id uuid primary key,
  user_id uuid not null references users(id) on delete cascade,
  session_id text not null references sessions(id) on delete cascade,
  endpoint text not null unique,
  p256dh text not null,
  auth text not null,
  created_at timestamptz not null
);
create index push_subscriptions_user_idx on push_subscriptions (user_id)
"""

DOWNGRADE = """
drop table if exists push_subscriptions
"""


def _run(sql: str) -> None:
    for statement in sql.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run(UPGRADE)


def downgrade() -> None:
    _run(DOWNGRADE)
