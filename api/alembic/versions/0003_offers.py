"""v2 L1: rider offers (06 §A v2). An offer gives one rider 30 s to accept an order; every state
change is one conditional `update … where state = 'sent'`, so exactly one outcome wins.

Revision ID: 0003_offers
Revises: 0002_demo_partition
"""

from alembic import op

revision = "0003_offers"
down_revision = "0002_demo_partition"
branch_labels = None
depends_on = None

UPGRADE = """
create table offers (
  id uuid primary key,
  order_id uuid not null references orders(id) on delete cascade,
  rider_id uuid not null references riders(id) on delete cascade,
  state text not null default 'sent' check (state in ('sent','accepted','declined','expired')),
  expires_at timestamptz not null,
  created_at timestamptz not null,
  closed_at timestamptz,
  unique (order_id, rider_id)
);
create index offers_rider_state_idx on offers (rider_id, state);
create index offers_sent_idx on offers (expires_at) where state = 'sent';
create unique index offers_one_open_per_rider on offers (rider_id) where state = 'sent';
create unique index offers_one_open_per_order on offers (order_id) where state = 'sent'
"""

DOWNGRADE = """
drop table if exists offers
"""


def _run(sql: str) -> None:
    for statement in sql.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run(UPGRADE)


def downgrade() -> None:
    _run(DOWNGRADE)
