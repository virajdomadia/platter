"""v2 L5: refunds, the ledger and payouts (06 §A v2).

* `refunds`: at most one per order (unique), written before Razorpay is ever called, so a retry
  or a race can't refund twice; `status` pending → sending → processed | failed.
* `ledger_entries`: signed paise per account ('platform' | 'restaurant:{id}' | 'rider:{id}').
  A delivered order writes sale / fee / delivery / delivery_margin, once (unique per order+kind);
  its entries always sum to the order's total, less anything refunded.
* `payouts`: an admin marks money paid; the matching negative ledger entry is written in the same
  transaction, never above the balance. `is_demo` keeps the public demo's money apart.

Revision ID: 0008_money
Revises: 0007_retire_old_names
"""

from alembic import op

revision = "0008_money"
down_revision = "0007_retire_old_names"
branch_labels = None
depends_on = None

UPGRADE = """
create table refunds (
  id uuid primary key,
  order_id uuid not null unique references orders(id) on delete cascade,
  amount_paise integer not null check (amount_paise > 0),
  reason text not null,
  status text not null default 'pending'
    check (status in ('pending', 'sending', 'processed', 'failed')),
  razorpay_refund_id text,
  created_at timestamptz not null,
  updated_at timestamptz not null
);
create table payouts (
  id uuid primary key,
  account text not null,
  amount_paise integer not null check (amount_paise > 0),
  reference text not null,
  paid_by uuid not null references users(id),
  is_demo boolean not null,
  paid_at timestamptz not null,
  unique (account, reference)
);
create table ledger_entries (
  id bigserial primary key,
  account text not null,
  kind text not null check (kind in ('sale', 'fee', 'delivery', 'delivery_margin', 'refund',
                                     'payout')),
  amount_paise integer not null,
  order_id uuid references orders(id) on delete cascade,
  payout_id uuid references payouts(id) on delete cascade,
  is_demo boolean not null,
  created_at timestamptz not null
);
create index ledger_account_idx on ledger_entries (account, is_demo, created_at desc);
create unique index ledger_once_per_order on ledger_entries (order_id, kind)
  where order_id is not null
"""

DOWNGRADE = """
drop table if exists ledger_entries;
drop table if exists payouts;
drop table if exists refunds
"""


def _run(sql: str) -> None:
    for statement in sql.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run(UPGRADE)


def downgrade() -> None:
    _run(DOWNGRADE)
