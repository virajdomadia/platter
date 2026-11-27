"""v2 L4: ratings (one per delivered order). The public restaurant score counts real customers'
ratings only (`restaurants.rating_sum / rating_count`): a demo visitor's rating is kept for them
but never moves a public number.

Revision ID: 0006_ratings
Revises: 0005_menu_sandbox
"""

from alembic import op

revision = "0006_ratings"
down_revision = "0005_menu_sandbox"
branch_labels = None
depends_on = None

UPGRADE = """
create table ratings (
  id uuid primary key,
  order_id uuid not null unique references orders(id) on delete cascade,
  restaurant_stars smallint not null check (restaurant_stars between 1 and 5),
  rider_stars smallint check (rider_stars between 1 and 5),
  line text,
  is_demo boolean not null,
  created_at timestamptz not null
);
alter table restaurants add column rating_sum integer not null default 0;
alter table restaurants add column rating_count integer not null default 0
"""

DOWNGRADE = """
alter table restaurants drop column if exists rating_count;
alter table restaurants drop column if exists rating_sum;
drop table if exists ratings
"""


def _run(sql: str) -> None:
    for statement in sql.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run(UPGRADE)


def downgrade() -> None:
    _run(DOWNGRADE)
