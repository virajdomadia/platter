"""Review 2026-11-27: demo data is a partition, not just an account (`users.is_demo`,
`orders.is_demo`), and a fixed-window `rate_limits` table shared by every API instance.

Revision ID: 0002_demo_partition
Revises: 0001_v1
"""

from alembic import op

revision = "0002_demo_partition"
down_revision = "0001_v1"
branch_labels = None
depends_on = None

UPGRADE = """
alter table users add column is_demo boolean not null default false;
alter table orders add column is_demo boolean not null default false;
update users set is_demo = true
  where password_hash is null and (email like '%@platter.demo' or email like '%.platter.demo');
update orders o set is_demo = true from users u where u.id = o.user_id and u.is_demo;
create index orders_demo_status_idx on orders (is_demo, status);
create table rate_limits (
  key text primary key,
  window_start timestamptz not null,
  hits int not null
)
"""

DOWNGRADE = """
drop table if exists rate_limits;
drop index if exists orders_demo_status_idx;
alter table orders drop column if exists is_demo;
alter table users drop column if exists is_demo
"""


def _run(sql: str) -> None:
    for statement in sql.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run(UPGRADE)


def downgrade() -> None:
    _run(DOWNGRADE)
