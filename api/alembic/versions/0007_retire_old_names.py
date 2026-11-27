"""Retire the three pre-#8 restaurants. PR #8 renamed kitchens that shared names with real brands
by changing their slugs, and the seed upserts by slug, so any database seeded before #8 still
lists the old rows (with the real brands' names) beside the renamed ones.

Demo history at the old slugs is deleted (its children cascade); an old restaurant with no orders
left is deleted with its menu and its (password-less, demo) owner. One that a real customer's
order still points to is never deleted: it takes its fictional name and leaves every list.
Idempotent; a database seeded after #8 has none of these rows and nothing happens.

Revision ID: 0007_retire_old_names
Revises: 0006_ratings
"""

from alembic import op

revision = "0007_retire_old_names"
down_revision = "0006_ratings"
branch_labels = None
depends_on = None

UPGRADE = """
delete from orders o using restaurants r
  where r.id = o.restaurant_id and o.is_demo
    and r.slug in ('koramangala-social', 'pizza-bakery', 'chai-point');
delete from restaurants r
  where r.slug in ('koramangala-social', 'pizza-bakery', 'chai-point')
    and not exists (select 1 from orders o where o.restaurant_id = r.id);
update restaurants set name = 'Bandstand Kitchen', is_sandbox = true
  where slug = 'koramangala-social';
update restaurants set name = 'Forno 17', is_sandbox = true where slug = 'pizza-bakery';
update restaurants set name = 'Tapri Tales', is_sandbox = true where slug = 'chai-point';
delete from users u
  where u.email in ('owner.koramangala-social@platter.demo', 'owner.pizza-bakery@platter.demo',
                    'owner.chai-point@platter.demo')
    and u.password_hash is null and u.is_demo
    and not exists (select 1 from restaurants r where r.owner_user_id = u.id)
"""


def _run(sql: str) -> None:
    for statement in sql.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run(UPGRADE)


def downgrade() -> None:
    pass  # the old rows were demo data under real brands' names; nothing to put back
