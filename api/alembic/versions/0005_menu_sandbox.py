"""v2 L3: the demo kitchen's menu editor works on a private sandbox copy (`is_sandbox`), never on
the public menu. A sandbox is not listed, has no public page and takes no orders.

Revision ID: 0005_menu_sandbox
Revises: 0004_push
"""

from alembic import op

revision = "0005_menu_sandbox"
down_revision = "0004_push"
branch_labels = None
depends_on = None

UPGRADE = """
alter table restaurants add column is_sandbox boolean not null default false
"""

DOWNGRADE = """
delete from restaurants where is_sandbox;
alter table restaurants drop column if exists is_sandbox
"""


def _run(sql: str) -> None:
    for statement in sql.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run(UPGRADE)


def downgrade() -> None:
    _run(DOWNGRADE)
