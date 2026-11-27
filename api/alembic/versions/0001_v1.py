"""v1 schema (06 §A): PostGIS, users / sessions / addresses, restaurants + menu, riders + positions
+ track, orders + items + events (the bus) + legs, webhook events.

Revision ID: 0001_v1
Revises:
"""

from alembic import op

revision = "0001_v1"
down_revision = None
branch_labels = None
depends_on = None

UPGRADE = """
create extension if not exists postgis;
create extension if not exists citext;

create type user_role    as enum ('customer','restaurant','rider','admin');
create type rider_status as enum ('offline','available','busy');
create type order_status as enum ('pending_payment','placed','accepted','preparing','ready',
                                  'picked_up','delivered','rejected','cancelled','expired');
create type payment_kind as enum ('cod','razorpay');
create type leg_kind     as enum ('to_restaurant','to_customer');
create type route_method as enum ('osrm','line');

create table users (
  id uuid primary key,
  email citext not null unique,
  password_hash text,
  name text not null,
  phone text,
  role user_role not null default 'customer',
  created_at timestamptz not null default now()
);

create table sessions (
  id text primary key,
  user_id uuid not null references users(id) on delete cascade,
  expires_at timestamptz not null,
  created_at timestamptz not null default now()
);
create index sessions_user_id_idx on sessions (user_id);

create table addresses (
  id uuid primary key,
  user_id uuid not null references users(id) on delete cascade,
  label text not null,
  line text not null,
  loc geography(point, 4326) not null,
  created_at timestamptz not null default now()
);
create index addresses_user_id_idx on addresses (user_id);

create table restaurants (
  id uuid primary key,
  owner_user_id uuid not null unique references users(id),
  slug citext not null unique,
  name text not null,
  area text not null,
  cuisines text[] not null default '{}',
  is_veg boolean not null default false,
  loc geography(point, 4326) not null,
  address text not null,
  prep_min int not null default 15,
  hours jsonb not null default '{}',
  is_open boolean not null default true,
  cover_url text,
  rating numeric(2,1),
  board_seen_at timestamptz,
  created_at timestamptz not null default now()
);
create index restaurants_loc_gist on restaurants using gist (loc);

create table menu_categories (
  id uuid primary key,
  restaurant_id uuid not null references restaurants(id) on delete cascade,
  name text not null,
  sort int not null default 0
);
create index menu_categories_restaurant_sort_idx on menu_categories (restaurant_id, sort);

create table menu_items (
  id uuid primary key,
  restaurant_id uuid not null references restaurants(id) on delete cascade,
  category_id uuid not null references menu_categories(id) on delete cascade,
  name text not null,
  description text,
  price_paise int not null check (price_paise > 0),
  is_veg boolean not null,
  photo_url text,
  is_available boolean not null default true,
  sort int not null default 0
);
create index menu_items_restaurant_cat_sort_idx on menu_items (restaurant_id, category_id, sort);

create table riders (
  id uuid primary key,
  user_id uuid not null unique references users(id),
  name text not null,
  phone text not null,
  vehicle text not null,
  is_sim boolean not null default false,
  status rider_status not null default 'available',
  speed_kmh numeric(4,1) not null default 22.0,
  created_at timestamptz not null default now()
);
create index riders_status_idx on riders (status);

create table rider_positions (
  rider_id uuid primary key references riders(id) on delete cascade,
  loc geography(point, 4326) not null,
  heading smallint,
  speed_mps numeric(5,2),
  recorded_at timestamptz not null,
  client_at timestamptz
);
create index rider_positions_loc_gist on rider_positions using gist (loc);

create sequence order_number_seq start 1001;

create table orders (
  id uuid primary key,
  number text not null unique,
  user_id uuid not null references users(id),
  restaurant_id uuid not null references restaurants(id),
  rider_id uuid references riders(id),
  status order_status not null,
  payment payment_kind not null,
  address_line text not null,
  drop_loc geography(point, 4326) not null,
  subtotal_paise int not null,
  delivery_fee_paise int not null,
  platform_fee_paise int not null,
  total_paise int not null,
  distance_m int not null,
  route_method route_method not null,
  eta_s int,
  note text,
  razorpay_order_id text unique,
  razorpay_payment_id text,
  reject_reason text,
  created_at timestamptz not null default now(),
  placed_at timestamptz, accepted_at timestamptz, preparing_at timestamptz, ready_at timestamptz,
  picked_up_at timestamptz, delivered_at timestamptz, rejected_at timestamptz,
  cancelled_at timestamptz, expired_at timestamptz
);
create index orders_user_created_idx on orders (user_id, created_at desc);
create index orders_restaurant_status_idx on orders (restaurant_id, status);
create index orders_rider_idx on orders (rider_id) where rider_id is not null;
create index orders_waiting_idx on orders (status, accepted_at) where rider_id is null;

create table order_items (
  id uuid primary key,
  order_id uuid not null references orders(id) on delete cascade,
  menu_item_id uuid references menu_items(id) on delete set null,
  name text not null,
  price_paise int not null,
  qty int not null check (qty > 0),
  is_veg boolean not null
);
create index order_items_order_idx on order_items (order_id);

create table order_events (
  seq bigserial primary key,
  order_id uuid not null references orders(id) on delete cascade,
  kind text not null,
  actor_role text not null,
  actor_id uuid,
  payload jsonb not null default '{}',
  at timestamptz not null default now()
);
create index order_events_order_seq_idx on order_events (order_id, seq);

create table rider_legs (
  id uuid primary key,
  order_id uuid not null references orders(id) on delete cascade,
  rider_id uuid not null references riders(id) on delete cascade,
  kind leg_kind not null,
  polyline text not null,
  distance_m int not null,
  duration_s int not null,
  method route_method not null,
  started_at timestamptz not null,
  arrived_at timestamptz,
  ended_at timestamptz
);
create index rider_legs_open_idx on rider_legs (rider_id) where ended_at is null;
create index rider_legs_order_idx on rider_legs (order_id);

create table rider_track (
  id bigserial primary key,
  order_id uuid not null references orders(id) on delete cascade,
  rider_id uuid not null references riders(id) on delete cascade,
  at timestamptz not null,
  loc geography(point, 4326) not null
);
create index rider_track_order_at_idx on rider_track (order_id, at);

create table webhook_events (
  id text primary key,
  event text not null,
  received_at timestamptz not null default now()
);
"""

DOWNGRADE = """
drop table if exists webhook_events, rider_track, rider_legs, order_events, order_items, orders,
  rider_positions, riders, menu_items, menu_categories, restaurants, addresses, sessions, users
  cascade;
drop sequence if exists order_number_seq;
drop type if exists route_method, leg_kind, payment_kind, order_status, rider_status, user_role;
"""


def _run(sql: str) -> None:
    # asyncpg prepares each statement, so a script runs one statement at a time.
    for statement in sql.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run(UPGRADE)


def downgrade() -> None:
    _run(DOWNGRADE)
